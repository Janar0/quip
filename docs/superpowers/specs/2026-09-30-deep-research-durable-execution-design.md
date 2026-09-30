# Deep Research durable execution

**Status:** approved first-release design; implemented on branch `codex/deep-research-coordinator-20260930`. Deployment enablement still requires verifying a single effective worker.

## Goal and current boundary

Explicit Research mode must continue after navigation/reload, save progress and the report (including partial results/errors), and support Stop. It is separate from fast Search and respects the existing admin gate. Add no broker or table in the first release.

`CompletionService` already persists `ChatRun` plus its assistant `Message` before SSE, and `ChatRun.run_metadata` is JSON. But the response omits that metadata, a disconnect marks the run cancelled, and `run_deep_research()` keeps its session, queue, and child tasks in memory. `main.py` has no durable runner or restart recovery.

## Minimum page-resilient design

1. **Detach execution from SSE.** Add `mode_hint="research"` and reject it when `research_enabled` is false. After committing the existing user/assistant/`ChatRun` records, dispatch to a small `ResearchRunManager` in `app.state`, started/stopped by `main.py` lifespan. It captures IDs and immutable context, uses fresh `async_session` sessions, and runs independently. POST SSE relays manager events; a disconnect only detaches that listener for research.

2. **Persist a snapshot, not an event log.** Reuse `ChatRun.run_metadata` for a versioned, bounded `{seq, progress, subagents, errors, sources, usage, cancel_requested}` snapshot. Sources come only from validated search-tool results. Keep partial/final report text on the linked `Message`; add a draft-save helper that does not add `UsageLog` rows, flushing on phase/agent changes and coalescing text writes (e.g. 1s/1 KiB). Call `save_assistant_message()` once at terminal state for final content, citations, and aggregate usage.

3. **Reconnect and stop.** Add authenticated `GET /api/chats/{chat_id}/runs/{run_id}` for the sanitized snapshot and linked partial/final message. `GET /api/chats/{chat_id}` already returns recent run IDs; after reload the client restores progress and polls the run endpoint. Add `POST /api/chats/{chat_id}/runs/{run_id}/cancel`, owner-check both IDs, and make it idempotent. UI progress/terminal state comes from the run, not page-local `isStreaming`; event replay is unnecessary for this release.

## Lifecycle and cancellation contract

`queued → running → completed | partial | failed | cancelled | interrupted` (`cancel_requested` is a flag during cleanup). `partial` means useful text plus source/agent errors; `failed` means no useful report; `cancelled` preserves any partial report. Every terminal state keeps the snapshot and sets `finished_at`; conditional updates make terminal states immutable.

Pass a manager-owned cancellation event into `run_deep_research()`. Stop new calls/spawns, close cancellable streams, await children, persist partial text, then mark cancelled. An in-flight external call may already have incurred cost/effects; never replay it. On startup, mark persisted nonterminal runs `interrupted`, preserve partial text, and do not retry because prior charges/effects are uncertain.

This supports page reload while the process lives, not restart-resume. The manager is process-local, so v1 assumes one ASGI worker (or chat-sticky routing); multiple workers need DB leases/polling or a broker. True resume also requires checkpointed, idempotent steps.

## Files and limits

Backend seams: `schemas/chat.py`; `services/completion/service.py`; new `services/research/run_manager.py`; `services/research/{orchestrator,types,dispatcher}.py`; `routers/chats.py`; `services/messages_persist.py`; `main.py`. Frontend seams: `lib/api/{chats,chat-stream}.ts`, `lib/stores/chat.ts`, `DeepResearchProgress.svelte`. Keep provider/search implementation in the search worker's files.

Existing limits: 20 coordinator rounds, 15 sub-agent rounds, 100 session searches, and the user-wide preflight `_check_budget()`. The implementation adds configurable defaults of 8 children total, 3 concurrent, 10 minutes, and a $1 cumulative known-cost stop threshold (one in-flight call may cross it). It aggregates usage incrementally and starts no new calls after a limit; local/unknown-cost providers remain bounded by steps/time.

## Mocked acceptance tests

Use ASGI, temporary SQLite, a fake manager/coordinator, and fake provider/search results. Verify: mode/gate and single run creation; disconnect/reload restores progress, partial content, sources, and final report; Stop auth/idempotency and no later spawns; visible partial failure; terminal-write races; startup interruption without replay; and every budget halts further fake calls. Empty/error-only results must create no source footer. No paid providers, live databases, or web calls.
