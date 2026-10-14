# KX Shim — спецификация серверной стороны secure-rendezvous (v0, клиент 1.4.x)

Шим слушает клиентский порт вместо hbbs, выполняет с клиентом тот же обмен,
что Pro-hbbs, дальше гоняет расшифрованный трафик в настоящий hbbs.

Источники (все уравнения — оттуда, побайтово):
- `rustdesk/src/common.rs:1999 secure_tcp_impl`, `:2084 create_symmetric_key_msg`
- `rustdesk/hbb_common/src/tcp.rs`: `Encrypt::{new,enc,dec}`, `get_nonce`,
  `FramedStream::{send_raw,next,set_key}`, `BytesCodec` framing
- `rustdesk/hbb_common/protos/rendezvous.proto`: `KeyExchange{keys[bytes]=1}`

## Обозначения

- `SignSk/SighPk` — ed25519-ключи hbbs (`data/id_ed25519`: base64 64 байт;
  вторая половина = SignPk = содержимое `id_ed25519.pub`). Клиент сверяет
  подпись этим ключом (`get_rs_pk(key)` из своей настройки Key).
- `BoxSk_S/BoxPk_S` — Curve25519-ключи шима, свежие на каждое соединение.
- `K` — 32-байтный secretbox-ключ сессии, генерирует КЛИЕНТ.
- `ZERO24` — 24 нулевых байта (nonce для box).
- `N(s)` — 24 байта: LE64(s) + 16 нулей (nonce для secretbox кадров).

## Handshake

1. Шим → клиент (сразу по accept, plaintext frame):
   `RendezvousMessage{key_exchange: {keys: [ed25519_sign(BoxPk_S, SignSk)]}}`
   (ровно 1 ключ — клиент проверяет `keys.len() == 1`).
2. Клиент → шим (plaintext frame):
   `RendezvousMessage{key_exchange: {keys: [EphemPk_C(32B), sealed]}}`,
   где `sealed = crypto_box(K, ZERO24, BoxPk_S, EphemSk_C)`.
3. Шим: `K = crypto_box_open(sealed, ZERO24, EphemPk_C, BoxSk_S)`;
   длина K обязана быть 32, иначе рвём соединение.
4. Дальше обе стороны: `Encrypt::new(K)` — счётчики `send=0/recv=0`.

## Кадры после handshake (обе стороны, симметрично)

- Фрейминг ВНЕ шифра (BytesCodec, как в repro: 1/2/3/4-байтный LE-заголовок).
- Полезная нагрузка кадра длиной `<= 1` идёт ОТКРЫТО, счётчики не трогаются
  (пустые heartbeat `Bytes::new()` обеих сторон).
- Иначе отправка: `send += 1; cipher = secretbox_seal(plain, N(send), K)`.
- Иначе приём: `recv += 1; plain = secretbox_open(cipher, N(recv), K)`;
  ошибка → рвём соединение (несоответствие счётчиков = fatal, как у клиента).

Порядок критичен: клиент шлёт свой KeyExchange-ответ открытым текстом и
только потом `set_key`; первый зашифрованный кадр клиента — PunchHoleRequest
с nonce=1. Шим зеркально: ответ уже получен открытым, свой `set_key` — сразу
после шага 3, первый входящий шифрокадр ждёт с nonce=1.

## Режимы (определяются по первому кадру клиента)

- Первый кадр = `key_exchange` с 2 ключами → SECURE (выше).
- Первый кадр = валидный plaintext `RendezvousMessage` с другим union
  (напр. `punch_hole_request`) → PLAIN passthrough: шим работает глупым
  TCP-прокси без крипто. Стартовый KeyExchange шима plain-клиентам не мешает:
  их `get_next_nonkeyexchange_msg` такие кадры пропускает (проверено: фейковый
  plain-клиент без skip-логики прочитал бы KX шима первым — как и положено).
- Ни то ни другое → закрыть соединение.

## Ключи и порты

- SignSk: читается из `data/id_ed25519` при старте шима (только чтение).
- hbbs переезжает на `127.0.0.1:21166` (`-p 21166`), шим слушает `0.0.0.0:21116`
  и проксирует туда. Клиенты ничего не меняют (тот же ID-сервер:21116).
- Поддерживается только v0 (`set_key`, один ключ на оба направления) —
  то, что использует secure_tcp клиента 1.4.x. v1/split (`set_key_split`,
  `KxParams`, `signed_params`) — не реализовано, отдельная работа.

## Что НЕ логировать

`K`, BoxSk_S, SignSk, содержимое sealed/кадров. Только отпечатки
(SHA256 первых 8 hex) и счётчики.
