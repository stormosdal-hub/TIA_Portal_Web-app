# Graph Report - TIA_Portal_Web-app  (2026-06-29)

## Corpus Check
- 24 files · ~55,355 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 572 nodes · 1077 edges · 23 communities (21 shown, 2 thin omitted)
- Extraction: 98% EXTRACTED · 2% INFERRED · 0% AMBIGUOUS · INFERRED: 21 edges (avg confidence: 0.82)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `af0ca2df`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

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
- [[_COMMUNITY_Community 17|Community 17]]
- [[_COMMUNITY_Community 19|Community 19]]
- [[_COMMUNITY_Community 20|Community 20]]
- [[_COMMUNITY_Community 22|Community 22]]
- [[_COMMUNITY_Community 23|Community 23]]
- [[_COMMUNITY_Community 24|Community 24]]

## God Nodes (most connected - your core abstractions)
1. `Engine` - 57 edges
2. `render()` - 18 edges
3. `evalBox()` - 17 edges
4. `TIA Web Practice — a browser-based TIA-Portal-style PLC IDE` - 17 edges
5. `render()` - 16 edges
6. `index.html — App Entry Point` - 16 edges
7. `Handler` - 14 edges
8. `notEmpty()` - 13 edges
9. `applyOutput()` - 13 edges
10. `Runtime` - 12 edges

## Surprising Connections (you probably didn't know these)
- `Handler` --uses--> `Engine`  [INFERRED]
  plc_server.py → plc_engine.py
- `Runtime` --uses--> `Engine`  [INFERRED]
  plc_server.py → plc_engine.py
- `setQ()` --calls--> `notEmpty()`  [INFERRED]
  js/codegen.js → js/sim.js
- `outputLines()` --calls--> `notEmpty()`  [INFERRED]
  js/codegen.js → js/sim.js
- `fbdBox()` --calls--> `notEmpty()`  [INFERRED]
  js/codegen.js → js/sim.js

## Import Cycles
- None detected.

## Communities (23 total, 2 thin omitted)

### Community 0 - "PLC Scan Engine"
Cohesion: 0.06
Nodes (58): addNetwork(), addOperandLabel(), appendInput(), attachPendingTracker(), attachTagDrop(), boxGeom(), boxLabel(), buildBox() (+50 more)

### Community 1 - "FBD Editor"
Cohesion: 0.07
Nodes (49): addHit(), addNetwork(), applyEditValue(), attachTagDrop(), buildNetworkSVG(), callArgLabel(), callBoxRows(), closeMenu() (+41 more)

### Community 2 - "Ladder (LAD) Editor"
Cohesion: 0.08
Nodes (44): Cyclic Scan Simulator — scan loop evaluating all networks per LAD/FBD semantics, applyOutput(), branchValue(), buildScope(), clearLiveFlags(), cmp(), collectCalledIds(), collectRows() (+36 more)

### Community 3 - "Simulation Engine"
Cohesion: 0.06
Nodes (27): CLAUDE.md — Contributor / Agent Guide, TIA Data Model — Project / Block / Network / Stage / Branch / Element / Box / Wire, T.bus — Cross-Module Event Bus (on/off/emit), file:// Constraint — no ES modules, no fetch, no CDN, no bundler, IIFE Module Pattern — (function(T){...})(window.TIA) — no ES modules, file:// safe, index.html — App Entry Point, clone(), close() (+19 more)

### Community 4 - "Core Architecture & Data Model"
Cohesion: 0.12
Nodes (25): blockBody(), blockCtx(), buildPinTable(), callLines(), cvVar(), ensureGpio(), fbdBox(), fbdNetwork() (+17 more)

### Community 5 - "Python Code Generator"
Cohesion: 0.26
Nodes (3): BaseHTTPRequestHandler, Handler, Serve files from STATIC_DIR. GET / -> index.html. Path traversal is         prev

### Community 6 - "HTTP / PLC Server"
Cohesion: 0.18
Nodes (19): activateTab(), adoptProject(), boot(), buildDemoProject(), buildMenu(), closeDropdown(), closeTab(), initAutosave() (+11 more)

### Community 7 - "App Bootstrap & UI Shell"
Cohesion: 0.18
Nodes (17): buildModal(), closeContextMenu(), closeModal(), ctxItem(), icon(), nodeRow(), onDocDownForCtx(), onEscForCtx() (+9 more)

### Community 8 - "Project Tree Panel"
Cohesion: 0.05
Nodes (38): _cmp(), Engine, idiv(), norm_x(), _not_empty(), num(), parse_time_ms(), parse_time_s() (+30 more)

### Community 9 - "Toolbar & Ribbon"
Cohesion: 0.14
Nodes (5): btn(), build(), group(), updateOnlineBtns(), updateSimBtn()

### Community 10 - "Tags Outline Panel"
Cohesion: 0.11
Nodes (18): Addresses & data types, Analog output (software PWM) + scaling, Architecture (for extending), Assigning tags by drag-and-drop, Editing, Online mode — run + monitor + change the program live (Pi runtime), Project tree & simulation table tips, Run it (+10 more)

### Community 11 - "GPIO Hardware Abstraction"
Cohesion: 0.14
Nodes (14): Active editor (set by lad.js / fbd.js when a block opens), Core API recap (already implemented in core.js — DO NOT reimplement), Cross-module contracts, Data model (from core.js — reference), Definition of done for each module, Hard rules, Instruction tree (instructions.js), LAD power-flow semantics (the simulator follows this; editors must build this shape) (+6 more)

### Community 12 - "Block Interface Editor"
Cohesion: 0.22
Nodes (8): Adding a new instruction (LAD/FBD) — the recipe, Architecture / where things live, CLAUDE.md — TIA Web Practice (project operating manual), Data model (core.js), Hard constraints (never violate), Known gotchas (these bit us before), Style, Verifying changes (no Node here — use headless Chromium, already installed at /usr/bin/chromium)

### Community 13 - "Tag Table Editor"
Cohesion: 0.09
Nodes (9): _MockAnalog, _MockPin, Dependency-free stand-in for a gpiozero device (mirrors codegen _MockPin)., Float-capable stand-in for a gpiozero PWMOutputDevice (duty 0.0..1.0).     Mirro, Build input/output pin devices from project['gpio'] (mirrors codegen.js, main(), Holds the engine, the running flag, and the scan thread. All engine access     i, Background thread: read inputs, scan, write outputs at ~SCAN_HZ while         ru (+1 more)

### Community 14 - "Tree Details View"
Cohesion: 0.27
Nodes (11): bucketTags(), headerRow(), icon(), matches(), memberMatches(), memberRow(), render(), tagMatches() (+3 more)

### Community 15 - "Online PLC Monitor"
Cohesion: 0.29
Nodes (6): addMember(), notifyIface(), removeMember(), render(), renderDb(), renderIface()

### Community 16 - "PLC Launcher Script"
Cohesion: 0.33
Nodes (9): addressLooksValid(), addTag(), buildRow(), deleteSelected(), emitChanged(), open(), refreshDot(), render() (+1 more)

### Community 17 - "Community 17"
Cohesion: 0.43
Nodes (7): freshRef(), icon(), leafRow(), memberRow(), render(), tagRow(), twisty()

### Community 19 - "Community 19"
Cohesion: 0.43
Nodes (5): api(), applyState(), emit(), poll(), snap()

### Community 20 - "Community 20"
Cohesion: 0.29
Nodes (6): dependencies, @modelcontextprotocol/sdk, main, name, type, version

### Community 22 - "Community 22"
Cohesion: 0.40
Nodes (4): __dirname, server, transport, VAULT

## Knowledge Gaps
- **46 isolated node(s):** `node`, `name`, `version`, `type`, `main` (+41 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **2 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `index.html — App Entry Point` connect `Simulation Engine` to `PLC Scan Engine`, `FBD Editor`, `Ladder (LAD) Editor`, `Core Architecture & Data Model`, `HTTP / PLC Server`, `App Bootstrap & UI Shell`, `Toolbar & Ribbon`, `Tree Details View`, `Online PLC Monitor`, `PLC Launcher Script`, `Community 17`, `Community 19`?**
  _High betweenness centrality (0.320) - this node is a cross-community bridge._
- **Why does `CLAUDE.md — Contributor / Agent Guide` connect `Simulation Engine` to `PLC Scan Engine`, `FBD Editor`, `Ladder (LAD) Editor`, `HTTP / PLC Server`, `Toolbar & Ribbon`?**
  _High betweenness centrality (0.097) - this node is a cross-community bridge._
- **Why does `TIA Web Practice — a browser-based TIA-Portal-style PLC IDE` connect `Tags Outline Panel` to `Simulation Engine`?**
  _High betweenness centrality (0.043) - this node is a cross-community bridge._
- **Are the 2 inferred relationships involving `Engine` (e.g. with `Handler` and `Runtime`) actually correct?**
  _`Engine` has 2 INFERRED edges - model-reasoned connections that need verification._
- **What connects `node`, `name`, `version` to the rest of the system?**
  _81 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `PLC Scan Engine` be split into smaller, more focused modules?**
  _Cohesion score 0.061971830985915494 - nodes in this community are weakly interconnected._
- **Should `FBD Editor` be split into smaller, more focused modules?**
  _Cohesion score 0.07093253968253968 - nodes in this community are weakly interconnected._