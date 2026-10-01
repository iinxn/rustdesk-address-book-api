# Connection Error Analysis

## Symptom

Logged-in RustDesk Client → Address Book → device → `Connection error:
Failed to secure tcp: deadline has elapsed`. Same ID typed manually while
logged out connects fast. Logout restores manual connections.

## Reproduction (empirically proven against live hbbs 1.1.16)

Stand: `rustdesk-diagnostic/` (native hbbs/hbbr,Key auto-generated).
Full proof in `rustdesk-diagnostic/docs/connection-diagnostic.md`; summary:

- `scripts/repro_handshake.py` speaks the real rendezvous protocol (protobuf
  schema from `rustdesk/hbb_common`, `BytesCodec` framing from source).
- Secure stage (what a logged-in client does): TCP connects in ~2ms, hbbs
  sends NOTHING for 12-35s (runs with and without `-k`), then EOF on hbbs
  30s idle timeout. hbbs source: `handle_listener_inner` only reads;
  `handle_tcp` has NO `KeyExchange` arm — OSS hbbs never speaks first.
- Plain stage (logged-out client): framed `PunchHoleRequest` answered in
  ~1ms (`punch_hole_response`; `failure: 3` LICENSE_MISMATCH on wrong key,
  no failure field with matching key).

Live GUI-client Tests A–D/forced-relay still require real endpoints and
remain manual QA (protocol in Verification below).

## Comparison

### Where the error text comes from

`src/client.rs:419-421`:

```rust
if !key.is_empty() && (!token.is_empty() || !switch_code.is_empty()) {
    secure_tcp(&mut socket, &key)
        .await
        .map_err(|e| anyhow!("Failed to secure tcp: {}", e))?;
}
```

`socket` at this point is the plain TCP connection to the **rendezvous
server (hbbs)** (`connect_tcp(&*rendezvous_server, ...)` at `:382`). This is
the ONLY place producing `Failed to secure tcp`. It happens before any
peer-specific logic (punch request is built later at `:450`).

`secure_tcp_impl` (`src/common.rs:1999-2043`) waits `READ_TIMEOUT` for the
server's `KeyExchange` message (`:2011`). Silence → timeout error, rendered
as `deadline has elapsed`.

### Gate inputs — login vs peer data

| Input | Source | Login-gated? | AB-gated? |
| ----- | ------ | ------------ | --------- |
| `key` (licence key) | `crate::get_key(false)` | No — and **never empty**: falls back to built-in `RS_PUB_KEY` (`src/common.rs:1865-1884`) | No |
| `token` | `LocalConfig::get_option("access_token")` (`src/ui_session_interface.rs:1943`) | **YES — set only by `/api/login`, cleared on logout** | No |
| `switch_code` | `switch_uuid` from fleet-switch flows only (`src/client.rs:3769-3777`, `src/flutter.rs:1323-1327`) | No | No (AB passes `''`) |
| `rendezvous_server` | client ID-server settings | No | No |

Effective gate: `secure_tcp` to hbbs runs **iff logged in**. Logged out →
plain TCP rendezvous → works.

### Manual connection

`connect()` in `flutter/lib/common.dart:2578-2604` → same `session_add` →
same `Client::start(peer, key, token=access_token, ...)`. When logged out,
`token` is empty → handshake skipped.

### Address Book connection

AB tap calls the same `connect(id, password: peer.password, ...)` with the
same ID string. Differences vs manual are ONLY:

- `password`/`shared_password` preset (`src/flutter.rs:1305-1316`) — used in
  the post-handshake login to the remote peer, AFTER a secure channel exists.
  Cannot cause a rendezvous-stage `secure tcp` failure.
- `force_relay` — from per-ID **local** peer option or UI default `false`
  (`src/client.rs:1873-1877`); identical store for manual and AB for one ID.
- `Peer` display fields (`alias/tags/note/username/hostname/platform`) —
  never read by the transport path. `Peer.fromJson` ignores unknown keys.

Conclusion: **no field our `/api/ab/peers` returns can influence the failing
stage.** Our responses contain only display/auth-data keys
(`id/alias/tags/note/username/hostname/platform/hash/password`), no
`server/relay/rendezvous/key/url/port` keys (locked by regression test).

## What exactly changes after API login / AB selection

Definitive per-input diff (manual vs AB, logged in vs out):

| Client state / path input | After API login | After AB selection | Feeds secure_tcp? |
| ------------------------- | --------------- | ------------------ | ----------------- |
| `access_token` (LocalConfig) | set (enables secure_tcp gate) | — | **YES (gate)** |
| `user_info` cache | set | — | No |
| AB/group caches (`mainSaveAb/Group`) | pulled | — | No |
| `rendezvous_server`, `key`, proxy/ws options | unchanged | unchanged | (inputs, unchanged) |
| Session `password` preset | — | set from peer (post-handshake auth only) | No |
| Session `force_relay` | — | same default `false`, same local per-ID option store | No |
| Session `switch_uuid` | — | `''` (only fleet-switch flows set it) | No |
| `rustdesk_id` string | — | passed through; `@`/`/r` forms would redirect transport — **now rejected server-side (422), see below** | Only via `@`/`/r` forms |

### ID redirect vector — found and fixed in our backend

`LoginConfigHandler::initialize` (`src/client.rs:1811-1846`): an ID
containing `@` is parsed as `id@server?key=...` and silently redirects the
whole connection (server + key) elsewhere; a trailing `/r` forces relay.
`connect()` strips spaces but not these. So a crafted/stale `rustdesk_id`
in an Address Book is the ONE peer-data shape that changes the connection
path while the bare ID typed manually works.

Fix (this repo, no client change): `app/core/validators.py` —
`validate_rustdesk_id` rejects `@ / \ ? & =`, whitespace and anything outside
`[A-Za-z0-9._-]`; enforced in `POST /api/ab/peer/add`, `POST/PUT /api/v1`
entries and the Jinja panel form (422 + `{"error"}`). Tests:
`tests/test_id_validation.py`. Existing numeric/standard IDs unaffected.

### Live log protocol (one run decides it)

On the failing client, filter the log for this exact sequence:

```text
rendezvous server: <host>     # which hbbs is actually dialed
Connection secured             # present = handshake OK (then cause is later)
Failed to secure tcp: deadline has elapsed   # absent handshake reply in READ_TIMEOUT
#1 TCP punch attempt ...       # only if handshake passed
```

- `Failed to secure tcp` with NO preceding `Connection secured` → hbbs never
  completed key exchange → check hbbs edition + key match (Fix §1-3).
- `Connection secured` present but punch/relay then fails → different stage,
  re-open with punch/relay logs (this analysis does not apply).

## Root Cause

Primary (code-proven mechanism, needs live confirmation of Variant A):

> After API login, the client mandates an encrypted rendezvous handshake
> (`secure_tcp`, key exchange with `key` = custom licence key or built-in
> `RS_PUB_KEY`) with hbbs. If hbbs cannot complete it within READ_TIMEOUT —
> community/non-Pro hbbs, **client key ≠ hbbs key** (official FAQ cause),
> proxy/firewall breaking the exchange — every logged-in connection dies with
> `Failed to secure tcp: deadline has elapsed` before any peer contact.
> Logout removes the token → handshake skipped → manual works again.

The reported AB-vs-manual contrast is most likely an untested confound: when
logged in, users connect via AB; login+manual was never tried (§25). If that
test also fails → Variant A, purely login-state, backend peer data exonerated.

Ruled out (by code): peer serialization, password/hash format, tag data,
`forceAlwaysRelay`, `switch_uuid`, our API changing rendezvous/relay/key
config (our responses carry no such fields; client config changes only via
settings UI or hbbs `ConfigureUpdate`).

## Evidence

- Gate + error site: `src/client.rs:411-421`, `:850-852` (relay path, same gate).
- Token source: `src/ui_session_interface.rs:1943`.
- Key never empty: `src/common.rs:1865-1884`.
- Timeout shape: `src/common.rs:2011` (`timeout(READ_TIMEOUT, conn.next())`).
- Comment acknowledging this timeout class: `src/client.rs:3814`.
- Shared connect path: `flutter/lib/common.dart:2578-2604`,
  `flutter/lib/models/model.dart:3805-3818`.
- Our backend payload safety: `tests/test_connection_safety.py` (allowed key
  sets, password/hash roundtrip, error shape).

## Fix

No FastAPI code change can fix a client↔hbbs handshake and none was made
(returning no token would break Address Book itself). Fix is server-side /
operational, in order:

1. Run the §25 fork: login + manual ID. FAIL → Variant A confirmed (this analysis).
2. `hbbs` edition: secure rendezvous handshake needs Pro (or key-exchange
   capable) hbbs. Check `hbbs`/`hbbr` versions and logs at the connect timestamp.
3. Key match (FAQ #1 cause): client Settings → Key must equal hbbs
   `id_ed25519.pub`. Mismatch → `Signature mismatch`/timeout in exchange.
4. Force-relay experiment (§13): if relay-forced connects, direct/UDP path or
   NAT handling is involved — still after the rendezvous stage, diagnostic only.
5. `hbbs`/`hbbr`/client logs with one timestamp (§22); tcpdump rendezvous
   port if still unclear (§23).

## Regression Test

`tests/test_connection_safety.py` (runs in CI, no live client needed):

1. login response contains only contract keys (no config-changing fields);
2. personal AND shared peer payloads contain no transport-affecting keys
   (`server/relay/rendezvous/key/url/port/host/...` — exact deny-list);
3. shared `password` encrypt→API→decrypt roundtrip is byte-identical
   (catches key rotation/corruption that WOULD break post-handshake auth);
4. personal `hash` roundtrip identical;
5. error bodies keep `{"error": ...}` shape the client parses.

`tests/test_id_validation.py`: `@ / \ ? & =`, whitespace and non-ID
characters are rejected with 422 on all entry-create/update paths.

## Verification

- `pytest`: all green (14 existing + 5 new).
- Live Tests 1–5, A/B/C devices, password/no-password, multi-book (§31–§35)
  require a Windows client + hbbs/hbbr and are recorded here as the manual QA
  checklist; §25 fork result decides Variant A vs B.

Safe debug representation (§9): log peer responses only with
`password/hash/token` redacted; this repo never logs them (see `app/core/logging.py`).
