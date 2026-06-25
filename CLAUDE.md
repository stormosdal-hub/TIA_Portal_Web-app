# CLAUDE.md — TIA Web Practice (project operating manual)

A browser-based, Siemens-TIA-Portal-style PLC IDE for practicing **Ladder (LAD)** and
**Function Block Diagram (FBD)** with a real cyclic-scan **simulator**. It runs by
**double-clicking `index.html`** — no server, no build step, no internet.

> User docs: `README.md`. Module interface contract: `SPEC.md`. This file is the
> contributor/agent guide — read it before changing code.

## Hard constraints (never violate)
- Runs from **`file://`**. So: **no ES modules / `import` / `export`**, **no `fetch()`** of local
  files, **no bundler**, **no npm**, **no CDN / external libraries**. Classic `<script>` tags only.
- Everything attaches to the global **`window.TIA`** (alias `T`). Each module is an IIFE:
  `(function (T) { 'use strict'; /* ... */ })(window.TIA);`
- Build DOM with **`T.el(tag, attrs, ...children)`** and SVG with **`T.svg(...)`** (see `core.js`).
- Inject component CSS with **`T.injectCSS('unique-id', css)`** using the `--tia-*` theme variables
  from `css/tia.css`. Don't edit `css/tia.css` for component styling.
- Don't call other feature modules at **load time** — only at runtime (event handlers / after boot).
- Always create model objects via the **`T.model.*`** factories so shapes stay valid for the simulator.

## Architecture / where things live
Load order (`index.html`): `core.js` → feature modules → `toolbar.js` → `app.js` (bootstrap, last).
- **`js/core.js`** — THE contract: `window.TIA` namespace, DOM helpers, the **element catalog**
  (`T.catalog`, the canonical instruction `kind` strings), data-model factories (`T.model.*`),
  project access, **sim memory** (`T.mem`) + operand resolution (`T.resolve`, `T.readBit/writeBit/
  readNum/writeNum`), local-scope (`T._scope`, `T.memberKey`), persistence, autocomplete
  (`T.attachAutocomplete`, `T.operandCandidates`), icons.
- **`js/tags.js`** tag table · **`js/tree.js`** project tree · **`js/iface.js`** block-interface
  editor + DB viewer · **`js/outline.js`** Tags outline · **`js/details.js`** tree Details view ·
  **`js/instructions.js`** instruction tree · **`js/lad.js`** ladder editor · **`js/fbd.js`** FBD
  editor · **`js/sim.js`** scan engine + simulation table · **`js/toolbar.js`** ribbon ·
  **`js/app.js`** bootstrap (tabs, inspector, splitters, demo project, autosave, compile).
- Editors expose `T.editors.<name>` and set `T.activeEditor`. The simulator is `T.sim`.
  Cross-module communication is via the event bus **`T.bus.on/emit`** (events incl. `project:loaded`,
  `block:activated`, `open:block`, `open:tags`, `tree:changed`, `tree:select`, `tags:changed`,
  `iface:changed`, `sim:tick`, `sim:state`).

## Data model (core.js)
`Project{name,device,tags[],blocks[],activeBlockId}` · `Block{type:OB|FC|FB|DB,lang:LAD|FBD,
networks[],iface}` · `Network{stages[],outputs[]  (LAD) ; boxes[],wires[]  (FBD)}` ·
`Stage{branches[]}` (ORed) · `Branch{elements[]}` (ANDed) · `Element{kind,operand,params,args}` ·
`Box{kind,x,y,operand,params,inputs[],outputs[]}`. LAD power flow:
`rungPower = AND over stages ( OR over branches ( AND over inline element values ) )`; empty stages ⇒ true.
Block interface: `block.iface = {input,output,inout,temp,constant, static(FB)}`, members
`{id,name,dataType,default,comment}`. FB calls get an instance DB (`type:'DB', instanceOf:fbId`).

## Verifying changes (no Node here — use headless Chromium, already installed at /usr/bin/chromium)
Write a temporary `<name>.html` in the project dir that mirrors `index.html`'s mount-point divs,
loads the js in order, and runs assertions into a `#r` div + `document.title`. Then:
```
URL="file:///home/stormpi5/Documents/Browser%20apps/web-based%20TIA%20Portal/<name>.html"   # %20 for spaces
chromium --headless=new --disable-gpu --no-sandbox --virtual-time-budget=9000 --dump-dom "$URL"
```
Parse the `#r` div (python3 + regex + html.unescape). For visuals add
`--screenshot=/tmp/x.png --window-size=1680,950` and crop with PIL. Drive the UI with synthetic
events: `MouseEvent`, `KeyboardEvent`, and `DragEvent` with a real `new DataTransfer()` (the editors'
drop targets read `text/tia-kind`, `text/tia-block`, `text/tia-tag`). **Any in-page `setTimeout` must
fire before `--virtual-time-budget`.** Delete the temp harness when done. The **tia-verifier** subagent
automates this — prefer it after every change.

## Known gotchas (these bit us before)
- `T.el(tag,{draggable:true})` must emit the string `"true"` (empty `draggable=""` = NOT draggable).
  Handled in `T.el`; pass `draggable:true`.
- **Click-to-edit must not re-render before opening the floating `<input>`** — a click handler that
  calls `select()/selectBox()` (which `render()`) detaches the clicked SVG node so the input lands in
  discarded DOM. Use the no-render variant: LAD `select(el,true)`, FBD `selectBox(net,box,true)`.
- FBD `render()` must **not** `cancelPending()` — `onPinClick` sets `pending` then renders to draw the
  rubber-band; cancelling there breaks wiring.
- Sim coloring: LAD wires colour by `net._power` (stamped in `evalLadNetwork`); output boxes colour by
  EN, not their delayed Q. While running, energized = green (`*-live`), de-energized = dashed blue
  (`*-low`); cleared on stop.
- `T.mem.reset()` clears memory only; `T.sim.reset()` clears timer/counter/edge **instance state**
  (it runs on Start). When testing edges/counters, reset instance state too.
- Block-local member operands resolve via `T._scope` (set during `sim.executeBlock`) which `T.resolve`
  checks **before** global tags.
- Operand autocomplete is attached **before** the inline-edit's commit keydown; it only pre-empts
  Enter when a suggestion is highlighted (otherwise Enter commits typed text).
- Code-block editor uses a split layout: `#tia-editor.tia-split-host` (flex column) → `.tia-iface-mount`
  (own scroll) above `.tia-code-mount` (own scroll), so editing the interface never scrolls the network.

## Adding a new instruction (LAD/FBD) — the recipe
1. **`core.js`**: add a `T.catalog.<kind>` entry (`name, group, area:'inline'|'output', box, operandRole,
   dataType, defParams, pins:{in,out}, lad/fbd availability`).
2. **`sim.js`**: add a `case '<kind>'` in `applyOutput` (LAD) and/or `evalBox` (FBD). Use
   `T.readBit/writeBit/readNum/writeNum`; per-instance state via `inst(el.id)` / `inst(box.id)`.
3. **`lad.js`**: titleMap + `inputParamMap`/`outputParamMap` for box pins; operand-on-top if the box
   stores a bit.
4. **`fbd.js`**: add to `hasTitleBar` (titled box); `boxLabel`'s default already upper-cases; add to the
   operand-above list if it stores a bit.
5. **Verify** with the tia-verifier pattern. Template to copy: the SR/RS + P/N/R/F_TRIG work.

## Style
Match the surrounding code: small focused functions, brief comments, the existing naming. Prefer minimal
additive edits over rewrites. After a change, run the verifier and report what you changed + any risks.
