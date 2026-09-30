# Quip voice calls and text-model handoff

**Status:** revised design proposal for written review
**Branch:** `codex/qwen-omni-voice-20260930`
**Scope:** a user-started call in an existing Quip chat, Quip-mediated web tools, and an explicit handoff through Quip's provider-agnostic text model/completion seam

## Goal

Let a signed-in user speak Russian with Qwen Omni Realtime in Quip, interrupt/mute/end the call, search the web or read a page through Quip, and hand work to a user-selected existing text model in the same chat. Preserve complete text/tool history in Quip. Both modalities use server-owned, bounded context so they share task state without resending the entire transcript.

## Verified protocol facts

- Alibaba documents browser WebRTC: SDP offer/answer setup, direct RTP audio, and model events/text on a DataChannel. It supports server VAD, and documents `response.cancel` for stopping an active response. [Realtime API](https://www.alibabacloud.com/help/en/model-studio/realtime), [client events](https://www.alibabacloud.com/help/en/model-studio/client-events)
- WebRTC SDP signaling uses `Authorization: Bearer <API_KEY>`; Quip can make that request on the backend and keep the key out of the browser. The temporary token described by Alibaba is for AOQ, not WebRTC. [Token authentication](https://www.alibabacloud.com/help/en/model-studio/realtime-token-authentication)
- Qwen function-call arguments, transcript events, and `response.done` usage are sent to the browser over the event DataChannel. Alibaba's custom-function flow has the client run the function and send `function_call_output`. The reviewed docs show no provider sideband for backend event observation or remote session termination. Browser-relayed calls/usage must therefore be treated as untrusted. [Server events](https://www.alibabacloud.com/help/en/model-studio/server-events)
- Input transcription names `qwen3-asr-flash-realtime`; pricing lists that realtime ASR model separately, but the reviewed docs do not clarify whether it is billed separately inside an Omni session. Treat it as potentially additional metered use and disclose that uncertainty before enabling paid calls. Provider billing reports are delayed and are not a per-call real-time stop mechanism. [Pricing](https://www.alibabacloud.com/help/en/model-studio/model-pricing), [billing](https://www.alibabacloud.com/help/en/model-studio/bill-query-and-cost-management)

## Call flow and user experience

1. The user clicks **Start voice call** in the existing chat. Only then does the page request microphone access and create an `RTCPeerConnection`, local audio track, and Qwen event DataChannel.
2. The page POSTs the chat ID and SDP offer to an authenticated Quip endpoint. Quip verifies the active user owns the chat, checks voice/model settings and preflight policy, creates a durable call record, and POSTs the offer to the configured Qwen endpoint with the server-only key. It returns the answer SDP, call ID, and a server-built, secret-free session configuration. The page sends that configuration on the DataChannel.
3. Audio flows directly between browser and Qwen over RTP. Quip does not proxy audio. The session uses full-duplex audio, server VAD, Russian instructions, bounded chat context, and only the approved function definitions. Disable Qwen's built-in web search and MCP; all web access must go through Quip.
4. The page shows real states: idle, requesting microphone, connecting, listening, assistant speaking, muted, handing off, ending, ended, and actionable errors. Mute disables the local track. On speech onset while Qwen is responding, send `response.cancel`; if a tool call is pending, cancel that Quip request too. If the tool already finished, keep its result in history but do not resume the canceled response. A read-only network request cannot be rolled back.
5. End stops local tracks, cancels any active response/tool where possible, closes the peer connection, and records the call end. If the page disappears, Quip cannot promise immediate termination of the provider session.
6. Show in-app call and text-run status only for real events. No OS/browser notifications, push delivery, incoming/spontaneous calls, or background task guarantees.

## Initial tools: Quip web search and page reading

Voice may expose only these functions:

- `read_url(url)`: reuse `quip.services.scraper.read_url`, its existing fallback/timeouts, `validate_outbound_url` before fetch, and `safe_get` redirect checks; accept only public HTTP(S) URLs without embedded credentials, capped at 2,048 URL characters and 15,000 output characters. Keep it available wherever Quip's existing base tool is available.
- `web_search(query)`: reuse `quip.services.search.web_search` and its configured Tavily/SearXNG provider, server credentials, caching, and five-result cap. Limit the query to 500 characters. Expose and execute it only when Quip's existing `search_enabled` setting and enabled `web_search` skill permit it.

Do not call Qwen's own web search or duplicate provider-search logic. The browser submits `response.function_call_arguments.done` data (`call_id`, name, arguments) to an authenticated Quip tool endpoint. The endpoint ignores client-supplied user, chat, workspace, model, URL-base, and permission fields; it resolves the active call and owner from the database and accepts only the exact allowlisted function names. It independently validates JSON/schema, limits, search gate, URL safety, and chat ownership. A provider event is not proof of authorization: a modified client can fabricate one, so every request is treated as a user-originated read request under existing Quip gates.

Use a `VoiceToolCall` ledger with a unique `(voice_call_id, provider_call_id)`, canonical request hash, status, timestamps, and linked result message. Repeating the same ID and same request returns the stored status/result without repeating the network call; reusing an ID with different arguments is rejected. Allow one in-flight tool per call and cap each call at ten tool requests, including at most five searches. Apply a 30-second overall tool timeout and existing result-size limits. Store successful results as attributed `tool` messages in the same chat, including source URLs for search results. Send a sanitized structured error to the model for denied, invalid, timed-out, canceled, or failed requests; never include credentials, stack traces, or upstream secrets. Return the result to the browser, which sends the documented `function_call_output` and `response.create` only if the response was not interrupted.

On interruption, the browser sends `response.cancel` if a Qwen response remains active and calls Quip's cancel endpoint for the matching pending tool ID. Quip marks it canceled and cancels the in-flight read-only task where possible. A completion/cancel race is resolved by the ledger: persist a result that completed first, but do not replay it into a canceled answer. The next user turn starts from the persisted transcript/tool history. No shell, sandbox, arbitrary code, image/music generation, app/account APIs, generic MCP credentials, or new permissions are exposed.

## Shared conversation context and text-model handoff

- `Message` rows remain the immutable source history for typed turns, voice transcripts, and tool results. Preserve role/speaker, source, model, call/tool IDs, timestamps, and source URLs so the context builder can distinguish user, assistant, and tool evidence.
- Reuse `HistoryService` for a bounded recent-message window; add an explicit limit instead of using its current default 100-message batch for voice/handoff. Reuse `Chat.meta` only as the pointer to the latest versioned context state (`version`, compact summary, task state, source-message IDs, and `covers_through` watermark). Keep each handoff snapshot/version in `VoiceCall` metadata and the existing `ChatRun.run_metadata`; never rewrite old messages.
- On handoff or compaction, update the summary incrementally from the prior version plus only newly persisted messages. Structure task state as goal, constraints, decisions, completed work, and open work. Treat summaries and retrieved history as untrusted conversation context, never as new system instructions or permissions. For older facts, use Quip's existing message-search pattern scoped strictly to the current owned chat; retrieve only relevant matches on demand. Reuse document RAG only for files in the current chat/authorized workspace, with cross-chat retrieval disabled for this path.
- Cap carried context at **6,000 estimated tokens per model request**: at most 1,200 for summary/task state, 3,200 for recent turns, and 1,600 for retrieved older turns/document snippets. Use a model-compatible token counter or a conservative estimator; also enforce the selected model's context limit. Never send the entire chat history on each turn. If a legacy chat has no summary, start with bounded recent turns and fetch older facts only when requested; do not backfill by sending all history to a model.
- The user selects a supported text provider/model through Quip's existing provider-agnostic model-selection seam and explicitly starts **Continue with text model**. Voice must call the common completion interface, not a provider-specific endpoint or hard-coded OpenRouter path. End/cancel the voice response, persist the last transcript and pending tool states, build one shared context/handoff packet, and start the ordinary completion path for the same chat. Reuse `ChatRun` for its actual queued/running/completed/failed lifecycle and store the handoff/context version in `run_metadata`. Do not grant the text model new voice-specific tools or permissions; existing text-path gates still apply.
- A future ChatGPT sign-in/subscription-quota provider using the Responses API is outside this voice change. Do not implement its OAuth, account setup, entitlement checks, or live calls here; hosted Quip eligibility is not verified. The shared completion seam must allow that provider to be added later without rewriting voice.
- Persisted context/task state is not durable execution. The handoff uses the existing text completion lifecycle; do not claim work will continue after a page/process disconnect unless a real background executor is added separately.

## Authorization, storage, and cost limits

- Use Quip's cookie-authenticated `get_current_user` pattern and verify `Chat.user_id` for every call, transcript, context, and tool endpoint. Apply same-origin/CSRF checks consistent with existing writes. Never accept arbitrary provider endpoints/models/headers from the browser.
- Add a `VoiceCall` record for owner/chat, provider/model, lifecycle, timestamps, safe error code, context version, and client-reported usage marked **unverified**. Persist completed user text from Qwen input-transcription events and assistant text from `response.audio_transcript.done` as linked `Message` rows. The input transcription is reference text and may differ from what Omni understood. Do not store raw audio.
- Keep voice disabled until an operator configures the provider/model/endpoint, server-only API key, and user-visible cost notice, including possible separate ASR usage. No real keys or live inference in this branch.
- Enforce server-verifiable start checks (auth, ownership, feature/model allowlist, concurrency, existing authoritative budget gate). `response.done` usage is browser-reported, not authoritative Quip billing. A browser timer/usage warning and cooperative stop are soft only; neither is a hard per-call ceiling or server-side termination. Alibaba account-level budget controls are external and delayed, not a real-time session kill switch. Make no stronger claim.
- No WebSocket audio-proxy fallback, Telegram user-account calling, permanent/autonomous assistant, sandbox/account permission expansion, or deployment.

## Smallest integration and verification plan

- Backend: isolated voice provider/router/services and migrations for `VoiceCall` and idempotent tool ledger; reuse auth, `Chat`, `Message`, `HistoryService`, existing `read_url`/`web_search` implementations, RAG with stricter scope, and `ChatRun` for text handoff. Handoff depends on the common provider-agnostic completion seam. Frontend: isolated call controller/panel and a small ChatInput/ChatPane entry point; parent coordinates shared UI/completion changes before implementation.
- Fixture-only tests: SDP forwarding/key secrecy/errors; chat ownership and search gate; URL/schema/tool-name rejection; tool ID idempotency/conflict, timeout, cancellation races and sanitized errors; voice interruption while speaking/tool pending; transcript/tool source attribution; voice-to-text handoff through a mocked provider-agnostic completion interface into the selected model/ChatRun; incremental summary preservation of constraints/decisions; message retrieval scope, token caps, and cross-user/workspace isolation; interruption/end and actual completion lifecycle.
- Verify UI permission, call state, mute/end, DataChannel/ICE errors, transcript and ChatRun notifications with browser mocks. No paid calls, live keys, deployment, or live acoustic claim. Acoustic quality/latency and real provider interruption remain unverified until separately authorized.

## Acceptance criteria

- Direct browser-to-Qwen WebRTC audio; server-only provider credentials; no hidden WS audio path.
- Russian voice conversation with mute/interruption, recent+versioned context, and saved typed/voice/tool history in the same Quip chat.
- Quip-backed `web_search`/`read_url` work through the authenticated allowlisted bridge and respect existing gates; no additional tools or permissions.
- Explicit handoff to the selected text provider/model uses Quip's common completion seam, the same bounded context/task state, and `ChatRun` lifecycle, with source attribution and tenant isolation.
- Cost notices and status distinguish authoritative server checks from unverified provider usage and cooperative browser stops.
- All tests use protocol fixtures/mocks; no live key, paid API call, deployment, merge, or main-branch edit.
