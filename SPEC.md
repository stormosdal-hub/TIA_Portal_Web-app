# TIA-like Browser PLC IDE — Module Interface Contract (SPEC)

This file is the **authoritative contract** for every module. Read `js/core.js`
(the real code) for exact data shapes and helpers, `index.html` for the DOM mount
points, and `css/tia.css` for theme variables. Then implement your module to match.

## Hard rules
- **No ES modules, no bundler, no `import`/`export`, no `fetch()`** — the app runs
  from `file://` by double-clicking `index.html`. Use only classic globals on `window.TIA`.
- **No external libraries / no CDN / no internet.** Pure vanilla JS + SVG/DOM.
- Every module is an IIFE that augments `window.TIA`. Pattern:
  ```js
  (function (T) { 'use strict'; /* ... */ })(window.TIA);
  ```
- Do **not** call other feature modules at load time. Only call them at runtime
  (inside event handlers / functions invoked after `app.js` boots).
- Inject your own component CSS via `T.injectCSS('id', '...css...')` using the
  `--tia-*` theme variables. Do **not** edit `css/tia.css`.
- Build DOM with `T.el(tag, attrs, ...children)` and `T.svg(...)` (see core.js).

## Core API recap (already implemented in core.js — DO NOT reimplement)
- `T.bus.on/off/emit(evt, data)` — event bus.
- `T.el, T.svg, T.append, T.clear, T.injectCSS, T.$, T.$$` — DOM helpers.
- `T.uid(prefix)` — unique id.
- `T.catalog` — map of `kind -> def` (THE element catalog). `T.catalogGroups`,
  `T.catalogFor('LAD'|'FBD') -> [{kind, def}]`.
- `T.model.newProject/newTag/newBlock/newNetwork/newStage/newBranch/newElement/newBox/newWire`.
- `T.project` (live project), `T.setProject(p)`, `T.getActiveBlock()`,
  `T.setActiveBlock(id)`, `T.findBlock(id)`, `T.tagByName`, `T.tagByAddress`,
  `T.nextBlockNumber(type)`.
- `T.mem` — sim memory: `getBit/setBit/getWord/setWord/reset`, `.bits`, `.words`.
- `T.resolve(operand, expect)`, `T.readBit/writeBit/readNum/writeNum`,
  `T.parseTime/fmtTime` — operand resolution for the simulator.
- `T.storage.save/load/exportFile/importFile(cb)`.
- `T.icons.*` (SVG strings), `T.status(msg, kind)`.

## Data model (from core.js — reference)
```
Project { name, device:{name,type}, tags:[Tag], blocks:[Block], activeBlockId }
Tag     { id, name, dataType:'Bool|Int|Real|Word|Time', address:'I0.0|Q0.0|M0.0|MW0|...', comment }
Block   { id, type:'OB|FC|FB|DB', name, number, lang:'LAD|FBD', comment, networks:[Network] }
Network {
  id, title, comment,
  // LAD representation:
  stages:  [ Stage ],     // series-connected condition groups (ANDed)
  outputs: [ Element ],   // output-area elements, vertically stacked (each gets rung power)
  // FBD representation:
  boxes:   [ Box ],
  wires:   [ Wire ],
}
Stage   { id, branches:[ Branch ] }        // branches are ORed together
Branch  { id, elements:[ Element ] }       // elements are ANDed (series)
Element { id, kind, operand:'tag-or-address', params?:{...} }   // kind ∈ T.catalog
Box     { id, kind, x, y, operand, params?, inputs:[Pin], outputs:[Pin] }
Pin(in) { id, name, inverted, operand }    // operand used if pin is not wired
Pin(out){ id, name }
Wire    { id, from:{box,pin}, to:{box,pin} }   // box/pin are ids
```

### LAD power-flow semantics (the simulator follows this; editors must build this shape)
- `rungPower = AND over stages of ( OR over branches of ( AND over inline elements ) )`
- An empty `stages` array ⇒ `rungPower = true` (direct connection to left rail).
- Inline kinds (`area:'inline'`): `contact_no, contact_nc, edge_p, edge_n, compare`.
- Output kinds (`area:'output'`): coils, timers, counters, move, math. Each output
  element in `network.outputs` receives `rungPower` as its enable/IN.
- Per-instance state (edges, timers, counters) is keyed by `element.id` in the simulator.

## Cross-module contracts

### Active editor (set by lad.js / fbd.js when a block opens)
`T.activeEditor` is an object the toolbar & instruction tree call into:
```
T.activeEditor = {
  lang: 'LAD' | 'FBD',
  block: <Block>,
  insert(kind),        // insert a catalog element of `kind` at current insertion point/selection
  deleteSelection(),   // delete currently selected element(s)
  addNetwork(),        // append a new empty network and focus it
  refresh(),           // full re-render
  highlight(),         // re-apply live/energized classes after a sim tick (cheap)
}
```
- `lad.js` and `fbd.js` each expose `T.editors.lad` and `T.editors.fbd` with:
  `open(hostEl, block)` → renders the block into `hostEl` (the `#tia-editor` host)
  and sets `T.activeEditor` to itself. `app.js` decides which to call based on `block.lang`.

### Instruction tree (instructions.js)
- Renders into `#tia-instructions`. Groups by `T.catalogGroups`, lists
  `T.catalogFor(activeLang)`. Updates when `T.bus.emit('block:activated')` fires
  (read `T.getActiveBlock().lang`).
- Clicking an instruction calls `T.activeEditor && T.activeEditor.insert(kind)`.
- Also set `draggable` and on `dragstart` put `e.dataTransfer.setData('text/tia-kind', kind)`
  so editors can support drag-drop (editors read this type).

### Project tree (tree.js)
- Renders into `#tia-tree`. Structure (collapsible):
  `Project ▸ Device (PLC_1 [CPU type]) ▸ { Program blocks ▸ [blocks...], PLC tags ▸ [Default tag table] }`.
- Clicking a Program block: `T.setActiveBlock(block.id)` then
  `T.bus.emit('open:block', block)`.
- Clicking "PLC tags": `T.bus.emit('open:tags')`.
- Provide right-click / button affordances to add OB/FC/FB (use `T.model.newBlock`,
  `T.nextBlockNumber`) and delete/rename. Emit `T.bus.emit('tree:changed')` after edits.
- Re-render on `project:loaded`, `tree:changed`, `block:activated`.

### Tag table (tags.js)
- Renders an editable PLC tag table into a host element via `T.editors.tags.open(hostEl)`.
- Columns: Name, Data type (select of `T.DataTypes`), Address, Comment. Editable cells.
- Add-row / delete-row buttons. Writes to `T.project.tags`. Emit `T.bus.emit('tags:changed')`.
- Re-render on `project:loaded`.

### Simulator (sim.js)
Public API:
```
T.sim = {
  running: false,
  start(),            // reset state, begin scan loop (setInterval ~ 50–100ms)
  stop(),
  toggle(),
  scanOnce(),         // run exactly one scan cycle (also used internally)
  reset(),            // clear sim memory + instance state
}
```
- On each scan: execute `T.project` starting at OB1 (block type 'OB', number 1) and any
  other OBs by number; evaluate every network per the LAD power-flow semantics above
  (and FBD via boxes/wires). Write results to `T.mem`.
- Tag whose `address` is empty: key memory by `'@'+NAME` (already handled by `T.resolve`).
- After each scan, set `element._live` / `box._live` / `pin._val` booleans on the model
  so editors can show energized (green) flow, then `T.bus.emit('sim:tick')`.
  Editors listen to `sim:tick` and call their own `highlight()`.
- Maintain instance state keyed by `element.id` (edges: prevInput; timers: startTime/elapsed
  using `performance.now()`; counters: count value).
- Implement the **Simulation table** UI (rendered into the inspector when its tab is
  active — coordinate via `T.bus.emit('inspector:sim')` / `app.js` passes the host).
  Expose `T.sim.renderTable(hostEl)` that builds a table of all tags (and live I/Q/M
  addresses) with current values; bool values are clickable toggles when running;
  numeric values are editable inputs. Re-render on `sim:tick` and `tags:changed`.
- Emit `T.bus.emit('sim:state', {running})` on start/stop so the toolbar/status update.

### Toolbar (toolbar.js) and bootstrap (app.js) are implemented separately (not by you).
They will call the APIs above. Make sure your public methods match exactly.

## Visual fidelity notes
- LAD: draw with **SVG** — left & right vertical rails, horizontal wires, classic
  symbols: contact `─┤ ├─`, NC contact `─┤/├─`, coil `─( )─`, set `─(S)─`,
  reset `─(R)─`, P/N edge `─┤P├─`. Boxes (timers/compare/math) are labeled rectangles
  with named input/output pins. Network header shows `Network N: <title>` with a
  comment line. Energized wires/elements turn green (`--tia-live`) during simulation.
- FBD: draw boxes as rectangles with input pins on the left, output pins on the right,
  small circle on a pin = inverted. Wires are orthogonal/curved lines between pins.
  Each unconnected input pin shows its `operand` label above it; output assignment box
  shows the written tag.
- Match TIA grey/petrol palette already defined in `css/tia.css`.

## Definition of done for each module
- Loads with no console errors when included before `app.js`.
- Renders correct, interactive UI.
- Uses only `T.*` APIs above; introduces no new global except its own `T.editors.*`/`T.sim`.
- Reasonable, readable code with brief comments. No TODOs left in critical paths.
