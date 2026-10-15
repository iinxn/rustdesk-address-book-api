#!/usr/bin/env python3
"""KX shim: speaks the Pro-style rendezvous KeyExchange (v0) to 1.4.x clients,
proxies decrypted traffic to a real OSS hbbs. Spec: docs/en.md §6.

Hardened for external exposure (21116 WILL face the general network):
- frame size cap (2MB), read timeouts everywhere (no slow-loris hold),
- max concurrent connections + per-IP connection rate limit,
- no auth exists in the rendezvous protocol itself; the shim adds none
  (stock clients must keep working) — exposure is limited by the caps above
  plus upstream hbbs licence_key enforcement at punch stage.
NEVER logs key material (fingerprints only).
"""
import argparse
import asyncio
import base64
import hashlib
import logging
import struct
import time
from collections import deque

from app.shim import rendezvous_pb2 as rz
from nacl.bindings import (
    crypto_box,
    crypto_box_keypair,
    crypto_box_open,
    crypto_secretbox,
    crypto_secretbox_open,
    crypto_sign,
)

ZERO24 = b"\x00" * 24
FIRST_TIMEOUT = 40.0
READ_TIMEOUT = 60.0
MAX_FRAME = 2 * 1024 * 1024
MAX_CONNS = 200
MAX_CONNS_PER_MIN_PER_IP = 30

log = logging.getLogger("kx-shim")


def fp(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()[:8]


def nonce(s: int) -> bytes:
    return struct.pack("<Q", s & 0xFFFFFFFFFFFFFFFF) + b"\x00" * 16


def frame_encode(payload: bytes) -> bytes:
    n = len(payload)
    if n <= 0x3F:
        return bytes([(n << 2) & 0xFF]) + payload
    if n <= 0x3FFF:
        return struct.pack("<H", ((n << 2) | 0x1) & 0xFFFF) + payload
    if n <= 0x3FFFFF:
        h = ((n << 2) | 0x2) & 0xFFFFFFFF
        return struct.pack("<H", h & 0xFFFF) + bytes([(h >> 16) & 0xFF]) + payload
    raise ValueError("frame too big")


async def read_exactly(reader: asyncio.StreamReader, n: int) -> bytes | None:
    try:
        return await asyncio.wait_for(reader.readexactly(n), READ_TIMEOUT)
    except (asyncio.IncompleteReadError, ConnectionError, asyncio.TimeoutError):
        return None


async def frame_decode(reader: asyncio.StreamReader) -> bytes | None:
    first = await read_exactly(reader, 1)
    if not first:
        return None
    hl = (first[0] & 0x3) + 1
    rest = b""
    if hl > 1:
        rest = await read_exactly(reader, hl - 1)
        if rest is None:
            return None
    n = int.from_bytes(first + rest, "little") >> 2
    if n > MAX_FRAME:
        return None
    if n == 0:
        return b""
    return await read_exactly(reader, n)


class SessionCrypt:
    """Mirror of tcp.rs Encrypt::new (v0): counters ++ before use, skip len<=1."""

    def __init__(self, key: bytes):
        self.key = key
        self.send_ctr = 0
        self.recv_ctr = 0

    def enc(self, data: bytes) -> bytes:
        if len(data) <= 1:
            return data
        self.send_ctr += 1
        return crypto_secretbox(data, nonce(self.send_ctr), self.key)

    def dec(self, data: bytes) -> bytes:
        if len(data) <= 1:
            return data
        self.recv_ctr += 1
        return crypto_secretbox_open(data, nonce(self.recv_ctr), self.key)


def load_sign_sk(path: str) -> bytes:
    raw = base64.b64decode(open(path).read().strip())
    if len(raw) != 64:
        raise SystemExit(f"FATAL: bad id_ed25519 length: {len(raw)}")
    return raw


class Gate:
    """Concurrency + per-IP rate limits."""

    def __init__(self, max_conns: int, per_min_per_ip: int):
        self.sem = asyncio.Semaphore(max_conns)
        self.per_min = per_min_per_ip
        self.hits: dict[str, deque] = {}

    def admit(self, ip: str) -> bool:
        now = time.monotonic()
        q = self.hits.setdefault(ip, deque())
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= self.per_min:
            return False
        q.append(now)
        return True


async def pipe_plain(src, dst, tag: str):
    try:
        while True:
            try:
                data = await asyncio.wait_for(src.read(65536), READ_TIMEOUT)
            except asyncio.TimeoutError:
                break
            if not data:
                break
            dst.write(data)
            await dst.drain()
    except (ConnectionError, asyncio.IncompleteReadError):
        pass
    except Exception as e:
        log.warning("%s pipe error: %r", tag, e)


async def pipe_c2s(reader, writer, crypt: SessionCrypt):
    try:
        while True:
            p = await frame_decode(reader)
            if p is None:
                break
            try:
                plain = crypt.dec(p)
            except Exception:
                log.warning("c2s decrypt failed, closing")
                break
            writer.write(frame_encode(plain))
            await writer.drain()
    except (ConnectionError, asyncio.IncompleteReadError):
        pass


async def pipe_s2c(reader, writer, crypt: SessionCrypt):
    try:
        while True:
            p = await frame_decode(reader)
            if p is None:
                break
            writer.write(frame_encode(crypt.enc(p)))
            await writer.drain()
    except (ConnectionError, asyncio.IncompleteReadError):
        pass
    except Exception as e:
        log.warning("s2c error: %r", e)


async def handle(conn_r, conn_w, upstream, sign_sk: bytes, gate: Gate):
    peer = conn_w.get_extra_info("peername")
    ip = peer[0] if peer else "?"
    if not gate.admit(ip):
        log.warning("%s: connection rate limited", ip)
        conn_w.close()
        return
    try:
        await asyncio.wait_for(gate.sem.acquire(), 10)
    except asyncio.TimeoutError:
        log.warning("%s: overloaded, drop", ip)
        conn_w.close()
        return
    try:
        await _handle(conn_r, conn_w, upstream, sign_sk, peer)
    finally:
        gate.sem.release()


async def _handle(conn_r, conn_w, upstream, sign_sk: bytes, peer):
    try:
        up_r, up_w = await asyncio.wait_for(asyncio.open_connection(*upstream), 10)
    except Exception as e:
        log.warning("%s: upstream %s unreachable: %r", peer, upstream, e)
        conn_w.close()
        return
    box_pk, box_sk = crypto_box_keypair()
    kx = rz.RendezvousMessage()
    kx.key_exchange.keys.append(crypto_sign(bytes(box_pk), sign_sk))
    conn_w.write(frame_encode(kx.SerializeToString()))
    await conn_w.drain()
    log.info("%s: sent KX (box_pk=%s)", peer, fp(bytes(box_pk)))
    try:
        first = await asyncio.wait_for(frame_decode(conn_r), FIRST_TIMEOUT)
    except asyncio.TimeoutError:
        first = None
    if first is None:
        log.info("%s: no first frame, close", peer)
        conn_w.close()
        up_w.close()
        return
    mode = "plain"
    crypt = None
    rest = first
    try:
        m = rz.RendezvousMessage()
        m.ParseFromString(first)
        kind = m.WhichOneof("union")
    except Exception:
        kind = None
    if kind == "key_exchange" and len(m.key_exchange.keys) == 2:
        try:
            cli_eph, sealed = bytes(m.key_exchange.keys[0]), bytes(m.key_exchange.keys[1])
            if len(cli_eph) != 32:
                raise ValueError("bad eph pk len")
            K = crypto_box_open(sealed, ZERO24, cli_eph, box_sk)
            if len(K) != 32:
                raise ValueError("bad K len")
            crypt = SessionCrypt(K)
            mode = "secure"
            rest = None
            log.info("%s: secure established (cli_eph=%s)", peer, fp(cli_eph))
        except Exception as e:
            log.warning("%s: KX open failed: %r", peer, e)
            conn_w.close()
            up_w.close()
            return
    if mode == "plain":
        log.info("%s: plain passthrough (%s)", peer, kind)
        up_w.write(frame_encode(rest))
        await up_w.drain()
        await asyncio.gather(
            pipe_plain(conn_r, up_w, "c2s-plain"),
            pipe_plain(up_r, conn_w, "s2c-plain"),
        )
    elif crypt is not None:
        await asyncio.gather(
            pipe_c2s(conn_r, up_w, crypt),
            pipe_s2c(up_r, conn_w, crypt),
        )
    else:
        log.warning("%s: no crypt in secure mode, close", peer)
        conn_w.close()
        up_w.close()
        return
    for w in (conn_w, up_w):
        try:
            w.close()
        except Exception:
            pass
    log.info("%s: closed (%s)", peer, mode)


async def amain(args):
    host, port = args.listen.rsplit(":", 1)
    uh, up = args.upstream.rsplit(":", 1)
    sign_sk = load_sign_sk(args.id_key)
    gate = Gate(args.max_conns, args.per_ip_per_min)
    log.info("signing with hbbs key (pub=%s…)", base64.b64encode(sign_sk[32:]).decode()[:12])
    srv = await asyncio.start_server(
        lambda r, w: handle(r, w, (uh, int(up)), sign_sk, gate), host, int(port))
    log.info("listening %s -> upstream %s", args.listen, args.upstream)
    async with srv:
        await srv.serve_forever()


def build_parser():
    import argparse as _ap
    ap = _ap.ArgumentParser(prog="app.shim")
    ap.add_argument("--listen", default="127.0.0.1:21116")
    ap.add_argument("--upstream", default="127.0.0.1:21117")
    ap.add_argument("--id-key", default="")
    ap.add_argument("--max-conns", type=int, default=MAX_CONNS)
    ap.add_argument("--per-ip-per-min", type=int, default=MAX_CONNS_PER_MIN_PER_IP)
    return ap


def main(argv=None):
    import asyncio as _aio
    _aio.run(amain(build_parser().parse_args(argv)))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    main()
