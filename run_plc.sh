#!/usr/bin/env bash
# Start the Raspberry Pi PLC runtime, then open http://localhost:8000 in your browser.
# Add --mock to test with no GPIO hardware.   On a real Pi: sudo apt install python3-gpiozero
cd "$(dirname "$0")"
exec python3 plc_server.py "$@"
