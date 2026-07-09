# vidapi/api — REST Endpoints

**Generated:** 2025-07-09
**Score:** 14 — distinct domain (API layer)

## OVERVIEW
FastAPI routers for all endpoints. Each domain has its own router module; assembled in `__init__.py` with `/api/v1` prefix.

## STRUCTURE
```
api/
├── __init__.py      # api_router assembly
├── routes.py        # Task CRUD (/tasks)
├── streaming.py     # SSE progress (/tasks/{id}/stream)
├── cookies.py       # BiliBili cookie management
├── system.py        # System info (/system/info)
└── config.py        # Config GET/PUT (/config)
```

## WHERE TO LOOK
| Task | Location |
|------|----------|
| Add task endpoint | `routes.py` |
| Add SSE event | `streaming.py` |
| Cookie upload/verify | `cookies.py` |
| System info | `system.py` |
| Config API | `config.py` |

## CONVENTIONS
- Router prefix: `/api/v1` (set in `__init__.py`)
- Tags per router: `["tasks"]`, `["streaming"]`, etc.
- Dependency injection: `Depends(get_task_manager)` from `main.py`
- Response models: `models.py` (TaskResponse, TaskListResponse, etc.)

## ANTI-PATTERNS
- Don't put business logic in routes — delegate to `TaskManager`
- Don't import `main` directly for DI — use `get_task_manager()` factory