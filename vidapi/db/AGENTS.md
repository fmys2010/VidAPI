# vidapi/db — Persistence Layer

**Generated:** 2025-07-09
**Score:** 10 — distinct domain (SQLite + aiosqlite)

## OVERVIEW
Async SQLite database for task persistence. WAL mode for concurrent reads/writes. Schema defined in `schema.sql`, applied via `migrate.py`.

## STRUCTURE
```
db/
├── database.py      # Database class (connection, CRUD, indexes)
├── migrate.py       # Schema initialization + migration runner
├── schema.sql       # Tasks + config tables (SQL DDL)
└── __init__.py      # Re-exports Database
```

## WHERE TO LOOK
| Task | Location |
|------|----------|
| Task CRUD | `database.py` (save_task, get_task, list_tasks, delete_task) |
| State recovery | `database.py` (reset_downloading_tasks) |
| Config persistence | `database.py` (get_config, set_config) |
| Schema changes | `schema.sql` + `migrate.py` |

## CONVENTIONS
- `aiosqlite` with `row_factory = aiosqlite.Row` for dict-like rows
- WAL mode: `PRAGMA journal_mode=WAL` + `PRAGMA foreign_keys=ON`
- Indexes on `state` and `created_at` for common queries
- JSON storage for `urls` array in tasks table
- Timestamps in UTC, auto-updated on write

## ANTI-PATTERNS
- Don't use sync `sqlite3` — breaks async event loop
- Don't skip WAL mode — needed for concurrent task_manager access
- Don't store parsed cookies — only raw `Cookie:` header string