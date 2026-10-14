#!/usr/bin/env python3
"""Reproduce the exact failing stage of:
  "Failed to secure tcp: deadline has elapsed"

Simulates what RustDesk client 1.4.9 does at src/client.rs:418-462 against a
real hbbs, WITHOUT modifying any client:

  Stage SECURE (logged-in client): TCP connect, then WAIT for the server-first
      KeyExchange exactly like secure_tcp_impl (common.rs:1999). Silence until
      timeout  =>  the client raises the reported error.
  Stage PLAIN (logged-out client): TCP connect, immediately send a framed
      PunchHoleRequest with empty token/key (gate skipped). Any server reply
      => plain path alive.
  Stage TOKEN_PLAIN: same punch but WITH token + licence_key fields, proving
      hbbs tolerates Pro fields on the plain path (protobuf forward compat).

Framing: hbb_common BytesCodec (1/2-byte LE header, low 2 bits = head len-1).

Usage: python3 repro_handshake.py [--host 127.0.0.1] [--port 21116] [--wait 35]
"""
import argparse
import socket
import struct
import sys
import time

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import rendezvous_pb2 as rz  # noqa: E402


def frame(msg: bytes) -> bytes:
    n = len(msg)
    if n <= 0x3F:
        return struct.pack("B", (n << 2) & 0xFF) + msg
    if n <= 0x3FFF:
        return struct.pack("<H", ((n << 2) | 0x1) & 0xFFFF) + msg
    raise ValueError("frame too big for repro")


def read_frame(s: socket.socket, timeout: float, t0: float):
    s.settimeout(timeout)
    hdr = b""
    while len(hdr) < 1:
        chunk = s.recv(1)
        if not chunk:
            return None, "EOF"
        hdr += chunk
    head_len = (hdr[0] & 0x3) + 1
    while len(hdr) < head_len:
        chunk = s.recv(head_len - len(hdr))
        if not chunk:
            return None, "EOF"
        hdr += chunk
    n = int.from_bytes(hdr, "little") >> 2
    body = b""
    while len(body) < n:
        chunk = s.recv(n - len(body))
        if not chunk:
            return None, "EOF"
        body += chunk
    return body, f"{time.time() - t0:.3f}s"


def stage_secure(host, port, wait):
    print(f"--- Stage SECURE (logged-in gate: waits server KeyExchange, timeout={wait}s) ---")
    t0 = time.time()
    s = socket.create_connection((host, port), timeout=10)
    print(f"[{time.time() - t0:.3f}s] TCP connected, waiting for server-first bytes...")
    try:
        body, info = read_frame(s, wait, t0)
    except socket.timeout:
        print(f"[{time.time() - t0:.3f}s] TIMEOUT: hbbs sent nothing -> client raises "
              f"'Failed to secure tcp: deadline has elapsed'")
        s.close()
        return "SECURE_FAIL_SILENCE"
    if body is None:
        print(f"[{info}] server closed connection without data -> same client error")
        s.close()
        return "SECURE_FAIL_EOF"
    m = rz.RendezvousMessage()
    m.ParseFromString(body)
    kind = m.WhichOneof("union")
    print(f"[{info}] server sent: {kind}")
    s.close()
    return f"SECURE_GOT_{kind}"


def stage_punch(host, port, token, key, label, wait=10):
    print(f"--- Stage {label} (plain PunchHoleRequest token={token!r:.12} key_len={len(key)}) ---")
    t0 = time.time()
    s = socket.create_connection((host, port), timeout=10)
    req = rz.RendezvousMessage()
    ph = req.punch_hole_request
    ph.id = "999999999"
    ph.nat_type = 0
    ph.licence_key = key
    ph.conn_type = 0
    ph.token = token
    ph.version = "1.4.9"
    ph.udp_port = 0
    ph.force_relay = False
    s.sendall(frame(req.SerializeToString()))
    print(f"[{time.time() - t0:.3f}s] punch sent, waiting reply...")
    try:
        body, info = read_frame(s, wait, t0)
    except socket.timeout:
        print(f"[{time.time() - t0:.3f}s] TIMEOUT waiting punch reply (unknown peer, expected)")
        s.close()
        return "PUNCH_TIMEOUT_UNKNOWN_PEER"
    if body is None:
        print(f"[{info}] EOF")
        s.close()
        return "PUNCH_EOF"
    m = rz.RendezvousMessage()
    m.ParseFromString(body)
    print(f"[{info}] server replied: {m.WhichOneof('union')}")
    s.close()
    return "PUNCH_REPLIED"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=21116)
    ap.add_argument("--wait", type=float, default=35.0)
    a = ap.parse_args()
    r1 = stage_secure(a.host, a.port, a.wait)
    print()
    r2 = stage_punch(a.host, a.port, "", "", "PLAIN")
    print()
    r3 = stage_punch(a.host, a.port, "dummy-access-token", "dummy-licence-key", "TOKEN_PLAIN")
    print()
    print(f"RESULT secure={r1} plain={r2} token_plain={r3}")
    if r1 == "SECURE_FAIL_SILENCE" and r2 == "PUNCH_REPLIED":
        print("VERDICT: reproduced — secure stage silent, plain stage answered. "
              "Login-gated secure_tcp is the failing stage.")


if __name__ == "__main__":
    main()
