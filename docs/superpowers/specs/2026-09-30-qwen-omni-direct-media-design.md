# Quip website voice calls with Qwen Omni Realtime

**Status:** design proposal for review  
**Branch:** `codex/qwen-omni-voice-20260930`  
**Scope:** one user-started voice call inside an existing Quip web chat

## Goal

Let a signed-in user start, mute, interrupt, and end a spoken Russian conversation from a Quip chat. The call uses Qwen Omni Realtime over browser WebRTC, receives the chat's recent context, routes any enabled tools through Quip's authenticated backend, and saves recognized user/assistant text in that chat. The UI reports real call states and failures.

## Protocol findings that constrain the design

- Alibaba documents WebRTC for browser voice. The browser exchanges an SDP offer for an answer, then audio travels on RTP and model events/text travel on a DataChannel. WebRTC supports server VAD modes, not manual mode. [Realtime API](https://www.alibabacloud.com/help/en/model-studio/realtime)
- For WebRTC, the provider API key is used in the SDP HTTP request's `Authorization` header. The request can be sent by the client or server. Quip will send it from its backend and return only the SDP answer. The docs do not describe an ephemeral WebRTC key; the temporary client token belongs to the separate AOQ protocol. [Token authentication](https://www.alibabacloud.com/help/en/model-studio/realtime-token-authentication)
- Qwen sends input speech VAD and transcription events, assistant audio transcript events, `response.done` usage, and function-call events over the provider event channel. `response.cancel` cancels an ongoing response. Qwen3.8 supports custom function calling and remote MCP; in the documented custom-function flow the client runs the tool. No Qwen sideband/control connection for a backend observer was found in the reviewed docs. [Client events](https://www.alibabacloud.com/help/en/model-studio/client-events), [server events](https://www.alibabacloud.com/help/en/model-studio/server-events)
- The input transcript option names `qwen3-asr-flash-realtime`; Alibaba's pricing page lists a separate duration-based rate for that realtime ASR model, but the reviewed pages do not say whether enabling it inside an Omni session is included or billed separately. Treat it as potentially additional metered usage and confirm the workspace's accounting before enabling paid calls. [Realtime events](https://www.alibabacloud.com/help/en/model-studio/server-events), [model pricing](https://www.alibabacloud.com/help/en/model-studio/model-pricing)
- Provider usage arrives in `response.done` on the browser DataChannel. The billing docs describe cost views and bill generation after a call, typically with minute-level delay; they do not document a per-call live usage API that Quip can use to stop this WebRTC session. [Billing and cost management](https://www.alibabacloud.com/help/en/model-studio/bill-query-and-cost-management)
- The selected model and configured endpoint remain server configuration. Model names and rates may change; read the current [Realtime model/pricing documentation](https://www.alibabacloud.com/help/en/model-studio/model-pricing) before enabling provider billing.

## User experience

1. Add a **Start voice call** action to the existing chat composer. Starting is an explicit user gesture; only then request microphone access.
2. Show in-app states: `idle`, `requesting microphone`, `connecting`, `listening`, `assistant speaking`, `muted`, `ending`, `ended`, and actionable errors. Keep mute and end controls visible while connected.
3. Use full-duplex audio with server VAD. When the provider reports speech onset while Quip is speaking, send the documented `response.cancel` event so the user can interrupt. The browser also immediately stops local playback if needed. Exact barge-in behavior must be verified in mocked browser flows and then manually during an explicitly enabled real call; it must not be claimed as tested by fixtures.
4. Show live transcript text in the call UI. Save completed user transcription and assistant audio transcript as ordinary `Message` rows in the same chat, tagged as voice-originated. Do not record or persist raw audio. Qwen documents the input transcript as a reference transcription that can differ from what the Omni model understood.
5. On mute, disable the local microphone track. On end, stop all media tracks, send `response.cancel` if a response is active, close the peer connection, and record the final call state. If the tab disappears, the provider connection eventually closes on its own; Quip cannot promise immediate server termination.
6. Errors (microphone denied, configuration unavailable, SDP rejection, upstream failure, DataChannel/ICE failure, transcript failure, disconnect) appear in the call panel and an in-app toast where the app's existing notification surface supports it. No OS/browser notifications, background delivery, incoming calls, or task notifications without a real task event source.

## Request and trust boundaries

```text
User clicks Start
  Browser asks for microphone permission
  Browser creates RTCPeerConnection + audio track + Qwen event DataChannel
  Browser POSTs {chat_id, offer_sdp} to authenticated Quip voice endpoint
    Quip verifies the signed-in user owns the chat and preflight policy allows start
    Quip sends SDP offer to configured Qwen endpoint with server-only API key
    Quip returns {call_id, answer_sdp} (never the key or provider credentials)
  Browser sets answer; RTP audio then flows directly between browser and Qwen
  Browser receives Qwen events/transcripts and reports allowed events to Quip
  Quip independently authenticates/authorizes transcript writes and tool requests
```

The backend owns provider/model configuration, the Qwen secret, call records, chat ownership checks, transcript persistence, and tool execution. The browser owns microphone capture, the peer connection, rendering provider events, and closing the direct media connection.

Every browser-submitted event is untrusted. In particular, a relayed function-call payload is not proof that Qwen emitted it: a client can fabricate DataChannel events. The backend must treat it as a user-originated request and independently check active call ownership, the current server-computed tool allowlist, argument schema, existing Quip permissions, rate limits, and any existing confirmation requirement before execution. Do not expose backend credentials or use provider MCP headers from the browser session configuration. The first implementation must exclude shell/sandbox tools, account/security administration, persistent credentials, arbitrary code execution, and newly granted permissions. If existing safe tools cannot be isolated and authorized, expose no tools in voice until they can.

Use the existing cookie-authenticated API pattern (`get_current_user`) and verify `Chat.user_id` for every endpoint. Add same-origin/CSRF checks consistent with the app's current write endpoints. The offer endpoint accepts only SDP for the configured model/provider; it does not accept arbitrary upstream URLs, models, headers, or credentials from the browser.

## Context, transcript, and call records

- Build a bounded, server-side snapshot of the most recent chat messages after checking ownership. Put it in the Qwen session `instructions` together with concise Russian-language behavior instructions. Do not accept history from the browser. The reviewed Realtime `conversation.item.create` event is documented for function results or MCP approvals, not arbitrary chat-history injection.
- Create a durable `VoiceCall` row with user/chat IDs, provider/model, lifecycle status, timestamps, and an optional client-reported usage blob marked **unverified**. Store only safe error codes/messages.
- Save final user text from `conversation.item.input_audio_transcription.completed` and assistant text from `response.audio_transcript.done` as linked `Message` rows with voice metadata and provider/model. Deduplicate by call plus provider item/event ID. Keep partial deltas in the UI; do not repeatedly write them as separate messages.
- Do not turn browser-reported token counts into authoritative `UsageLog.cost`, billing, or Quip budget consumption. They may be retained as unverified diagnostics only.

## Cost controls and their limits

- Keep the feature disabled unless an operator configures the provider/model/endpoint, a server-side API key, and a user-visible cost notice that covers both Omni token usage and the possibly separate input-transcription usage. Use environment-backed secret configuration and a sample config only; never put a key in frontend code, fixtures, logs, or repository history.
- Before signaling, enforce server-verifiable controls available to Quip: authenticated user, chat ownership, feature enabled, one active call per user, configured model allowlist, and any existing budget gate that can be evaluated from authoritative Quip data.
- A browser timer/usage warning can ask the user to end the call, and an in-app threshold can send a cooperative stop request. Neither is a hard cost cap: the browser can be modified or disconnected, and Quip has no documented provider control channel to close the active Qwen session. Do not represent client-reported usage as a server-enforced budget.
- Provider billing has account-level budget controls, but the docs describe billing reports after calls and delayed aggregation. That account setting is external to this feature and is not a per-call real-time kill switch. Until trusted per-call metering/control exists, communicate the direct-call cost limitation before start and keep any configured call-duration cap explicitly labeled as client-enforced/soft.
- No live provider key, paid inference, production configuration, deployment, or automatic WebSocket audio-proxy fallback is part of this work.

## Configuration and module boundaries

- Keep the provider interface narrow: configured model, SDP offer-to-answer exchange, provider event/schema helpers, and sanitized errors. Implement Qwen WebRTC only; keep provider/model values configurable so another supported direct-media adapter can be added later.
- Backend: isolated voice router/service/provider adapter plus migration/model for call lifecycle and transcript metadata. Reuse existing auth, `Chat`, `Message`, and current safe server-side tool facilities rather than changing general chat completion behavior.
- Frontend: isolated voice-call controller/component plus a small entry point in `ChatInput`/`ChatPane`. Keep the normal text-send path untouched.
- No full-audio WebSocket proxy, Telegram user-account calling, browser Notification API, push service worker, autonomous assistant, sandbox/account permission expansion, or unrelated chat tools.

## Verification plan after design approval

1. Backend protocol fixtures: verify configured Qwen endpoint/model, SDP `Content-Type`, server-only Bearer header, exact SDP forwarding/answer, and sanitized upstream failures using mocked HTTP; never call Qwen.
2. Backend authorization/persistence fixtures: reject missing auth, wrong chat owner, arbitrary provider/model/URL, disabled feature, duplicate active calls, forged/disallowed tools, invalid arguments, and duplicate transcript event IDs; verify legitimate transcript messages and voice-call states persist.
3. Frontend mocks: permission grant/denial, connecting/connected/error transitions, mute/unmute, end cleanup, ICE/DataChannel failure, VAD speech onset and `response.cancel`, transcript rendering, and a forged client function event being rejected by backend policy.
4. Run existing relevant frontend/backend tests and type/lint checks as requested by the implementation task. No live microphone or paid provider test is required for this branch; actual acoustic quality/latency and real provider behavior remain unverified until a separately authorized manual call.

## Acceptance criteria

- A signed-in user can start and end a call from an existing Quip website chat; provider API keys never reach the browser.
- Audio uses direct browser-to-Qwen WebRTC RTP; transcripts and text/control events use the documented DataChannel. There is no hidden WebSocket media fallback.
- User can mute and interrupt assistant speech; Russian instructions and existing chat context are applied.
- Completed transcript turns and call lifecycle/error status are saved to the owning chat and visible after reload.
- Tool execution, if enabled, is performed by Quip under the authenticated user's existing permissions and server allowlist; browser/model output never authorizes itself.
- Cost/UI claims distinguish server-enforced preflight controls from unverified usage reports and cooperative client stops.
- Tests run entirely against fixtures/mocks; no paid API call, live key, deployment, or main-branch change.
