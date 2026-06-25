#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================================
# plc_engine.py — generic PLC INTERPRETER for the TIA Web Practice IDE.
#
# This is the Raspberry Pi "fixed runtime": instead of generating Python from a
# program (see js/codegen.js) and re-running it, this module INTERPRETS the
# project data model directly. The program can therefore be swapped at runtime
# (online change) without restarting the process.
#
# Semantics are a faithful port of js/sim.js (the source of truth) using
# js/codegen.js as the per-instruction reference. In particular:
#   * Memory M is a dict keyed by tag NAME (or raw address / symbol), exactly
#     like codegen.js's resolveOp(). Block-local interface members are keyed
#     "<instance>.<member>".
#   * Numbers are coerced via num(); time literals (T#...) -> seconds.
#   * LAD rung power = AND over stages ( OR over branches ( AND over inline
#     element values ) ); an empty `stages` list => True (direct rail).
#   * FBD boxes are evaluated in topological (dependency) order; a wire into a
#     not-yet-computed pin uses the last-scan cached value (FBP) so latches /
#     feedback work.
#   * Timer state uses an overridable now() (time.monotonic in seconds).
#
# Pure stdlib + optional gpiozero. Auto-falls back to a pure-Python mock backend
# when gpiozero is unavailable or mock=True is requested.
# ============================================================================

import re
import time
from collections import defaultdict


# --------------------------------------------------------------------------
# Small value helpers (mirror codegen.js num()/idiv() and sim.js num())
# --------------------------------------------------------------------------
def num(v):
    """Coerce any memory value to a number. bool -> int; None/'' -> 0."""
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (int, float)):
        return v
    if v is None:
        return 0
    try:
        f = float(v)
        return int(f) if f.is_integer() else f
    except (TypeError, ValueError):
        return 0


def idiv(a, b):
    """Divide-by-zero-guarded division (mirrors codegen.js idiv / sim.js mathOp)."""
    b = num(b)
    return 0 if b == 0 else num(a) / b


def norm_x(mn, v, mx):
    """NORM_X: OUT = (VALUE-MIN)/(MAX-MIN); 0 if MAX==MIN. Not clamped (matches sim.js)."""
    mn = num(mn)
    mx = num(mx)
    d = mx - mn
    return 0 if d == 0 else (num(v) - mn) / d


def scale_x(mn, v, mx):
    """SCALE_X: OUT = VALUE*(MAX-MIN)+MIN (mirrors sim.js scaleX)."""
    mn = num(mn)
    mx = num(mx)
    return num(v) * (mx - mn) + mn


def _not_empty(s):
    return s is not None and str(s).strip() != ''


# IEC time literal "T#5s" / "T#1m30s" / "500ms" -> milliseconds (port of T.parseTime).
_TIME_RE = re.compile(r'(\d+(?:\.\d+)?)\s*(ms|s|m|h|d)', re.IGNORECASE)


def parse_time_ms(s):
    if s is None:
        return 0
    if isinstance(s, (int, float)) and not isinstance(s, bool):
        return s
    s = str(s).strip()
    if re.match(r'^\d+(\.\d+)?$', s):       # plain milliseconds
        return round(float(s))
    ms = 0.0
    matched = False
    body = re.sub(r'^t#', '', s, flags=re.IGNORECASE)
    for m in _TIME_RE.finditer(body):
        matched = True
        v = float(m.group(1))
        unit = m.group(2).lower()
        ms += v * {'ms': 1, 's': 1000, 'm': 60000, 'h': 3600000, 'd': 86400000}[unit]
    if matched:
        return round(ms)
    try:
        return float(body)
    except ValueError:
        return 0


def parse_time_s(s):
    """Time literal -> seconds (codegen.js uses seconds for the PT argument)."""
    return parse_time_ms(s) / 1000.0


# Numeric comparison by operator string (mirrors sim.js cmp()).
def _cmp(op, a, b):
    return {
        '==': a == b, '<>': a != b,
        '>':  a > b,  '<':  a < b,
        '>=': a >= b, '<=': a <= b,
    }.get(op, False)


# --------------------------------------------------------------------------
# I/O backends
# --------------------------------------------------------------------------
class _MockPin:
    """Dependency-free stand-in for a gpiozero device (mirrors codegen _MockPin)."""
    def __init__(self, v=False):
        self._v = bool(v)

    @property
    def value(self):
        return self._v

    @value.setter
    def value(self, v):
        self._v = bool(v)


class _MockAnalog:
    """Float-capable stand-in for a gpiozero PWMOutputDevice (duty 0.0..1.0).
    Mirrors codegen.js _MockAnalog. The plain _MockPin coerces to bool, which
    would destroy PWM duty values, so analog outputs need this float backend."""
    def __init__(self, v=0.0):
        self._v = float(v)

    @property
    def value(self):
        return self._v

    @value.setter
    def value(self, v):
        self._v = float(v)


# --------------------------------------------------------------------------
# Engine
# --------------------------------------------------------------------------
class Engine:
    """Interprets a TIA-Web project (LAD/FBD), drives GPIO, exposes live state.

    Public API:
        Engine(project=None, mock=False)
        set_program(project)      load/replace program, reset state, rebuild GPIO
        scan()                    run exactly one PLC scan (no I/O)
        read_inputs()             GPIO inputs -> M
        write_outputs()           M -> GPIO outputs
        force(key, value)         set M[key] = value
        snapshot()                -> dict for monitoring
        now()                     overridable clock (seconds); set _clock to override

    Attributes:
        M       memory dict (tag name / address / symbol -> value)
        live    {element_id: bool}   per-element energized flag (sim.js _live)
        power   {network_id: bool}   per-LAD-network rung power (sim.js net._power)
        pinval  {pin_id: bool}       per-FBD-pin value (sim.js pin._val)
        scan_count  number of scans executed since the program was loaded
    """

    def __init__(self, project=None, mock=False):
        self.mock = bool(mock)
        self._clock = None            # override: set to a float to freeze now()
        self._reset_runtime_state()
        self.project = None
        self.set_program(project)

    # ---- clock (overridable for deterministic testing) --------------------
    def now(self):
        return self._clock if self._clock is not None else time.monotonic()

    # ---- (re)initialise everything that is per-program ---------------------
    def _reset_runtime_state(self):
        self.M = defaultdict(int)     # memory: keyed by tag name / address / symbol
        self.ST = {}                  # timer/counter/edge instance state, keyed by element/box id
        self.FBP = {}                 # FBD cross-scan pin cache (feedback / latches), key "box|pin"
        self.live = {}                # element_id -> bool
        self.power = {}               # network_id -> bool
        self.pinval = {}              # pin_id -> bool
        self.scan_count = 0
        self._scope = None            # active block-local member scope (member-name lc -> key)

    # =======================================================================
    #  Program loading
    # =======================================================================
    def set_program(self, project):
        """Load or replace the running program. Resets all state, seeds memory
        with declared tags, and (re)builds the GPIO backend from project['gpio']."""
        self._reset_runtime_state()
        self.project = project or None
        # scan cycle time (s) requested by the program; the server loop paces to this
        try:
            self.scan_s = max(0.001, float((project or {}).get('scanMs', 50)) / 1000.0)
        except (TypeError, ValueError):
            self.scan_s = 0.05
        # index blocks by id and by name for fast call resolution
        self._blocks_by_id = {}
        self._blocks_by_name = {}
        if self.project:
            for b in (self.project.get('blocks') or []):
                self._blocks_by_id[b.get('id')] = b
                self._blocks_by_name[b.get('name')] = b
            self._seed_memory()
            self._build_gpio()
        else:
            self._tags = []
            self.inputs = {}
            self.outputs = {}
            self.pwms = {}
        return {'ok': True}

    def _seed_memory(self):
        """Initialise M with every declared tag by its NAME (bool->False, num->0).
        Matches codegen.js collectKeys() which keys by tag name."""
        self._tags = list(self.project.get('tags') or [])
        for t in self._tags:
            name = t.get('name')
            if not _not_empty(name):
                continue
            if t.get('dataType') == 'Bool':
                self.M[name] = False
            else:
                self.M[name] = 0

    # ---- block lookups (codegen.js T.findBlock equivalents) ---------------
    def _find_block(self, ref):
        """Resolve a block reference (id preferred, then name)."""
        if ref is None:
            return None
        return self._blocks_by_id.get(ref) or self._blocks_by_name.get(ref)

    # =======================================================================
    #  GPIO backend (gpiozero on a Pi, pure-Python mock otherwise)
    # =======================================================================
    def _build_gpio(self):
        """Build input/output pin devices from project['gpio'] (mirrors codegen.js
        gpioMap()). Inputs = dir 'in' (or area I); outputs = dir 'out' (or area Q).
        Unmapped tags simply stay internal memory in M."""
        self.inputs = {}     # tag name -> device with .value (digital input)
        self.outputs = {}    # tag name -> device with .value (digital output)
        self.pwms = {}       # tag name -> device with float .value (analog/PWM output)
        gmap = self.project.get('gpio') if self.project else None
        if not isinstance(gmap, list):
            gmap = []
        tag_by_name = {t.get('name'): t for t in self._tags}

        # Decide once whether we can use real gpiozero.
        use_real = not self.mock and self._gpiozero_available()

        for m in gmap:
            bcm = m.get('bcm')
            if bcm is None or bcm == '':
                continue
            tag = m.get('tag')
            tagdef = tag_by_name.get(tag) or {}
            addr = (tagdef.get('address') or '')
            # direction: explicit dir, else infer from address area (I -> in, Q -> out)
            direction = m.get('dir')
            if not direction:
                if re.match(r'^I', addr, re.IGNORECASE):
                    direction = 'in'
                elif re.match(r'^Q', addr, re.IGNORECASE):
                    direction = 'out'
                else:
                    direction = 'out'
            pull = m.get('pull') or 'down'
            active_low = bool(m.get('activeLow'))
            try:
                if direction == 'pwm':
                    freq = m.get('freq')
                    freq = 100 if (freq is None or freq == '') else int(freq)
                    self.pwms[tag] = self._make_pwm(bcm, freq, use_real)
                elif direction == 'in':
                    self.inputs[tag] = self._make_input(bcm, pull, active_low, use_real)
                else:
                    self.outputs[tag] = self._make_output(bcm, active_low, use_real)
            except Exception:
                # any hardware-init failure -> fall back to a mock device for this tag
                if direction == 'pwm':
                    self.pwms[tag] = _MockAnalog(0.0)
                elif direction == 'in':
                    self.inputs[tag] = _MockPin(False)
                else:
                    self.outputs[tag] = _MockPin(False)

    @staticmethod
    def _gpiozero_available():
        try:
            import gpiozero  # noqa: F401
            return True
        except Exception:
            return False

    def _make_input(self, bcm, pull, active_low, use_real):
        if not use_real:
            return _MockPin(False)
        from gpiozero import DigitalInputDevice
        # active_state is only valid when there is no pull resistor (pull == 'none')
        active_state = ((not active_low) if pull == 'none' else None)
        return DigitalInputDevice(bcm, pull_up=(pull == 'up'), active_state=active_state)

    def _make_output(self, bcm, active_low, use_real):
        if not use_real:
            return _MockPin(False)
        from gpiozero import DigitalOutputDevice
        return DigitalOutputDevice(bcm, active_high=(not active_low))

    def _make_pwm(self, bcm, freq, use_real):
        if not use_real:
            return _MockAnalog(0.0)
        from gpiozero import PWMOutputDevice
        return PWMOutputDevice(bcm, frequency=freq)

    def read_inputs(self):
        """Read every mapped GPIO input into M (by tag name)."""
        for tag, dev in self.inputs.items():
            self.M[tag] = bool(dev.value)

    def write_outputs(self):
        """Write M (by tag name) to every mapped GPIO output. Digital outputs
        take the bool; PWM (analog) outputs take the tag's number clamped to
        [0.0, 1.0] as a duty cycle (mirrors codegen.js write_outputs())."""
        for tag, dev in self.outputs.items():
            dev.value = bool(self.M[tag])
        for tag, dev in self.pwms.items():
            dev.value = max(0.0, min(1.0, float(num(self.M[tag]))))

    # =======================================================================
    #  Operand resolution (port of codegen.js resolveOp / rd / wt)
    #  A resolved operand is one of:
    #     ('lit', value)   constant literal (number / bool / seconds)
    #     ('key', key)     a memory key in M (tag name / address / symbol /
    #                      "<instance>.<member>" for a block-local member)
    # =======================================================================
    def _resolve(self, op, ctx):
        raw = '' if op is None else str(op).strip()
        if raw == '':
            return ('lit', False)
        if re.match(r'^-?\d+(\.\d+)?$', raw):
            f = float(raw)
            return ('lit', int(f) if f.is_integer() else f)
        if re.match(r'^(true|false)$', raw, re.IGNORECASE):
            return ('lit', raw.lower() == 'true')
        if re.match(r'^t#', raw, re.IGNORECASE):
            return ('lit', parse_time_s(raw))      # time literal -> seconds
        # block-local interface member (shadows global tags), keyed "<inst>.<member>"
        if ctx and ctx.get('members') and raw.lower() in ctx['members']:
            member_name = ctx['members'][raw.lower()]
            return ('key', ctx['inst'] + '.' + member_name)
        # tag name (or any unknown symbol / raw address) keyed directly
        return ('key', raw)

    def _rd(self, op, ctx):
        """Read an operand's raw stored value."""
        kind, val = self._resolve(op, ctx)
        if kind == 'lit':
            return val
        return self.M[val]

    def _rd_bool(self, op, ctx):
        return bool(self._rd(op, ctx))

    def _rd_num(self, op, ctx):
        return num(self._rd(op, ctx))

    def _secs(self, op, ctx):
        """Resolve a PT operand to seconds: literal (already seconds) or num(value)."""
        kind, val = self._resolve(op, ctx)
        if kind == 'lit':
            return val
        return num(self.M[val])

    def _wkey(self, op, ctx):
        """L-value memory key for writing an operand, or None if not writable."""
        kind, val = self._resolve(op, ctx)
        if kind == 'key':
            return val
        return None

    def _write(self, op, ctx, value):
        k = self._wkey(op, ctx)
        if k is not None:
            self.M[k] = value

    # =======================================================================
    #  Timer / counter / edge / latch primitives (port of codegen.js helpers)
    #  Timers use seconds; PT is supplied in seconds.
    # =======================================================================
    def _ton(self, i, inp, pt):
        s = self.ST.setdefault(i, {'t0': None})
        if inp:
            if s['t0'] is None:
                s['t0'] = self.now()
            return (self.now() - s['t0']) >= pt
        s['t0'] = None
        return False

    def _tof(self, i, inp, pt):
        s = self.ST.setdefault(i, {'t0': None, 'prev': False})
        if inp:
            s['t0'] = None
            q = True
        else:
            if s['prev'] and s['t0'] is None:
                s['t0'] = self.now()
            q = (s['t0'] is not None) and ((self.now() - s['t0']) < pt)
        s['prev'] = inp
        return q

    def _tp(self, i, inp, pt):
        s = self.ST.setdefault(i, {'t0': None, 'prev': False})
        if inp and not s['prev'] and s['t0'] is None:
            s['t0'] = self.now()
        q = False
        if s['t0'] is not None:
            if (self.now() - s['t0']) < pt:
                q = True
            elif not inp:
                s['t0'] = None
        s['prev'] = inp
        return q

    def _ctu(self, i, cu, pv, reset):
        s = self.ST.setdefault(i, {'c': 0, 'prev': False})
        if reset:
            s['c'] = 0
        elif cu and not s['prev']:
            s['c'] += 1
        s['prev'] = cu
        return (s['c'] >= pv, s['c'])

    def _ctd(self, i, cd, pv, load):
        s = self.ST.setdefault(i, {'c': pv, 'prev': False})
        if load:
            s['c'] = pv
        elif cd and not s['prev']:
            s['c'] -= 1
        s['prev'] = cd
        return (s['c'] <= 0, s['c'])

    def _redge(self, i, clk):
        s = self.ST.setdefault(i, {'p': False})
        q = clk and not s['p']
        s['p'] = clk
        return q

    def _fedge(self, i, clk):
        s = self.ST.setdefault(i, {'p': False})
        q = (not clk) and s['p']
        s['p'] = clk
        return q

    @staticmethod
    def _sr(cur, s_in, r_in):      # reset dominant
        return False if r_in else (True if s_in else cur)

    @staticmethod
    def _rs(cur, r_in, s_in):      # set dominant
        return True if s_in else (False if r_in else cur)

    # =======================================================================
    #  LAD evaluation
    # =======================================================================
    def _inline_value(self, el, ctx):
        """Inline (contact-area) element value; records el._live in self.live."""
        kind = el.get('kind')
        if kind == 'contact_no':
            v = self._rd_bool(el.get('operand'), ctx)
        elif kind == 'contact_nc':
            v = not self._rd_bool(el.get('operand'), ctx)
        elif kind == 'edge_p':
            v = self._redge(el.get('id'), self._rd_bool(el.get('operand'), ctx))
        elif kind == 'edge_n':
            v = self._fedge(el.get('id'), self._rd_bool(el.get('operand'), ctx))
        elif kind == 'compare':
            p = el.get('params') or {}
            v = _cmp(p.get('op') or '==',
                     self._rd_num(p.get('in1'), ctx),
                     self._rd_num(p.get('in2'), ctx))
        else:
            v = True
        self.live[el.get('id')] = bool(v)
        return bool(v)

    def _rung_power(self, net, ctx):
        """AND over stages ( OR over branches ( AND over inline element values ) ).
        Empty stages => True. Every element is evaluated so each gets its _live."""
        stages = net.get('stages') or []
        if not stages:
            return True
        rung = True
        for st in stages:
            branches = st.get('branches') or []
            if not branches:
                stage_val = True          # a stage with no branches passes power
            else:
                stage_val = False
                for br in branches:
                    els = br.get('elements') or []
                    bval = True
                    for e in els:
                        # evaluate EVERY element (so each gets _live) even after a False
                        if not self._inline_value(e, ctx):
                            bval = False
                    if bval:
                        stage_val = True
            if not stage_val:
                rung = False
        return rung

    def _apply_output(self, el, p, ctx):
        """Apply one output-area element with rung power p. Records el._live."""
        k = el.get('kind')
        par = el.get('params') or {}
        eid = el.get('id')

        if k == 'coil':
            self._write(el.get('operand'), ctx, p)
            self.live[eid] = bool(p)
        elif k == 'coil_neg':
            self._write(el.get('operand'), ctx, (not p))
            self.live[eid] = bool(p)
        elif k == 'coil_set':
            if p:
                self._write(el.get('operand'), ctx, True)
            self.live[eid] = bool(p)
        elif k == 'coil_reset':
            if p:
                self._write(el.get('operand'), ctx, False)
            self.live[eid] = bool(p)

        elif k == 'ton':
            self._set_q(par.get('q'), ctx, self._ton(eid, p, self._secs(par.get('pt'), ctx)))
            self.live[eid] = bool(p)
        elif k == 'tof':
            self._set_q(par.get('q'), ctx, self._tof(eid, p, self._secs(par.get('pt'), ctx)))
            self.live[eid] = bool(p)
        elif k == 'tp':
            self._set_q(par.get('q'), ctx, self._tp(eid, p, self._secs(par.get('pt'), ctx)))
            self.live[eid] = bool(p)

        elif k == 'ctu':
            q, cv = self._ctu(eid, p, self._rd_num(par.get('pv'), ctx),
                              self._rd_bool(par.get('r') or '', ctx))
            if _not_empty(par.get('cv')):
                self._write(par.get('cv'), ctx, cv)
            if _not_empty(par.get('q')):
                self._write(par.get('q'), ctx, q)
            self.live[eid] = bool(p)
        elif k == 'ctd':
            q, cv = self._ctd(eid, p, self._rd_num(par.get('pv'), ctx),
                              self._rd_bool(par.get('r') or '', ctx))
            if _not_empty(par.get('cv')):
                self._write(par.get('cv'), ctx, cv)
            if _not_empty(par.get('q')):
                self._write(par.get('q'), ctx, q)
            self.live[eid] = bool(p)

        elif k == 'move':
            if p:
                self._write(par.get('out'), ctx, self._rd_num(par.get('in'), ctx))
            self.live[eid] = bool(p)
        elif k in ('add', 'sub', 'mul', 'div'):
            if p:
                self._write(par.get('out'), ctx,
                            self._math(k, self._rd_num(par.get('in1'), ctx),
                                       self._rd_num(par.get('in2'), ctx)))
            self.live[eid] = bool(p)

        elif k == 'norm_x':
            if p:
                self._write(par.get('out'), ctx,
                            norm_x(self._rd_num(par.get('min'), ctx),
                                   self._rd_num(par.get('val'), ctx),
                                   self._rd_num(par.get('max'), ctx)))
            self.live[eid] = bool(p)
        elif k == 'scale_x':
            if p:
                self._write(par.get('out'), ctx,
                            scale_x(self._rd_num(par.get('min'), ctx),
                                    self._rd_num(par.get('val'), ctx),
                                    self._rd_num(par.get('max'), ctx)))
            self.live[eid] = bool(p)

        elif k == 'sr':                     # reset dominant; operand stores Q
            cur = self._rd_bool(el.get('operand'), ctx)
            q = self._sr(cur, p, self._rd_bool(par.get('r') or '', ctx))
            self._write(el.get('operand'), ctx, q)
            self.live[eid] = bool(q)
        elif k == 'rs':                     # set dominant; operand stores Q
            cur = self._rd_bool(el.get('operand'), ctx)
            q = self._rs(cur, p, self._rd_bool(par.get('s') or '', ctx))
            self._write(el.get('operand'), ctx, q)
            self.live[eid] = bool(q)

        elif k in ('p_trig', 'r_trig'):
            q = self._redge(eid, p)
            self._set_q(par.get('q'), ctx, q)
            self.live[eid] = bool(q)
        elif k in ('n_trig', 'f_trig'):
            q = self._fedge(eid, p)
            self._set_q(par.get('q'), ctx, q)
            self.live[eid] = bool(q)

        elif k == 'call':
            self.live[eid] = bool(p)
            if p:
                self._call_lad(el, ctx)
        else:
            self.live[eid] = bool(p)

    def _set_q(self, op, ctx, value):
        """Write a Q result to operand if set; the result is discarded otherwise
        (the helper already advanced state). Mirrors codegen.js setQ()."""
        if _not_empty(op):
            self._write(op, ctx, value)
        return value

    @staticmethod
    def _math(k, a, b):
        a = num(a)
        b = num(b)
        if k == 'add':
            return a + b
        if k == 'sub':
            return a - b
        if k == 'mul':
            return a * b
        if k == 'div':
            return idiv(a, b)
        return 0

    def _eval_lad_network(self, net, ctx):
        p = self._rung_power(net, ctx)
        self.power[net.get('id')] = bool(p)
        for el in (net.get('outputs') or []):
            self._apply_output(el, p, ctx)

    # ---- LAD block call ---------------------------------------------------
    def _call_lad(self, el, ctx):
        """Execute a call element: copy wired args into the callee instance,
        run it, copy outputs back (mirrors codegen.js callLines for LAD)."""
        params = el.get('params') or {}
        tb = self._find_block(params.get('target'))
        if not tb:
            return
        inst = self._instance_id(el, tb, params)
        args = el.get('args') or {}
        # copy inputs into instance member storage ("<inst>.<member>")
        for m in self._iface_call_inputs(tb):
            a = args.get(m.get('name'))
            if _not_empty(a):
                self.M[inst + '.' + m.get('name')] = self._rd(a, ctx)
        self._run_block(tb, inst)
        # copy outputs back to caller operands
        for m in self._iface_call_outputs(tb):
            a = args.get(m.get('name'))
            if _not_empty(a):
                self._write(a, ctx, self.M[inst + '.' + m.get('name')])

    # =======================================================================
    #  FBD evaluation (port of codegen.js fbdNetwork / fbdBox / topo)
    # =======================================================================
    def _eval_fbd_network(self, net, ctx):
        boxes = net.get('boxes') or []
        wires = net.get('wires') or []
        # wire lookup: "to_box|to_pin" -> {box, pin} source output
        src_of_input = {}
        for w in wires:
            to = w.get('to') or {}
            src_of_input[str(to.get('box')) + '|' + str(to.get('pin'))] = w.get('from')

        order = self._topo(boxes, wires)
        computed = {}                  # "box|pin" -> value for outputs computed this scan

        def in_expr(box, pin):
            """Resolve an input pin's value (wired source, else cached FBP, else operand)."""
            key = str(box.get('id')) + '|' + str(pin.get('id'))
            src = src_of_input.get(key)
            if src:
                skey = str(src.get('box')) + '|' + str(src.get('pin'))
                if skey in computed:
                    v = computed[skey]
                else:
                    v = self.FBP.get(skey, False)     # feedback / not yet computed
            else:
                v = self._rd(pin.get('operand'), ctx)
            if pin.get('inverted'):
                v = (not v)
            return v

        for box in order:
            ins = box.get('inputs') or []
            outs = box.get('outputs') or []
            in_vals = []
            for pin in ins:
                val = in_expr(box, pin)
                self.pinval[pin.get('id')] = bool(val)
                in_vals.append(val)
            out_vals = self._eval_fbd_box(box, in_vals, ctx)
            # store output pin values: into computed (this scan) and FBP (next scan)
            for i, pin in enumerate(outs):
                pv = out_vals[i] if i < len(out_vals) else False
                pkey = str(box.get('id')) + '|' + str(pin.get('id'))
                computed[pkey] = pv
                self.FBP[pkey] = pv
                self.pinval[pin.get('id')] = bool(pv)

    def _eval_fbd_box(self, box, in_e, ctx):
        """Evaluate one FBD box; return a list of output-pin values (in pin order).
        Mirrors codegen.js fbdBox / sim.js evalBox."""
        k = box.get('kind')
        p = box.get('params') or {}
        outs = box.get('outputs') or []
        n_out = len(outs)
        out_vals = [False] * max(n_out, 1)
        bid = box.get('id')
        live = False

        if k == 'fb_and':
            v = all(bool(e) for e in in_e) if in_e else False
            out_vals[0] = v
            live = v
        elif k == 'fb_or':
            v = any(bool(e) for e in in_e)
            out_vals[0] = v
            live = v
        elif k == 'fb_xor':
            acc = 0
            for e in in_e:
                acc ^= (1 if e else 0)
            v = (acc == 1)
            out_vals[0] = v
            live = v
        elif k == 'fb_not':
            v = (not (in_e[0] if in_e else False))
            out_vals[0] = v
            live = v
        elif k == 'assign':
            v = bool(in_e[0] if in_e else False)
            if _not_empty(box.get('operand')):
                self._write(box.get('operand'), ctx, v)
            out_vals[0] = v
            live = v
        elif k == 'compare':
            a = num(in_e[0] if len(in_e) > 0 else 0)
            b = num(in_e[1] if len(in_e) > 1 else 0)
            v = _cmp(p.get('op') or '==', a, b)
            out_vals[0] = v
            live = v
        elif k == 'ton':
            v = self._ton(bid, bool(in_e[0] if in_e else False), self._secs(p.get('pt'), ctx))
            out_vals[0] = v
            live = v
        elif k == 'tof':
            v = self._tof(bid, bool(in_e[0] if in_e else False), self._secs(p.get('pt'), ctx))
            out_vals[0] = v
            live = v
        elif k == 'tp':
            v = self._tp(bid, bool(in_e[0] if in_e else False), self._secs(p.get('pt'), ctx))
            out_vals[0] = v
            live = v
        elif k == 'ctu':
            q, cv = self._ctu(bid, bool(in_e[0] if in_e else False),
                              self._rd_num(p.get('pv'), ctx),
                              bool(in_e[1] if len(in_e) > 1 else False))
            out_vals[0] = q
            if n_out > 1:
                out_vals[1] = cv
            live = q
        elif k == 'ctd':
            q, cv = self._ctd(bid, bool(in_e[0] if in_e else False),
                              self._rd_num(p.get('pv'), ctx),
                              bool(in_e[1] if len(in_e) > 1 else False))
            out_vals[0] = q
            if n_out > 1:
                out_vals[1] = cv
            live = q
        elif k == 'move':
            v = num(in_e[0] if in_e else 0)
            if _not_empty(p.get('out')):
                self._write(p.get('out'), ctx, v)
            out_vals[0] = v
            live = True
        elif k in ('add', 'sub', 'mul', 'div'):
            a = num(in_e[0] if len(in_e) > 0 else 0)
            b = num(in_e[1] if len(in_e) > 1 else 0)
            v = self._math(k, a, b)
            if _not_empty(p.get('out')):
                self._write(p.get('out'), ctx, v)
            out_vals[0] = v
            live = True
        elif k in ('norm_x', 'scale_x'):
            mn = num(in_e[0] if len(in_e) > 0 else 0)   # MIN
            vl = num(in_e[1] if len(in_e) > 1 else 0)   # VALUE
            mx = num(in_e[2] if len(in_e) > 2 else 0)   # MAX
            v = norm_x(mn, vl, mx) if k == 'norm_x' else scale_x(mn, vl, mx)
            if _not_empty(p.get('out')):
                self._write(p.get('out'), ctx, v)
            out_vals[0] = v
            live = True
        elif k == 'sr':                 # reset dominant; in pins [S, R1]
            cur = (self._rd_bool(box.get('operand'), ctx) if _not_empty(box.get('operand'))
                   else self.FBP.get(str(bid) + '|q', False))
            q = self._sr(cur, bool(in_e[0] if in_e else False),
                         bool(in_e[1] if len(in_e) > 1 else False))
            if _not_empty(box.get('operand')):
                self._write(box.get('operand'), ctx, q)
            self.FBP[str(bid) + '|q'] = q
            out_vals[0] = q
            live = q
        elif k == 'rs':                 # set dominant; in pins [R, S1]
            cur = (self._rd_bool(box.get('operand'), ctx) if _not_empty(box.get('operand'))
                   else self.FBP.get(str(bid) + '|q', False))
            q = self._rs(cur, bool(in_e[0] if in_e else False),
                         bool(in_e[1] if len(in_e) > 1 else False))
            if _not_empty(box.get('operand')):
                self._write(box.get('operand'), ctx, q)
            self.FBP[str(bid) + '|q'] = q
            out_vals[0] = q
            live = q
        elif k in ('p_trig', 'r_trig'):
            q = self._redge(bid, bool(in_e[0] if in_e else False))
            if _not_empty(p.get('q')):
                self._write(p.get('q'), ctx, q)
            out_vals[0] = q
            live = q
        elif k in ('n_trig', 'f_trig'):
            q = self._fedge(bid, bool(in_e[0] if in_e else False))
            if _not_empty(p.get('q')):
                self._write(p.get('q'), ctx, q)
            out_vals[0] = q
            live = q
        elif k == 'call':
            en = bool(in_e[0] if in_e else False)
            out_vals = self._call_fbd(box, in_e, en, ctx)
            live = en
        else:
            out_vals[0] = (in_e[0] if in_e else False)
            live = bool(out_vals[0])

        self.live[bid] = bool(live)
        return out_vals

    def _call_fbd(self, box, in_e, en, ctx):
        """Execute an FBD call box. Returns output-pin values (ENO + members)."""
        params = box.get('params') or {}
        tb = self._find_block(params.get('target'))
        ins = box.get('inputs') or []
        outs = box.get('outputs') or []
        out_vals = [False] * len(outs)
        if not tb:
            if out_vals:
                out_vals[0] = en
            return out_vals
        inst = self._instance_id(box, tb, params)
        # copy member input pins (after EN) into instance storage
        in_names = {pp.get('name'): i for i, pp in enumerate(ins)}
        for m in self._iface_call_inputs(tb):
            idx = in_names.get(m.get('name'))
            if idx is not None and en:
                self.M[inst + '.' + m.get('name')] = in_e[idx]
        if en:
            self._run_block(tb, inst)
        # output pins reflect instance output members (held when EN is False)
        out_names = {pp.get('name'): i for i, pp in enumerate(outs)}
        for m in self._iface_call_outputs(tb):
            idx = out_names.get(m.get('name'))
            if idx is not None:
                out_vals[idx] = self.M[inst + '.' + m.get('name')]
        if outs:
            out_vals[0] = en          # ENO follows EN (first out pin)
        return out_vals

    @staticmethod
    def _topo(boxes, wires):
        """Topological order of boxes by wires; back-edges (cycles) are skipped
        (mirrors codegen.js topo())."""
        deps = {b.get('id'): set() for b in boxes}
        for w in wires:
            frm = w.get('from') or {}
            to = w.get('to') or {}
            tb = to.get('box')
            fb = frm.get('box')
            if tb in deps and fb != tb:
                deps[tb].add(fb)
        order = []
        placed = set()
        temp = set()
        by_id = {b.get('id'): b for b in boxes}

        def visit(bid):
            if bid in placed or bid in temp:
                return            # temp -> back edge, skip
            temp.add(bid)
            for d in list(deps.get(bid, ())):
                visit(d)
            temp.discard(bid)
            placed.add(bid)
            b = by_id.get(bid)
            if b is not None:
                order.append(b)

        for b in boxes:
            visit(b.get('id'))
        return order

    # =======================================================================
    #  Block execution (interface scope + call args)
    #  Members are keyed "<instance>.<member>" in M, matching codegen.js.
    # =======================================================================
    def _iface_sections(self, btype):
        if btype == 'FB':
            return ['input', 'output', 'inout', 'static', 'temp', 'constant']
        if btype == 'FC':
            return ['input', 'output', 'inout', 'temp', 'constant']
        return ['temp', 'constant']    # OB

    def _iface_members(self, blk):
        iface = blk.get('iface')
        if not iface:
            return []
        out = []
        for sec in self._iface_sections(blk.get('type')):
            for m in (iface.get(sec) or []):
                out.append(m)
        return out

    def _iface_call_inputs(self, blk):
        iface = blk.get('iface') or {}
        return list(iface.get('input') or []) + list(iface.get('inout') or [])

    def _iface_call_outputs(self, blk):
        iface = blk.get('iface') or {}
        return list(iface.get('output') or []) + list(iface.get('inout') or [])

    def _instance_id(self, node, target_block, params):
        """Instance name used to key member storage. Mirrors codegen.js:
        the instance-DB block's name if wired, else "<target>_<id-suffix>"."""
        inst_db = params.get('instanceDb')
        if _not_empty(inst_db):
            db = self._find_block(inst_db)
            if db and db.get('name'):
                return db.get('name')
        return (target_block.get('name') or 'blk') + '_' + str(node.get('id'))[-4:]

    def _block_ctx(self, blk, inst):
        """Build a per-block evaluation context: member-name (lowercase) -> member
        name, plus the instance id used to key "<inst>.<member>"."""
        members = {}
        for m in self._iface_members(blk):
            name = m.get('name')
            if name:
                members[name.lower()] = name
        return {'members': members, 'inst': inst}

    def _run_block(self, blk, inst):
        """Execute every network of a block under its own member context."""
        if not blk or blk.get('type') == 'DB':
            return
        ctx = self._block_ctx(blk, inst)
        lang = blk.get('lang')
        for net in (blk.get('networks') or []):
            if not net:
                continue
            try:
                if lang == 'FBD':
                    self._eval_fbd_network(net, ctx)
                else:
                    self._eval_lad_network(net, ctx)
            except Exception:
                # a bad network must not crash the whole scan (sim.js swallows too)
                pass

    # =======================================================================
    #  SCAN DRIVER (port of sim.js scanOnce / codegen.js scan)
    # =======================================================================
    def _collect_called(self):
        """Block ids/names referenced by any kind:'call' element/box."""
        called = set()
        if not self.project:
            return called
        for blk in (self.project.get('blocks') or []):
            for net in (blk.get('networks') or []):
                if not net:
                    continue
                for el in (net.get('outputs') or []):
                    if el.get('kind') == 'call':
                        tgt = (el.get('params') or {}).get('target')
                        if _not_empty(tgt):
                            called.add(tgt)
                for bx in (net.get('boxes') or []):
                    if bx.get('kind') == 'call':
                        tgt = (bx.get('params') or {}).get('target')
                        if _not_empty(tgt):
                            called.add(tgt)
        return called

    def scan(self):
        """Run exactly one PLC scan (no I/O). Mirrors sim.js scanOnce():
        run every OB (ascending number); enabled call elements run their target
        inline; then run any orphan FC/FB (never referenced by a call) once."""
        if not self.project:
            return
        blocks = self.project.get('blocks') or []

        def by_num(btype):
            return sorted((b for b in blocks if b.get('type') == btype),
                          key=lambda b: b.get('number') or 0)

        called = self._collect_called()

        # 1) every OB, ascending number
        for blk in by_num('OB'):
            self._run_block(blk, blk.get('name') or blk.get('id') or '')

        # 2) orphan FC/FB (never referenced by a call) run once, like the simulator
        for blk in by_num('FC') + by_num('FB'):
            ident = blk.get('id')
            name = blk.get('name')
            if ident not in called and name not in called:
                # orphan instance id mirrors codegen.js ("<name>_inst")
                self._run_block(blk, (name or 'blk') + '_inst')

        self.scan_count += 1

    # =======================================================================
    #  Monitoring / forcing
    # =======================================================================
    def force(self, key, value):
        """Set M[key] = value (input/memory forcing from the app). Booleans stay
        bool; numeric strings/numbers are coerced. For a GPIO-mapped INPUT running
        in mock mode, also drive the mock pin so read_inputs() keeps the forced
        value — this lets you test a program with no hardware. (Real GPIO inputs are
        driven by the physical pin and can't be forced, which is correct.)"""
        v = value
        if isinstance(value, str):
            low = value.strip().lower()
            if low in ('true', 'false'):
                v = (low == 'true')
            else:
                try:
                    f = float(value)
                    v = int(f) if f.is_integer() else f
                except ValueError:
                    v = value
        self.M[key] = v
        dev = self.inputs.get(key)
        if isinstance(dev, _MockPin):
            dev.value = bool(v)
        return {'ok': True}

    def snapshot(self, running=False):
        """Live state for the browser monitor. mem includes every project tag by
        name; live/power/pins are keyed by element/network/pin id (see class doc)."""
        mem = {}
        # every declared tag, by name, with current value (bool stays bool)
        for t in self._tags:
            name = t.get('name')
            if not _not_empty(name):
                continue
            v = self.M.get(name, False if t.get('dataType') == 'Bool' else 0)
            if t.get('dataType') == 'Bool':
                mem[name] = bool(v)
            else:
                mem[name] = num(v)
        # also surface any extra memory keys the program touched (members, symbols)
        for k, v in self.M.items():
            if k not in mem:
                mem[k] = (bool(v) if isinstance(v, bool) else v)
        return {
            'running': bool(running),
            'scan': self.scan_count,
            'mem': mem,
            'live': dict(self.live),
            'power': dict(self.power),
            'pins': dict(self.pinval),
        }


# Quick manual check when run directly (no hardware needed).
if __name__ == '__main__':
    eng = Engine(mock=True)
    print('plc_engine import OK; gpiozero available:', Engine._gpiozero_available())
