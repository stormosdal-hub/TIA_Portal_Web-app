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

import math
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


_ADDR_RE = re.compile(r'^[IQM](\d+\.\d+|W\d+|B\d+|D\d+)$', re.IGNORECASE)


def _in_param_key(kind, pin_name):
    """Map a box pin NAME -> params key (parity: sim.js inParamKey — an unwired
    numeric pin reads its box.params literal/operand, NOT pin.operand)."""
    table = {
        'compare': {'in1': 'in1', 'in2': 'in2'},
        'ton': {'PT': 'pt'}, 'tof': {'PT': 'pt'}, 'tp': {'PT': 'pt'},
        'ctu': {'PV': 'pv'}, 'ctd': {'PV': 'pv'},
        'move': {'IN': 'in'},
        'add': {'in1': 'in1', 'in2': 'in2'}, 'sub': {'in1': 'in1', 'in2': 'in2'},
        'mul': {'in1': 'in1', 'in2': 'in2'}, 'div': {'in1': 'in1', 'in2': 'in2'},
        'norm_x': {'MIN': 'min', 'VALUE': 'val', 'MAX': 'max'},
        'scale_x': {'MIN': 'min', 'VALUE': 'val', 'MAX': 'max'},
    }
    return table.get(kind, {}).get(pin_name)


# ==========================================================================
#  SCL (Structured Control Language) — tokenizer + parser.
#  A faithful port of js/scl.js (same AST shape, same precedence: NOT binds at
#  factor level, AND > XOR > OR, comparisons above add/mul). The evaluator
#  lives on Engine (it needs the operand layer / block context).
# ==========================================================================
class _SclError(Exception):
    def __init__(self, msg, line=0, col=0):
        super().__init__(msg)
        self.line = line
        self.col = col


_SCL_KW = {
    'IF', 'THEN', 'ELSIF', 'ELSE', 'END_IF',
    'CASE', 'OF', 'END_CASE',
    'FOR', 'TO', 'BY', 'DO', 'END_FOR',
    'WHILE', 'END_WHILE',
    'REPEAT', 'UNTIL', 'END_REPEAT',
    'EXIT', 'CONTINUE', 'RETURN',
    'AND', 'OR', 'XOR', 'NOT', 'MOD',
    'TRUE', 'FALSE',
}


def _scl_tokenize(src):
    toks = []
    i, line, col = 0, 1, 1
    n = len(src)
    state = {'i': 0, 'line': 1, 'col': 1}

    def err(msg):
        raise _SclError(msg, state['line'], state['col'])

    def adv(k):
        for _ in range(k):
            if state['i'] < n and src[state['i']] == '\n':
                state['line'] += 1
                state['col'] = 1
            else:
                state['col'] += 1
            state['i'] += 1

    while state['i'] < n:
        i = state['i']
        c = src[i]
        if c in ' \t\r\n':
            adv(1)
            continue
        if c == '/' and i + 1 < n and src[i + 1] == '/':          # line comment
            while state['i'] < n and src[state['i']] != '\n':
                adv(1)
            continue
        if c == '(' and i + 1 < n and src[i + 1] == '*':          # block comment
            adv(2)
            while state['i'] < n and not (src[state['i']] == '*'
                                          and state['i'] + 1 < n and src[state['i'] + 1] == ')'):
                adv(1)
            if state['i'] >= n:
                err('Unterminated (* comment *)')
            adv(2)
            continue
        sl, sc = state['line'], state['col']
        if c.isdigit():
            s = ''
            while state['i'] < n and src[state['i']].isdigit():
                s += src[state['i']]
                adv(1)
            # fractional part only when followed by a digit (keeps 1..5 ranges intact)
            if state['i'] < n and src[state['i']] == '.' \
                    and state['i'] + 1 < n and src[state['i'] + 1].isdigit():
                s += '.'
                adv(1)
                while state['i'] < n and src[state['i']].isdigit():
                    s += src[state['i']]
                    adv(1)
            v = float(s)
            v = int(v) if v.is_integer() else v
            toks.append({'t': 'num', 'v': v, 'line': sl, 'col': sc})
            continue
        if c.isalpha() or c == '_':
            s = ''
            while state['i'] < n and (src[state['i']].isalnum() or src[state['i']] == '_'):
                s += src[state['i']]
                adv(1)
            if state['i'] < n and src[state['i']] == '#':          # typed literal T#5s / INT#3
                rest = ''
                adv(1)
                while state['i'] < n and (src[state['i']].isalnum() or src[state['i']] in '_.'):
                    rest += src[state['i']]
                    adv(1)
                up = s.upper()
                if up in ('T', 'TIME'):
                    val = parse_time_ms('T#' + rest) or 0
                else:
                    try:
                        val = float(rest)
                    except ValueError:
                        val = 0.0
                    val = int(val) if float(val).is_integer() else val
                toks.append({'t': 'num', 'v': val, 'line': sl, 'col': sc})
                continue
            up = s.upper()
            if up in _SCL_KW:
                toks.append({'t': 'kw', 'v': up, 'line': sl, 'col': sc})
            else:
                toks.append({'t': 'id', 'v': s, 'line': sl, 'col': sc})
            continue
        two = src[i:i + 2]
        if two in (':=', '<=', '>=', '<>', '..'):
            toks.append({'t': 'op', 'v': two, 'line': sl, 'col': sc})
            adv(2)
            continue
        if c in '+-*/()<>=;:,.':
            toks.append({'t': 'op', 'v': c, 'line': sl, 'col': sc})
            adv(1)
            continue
        err('Unexpected character "%s"' % c)
    toks.append({'t': 'eof', 'v': '<eof>', 'line': state['line'], 'col': state['col']})
    return toks


def _scl_parse(src):
    toks = _scl_tokenize(src)
    p = [0]

    def peek():
        return toks[p[0]]

    def nxt():
        t = toks[p[0]]
        p[0] += 1
        return t

    def err(msg, tk=None):
        tk = tk or peek()
        raise _SclError(msg + ' near "%s"' % (tk['v'],), tk.get('line', 0), tk.get('col', 0))

    def is_op(v):
        t = peek()
        return t['t'] == 'op' and t['v'] == v

    def is_kw(v):
        t = peek()
        return t['t'] == 'kw' and t['v'] == v

    def eat_op(v):
        if not is_op(v):
            err('Expected "%s"' % v)
        return nxt()

    def eat_kw(v):
        if not is_kw(v):
            err('Expected %s' % v)
        return nxt()

    def accept_op(v):
        if is_op(v):
            nxt()
            return True
        return False

    def parse_stmts(stop):
        out = []
        while not stop():
            if peek()['t'] == 'eof':
                break
            if accept_op(';'):
                continue
            out.append(parse_stmt())
        return out

    def parse_stmt():
        t = peek()
        if t['t'] == 'kw':
            v = t['v']
            if v == 'IF':
                return parse_if()
            if v == 'CASE':
                return parse_case()
            if v == 'FOR':
                return parse_for()
            if v == 'WHILE':
                return parse_while()
            if v == 'REPEAT':
                return parse_repeat()
            if v == 'EXIT':
                nxt(); accept_op(';'); return {'n': 'exit'}
            if v == 'CONTINUE':
                nxt(); accept_op(';'); return {'n': 'continue'}
            if v == 'RETURN':
                nxt(); accept_op(';'); return {'n': 'return'}
        if t['t'] == 'id':
            name = parse_lvalue()
            eat_op(':=')
            e = parse_expr()
            accept_op(';')
            return {'n': 'assign', 'name': name, 'expr': e}
        err('Unexpected statement')

    def parse_lvalue():
        name = nxt()['v']
        while is_op('.'):
            nxt()
            if peek()['t'] != 'id':
                err('Expected member name')
            name += '.' + nxt()['v']
        return name

    def parse_if():
        eat_kw('IF')
        arms = []
        cond = parse_expr()
        eat_kw('THEN')
        body = parse_stmts(lambda: is_kw('ELSIF') or is_kw('ELSE') or is_kw('END_IF'))
        arms.append({'cond': cond, 'body': body})
        while is_kw('ELSIF'):
            nxt()
            cond = parse_expr()
            eat_kw('THEN')
            body = parse_stmts(lambda: is_kw('ELSIF') or is_kw('ELSE') or is_kw('END_IF'))
            arms.append({'cond': cond, 'body': body})
        els = None
        if is_kw('ELSE'):
            nxt()
            els = parse_stmts(lambda: is_kw('END_IF'))
        eat_kw('END_IF')
        accept_op(';')
        return {'n': 'if', 'arms': arms, 'els': els}

    def is_case_boundary():
        if is_kw('END_CASE') or is_kw('ELSE'):
            return True
        t = peek()
        if t['t'] != 'num' and not (t['t'] == 'op' and t['v'] == '-'):
            return False
        q = [p[0]]

        def skip_label():
            if toks[q[0]]['t'] == 'op' and toks[q[0]]['v'] == '-':
                q[0] += 1
            if toks[q[0]]['t'] != 'num':
                return False
            q[0] += 1
            if toks[q[0]]['t'] == 'op' and toks[q[0]]['v'] == '..':
                q[0] += 1
                if toks[q[0]]['t'] == 'op' and toks[q[0]]['v'] == '-':
                    q[0] += 1
                if toks[q[0]]['t'] != 'num':
                    return False
                q[0] += 1
            return True

        if not skip_label():
            return False
        while toks[q[0]]['t'] == 'op' and toks[q[0]]['v'] == ',':
            q[0] += 1
            if not skip_label():
                return False
        return toks[q[0]]['t'] == 'op' and toks[q[0]]['v'] == ':'

    def parse_signed_int():
        sign = 1
        if is_op('-'):
            nxt()
            sign = -1
        if peek()['t'] != 'num':
            err('Expected number in CASE label')
        return sign * nxt()['v']

    def parse_case_label():
        lo = parse_signed_int()
        if is_op('..'):
            nxt()
            hi = parse_signed_int()
            return {'lo': lo, 'hi': hi}
        return {'lo': lo, 'hi': lo}

    def parse_case():
        eat_kw('CASE')
        sel = parse_expr()
        eat_kw('OF')
        arms = []
        els = None
        while not is_kw('END_CASE') and not is_kw('ELSE'):
            labels = [parse_case_label()]
            while accept_op(','):
                labels.append(parse_case_label())
            eat_op(':')
            body = parse_stmts(is_case_boundary)
            arms.append({'labels': labels, 'body': body})
        if is_kw('ELSE'):
            nxt()
            els = parse_stmts(lambda: is_kw('END_CASE'))
        eat_kw('END_CASE')
        accept_op(';')
        return {'n': 'case', 'expr': sel, 'arms': arms, 'els': els}

    def parse_for():
        eat_kw('FOR')
        if peek()['t'] != 'id':
            err('Expected loop variable')
        v = parse_lvalue()
        eat_op(':=')
        frm = parse_expr()
        eat_kw('TO')
        to = parse_expr()
        by = None
        if is_kw('BY'):
            nxt()
            by = parse_expr()
        eat_kw('DO')
        body = parse_stmts(lambda: is_kw('END_FOR'))
        eat_kw('END_FOR')
        accept_op(';')
        return {'n': 'for', 'var': v, 'from': frm, 'to': to, 'by': by, 'body': body}

    def parse_while():
        eat_kw('WHILE')
        cond = parse_expr()
        eat_kw('DO')
        body = parse_stmts(lambda: is_kw('END_WHILE'))
        eat_kw('END_WHILE')
        accept_op(';')
        return {'n': 'while', 'cond': cond, 'body': body}

    def parse_repeat():
        eat_kw('REPEAT')
        body = parse_stmts(lambda: is_kw('UNTIL'))
        eat_kw('UNTIL')
        cond = parse_expr()
        eat_kw('END_REPEAT')
        accept_op(';')
        return {'n': 'repeat', 'body': body, 'cond': cond}

    def parse_expr():
        return parse_or()

    def parse_or():
        a = parse_xor()
        while is_kw('OR'):
            nxt()
            a = {'n': 'bin', 'op': 'OR', 'a': a, 'b': parse_xor()}
        return a

    def parse_xor():
        a = parse_and()
        while is_kw('XOR'):
            nxt()
            a = {'n': 'bin', 'op': 'XOR', 'a': a, 'b': parse_and()}
        return a

    def parse_and():
        a = parse_cmp()
        while is_kw('AND'):
            nxt()
            a = {'n': 'bin', 'op': 'AND', 'a': a, 'b': parse_cmp()}
        return a

    def parse_cmp():
        a = parse_add()
        while (is_op('=') or is_op('<>') or is_op('<') or is_op('>')
               or is_op('<=') or is_op('>=')):
            op = nxt()['v']
            a = {'n': 'bin', 'op': op, 'a': a, 'b': parse_add()}
        return a

    def parse_add():
        a = parse_mul()
        while is_op('+') or is_op('-'):
            op = nxt()['v']
            a = {'n': 'bin', 'op': op, 'a': a, 'b': parse_mul()}
        return a

    def parse_mul():
        a = parse_unary()
        while is_op('*') or is_op('/') or is_kw('MOD'):
            op = nxt()['v']
            a = {'n': 'bin', 'op': op, 'a': a, 'b': parse_unary()}
        return a

    def parse_unary():
        if is_kw('NOT'):
            nxt()
            return {'n': 'un', 'op': 'NOT', 'a': parse_unary()}
        if is_op('-'):
            nxt()
            return {'n': 'un', 'op': '-', 'a': parse_unary()}
        if is_op('+'):
            nxt()
            return parse_unary()
        return parse_primary()

    def parse_primary():
        t = peek()
        if t['t'] == 'num':
            nxt()
            return {'n': 'num', 'v': t['v']}
        if t['t'] == 'kw' and t['v'] in ('TRUE', 'FALSE'):
            nxt()
            return {'n': 'bool', 'v': t['v'] == 'TRUE'}
        if is_op('('):
            nxt()
            e = parse_expr()
            eat_op(')')
            return e
        if t['t'] == 'id':
            name = parse_lvalue()
            if is_op('('):
                nxt()
                args = []
                if not is_op(')'):
                    args.append(parse_expr())
                    while accept_op(','):
                        args.append(parse_expr())
                eat_op(')')
                return {'n': 'call', 'name': name, 'args': args}
            return {'n': 'var', 'name': name}
        err('Unexpected token in expression')

    body = parse_stmts(lambda: peek()['t'] == 'eof')
    if peek()['t'] != 'eof':
        err('Unexpected token')
    return {'n': 'block', 'body': body}


def _scl_num(v):
    if v is True:
        return 1
    if v is False:
        return 0
    return num(v)


def _scl_bool(v):
    if isinstance(v, bool):
        return v
    return _scl_num(v) != 0


def _scl_intify(x):
    """Collapse integral floats to int (JS numbers don't distinguish 3.0/3)."""
    if isinstance(x, float) and x.is_integer():
        return int(x)
    return x


def _js_round(x):
    """JS Math.round: half rounds toward +Infinity (Python round() is banker's)."""
    return math.floor(x + 0.5)


# built-in SCL functions (mirrors scl.js FUNCS)
_SCL_FUNCS = {
    'ABS': lambda a: abs(_scl_num(a[0])),
    'SQRT': lambda a: math.sqrt(_scl_num(a[0])),
    'SQR': lambda a: _scl_num(a[0]) * _scl_num(a[0]),
    'MIN': lambda a: min(_scl_num(x) for x in a),
    'MAX': lambda a: max(_scl_num(x) for x in a),
    'LIMIT': lambda a: max(_scl_num(a[0]), min(_scl_num(a[1]), _scl_num(a[2]))),
    'TRUNC': lambda a: math.trunc(_scl_num(a[0])),
    'ROUND': lambda a: _js_round(_scl_num(a[0])),
    'INT': lambda a: math.trunc(_scl_num(a[0])),
    'REAL': lambda a: _scl_num(a[0]),
    'LN': lambda a: math.log(_scl_num(a[0])),
    'EXP': lambda a: math.exp(_scl_num(a[0])),
    'SIN': lambda a: math.sin(_scl_num(a[0])),
    'COS': lambda a: math.cos(_scl_num(a[0])),
    'TAN': lambda a: math.tan(_scl_num(a[0])),
}

_SCL_MAX_ITER = 200000
_SCL_EXIT, _SCL_CONT, _SCL_RET = 'exit', 'continue', 'return'


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
        self.ST = {}                  # timer/counter/edge state, keyed "<inst>:<element id>"
        self.FBP = {}                 # FBD cross-scan pin cache (feedback / latches), key "<inst>:box|pin"
        self.live = {}                # element_id -> bool
        self.power = {}               # network_id -> bool
        self.pinval = {}              # pin_id -> bool
        self.scan_count = 0
        self._scope = None            # active block-local member scope (member-name lc -> key)
        self._alias = {}              # lowercase tag name / address -> canonical tag name
        self._tag_bits = set()        # lowercase names of Bool tags (SCL type resolution)
        self._callstack = set()       # re-entrant block-call guard (parity: sim.js _scanCtx.stack)
        self._scl_cache = {}          # block id -> (code, program|None, error|None)
        self.err_count = 0            # networks that raised during scan (see _run_block)
        self.last_error = None

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
        # SCL blocks run natively now — warn only when one fails to parse
        warnings = []
        if self.project:
            for b in (self.project.get('blocks') or []):
                if b.get('type') != 'DB' and b.get('lang') == 'SCL' and str(b.get('code') or '').strip():
                    _code, _prog, perr = self._scl_program(b)
                    if perr:
                        warnings.append('SCL block "%s": %s (block is skipped)'
                                        % (b.get('name') or '?', perr))
        return {'ok': True, 'warnings': warnings}

    def _seed_memory(self):
        """Initialise M with every declared tag by its NAME (bool->False, num->0).
        Matches codegen.js collectKeys() which keys by tag name. Also builds the
        alias table so an operand typed as the tag's ADDRESS ("I0.0", "%I0.0")
        or with different case hits the SAME cell that read_inputs() writes."""
        self._tags = list(self.project.get('tags') or [])
        self._alias = {}
        self._tag_bits = set()
        for t in self._tags:
            name = t.get('name')
            if not _not_empty(name):
                continue
            if t.get('dataType') == 'Bool':
                self.M[name] = False
                self._tag_bits.add(str(name).lower())
            else:
                self.M[name] = 0
            self._alias.setdefault(str(name).lower(), name)
            addr = str(t.get('address') or '').strip()
            if addr:
                self._alias.setdefault(addr.lower(), name)

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
                    deb = m.get('debounce')
                    bounce_s = (int(deb) / 1000.0) if deb not in (None, '', 0, '0') else None
                    self.inputs[tag] = self._make_input(bcm, pull, active_low, use_real, bounce_s)
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

    def _make_input(self, bcm, pull, active_low, use_real, bounce_s=None):
        if not use_real:
            return _MockPin(False)
        from gpiozero import DigitalInputDevice
        # active_state is only valid when there is no pull resistor (pull == 'none')
        active_state = ((not active_low) if pull == 'none' else None)
        return DigitalInputDevice(bcm, pull_up=(pull == 'up'), active_state=active_state,
                                  bounce_time=bounce_s)

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
        if raw.startswith('%'):                     # TIA absolute-address prefix
            raw = raw[1:].strip()
        if re.match(r'^-?\d+(\.\d+)?$', raw):
            f = float(raw)
            return ('lit', int(f) if f.is_integer() else f)
        if re.match(r'^(true|false)$', raw, re.IGNORECASE):
            return ('lit', raw.lower() == 'true')
        if re.match(r'^t#', raw, re.IGNORECASE):
            return ('lit', parse_time_ms(raw))      # time literal -> ms (app-native, sim parity)
        # block-local interface member (shadows global tags), keyed "<inst>.<member>"
        if ctx and ctx.get('members') and raw.lower() in ctx['members']:
            member_name = ctx['members'][raw.lower()]
            return ('key', ctx['inst'] + '.' + member_name)
        # tag aliasing: name (any case) or its address -> the canonical name cell
        alias = self._alias.get(raw.lower())
        if alias is not None:
            return ('key', alias)
        # bare address with no tag: normalise case so all its users share one cell
        if _ADDR_RE.match(raw):
            return ('key', raw.upper())
        # unknown symbol keyed directly
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

    def _ms(self, op, ctx):
        """Resolve a time operand to MILLISECONDS (the app's native unit): a
        plain number IS ms, T# literals parse to ms, a tag/member VALUE is ms.
        Parity: sim.js resolvePT. Never negative."""
        raw = '' if op is None else str(op).strip()
        if raw == '':
            return 0
        if re.match(r'^-?\d+(\.\d+)?$', raw):
            return max(0.0, float(raw))
        if re.match(r'^t#', raw, re.IGNORECASE):
            return max(0, parse_time_ms(raw))
        return max(0, num(self._rd(raw, ctx)))

    def _secs(self, op, ctx):
        """PT operand -> seconds (the timer primitives run on seconds)."""
        return self._ms(op, ctx) / 1000.0

    def _wkey(self, op, ctx):
        """L-value memory key for writing an operand, or None if not writable."""
        kind, val = self._resolve(op, ctx)
        if kind == 'key':
            return val
        return None

    def _write(self, op, ctx, value):
        k = self._wkey(op, ctx)
        if k is not None:
            # scrub non-finite numbers (a MUL overflow would poison memory AND
            # break the JSON snapshot; sim.js setWord does the same)
            if isinstance(value, float) and not math.isfinite(value):
                value = 0
            self.M[k] = value

    # =======================================================================
    #  Timer / counter / edge / latch primitives (port of codegen.js helpers)
    #  Timers use seconds; PT is supplied in seconds.
    # =======================================================================
    # Timers return (q, et_ms) — ET mirrors sim.js (milliseconds, clamped to PT).
    def _ton(self, i, inp, pt):
        s = self.ST.setdefault(i, {'t0': None})
        el = 0.0
        q = False
        if inp:
            if s['t0'] is None:
                s['t0'] = self.now()
            el = self.now() - s['t0']
            q = el >= pt
        else:
            s['t0'] = None
        return (q, min(el, pt) * 1000.0)

    def _tof(self, i, inp, pt):
        s = self.ST.setdefault(i, {'t0': None, 'prev': False})
        el = 0.0
        if inp:
            s['t0'] = None
            q = True
        else:
            if s['prev'] and s['t0'] is None:
                s['t0'] = self.now()
            if s['t0'] is not None:
                el = self.now() - s['t0']
                if el >= pt:
                    q = False
                    el = pt
                else:
                    q = True
            else:
                q = False
        s['prev'] = inp
        return (q, el * 1000.0)

    def _tp(self, i, inp, pt):
        s = self.ST.setdefault(i, {'t0': None, 'prev': False})
        q = False
        el = 0.0
        if inp and not s['prev'] and s['t0'] is None:
            s['t0'] = self.now()
        if s['t0'] is not None:
            el = self.now() - s['t0']
            if el < pt:
                q = True
            else:
                q = False
                el = pt
                if not inp:
                    s['t0'] = None
        s['prev'] = inp
        return (q, min(el, pt) * 1000.0)

    def _ctu(self, i, cu, pv, reset):
        s = self.ST.setdefault(i, {'c': 0, 'prev': False})
        if reset:
            s['c'] = 0
        elif cu and not s['prev']:
            s['c'] = min(s['c'] + 1, 32767)
        s['prev'] = cu
        return (s['c'] >= pv, s['c'])

    def _ctd(self, i, cd, pv, load):
        # IEC/S7: CV starts at 0 (Q true) until LD loads PV (sim.js parity)
        s = self.ST.setdefault(i, {'c': 0, 'prev': False})
        if load:
            s['c'] = pv
        elif cd and not s['prev']:
            s['c'] = max(s['c'] - 1, -32767)
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
    def _stid(self, ctx, eid):
        """Per-element state id, scoped by the executing instance so an FB's
        timers/counters/edges never share state between instances (sim.js inst())."""
        return (((ctx.get('inst') if ctx else '') or '')) + ':' + str(eid)

    def _inline_value(self, el, ctx):
        """Inline (contact-area) element value; records el._live in self.live."""
        kind = el.get('kind')
        if kind == 'contact_no':
            v = self._rd_bool(el.get('operand'), ctx)
        elif kind == 'contact_nc':
            v = not self._rd_bool(el.get('operand'), ctx)
        elif kind == 'edge_p':
            v = self._redge(self._stid(ctx, el.get('id')), self._rd_bool(el.get('operand'), ctx))
        elif kind == 'edge_n':
            v = self._fedge(self._stid(ctx, el.get('id')), self._rd_bool(el.get('operand'), ctx))
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
                # an empty branch is a bare wire only while the WHOLE stage is
                # empty; alongside a populated branch it is an unfinished
                # parallel arm and must not short the OR (sim.js parity)
                has_els = any((br.get('elements') or []) for br in branches)
                stage_val = False
                for br in branches:
                    els = br.get('elements') or []
                    bval = True
                    for e in els:
                        # evaluate EVERY element (so each gets _live) even after a False
                        if not self._inline_value(e, ctx):
                            bval = False
                    if bval and ((not has_els) or els):
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

        elif k in ('ton', 'tof', 'tp'):
            fn = {'ton': self._ton, 'tof': self._tof, 'tp': self._tp}[k]
            q, et = fn(self._stid(ctx, eid), p, self._secs(par.get('pt'), ctx))
            if _not_empty(par.get('q')):
                self._write(par.get('q'), ctx, q)
            if _not_empty(par.get('et')):
                self._write(par.get('et'), ctx, et)
            self.live[eid] = bool(p)

        elif k == 'ctu':
            q, cv = self._ctu(self._stid(ctx, eid), p, self._rd_num(par.get('pv'), ctx),
                              self._rd_bool(par.get('r') or '', ctx))
            if _not_empty(par.get('cv')):
                self._write(par.get('cv'), ctx, cv)
            if _not_empty(par.get('q')):
                self._write(par.get('q'), ctx, q)
            self.live[eid] = bool(p)
        elif k == 'ctd':
            q, cv = self._ctd(self._stid(ctx, eid), p, self._rd_num(par.get('pv'), ctx),
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
            q = self._redge(self._stid(ctx, eid), p)
            self._set_q(par.get('q'), ctx, q)
            self.live[eid] = bool(q)
        elif k in ('n_trig', 'f_trig'):
            q = self._fedge(self._stid(ctx, eid), p)
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
        inst = (ctx.get('inst') if ctx else '') or ''
        # wire lookup: "to_box|to_pin" -> {box, pin} source output
        src_of_input = {}
        for w in wires:
            to = w.get('to') or {}
            src_of_input[str(to.get('box')) + '|' + str(to.get('pin'))] = w.get('from')

        order = self._topo(boxes, wires)
        computed = {}                  # "box|pin" -> value for outputs computed this scan
        # FBP cache keys are instance-scoped (parity: sim.js pinKey)
        fbp_key = lambda b, p: inst + ':' + str(b) + '|' + str(p)

        def in_expr(box, pin):
            """Resolve an input pin's value (wired source, else cached FBP, else
            the box.params literal for numeric pins, else pin.operand)."""
            key = str(box.get('id')) + '|' + str(pin.get('id'))
            src = src_of_input.get(key)
            if src:
                skey = str(src.get('box')) + '|' + str(src.get('pin'))
                if skey in computed:
                    v = computed[skey]
                else:
                    v = self.FBP.get(fbp_key(src.get('box'), src.get('pin')), False)  # feedback
            else:
                pk = _in_param_key(box.get('kind'), pin.get('name'))
                if pk == 'pt':
                    v = self._ms((box.get('params') or {}).get(pk), ctx)   # PT: app-native ms
                elif pk:
                    v = self._rd_num((box.get('params') or {}).get(pk), ctx)
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
                computed[str(box.get('id')) + '|' + str(pin.get('id'))] = pv
                self.FBP[fbp_key(box.get('id'), pin.get('id'))] = pv
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
        elif k in ('ton', 'tof', 'tp'):
            # the PT pin value (wired or param, resolved by in_expr) is in ms
            pti = next((i for i, pp in enumerate(box.get('inputs') or []) if pp.get('name') == 'PT'), None)
            pt_s = (max(0, num(in_e[pti])) / 1000.0) if (pti is not None and pti < len(in_e)) \
                else self._secs(p.get('pt'), ctx)
            fn = {'ton': self._ton, 'tof': self._tof, 'tp': self._tp}[k]
            v, et = fn(self._stid(ctx, bid), bool(in_e[0] if in_e else False), pt_s)
            if _not_empty(p.get('q')):          # sim.js evalTON writes par.q/par.et in FBD too
                self._write(p.get('q'), ctx, v)
            if _not_empty(p.get('et')):
                self._write(p.get('et'), ctx, et)
            out_vals[0] = v
            if n_out > 1:                       # ET pin mirrors sim.js: reads back par.et (0 when unset)
                out_vals[1] = et if _not_empty(p.get('et')) else 0
            live = v
        elif k in ('ctu', 'ctd'):
            pvi = next((i for i, pp in enumerate(box.get('inputs') or []) if pp.get('name') == 'PV'), None)
            pv = num(in_e[pvi]) if (pvi is not None and pvi < len(in_e)) else self._rd_num(p.get('pv'), ctx)
            fn = self._ctu if k == 'ctu' else self._ctd
            q, cv = fn(self._stid(ctx, bid), bool(in_e[0] if in_e else False), pv,
                       bool(in_e[1] if len(in_e) > 1 else False))
            if _not_empty(p.get('cv')):         # sim.js evalCTU writes par.cv/par.q in FBD too
                self._write(p.get('cv'), ctx, cv)
            if _not_empty(p.get('q')):
                self._write(p.get('q'), ctx, q)
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
            qk = self._stid(ctx, bid) + '|q'
            cur = (self._rd_bool(box.get('operand'), ctx) if _not_empty(box.get('operand'))
                   else self.FBP.get(qk, False))
            q = self._sr(cur, bool(in_e[0] if in_e else False),
                         bool(in_e[1] if len(in_e) > 1 else False))
            if _not_empty(box.get('operand')):
                self._write(box.get('operand'), ctx, q)
            self.FBP[qk] = q
            out_vals[0] = q
            live = q
        elif k == 'rs':                 # set dominant; in pins [R, S1]
            qk = self._stid(ctx, bid) + '|q'
            cur = (self._rd_bool(box.get('operand'), ctx) if _not_empty(box.get('operand'))
                   else self.FBP.get(qk, False))
            q = self._rs(cur, bool(in_e[0] if in_e else False),
                         bool(in_e[1] if len(in_e) > 1 else False))
            if _not_empty(box.get('operand')):
                self._write(box.get('operand'), ctx, q)
            self.FBP[qk] = q
            out_vals[0] = q
            live = q
        elif k in ('p_trig', 'r_trig'):
            q = self._redge(self._stid(ctx, bid), bool(in_e[0] if in_e else False))
            if _not_empty(p.get('q')):
                self._write(p.get('q'), ctx, q)
            out_vals[0] = q
            live = q
        elif k in ('n_trig', 'f_trig'):
            q = self._fedge(self._stid(ctx, bid), bool(in_e[0] if in_e else False))
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
        the instance-DB block's name if wired, else "<target>_<full node id>"
        (a truncated id suffix can collide across call sites)."""
        inst_db = params.get('instanceDb')
        if _not_empty(inst_db):
            db = self._find_block(inst_db)
            if db and db.get('name'):
                return db.get('name')
        return (target_block.get('name') or 'blk') + '_' + str(node.get('id'))

    def _block_ctx(self, blk, inst):
        """Build a per-block evaluation context: member-name (lowercase) -> member
        name, the Bool members (SCL type resolution), and the instance id used to
        key "<inst>.<member>"."""
        members = {}
        bits = set()
        for m in self._iface_members(blk):
            name = m.get('name')
            if name:
                members[name.lower()] = name
                if m.get('dataType') == 'Bool':
                    bits.add(name.lower())
        return {'members': members, 'bits': bits, 'inst': inst}

    def _run_block(self, blk, inst):
        """Execute every network of a block under its own member context.
        Re-entrant calls are blocked (parity: sim.js cycle guard) so recursive
        programs can't blow the Python stack every scan."""
        if not blk or blk.get('type') == 'DB':
            return
        bid = blk.get('id')
        if bid in self._callstack:
            return
        self._callstack.add(bid)
        ctx = self._block_ctx(blk, inst)
        lang = blk.get('lang')
        try:
            if lang == 'SCL':
                try:
                    _code, prog, _perr = self._scl_program(blk)
                    if prog is not None:
                        self._scl_run_stmts(prog['body'], ctx)
                except Exception as e:
                    self.err_count += 1
                    self.last_error = '%s (SCL): %s' % (blk.get('name') or bid, e)
                return
            for net in (blk.get('networks') or []):
                if not net:
                    continue
                try:
                    if lang == 'FBD':
                        self._eval_fbd_network(net, ctx)
                    else:
                        self._eval_lad_network(net, ctx)
                except Exception as e:
                    # a bad network must not crash the whole scan (sim.js logs too);
                    # keep a diagnosis for /api/state instead of failing silently
                    self.err_count += 1
                    self.last_error = '%s / network %s: %s' % (
                        blk.get('name') or bid, net.get('id'), e)
        finally:
            self._callstack.discard(bid)

    # =======================================================================
    #  SCL execution (evaluator port of scl.js — parser is module-level)
    # =======================================================================
    def _scl_program(self, blk):
        """Parse-and-cache a block's SCL body. Returns (code, program|None, err|None)."""
        code = str(blk.get('code') or '')
        bid = blk.get('id')
        c = self._scl_cache.get(bid)
        if c and c[0] == code:
            return c
        try:
            entry = (code, _scl_parse(code), None)
        except _SclError as e:
            entry = (code, None, 'line %s: %s' % (e.line, e))
        except Exception as e:                     # defensive: any parser bug
            entry = (code, None, str(e))
        self._scl_cache[bid] = entry
        return entry

    def _scl_is_bit(self, name, ctx):
        """Storage class of an operand — mirrors scl.js opIsBit(): Bool member /
        Bool tag / bit address -> bit; undeclared symbols and words -> number."""
        raw = str('' if name is None else name).strip()
        if raw.startswith('%'):
            raw = raw[1:].strip()
        low = raw.lower()
        if ctx and ctx.get('members') and low in ctx['members']:
            return low in (ctx.get('bits') or ())
        alias = self._alias.get(low)
        if alias is not None:
            return alias.lower() in self._tag_bits
        return bool(re.match(r'^[IQM]\d+\.\d+$', raw, re.IGNORECASE))

    def _scl_read(self, name, ctx):
        v = self._rd(name, ctx)
        return bool(v) if self._scl_is_bit(name, ctx) else num(v)

    def _scl_write(self, name, value, ctx):
        if self._scl_is_bit(name, ctx):
            self._write(name, ctx, _scl_bool(value))
        else:
            self._write(name, ctx, _scl_intify(_scl_num(value)))

    def _scl_eval(self, node, ctx):
        n = node['n']
        if n == 'num' or n == 'bool':
            return node['v']
        if n == 'var':
            return self._scl_read(node['name'], ctx)
        if n == 'call':
            fn = _SCL_FUNCS.get(node['name'].upper())
            if not fn:
                return 0                          # unknown call -> 0 (lenient, scl.js parity)
            return fn([self._scl_eval(a, ctx) for a in node['args']])
        if n == 'un':
            if node['op'] == 'NOT':
                return not _scl_bool(self._scl_eval(node['a'], ctx))
            return -_scl_num(self._scl_eval(node['a'], ctx))
        if n == 'bin':
            op = node['op']
            if op == 'AND':                       # boolean operators short-circuit
                return _scl_bool(self._scl_eval(node['a'], ctx)) and _scl_bool(self._scl_eval(node['b'], ctx))
            if op == 'OR':
                return _scl_bool(self._scl_eval(node['a'], ctx)) or _scl_bool(self._scl_eval(node['b'], ctx))
            if op == 'XOR':
                return _scl_bool(self._scl_eval(node['a'], ctx)) != _scl_bool(self._scl_eval(node['b'], ctx))
            a = _scl_num(self._scl_eval(node['a'], ctx))
            b = _scl_num(self._scl_eval(node['b'], ctx))
            if op == '+':
                return a + b
            if op == '-':
                return a - b
            if op == '*':
                return a * b
            if op == '/':
                return 0 if b == 0 else _scl_intify(a / b)
            if op == 'MOD':                       # JS %: remainder takes the dividend's sign
                return 0 if b == 0 else _scl_intify(math.fmod(a, b))
            if op == '=':
                return a == b
            if op == '<>':
                return a != b
            if op == '<':
                return a < b
            if op == '>':
                return a > b
            if op == '<=':
                return a <= b
            if op == '>=':
                return a >= b
            return 0
        return 0

    def _scl_run_stmts(self, stmts, ctx):
        for s in stmts:
            sig = self._scl_run_stmt(s, ctx)
            if sig:
                return sig
        return None

    def _scl_run_stmt(self, s, ctx):
        n = s['n']
        if n == 'assign':
            self._scl_write(s['name'], self._scl_eval(s['expr'], ctx), ctx)
            return None
        if n == 'if':
            for arm in s['arms']:
                if _scl_bool(self._scl_eval(arm['cond'], ctx)):
                    return self._scl_run_stmts(arm['body'], ctx)
            if s['els'] is not None:
                return self._scl_run_stmts(s['els'], ctx)
            return None
        if n == 'case':
            v = _scl_num(self._scl_eval(s['expr'], ctx))
            for arm in s['arms']:
                for lab in arm['labels']:
                    if lab['lo'] <= v <= lab['hi']:
                        return self._scl_run_stmts(arm['body'], ctx)
            if s['els'] is not None:
                return self._scl_run_stmts(s['els'], ctx)
            return None
        if n == 'for':
            i = _scl_num(self._scl_eval(s['from'], ctx))
            to = _scl_num(self._scl_eval(s['to'], ctx))
            by = _scl_num(self._scl_eval(s['by'], ctx)) if s['by'] else 1
            if by == 0:
                return None
            guard = 0
            while (i <= to) if by > 0 else (i >= to):
                guard += 1
                if guard > _SCL_MAX_ITER:
                    break
                self._scl_write(s['var'], i, ctx)
                sig = self._scl_run_stmts(s['body'], ctx)
                if sig == _SCL_EXIT:
                    break
                if sig == _SCL_RET:
                    return _SCL_RET
                i += by                            # CONTINUE falls through to here
            return None
        if n == 'while':
            guard = 0
            while _scl_bool(self._scl_eval(s['cond'], ctx)):
                guard += 1
                if guard > _SCL_MAX_ITER:
                    break
                sig = self._scl_run_stmts(s['body'], ctx)
                if sig == _SCL_EXIT:
                    break
                if sig == _SCL_RET:
                    return _SCL_RET
            return None
        if n == 'repeat':
            guard = 0
            while True:
                guard += 1
                if guard > _SCL_MAX_ITER:
                    break
                sig = self._scl_run_stmts(s['body'], ctx)
                if sig == _SCL_EXIT:
                    break
                if sig == _SCL_RET:
                    return _SCL_RET
                if _scl_bool(self._scl_eval(s['cond'], ctx)):
                    break
            return None
        if n == 'exit':
            return _SCL_EXIT
        if n == 'continue':
            return _SCL_CONT
        if n == 'return':
            return _SCL_RET
        return None

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
        self._callstack.clear()        # defensive: never let a guard leak across scans
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
        def safe(v):
            # non-finite floats would make json.dumps emit bare Infinity/NaN,
            # which the browser's response.json() rejects (killing the monitor)
            if isinstance(v, float) and not math.isfinite(v):
                return 0
            return v

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
                mem[name] = safe(num(v))
        # also surface any extra memory keys the program touched (members, symbols)
        for k, v in self.M.items():
            if k not in mem:
                mem[k] = (bool(v) if isinstance(v, bool) else safe(v))
        return {
            'running': bool(running),
            'scan': self.scan_count,
            'mem': mem,
            'live': dict(self.live),
            'power': dict(self.power),
            'pins': dict(self.pinval),
            'errors': self.err_count,
            'lastError': self.last_error,
        }


# Quick manual check when run directly (no hardware needed).
if __name__ == '__main__':
    eng = Engine(mock=True)
    print('plc_engine import OK; gpiozero available:', Engine._gpiozero_available())
