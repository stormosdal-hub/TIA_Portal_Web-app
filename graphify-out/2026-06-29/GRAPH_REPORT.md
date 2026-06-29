# Graph Report - .  (2026-06-28)

## Corpus Check
- 21 files · ~54,728 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 516 nodes · 1025 edges · 17 communities (16 shown, 1 thin omitted)
- Extraction: 98% EXTRACTED · 2% INFERRED · 0% AMBIGUOUS · INFERRED: 21 edges (avg confidence: 0.82)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_PLC Scan Engine|PLC Scan Engine]]
- [[_COMMUNITY_FBD Editor|FBD Editor]]
- [[_COMMUNITY_Ladder (LAD) Editor|Ladder (LAD) Editor]]
- [[_COMMUNITY_Simulation Engine|Simulation Engine]]
- [[_COMMUNITY_Core Architecture & Data Model|Core Architecture & Data Model]]
- [[_COMMUNITY_Python Code Generator|Python Code Generator]]
- [[_COMMUNITY_HTTP  PLC Server|HTTP / PLC Server]]
- [[_COMMUNITY_App Bootstrap & UI Shell|App Bootstrap & UI Shell]]
- [[_COMMUNITY_Project Tree Panel|Project Tree Panel]]
- [[_COMMUNITY_Toolbar & Ribbon|Toolbar & Ribbon]]
- [[_COMMUNITY_Tags Outline Panel|Tags Outline Panel]]
- [[_COMMUNITY_GPIO Hardware Abstraction|GPIO Hardware Abstraction]]
- [[_COMMUNITY_Block Interface Editor|Block Interface Editor]]
- [[_COMMUNITY_Tag Table Editor|Tag Table Editor]]
- [[_COMMUNITY_Tree Details View|Tree Details View]]
- [[_COMMUNITY_Online PLC Monitor|Online PLC Monitor]]
- [[_COMMUNITY_PLC Launcher Script|PLC Launcher Script]]

## God Nodes (most connected - your core abstractions)
1. `Engine` - 57 edges
2. `render()` - 18 edges
3. `evalBox()` - 17 edges
4. `render()` - 16 edges
5. `index.html — App Entry Point` - 16 edges
6. `Handler` - 14 edges
7. `notEmpty()` - 13 edges
8. `applyOutput()` - 13 edges
9. `Runtime` - 12 edges
10. `markDirty()` - 11 edges

## Surprising Connections (you probably didn't know these)
- `SPEC.md — Module Interface Contract` --semantically_similar_to--> `CLAUDE.md — Contributor / Agent Guide`  [INFERRED] [semantically similar]
  SPEC.md → CLAUDE.md
- `Handler` --uses--> `Engine`  [INFERRED]
  plc_server.py → plc_engine.py
- `Runtime` --uses--> `Engine`  [INFERRED]
  plc_server.py → plc_engine.py
- `README.md — User Documentation` --references--> `TIA Data Model — Project / Block / Network / Stage / Branch / Element / Box / Wire`  [INFERRED]
  README.md → SPEC.md
- `setQ()` --calls--> `notEmpty()`  [INFERRED]
  js/codegen.js → js/sim.js

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **All feature modules implement the IIFE pattern to avoid ES module constraints under file://** — js_core, js_lad, js_fbd, js_sim, iife_pattern, file_url_constraint [EXTRACTED 1.00]
- **sim:tick event emitted by sim.js, consumed by lad.js and fbd.js for live highlighting** — js_sim, js_lad, js_fbd, event_bus [EXTRACTED 1.00]
- **Ordered script load chain: core.js → feature modules → toolbar.js → app.js** — js_core, js_lad, js_fbd, js_sim, js_toolbar, js_app [EXTRACTED 1.00]

## Communities (17 total, 1 thin omitted)

### Community 0 - "PLC Scan Engine"
Cohesion: 0.05
Nodes (38): _cmp(), Engine, idiv(), norm_x(), _not_empty(), num(), parse_time_ms(), parse_time_s() (+30 more)

### Community 1 - "FBD Editor"
Cohesion: 0.06
Nodes (58): addNetwork(), addOperandLabel(), appendInput(), attachPendingTracker(), attachTagDrop(), boxGeom(), boxLabel(), buildBox() (+50 more)

### Community 2 - "Ladder (LAD) Editor"
Cohesion: 0.07
Nodes (49): addHit(), addNetwork(), applyEditValue(), attachTagDrop(), buildNetworkSVG(), callArgLabel(), callBoxRows(), closeMenu() (+41 more)

### Community 3 - "Simulation Engine"
Cohesion: 0.08
Nodes (44): Cyclic Scan Simulator — scan loop evaluating all networks per LAD/FBD semantics, applyOutput(), branchValue(), buildScope(), clearLiveFlags(), cmp(), collectCalledIds(), collectRows() (+36 more)

### Community 4 - "Core Architecture & Data Model"
Cohesion: 0.06
Nodes (29): CLAUDE.md — Contributor / Agent Guide, TIA Data Model — Project / Block / Network / Stage / Branch / Element / Box / Wire, T.bus — Cross-Module Event Bus (on/off/emit), file:// Constraint — no ES modules, no fetch, no CDN, no bundler, IIFE Module Pattern — (function(T){...})(window.TIA) — no ES modules, file:// safe, index.html — App Entry Point, clone(), close() (+21 more)

### Community 5 - "Python Code Generator"
Cohesion: 0.12
Nodes (25): blockBody(), blockCtx(), buildPinTable(), callLines(), cvVar(), ensureGpio(), fbdBox(), fbdNetwork() (+17 more)

### Community 6 - "HTTP / PLC Server"
Cohesion: 0.10
Nodes (7): BaseHTTPRequestHandler, Handler, main(), Serve files from STATIC_DIR. GET / -> index.html. Path traversal is         prev, Holds the engine, the running flag, and the scan thread. All engine access     i, Background thread: read inputs, scan, write outputs at ~SCAN_HZ while         ru, Runtime

### Community 7 - "App Bootstrap & UI Shell"
Cohesion: 0.18
Nodes (19): activateTab(), adoptProject(), boot(), buildDemoProject(), buildMenu(), closeDropdown(), closeTab(), initAutosave() (+11 more)

### Community 8 - "Project Tree Panel"
Cohesion: 0.18
Nodes (17): buildModal(), closeContextMenu(), closeModal(), ctxItem(), icon(), nodeRow(), onDocDownForCtx(), onEscForCtx() (+9 more)

### Community 9 - "Toolbar & Ribbon"
Cohesion: 0.14
Nodes (5): btn(), build(), group(), updateOnlineBtns(), updateSimBtn()

### Community 10 - "Tags Outline Panel"
Cohesion: 0.27
Nodes (11): bucketTags(), headerRow(), icon(), matches(), memberMatches(), memberRow(), render(), tagMatches() (+3 more)

### Community 11 - "GPIO Hardware Abstraction"
Cohesion: 0.19
Nodes (5): _MockAnalog, _MockPin, Dependency-free stand-in for a gpiozero device (mirrors codegen _MockPin)., Float-capable stand-in for a gpiozero PWMOutputDevice (duty 0.0..1.0).     Mirro, Build input/output pin devices from project['gpio'] (mirrors codegen.js

### Community 12 - "Block Interface Editor"
Cohesion: 0.29
Nodes (6): addMember(), notifyIface(), removeMember(), render(), renderDb(), renderIface()

### Community 13 - "Tag Table Editor"
Cohesion: 0.33
Nodes (9): addressLooksValid(), addTag(), buildRow(), deleteSelected(), emitChanged(), open(), refreshDot(), render() (+1 more)

### Community 14 - "Tree Details View"
Cohesion: 0.43
Nodes (7): freshRef(), icon(), leafRow(), memberRow(), render(), tagRow(), twisty()

### Community 15 - "Online PLC Monitor"
Cohesion: 0.43
Nodes (5): api(), applyState(), emit(), poll(), snap()

## Knowledge Gaps
- **2 isolated node(s):** `run_plc.sh script`, `window.TIA Global Namespace (alias T)`
  These have ≤1 connection - possible missing edges or undocumented components.
- **1 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `index.html — App Entry Point` connect `Core Architecture & Data Model` to `FBD Editor`, `Ladder (LAD) Editor`, `Simulation Engine`, `Python Code Generator`, `App Bootstrap & UI Shell`, `Project Tree Panel`, `Toolbar & Ribbon`, `Tags Outline Panel`, `Block Interface Editor`, `Tag Table Editor`, `Tree Details View`, `Online PLC Monitor`?**
  _High betweenness centrality (0.337) - this node is a cross-community bridge._
- **Why does `CLAUDE.md — Contributor / Agent Guide` connect `Core Architecture & Data Model` to `FBD Editor`, `Ladder (LAD) Editor`, `Simulation Engine`, `App Bootstrap & UI Shell`, `Toolbar & Ribbon`?**
  _High betweenness centrality (0.090) - this node is a cross-community bridge._
- **Why does `T.bus — Cross-Module Event Bus (on/off/emit)` connect `Core Architecture & Data Model` to `FBD Editor`, `Ladder (LAD) Editor`, `Simulation Engine`?**
  _High betweenness centrality (0.052) - this node is a cross-community bridge._
- **Are the 2 inferred relationships involving `Engine` (e.g. with `Handler` and `Runtime`) actually correct?**
  _`Engine` has 2 INFERRED edges - model-reasoned connections that need verification._
- **What connects `Coerce any memory value to a number. bool -> int; None/'' -> 0.`, `Divide-by-zero-guarded division (mirrors codegen.js idiv / sim.js mathOp).`, `NORM_X: OUT = (VALUE-MIN)/(MAX-MIN); 0 if MAX==MIN. Not clamped (matches sim.js)` to the rest of the system?**
  _37 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `PLC Scan Engine` be split into smaller, more focused modules?**
  _Cohesion score 0.0515406162464986 - nodes in this community are weakly interconnected._
- **Should `FBD Editor` be split into smaller, more focused modules?**
  _Cohesion score 0.061971830985915494 - nodes in this community are weakly interconnected._