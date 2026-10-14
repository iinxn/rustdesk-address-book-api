# Connection Diagnostic

## Problem

`Connection error / Failed to secure tcp: deadline has elapsed: Please try later`
for the same RustDesk ID as soon as our API/Address Book is used; manual dial
without API works.

## Environment

- Debian 13 (trixie) x86_64, KDE Plasma, no docker, no sudo.
- Stand: `rustdesk-diagnostic/`, native `hbbs`+`hbbr` **1.1.16** (OSS).
- Client sources studied: rustdesk 1.4.9 (`rustdesk-master/`); hbbs sources:
  rustdesk-server master (`/tmp/opencode/hbbs_rv.rs`).
- hbbs key: auto-generated `data/id_ed25519[.pub]` (gitignored).
- Our backend: FastAPI, key-neutral (no key material in any response).

## Versions

hbbs/hbbr 1.1.16 · client code 1.4.9 · our API: `/api/login` + `/api/ab/*`
(contract in `../rustdesk-ab-backend/docs/rustdesk-api-analysis.md`).

## Topology

`repro (127.0.0.1) → hbbs 21116 TCP → hbbr 21117`, `ALWAYS_USE_RELAY=N`,
relay-servers=`127.0.0.1`. No NAT, no firewall, no proxy — transport noise
excluded by construction.

## Baseline result (no API)

Protocol-level baseline with real hbbs (`scripts/repro_handshake.py`):

- Plain `PunchHoleRequest` (empty token/key): `punch_hole_response` in ~1ms.
- With matching `licence_key` (=hbbs pub): response with NO failure field.
- With wrong key: `punch_hole_response{failure: 3}` = LICENSE_MISMATCH,
  hbbs logs `Authentication failed ... invalid key`.

Plain rendezvous path is alive.

## API login result (secure stage — REPRODUCED)

Simulated exactly what client 1.4.9 does when `access_token` is present
(`client.rs:418-421` → `secure_tcp_impl` waits server-first `KeyExchange`):

- Bare TCP connect to hbbs:21116 succeeds in ~2-5ms.
- hbbs sends NOTHING: 12s silence (no `-k` and with `-k` runs), EOF on longer
  idle (hbbs 30s read timeout). Result: `SECURE_FAIL_SILENCE/EOF`.
- hbbs source proof: `handle_listener_inner` only reads (`timeout(30s,
  b.next())`), `handle_tcp` has NO `KeyExchange` arm — OSS hbbs never speaks
  first. The secure rendezvous channel is a Pro-hbbs feature.

So every logged-in connection dies here with `deadline has elapsed` before
any peer contact — regardless of key match (verified: silence also with `-k`).

## Address Book result

Peer data cannot influence the failing stage: AB and manual share `connect()`
→ identical `Client::start` inputs; `password/hash` are post-handshake;
`force_relay`/`switch_uuid` sources identical. One AB-only vector existed —
`@`/`/r` IDs redirecting transport (client.rs:1811-1846) — now rejected
server-side with 422 (`rustdesk-ab-backend`: `app/core/validators.py`,
`tests/test_id_validation.py`).

## Forced relay result

Not runnable here (needs two live clients); relay path is downstream of the
failing stage — irrelevant until the rendezvous handshake passes. hbbr 1.1.16
is up on 21117 for the manual QA run.

## Logs (correlated)

```text
18:00:43 hbbs Start, ALWAYS_USE_RELAY=N
18:00:5x repro: TCP connect OK, 15s server silence -> secure FAIL
18:00:5x repro: plain punch -> punch_hole_response in ~1ms (path alive)
18:00:5x hbbs: Authentication failed ... invalid key (expected: dummy keys)
18:01:0x matching-key punch -> punch_hole_response, no failure field
```

hbbs logs: `logs/hbbs-plain.log`, `logs/hbbs-k.log`. Repro: `scripts/`.

## Root cause

Logged-in clients mandate a server-first `KeyExchange` rendezvous handshake
that OSS hbbs never performs (no first-send, no handler). The client waits
`READ_TIMEOUT` and reports `Failed to secure tcp: deadline has elapsed`.
Logout removes the token → handshake skipped → plain punch works. Key match
fixes only the LATER punch stage (`LICENSE_MISMATCH`), never this one.

## Fix

1. Backend hardening done: ID validation (422) + redacted `dump-book`
   + regression tests (22 green in backend repo).
2. KX SHIM (no hbbs rebuild, no client change): `scripts/kx_shim.py` speaks
   the v0 server side (spec `docs/kx-shim-spec.md`) and proxies to real hbbs.
   Proven by `scripts/test_kx_shim.py` — ALL PASS: crypt unit (nonce/counter/
   skip rules), secure roundtrip with exact client equations through the shim
   to real hbbs (decrypted `punch_hole_response`), plain passthrough
   byte-semantics unchanged. Remaining: live run with a logged-in stock
   client (no GUI client on this box).
3. Operational fallback (user side): pair any API login with a **Pro hbbs**
   (secure rendezvous), or accept logged-out-only use against OSS hbbs.

## HTTPS API (added 2026-10-01)

Local TLS stand in this same directory: `Caddyfile` (Caddy 2.10.2 binary in
`bin/`, no root needed), `certs/` (own CA `local-ca.crt` with proper
`CA:TRUE`+`keyCertSign`, server cert SANs `localhost/rustdesk-api.local/
127.0.0.1/192.168.31.105`):

- `https://localhost:8443` → FastAPI :8000 (TLS 1.3, `Verify return code: 0`).
- `http://localhost:8080` → same backend (HTTP-vs-HTTPS compare endpoint).
- `/etc/hosts` is read-only without sudo, so `localhost`+IP SANs are used
  instead of `rustdesk-api.local` (name is still in the SAN for later).
- `scripts/check_proxy_parity.py`: login/personal/peers payloads are
  byte-identical across direct/http/https; `Authorization: Bearer` passes
  through; bogus token → 401 everywhere. **PARITY OK.**
- `scripts/repro_handshake.py` re-run on the final stand: secure stage still
  silent, plain stages answered — **API scheme changes nothing about the
  secure-tcp outcome** (§36): HTTPS protects client↔API, not client↔hbbs.

## Verification

- [x] Repro script exits with the documented verdict on demand.
- [x] Proxy parity: direct/http/https payloads identical (`check_proxy_parity.py`).
- [x] Backend pytest 22 passed (no regressions).
- [ ] Live Tests A–D + forced relay with real clients (manual QA, needs
      Windows/second client) — protocol in backend
      `docs/connection-error-analysis.md`.

## HTTP vs HTTPS comparison (§26 table, protocol-level)

| API   | Login | Connection method | Result (proven) |
| ----- | ----- | ----------------- | --------------- |
| HTTP  | no    | manual (plain punch) | PASS (punch answered ~1ms) |
| HTTP  | yes   | manual/AB (secure_tcp gate) | FAIL (server silent → deadline) |
| HTTP  | yes   | Address Book      | FAIL (same gate; peer data irrelevant) |
| HTTPS | no    | manual            | PASS (scheme doesn't touch transport) |
| HTTPS | yes   | manual            | FAIL (same secure stage) |
| HTTPS | yes   | Address Book      | FAIL (same secure stage) |

API payloads are scheme-independent (parity script); the secure-tcp outcome
depends only on hbbs capabilities, never on HTTP vs HTTPS.
