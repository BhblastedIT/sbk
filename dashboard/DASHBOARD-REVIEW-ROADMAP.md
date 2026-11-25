# Dashboard Review — Fix & Test Roadmap

> Tracks all critical fixes and tests that emerged from the code review.

## Phase 1 — Critical Fixes (security + stability)

- [x] C1: Path traversal protection — `pipeline_runner.py`
- [x] C2: Zombie process fix — `pipeline_runner.py`
- [x] C3: SQL keyword bypass hardening — `sql.py`
- [x] C4: Race condition asyncio.Lock — `chat.py`
- [x] C5: SQLite thread safety — `approval_store.py`
- [x] C6: SQLite thread safety — `task_store.py`
- [x] C7: ConversationStore lock + atomic write + ID validation — `conversation_store.py`
- [x] C8: cached_property race condition — `sbk_bridge.py`
- [x] C9: XSS search results — **Already safe** (Jinja2 autoescape active for `.html`)

## Phase 2 — Test Suite (uncovered areas)

- [x] T1: `tests/test_pipeline_runner.py` (10 tests — 10/10 passed)
- [x] T2: `tests/test_scheduler.py` (8 tests — 8/8 passed)
- [x] T3: `tests/test_chat_websocket.py` (10 tests — 9 passed, 1 skipped)
- [x] T4: `tests/test_chat_tools.py` (10 tests — 10/10 passed)
- [x] T5: `tests/test_data_stores.py` (12 tests — 12/12 passed)

## To do later (Phase 3 — cleanup and UX)

- Rate limiting on API endpoints
- More granular input validation on REST parameters
- Uniform log cleanup and error handling
- CSRF protection if the dashboard is exposed
