/* ============================================================================
 * online.js — connect the app to the Raspberry Pi "fixed runtime" (plc_server.py)
 * for live GPIO monitoring + downloading/changing the program online.
 *
 * Only active when the app is SERVED over http(s) by the runtime (not file://),
 * so same-origin fetch to /api/* works. The runtime is the PLC; this module
 * downloads the program to it and polls its live state to drive the diagram's
 * green/blue highlighting and the simulation table (reusing the sim visuals).
 *
 * Runtime API:  GET /api/info ; GET /api/state ; POST /api/program ;
 *               POST /api/force {key,value} ; POST /api/run ; POST /api/stop
 * ==========================================================================*/
(function (T) {
  'use strict';

  const O = {
    connected: false,
    monitoring: false,
    running: false,
    mock: false,
    scan: 0,
    _timer: null,
    _index: null,
  };
  T.online = O;

  O.available = function () { return /^https?:$/.test(location.protocol); };

  function api(path, opts) {
    opts = opts || {};
    if (opts.body && typeof opts.body !== 'string') opts.body = JSON.stringify(opts.body);
    opts.headers = Object.assign({ 'Content-Type': 'application/json' }, opts.headers || {});
    return fetch(path, opts).then((r) => {
      if (!r.ok) throw new Error('HTTP ' + r.status);
      const ct = r.headers.get('content-type') || '';
      return ct.indexOf('json') >= 0 ? r.json() : r.text();
    });
  }
  function snap() { return { connected: O.connected, monitoring: O.monitoring, running: O.running, mock: O.mock, scan: O.scan, available: O.available() }; }
  function emit() { T.bus.emit('online:state', snap()); }

  /* ----------------------------------------------------------- connect */
  O.connect = function () {
    if (!O.available()) {
      T.status('Online needs the app served by the Pi runtime (open http://localhost:8000, run plc_server.py).', 'warn');
      emit(); return Promise.resolve(false);
    }
    return api('/api/info').then((info) => {
      O.connected = true; O.running = !!info.running; O.mock = !!info.mock;
      T.status('Connected to PLC runtime' + (info.mock ? ' (mock — no hardware)' : ''), 'ok');
      emit(); return true;
    }).catch(() => {
      O.connected = false;
      T.status('No PLC runtime at ' + location.host + ' — start it with: python3 plc_server.py', 'warn');
      emit(); return false;
    });
  };

  /* ------------------------------------------------- download / change program */
  O.download = function () {
    // TIA-style consistency check first: never download a program with hard errors
    const res = (T.app && T.app.compile) ? T.app.compile() : { errors: 0 };
    if (res && res.errors) {
      T.status('Download aborted — fix the ' + res.errors + ' compile error(s) first (see Output)', 'err');
      return Promise.resolve(false);
    }
    const scl = (T.project.blocks || []).filter((b) => b.type !== 'DB' && b.lang === 'SCL' && (b.code || '').trim());
    const go = O.connected ? Promise.resolve(true) : O.connect();
    return go.then((ok) => {
      if (!ok) return;
      return api('/api/program', { method: 'POST', body: T.project }).then(() => {
        O.running = true;
        buildIndex();
        if (scl.length) {
          T.status('Downloaded — but SCL block(s) ' + scl.map((b) => b.name).join(', ') +
                   ' are NOT executed by the Pi online runtime (use Export Python for SCL)', 'warn');
        } else {
          T.status('Program downloaded to PLC — running on the Pi', 'ok');
        }
        O.startMonitor();
      }).catch((e) => T.status('Download failed: ' + e.message, 'err'));
    });
  };

  /* --------------------------------------------------------------- forcing */
  // Called by the simulation table while monitoring; pushes a value to the runtime.
  O.force = function (key, value) {
    if (!O.connected) return;
    api('/api/force', { method: 'POST', body: { key: key, value: value } }).catch(() => {});
  };

  /* ------------------------------------------------------------- monitoring */
  O.startMonitor = function () {
    if (!O.connected || O.monitoring) return;
    if (T.sim && T.sim.running) T.sim.stop();   // the Pi is the PLC now
    O.monitoring = true;
    buildIndex();
    T.bus.emit('sim:state', { running: true });  // editors apply energized/de-energized colouring
    emit();
    poll();
    O._timer = setInterval(poll, 150);
  };
  O.stopMonitor = function () {
    if (O._timer) { clearInterval(O._timer); O._timer = null; }
    if (!O.monitoring) { emit(); return; }
    O.monitoring = false;
    T.bus.emit('sim:state', { running: false });  // clear highlights
    emit();
  };
  O.toggleMonitor = function () { O.monitoring ? O.stopMonitor() : O.startMonitor(); };

  O.run = function () { api('/api/run', { method: 'POST' }).then((r) => { O.running = !!(r && r.running); emit(); }).catch(() => {}); };
  O.stop = function () { api('/api/stop', { method: 'POST' }).then((r) => { O.running = !!(r && r.running); emit(); }).catch(() => {}); };

  let _inflight = false, _fails = 0;
  function poll() {
    if (_inflight) return;                    // never stack requests on a slow Pi
    _inflight = true;
    api('/api/state')
      .then((s) => { _fails = 0; applyState(s); })
      .catch(() => {
        if (O.monitoring && ++_fails >= 10) { // ~1.5 s of silence: the Pi is gone
          O.stopMonitor();
          O.connected = false;
          emit();
          T.status('PLC runtime unreachable — monitoring stopped', 'err');
        }
      })
      .finally(() => { _inflight = false; });
  }

  // index model objects by id so a snapshot can light them up
  function buildIndex() {
    const idx = { el: {}, net: {}, pin: {} };
    (T.project.blocks || []).forEach((b) => (b.networks || []).forEach((n) => {
      idx.net[n.id] = n;
      (n.stages || []).forEach((s) => (s.branches || []).forEach((br) => (br.elements || []).forEach((e) => { idx.el[e.id] = e; })));
      (n.outputs || []).forEach((e) => { idx.el[e.id] = e; });
      (n.boxes || []).forEach((bx) => { idx.el[bx.id] = bx; (bx.inputs || []).concat(bx.outputs || []).forEach((p) => { idx.pin[p.id] = p; }); });
    }));
    O._index = idx;
  }

  function applyState(s) {
    if (!s || !O.monitoring) return;   // a late response must not re-light a stopped monitor
    O.running = !!s.running; O.scan = s.scan || 0;
    // memory values -> T.mem (by tag name, so the sim table & contacts read real values)
    if (s.mem) (T.project.tags || []).forEach((t) => {
      const v = s.mem[t.name];
      if (v === undefined) return;
      if (t.dataType === 'Bool') T.writeBit(t.name, !!v); else T.writeNum(t.name, +v || 0);
    });
    // liveness -> model flags the editors' highlight() reads
    const idx = O._index || {};
    if (s.live) for (const id in s.live) { const e = idx.el[id]; if (e) e._live = !!s.live[id]; }
    if (s.power) for (const id in s.power) { const n = idx.net[id]; if (n) n._power = !!s.power[id]; }
    if (s.pins) for (const id in s.pins) { const p = idx.pin[id]; if (p) p._val = !!s.pins[id]; }
    T.bus.emit('sim:tick');           // editors re-highlight, sim table refreshes
    T.bus.emit('online:tick', { scan: O.scan });
  }

  // rebuild the id index if the project reloads while monitoring
  T.bus.on('project:loaded', () => { if (O.monitoring) buildIndex(); });
  T.bus.on('tree:changed',   () => { if (O.monitoring) buildIndex(); });
})(window.TIA);
