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
    const go = O.connected ? Promise.resolve(true) : O.connect();
    return go.then((ok) => {
      if (!ok) return;
      return api('/api/program', { method: 'POST', body: T.project }).then((r) => {
        O.running = true;
        buildIndex();
        const warns = (r && r.warnings) || [];
        if (warns.length) T.status('Downloaded with warnings: ' + warns.join(' · '), 'warn');
        else T.status('Program downloaded to PLC — running on the Pi', 'ok');
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

  /* ---------------------------------------------- connection-info popup */
  // A modal you open from the toolbar: shows this runtime's network address so
  // you can connect Automation Sim (on another PC / your desk) without running
  // `hostname -I` in a terminal. The "Check address" button hits /api/netinfo.
  function injectInfoCSS() {
    T.injectCSS('tia-online-info-css', `
      .tia-oi-ov{position:fixed;inset:0;background:rgba(0,0,0,.42);display:flex;
        align-items:center;justify-content:center;z-index:10000;}
      .tia-oi{background:var(--tia-panel);color:var(--tia-text);border:1px solid var(--tia-border);
        border-radius:8px;min-width:340px;max-width:480px;box-shadow:0 14px 44px rgba(0,0,0,.45);
        font-family:var(--tia-font);}
      .tia-oi-head{padding:12px 16px;font-weight:600;border-bottom:1px solid var(--tia-border);}
      .tia-oi-body{padding:14px 16px;display:flex;flex-direction:column;gap:10px;font-size:13px;}
      .tia-oi-foot{padding:10px 16px;border-top:1px solid var(--tia-border);display:flex;
        justify-content:flex-end;gap:8px;}
      .tia-oi button{font:inherit;font-size:12px;padding:5px 12px;border-radius:5px;cursor:pointer;
        border:1px solid var(--tia-border);background:var(--tia-hover);color:var(--tia-text);}
      .tia-oi button.primary{background:var(--tia-accent);border-color:var(--tia-accent);color:var(--tia-text-inv);}
      .tia-oi-status{font-size:12px;color:var(--tia-text-soft);}
      .tia-oi-section{font-size:11px;text-transform:uppercase;letter-spacing:.05em;color:var(--tia-text-soft);}
      .tia-oi-box{background:var(--tia-bg);border:1px solid var(--tia-border-soft);border-radius:6px;
        padding:10px 12px;font-size:12.5px;line-height:1.6;}
      .tia-oi-row{display:flex;align-items:center;gap:8px;margin:3px 0;}
      .tia-oi-url{font-family:var(--tia-mono);color:var(--tia-accent);word-break:break-all;flex:1;}
      .tia-oi-copy{padding:2px 8px !important;font-size:11px !important;}
      .tia-oi-hint{font-size:11.5px;color:var(--tia-text-soft);}
      .tia-oi-warn{color:#c0392b;}
    `);
  }

  O.showInfo = function () {
    injectInfoCSS();
    const old = document.querySelector('.tia-oi-ov');
    if (old) old.remove();

    const statusEl = T.el('div', { class: 'tia-oi-status' });
    const box = T.el('div', { class: 'tia-oi-box' }, 'Checking…');
    const checkBtn = T.el('button', { class: 'primary', onclick: check }, 'Check address');
    const closeBtn = T.el('button', { onclick: closeIt }, 'Close');

    const modal = T.el('div', { class: 'tia-oi' },
      T.el('div', { class: 'tia-oi-head' }, 'PLC connection'),
      T.el('div', { class: 'tia-oi-body' },
        statusEl,
        T.el('div', { class: 'tia-oi-section' }, 'This runtime is reachable at'),
        box,
        T.el('div', { class: 'tia-oi-hint' },
          'In Automation Sim → Online ▾, enter one of these addresses (or use its Search button).')
      ),
      T.el('div', { class: 'tia-oi-foot' }, closeBtn, checkBtn)
    );
    const ov = T.el('div', { class: 'tia-oi-ov' }, modal);
    ov.addEventListener('mousedown', (e) => { if (e.target === ov) closeIt(); });
    ov.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeIt(); });
    ov.tabIndex = -1;
    document.body.appendChild(ov);
    ov.focus();

    renderStatus();
    check();

    function closeIt() { if (ov.parentNode) ov.parentNode.removeChild(ov); }

    function renderStatus() {
      const bits = [];
      bits.push(O.connected ? 'connected' : (O.available() ? 'not connected' : 'offline app'));
      if (O.connected) bits.push(O.mock ? 'mock I/O' : 'real GPIO');
      if (O.monitoring) bits.push('monitoring');
      statusEl.textContent = 'Status: ' + bits.join(' · ');
    }

    function check() {
      if (!O.available()) {
        T.clear(box);
        box.appendChild(T.el('span', { class: 'tia-oi-warn' },
          'Open this app from the runtime (http://<host>:<port>) to read its address — a file:// page has no server.'));
        return;
      }
      box.textContent = 'Checking…';
      api('/api/netinfo').then(render).catch((e) => {
        T.clear(box);
        box.appendChild(T.el('span', { class: 'tia-oi-warn' }, 'Unavailable: ' + (e && e.message || e)));
      });
    }

    function render(ni) {
      T.clear(box);
      box.appendChild(T.el('div', { class: 'tia-oi-row' },
        T.el('span', { class: 'tia-oi-hint' }, 'hostname: '),
        T.el('b', null, ni.hostname || '?')));
      const urls = (ni.urls && ni.urls.length) ? ni.urls
        : ['http://localhost:' + (ni.port || '?') + '  (this machine only — no LAN address found)'];
      urls.forEach((u) => {
        const row = T.el('div', { class: 'tia-oi-row' },
          T.el('span', { class: 'tia-oi-url' }, u));
        if (/^https?:\/\//.test(u) && navigator.clipboard) {
          row.appendChild(T.el('button', {
            class: 'tia-oi-copy', onclick: () => {
              navigator.clipboard.writeText(u).then(
                () => T.status('Copied ' + u, 'ok'), () => T.status('Copy failed', 'warn'));
            }
          }, 'Copy'));
        }
        box.appendChild(row);
      });
      if (ni.modbusPort) {
        box.appendChild(T.el('div', { class: 'tia-oi-row' },
          T.el('span', { class: 'tia-oi-hint' }, 'Modbus TCP on port '),
          T.el('b', null, String(ni.modbusPort))));
      }
    }
  };

  // rebuild the id index if the project reloads while monitoring
  T.bus.on('project:loaded', () => { if (O.monitoring) buildIndex(); });
  T.bus.on('tree:changed',   () => { if (O.monitoring) buildIndex(); });
})(window.TIA);
