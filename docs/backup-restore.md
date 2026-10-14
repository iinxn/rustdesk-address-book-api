# Backup & restore

## Автобэкап

```bash
cd /home/user/Documents/rustdesk-manager
.venv/bin/python -m app.cli backup            # -> data/backup-YYYYMMDD-HHMMSS.db
.venv/bin/python -m app.cli backup --dest /mnt/safe/manual.db
```

Использует SQLite Backup API (консистентен при живой записи, в отличие от
`cp` открытого файла), затем `PRAGMA integrity_check` копии и права `0600`.
Можно вызывать по cron на работающем приложении (останавливать не нужно).

## Восстановление

```bash
./scripts/stop.sh                       # остановить приложение
cp data/base.db data/base.db.before-restore
cp /mnt/safe/manual.db data/base.db
chmod 600 data/base.db
.venv/bin/python -m app                 # миграции применятся сами (upgrade head)
./scripts/start.sh
```

Проверить: login, адресная книга (сверить counts), `/health/ready` → `ready`.

## Нерегулярные копии

- Перед миграциями/обновлениями: `cp data/base.db ~/Documents/backups/...`.
- Исходный `dev.db` старого проекта не трогается и остаётся как есть.
- `-wal`/`-shm` рядом с базой — служебные файлы SQLite (журнал), не базы;
  бэкап через Backup API их консолидирует корректно.

## Что НЕ бэкапится автоматически

- `shim-hbbs.key` / `id_ed25519` (ключи hbbs — хранить отдельно, шифрованно).
- `.env` (секреты — отдельно).
- `logs/` (пересоздаются).
