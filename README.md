# TIA Web Practice — a browser-based TIA-Portal-style PLC IDE

A self-contained, offline practice environment for **Ladder Logic (LAD)** and
**Function Block Diagram (FBD)** with a real **cyclic-scan simulator**. It mimics
the look and workflow of Siemens TIA Portal.

## Run it
**Double-click `index.html`** — it opens in your browser. No install, no server,
no internet. Works directly from the filesystem (`file://`). Chromium/Chrome and
Firefox are both fine.

## What's included
- **Project tree** (left): Device → Program blocks (OB/FC/FB) → PLC tags.
  Click a block to open it; right-click to rename/delete; `＋ Add new block` to create one.
- **Tabbed editors** (center): a LAD editor and an FBD editor that render like TIA.
- **Instruction tree** (right): bit logic, comparator, timers, counters, move, math.
  Click or drag an instruction into the editor.
- **Simulation table** (bottom dock): live monitor/modify of all tags. While the
  PLC is running, click a Bool to toggle an input, or type analog values.
- **Ribbon toolbar**: New / Open / Save / Export, Insert network, Delete, Compile,
  and **Start/Stop** the simulator.

## The demo project (`Conveyor_Demo`)
Loads automatically the first time:
- **Network 1** — Motor seal-in: `(Start_PB ∥ Motor) · /Stop_PB → Motor`
- **Network 2** — Run lamp on-delay: `Motor → TON(3s) → Run_Lamp`
- **Network 3** — Part counter: `Part_Sensor → CTU(PV=5) → Part_Count`
- **Network 4** — Batch done: `Part_Count ≥ 5 → Count_Done`
- **Network 5** — Calls **FB “Logic”** with parameters: `In1:=Start_PB, In2:=Part_Sensor, Out=>AND_Out`
- **FB1 “Logic” (FBD)** — a parameterized block (interface `In1, In2 → Out`, plus a `Static` var):
  `Out := In1 AND In2`. Its instance data block is **`Logic_DB`** (in the project tree).

### Try it
1. Press **Start** (Simulation group). The status bar shows `● RUN`.
2. In the **Simulation table** (bottom), toggle **Start_PB** on → the motor latches
   and the rung turns **green** (live power flow). Toggle **Stop_PB** on → it drops.
3. Watch **Run_Lamp** turn on 3 s after the motor starts (TON).
4. Toggle **Part_Sensor** a few times → **Part_Count** climbs; at 5, **Count_Done** sets.

## Assigning tags by drag-and-drop
The left dock has two tabs: **Project tree** and **Tags**. The **Tags** outline lists every PLC tag
grouped into **Inputs / Outputs / Memory** (collapsible, with a filter box), and — when a code block
is open — that block's **interface variables** (Input/Output/InOut/Static…). At the bottom of the dock is
a TIA-style **Details view** that shows the contents of whatever you last clicked in the tree (the tag
table → its tags; a data block → its members; a block → its interface). **Drag a tag (or a block
variable) onto a contact, coil, FBD input pin, assignment box, timer/counter parameter, or a call's
parameter pin** to assign it — no typing. You can also drag straight from a block's **interface table**
(use the ⠿ grip on each row).

## Typing with autocomplete
Click a `???` (or any operand) to edit it: a **suggestion dropdown** appears listing matching PLC tags and
the block's interface variables. Type to filter, use ↑/↓ + Enter (or click) to pick — just press Enter to
keep what you typed.

## Editing
- **Undo / redo**: **Ctrl+Z** / **Ctrl+Y** (or Ctrl+Shift+Z) in the LAD and FBD editors
  (per block, up to 60 steps — network deletes included).
- **Copy / cut / paste**: **Ctrl+C / Ctrl+X / Ctrl+V** duplicates the selected LAD element
  or FBD box (fresh ids; successive pastes cascade).
- **Zoom**: **Ctrl+scroll** over the editor, or **Ctrl + / Ctrl − / Ctrl 0** (40–200%).
- **Rename safely**: renaming a PLC tag (tag table) or a block-interface member updates
  every operand, call parameter and GPIO mapping that referenced it.
- **Cross-references**: Inspector ▸ **Properties** ▸ *Where used* lists every place a tag or
  member is referenced (block, network, slot — SCL hits with line numbers); click to jump.
- **Insert**: click an instruction on the right, **or drag-and-drop it onto a network** —
  dropping on the **left half** of an existing contact inserts *before* it, right half *after*.
  Contacts/compare go in the condition area; coils/timers/counters/move/math go to
  the output side.
- **Set operands**: click the `???`/label above a contact or coil and type a tag
  name (e.g. `Start_PB`) or an absolute address (e.g. `I0.0`, `Q0.0`, `M0.1`, `MW10`).
- **Parallel branch (OR)**: right-click an element → *Open parallel branch*.
- **New network**: toolbar *Network* button (or `T.activeEditor.addNetwork()`).
- **Delete**: select an element and press **Delete**, or the toolbar *Delete* button.
- **FBD**: drag boxes to move; click an **output pin** then an **input pin** to wire
  them; click a pin's operand label to assign a tag. On expandable boxes (AND/OR/XOR/ADD/MUL)
  use **＋** to add an input pin and **−** to remove the last one (or right-click a pin →
  *Delete pin*).
- **Block interface**: every FC/FB/OB has a **Block interface** panel at the top of its editor
  (collapsible) where you declare typed local variables in sections — **Input, Output, InOut,
  Static** (FB only), **Temp, Constant** — each with a name, data type, default and comment.
  Reference these by name inside the block's networks; they're local to the block (and shadow
  global tags of the same name).
- **Call another block**: drag an FC/FB (or OB) from the project tree onto a network — it drops
  in as a call box showing **EN/ENO plus a pin for every Input/Output/InOut parameter**. Click a
  pin's `???` to wire a tag (or another local variable) to that parameter. Dropping a **function
  block** also auto-creates its **instance data block** (e.g. `Logic_DB`), shown in the project
  tree; double-click it to monitor the instance's live values. **Double-click a call box** (or a
  block in the tree) to jump into that block.
- **Parameter passing simulates for real**: when a call's `EN` is true, the wired input tags are
  copied into the block's inputs, the block runs against its own instance storage, and its outputs
  are written back to your wired tags. FB **Static** variables persist across scans in the instance
  DB. Blocks you haven't called anywhere still run automatically so everything you write simulates.

## Simulation view (online-style)
While the PLC is running, the editors color the logic like TIA's online monitoring:
- **Energized (TRUE/power-flowing)** → solid **green** wires and symbols.
- **De-energized (FALSE)** → dashed **blue** wires; contacts/coils/boxes show blue.
Stopping the simulator returns the diagram to its normal black drawing.

## Run it on a Raspberry Pi (Export Python)
Toolbar **Raspberry Pi → Export Python** opens a view where you:
1. Map each Bool tag to a **GPIO (BCM) pin** — inputs (`I`) become GPIO inputs, outputs (`Q`) become GPIO
   outputs; unmapped tags stay internal memory. Set pull (up/down/none) and active-low per pin.
2. **Download .py** — a single self-contained Python file whose scan loop computes exactly what the
   in-app simulator does (verified by parity tests).

On the Pi: `python3 <project>.py` (needs **`gpiozero`** — `sudo apt install python3-gpiozero`; note the
Pi 5 uses gpiozero/lgpio, **not** RPi.GPIO). Test it on any machine with no hardware via
`python3 <project>.py --mock`.

## Analog output (software PWM) + scaling
The Pi has no analog (DAC) output, so analog control uses **software PWM**: map a **numeric** tag (Int/Real)
to a GPIO in **Raspberry Pi → Export Python**, set its Direction to **pwm**, give it a **Freq (Hz)** (default
100), and the runtime drives a `gpiozero.PWMOutputDevice` whose duty cycle follows the tag's value, **clamped
to 0.0–1.0**. (Analog *input* isn't supported — no on-board ADC.)

Condition the value with the two standard TIA scaling boxes (group **Conversion** in the instruction tree):
- **NORM_X** — `OUT = (VALUE − MIN) / (MAX − MIN)` — normalize a raw value to 0.0–1.0.
- **SCALE_X** — `OUT = VALUE × (MAX − MIN) + MIN` — scale a 0.0–1.0 value into an engineering range.

The demo's *"Conveyor PWM duty"* network shows the pattern: `NORM_X(0, Part_Count, 5) → Conveyor_PWM`
(BCM 18, 200 Hz), so the PWM duty ramps 0→1 as parts count 0→5. The math is identical in the simulator, the
generated `.py`, and the online runtime.

## Scan cycle time (timer/blinker speed)
A timer (TON/TOF) is evaluated **once per scan**, so the scan cycle is the floor on how fast timers and
blinkers can change — *not* the GPIO (which switches in the MHz range). Set it in **Raspberry Pi → Export
Python → Scan cycle (ms)** (default 50 ms = 20 Hz). Lower it to blink faster (e.g. 5 ms ≈ 200 Hz, 2 ms ≈
500 Hz on the Pi); the in-app simulator clamps to ≥20 ms for browser smoothness. The value travels with the
program, so the generated `.py` and the online runtime both honour it. Practical floor ~1–2 ms (Python +
`time.sleep` granularity); for true kHz/precise signals use hardware PWM, not a scan-loop timer.

## Online mode — run + monitor + change the program live (Pi runtime)
Instead of a one-off `.py`, a **fixed runtime** can run any program, let you change it online, and monitor
it live in the app — TIA-style online monitoring against a real Pi.

1. On the Pi, start the runtime + web server (add `--mock` to try it with no hardware):
   `./run_plc.sh`  (or `python3 plc_server.py`)  — then open **http://localhost:8000** in the browser.
2. In the app, the **Online (PLC)** toolbar group: **Connect** → **Download → PLC** (sends the current
   program to the runtime — change it anytime) → **Monitor**. The diagram now lights up **green/blue from
   real GPIO/memory** and the **Simulation table** shows live values; toggling/forcing a tag there is sent
   to the running PLC. A `🔵 ONLINE` pill shows the status.

Files: `plc_engine.py` interprets the program (a faithful Python port of the simulator — LAD, FBD
**and SCL** — verified by parity tests); `plc_server.py` serves the app and a small JSON API
(`/api/state`, `/api/program`, `/api/force`, …). Pure stdlib + gpiozero; no other dependencies.
**Stop** de-energizes all mapped GPIO outputs (real PLC STOP behavior).

The same API makes the runtime a device for the sibling **Automation Sim** project
(`../automation_sim`): its gateway's `tiaweb` adapter polls `/api/state` and forces inputs via
`/api/force`, so PLC tags bind to a 3D factory scene (conveyors, lamps, robots) and panel
widgets can press the PLC's buttons. See `automation_sim/README.md` → adapter `tiaweb`.

## Saving your work
- **Save** stores the project in the browser's local storage (auto-restored next launch;
  the IDE also autosaves every few seconds).
- Every save also files the project **by name**, so several projects can live in the same
  browser: the **Project menu** lists recent ones to switch between (the current project is
  saved first), and **Project ▸ Rename project…** changes the name.
- **Export** downloads a `.json` file. **Open** re-imports one. Use this to back up or
  move projects between machines (local storage is per-browser).

## Addresses & data types
- Bits: `I0.0` (input), `Q0.0` (output), `M0.0` (memory flag). Bytes/words/dwords: `MB0`, `MW0`, `MD0`, `IW64`…
- **I/Q/M addresses overlap like a real S7** (big-endian): `%MW0` is `%MB0<<8 | %MB1`, so
  `%M0.3` really is bit 3 of MW0's high byte and writing `MW0 := 255` sets `M1.0..M1.7`.
  `MW` is a signed 16-bit word; `MD` holds a 32-bit int — or an IEEE-754 float32 when the
  tag there is `Real`. **Don't place a word tag over bytes used by bit tags** — Compile
  warns about overlapping tag addresses.
- Data types: `Bool`, `Int`, `Real`, `Word`, `Time` (time literals `T#5s`, `T#1m30s`,
  `TIME#…`, and S5 style `S5T#2s` / `S5TIME#…`).
- A symbolic tag with no address still simulates (it gets its own memory slot).

## Supported instructions
Bit logic (`contact NO/NC`, `P/N edge`, `coil`, `negated coil`, `set/reset`),
**`SR`/`RS` latches**, **edge triggers** `P_TRIG`/`N_TRIG`/`R_TRIG`/`F_TRIG`,
`AND/OR/XOR/NOT` (FBD) + assignment, `compare` (`== <> > < >= <=`),
timers `TON/TOF/TP`, counters `CTU/CTD/CTUD` (up/down with `R`, `LD`, `QU`, `QD`),
`MOVE`, math `ADD/SUB/MUL/DIV`, and block **calls** (drag a block from the tree onto
a network). Math and conversion boxes expose **ENO** (= EN and no numeric error —
divide-by-zero, `NORM_X` with MAX=MIN, overflow): wire a bit operand to it to chain
error status like TIA.

Blocks can also be written in **SCL** (structured text: `IF/CASE/FOR/WHILE/REPEAT`,
`EXIT/CONTINUE`, math functions) — SCL runs in the in-app simulator, on the online Pi
runtime, and in the exported `.py`, with the same semantics in all three.

GPIO inputs support an optional **debounce (ms)** in the Raspberry Pi pin table — it filters
mechanical switch bounce that would otherwise double-count CTU/P_TRIG edges on real hardware.

## Project tree & simulation table tips
- **Single-click** a block or the tag table to preview it in the **Details view**; **double-click** to open it.
- In the **Simulation table**, each Bool has two controls: a **latching toggle** (`○/●`) and a round
  **momentary push-button** beside it — hold it to invert the bit, release to revert (great for testing
  edge triggers and start buttons).

## Architecture (for extending)
Plain vanilla JS, no build step. Everything hangs off the `window.TIA` namespace.
See **`SPEC.md`** for the full module contract. Files load in this order
(`index.html`): `core.js` (data model + the instruction **catalog** + sim memory) →
feature modules (`tags, tree, instructions, lad, fbd, sim`) → `toolbar.js` →
`app.js` (bootstrap). To add an instruction, add a `kind` to `TIA.catalog` in
`core.js`, then handle its rendering (lad/fbd) and evaluation (`sim.js`).
