# Qwen Omni Direct-Media Voice Calls Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add authenticated Russian Qwen WebRTC calls with optional user-enabled camera, safe Quip web tools, and a bounded Luna task that can run while Qwen keeps talking.

**Architecture:** Add a narrow authenticated voice API and call/tool ledger; the backend brokers only Qwen SDP and approved tools while audio/video stay direct. Reuse `Chat`/`Message`, `HistoryService`, the ordinary selected-model completion seam, and the one durable run/task substrate shared with Research; do not add a voice-specific task store or worker. Keep WebRTC, camera, ringback, and task display in isolated frontend modules.

**Tech Stack:** FastAPI, SQLAlchemy/Alembic, pytest/httpx async fixtures, Svelte 5/TypeScript, Vitest, browser WebRTC/DataChannel/MediaStream/Web Audio APIs.

**Spec:** `docs/superpowers/specs/2026-09-30-qwen-omni-direct-media-design.md`

## Global Constraints

- Direct browser↔Qwen WebRTC audio; the Qwen API key stays server-side; no WebSocket audio-proxy fallback.
- External voice web tools are only `web_search` and `read_url`; enforce existing `search_enabled`/skill gates, URL safety, ownership, and tool limits (one active web tool, 10 calls and five searches per call, 30-second timeout). Internal task delegation must call the shared run service, never spawn nested tasks.
- Carry no more than 6,000 estimated tokens per model request: 1,200 summary/task state, 3,200 recent turns, and 1,600 retrieved older turns/document snippets.
- Permit at most one active delegated task per voice call. A user clarification updates that task's revision and stable ID. Speech interruption cancels only Qwen's spoken response; task cancellation requires the explicit task-cancel action. Keep task updates/results structured and bounded; no free-form model-to-model loop.
- Luna is the requested OpenRouter text/agent preference; resolve its real ID from the runtime Quip model catalog, pass it through the existing selector/completion path, and never hard-code a guessed ID or change the production default. If no Luna catalog entry is available, report unavailable.
- Camera is optional and user-started from an explicit control; while off, send no video frames. Stop all audio/video tracks on end/error. Ringback is local, starts only during connection after user interaction, stops on answer/connected, cancel/end, timeout, or error, and never delays signaling/media.
- Keep full transcript in the same chat as attributed `Message` rows; do not store raw audio or mutate historical messages.
- Direct DataChannel transcript/usage events are client-reported; show usage as preliminary and browser stop as cooperative, never a hard server cost limit.
- Do not add OAuth, the future ChatGPT subscription provider, Telegram calls, screen capture, shell/apps, an always-on assistant, push notifications, live keys/calls, or deployment.

## Review Focus

- Forged or malformed SDP, provider events, tool names, and tool arguments must fail closed; test with invalid-signaling and unknown-tool fixtures in Tasks 1–2.
- Cross-user chat/call/history/document access must return not-found/denied without leaking existence; test ownership and retrieval isolation in Tasks 1 and 3.
- Duplicate/conflicting tool IDs, timeout, mute/end, and barge-in races must not replay side effects or resume a canceled response; test in Task 2 and mock interruption in Task 4.
- Missing provider config, upstream errors, denied microphone permission, and ICE/DataChannel failure must reach a visible recoverable error state; test in Tasks 1 and 4.
- Old-history retrieval, versioned summaries, same-task clarifications, stale result suppression, and Luna catalog resolution must remain source-attributed and under the token cap; test in Tasks 3–4.
- Camera denial/unavailability must leave audio calling usable; off/end/error must stop camera tracks, and ringback must clean up without entering RTP audio; test in Task 4.

---

### Task 1: Authenticated voice session and SDP broker

**Files:**
- Create: `backend/quip/models/voice.py` (`VoiceCall`, `VoiceToolCall`)
- Modify: `backend/quip/models/__init__.py`, `backend/quip/main.py`, `backend/quip/core/config.py` only if a setting helper is needed
- Create: `backend/quip/schemas/voice.py`, `backend/quip/routers/voice.py`, `backend/quip/services/voice/session.py`
- Create: `backend/quip/migrations/versions/0008_voice_calls.py` (down-revision `0007_telegram_update_queue`)
- Test: `backend/tests/test_voice_sessions.py`, `backend/tests/test_migrations.py`

**Interfaces:**
- `POST /api/voice/calls` takes `{chat_id, sdp, type}`; authenticated backend verifies `Chat.user_id`, stores a `VoiceCall`, sends the offer to the configured fixed Qwen realtime endpoint with the server-only key, and returns `{call_id, sdp, type}` without credentials.
- `POST /api/voice/calls/{call_id}/end` marks an owned call terminal. No server-side session kill or hard billing cap is promised.
- `VoiceCall` records owner, chat, configured provider/model, lifecycle timestamps/status, and client-reported usage metadata. `VoiceToolCall` has a unique `(voice_call_id, provider_call_id)` key, argument hash, status, and result metadata.

- [x] Add failing tests for unauthenticated requests, another user's chat/call, missing config, upstream SDP failure, and response/header/key secrecy; add migration round-trip/schema tests.
- [x] Run: `cd backend && pytest tests/test_voice_sessions.py tests/test_migrations.py -q` — expected failures before implementation.
- [x] Implement the two ledger models, migration, fixed-endpoint SDP broker, authenticated routes, visible sanitized errors, and sample-only Qwen config names; never accept a provider URL or credential from the browser.
- [x] Run the same pytest command — expected pass, including no credential string in JSON/errors.
- [x] Commit the session slice.

### Task 2: Transcript and idempotent Quip tool bridge

**Files:**
- Create: `backend/quip/services/voice/events.py`, `backend/quip/services/voice/tools.py`
- Modify: `backend/quip/routers/voice.py`, `backend/quip/services/scraper.py` (validate the original URL before the Jina reader request)
- Test: `backend/tests/test_voice_events.py`, `backend/tests/test_voice_tools.py`

**Interfaces:**
- `VoiceToolService.execute(db, user, call_id, provider_call_id, name, arguments)` accepts only `web_search` or `read_url`; it resolves `user/chat` from the persisted call, applies Quip's search gates and URL validation, records an idempotent result, and returns a bounded JSON result.
- `POST /api/voice/calls/{call_id}/tools` accepts `{provider_call_id, name, arguments}` and returns the recorded result for the browser to send back to Qwen as a function-call output.
- `POST /api/voice/calls/{call_id}/events` accepts only supported transcript/usage event shapes and persists user/assistant/tool transcript messages in that call's chat with `meta.source="qwen_realtime_client_event"`; it does not treat client usage as authoritative.
- Browser speech interruption aborts pending read-only tool work where possible; a result that wins the race may be saved, but must not restart a canceled Qwen response. It does not cancel delegated text work.

- [ ] Add failing fixture tests for supported transcript events, unknown/malformed events, unknown tool names, disabled search gate, unsafe original URL/redirects, same-ID replay vs. conflicting arguments, call limits/timeouts, and cancellation/result races.
- [ ] Run: `cd backend && pytest tests/test_voice_events.py tests/test_voice_tools.py -q` — expected failures before implementation.
- [ ] Implement strict event parsing, message attribution, the two-tool allowlist, existing `web_search`/`read_url` reuse, persistent ID/hash replay checks, and limits from the spec; do not call `ToolExecutor` or expose sandbox tools.
- [ ] Run the same pytest command — expected pass with mocked search/fetch only.
- [ ] Commit the event/tool slice.

### Task 3: Bounded shared context and shared-run delegation

**Files:**
- Create: `backend/quip/services/voice/context.py`
- Create: `backend/quip/services/voice/tasks.py` (adapter only; no task table/worker)
- Modify: `backend/quip/services/completion/history.py`, `backend/quip/services/completion/service.py`, `backend/quip/routers/voice.py`, `backend/quip/schemas/voice.py`
- Test: `backend/tests/test_voice_context.py`, `backend/tests/test_voice_tasks.py`, `backend/tests/test_history_truncation.py`

**Interfaces:**
- `HistoryService.build(..., limit: int = HISTORY_LIMIT)` keeps existing callers unchanged while voice supplies a bounded recent-turn limit.
- `VoiceContextService.build_task_context(db, user, chat, task_goal) -> VoiceContextPacket` loads only the owned chat, latest versioned summary/task state, bounded recent turns, and on-demand older message/document matches. The packet reports source IDs and estimated tokens and enforces the spec's 6,000-token allocation.
- `VoiceTaskAdapter` consumes the shared Research run contract: stable `task_id`, `owner_id`, `chat_id`, status, monotonic revision, context version, explicit cancel, and result-message ID. Its narrow methods are `create(user, chat, model_id, goal, packet, idempotency_key) -> RunSnapshot`, `update(user, task_id, expected_revision, user_message_ids, packet) -> RunSnapshot`, `get(user, task_id, after_revision) -> list[RunEvent]`, and `cancel(user, task_id) -> RunSnapshot`. Wire this adapter to the Research run/task substrate; do not add `VoiceTask` storage, a second worker, or a second status machine.
- Qwen's internal `delegate_to_text_model` function creates at most one active task per call. A user clarification updates that same task ID/revision. The shared runner uses the catalog-resolved OpenRouter Luna ID through `CompletionService.chat_completion`, with a server-side tool allowlist containing only `web_search` and `read_url`; limit its context to the same packet budget, disallow nested delegation, and return only bounded structured progress/final events. A late older-revision/canceled result is never relayed to Qwen.
- With no Qwen backend sideband, the authenticated browser reads shared task events/results and relays them over the active DataChannel. `response.cancel` affects speech only. The separate explicit task-cancel endpoint affects the run.
- The standard selected-model path is `selectedModel` → `streamChat` → `/api/chat/completions` → `CompletionService.chat_completion`; current backend dispatch supports OpenRouter/Ollama. Voice must call this common path and contain no provider-specific completion code. A future subscription provider remains a core model-catalog/dispatcher change.

**Integration gate:** The Research durable-run API/model is being designed separately and is not present in this checkout. Before Task 3 implementation, agree the adapter contract with that work and bind this adapter to its one run store/worker. This is the only blocker to implementing concurrent task execution; session/media/tool/UI work remains independently plan-able.

- [ ] Add failing tests for incremental versioned summary/source watermark, constraint/decision retention, bounded history, same-chat older-fact retrieval, cross-user/workspace isolation, and exact token-budget overflow behavior. With a fake adapter implementing the agreed shared-run contract, test one active task/call, same-ID revision updates, explicit cancel, stale-result suppression, source attribution, and speech interruption without task cancellation.
- [ ] Run: `cd backend && pytest tests/test_voice_context.py tests/test_voice_tasks.py tests/test_history_truncation.py -q` — expected failures before implementation.
- [ ] Implement the bounded packet, versioned `Chat.meta` context pointer, untrusted server-built context injection, and adapter to the agreed shared run store/worker; do not accept a browser-supplied summary/context packet or create a competing task engine.
- [ ] Run the same pytest command — expected pass, including unchanged existing history callers.
- [ ] Commit the context/task adapter slice.

### Task 4: In-chat WebRTC controls and truthful status notifications

**Files:**
- Create: `frontend/src/lib/api/voice.ts`, `frontend/src/lib/services/voice/session.ts`, `frontend/src/lib/components/chat/VoiceCallPanel.svelte`
- Modify: `frontend/src/lib/components/chat/ChatInput.svelte`, `frontend/src/lib/components/chat/ChatPane.svelte`, `frontend/src/lib/stores/chat.ts`, `frontend/src/lib/i18n/locales/en.json`, `frontend/src/lib/i18n/locales/ru.json`
- Test: `frontend/src/lib/services/voice/session.test.ts`, `frontend/src/lib/components/chat/VoiceCallPanel.test.ts`

**Interfaces:**
- `VoiceSession.start(chatId)`, `.setCamera(enabled)`, `.mute(muted)`, `.end()`, `.delegate(goal)`, `.updateTask(taskId, revision, userText)`, and `.cancelTask(taskId)` own local tracks, `RTCPeerConnection`, DataChannel events, task event relay, cancellation, and API calls; credentials never enter browser state.
- Show call/task states in the existing chat. Request microphone on call start and camera only on a separate explicit camera action; show local preview/on-off. Resolve Luna from `modelList` by its actual OpenRouter catalog ID and never mutate `adminDefaultModel`.
- Generated local ringback may play only once connection setup has been initiated by the user; stop on SDP answer/connected, cancel/end, timeout, error, and component teardown. It must not delay signaling, feed into RTP audio, or bypass browser interaction/autoplay rules.
- In-app feedback may reflect actual call/tool/shared-run state. Do not request OS/push permission, promise closed-tab delivery, or create incoming/outbound AI calls.

- [ ] Add failing Vitest cases with mocked `getUserMedia`, `RTCPeerConnection`, DataChannel, task API, model catalog, and Web Audio for mic/camera denial, camera-off/no-video-track, local preview, stop-all-tracks on end/error, connection recovery, transcript/task status, same-task clarification, speech interruption without task cancel, explicit task cancel, Luna ID pass-through/unavailable state, and ringback cleanup for answer/connected/cancel/end/timeout/error/teardown. Assert tone is local-only and does not delay signaling.
- [ ] Run: `cd frontend && npm test -- --run src/lib/services/voice/session.test.ts src/lib/components/chat/VoiceCallPanel.test.ts` — expected failures before implementation.
- [ ] Implement the isolated audio/video controller and panel plus minimal `ChatInput`/`ChatPane` integration; verify the exact Qwen video track/session semantics against the official WebRTC Omni guide during implementation. Map errors and shared-run outcomes to translated in-app states.
- [ ] Run the targeted Vitest command, then `cd frontend && npm run check` — expected pass with no permission prompt before the corresponding user action, no camera frames while off, and no ringback after terminal connection states.
- [ ] Commit the UI slice.
