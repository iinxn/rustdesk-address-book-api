#!/usr/bin/env python3
"""KX shim: speaks the Pro-style rendezvous KeyExchange (v0) to 1.4.x clients,
proxies decrypted traffic to a real OSS hbbs. Spec: docs/en.md §6.

  clients (21116) --> shim --> hbbs (127.0.0.1:21166, run with -p 21166)

Plain (logged-out) clients are proxied byte-for-byte. NEVER logs key material
(fingerprints only). Run: python3 kx_shim.py [--listen 0.0.0.0:21116
--upstream 127.0.0.1:21166 --id-key ../data/id_ed25519]
"""
import argparse
import asyncio
import base64
import hashlib
import logging
import struct
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import rendezvous_pb2 as rz  # noqa: E402
from nacl.bindings import (  # noqa: E402
    crypto_box,
    crypto_box_keypair,
    crypto_box_open,
    crypto_secretbox,
    crypto_secretbox_open,
    crypto_sign,
)

ZERO24 = b"\x00" * 24
FIRST_TIMEOUT = 40.0

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


async def frame_decode(reader: asyncio.StreamReader) -> bytes | None:
    try:
        first = await reader.readexactly(1)
    except (asyncio.IncompleteReadError, ConnectionError):
        return None
    hl = (first[0] & 0x3) + 1
    rest = b""
    if hl > 1:
        try:
            rest = await reader.readexactly(hl - 1)
        except (asyncio.IncompleteReadError, ConnectionError):
            return None
    n = int.from_bytes(first + rest, "little") >> 2
    if n == 0:
        return b""
    try:
        return await reader.readexactly(n)
    except (asyncio.IncompleteReadError, ConnectionError):
        return None


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
        raise SystemExit(f"bad id_ed25519 length: {len(raw)}")
    return raw


async def pipe_plain(src: asyncio.StreamReader, dst: asyncio.StreamWriter, tag: str):
    try:
        while True:
            data = await src.read(65536)
            if not data:
                break
            dst.write(data)
            await dst.drain()
    except (ConnectionError, asyncio.IncompleteReadError):
        pass
    except Exception as e:
        log.warning("%s pipe error: %r", tag, e)


async def pipe_c2s(reader, writer, crypt: SessionCrypt):
    """client -> hbbs: decrypt frame payloads, forward plaintext."""
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
    """hbbs -> client: encrypt frame payloads, forward."""
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


async def handle(conn_r, conn_w, upstream, sign_sk: bytes):
    peer = conn_w.get_extra_info("peername")
    try:
        up_r, up_w = await asyncio.open_connection(*upstream)
    except Exception as e:
        log.warning("%s: upstream %s unreachable: %r", peer, upstream, e)
        conn_w.close()
        return
    box_pk, box_sk = crypto_box_keypair()
    # Step 1: server-first KeyExchange, plaintext (spec §Handshake.1).
    kx = rz.RendezvousMessage()
    kx.key_exchange.keys.append(crypto_sign(bytes(box_pk), sign_sk))
    conn_w.write(frame_encode(kx.SerializeToString()))
    await conn_w.drain()
    log.info("%s: sent KX (box_pk=%s)", peer, fp(bytes(box_pk)))
    # Step 2: branch on first client frame (spec §Режимы).
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
        async def fwd_first():
            up_w.write(frame_encode(rest))
            await up_w.drain()
        await fwd_first()
        await asyncio.gather(
            pipe_plain(conn_r, up_w, "c2s-plain"),
            pipe_plain(up_r, conn_w, "s2c-plain"),
        )
    else:
        assert crypt is not None
        await asyncio.gather(
            pipe_c2s(conn_r, up_w, crypt),
            pipe_s2c(up_r, conn_w, crypt),
        )
    for w in (conn_w, up_w):
        try:
            w.close()
        except Exception:
            pass
    log.info("%s: closed (%s)", peer, mode)


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--listen", default="0.0.0.0:21116")
    ap.add_argument("--upstream", default="127.0.0.1:21166")
    ap.add_argument("--id-key", default="../data/id_ed25519")
    a = ap.parse_args()
    host, port = a.listen.rsplit(":", 1)
    uh, up = a.upstream.rsplit(":", 1)
    sign_sk = load_sign_sk(a.id_key)
    log.info("signing with hbbs key (pub=%s…)", base64.b64encode(sign_sk[32:]).decode()[:12])
    srv = await asyncio.start_server(
        lambda r, w: handle(r, w, (uh, int(up)), sign_sk), host, int(port))
    log.info("listening %s -> upstream %s", a.listen, a.upstream)
    async with srv:
        await srv.serve_forever()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    asyncio.run(main())
