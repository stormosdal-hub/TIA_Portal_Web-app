#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================================
# plc_server.py — serve the TIA Web Practice app + a small HTTP API, and run
# the cyclic PLC scan loop on a Raspberry Pi.
#
# The browser app (index.html + js/*) can POST a new program here to run it on
# real GPIO, monitor live state, and force values — all without restarting the
# process (online change), because plc_engine.py INTERPRETS the program.
#
# Pure stdlib only (http.server). Optional gpiozero is used by plc_engine if a
# real Pi is detected; otherwise the engine auto-falls back to a mock backend.
#
#   python3 plc_server.py                 # serve ./ on :8000, real GPIO if available
#   python3 plc_server.py --mock          # force the pure-Python mock backend
#   python3 plc_server.py --port 8080     # different port
#   python3 plc_server.py --dir /path     # serve static files from a directory
#   python3 plc_server.py --modbus-port 5020   # also serve Modbus TCP (see modbus_server.py)
#
# JSON API (all responses carry permissive CORS headers):
#   GET  /api/info        -> {ok, running, mock, scan, hasProgram, project, modbusPort}
#   GET  /api/state       -> engine.snapshot()
#   GET  /api/tags        -> {ok, tags: [{name, dataType, address, comment}, ...]}
#   GET  /api/modbus-map  -> {ok, port, bank, map: {tagName: {kind, address[, registers]}}}
#   POST /api/program     -> body = project JSON; load + start; -> {ok}
#   POST /api/force       -> body = {key, value}; -> {ok}
#   POST /api/run         -> running = True;  -> {ok, running}
#   POST /api/stop        -> running = False; -> {ok, running}
# ============================================================================

import argparse
import json
import mimetypes
import os
import posixpath
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse

from plc_engine import Engine
from modbus_server import BANK, modbus_map, serve_modbus


SCAN_HZ = 20                 # scan rate (Hz) while running
SCAN_PERIOD = 1.0 / SCAN_HZ  # ~50 ms


class Runtime:
    """Holds the engine, the running flag, and the scan thread. All engine access
    is guarded by a single lock so the scan loop and HTTP handlers never race."""

    def __init__(self, mock=False):
        self.lock = threading.Lock()
        self.mock = mock
        self.engine = Engine(mock=mock)
        self.running = False
        self.has_program = False
        self.project_name = None
        self.modbus_port = None   # set by main() once the Modbus server is up
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    # ---- scan loop --------------------------------------------------------
    def _loop(self):
        """Background thread: read inputs, scan, write outputs at ~SCAN_HZ while
        running. Idle (cheap sleep) when stopped or no program is loaded."""
        while not self._stop.is_set():
            start = time.monotonic()
            with self.lock:
                run = self.running and self.has_program
                if run:
                    try:
                        self.engine.read_inputs()
                        self.engine.scan()
                        self.engine.write_outputs()
                    except Exception as e:
                        # never let a bad program kill the loop
                        sys.stderr.write('[scan] error: %r\n' % (e,))
            # pace the loop to the program's requested scan time; idle cheaply
            elapsed = time.monotonic() - start
            period = getattr(self.engine, 'scan_s', SCAN_PERIOD)
            delay = (period - elapsed) if run else 0.05
            if delay > 0:
                self._stop.wait(delay)

    def shutdown(self):
        self._stop.set()
        with self.lock:
            self._outputs_off()

    def _outputs_off(self):
        """STOP behavior of a real PLC: de-energize every output. Without this,
        stopping the scan freezes GPIO in its last state (motor keeps running).
        Caller must hold self.lock."""
        try:
            for dev in self.engine.outputs.values():
                dev.value = False
            for dev in self.engine.pwms.values():
                dev.value = 0.0
        except Exception as e:
            sys.stderr.write('[stop] output reset error: %r\n' % (e,))

    # ---- API operations (all take the lock) -------------------------------
    def set_program(self, project):
        with self.lock:
            res = self.engine.set_program(project) or {}
            self.has_program = True
            self.running = True
            self.project_name = (project or {}).get('name')
            return res

    def force(self, key, value):
        with self.lock:
            self.engine.force(key, value)

    def set_running(self, run):
        with self.lock:
            was = self.running
            # only run when we actually have a program
            self.running = bool(run) and self.has_program
            if was and not self.running:
                self._outputs_off()
            return self.running

    def info(self):
        with self.lock:
            return {
                'ok': True,
                'running': self.running,
                'mock': self.mock,
                'scan': self.engine.scan_count,
                'hasProgram': self.has_program,
                'project': self.project_name,
                'modbusPort': self.modbus_port,
            }

    def state(self):
        with self.lock:
            return self.engine.snapshot(running=self.running)

    def tags(self):
        """Declared project tags (name/dataType/address/comment) — lets a
        client (e.g. the automation_sim gateway) discover what to subscribe to
        instead of hand-maintaining its own copy of the tag list."""
        with self.lock:
            return [{'name': t.get('name'), 'dataType': t.get('dataType'),
                     'address': t.get('address') or None, 'comment': t.get('comment') or None}
                    for t in (getattr(self.engine, '_tags', None) or [])
                    if t.get('name')]


# module-global runtime + static dir, set up in main()
RT = None
STATIC_DIR = None


class Handler(BaseHTTPRequestHandler):
    server_version = 'TIA-PLC-Runtime/1.0'

    # ---- low-level response helpers --------------------------------------
    def _cors(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')

    def _send_json(self, obj, code=200):
        body = json.dumps(obj).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _send_bytes(self, body, content_type, code=200):
        self.send_response(code)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self._cors()
        self.end_headers()
        if body:
            self.wfile.write(body)

    MAX_BODY = 8 * 1024 * 1024    # a project JSON is KBs; cap so a bad POST can't OOM a Pi

    def _read_body_json(self):
        length = int(self.headers.get('Content-Length') or 0)
        if length > self.MAX_BODY:
            raise ValueError('request body too large (%d bytes)' % length)
        raw = self.rfile.read(length) if length else b''
        if not raw:
            return None
        return json.loads(raw.decode('utf-8'))

    # quieter logging
    def log_message(self, fmt, *args):
        sys.stderr.write('%s - %s\n' % (self.address_string(), fmt % args))

    # ---- HTTP verbs -------------------------------------------------------
    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.send_header('Content-Length', '0')
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path
        if path.startswith('/api/'):
            return self._handle_api_get(path)
        return self._serve_static(path)

    def do_POST(self):
        path = urlparse(self.path).path
        if not path.startswith('/api/'):
            return self._send_json({'ok': False, 'error': 'not found'}, 404)
        try:
            return self._handle_api_post(path)
        except Exception as e:
            return self._send_json({'ok': False, 'error': str(e)}, 400)

    # ---- API ---------------------------------------------------------------
    def _handle_api_get(self, path):
        if path == '/api/info':
            return self._send_json(RT.info())
        if path == '/api/state':
            return self._send_json(RT.state())
        if path == '/api/tags':
            return self._send_json({'ok': True, 'tags': RT.tags()})
        if path == '/api/modbus-map':
            return self._send_json({'ok': True, 'port': RT.modbus_port, 'bank': BANK,
                                     'map': modbus_map(RT)})
        return self._send_json({'ok': False, 'error': 'unknown endpoint'}, 404)

    def _handle_api_post(self, path):
        if path == '/api/program':
            project = self._read_body_json()
            if not isinstance(project, dict):
                return self._send_json({'ok': False, 'error': 'expected project JSON object'}, 400)
            res = RT.set_program(project)
            return self._send_json({'ok': True, 'warnings': res.get('warnings', [])})

        if path == '/api/force':
            body = self._read_body_json() or {}
            key = body.get('key')
            if not key:
                return self._send_json({'ok': False, 'error': 'missing key'}, 400)
            RT.force(key, body.get('value'))
            return self._send_json({'ok': True})

        if path == '/api/run':
            return self._send_json({'ok': True, 'running': RT.set_running(True)})

        if path == '/api/stop':
            return self._send_json({'ok': True, 'running': RT.set_running(False)})

        return self._send_json({'ok': False, 'error': 'unknown endpoint'}, 404)

    # ---- static files ------------------------------------------------------
    def _serve_static(self, url_path):
        """Serve files from STATIC_DIR. GET / -> index.html. Path traversal is
        prevented by normalising and confining to STATIC_DIR."""
        rel = unquote(urlparse(url_path).path)
        if rel == '/' or rel == '':
            rel = '/index.html'
        # normalise to a safe relative path (no .. escapes)
        rel = posixpath.normpath(rel).lstrip('/')
        full = os.path.join(STATIC_DIR, *rel.split('/'))
        full = os.path.abspath(full)
        if not full.startswith(os.path.abspath(STATIC_DIR)):
            return self._send_bytes(b'Forbidden', 'text/plain; charset=utf-8', 403)
        if os.path.isdir(full):
            full = os.path.join(full, 'index.html')
        if not os.path.isfile(full):
            return self._send_bytes(b'Not found', 'text/plain; charset=utf-8', 404)
        ctype = mimetypes.guess_type(full)[0] or 'application/octet-stream'
        # make sure text types are utf-8 so the browser renders correctly
        if ctype.startswith('text/') or ctype in ('application/javascript', 'application/json'):
            ctype += '; charset=utf-8'
        try:
            with open(full, 'rb') as f:
                data = f.read()
        except OSError:
            return self._send_bytes(b'Not found', 'text/plain; charset=utf-8', 404)
        return self._send_bytes(data, ctype)


def main(argv=None):
    global RT, STATIC_DIR
    parser = argparse.ArgumentParser(description='TIA Web Practice — Raspberry Pi PLC runtime server')
    parser.add_argument('--port', type=int, default=8000, help='HTTP port (default 8000)')
    parser.add_argument('--mock', action='store_true', help='force the pure-Python mock GPIO backend')
    parser.add_argument('--dir', default=None, help='directory of static files (default: this file\'s dir)')
    parser.add_argument('--modbus-port', type=int, default=0,
                         help='also serve Modbus TCP on this port (0 = disabled); '
                              'ports <1024 (e.g. the standard 502) need root/CAP_NET_BIND_SERVICE')
    args = parser.parse_args(argv)

    STATIC_DIR = os.path.abspath(args.dir or os.path.dirname(os.path.abspath(__file__)))
    # ensure common web types are registered (some minimal systems miss .js/.css)
    mimetypes.add_type('application/javascript', '.js')
    mimetypes.add_type('text/css', '.css')

    RT = Runtime(mock=args.mock)
    RT.modbus_port = args.modbus_port or None

    httpd = ThreadingHTTPServer(('0.0.0.0', args.port), Handler)
    modbus_srv = None
    modbus_thread = None
    if RT.modbus_port:
        modbus_srv = serve_modbus(RT, RT.modbus_port)
        modbus_thread = threading.Thread(target=modbus_srv.serve_forever, daemon=True)
        modbus_thread.start()

    backend = 'MOCK' if (args.mock or not Engine._gpiozero_available()) else 'gpiozero'
    print('TIA PLC runtime — I/O backend: %s' % backend)
    print('Open the app at:  http://localhost:%d' % args.port)
    print('API base:         http://localhost:%d/api' % args.port)
    if RT.modbus_port:
        print('Modbus TCP server: 0.0.0.0:%d  (map: /api/modbus-map)' % RT.modbus_port)
    print('Idle (no program). POST a project to /api/program to start. Ctrl+C to stop.')
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print('\nstopping...')
    finally:
        RT.shutdown()
        httpd.server_close()
        if modbus_srv:
            modbus_srv.shutdown()
            modbus_srv.server_close()


if __name__ == '__main__':
    main()
