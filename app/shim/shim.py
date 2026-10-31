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
import os
import struct
import time
from collections import deque

from app.core.validators import validate_rustdesk_id
from app.services.discovery_events import publish as _publish_discovery
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
# Discovery: parse only small rendezvous control frames, never bulk traffic.
DISCOVERY_MAX_PARSE = 4096
# A single source IP may introduce at most this many *new* IDs per minute.
# Repeat "seen" events for already-known IDs are free (so keepalives work).
DISCOVERY_NEW_IDS_PER_IP_PER_MIN = int(
    os.environ.get("DISCOVERY_NEW_IDS_PER_IP_PER_MIN", "30")
)
DISCOVERY_REMEMBER_SEC = 1800.0

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
        self.max_conns = max_conns
        self.per_min = per_min_per_ip
        self.hits: dict[str, deque] = {}
        self._swept_at = time.monotonic()

    def admit(self, ip: str) -> bool:
        now = time.monotonic()
        # SEC-014: UDP source IPs are spoofable, so a flood from fake addresses
        # would otherwise grow `hits` without bound. Sweep stale buckets at most
        # once a minute (cheap, synchronous, single-threaded event loop).
        if now - self._swept_at > 60:
            self._swept_at = now
            self.sweep(now)
        q = self.hits.setdefault(ip, deque())
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= self.per_min:
            return False
        q.append(now)
        return True

    def sweep(self, now: float | None = None) -> None:
        """Drop empty/expired per-IP buckets (SEC-014)."""
        now = time.monotonic() if now is None else now
        for ip in list(self.hits):
            q = self.hits[ip]
            while q and now - q[0] > 60:
                q.popleft()
            if not q:
                del self.hits[ip]


# --- discovery (rendezvous evidence only; never tokens/keys) ---
#
# The shim sees the sender's *own* ID only in RegisterPk/RegisterPeer. Other
# messages (PunchHoleRequest, RequestRelay) carry the *target* ID and must
# never be attributed to the sender. A connection event is therefore built
# only from a target id seen on a connection that already identified its own
# id, and the two ids stay separate.
#
# Who asked: the stock client puts its API `access_token` (issued by our
# `/api/login`) into PunchHoleRequest/RequestRelay.token whenever it is logged
# in (client.rs/_start_inner; that also forces the secure KX path). The shim
# never forwards the token itself: only its SHA-256 leaves this thread, and the
# API resolves it against `sessions.token`. The digest is not stored either.

CONN_TYPE_NAMES = {
    0: "DEFAULT_CONN",
    1: "FILE_TRANSFER",
    2: "PORT_FORWARD",
    3: "RDP",
    4: "VIEW_CAMERA",
    5: "TERMINAL",
}
# RustDesk retries punch requests and falls back to RequestRelay within one
# attempt. One audit row per (initiator, token, target, connection type) per
# window is enough; the first request kind is kept as `via`.
CONNECTION_DEDUPE_SEC = float(os.environ.get("DISCOVERY_CONNECTION_DEDUPE_SEC", "60"))
_CONN_LAST: dict[tuple[str, str, str, str], float] = {}
_CONN_MAX_KEYS = 5000


def _parse_control(payload: bytes) -> dict | None:
    """Classify a small rendezvous control frame.

    Returns `{"sender_id": ...}` for RegisterPeer/RegisterPk or
    `{"target_id": ..., "via": ..., "conn_type": ..., "token_hash": ...}` for
    PunchHoleRequest/RequestRelay. Never returns raw bytes, tokens or key
    material: `token_hash` is the SHA-256 hex of the API token ("" if none).
    """
    if not payload or len(payload) > DISCOVERY_MAX_PARSE:
        return None
    try:
        m = rz.RendezvousMessage()
        m.ParseFromString(payload)
        kind = m.WhichOneof("union")
        if kind in ("register_peer", "register_pk"):
            rid = (getattr(m, kind).id or "").strip()
            if validate_rustdesk_id(rid) is not None:
                return None
            return {"kind": kind, "sender_id": rid}
        if kind == "punch_hole_request":
            req = m.punch_hole_request
            via = "direct"
        elif kind == "request_relay":
            req = m.request_relay
            via = "relay"
        else:
            return None
        target = (req.id or "").strip()
        if validate_rustdesk_id(target) is not None:
            return None
        token = req.token or ""
        return {
            "kind": kind,
            "target_id": target,
            "via": via,
            "conn_type": CONN_TYPE_NAMES.get(int(req.conn_type), ""),
            "token_hash": _token_hash(token) if 0 < len(token) <= 512 else "",
        }
    except Exception:
        return None


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8", "replace")).hexdigest()


def _sender_id(payload: bytes) -> str | None:
    info = _parse_control(payload)
    return info.get("sender_id") if info else None


def _publish_connection(from_id: str, target_id: str, ip: str, via: str,
                        conn_type: str, token_hash: str = "") -> bool:
    """Publish one connection attempt, collapsed over the dedupe window."""
    if CONNECTION_DEDUPE_SEC > 0:
        now = time.monotonic()
        key = (from_id, token_hash, target_id, conn_type)
        last = _CONN_LAST.get(key)
        if last is not None and now - last < CONNECTION_DEDUPE_SEC:
            return False
        _CONN_LAST[key] = now
        if len(_CONN_LAST) > _CONN_MAX_KEYS:
            for k, ts in list(_CONN_LAST.items()):
                if now - ts >= CONNECTION_DEDUPE_SEC:
                    _CONN_LAST.pop(k, None)
    return _publish_discovery(
        "connection", target_id, ip, "tcp",
        extra={"from_id": from_id, "via": via, "conn_type": conn_type,
               "token_hash": token_hash},
    )


class _DiscoveryGuard:
    """Rate-limit *new* IDs per source IP, allow repeat sightings freely."""

    def __init__(self) -> None:
        self.hits: dict[str, deque] = {}
        self.known: dict[str, dict[str, float]] = {}
        self._swept_at = time.monotonic()

    def admit(self, ip: str, rid: str) -> bool:
        now = time.monotonic()
        if now - self._swept_at > 60:
            self._swept_at = now
            self._sweep(now)
        known = self.known.setdefault(ip, {})
        last = known.get(rid)
        if last is not None and now - last < DISCOVERY_REMEMBER_SEC:
            known[rid] = now
            return True
        q = self.hits.setdefault(ip, deque())
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= DISCOVERY_NEW_IDS_PER_IP_PER_MIN:
            return False
        q.append(now)
        known[rid] = now
        return True

    def _sweep(self, now: float) -> None:
        for ip, q in list(self.hits.items()):
            while q and now - q[0] > 60:
                q.popleft()
            if not q:
                self.hits.pop(ip, None)
        for ip, known in list(self.known.items()):
            for rid, last in list(known.items()):
                if now - last >= DISCOVERY_REMEMBER_SEC:
                    known.pop(rid, None)
            if not known:
                self.known.pop(ip, None)


_GUARD = _DiscoveryGuard()
# id -> tokens of live TCP connections that identified themselves with it.
_ID_CONNS: dict[str, set[object]] = {}


class _ConnTracker:
    """Per-TCP-connection observation: learn the ID, keep liveness, close once."""

    def __init__(self, ip: str):
        self.ip = ip or "?"
        self.token = object()
        self.ids: set[str] = set()
        self.closed = False

    def observe(self, payload: bytes) -> None:
        info = _parse_control(payload)
        if info is None:
            if self.ids:
                # Keepalive/other frame on an identified connection: still alive.
                for known in self.ids:
                    _publish_discovery("seen", known, self.ip, "tcp")
            return

        rid = info.get("sender_id")
        if rid is not None:
            if rid not in self.ids:
                if not _GUARD.admit(self.ip, rid):
                    return
                self.ids.add(rid)
                conns = _ID_CONNS.setdefault(rid, set())
                conns.add(self.token)
                # First live connection for this ID -> connect, otherwise just
                # a sighting (another connection already keeps it online).
                _publish_discovery("connect" if len(conns) == 1 else "seen",
                                   rid, self.ip, "tcp")
            else:
                _publish_discovery("seen", rid, self.ip, "tcp")
            return

        target = info.get("target_id")
        if not target:
            return
        # A connection attempt is only meaningful with the initiator's own id,
        # which this connection learned from RegisterPeer/RegisterPk. When the
        # client has not identified itself yet, record the target with an
        # unknown initiator instead of guessing.
        senders = self.ids or {""}
        for sender in senders:
            _publish_connection(
                sender, target, self.ip,
                info.get("via", ""), info.get("conn_type", ""),
                info.get("token_hash", ""),
            )

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        for rid in list(self.ids):
            conns = _ID_CONNS.get(rid)
            if conns is not None:
                conns.discard(self.token)
            if not conns:
                _ID_CONNS.pop(rid, None)
                _publish_discovery("disconnect", rid, self.ip, "tcp")
        self.ids.clear()


def _observe_udp(data: bytes, ip: str) -> None:
    rid = _sender_id(data)
    if rid is None:
        return
    if not _GUARD.admit(ip, rid):
        return
    _publish_discovery("seen", rid, ip, "udp")


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


async def pipe_c2s(reader, writer, crypt: SessionCrypt, diag: bool,
                   peer, tracker: _ConnTracker | None = None):
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
            if tracker is not None:
                try:
                    tracker.observe(plain)
                except Exception as e:  # never break the protocol on a parser bug
                    log.debug("discovery observe error: %r", e)
            if diag:
                _log_msg("c2s", peer, plain)
            writer.write(frame_encode(plain))
            await writer.drain()
    except (ConnectionError, asyncio.IncompleteReadError):
        pass


def _log_msg(direction: str, peer, payload: bytes) -> None:
    """Diagnostic only (SHIM_DIAG_MSGTYPES=1): message type + target peer id.
    Never tokens, keys, passwords or raw bytes."""
    try:
        m = rz.RendezvousMessage()
        m.ParseFromString(payload)
        kind = m.WhichOneof("union")
        target = ""
        if kind == "punch_hole_request":
            target = f" id={m.punch_hole_request.id}"
        elif kind == "request_relay":
            target = f" id={m.request_relay.id}"
        elif kind == "register_peer":
            target = f" id={m.register_peer.id}"
        log.info("%s %s%s", direction, kind, target)
    except Exception as e:
        log.info("%s unparsed (%d bytes): %r", direction, len(payload), e)


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


async def handle(conn_r, conn_w, upstream, sign_sk: bytes, gate: Gate, diag: bool = False):

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
        await _handle(conn_r, conn_w, upstream, sign_sk, peer, diag)
    finally:
        gate.sem.release()


async def _handle(conn_r, conn_w, upstream, sign_sk: bytes, peer, diag: bool = False):
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
    ip = peer[0] if peer else "?"
    tracker = _ConnTracker(ip)
    try:
        if mode == "plain":
            log.info("%s: plain passthrough (%s)", peer, kind)
            try:
                tracker.observe(rest)
            except Exception as e:
                log.debug("discovery observe error: %r", e)
            up_w.write(frame_encode(rest))
            await up_w.drain()
            await asyncio.gather(
                pipe_plain(conn_r, up_w, "c2s-plain"),
                pipe_plain(up_r, conn_w, "s2c-plain"),
            )
        elif crypt is not None:
            await asyncio.gather(
                pipe_c2s(conn_r, up_w, crypt, diag, peer, tracker),
                pipe_s2c(up_r, conn_w, crypt),
            )
        else:
            log.warning("%s: no crypt in secure mode, close", peer)
            return
    finally:
        tracker.close()
        for w in (conn_w, up_w):
            try:
                w.close()
            except Exception:
                pass
    log.info("%s: closed (%s)", peer, mode)


# UDP rendezvous relay (plaintext protobuf: the UDP path has no crypto,
# all of it lives in the TCP Stream). NAT-style: each client address gets its
# own upstream socket so replies route back unambiguously. Sessions expire on
# idle; counts are capped; only session creation is rate-limited (datagrams
# themselves are cheap, keepalives must not trip the limiter).
UDP_IDLE_TIMEOUT = 120.0
UDP_SWEEP_INTERVAL = 30.0
UDP_MAX_DATAGRAM = 65507
# A real client re-registers every ~12 s from the same socket, so a session
# that has sent a single datagram for this long is not a live client (often a
# spoofed source). Such "unconfirmed" sessions are swept early and are the
# first to be evicted when the table is full, so one-shot floods cannot lock
# registered devices out.
UDP_UNCONFIRMED_TIMEOUT = 30.0
UDP_MAX_SESSIONS = 2048
UDP_NEW_PER_IP_PER_MIN = 600
UDP_LOG_EVERY = 60.0


class _UpstreamProto(asyncio.DatagramProtocol):
    def __init__(self, queue: asyncio.Queue):
        self.queue = queue

    def datagram_received(self, data: bytes, addr):
        try:
            self.queue.put_nowait((data, addr))
        except asyncio.QueueFull:
            pass

    def error_received(self, exc):
        pass

    def connection_lost(self, exc):
        try:
            self.queue.put_nowait(None)
        except asyncio.QueueFull:
            pass


class UdpRelay:
    """NAT-style UDP relay with its own budget (independent of TCP `Gate`).

    `gate` limits *new* sessions per source IP and `gate.max_conns` is the
    session-table size. Sessions that have sent only one datagram are kept in
    `unconfirmed` (insertion order = age) for early sweep and eviction.
    """

    def __init__(self, upstream: tuple[str, int], gate: Gate):
        self.upstream = upstream
        self.gate = gate
        self.transport: asyncio.DatagramTransport | None = None
        self.sessions: dict[tuple, dict] = {}
        self.unconfirmed: dict[tuple, float] = {}
        self._tasks: set[asyncio.Task] = set()
        self._closed = False
        self._drops = {"rate": 0, "full": 0, "evicted": 0}
        self._drops_logged_at = 0.0

    def _note_drop(self, kind: str) -> None:
        """Count drops; one summary line per UDP_LOG_EVERY instead of per packet."""
        self._drops[kind] += 1
        now = time.monotonic()
        if now - self._drops_logged_at >= UDP_LOG_EVERY:
            self._drops_logged_at = now
            log.warning("udp relay pressure: sessions=%d/%d rate_limited=%d full=%d evicted=%d",
                        len(self.sessions), self.gate.max_conns, self._drops["rate"],
                        self._drops["full"], self._drops["evicted"])
            self._drops = {"rate": 0, "full": 0, "evicted": 0}

    def _make_room(self) -> bool:
        """Free one slot for a new session: evict the oldest unconfirmed one."""
        if len(self.sessions) < self.gate.max_conns:
            return True
        if not self.unconfirmed:
            return False
        oldest = next(iter(self.unconfirmed))
        self._drop(oldest)
        self._note_drop("evicted")
        return True

    def _spawn(self, coro) -> asyncio.Task:
        # SEC-015: forget finished tasks instead of leaking them for the
        # lifetime of the process (long-running relay).
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    async def start(self, host: str, port: int):
        loop = asyncio.get_running_loop()
        transport, _ = await loop.create_datagram_endpoint(
            lambda: _ListenProto(self), local_addr=(host, port))
        self.transport = transport
        self._spawn(self._sweep())
        log.info("udp relay listening %s:%d -> %s:%d", host, port, *self.upstream)

    def datagram_received(self, data: bytes, addr):
        try:
            self._on_datagram(data, addr)
        except Exception as e:
            log.warning("udp dispatch error from %s: %r", addr[0] if addr else "?", e)

    def _on_datagram(self, data: bytes, addr):
        if self._closed or len(data) > UDP_MAX_DATAGRAM:
            return
        try:
            _observe_udp(data, addr[0])
        except Exception as e:
            log.debug("discovery udp observe error: %r", e)
        sess = self.sessions.get(addr)
        if sess is None:
            ip = addr[0]
            if not self.gate.admit(ip):
                self._note_drop("rate")
                return
            if not self._make_room():
                self._note_drop("full")
                return
            now = time.monotonic()
            sess = {"queue": asyncio.Queue(), "last": now, "created": now,
                    "up": None, "pending": data}
            self.sessions[addr] = sess
            self.unconfirmed[addr] = now
            self._spawn(self._responder(addr))
            log.debug("udp session opened for %s", ip)
            return
        sess["last"] = time.monotonic()
        # Second datagram from the same socket: a live client, not a one-shot.
        self.unconfirmed.pop(addr, None)
        up = sess["up"]
        if up is not None:
            up.sendto(data)

    async def _responder(self, addr):
        sess = self.sessions.get(addr)
        if sess is None:
            return
        try:
            loop = asyncio.get_running_loop()
            transport, _ = await loop.create_datagram_endpoint(
                lambda: _UpstreamProto(sess["queue"]),
                remote_addr=self.upstream)
            sess["up"] = transport
            pending = sess.pop("pending", b"")
            if pending:
                transport.sendto(pending)
            while True:
                try:
                    item = await asyncio.wait_for(sess["queue"].get(), UDP_IDLE_TIMEOUT)
                except asyncio.TimeoutError:
                    break
                if item is None:
                    break
                data, _ = item
                if self.transport is not None and not self._closed:
                    self.transport.sendto(data, addr)
                sess["last"] = time.monotonic()
        except (ConnectionError, OSError) as e:
            log.warning("udp upstream error for %s: %r", addr[0], e)
        finally:
            # The address may already belong to a newer session (evicted or
            # idle-dropped, then the client spoke again): close only our own.
            if self.sessions.get(addr) is sess:
                self._drop(addr)
            elif sess.get("up") is not None:
                try:
                    sess["up"].close()
                except Exception:
                    pass

    def _drop(self, addr):
        self.unconfirmed.pop(addr, None)
        sess = self.sessions.pop(addr, None)
        if sess is None:
            return
        up = sess.get("up")
        if up is not None:
            try:
                up.close()
            except Exception:
                pass
        try:
            sess["queue"].put_nowait(None)
        except asyncio.QueueFull:
            pass
        log.debug("udp session closed for %s", addr[0])

    async def _sweep(self):
        try:
            while not self._closed:
                await asyncio.sleep(UDP_SWEEP_INTERVAL)
                self.sweep_once(time.monotonic())
        except asyncio.CancelledError:
            pass

    def sweep_once(self, now: float) -> None:
        self.gate.sweep(now)  # SEC-014: guaranteed periodic purge
        for addr, created in list(self.unconfirmed.items()):
            if now - created > UDP_UNCONFIRMED_TIMEOUT:
                self._drop(addr)
        for addr, sess in list(self.sessions.items()):
            if now - sess["last"] > UDP_IDLE_TIMEOUT:
                self._drop(addr)

    async def aclose(self):
        self._closed = True
        for addr in list(self.sessions):
            self._drop(addr)
        for t in list(self._tasks):
            t.cancel()
        if self.transport is not None:
            try:
                self.transport.close()
            except Exception:
                pass
            self.transport = None


class _ListenProto(asyncio.DatagramProtocol):
    def __init__(self, relay: UdpRelay):
        self.relay = relay

    def datagram_received(self, data: bytes, addr):
        self.relay.datagram_received(data, addr)

    def error_received(self, exc):
        pass


def raise_fd_limit(udp_sessions: int, tcp_conns: int) -> None:
    """Each UDP session holds one upstream socket, each TCP proxy two sockets.

    The default soft RLIMIT_NOFILE (often 1024) is below what ~800 devices
    need; raise it up to the hard limit and warn when even that is too low.
    """
    try:
        import resource
    except ImportError:  # non-POSIX
        return
    need = udp_sessions + 2 * tcp_conns + 256
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    if soft != resource.RLIM_INFINITY and soft < need:
        target = need if hard == resource.RLIM_INFINITY else min(need, hard)
        try:
            resource.setrlimit(resource.RLIMIT_NOFILE, (target, hard))
            soft = target
        except (ValueError, OSError) as e:
            log.warning("cannot raise RLIMIT_NOFILE to %d: %r", target, e)
    if soft != resource.RLIM_INFINITY and soft < need:
        log.warning("RLIMIT_NOFILE=%d is below the %d sockets the shim may need; "
                    "raise LimitNOFILE / ulimit -n", soft, need)


async def amain(args):
    host, port = args.listen.rsplit(":", 1)
    uh, up = args.upstream.rsplit(":", 1)
    sign_sk = load_sign_sk(args.id_key)
    gate = Gate(args.max_conns, args.per_ip_per_min)
    udp_gate = Gate(args.udp_max_sessions, args.udp_per_ip_per_min)
    raise_fd_limit(args.udp_max_sessions, args.max_conns)
    # A restarted shim has no live TCP connections from the previous run.
    _publish_discovery("reset", "*")
    log.info("signing with hbbs key (pub=%s…)", base64.b64encode(sign_sk[32:]).decode()[:12])
    relay = UdpRelay((uh, int(up)), udp_gate)
    await relay.start(host, int(port))
    srv = await asyncio.start_server(
        lambda r, w: handle(r, w, (uh, int(up)), sign_sk, gate), host, int(port))
    log.info("listening %s -> upstream %s", args.listen, args.upstream)
    try:
        async with srv:
            await srv.serve_forever()
    finally:
        await relay.aclose()


def build_parser():
    import argparse as _ap
    ap = _ap.ArgumentParser(prog="app.shim")
    ap.add_argument("--listen", default="127.0.0.1:21116")
    # NOTE: the relay port (hbbs 21117) speaks a different protocol — upstream
    # must be the hbbs *rendezvous* port (moved with `hbbs -p`, e.g. 21166).
    ap.add_argument("--upstream", default="127.0.0.1:21166")
    ap.add_argument("--id-key", default="")
    ap.add_argument("--max-conns", type=int, default=MAX_CONNS)
    ap.add_argument("--per-ip-per-min", type=int, default=MAX_CONNS_PER_MIN_PER_IP)
    ap.add_argument("--udp-max-sessions", type=int, default=UDP_MAX_SESSIONS)
    ap.add_argument("--udp-per-ip-per-min", type=int, default=UDP_NEW_PER_IP_PER_MIN)
    return ap


def main(argv=None):
    import asyncio as _aio
    _aio.run(amain(build_parser().parse_args(argv)))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    main()
