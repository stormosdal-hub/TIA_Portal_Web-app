#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================================
# modbus_server.py — Modbus TCP SERVER mode for the TIA Web Practice runtime.
#
# Exposes the running PLC's I/Q/M memory as the four standard Modbus tables so
# any Modbus master (SCADA/HMI, or this project's own `automation_sim` gateway
# using its generic `modbus` adapter) can connect — no project-specific setup
# needed, no dependency beyond the stdlib (socketserver), and no relation to
# plc_engine.py's tag-name layer: addresses map straight onto the same S7-style
# byte-overlapped memory that Mem (plc_engine.py) already implements, so a
# Modbus write and a ladder-side %MW/%M reference land in the exact same bytes.
#
# Address mapping (0-based raw protocol addresses, NOT legacy 40001-style
# references). Each bit table and each register table is split into two
# 10000-wide banks so both M and Q are reachable without inventing a 5th
# Modbus table:
#
#   Coils            (FC01 read / FC05,FC15 write)   0..9999      -> M bit
#                                                     10000..19999 -> Q bit
#   Discrete Inputs   (FC02 read-only)                0..65535     -> I bit
#   Holding Registers (FC03 read / FC06,FC16 write)   0..9999      -> M word
#                                                     10000..19999 -> Q word
#   Input Registers   (FC04 read-only)                0..65535     -> I word
#
# Bit address N -> byte N//8, bit N%8. Register address N -> byte offset N*2
# (big-endian, 2 bytes/register); a 32-bit tag (Dint/Real) spans two
# consecutive registers automatically since it's 4 raw bytes underneath.
# Registers carry the raw bit pattern (unsigned on the wire) — sign/float
# interpretation is left to the Modbus client, exactly like a real PLC.
#
# See Runtime.modbus_map() (also GET /api/modbus-map) for the derived
# kind+address of every tag that has a TIA address in a reachable bank.
# ============================================================================

import re
import socketserver
import struct


ILLEGAL_FUNCTION = 0x01
ILLEGAL_DATA_ADDRESS = 0x02
ILLEGAL_DATA_VALUE = 0x03
SLAVE_DEVICE_FAILURE = 0x04

BANK = 10000            # M bank: [0, BANK); Q bank: [BANK, 2*BANK)
MAX_QTY_BITS = 2000
MAX_QTY_REGS = 125

_AB_RE = re.compile(r'^([IQM])(\d+)\.(\d+)$')
_AW_RE = re.compile(r'^([IQM])([BWD])(\d+)$')


class ModbusError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def _bit_key(area, addr):
    return '%s%d.%d' % (area, addr // 8, addr % 8)


def _word_key(area, addr):
    return '%sW%d' % (area, addr * 2)


def _coil_key(addr):
    if addr < BANK:
        return _bit_key('M', addr)
    if addr < 2 * BANK:
        return _bit_key('Q', addr - BANK)
    raise ModbusError(ILLEGAL_DATA_ADDRESS)


def _discrete_key(addr):
    return _bit_key('I', addr)


def _holding_key(addr):
    if addr < BANK:
        return _word_key('M', addr)
    if addr < 2 * BANK:
        return _word_key('Q', addr - BANK)
    raise ModbusError(ILLEGAL_DATA_ADDRESS)


def _input_key(addr):
    return _word_key('I', addr)


def modbus_map(runtime):
    """{tag name: {kind, address[, registers]}} for every tag whose TIA address
    falls in a reachable bank. Bit tags (M/Q/I<byte>.<bit>) -> coil/discrete;
    word/dword tags (xW/xD<byte>) -> holding/input (dword = 2 registers).
    Byte-sized (xB) tags and nameless/addressless tags are omitted — a single
    byte isn't cleanly addressable as a whole Modbus register."""
    out = {}
    with runtime.lock:
        tags = list(getattr(runtime.engine, '_tags', []) or [])
    for t in tags:
        name = t.get('name')
        addr = str(t.get('address') or '').strip().upper()
        if not name or not addr:
            continue
        m = _AB_RE.match(addr)
        if m:
            area, byte, bit = m.group(1), int(m.group(2)), int(m.group(3))
            n = byte * 8 + bit
            if area == 'M':
                out[name] = {'kind': 'coil', 'address': n}
            elif area == 'Q':
                out[name] = {'kind': 'coil', 'address': BANK + n}
            else:
                out[name] = {'kind': 'discrete', 'address': n}
            continue
        m = _AW_RE.match(addr)
        if m and m.group(2) != 'B':
            area, size, byte = m.group(1), m.group(2), int(m.group(3))
            regs = 1 if size == 'W' else 2
            n = byte // 2
            if area == 'M':
                out[name] = {'kind': 'holding', 'address': n, 'registers': regs}
            elif area == 'Q':
                out[name] = {'kind': 'holding', 'address': BANK + n, 'registers': regs}
            else:
                out[name] = {'kind': 'input', 'address': n, 'registers': regs}
    return out


class _Handler(socketserver.BaseRequestHandler):
    def handle(self):
        rt = self.server.runtime
        sock = self.request
        sock.settimeout(60)
        buf = b''
        try:
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    return
                buf += chunk
                while len(buf) >= 7:
                    length = struct.unpack('>H', buf[4:6])[0]
                    frame_len = 6 + length
                    if frame_len < 8 or len(buf) < frame_len:
                        break
                    frame, buf = buf[:frame_len], buf[frame_len:]
                    resp = self._dispatch(rt, frame)
                    if resp is not None:
                        sock.sendall(resp)
        except (OSError, ConnectionError, struct.error):
            return

    def _dispatch(self, rt, frame):
        txn_id, proto_id, _length, unit_id = struct.unpack('>HHHB', frame[:7])
        pdu = frame[7:]
        if proto_id != 0 or not pdu:
            return None
        fc = pdu[0]
        try:
            body = bytes([fc]) + self._handle_fc(rt, fc, pdu[1:])
        except ModbusError as e:
            body = bytes([fc | 0x80, e.code])
        except Exception:
            body = bytes([fc | 0x80, SLAVE_DEVICE_FAILURE])
        header = struct.pack('>HHHB', txn_id, 0, len(body) + 1, unit_id)
        return header + body

    def _handle_fc(self, rt, fc, data):
        if fc == 0x01:
            return self._read_bits(rt, data, _coil_key)
        if fc == 0x02:
            return self._read_bits(rt, data, _discrete_key)
        if fc == 0x03:
            return self._read_regs(rt, data, _holding_key)
        if fc == 0x04:
            return self._read_regs(rt, data, _input_key)
        if fc == 0x05:
            return self._write_coil(rt, data)
        if fc == 0x06:
            return self._write_reg(rt, data)
        if fc == 0x0F:
            return self._write_coils(rt, data)
        if fc == 0x10:
            return self._write_regs(rt, data)
        raise ModbusError(ILLEGAL_FUNCTION)

    def _read_bits(self, rt, data, keyfn):
        if len(data) < 4:
            raise ModbusError(ILLEGAL_DATA_VALUE)
        addr, qty = struct.unpack('>HH', data[:4])
        if qty < 1 or qty > MAX_QTY_BITS:
            raise ModbusError(ILLEGAL_DATA_VALUE)
        nbytes = (qty + 7) // 8
        out = bytearray(nbytes)
        with rt.lock:
            for i in range(qty):
                if bool(rt.engine.M[keyfn(addr + i)]):
                    out[i // 8] |= (1 << (i % 8))
        return bytes([nbytes]) + bytes(out)

    def _read_regs(self, rt, data, keyfn):
        if len(data) < 4:
            raise ModbusError(ILLEGAL_DATA_VALUE)
        addr, qty = struct.unpack('>HH', data[:4])
        if qty < 1 or qty > MAX_QTY_REGS:
            raise ModbusError(ILLEGAL_DATA_VALUE)
        out = bytearray()
        with rt.lock:
            for i in range(qty):
                v = int(rt.engine.M[keyfn(addr + i)]) & 0xFFFF
                out += struct.pack('>H', v)
        return bytes([len(out)]) + bytes(out)

    def _write_coil(self, rt, data):
        if len(data) < 4:
            raise ModbusError(ILLEGAL_DATA_VALUE)
        addr, val = struct.unpack('>HH', data[:4])
        if val not in (0x0000, 0xFF00):
            raise ModbusError(ILLEGAL_DATA_VALUE)
        with rt.lock:
            rt.engine.M[_coil_key(addr)] = (val == 0xFF00)
        return data[:4]

    def _write_reg(self, rt, data):
        if len(data) < 4:
            raise ModbusError(ILLEGAL_DATA_VALUE)
        addr, val = struct.unpack('>HH', data[:4])
        with rt.lock:
            rt.engine.M[_holding_key(addr)] = val
        return data[:4]

    def _write_coils(self, rt, data):
        if len(data) < 5:
            raise ModbusError(ILLEGAL_DATA_VALUE)
        addr, qty, nbytes = struct.unpack('>HHB', data[:5])
        payload = data[5:5 + nbytes]
        if qty < 1 or qty > MAX_QTY_BITS or len(payload) != nbytes:
            raise ModbusError(ILLEGAL_DATA_VALUE)
        with rt.lock:
            for i in range(qty):
                bit = (payload[i // 8] >> (i % 8)) & 1
                rt.engine.M[_coil_key(addr + i)] = bool(bit)
        return struct.pack('>HH', addr, qty)

    def _write_regs(self, rt, data):
        if len(data) < 5:
            raise ModbusError(ILLEGAL_DATA_VALUE)
        addr, qty, nbytes = struct.unpack('>HHB', data[:5])
        payload = data[5:5 + nbytes]
        if qty < 1 or qty > MAX_QTY_REGS or nbytes != qty * 2 or len(payload) != nbytes:
            raise ModbusError(ILLEGAL_DATA_VALUE)
        with rt.lock:
            for i in range(qty):
                v = struct.unpack('>H', payload[i * 2:i * 2 + 2])[0]
                rt.engine.M[_holding_key(addr + i)] = v
        return struct.pack('>HH', addr, qty)


class _Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def serve_modbus(runtime, port, bind='0.0.0.0'):
    """Build (not start) the Modbus TCP server bound to (bind, port). Caller
    runs `srv.serve_forever()` (typically on a daemon thread) and is
    responsible for `srv.shutdown(); srv.server_close()` on exit."""
    srv = _Server((bind, port), _Handler)
    srv.runtime = runtime
    return srv
