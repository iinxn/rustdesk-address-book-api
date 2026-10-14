# Security audit

Method: manual code review of every route/service/shim path + `pip-audit`
(clean), `bandit` (0 High, 3 Low dispositioned below), `npm audit`
(1 High, build-time only, fixed), targeted regression tests (all green).
Date: 2026-10-12. Auditor: OpenCode (automated, human-reviewed plan).

| Уязвимость | Критичность | Компонент | Причина | Исправление | Проверка | Остаточный риск |
|---|---|---|---|---|---|---|
| Login без rate limit (перебор паролей) | High | API | Лимитера не было; bcrypt медленный, но перебор возможен | `RateLimitMiddleware`: 20/мин/IP на `/api/login` → 429 | `test_login_rate_limited` | Низкий: распределённый перебор с многих IP виден только в логах |
| Отсутствующие секреты молча заменялись insecure-значениями (эфемерный DEVICE_SECRET теряет пароли; дефолтный WEB_SECRET) | High | Deployment | Значения по умолчанию вместо fail-fast | `load_settings()` падает с понятной ошибкой; `DEV_MODE=1` только для dev | Ручной запуск без секретов → `FATAL` (проверено) | Нет, если оператор не включит DEV_MODE в проде (документировано) |
| Шим без лимитов на внешнем порту (память через гигантские фреймы, slow-loris, flood коннектов) | High | Shim | `readexactly(n)` без cap, чтений без таймаутов не было на всех путях, без rate limit | Cap 2MB, `READ_TIMEOUT` 60s на всех чтениях, max 200 коннектов, 30/мин/IP, bounded restarts | `test_shim.py` (cap rejection, gates) | Протокол без аутентификации по дизайну RustDesk — caps единственная защита |
| Heartbeat без аутентификации позволяет подделывать presence | Medium | API | Так спроектирован клиент (устройств без credentials) | Rate limit 300/мин/IP; влияние ограничено статусом (не данными) | Ручная проверка + задокументировано | Подмена last_seen возможна в пределах лимита |
| Относительный DATABASE_URL создавал stray-БД от CWD | Medium | Deployment | Путь зависел от cwd | `resolved_database_url`: дефолт и относительные пути якорятся на `data/` | `test_database_path_is_stable` | Нет |
| FK pragma не включалась (осиротевшие связи при удалениях) | Medium | DB | Нет listener'а | `PRAGMA foreign_keys=ON` + `busy_timeout` на каждое соединение (app и тесты) | `test_database_foreign_keys_enabled` | Нет |
| Тела без лимита (большие JSON) | Medium | API | Нет cap | `BodyCapMiddleware` 5MB → 413 (legacy push с 600+ устройств влезает) | `test_oversized_request_rejected` | Chunked без Content-Length сверх лимита не ловится (документировано) |
| `assert` в прод-коде (2 шт., bandit B101 Low) | Low | App/Shim | Отладочные проверки | Заменены явными ветвлениями | bandit повторно | Нет |
| try/except/pass при close (bandit B110 Low) | Informational | Shim | Штатное закрытие сокетов | Оставлено сознательно (best practice для cleanup) | — | Нет |
| `source-map-js` GHSA (npm, High) | Low | Frontend build | Транзитивная зависимость сборки | `npm audit fix` + пересборка dist | `npm audit` повторно | Только build-time, в рантайм не попадает |
| bcrypt вместо Argon2id | Informational | Auth | — | Оставлено: bcrypt корректен и достаточен, миграция обнулила бы хэши без выигрыша | Существующие auth-тесты | Нет |
| Legacy panel без per-form CSRF-токенов | Low | Panel | Исторический код | SameSite=Lax выставлен явно; SPA (основной UI) на Bearer без cookies | Ручная проверка редиректов без сессии | CSRF возможен только со same-site контекста |
| Customers глобальны для всех вошедших | Informational | API | Нет владельца у Customer | Задокументировано как ограничение MVP; чтение/запись требуют входа | — | Межпользовательская видимость клиентов |
| Зависимости Python | — | Deps | — | `pip-audit`: No known vulnerabilities found | CI-повтор | — |

Проверено и признано безопасным без изменений: IDOR на всех endpoint'ах
(`get_book_for_user` + `rule_for` + deny-тесты), mass-assignment (Pydantic/
явные `.get`, тест), SQLi (ORM + whitelist sort, тест), отсутствие секретов
в логах (кода логирования секретов нет; shim — только fingerprints),
отсутствие `shell=True`/подстановок в команды, Bearer вместо cookies для API
(CSRF N/A), Jinja-автоэскейп, React без `dangerouslySetInnerHTML`,
CORS отсутствует (same-origin SPA), `X-Forwarded-*` не читаются вообще.
