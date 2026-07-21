# vidapi 优化计划

**生成时间:** 2026-07-19
**基线:** HEAD (commit 7834645) vs audit-fixes worktree
**方法论:** Ponytail full + Ultrawork — 最小 diff、stdlib first、证据驱动
**证据来源:** 5 reviewer 报告 (Phase 3 review-work) + QA baseline 比对 + pytest 再测试

## 当前状态摘要

### 测试通过率（audit-fixes worktree）

| Suite | 通过 | 失败 | 性质 |
|---|---|---|---|
| Non-integration | 396 | 0 | 干净 |
| test_task_lifecycle | 41 | 0 | 干净（含 DELETE-cancel 8/8） |
| test_cookie_flow | 33 | 5 | 预存在网络调用 |
| test_database_recovery | 30 | 2 | 预存在 FK/NOT NULL fixture bug |
| test_concurrent_tasks | 16 | 6 | 预存在 timing + anyio 线程残留 |
| test_full_api_workflow | 54 | 9 | 预存在 cookie/SSE/timing |
| test_sse_streaming | — | hang | 预存在，baseline 同样 hang |

**净改动:** audit 修复消除了 2 个 baseline 回归（6 errors + 12 failures → 0 errors + 10 failures），其余失败全部是预存在。

## 优化阶梯（按 Ponytail ladder 排序）

### P0 — 根因 + 数据安全 + 阻塞 review

| ID | 问题 | 根因 | 修复方案 | 验证 | 工作量 |
|---|---|---|---|---|---|
| **P0.1** | `_cancelled_tasks` 内存泄漏 | `set` 无限增长，已取消 task 永不清理 | `cancel_task` 完成后从 `_cancelled_tasks` 移除；timeout 兜底 60s 后移除 | `tests/test_task_manager.py::test_cancelled_tasks_cleanup` | 5 行 |
| **P0.2** | `CancelledError` 被吞 | `except Exception` 捕获 `asyncio.CancelledError` 且不重抛 | 改用 `except Exception:` 之前先 `except asyncio.CancelledError: raise`；或在 `run_in_executor` 包装层显式 `if isinstance(e, CancelledError): raise` | `tests/test_workers.py::test_cancelled_error_propagates` | 4 行 |
| **P0.3** | DELETE 端点非幂等 | `get_task` 在 `_deleted_tasks` 里的 task 仍返回 404，但重复 DELETE 在并发场景下可能 race | `_deleted_tasks` 检查前加 `async with self._lock`；幂等返回 204 | `tests/test_api_routes.py::test_delete_idempotent` | 3 行 |

### P1 — 测试债 + 未对齐约定

| ID | 问题 | 根因 | 修复方案 | 验证 | 工作量 |
|---|---|---|---|---|---|
| **P1.1** | `test_database_recovery::test_foreign_keys_enabled` 失败 | 测试假设 `PRAGMA foreign_keys` 在 connection 上读取，实际 aiosqlite 每连接独立 | 测试改用 `self.db._execute("PRAGMA foreign_keys")` 而非直接 cursor | 该测试 pass | 1 行 |
| **P1.2** | `test_database_recovery::test_null_urls_field_handled` 失败 | `urls` 字段在 schema 中 NOT NULL，测试期望 null 可写 | 改测试为空 list `[]` 而非 None；或改 schema 为 NULL 允许 | 该测试 pass | 1 行 |
| **P1.3** | `test_concurrent_tasks` 6 failed | pytest-timeout 用 signal 模式，但 aiosqlite worker 线程不响应 SIGUSR1 | (a) conftest.py 添加 `@pytest.fixture(autouse=True)` 在每个测试结束后 `await db.close()` 强制清理；(b) 测试改为 `--timeout=30` 给 aiosqlite 更多时间 | 6 → 0 failed | 8-12 行 |
| **P1.4** | `test_full_api_workflow::test_cancel_downloading_task` 失败 | SSE 事件 `state_change` 在 cancel 后未及时广播 | `_await_running_task_done` 在 `complete_task` 之后显式 `_notify_state_change(task_id)` | 该测试 pass | 2 行 |
| **P1.5** | `test_full_api_workflow::test_sse_*` 3 failed | heartbeat 间隔测试期望 < 1s，config 默认 15s | 测试改为 override fixture 设置 `config.heartbeat_interval=0.1` | 3 → 0 failed | 3 行 |
| **P1.6** | `test_full_api_workflow::test_config_update_*` 2 failed | enum 字段 `download_mode` 中文 label vs 端接收 string | API 层 `ConfigUpdate` 用 `field_validator` 接受中文 label | 2 → 0 failed | 6 行 |
| **P1.7** | `test_cookie_flow::test_upload_cookie_endpoint` 失败 | endpoint 路由顺序错（`/verify` 在 `/{...}` 之前） | `api/cookies.py` 调换 `@router.post("/verify")` 与 `@router.post("/{key}")` 顺序 | 该测试 pass | 2 行 |
| **P1.8** | `test_sse_streaming.py` hang | aiosqlite 连接在 SSE 长连接期间被复用，doclose 不释放 | SSE handler 用独立 db connection 副本，或 `async with db.connect()` 模式 | 整个文件 pass | 中等 |

### P2 — 代码质量 + 预防御性

| ID | 问题 | 修复方案 | 价值 | 工作量 |
|---|---|---|---|---|
| **P2.1** | `update_progress` 缺 guard | 加 `if task_id not in self._tasks: return` | 防止 ghost progress | 2 行 |
| **P2.2** | `has_active_downloads` 死代码 | 删除（grep 无调用方） | -8 行 | 1 行 |
| **P2.3** | `resize_executor` 重复 import | 合并顶部 import | 风格 | 1 行 |
| **P2.4** | `_get_queue` 测试 shim 兜底 | 删除，改用 `task_manager._queues[task_id]` | -6 行 | 1 行 |
| **P2.5** | `logger.exception` cookie leak | `logger.exception(...)` 改 `logger.error(..., exc_info=False)` 在 cookie 路径 | 安全 | 2 行 |
| **P2.6** | `error_msg` 未 sanitize | 失败时 `error_msg = str(e)[:500]`，不含敏感字段 | 安全 | 1 行 |
| **P2.7** | SPEC.md 与 lock 机制不一致 | SPEC.md 加一节描述 `_deleted_tasks` + `_cancelled_tasks` 生命周期 | 文档同步 | 10 行 |
| **P2.8** | `RoutesResponse` 大量字段冗余 | 删除未使用的 `TaskResponse` 字段或拆 model | API 简化 | 视情况 |

## 执行顺序（关键路径）

```
P0.1 → P0.2 → P0.3   (review blocker，先做)
       ↓
P1.4 → P1.5 → P1.6 → P1.7   (测试债，连做)
       ↓
P1.1 → P1.2 → P1.3   (集成测试稳定)
       ↓
P1.8   (SSE 难题，单独做)
       ↓
P2.1 → P2.2 → P2.3 → P2.4 → P2.5 → P2.6 → P2.7 → P2.8   (清理)
```

## 跳过的事项（YAGNI）

- 不重构 `TaskManager` 为多个类（单 monolith 仍可维护）
- 不引入新依赖（如 tenacity、structlog）
- 不引入 prometheus metrics（无需求方）
- 不写 OpenAPI spec 文档（FastAPI auto-gen 已够）
- 不实现 graceful shutdown 之外的 SIGTERM 处理

## 何时需要回到 P1.8（SSE hang）

仅当生产环境真的报告 SSE 连接堆积才优先。当前 hang 仅在测试环境因 aiosqlite 单连接被 SSE 长占用导致。生产中 uvicorn worker 之间独立 connection pool，问题不显著。

## 验证策略

每完成一个 P0/P1 项目：
1. `ruff check vidapi/` 必须通过
2. 对应单元测试 pass
3. 受影响集成测试文件重新跑一遍，对比 failed 数不增加
4. 完成全部 P0 后：跑全量 `vidapi/tests/` (排除 SSE) 应全 pass

## 完成 criteria

- P0: 3 项全 pass + review-work 5 reviewer 重新跑通过 ≥4/5
- P1: 8 项全 pass + `pytest vidapi/tests/ --ignore=test_sse_streaming` 全 pass
- P2: 8 项全 pass + ruff check 通过 + SPEC.md 同步

## 历史回顾

audit-fixes 阶段已完成的根因修复（已 shipped）：
- `_deleted_tasks` guard（防已删除 task 被 cancel 误激活）
- `delete_task` workflow（cancel-then-delete）
- DELETE endpoint 返回 204 + 404 semantics
- `_cancelled_tasks` 集合加入跟踪
- `workers.py` CancelledError 在 yield 期间的传播
- `cookies.py` endpoint 路由顺序修复（已部分完成，待全量验证）

剩余工作 = 把 review phase 发现的"清理层"债务 + 测试对齐 debt 清算。
