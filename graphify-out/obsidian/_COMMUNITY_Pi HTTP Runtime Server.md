---
type: community
members: 28
---

# Pi HTTP Runtime Server

**Members:** 28 nodes

## Members
- [[.__init__()_3]] - code - plc_server.py
- [[._cors()]] - code - plc_server.py
- [[._gpiozero_available()]] - code - plc_engine.py
- [[._handle_api_get()]] - code - plc_server.py
- [[._handle_api_post()]] - code - plc_server.py
- [[._loop()]] - code - plc_server.py
- [[._read_body_json()]] - code - plc_server.py
- [[._send_bytes()]] - code - plc_server.py
- [[._send_json()]] - code - plc_server.py
- [[._serve_static()]] - code - plc_server.py
- [[.do_GET()]] - code - plc_server.py
- [[.do_OPTIONS()]] - code - plc_server.py
- [[.do_POST()]] - code - plc_server.py
- [[.force()_1]] - code - plc_server.py
- [[.info()]] - code - plc_server.py
- [[.log_message()]] - code - plc_server.py
- [[.set_program()_1]] - code - plc_server.py
- [[.set_running()]] - code - plc_server.py
- [[.shutdown()]] - code - plc_server.py
- [[.state()]] - code - plc_server.py
- [[Background thread read inputs, scan, write outputs at ~SCAN_HZ while         ru]] - rationale - plc_server.py
- [[BaseHTTPRequestHandler]] - code
- [[Handler]] - code - plc_server.py
- [[Holds the engine, the running flag, and the scan thread. All engine access     i]] - rationale - plc_server.py
- [[Runtime]] - code - plc_server.py
- [[Serve files from STATIC_DIR. GET  - index.html. Path traversal is         prev]] - rationale - plc_server.py
- [[main()]] - code - plc_server.py
- [[plc_server.py]] - code - plc_server.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Pi_HTTP_Runtime_Server
SORT file.name ASC
```

## Connections to other communities
- 6 edges to [[_COMMUNITY_PLC Engine Core]]
- 1 edge to [[_COMMUNITY_GPIO Backend & Mock]]

## Top bridge nodes
- [[._gpiozero_available()]] - degree 3, connects to 2 communities
- [[Handler]] - degree 14, connects to 1 community
- [[Runtime]] - degree 12, connects to 1 community
- [[plc_server.py]] - degree 5, connects to 1 community
- [[.__init__()_3]] - degree 2, connects to 1 community