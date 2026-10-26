---
name: sqlite-changes
description: >
  Use when changing the database schema or persistent data in this project:
  adding/altering tables or columns, writing an Alembic migration, handling
  `data/base.db` vs `data/pc-service.db`, backup/restore, or investigating a
  migration/revision error. Enforces the safe order (backup, migration on a
  copy, integrity check, git) required by AGENTS.md and DATA_MODEL.md.
---

# SQLite changes

Схема меняется только через Alembic. «Удалить базу и накатить заново» —
запрещённое решение. Полные правила — `docs/project/DATA_MODEL.md`.

## 1. Перед правкой

1. Прочитай `AGENTS.md` §5 и `docs/project/DATA_MODEL.md` целиком.
2. Определи текущий head:
   `.venv/bin/alembic -c alembic.ini heads`
3. Сделай backup:
   `.venv/bin/python -m app.cli backup`
4. Убедись, какая БД используется: `DATABASE_URL` в `.env` (по умолчанию
   `data/base.db`). Не переключай его на рабочем инстансе.
5. Помни: `data/base.db` и `data/pc-service.db` — разные исторические
   данные. Не сливай и не удаляй «лишнюю».

## 2. Миграция

Файл: `alembic/versions/NNNN_<name>.py`.

- `revision` — следующий номер, `down_revision` — текущий head;
- обязательны `upgrade()` и `downgrade()`;
- для SQLite-изменений колонок/ограничений — `op.batch_alter_table`;
- никаких импортов приложения и обращений к реальным данным;
- аддитивные изменения безопаснее; удаление/переименование — только с
  планом совместимости.

## 3. Проверка на копии (обязательно)

```bash
cp data/base.db /tmp/opencode/rd-test/copy.db
DATABASE_URL=sqlite:////tmp/opencode/rd-test/copy.db DEV_MODE=1 \
  .venv/bin/alembic -c alembic.ini upgrade head
DATABASE_URL=sqlite:////tmp/opencode/rd-test/copy.db DEV_MODE=1 \
  .venv/bin/python - <<'PY'
import sqlite3
c = sqlite3.connect('/tmp/opencode/rd-test/copy.db')
print(c.execute('PRAGMA integrity_check').fetchone()[0])
print(c.execute('SELECT version_num FROM alembic_version').fetchone())
PY
```

Затем downgrade на предыдущую ревизию и снова upgrade. Проверяй на копии
реальной БД, а не только на пустой.

## 4. После правки

- `git status` должен содержать файл миграции. Незакоммиченная миграция не
  попадёт в Docker/клон — это уже приводило к
  `Can't locate revision identified by '0003'`.
- Обнови `docs/project/DATA_MODEL.md` (и `API_REFERENCE.md`, если меняется
  контракт).
- Не меняй `alembic_version` вручную. Если ревизия «потерялась» —
  восстанови файл из git.
- Не коммить `data/`, `logs/`, `.env`, backup-файлы.

## 5. Красные флаги

- `create_all()` вместо миграции;
- `DROP`/`ALTER` вручную;
- `NOT NULL` без `server_default` на существующей таблице без batch;
- проверка только на пустой БД;
- «быстрый откат» прода через downgrade без понимания данных.
