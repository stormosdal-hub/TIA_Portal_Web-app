---
type: community
members: 85
---

# PLC Engine Core

**Members:** 85 nodes

## Members
- [[.__init__()_2]] - code - plc_engine.py
- [[._apply_output()]] - code - plc_engine.py
- [[._block_ctx()]] - code - plc_engine.py
- [[._call_fbd()]] - code - plc_engine.py
- [[._call_lad()]] - code - plc_engine.py
- [[._collect_called()]] - code - plc_engine.py
- [[._ctd()]] - code - plc_engine.py
- [[._ctu()]] - code - plc_engine.py
- [[._eval_fbd_box()]] - code - plc_engine.py
- [[._eval_fbd_network()]] - code - plc_engine.py
- [[._eval_lad_network()]] - code - plc_engine.py
- [[._fedge()]] - code - plc_engine.py
- [[._find_block()]] - code - plc_engine.py
- [[._iface_call_inputs()]] - code - plc_engine.py
- [[._iface_call_outputs()]] - code - plc_engine.py
- [[._iface_members()]] - code - plc_engine.py
- [[._iface_sections()]] - code - plc_engine.py
- [[._inline_value()]] - code - plc_engine.py
- [[._instance_id()]] - code - plc_engine.py
- [[._math()]] - code - plc_engine.py
- [[._rd()]] - code - plc_engine.py
- [[._rd_bool()]] - code - plc_engine.py
- [[._rd_num()]] - code - plc_engine.py
- [[._redge()]] - code - plc_engine.py
- [[._reset_runtime_state()]] - code - plc_engine.py
- [[._resolve()]] - code - plc_engine.py
- [[._rs()]] - code - plc_engine.py
- [[._run_block()]] - code - plc_engine.py
- [[._rung_power()]] - code - plc_engine.py
- [[._secs()]] - code - plc_engine.py
- [[._seed_memory()]] - code - plc_engine.py
- [[._set_q()]] - code - plc_engine.py
- [[._sr()]] - code - plc_engine.py
- [[._tof()]] - code - plc_engine.py
- [[._ton()]] - code - plc_engine.py
- [[._topo()]] - code - plc_engine.py
- [[._tp()]] - code - plc_engine.py
- [[._wkey()]] - code - plc_engine.py
- [[._write()]] - code - plc_engine.py
- [[.force()]] - code - plc_engine.py
- [[.now()]] - code - plc_engine.py
- [[.read_inputs()]] - code - plc_engine.py
- [[.scan()]] - code - plc_engine.py
- [[.set_program()]] - code - plc_engine.py
- [[.snapshot()]] - code - plc_engine.py
- [[.write_outputs()]] - code - plc_engine.py
- [[AND over stages ( OR over branches ( AND over inline element values ) ).]] - rationale - plc_engine.py
- [[Apply one output-area element with rung power p. Records el._live.]] - rationale - plc_engine.py
- [[Block idsnames referenced by any kind'call' elementbox.]] - rationale - plc_engine.py
- [[Build a per-block evaluation context member-name (lowercase) - member]] - rationale - plc_engine.py
- [[Coerce any memory value to a number. bool - int; None'' - 0.]] - rationale - plc_engine.py
- [[Divide-by-zero-guarded division (mirrors codegen.js idiv  sim.js mathOp).]] - rationale - plc_engine.py
- [[Engine]] - code - plc_engine.py
- [[Evaluate one FBD box; return a list of output-pin values (in pin order).]] - rationale - plc_engine.py
- [[Execute a call element copy wired args into the callee instance,         run it]] - rationale - plc_engine.py
- [[Execute an FBD call box. Returns output-pin values (ENO + members).]] - rationale - plc_engine.py
- [[Execute every network of a block under its own member context.]] - rationale - plc_engine.py
- [[Initialise M with every declared tag by its NAME (bool-False, num-0).]] - rationale - plc_engine.py
- [[Inline (contact-area) element value; records el._live in self.live.]] - rationale - plc_engine.py
- [[Instance name used to key member storage. Mirrors codegen.js         the instan]] - rationale - plc_engine.py
- [[Interprets a TIA-Web project (LADFBD), drives GPIO, exposes live state.      Pu]] - rationale - plc_engine.py
- [[L-value memory key for writing an operand, or None if not writable.]] - rationale - plc_engine.py
- [[Live state for the browser monitor. mem includes every project tag by         na]] - rationale - plc_engine.py
- [[Load or replace the running program. Resets all state, seeds memory         with]] - rationale - plc_engine.py
- [[NORM_X OUT = (VALUE-MIN)(MAX-MIN); 0 if MAX==MIN. Not clamped (matches sim.js)]] - rationale - plc_engine.py
- [[Read an operand's raw stored value.]] - rationale - plc_engine.py
- [[Read every mapped GPIO input into M (by tag name).]] - rationale - plc_engine.py
- [[Resolve a PT operand to seconds literal (already seconds) or num(value).]] - rationale - plc_engine.py
- [[Resolve a block reference (id preferred, then name).]] - rationale - plc_engine.py
- [[Run exactly one PLC scan (no IO). Mirrors sim.js scanOnce()         run every]] - rationale - plc_engine.py
- [[SCALE_X OUT = VALUE(MAX-MIN)+MIN (mirrors sim.js scaleX).]] - rationale - plc_engine.py
- [[Set Mkey = value (inputmemory forcing from the app). Booleans stay         bo]] - rationale - plc_engine.py
- [[Time literal - seconds (codegen.js uses seconds for the PT argument).]] - rationale - plc_engine.py
- [[Topological order of boxes by wires; back-edges (cycles) are skipped         (mi]] - rationale - plc_engine.py
- [[Write M (by tag name) to every mapped GPIO output. Digital outputs         take]] - rationale - plc_engine.py
- [[Write a Q result to operand if set; the result is discarded otherwise         (t]] - rationale - plc_engine.py
- [[_cmp()]] - code - plc_engine.py
- [[_not_empty()]] - code - plc_engine.py
- [[idiv()]] - code - plc_engine.py
- [[norm_x()]] - code - plc_engine.py
- [[num()_1]] - code - plc_engine.py
- [[parse_time_ms()]] - code - plc_engine.py
- [[parse_time_s()]] - code - plc_engine.py
- [[plc_engine.py]] - code - plc_engine.py
- [[scale_x()]] - code - plc_engine.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/PLC_Engine_Core
SORT file.name ASC
```

## Connections to other communities
- 7 edges to [[_COMMUNITY_GPIO Backend & Mock]]
- 6 edges to [[_COMMUNITY_Pi HTTP Runtime Server]]

## Top bridge nodes
- [[Engine]] - degree 57, connects to 2 communities
- [[plc_engine.py]] - degree 12, connects to 2 communities
- [[.set_program()]] - degree 6, connects to 1 community