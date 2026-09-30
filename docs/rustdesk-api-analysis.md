# RustDesk Client API — анализ для Address Book backend (MVP)

Источник: `/home/user/Documents/rustdesk-master`, `Cargo.toml: version = "1.4.9"`.
Дата анализа: 2026-09-29. Клиент НЕ изменяется, backend мимикрирует под Server Pro.

Ключевые файлы: `flutter/lib/models/ab_model.dart`, `flutter/lib/models/user_model.dart`,
`flutter/lib/common/hbbs/hbbs.dart`, `flutter/lib/models/peer_model.dart`,
`flutter/lib/common.dart:2742 getHttpHeaders()`, `flutter/lib/common/widgets/login.dart:842`,
`flutter/lib/models/group_model.dart`, `src/common.rs:1049`, `src/flutter_ffi.rs:1143`.

## 0. Базовые соглашения

- Base URL = `bind.mainGetApiServer()` (опция `api-server`, иначе rendezvous минус 2 порта).
  MVP: `http://<ip>:<port>`, HTTPS не нужен.
- Auth: `Authorization: Bearer <access_token>` (`common.dart:2742`).
  Токен в локальной опции `access_token`, `user_info` — JSON UserPayload (`login.dart:779`).
- Ошибки: JSON `{"error": "текст"}`. Проверки: `containsKey('error') -> throw`, `status != 200 -> HTTP $code`.
  Action-endpoints: успех = `200 + пустое тело` (`ab_model.dart:2002`).
  `401` на pull = `userModel.reset()` = разлогин.
- Пустые POST (personal/settings/peers/tags/shared/profiles): `Content-Type: application/json` + `Content-Length: 0` без тела. Backend обязан принимать пустое тело.
- `decode_http_response` декодирует gzip (legacy `GET /api/ab` шлёт `Accept-Encoding: gzip`).

## 1. Auth

| Endpoint | Method | Request | Response | Где вызывается |
| -------- | ------ | ------- | -------- | -------------- |
| `/api/login` | POST | JSON без auth: `{"username","password","id","uuid","autoLogin":true,"type":"account","deviceInfo":{}}` (`hbbs.dart:155`, `login.dart:842`) | Успех: `{"access_token":"...","type":"access_token","user":{"name","display_name","avatar","email","note","status":1,"is_admin":bool}}` (`hbbs.dart:180`). Ошибка: `{"error":"..."}` + HTTP != 200 | `user_model.dart:193 login()` |
| `/api/currentUser` | POST | Bearer + `{"id","uuid"}` (`user_model.dart:64`) | JSON UserPayload. `401/400` -> разлогин | `user_model.dart:53 refreshCurrentUser()` |
| `/api/logout` | POST | Bearer + `{"id","uuid"}`. Ответ игнорируется, timeout 2с | Любой 2xx | `user_model.dart:170 logOut()` |
| `/api/login-options` | GET | без auth | `[]` = только логин/пароль | `user_model.dart:240` (MVP: вернуть `[]`) |

## 2. Discovery (порядок важен)

| Endpoint | Method | Request | Response | Где вызывается |
| -------- | ------ | ------- | -------- | -------------- |
| `/api/ab/settings` | POST | Bearer + `Content-Length: 0` | `{"max_peer_one_ab": int}` (0 = без лимита). `404` = игнор | `ab_model.dart:230` |
| `/api/ab/personal` | POST | Bearer + `Content-Length: 0` | `{"guid":"<uuid>"}`. `404` = legacy-режим | `ab_model.dart:262` |
| `/api/ab/shared/profiles` | POST | Bearer, query `?current=N&pageSize=100`, цикл до `total` | `{"total":int,"data":[{"guid","name","owner","note","info","rule":1\|2\|3}]}`. `404` = нет shared. rule: 1=read,2=readWrite,3=fullControl | `ab_model.dart:295` |

Personal-профиль клиент синтезирует сам (guid из personal, name="My address book", rule=1).
`canWrite`: personal всегда true; shared: rule 2/3 (`ab_model.dart:1393`).

## 3. Legacy AB (только если personal -> 404)

| Endpoint | Method | Request | Response | Где вызывается |
| -------- | ------ | ------- | -------- | -------------- |
| `/api/ab` | GET | Bearer + gzip | `"null"` = пусто; иначе `{"data":"<json-string>","licensed_devices":int}`, внутри `{"tags":[],"peers":[],"tag_colors":"{}"}` | `LegacyAb.pullAbImpl:1008` |
| `/api/ab` | POST | Bearer, `{"data":"<json-string>"}` | Успех: пустое тело / `"null"` + 200 | `LegacyAb.pushAb:1055` |

MVP: основной путь — non-legacy; legacy достаточно заглушить (`GET -> "null"`, `POST -> 200 пусто`).

## 4. Non-legacy AB (основной путь MVP)

`{guid}` = guid книги.

| Endpoint | Method | Request | Response | Где вызывается |
| -------- | ------ | ------- | -------- | -------------- |
| `/api/ab/peers` | POST | Bearer, пустое тело, query `?current=N&pageSize=100&ab={guid}` | `{"total":int,"data":[Peer]}`. Peer: `id,hash,password,username,hostname,platform,alias,tags[],forceAlwaysRelay,rdpPort,rdpUsername,loginName,device_group_name,note,same_server` (`peer_model.dart:33`) | `Ab._fetchPeers:1432` |
| `/api/ab/tags/{guid}` | POST | Bearer, пустое тело, без query | **Массив напрямую**: `[{"name":str,"color":int}]`, `[]` = пусто. Цвет = Flutter Color.value | `Ab._fetchTags:1499` |
| `/api/ab/peer/add/{guid}` | POST | Bearer, один Peer-JSON за запрос: `{"id","alias","tags":[]}` + `password` (shared) / `note` | 200 пусто = ok; `{"error"}` = текст в UI | `Ab.addPeers:1548` |
| `/api/ab/peer/update/{guid}` | PUT | Bearer, одно поле за запрос: `{"id","tags":[]}` / `{"id","alias"}` / `{"id","note"}` / `{"id","hash"}` (personal) / `{"id","password"}` (shared) / `{"id","username","hostname","platform"}` (sync) | 200 пусто | `changeTagForPeers:1581`, `changeAlias:1607`, `changeNote:1628`, `_setPassword:1648`, `syncFromRecent:1682` |
| `/api/ab/peer/{guid}` | DELETE | Bearer, body-массив id: `["123"]` | 200 пусто | `Ab.deletePeers:1752` |
| `/api/ab/tag/add/{guid}` | POST | Bearer, `{"name","color":int}` по одному | 200 пусто | `Ab.addTags:1776` |
| `/api/ab/tag/rename/{guid}` | PUT | Bearer, `{"old","new"}` | 200 пусто | `Ab.renameTag:1805` |
| `/api/ab/tag/update/{guid}` | PUT | Bearer, `{"name","color":int}` | 200 пусто | `Ab.setTagColor:1834` |
| `/api/ab/tag/{guid}` | DELETE | Bearer, body-массив имён: `["Tag"]` | 200 пусто | `Ab.deleteTag:1858` |

Нюансы: после мутаций клиент делает `pullAb(quiet:true)` — коммитить до ответа.
`changeTagForPeers` = по одному PUT на id. `tags` в update = полный список (синхронизация).
При add peer клиент отбрасывает несуществующие теги локально (`removeNonExistentTags`).

## 5. Group-панель (вне MVP, вызывается автоматически после логина)

| Endpoint | Method | MVP-заглушка | Где |
| -------- | ------ | ------------ | --- |
| `/api/device-group/accessible` | GET Bearer `?current=&pageSize=` | `{"total":0,"data":[]}` | `group_model.dart:103` |
| `/api/users` | GET Bearer `?current=&pageSize=&accessible=&status=1` | `{"total":0,"data":[]}` | `group_model.dart:160` |
| `/api/peers` | GET Bearer `?current=&pageSize=&accessible=&status=1` | `{"total":0,"data":[]}` | `group_model.dart:224` |

## 6. Вне MVP

OIDC/2FA (`email_check/tfa_check`, `/api/oidc/*`), `licensed_devices`, relay/hbbs/hbbr,
`/api/devices/*`, `/api/switch-grant`, `/api/record`, Sciter `src/ui/ab.tis /api/ab/get` (deprecated).

## 7. Маппинг на PostgreSQL ТЗ

- `users` <-> `/api/login`, `user` в currentUser.
- `sessions`/токены <-> opaque Bearer (`secrets`, не обязательно JWT).
- `address_books(id UUID...)` <-> `{guid}`. Personal = 1 книга на юзера.
- `address_book_entries(UNIQUE(book,rustdesk_id))` <-> Peer. `password_encrypted` (AES-GCM, ключ из env).
  `hash` (personal) хранить как есть.
- `tags(UNIQUE(book,name))`, `entry_tags(entry,tag)` <-> `Peer.tags:[str]`. PUT tags = sync в транзакции.
- `customers` — только Web Panel. `address_book_permissions(book,user,rule 1/2/3)` <-> `AbProfile.rule`.

## 8. Окружение (Debian 13 trixie)

`python3 = 3.13.5`, но `pip`, `docker`, `pg_isready` отсутствуют.
Перед Шагом 2: `sudo apt install python3-pip python3-venv postgresql` (или uv/docker).

## 9. Минимум для сценария §38

`/api/login`, `/api/currentUser`, `/api/logout`, `/api/login-options->[]`,
`/api/ab/settings`, `/api/ab/personal`, `/api/ab/shared/profiles`,
`/api/ab/peers`, `/api/ab/tags/{guid}`, `/api/ab/peer/add|update|{guid}`,
`/api/ab/tag/add|rename|update|{guid}` + заглушки legacy `/api/ab` и group.
