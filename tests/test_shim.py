"""Shim unit tests (no network): framing, crypto rules, admission gates."""
import asyncio
import struct

import pytest

from app.shim import shim as S


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def test_frame_roundtrip():
    for n in (0, 1, 63, 64, 1000):
        assert run(S.frame_decode(_reader(S.frame_encode(b"x" * n)))) == b"x" * n


def _reader(data: bytes):
    r = asyncio.StreamReader()
    r.feed_data(data)
    r.feed_eof()
    return r


def test_frame_cap_rejects_huge():
    evil = bytes([(0x3FFFFFFF << 2 & 0xFF)])  # 1-byte header claiming huge len
    # header 0xFC -> head_len 1, n = 0xFC>>2 = 63, fine; craft 4-byte max:
    hdr = struct.pack("<I", (0x3FFFFFFF << 2 | 0x3) & 0xFFFFFFFF)
    assert run(S.frame_decode(_reader(hdr))) is None


def test_crypt_counters_and_skip():
    c = S.SessionCrypt(b"K" * 32)
    assert c.enc(b"") == b"" and c.dec(b"z") == b"z"
    assert (c.send_ctr, c.recv_ctr) == (0, 0)
    ct = c.enc(b"hello")
    assert (c.send_ctr, c.recv_ctr) == (1, 0)
    d = S.SessionCrypt(b"K" * 32)
    assert d.dec(ct) == b"hello"
    assert (d.send_ctr, d.recv_ctr) == (0, 1)
    assert S.nonce(1) == struct.pack("<Q", 1) + b"\x00" * 16


def test_wrong_key_decrypt_fails():
    c = S.SessionCrypt(b"K" * 32)
    ct = c.enc(b"hello")
    d = S.SessionCrypt(b"J" * 32)
    with pytest.raises(Exception):
        d.dec(ct)


def test_gate_rate_limit():
    import asyncio as _a
    g = S.Gate(max_conns=2, per_min_per_ip=2)
    assert g.admit("1.1.1.1") and g.admit("1.1.1.1")
    assert not g.admit("1.1.1.1")
    assert g.admit("2.2.2.2")

    async def _use():
        await g.sem.acquire()
        return True

    assert run(_use()) and run(_use())
