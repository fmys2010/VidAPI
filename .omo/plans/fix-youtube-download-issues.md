# Work Plan: Fix YouTube Download Issues

**Generated:** 2025-07-10
**Branch:** main
**Commit:** HEAD

## Executive Summary

Fix 5 critical YouTube download issues observed in production logs:
1. **Missing JS Runtime** → yt-dlp falls back to low quality (360p/480p/720p)
2. **403 Forbidden Errors** → Multiple videos fail due to YouTube bot detection
3. **Network Stalls** → Large files (1GB+) experience connection drops with no recovery
4. **Duplicate URLs** → Wasted bandwidth on repeated downloads
5. **No Retry/Recovery** → Failed downloads fail permanently with no fallback

---

## Root Cause Analysis

| Issue | Root Cause | Location |
|-------|------------|----------|
| JS Runtime | yt-dlp needs Node.js/Deno for YouTube signature decryption; no `extractor_args` or runtime config | `workers.py:239` `ydl_opts` |
| 403 Forbidden | YouTube bot detection blocks datacenter IPs; no YouTube-specific headers/cookies | `workers.py:268` (only BiliBili handled) |
| Network Stalls | `retries: 10` but aggressive `socket_timeout: 30`, `timeout: 30`; no partial file resumption | `workers.py:252-254` |
| Duplicate URLs | API accepts raw URL list; no deduplication at task creation | `task_manager.py:90` |
| No Retry | `session.run()` called once; no task-level retry with backoff | `task_manager.py:321` |

---

## Implementation Plan

### Wave 1: Foundation (Parallel - 3 agents)

#### Task 1.1: Add JS Runtime Support to yt-dlp Options
**File:** `vidapi/core/workers.py` (lines 239-257)
**Changes:**
- Add `extractor_args: {"youtube": {"player_client": ["android", "web"]}}` to bypass signature decryption
- Or detect system Node.js/Deno and add `--js-runtime` via `extractor_args`
- Add config option `js_runtime` to Config class

**Test:** `test_youtube_js_runtime_configured` - verify ydl_opts contains extractor_args for youtube

#### Task 1.2: Add YouTube-Specific HTTP Headers
**File:** `vidapi/core/workers.py` (lines 268-273)
**Changes:**
- Add YouTube branch alongside BiliBili handling
- Set realistic User-Agent, Accept-Language, Origin headers
- Add `http_headers` for YouTube to mimic browser

**Test:** `test_youtube_headers_configured` - verify ydl_opts has http_headers for youtube

#### Task 1.3: Add URL Deduplication at Task Creation
**File:** `vidapi/task_manager.py` (lines 90-129)
**Changes:**
- In `create_task()`, deduplicate URLs using ordered dict/set before saving
- Log warning if duplicates removed

**Test:** `test_create_task_deduplicates_urls` - verify duplicate URLs reduced to single entry

---

### Wave 2: Resilience (Parallel - 3 agents)

#### Task 2.1: Implement Format Fallback Chain
**File:** `vidapi/core/format_utils.py` (lines 38-67)
**Changes:**
- Modify `build_format_selector()` to return list of format selectors (primary + fallbacks)
- Fallback chain: requested quality → 1080p → 720p → 480p → best available
- Add `get_format_fallbacks(download_mode, quality)` helper

**Test:** `test_format_fallback_chain` - verify fallback list generated correctly

#### Task 2.2: Add Download Retry Logic with Backoff
**File:** `vidapi/core/workers.py` (lines 162-298, inside URL loop)
**Changes:**
- Wrap single URL download in retry loop (max 3 attempts)
- Exponential backoff: 5s, 15s, 45s
- On format failure, try next fallback format selector
- Log each retry attempt with reason

**Test:** `test_download_retry_on_failure` - verify retry behavior with mocked failures

#### Task 2.3: Improve Network Timeout/Resumption Settings
**File:** `vidapi/core/workers.py` (lines 252-256)
**Changes:**
- Increase `socket_timeout` to 60s, `timeout` to 60s
- Add `retries` for fragment downloads: `"fragment_retries": 10`
- Add `"hls_use_mpegts": True` for better HLS handling
- Keep `concurrent_fragment_downloads: 4` but add `"throttled_rate": "1M"` for large files

**Test:** `test_network_timeouts_configured` - verify ydl_opts has improved timeouts

---

### Wave 3: Task-Level Retry & Recovery (Sequential - 2 agents)

#### Task 3.1: Add Task-Level Retry in TaskManager
**File:** `vidapi/task_manager.py` (lines 271-329)
**Changes:**
- Add `max_task_retries` config option (default: 2)
- In `run_download()`, wrap `session.run()` in retry loop
- On failure, re-create session with next fallback format
- Only retry on transient errors (network, 403, 5xx), not on invalid URL

**Test:** `test_task_retry_on_transient_failure` - verify task retries with different format

#### Task 3.2: Add Partial File Cleanup & Resumption
**File:** `vidapi/core/workers.py` (lines 300-308)
**Changes:**
- Before download, check for existing `.part` files
- Use `continuedl: True` (already set) but verify it works
- Add `keep_fragments: True` for debugging failed merges
- Log resumption attempts

**Test:** `test_download_resumption` - verify partial files are reused

---

### Wave 4: Configuration & Polish (Parallel - 2 agents)

#### Task 4.1: Add New Config Options
**File:** `vidapi/core/config.py` (lines 18-131)
**New Options:**
```python
js_runtime: str = "auto"          # "auto", "nodejs", "deno", "none"
youtube_headers: bool = True       # Enable browser-like headers
format_fallback: bool = True       # Enable format fallback chain
max_retries: int = 3               # Per-URL retry attempts
task_max_retries: int = 2          # Task-level retries
retry_backoff_base: int = 5        # Base seconds for exponential backoff
fragment_retries: int = 10         # Fragment-level retries
socket_timeout: int = 60           # Socket timeout seconds
```

**Test:** `test_new_config_options` - verify all options load/save correctly

#### Task 4.2: Add Comprehensive Logging & Metrics
**File:** `vidapi/core/workers.py` (throughout)
**Changes:**
- Log format selector being used (primary/fallback)
- Log retry attempts with backoff duration
- Log network metrics (speed, timeouts, retries)
- Add structured error codes for programmatic handling

**Test:** `test_structured_logging` - verify log output contains expected fields

---

## Test Scenarios (TDD Contract)

### Scenario 1: JS Runtime Enables 1080p+
- **Given:** YouTube URL with 1080p available
- **When:** Download with `js_runtime: "auto"`
- **Then:** Format selector includes 1080p, actual height ≥ 1080
- **Surface:** `curl POST /api/v1/tasks` → SSE progress → verify 1080p in log

### Scenario 2: 403 Triggers Retry with Headers
- **Given:** YouTube URL that returns 403 on first attempt
- **When:** Download with `youtube_headers: true`
- **Then:** Retry with browser headers succeeds or fails gracefully
- **Surface:** Mock HTTP 403 → verify retry with headers → 200 or final error

### Scenario 3: Format Fallback on Quality Unavailable
- **Given:** YouTube video only available up to 720p
- **When:** Request 1080p with `format_fallback: true`
- **Then:** Falls back to 720p, logs fallback notice
- **Surface:** SSE log shows "提示: 实际只拿到 720p" → verify fallback chain

### Scenario 4: Network Stall Recovers
- **Given:** Large file download stalls mid-way
- **When:** Connection drops and recovers within timeout
- **Then:** Download resumes from partial file (continuedl)
- **Surface:** Verify `.part` file exists → download completes → no duplicate data

### Scenario 5: Duplicate URLs Deduplicated
- **Given:** Request with `["url1", "url1", "url2"]`
- **When:** Task created
- **Then:** Only 2 URLs processed, log warning for duplicate
- **Surface:** Task list shows 2 URLs, log contains "Removed 1 duplicate URL"

### Scenario 6: Task Retry on Transient Failure
- **Given:** Task fails with network error
- **When:** `task_max_retries: 2`
- **Then:** Task retries up to 2 times with backoff, then final state
- **Surface:** SSE shows retry attempts → final state completed/failed

---

## Parallel Execution Graph

```
Wave 1 (Parallel)
├─ Task 1.1: JS Runtime          → workers.py
├─ Task 1.2: YouTube Headers     → workers.py
└─ Task 1.3: URL Dedup           → task_manager.py

Wave 2 (Parallel)
├─ Task 2.1: Format Fallback     → format_utils.py
├─ Task 2.2: Download Retry      → workers.py
└─ Task 2.3: Network Timeouts    → workers.py

Wave 3 (Sequential)
├─ Task 3.1: Task Retry          → task_manager.py
└─ Task 3.2: Resumption          → workers.py

Wave 4 (Parallel)
├─ Task 4.1: Config Options      → config.py
└─ Task 4.2: Logging/Metrics     → workers.py
```

---

## Verification Checklist

### Automated Tests (Must Pass)
- [ ] All existing 365 tests still pass
- [ ] New unit tests for each task (12+ tests)
- [ ] Integration test: full download flow with mocked yt-dlp
- [ ] Format fallback chain test
- [ ] Retry logic test with mocked failures
- [ ] URL deduplication test

### Manual QA (Must Execute)
- [ ] **JS Runtime:** Download known 1080p+ video → verify 1080p in output
- [ ] **403 Recovery:** Test problematic URL → verify retry with headers
- [ ] **Format Fallback:** Request 4K on 1080p-only video → verify 1080p fallback
- [ ] **Network Stall:** Simulate slow connection → verify resumption
- [ ] **Dedup:** Submit duplicate URLs → verify single download
- [ ] **Task Retry:** Kill network mid-download → verify retry completes

### Regression Tests
- [ ] BiliBili downloads still work (cookies, formats)
- [ ] Audio-only mode unaffected
- [ ] Video-only mode unaffected
- [ ] Cancel mid-download works
- [ ] SSE progress streaming unchanged
- [ ] Config persistence works

---

## Risk Mitigation

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| JS runtime detection fails on some systems | Medium | High | Fallback to `"android"` player_client (no JS needed) |
| YouTube headers trigger more 403s | Low | Medium | Configurable via `youtube_headers` option |
| Format fallback picks wrong quality | Low | Medium | Strict height ordering in fallback chain |
| Retry loop causes infinite hangs | Low | High | Max retries + total timeout guard |
| Config changes break existing deployments | Low | High | All new options default to safe behavior |

---

## File Modification Summary

| File | Changes | Lines |
|------|---------|-------|
| `vidapi/core/workers.py` | JS runtime, headers, retry loop, timeouts, logging | ~80 lines |
| `vidapi/core/format_utils.py` | Fallback chain helper | ~30 lines |
| `vidapi/task_manager.py` | URL dedup, task retry logic | ~50 lines |
| `vidapi/core/config.py` | 8 new config options | ~40 lines |
| `vidapi/core/url_utils.py` | (Optional) URL normalization | ~10 lines |

**Total: ~210 lines across 5 files**

---

## Acceptance Criteria

**Definition of Done:**
1. All 12+ new tests pass (RED→GREEN→SURFACE)
2. All 365 existing tests pass
3. Manual QA scenarios 1-6 verified with artifacts
4. No regression in BiliBili/audio/video-only modes
5. Plan file updated with completion status
6. Momus review passes (if invoked)