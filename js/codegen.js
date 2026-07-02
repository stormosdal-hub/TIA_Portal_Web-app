/* ============================================================================
 * codegen.js — convert the LAD/FBD program to runnable Raspberry Pi Python.
 *
 * T.codegen.toPython(project) -> a self-contained .py string. Semantics mirror
 * sim.js exactly. The generated program has a pluggable I/O backend: gpiozero on
 * a real Pi (BCM numbering), or a dependency-free Mock backend (run with --mock)
 * so it can be tested with only python3 (no hardware, nothing installed).
 *
 * Memory model in the generated program: a dict M keyed by tag name (or address /
 * symbol). Block-local interface members are keyed "<instance>.<member>".
 * ==========================================================================*/
window.TIA = window.TIA || {};
(function (T) {
  'use strict';
  T.codegen = T.codegen || {};

  /* ---------------------------------------------------------------- helpers */
  function pyStr(s) {
    return "'" + String(s).replace(/\\/g, '\\\\').replace(/'/g, "\\'")
      .replace(/\r/g, '\\r').replace(/\n/g, '\\n') + "'";
  }
  function pyId(s) { return String(s || 'blk').replace(/[^A-Za-z0-9_]/g, '_'); }
  // user text going into a generated COMMENT must never inject a new line of code
  function cmt(s) { return String(s == null ? '' : s).replace(/[\r\n]+/g, ' '); }
  // unique Python function name per block ("My Block" and "My_Block" both pyId
  // to the same identifier — type+number disambiguates)
  function fnName(blk) { return 'block_' + pyId(blk.name) + '_' + (blk.type || 'B') + (blk.number || 0); }
  const CMP = { '==': '==', '<>': '!=', '>': '>', '<': '<', '>=': '>=', '<=': '<=' };
  const ADDR_RE = /^[IQM](\d+\.\d+|W\d+|B\d+|D\d+)$/i;

  // resolve an operand (in a block ctx) -> { lit } literal expr | { key } global | { local } member
  // Mirrors T.resolve's aliasing: a tag's name, its ADDRESS, and any case
  // variant all hit the SAME memory cell (read_inputs writes by tag name).
  function resolveOp(op, ctx) {
    let raw = (op == null ? '' : String(op)).trim();
    if (raw === '') return { lit: 'False' };
    if (raw.charAt(0) === '%') raw = raw.slice(1).trim();   // %I0.0 ≡ I0.0
    if (/^-?\d+(\.\d+)?$/.test(raw)) return { lit: raw };
    if (/^(true|false)$/i.test(raw)) return { lit: /^true$/i.test(raw) ? 'True' : 'False' };
    if (/^t#/i.test(raw)) return { lit: String(T.parseTime(raw) / 1000) };   // time literal -> seconds
    if (ctx && ctx.members && Object.prototype.hasOwnProperty.call(ctx.members, raw.toLowerCase())) {
      return { local: ctx.members[raw.toLowerCase()] };
    }
    const tags = (T.project && T.project.tags) || [];
    const tag = tags.find((t) => t.name === raw)
      || tags.find((t) => t.name && t.name.toLowerCase() === raw.toLowerCase())
      || tags.find((t) => (t.address || '').toUpperCase() === raw.toUpperCase());
    if (tag) return { key: tag.name };
    return { key: ADDR_RE.test(raw) ? raw.toUpperCase() : raw };
  }
  // Python expression that READS an operand's value
  function rd(op, ctx) {
    const r = resolveOp(op, ctx);
    if (r.lit !== undefined) return r.lit;
    if (r.local) return 'M[inst + ' + pyStr('.' + r.local) + ']';
    return 'M[' + pyStr(r.key) + ']';
  }
  function rdBool(op, ctx) { return 'bool(' + rd(op, ctx) + ')'; }
  function rdNum(op, ctx) { return 'num(' + rd(op, ctx) + ')'; }
  // operand/literal -> Python expr in MILLISECONDS (the app's native time unit:
  // T#5s parses to 5000, a plain number is ms, a tag/member VALUE is ms)
  function msExpr(op, ctx) {
    const raw = (op == null ? '' : String(op)).trim();
    if (raw === '') return '0';
    if (/^-?\d+(\.\d+)?$/.test(raw)) return String(Math.max(0, parseFloat(raw)));
    if (/^t#/i.test(raw)) return String(Math.max(0, T.parseTime(raw)));
    return 'num(' + rd(raw, ctx) + ')';
  }
  // PT for the generated timer helpers, which take SECONDS
  function secs(op, ctx) { return '(' + msExpr(op, ctx) + ' / 1000.0)'; }
  // per-element runtime-state id: scoped by the executing instance so an FB's
  // timers/counters/edges never share state between instances (parity: sim.js inst())
  function stId(id) { return '(inst + ' + pyStr(':' + id) + ')'; }
  // Python L-value for WRITING an operand (or null if not writable)
  function wt(op, ctx) {
    const r = resolveOp(op, ctx);
    if (r.local) return 'M[inst + ' + pyStr('.' + r.local) + ']';
    if (r.key) return 'M[' + pyStr(r.key) + ']';
    return null;
  }
  const notEmpty = (s) => s != null && String(s).trim() !== '';

  /* ----------------------------------------------------------- LAD: inline */
  function inlineExpr(el, ctx) {
    switch (el.kind) {
      case 'contact_no': return rd(el.operand, ctx);
      case 'contact_nc': return '(not ' + rd(el.operand, ctx) + ')';
      case 'edge_p': return 'redge(' + stId(el.id) + ', ' + rdBool(el.operand, ctx) + ')';
      case 'edge_n': return 'fedge(' + stId(el.id) + ', ' + rdBool(el.operand, ctx) + ')';
      case 'compare': {
        const op = CMP[(el.params && el.params.op) || '=='] || '==';
        return '(' + rdNum(el.params.in1, ctx) + ' ' + op + ' ' + rdNum(el.params.in2, ctx) + ')';
      }
      default: return 'True';
    }
  }
  function rungPower(net, ctx) {
    const stages = net.stages || [];
    if (!stages.length) return 'True';
    return stages.map((st) => {
      const branches = st.branches || [];
      // an empty branch is a bare wire only when the WHOLE stage is empty;
      // alongside a populated branch it is an unfinished arm (parity: sim.js stageValue)
      const withEls = branches.filter((br) => (br.elements || []).length);
      const use = withEls.length ? withEls : branches.slice(0, 1);
      const brs = use.map((br) => {
        const els = br.elements || [];
        return els.length ? '(' + els.map((e) => inlineExpr(e, ctx)).join(' and ') + ')' : 'True';
      });
      return brs.length ? '(' + brs.join(' or ') + ')' : 'True';
    }).join(' and ');
  }

  // assign a Q expr to an operand if set, else emit the bare call (keeps state updated)
  function setQ(op, expr, ctx) {
    const t = notEmpty(op) ? wt(op, ctx) : null;
    return t ? (t + ' = ' + expr) : expr;
  }

  /* ----------------------------------------------------------- LAD: outputs */
  function outputLines(el, ctx) {
    const p = el.params || {};
    const target = wt(el.operand, ctx);
    switch (el.kind) {
      case 'coil':       return [target + ' = p'];
      case 'coil_neg':   return [target + ' = (not p)'];
      case 'coil_set':   return ['if p: ' + target + ' = True'];
      case 'coil_reset': return ['if p: ' + target + ' = False'];
      case 'ton': return [setQ(p.q, 'ton(' + stId(el.id) + ', p, ' + secs(p.pt, ctx) + ')', ctx)];
      case 'tof': return [setQ(p.q, 'tof(' + stId(el.id) + ', p, ' + secs(p.pt, ctx) + ')', ctx)];
      case 'tp':  return [setQ(p.q, 'tp('  + stId(el.id) + ', p, ' + secs(p.pt, ctx) + ')', ctx)];
      case 'ctu': {
        const lines = ['q, cv = ctu(' + stId(el.id) + ', p, ' + rdNum(p.pv, ctx) + ', ' + rdBool(p.r || '', ctx) + ')'];
        if (notEmpty(p.cv)) lines.push(wt(p.cv, ctx) + ' = cv');
        if (notEmpty(p.q)) lines.push(wt(p.q, ctx) + ' = q');
        return lines;
      }
      case 'ctd': {
        const lines = ['q, cv = ctd(' + stId(el.id) + ', p, ' + rdNum(p.pv, ctx) + ', ' + rdBool(p.r || '', ctx) + ')'];
        if (notEmpty(p.cv)) lines.push(wt(p.cv, ctx) + ' = cv');
        if (notEmpty(p.q)) lines.push(wt(p.q, ctx) + ' = q');
        return lines;
      }
      case 'move': return ['if p: ' + wt(p.out, ctx) + ' = ' + rdNum(p.in, ctx)];
      case 'add': return ['if p: ' + wt(p.out, ctx) + ' = ' + rdNum(p.in1, ctx) + ' + ' + rdNum(p.in2, ctx)];
      case 'sub': return ['if p: ' + wt(p.out, ctx) + ' = ' + rdNum(p.in1, ctx) + ' - ' + rdNum(p.in2, ctx)];
      case 'mul': return ['if p: ' + wt(p.out, ctx) + ' = ' + rdNum(p.in1, ctx) + ' * ' + rdNum(p.in2, ctx)];
      case 'div': return ['if p: ' + wt(p.out, ctx) + ' = idiv(' + rdNum(p.in1, ctx) + ', ' + rdNum(p.in2, ctx) + ')'];
      case 'norm_x': return ['if p: ' + wt(p.out, ctx) + ' = norm_x(' + rdNum(p.min, ctx) + ', ' + rdNum(p.val, ctx) + ', ' + rdNum(p.max, ctx) + ')'];
      case 'scale_x': return ['if p: ' + wt(p.out, ctx) + ' = scale_x(' + rdNum(p.min, ctx) + ', ' + rdNum(p.val, ctx) + ', ' + rdNum(p.max, ctx) + ')'];
      case 'sr': return [target + ' = sr(' + target + ', p, ' + rdBool(p.r || '', ctx) + ')'];
      case 'rs': return [target + ' = rs(' + target + ', p, ' + rdBool(p.s || '', ctx) + ')'];
      case 'p_trig': case 'r_trig': return [setQ(p.q, 'redge(' + stId(el.id) + ', p)', ctx)];
      case 'n_trig': case 'f_trig': return [setQ(p.q, 'fedge(' + stId(el.id) + ', p)', ctx)];
      case 'call': return callLines(el, ctx, 'p');
      default: return ['# unsupported output: ' + el.kind];
    }
  }

  // Instance name for a call site: the instance DB's name, else a per-call-site
  // name from the FULL element id (a truncated id can collide across call sites).
  function callInstName(node, tb) {
    const dbName = node.params && node.params.instanceDb && (T.findBlock(node.params.instanceDb) || {}).name;
    return dbName || (tb.name + '_' + String(node.id));
  }

  // A block call (LAD element or FBD box). `enExpr` is the Python EN expression.
  function callLines(node, ctx, enExpr) {
    const tb = T.findBlock(node.params && node.params.target);
    if (!tb) return ['# call: target block not found'];
    const inst = callInstName(node, tb);
    const args = node.args || {};                       // LAD: el.args ; FBD: read from pins below
    const lines = ['if ' + enExpr + ':'];
    T.ifaceCallInputs(tb).forEach((m) => {
      const a = args[m.name];
      const src = node._fbdArg ? node._fbdArg(m.name) : (notEmpty(a) ? rd(a, ctx) : null);
      if (src != null) lines.push('    M[' + pyStr(inst + '.' + m.name) + '] = ' + src);
    });
    lines.push('    ' + fnName(tb) + '(' + pyStr(inst) + ')');
    T.ifaceCallOutputs(tb).forEach((m) => {
      const a = args[m.name];
      if (node._fbdOut) return;                         // FBD output pins are read after the if (EN may be false)
      if (notEmpty(a)) { const t = wt(a, ctx); if (t) lines.push('    ' + t + ' = M[' + pyStr(inst + '.' + m.name) + ']'); }
    });
    return lines;
  }

  /* ------------------------------------------------------ a LAD network */
  function ladNetwork(net, ctx, idx) {
    const lines = ['# Network ' + idx + (net.title ? ': ' + cmt(net.title) : '')];
    lines.push('p = ' + rungPower(net, ctx));
    (net.outputs || []).forEach((el) => { outputLines(el, ctx).forEach((l) => lines.push(l)); });
    return lines;
  }

  /* ====================================================================== *
   *  FBD network -> Python. Boxes are evaluated in dependency order; a wire
   *  into an already-computed pin uses its value, otherwise the last scan's
   *  cached value (FBP) so latches/feedback work.
   * ==================================================================== */
  // map a box pin NAME -> params key (parity: sim.js inParamKey — an unwired
  // numeric pin reads its box.params literal/operand, NOT pin.operand)
  function inParamKey(kind, pinName) {
    switch (kind) {
      case 'compare': if (pinName === 'in1') return 'in1'; if (pinName === 'in2') return 'in2'; break;
      case 'ton': case 'tof': case 'tp': if (pinName === 'PT') return 'pt'; break;
      case 'ctu': case 'ctd': if (pinName === 'PV') return 'pv'; break;
      case 'move': if (pinName === 'IN') return 'in'; break;
      case 'add': case 'sub': case 'mul': case 'div':
        if (pinName === 'in1') return 'in1'; if (pinName === 'in2') return 'in2'; break;
      case 'norm_x': case 'scale_x':
        if (pinName === 'MIN') return 'min';
        if (pinName === 'VALUE') return 'val';
        if (pinName === 'MAX') return 'max';
        break;
    }
    return null;
  }

  function fbdNetwork(net, ctx, idx) {
    const lines = ['# Network ' + idx + (net.title ? ': ' + cmt(net.title) : '') + '  (FBD)'];
    const boxes = net.boxes || [], wires = net.wires || [];
    const boxById = {}; boxes.forEach((b) => { boxById[b.id] = b; });
    // wire lookups
    const srcOfInput = {};   // "boxId|pinId" (input) -> {box,pin} source output
    wires.forEach((w) => { srcOfInput[w.to.box + '|' + w.to.pin] = w.from; });
    // topo order (ignore back edges)
    const order = topo(boxes, wires);
    const outVar = (boxId, pinId) => 'o_' + pyId(boxId).slice(-6) + '_' + pyId(pinId).slice(-4);
    // FBP cache keys are instance-scoped (parity: sim.js pinKey)
    const fbpKey = (boxId, pinId) => 'inst + ' + pyStr(':' + boxId + '|' + pinId);

    // expression for an input pin's value
    function inExpr(box, pin) {
      const src = srcOfInput[box.id + '|' + pin.id];
      let e;
      if (src) {
        e = computed[src.box + '|' + src.pin] ? outVar(src.box, src.pin)
          : ('FBP.get(' + fbpKey(src.box, src.pin) + ', False)');   // feedback / not yet computed
      } else {
        const pk = inParamKey(box.kind, pin.name);
        if (pk === 'pt') e = msExpr((box.params || {})[pk], ctx);   // PT: app-native ms
        else if (pk) e = rdNum((box.params || {})[pk], ctx);        // numeric param (PV/in1/…)
        else e = rd(pin.operand, ctx);                              // boolean pin operand
      }
      if (pin.inverted) e = '(not ' + e + ')';
      return e;
    }
    const computed = {};
    order.forEach((box) => {
      const ins = box.inputs || [], outs = box.outputs || [];
      const inE = ins.map((p) => inExpr(box, p));
      const ov = fbdBox(box, inE, ctx, lines, outVar);   // returns map pinId->expr written into lines
      outs.forEach((p) => { computed[box.id + '|' + p.id] = true; });
      // persist output pin values for next scan (feedback)
      outs.forEach((p, i) => { lines.push('FBP[' + fbpKey(box.id, p.id) + '] = ' + outVar(box.id, p.id)); });
    });
    return lines;
  }

  // emit one FBD box; sets o_<box>_<pin> vars for each output. Returns nothing.
  function fbdBox(box, inE, ctx, lines, outVar) {
    const outs = box.outputs || [];
    const O = (i) => outVar(box.id, (outs[i] || { id: 'o' + i }).id);
    const p = box.params || {};
    const k = box.kind;
    const setMain = (expr) => { lines.push(O(0) + ' = ' + expr); };
    // Pre-initialise EVERY output pin var so multi-output boxes (timer Q+ET,
    // counter Q+CV) never leave the secondary pin's var undefined for the pin-cache
    // step. The cases below overwrite the pins they actually compute.
    outs.forEach((pp, i) => lines.push(O(i) + ' = False'));
    switch (k) {
      case 'fb_and': setMain(inE.length ? '(' + inE.map((e) => 'bool(' + e + ')').join(' and ') + ')' : 'False'); break;
      case 'fb_or':  setMain(inE.length ? '(' + inE.map((e) => 'bool(' + e + ')').join(' or ') + ')' : 'False'); break;
      case 'fb_xor': setMain('(' + inE.map((e) => 'bool(' + e + ')').join(' ^ ') + ')'); break;
      case 'fb_not': setMain('(not ' + (inE[0] || 'False') + ')'); break;
      case 'assign':
        setMain('bool(' + (inE[0] || 'False') + ')');
        if (notEmpty(box.operand)) lines.push(wt(box.operand, ctx) + ' = ' + O(0));
        break;
      case 'compare': {
        const op = CMP[p.op || '=='] || '==';
        setMain('(num(' + (inE[0] || '0') + ') ' + op + ' num(' + (inE[1] || '0') + '))');
        break;
      }
      case 'ton': case 'tof': case 'tp': {
        // PT pin value (wired or param literal) is in app-native ms → seconds
        const pti = (box.inputs || []).findIndex((pp) => pp.name === 'PT');
        const pt = pti >= 0 ? '(num(' + inE[pti] + ') / 1000.0)' : secs(p.pt, ctx);
        setMain(k + '(' + stId(box.id) + ', bool(' + (inE[0] || 'False') + '), ' + pt + ')');
        if (notEmpty(p.q)) lines.push(wt(p.q, ctx) + ' = ' + O(0));   // sim.js writes par.q in FBD too
        break;
      }
      case 'ctu': case 'ctd': {
        const pvi = (box.inputs || []).findIndex((pp) => pp.name === 'PV');
        const pv = pvi >= 0 ? 'num(' + inE[pvi] + ')' : rdNum(p.pv, ctx);
        lines.push(O(0) + ', ' + cvVar(box, outVar) + ' = ' + k + '(' + stId(box.id) + ', bool(' + (inE[0] || 'False') + '), ' + pv + ', bool(' + (inE[1] || 'False') + '))');
        if (notEmpty(p.cv)) lines.push(wt(p.cv, ctx) + ' = ' + cvVar(box, outVar));   // sim.js writes par.cv/par.q in FBD too
        if (notEmpty(p.q)) lines.push(wt(p.q, ctx) + ' = ' + O(0));
        break;
      }
      case 'move': setMain('num(' + (inE[0] || '0') + ')'); if (notEmpty(p.out)) lines.push(wt(p.out, ctx) + ' = ' + O(0)); break;
      case 'add': setMain('num(' + (inE[0] || '0') + ') + num(' + (inE[1] || '0') + ')'); if (notEmpty(p.out)) lines.push(wt(p.out, ctx) + ' = ' + O(0)); break;
      case 'sub': setMain('num(' + (inE[0] || '0') + ') - num(' + (inE[1] || '0') + ')'); if (notEmpty(p.out)) lines.push(wt(p.out, ctx) + ' = ' + O(0)); break;
      case 'mul': setMain('num(' + (inE[0] || '0') + ') * num(' + (inE[1] || '0') + ')'); if (notEmpty(p.out)) lines.push(wt(p.out, ctx) + ' = ' + O(0)); break;
      case 'div': setMain('idiv(num(' + (inE[0] || '0') + '), num(' + (inE[1] || '0') + '))'); if (notEmpty(p.out)) lines.push(wt(p.out, ctx) + ' = ' + O(0)); break;
      case 'norm_x': setMain('norm_x(num(' + (inE[0] || '0') + '), num(' + (inE[1] || '0') + '), num(' + (inE[2] || '0') + '))'); if (notEmpty(p.out)) lines.push(wt(p.out, ctx) + ' = ' + O(0)); break;
      case 'scale_x': setMain('scale_x(num(' + (inE[0] || '0') + '), num(' + (inE[1] || '0') + '), num(' + (inE[2] || '0') + '))'); if (notEmpty(p.out)) lines.push(wt(p.out, ctx) + ' = ' + O(0)); break;
      case 'sr': {
        const qk = 'inst + ' + pyStr(':' + box.id + '|q');
        const cur = notEmpty(box.operand) ? wt(box.operand, ctx) : 'FBP.get(' + qk + ', False)';
        setMain('sr(' + cur + ', bool(' + (inE[0] || 'False') + '), bool(' + (inE[1] || 'False') + '))');
        if (notEmpty(box.operand)) lines.push(wt(box.operand, ctx) + ' = ' + O(0));
        lines.push('FBP[' + qk + '] = ' + O(0));
        break;
      }
      case 'rs': {
        // pins are [R, S1] (catalog order): inE[0] resets, inE[1] sets — parity: sim.js
        const qk = 'inst + ' + pyStr(':' + box.id + '|q');
        const cur = notEmpty(box.operand) ? wt(box.operand, ctx) : 'FBP.get(' + qk + ', False)';
        setMain('rs(' + cur + ', bool(' + (inE[0] || 'False') + '), bool(' + (inE[1] || 'False') + '))');
        if (notEmpty(box.operand)) lines.push(wt(box.operand, ctx) + ' = ' + O(0));
        lines.push('FBP[' + qk + '] = ' + O(0));
        break;
      }
      case 'p_trig': case 'r_trig': setMain('redge(' + stId(box.id) + ', bool(' + (inE[0] || 'False') + '))'); if (notEmpty(p.q)) lines.push(wt(p.q, ctx) + ' = ' + O(0)); break;
      case 'n_trig': case 'f_trig': setMain('fedge(' + stId(box.id) + ', bool(' + (inE[0] || 'False') + '))'); if (notEmpty(p.q)) lines.push(wt(p.q, ctx) + ' = ' + O(0)); break;
      case 'call': {
        const en = 'bool(' + (inE[0] || 'False') + ')';
        // map member name -> input pin expr (inputs are copied only while EN)
        box._fbdArg = (mname) => { const idx = (box.inputs || []).findIndex((pp) => pp.name === mname); return idx >= 0 ? inE[idx] : null; };
        box._fbdOut = true;              // marker: outputs handled below, unconditionally
        callLines(box, ctx, en).forEach((l) => lines.push(l));
        // output pins reflect the instance's members even when EN is false
        // (sim.js and the online engine hold last values; False-collapse diverged)
        const tb = T.findBlock(box.params && box.params.target);
        if (tb) {
          const instName = callInstName(box, tb);
          T.ifaceCallOutputs(tb).forEach((m) => {
            const idx = (box.outputs || []).findIndex((pp) => pp.name === m.name);
            if (idx >= 0) lines.push(O(idx) + ' = M[' + pyStr(instName + '.' + m.name) + ']');
          });
        }
        lines.push(O(0) + ' = ' + en);   // ENO follows EN
        break;
      }
      default: outs.forEach((pp, i) => lines.push(O(i) + ' = False'));
    }
    // ensure every output var is defined
    outs.forEach((pp, i) => { /* most set above; safety net handled per-case */ });
  }
  function cvVar(box, outVar) { const outs = box.outputs || []; return outVar(box.id, (outs[1] || { id: 'cv' }).id); }

  // topological order of boxes by wires (ignore back edges that would cycle)
  function topo(boxes, wires) {
    const deps = {}; boxes.forEach((b) => { deps[b.id] = new Set(); });
    wires.forEach((w) => { if (deps[w.to.box] && w.from.box !== w.to.box) deps[w.to.box].add(w.from.box); });
    const order = [], placed = new Set(), temp = new Set();
    function visit(id) {
      if (placed.has(id) || temp.has(id)) return;   // temp -> back edge, skip
      temp.add(id);
      (deps[id] ? Array.from(deps[id]) : []).forEach(visit);
      temp.delete(id); placed.add(id);
      const b = boxes.find((x) => x.id === id); if (b) order.push(b);
    }
    boxes.forEach((b) => visit(b.id));
    return order;
  }

  /* ---------------------------------------------------- block -> ctx ----- */
  function blockCtx(blk) {
    const members = {};
    if (blk.iface) (T.ifaceMembers(blk) || []).forEach((e) => { members[e.member.name.toLowerCase()] = e.member.name; });
    return { members };
  }
  function blockBody(blk) {
    const ctx = blockCtx(blk);
    const lines = [];
    if (blk.lang === 'SCL') {
      // text body -> Python via the SCL module (uses our rd/wt operand accessors)
      const body = T.scl ? T.scl.toPython(blk, (nm) => rd(nm, ctx), (nm) => wt(nm, ctx)) : ['# SCL module unavailable', 'pass'];
      body.forEach((l) => lines.push(l));
      if (!lines.length) lines.push('pass');
      return lines;
    }
    (blk.networks || []).forEach((net, i) => {
      const nl = blk.lang === 'FBD' ? fbdNetwork(net, ctx, i + 1) : ladNetwork(net, ctx, i + 1);
      nl.forEach((l) => lines.push(l));
      lines.push('');
    });
    if (!lines.length) lines.push('pass');
    return lines;
  }

  /* =================================================== collect memory keys */
  function collectKeys(project) {
    const bits = {}, words = {};
    (project.tags || []).forEach((t) => { (t.dataType === 'Bool' ? bits : words)[t.name] = true; });
    return { bits, words };
  }

  /* ====================================================== gpio pin mapping */
  function gpioMap(project) {
    const map = Array.isArray(project.gpio) ? project.gpio : [];
    const ins = [], outs = [], pwms = [];
    map.forEach((m) => {
      if (m.bcm == null || m.bcm === '') return;
      const tag = (project.tags || []).find((t) => t.name === m.tag);
      const dir = m.dir || (tag && /^I/i.test(tag.address || '') ? 'in' : (tag && /^Q/i.test(tag.address || '') ? 'out' : 'out'));
      if (dir === 'pwm') {                          // analog (software-PWM) output for a numeric tag
        const freq = (m.freq == null || m.freq === '') ? 100 : (parseInt(m.freq, 10) || 100);
        pwms.push({ tag: m.tag, bcm: m.bcm, freq: freq });
        return;
      }
      (dir === 'in' ? ins : outs).push({ tag: m.tag, bcm: m.bcm, pull: m.pull || 'down', activeLow: !!m.activeLow });
    });
    return { ins, outs, pwms };
  }

  /* ============================================================ assemble */
  T.codegen.toPython = function (project) {
    project = project || T.project;
    if (!project) return '# no project';
    const keys = collectKeys(project);
    const gm = gpioMap(project);
    const blocks = project.blocks || [];
    const obs = blocks.filter((b) => b.type === 'OB').sort((a, b) => (a.number || 0) - (b.number || 0));
    const fcs = blocks.filter((b) => b.type === 'FC').sort((a, b) => (a.number || 0) - (b.number || 0));
    const fbs = blocks.filter((b) => b.type === 'FB').sort((a, b) => (a.number || 0) - (b.number || 0));
    const calledNames = collectCalled(blocks);

    const O = [];
    const push = (s) => O.push(s == null ? '' : s);
    const ind = (lines, n) => lines.forEach((l) => push(l === '' ? '' : ' '.repeat(n) + l));

    push('#!/usr/bin/env python3');
    push('# -*- coding: utf-8 -*-');
    push('# Generated by TIA Web Practice  --  Raspberry Pi PLC runtime');
    push('# Project: ' + cmt(project.name || 'PLC') + '   Device: ' + cmt((project.device && project.device.type) || ''));
    push('# Real hardware: gpiozero (Raspberry Pi 5 / BCM).  Test off-Pi:  python3 ' + pyId(project.name || 'plc') + '.py --mock');
    push('import sys, time, math');
    push('from collections import defaultdict');
    push('');
    push('SCAN_S = ' + ((Math.max(1, +project.scanMs || 50)) / 1000) + '            # scan cycle time (s) — set in the app');
    push("MOCK = '--mock' in sys.argv");
    push('');
    push('# ---- clock (overridable for deterministic testing) ----');
    push('_CLK = [None]');
    push('def now():');
    push('    return _CLK[0] if _CLK[0] is not None else time.monotonic()');
    push('');
    push('# ---- numeric / safe helpers ----');
    push('def num(v):');
    push('    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else (int(v) if isinstance(v, bool) else (v or 0))');
    push('def idiv(a, b):');
    push('    return 0 if num(b) == 0 else num(a) / num(b)');
    push('def norm_x(mn, v, mx):');
    push('    d = num(mx) - num(mn)');
    push('    return 0 if d == 0 else (num(v) - num(mn)) / d');
    push('def scale_x(mn, v, mx):');
    push('    return num(v) * (num(mx) - num(mn)) + num(mn)');
    push('');
    push('# ---- state for timers / counters / edges ----');
    push('ST = {}');
    push('FBP = {}            # FBD pin cache (feedback / latches)');
    push('_CALLSTACK = set()  # re-entrant block-call guard (parity with the simulator)');
    push('def ton(i, inp, pt):');
    push('    s = ST.setdefault(i, {"t0": None})');
    push('    if inp:');
    push('        if s["t0"] is None: s["t0"] = now()');
    push('        return (now() - s["t0"]) >= pt');
    push('    s["t0"] = None; return False');
    push('def tof(i, inp, pt):');
    push('    s = ST.setdefault(i, {"t0": None, "prev": False})');
    push('    if inp: s["t0"] = None; q = True');
    push('    else:');
    push('        if s["prev"] and s["t0"] is None: s["t0"] = now()');
    push('        q = (s["t0"] is not None) and ((now() - s["t0"]) < pt)');
    push('    s["prev"] = inp; return q');
    push('def tp(i, inp, pt):');
    push('    s = ST.setdefault(i, {"t0": None, "prev": False})');
    push('    if inp and not s["prev"] and s["t0"] is None: s["t0"] = now()');
    push('    q = False');
    push('    if s["t0"] is not None:');
    push('        if (now() - s["t0"]) < pt: q = True');
    push('        elif not inp: s["t0"] = None');
    push('    s["prev"] = inp; return q');
    push('def ctu(i, cu, pv, reset):');
    push('    s = ST.setdefault(i, {"c": 0, "prev": False})');
    push('    if reset: s["c"] = 0');
    push('    elif cu and not s["prev"]: s["c"] = min(s["c"] + 1, 32767)');
    push('    s["prev"] = cu; return (s["c"] >= pv, s["c"])');
    push('def ctd(i, cd, pv, load):');
    push('    s = ST.setdefault(i, {"c": 0, "prev": False})   # IEC: CV starts at 0 until LD');
    push('    if load: s["c"] = pv');
    push('    elif cd and not s["prev"]: s["c"] = max(s["c"] - 1, -32767)');
    push('    s["prev"] = cd; return (s["c"] <= 0, s["c"])');
    push('def redge(i, clk):');
    push('    s = ST.setdefault(i, {"p": False}); q = clk and not s["p"]; s["p"] = clk; return q');
    push('def fedge(i, clk):');
    push('    s = ST.setdefault(i, {"p": False}); q = (not clk) and s["p"]; s["p"] = clk; return q');
    push('def sr(cur, s_in, r_in):  return False if r_in else (True if s_in else cur)   # reset dominant');
    push('def rs(cur, r_in, s_in):  return True if s_in else (False if r_in else cur)   # set dominant');
    push('');
    push('# ---- memory (tag name -> value) ----');
    push('M = defaultdict(int)');
    const bitKeys = Object.keys(keys.bits), wordKeys = Object.keys(keys.words);
    if (bitKeys.length) push('for _k in [' + bitKeys.map(pyStr).join(', ') + ']: M[_k] = False');
    wordKeys.forEach((k) => push('M[' + pyStr(k) + '] = 0'));
    push('');
    push('# ---- I/O backend ----');
    push('class _MockPin:');
    push('    def __init__(self, v=False): self._v = bool(v)');
    push('    @property');
    push('    def value(self): return self._v');
    push('    @value.setter');
    push('    def value(self, v): self._v = bool(v)');
    push('');
    push('class _MockAnalog:');
    push('    """Float-capable mock for a PWMOutputDevice (duty 0.0..1.0)."""');
    push('    def __init__(self, v=0.0): self._v = float(v)');
    push('    @property');
    push('    def value(self): return self._v');
    push('    @value.setter');
    push('    def value(self, v): self._v = float(v)');
    push('');
    push('def _make_input(bcm, pull, active_low):');
    push('    if MOCK: return _MockPin(False)');
    push('    from gpiozero import DigitalInputDevice');
    push('    return DigitalInputDevice(bcm, pull_up=(pull == "up"), active_state=((not active_low) if pull == "none" else None))');
    push('def _make_output(bcm, active_low):');
    push('    if MOCK: return _MockPin(False)');
    push('    from gpiozero import DigitalOutputDevice');
    push('    return DigitalOutputDevice(bcm, active_high=(not active_low))');
    push('def _make_pwm(bcm, freq):');
    push('    if MOCK: return _MockAnalog(0.0)');
    push('    from gpiozero import PWMOutputDevice');
    push('    return PWMOutputDevice(bcm, frequency=freq)');
    push('');
    push('INPUTS = {}');
    gm.ins.forEach((m) => push('INPUTS[' + pyStr(m.tag) + '] = _make_input(' + m.bcm + ', ' + pyStr(m.pull) + ', ' + (m.activeLow ? 'True' : 'False') + ')'));
    push('OUTPUTS = {}');
    gm.outs.forEach((m) => push('OUTPUTS[' + pyStr(m.tag) + '] = _make_output(' + m.bcm + ', ' + (m.activeLow ? 'True' : 'False') + ')'));
    push('PWMS = {}');
    gm.pwms.forEach((m) => push('PWMS[' + pyStr(m.tag) + '] = _make_pwm(' + m.bcm + ', ' + m.freq + ')'));
    push('');
    push('def read_inputs():');
    push('    for k, d in INPUTS.items(): M[k] = bool(d.value)');
    push('def write_outputs():');
    push('    for k, d in OUTPUTS.items(): d.value = bool(M[k])');
    push('    for k, d in PWMS.items(): d.value = max(0.0, min(1.0, float(M[k] or 0)))');
    push('');

    // ---- block functions (FC/FB) ----
    fcs.concat(fbs).forEach((blk) => {
      const fn = fnName(blk);
      push('def ' + fn + "(inst=''):");
      push('    # ' + cmt(blk.type + blk.number + '  ' + blk.name + '  (' + blk.lang + ')'));
      push('    if ' + pyStr(fn) + ' in _CALLSTACK: return   # re-entrant call blocked');
      push('    _CALLSTACK.add(' + pyStr(fn) + ')');
      push('    try:');
      ind(blockBody(blk), 8);
      push('    finally:');
      push('        _CALLSTACK.discard(' + pyStr(fn) + ')');
      push('');
    });

    // ---- scan ----
    push('def scan():');
    push("    inst = ''");
    obs.forEach((blk) => {
      push('    # ===== ' + cmt(blk.type + blk.number + '  ' + blk.name) + ' =====');
      ind(blockBody(blk), 4);
    });
    // orphan FC/FB (not referenced by any call) still run, like the simulator
    const orphans = fcs.concat(fbs).filter((b) => !calledNames[b.id]);
    if (orphans.length) {
      push('    # uncalled blocks (run once per scan, like the simulator)');
      orphans.forEach((b) => push('    ' + fnName(b) + '(' + pyStr(b.name + '_inst') + ')'));
    }
    push('');
    push('def run(cycles=None):');
    push('    n = 0');
    push('    try:');
    push('        while cycles is None or n < cycles:');
    push('            t0 = time.monotonic()');
    push('            read_inputs(); scan(); write_outputs()');
    push('            time.sleep(max(0.0, SCAN_S - (time.monotonic() - t0)))');
    push('            n += 1');
    push('    except KeyboardInterrupt:');
    push('        pass');
    push('');
    push("if __name__ == '__main__':");
    push('    print("PLC running" + (" (MOCK)" if MOCK else "") + " - Ctrl+C to stop")');
    push('    run()');
    push('');
    return O.join('\n');
  };

  function collectCalled(blocks) {
    const set = {};
    blocks.forEach((blk) => (blk.networks || []).forEach((net) => {
      (net.outputs || []).forEach((e) => { if (e.kind === 'call' && e.params && e.params.target) set[e.params.target] = true; });
      (net.boxes || []).forEach((b) => { if (b.kind === 'call' && b.params && b.params.target) set[b.params.target] = true; });
    }));
    return set;
  }

  /* ====================================================================== *
   *  UI — "Raspberry Pi" export view: pin map + generated code + download   *
   * ==================================================================== */
  function ensureGpio() { if (!Array.isArray(T.project.gpio)) T.project.gpio = []; return T.project.gpio; }
  function gpioEntry(tag) { return ensureGpio().find((e) => e.tag === tag) || null; }
  function setGpio(tag, patch) {
    const arr = ensureGpio();
    let e = arr.find((x) => x.tag === tag);
    if (!e) { e = { tag: tag }; arr.push(e); }
    Object.assign(e, patch);
    T.bus.emit('tags:changed');
  }
  function defaultDir(tag) { return /^I/i.test(tag.address || '') ? 'in' : 'out'; }

  function sel(options, value, onchange) {
    const s = T.el('select', { class: 'tia-input', onchange: (e) => onchange(e.target.value) });
    options.forEach((o) => s.appendChild(T.el('option', { value: o, selected: o === value }, o)));
    return s;
  }

  T.injectCSS('tia-rpi-css', `
    .rpi-root { padding: 8px 10px; }
    .rpi-intro { color: var(--tia-text-soft); margin-bottom: 8px; max-width: 820px; line-height: 1.5; }
    .rpi-intro code { font-family: var(--tia-mono); background: var(--tia-row-alt); padding: 0 3px; border-radius: 2px; }
    .rpi-bar { display: flex; gap: 6px; margin: 8px 0; align-items: center; }
    .rpi-bar .tia-status { margin-left: 8px; color: var(--tia-text-soft); }
    table.rpi-pintable { max-width: 820px; }
    table.rpi-pintable td .tia-input { width: 100%; min-width: 70px; }
    table.rpi-pintable .rpi-bcm { width: 70px; }
    .rpi-section { font-weight: 700; color: var(--tia-petrol-deep); margin: 6px 0 4px; }
    .rpi-code { font-family: var(--tia-mono); font-size: 12px; line-height: 1.45; white-space: pre;
      background: #1e2630; color: #d6e2ea; padding: 10px 12px; border-radius: 4px; overflow: auto;
      max-height: 50vh; border: 1px solid var(--tia-border); }
  `);

  const isNumericTag = (t) => ['Int', 'Real', 'Word', 'DInt', 'UInt'].indexOf(t.dataType) >= 0;

  function buildPinTable(refresh) {
    // Bool tags -> digital in/out; numeric tags -> software-PWM analog output.
    const tags = (T.project.tags || []).filter((t) => t.dataType === 'Bool' || isNumericTag(t));
    const table = T.el('table', { class: 'tia-table rpi-pintable' });
    table.appendChild(T.el('tr', {},
      ['Tag', 'Address', 'Direction', 'BCM pin', 'Pull / Freq', 'Active-low'].map((h) => T.el('th', {}, h))));
    if (!tags.length) { table.appendChild(T.el('tr', {}, T.el('td', { colspan: 6 }, 'No mappable tags.'))); return table; }
    tags.forEach((t) => {
      const g = gpioEntry(t.name) || {};
      const numeric = isNumericTag(t);
      const dir = g.dir || (numeric ? '—' : defaultDir(t));
      const bcm = T.el('input', { class: 'tia-input rpi-bcm', type: 'number', min: 0, max: 27,
        value: (g.bcm != null ? g.bcm : ''), placeholder: '—',
        onchange: (e) => { setGpio(t.name, { bcm: e.target.value === '' ? null : parseInt(e.target.value, 10) }); refresh(); } });

      let dirSel, midCell, alCell;
      if (numeric) {
        // numeric tag: PWM analog output (duty 0..1) or unmapped
        dirSel = sel(['pwm', '—'], dir, (v) => { setGpio(t.name, { dir: v }); refresh(); });
        if (dir === 'pwm') {
          const freq = T.el('input', { class: 'tia-input', type: 'number', min: 1, max: 8000,
            value: (g.freq != null ? g.freq : 100), title: 'PWM frequency (Hz)',
            onchange: (e) => { const v = Math.max(1, Math.min(8000, parseInt(e.target.value, 10) || 100)); setGpio(t.name, { freq: v }); e.target.value = v; refresh(); } });
          midCell = freq;
        } else {
          midCell = T.el('span', { class: 'tia-muted' }, '—');
        }
        alCell = T.el('span', { class: 'tia-muted' }, '—');
      } else {
        // Bool tag: digital input (in + pull) or output (out + active-low)
        dirSel = sel(['in', 'out'], dir, (v) => { setGpio(t.name, { dir: v }); refresh(); });
        midCell = dir === 'in'
          ? sel(['down', 'up', 'none'], g.pull || 'down', (v) => { setGpio(t.name, { pull: v }); refresh(); })
          : T.el('span', { class: 'tia-muted' }, '—');
        alCell = T.el('input', { type: 'checkbox', checked: !!g.activeLow,
          onchange: (e) => { setGpio(t.name, { activeLow: e.target.checked }); refresh(); } });
      }

      table.appendChild(T.el('tr', {},
        T.el('td', {}, t.name),
        T.el('td', { class: 'sim-mono' }, t.address || ''),
        T.el('td', {}, dirSel),
        T.el('td', {}, bcm),
        T.el('td', {}, midCell),
        T.el('td', { style: { textAlign: 'center' } }, alCell)));
    });
    return table;
  }

  function downloadPy() {
    const py = T.codegen.toPython(T.project);
    const name = (T.project.name || 'plc').replace(/[^A-Za-z0-9_]/g, '_').toLowerCase() + '.py';
    const blob = new Blob([py], { type: 'text/x-python' });
    const url = URL.createObjectURL(blob);
    const a = T.el('a', { href: url, download: name });
    document.body.appendChild(a); a.click();
    setTimeout(() => { URL.revokeObjectURL(url); a.remove(); }, 100);
    T.status('Downloaded ' + name, 'ok');
  }
  function copyPy(py) {
    const ta = T.el('textarea', { style: { position: 'fixed', left: '-9999px', top: '0' } });
    ta.value = py; document.body.appendChild(ta); ta.select();
    try { document.execCommand('copy'); T.status('Python copied to clipboard', 'ok'); }
    catch (e) { T.status('Copy not available — select the code manually', 'warn'); }
    ta.remove();
  }

  function renderRpi(host) {
    T.clear(host);
    const root = T.el('div', { class: 'rpi-root' });
    root.appendChild(T.el('div', { class: 'rpi-intro' },
      'Map each tag to a Raspberry Pi GPIO (BCM) pin, then download the Python program. ',
      'Bool inputs (I) become GPIO inputs, Bool outputs (Q) become GPIO outputs. ',
      'A numeric tag can drive a ', T.el('code', {}, 'pwm'), ' (software-PWM analog output): its value is written as a duty ',
      'clamped to 0.0–1.0 (scale to that range with NORM_X / SCALE_X). ',
      'Tags left unmapped stay internal memory. ',
      'On the Pi: ', T.el('code', {}, 'python3 ' + (T.project.name || 'plc').toLowerCase().replace(/[^a-z0-9_]/g, '_') + '.py'),
      ' (needs ', T.el('code', {}, 'gpiozero'), '). Test off-Pi with ', T.el('code', {}, '--mock'), '.'));

    const codePre = T.el('pre', { class: 'rpi-code' });
    const refresh = () => { codePre.textContent = T.codegen.toPython(T.project); };

    // scan cycle time — the floor on how fast timers/blinkers can change
    root.appendChild(T.el('div', { class: 'rpi-section' }, 'Runtime'));
    const scanInput = T.el('input', {
      class: 'tia-input', type: 'number', min: 1, max: 2000, style: { width: '76px' },
      value: (T.project.scanMs || 50),
      onchange: (e) => {
        const v = Math.max(1, Math.min(2000, parseInt(e.target.value, 10) || 50));
        T.project.scanMs = v; e.target.value = v; T.bus.emit('tags:changed'); refresh();
      },
    });
    root.appendChild(T.el('div', { class: 'rpi-row', style: { margin: '4px 0 6px' } },
      T.el('label', { style: { marginRight: '8px', fontWeight: '600' } }, 'Scan cycle (ms):'), scanInput,
      T.el('span', { class: 'tia-muted', style: { marginLeft: '10px' } },
        'A timer is checked once per scan, so this is the floor on timer/blinker speed (e.g. 5 ms ≈ 200 Hz). '
        + 'Practical limit ~1–2 ms on the Pi; the in-app simulator clamps to ≥20 ms.')));

    root.appendChild(T.el('div', { class: 'rpi-section' }, 'GPIO pin assignment'));
    root.appendChild(buildPinTable(refresh));

    root.appendChild(T.el('div', { class: 'rpi-bar' },
      T.el('button', { class: 'tia-tb-btn primary', onclick: downloadPy },
        (function () { const s = T.el('span'); s.innerHTML = T.icons.download; return s.firstChild; })(), ' Download .py'),
      T.el('button', { class: 'tia-tb-btn', onclick: () => copyPy(codePre.textContent) }, 'Copy'),
      T.el('button', { class: 'tia-tb-btn', onclick: refresh }, 'Regenerate')));

    root.appendChild(T.el('div', { class: 'rpi-section' }, 'Generated Python'));
    root.appendChild(codePre);
    host.appendChild(root);
    refresh();
  }

  T.editors = T.editors || {};
  T.editors.rpi = { open: renderRpi };

  console.log('[TIA] codegen loaded');
})(window.TIA);
