import asyncio
import json
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from quip.core.config import set_setting
from quip.main import app
from quip.models.chat import Chat, ChatRun, Message
from quip.models.usage import UsageLog
from quip.models.user import User
from quip.services.chat_runs import ChatRunManager

MODEL = "google/gemini-2.0-flash-001"


def _parse_sse(body: str) -> list[tuple[str, dict]]:
    events = []
    for block in body.strip().split("\n\n"):
        event = ""
        data = ""
        for line in block.split("\n"):
            if line.startswith("event: "):
                event = line[7:]
            elif line.startswith("data: "):
                data = line[6:]
        if event and data:
            events.append((event, json.loads(data)))
    return events


async def _seed_run(db_session, *, status="running", user=None):
    user = user or User(
        email=f"{uuid4()}@test.dev",
        username=f"u-{uuid4().hex[:12]}",
        name="Research owner",
    )
    db_session.add(user)
    await db_session.flush()
    chat = Chat(user_id=user.id, title="Persisted research")
    db_session.add(chat)
    await db_session.flush()
    message = Message(chat_id=chat.id, role="assistant", content="Partial report", model=MODEL)
    db_session.add(message)
    await db_session.flush()
    run = ChatRun(
        chat_id=chat.id,
        user_id=user.id,
        assistant_message_id=message.id,
        status=status,
        model=MODEL,
        run_metadata={
            "schema_version": 1,
            "task_kind": "research",
            "revision": 2,
            "context_version": 1,
            "cancel_requested": False,
            "steering": [],
            "snapshot": {
                "progress": [{"phase": "searching", "detail": "Mock search"}],
                "sources": [{"title": "Example source", "url": "https://example.org/source"}],
            },
        },
    )
    db_session.add(run)
    await db_session.commit()
    return chat, message, run, user


@pytest.mark.asyncio
async def test_research_mode_gate_fails_closed_and_search_remains_separate(client, auth_headers):
    set_setting("openrouter_api_key", "mock-key")
    set_setting("rag_enabled", "false")
    set_setting("sandbox_enabled", "false")
    set_setting("research_enabled", "false")
    set_setting("research_runner_mode", "disabled")
    created = await client.post("/api/chats", headers=auth_headers, json={"title": "Modes"})
    chat_id = created.json()["id"]

    rejected_by_admin_gate = await client.post(
        "/api/chat/completions",
        headers=auth_headers,
        json={"chat_id": chat_id, "model": MODEL, "message": "Do research", "mode_hint": "research"},
    )
    assert rejected_by_admin_gate.status_code == 403

    set_setting("research_enabled", "true")
    rejected_by_runner_guard = await client.post(
        "/api/chat/completions",
        headers=auth_headers,
        json={"chat_id": chat_id, "model": MODEL, "message": "Do research", "mode_hint": "research"},
    )
    assert rejected_by_runner_guard.status_code == 503

    set_setting("search_enabled", "true")
    seen = []

    async def fake_run(self, *, chat_id, user_id, max_rounds):
        seen.append((self.search_mode, max_rounds))
        from quip.services.streaming import sse_event
        yield sse_event("content", {"text": "Fast search response"})
        yield sse_event("done", {})

    from unittest.mock import AsyncMock, patch

    with patch("quip.services.completion.service.StreamOrchestrator.run", new=fake_run), \
         patch("quip.services.completion.service.save_assistant_message", new_callable=AsyncMock):
        search_response = await client.post(
            "/api/chat/completions",
            headers=auth_headers,
            json={"chat_id": chat_id, "model": MODEL, "message": "Quick search", "mode_hint": "search"},
        )
    assert search_response.status_code == 200
    assert seen == [(True, 3)]


@pytest.mark.asyncio
async def test_run_state_is_owner_scoped_and_cancel_is_idempotent(client, auth_headers, db_session):
    owner = (await db_session.execute(select(User).where(User.username == "testuser"))).scalar_one()
    chat, message, run, owner = await _seed_run(db_session, user=owner)
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    old_manager = getattr(app.state, "chat_run_manager", None)
    app.state.chat_run_manager = ChatRunManager(factory, runner_mode="single_process")
    try:
        state = await client.get(
            f"/api/chats/{chat.id}/runs/{run.id}", headers=auth_headers
        )
        assert state.status_code == 200
        payload = state.json()
        assert payload["revision"] == 2
        assert payload["context_version"] == 1
        assert payload["result_message_id"] == str(message.id)
        assert payload["message"]["content"] == "Partial report"
        assert payload["snapshot"]["sources"][0]["url"] == "https://example.org/source"
        chat_view = await client.get(f"/api/chats/{chat.id}", headers=auth_headers)
        assert chat_view.status_code == 200
        assert chat_view.json()["runs"][0]["task_kind"] == "research"

        from quip.services.auth import create_access_token
        other = User(
            email="other-research@test.dev", username="other-research",
            name="Other", role="user",
        )
        db_session.add(other)
        await db_session.commit()
        other_headers = {"Authorization": f"Bearer {create_access_token(str(other.id), other.role)}"}
        hidden = await client.get(
            f"/api/chats/{chat.id}/runs/{run.id}", headers=other_headers
        )
        assert hidden.status_code == 404
        wrong_chat = await client.get(
            f"/api/chats/{uuid4()}/runs/{run.id}", headers=auth_headers
        )
        assert wrong_chat.status_code == 404

        steering = await client.post(
            f"/api/chats/{chat.id}/runs/{run.id}/steer",
            headers=auth_headers,
            json={"instruction": "Add a concise limitations section."},
        )
        assert steering.status_code == 200
        assert steering.json()["context_version"] == 2
        assert steering.json()["run"]["steering"][0]["instruction"] == "Add a concise limitations section."

        cancelled = await client.post(
            f"/api/chats/{chat.id}/runs/{run.id}/cancel", headers=auth_headers
        )
        repeated = await client.post(
            f"/api/chats/{chat.id}/runs/{run.id}/cancel", headers=auth_headers
        )
        assert cancelled.status_code == repeated.status_code == 200
        assert cancelled.json()["accepted"] is True
        assert repeated.json()["accepted"] is False

        steered = await client.post(
            f"/api/chats/{chat.id}/runs/{run.id}/steer",
            headers=auth_headers,
            json={"instruction": "Include a short limitations section."},
        )
        assert steered.status_code == 409
    finally:
        await app.state.chat_run_manager.close()
        if old_manager is None:
            del app.state.chat_run_manager
        else:
            app.state.chat_run_manager = old_manager


@pytest.mark.asyncio
async def test_disconnect_detaches_and_reload_finds_partial_research(client, auth_headers, db_session):
    set_setting("openrouter_api_key", "mock-key")
    set_setting("research_enabled", "true")
    set_setting("research_runner_mode", "single_process")
    set_setting("rag_enabled", "false")
    set_setting("sandbox_enabled", "false")
    set_setting("tool_gating_enabled", "false")
    created = await client.post("/api/chats", headers=auth_headers, json={"title": "Durable"})
    chat_id = created.json()["id"]

    entered = asyncio.Event()
    release = asyncio.Event()

    async def fake_research(context, **_kwargs):
        await context.update_snapshot(
            progress=[{"phase": "searching", "detail": "Mock worker"}],
            sources=[{"title": "Fixture", "url": "https://example.test/source"}],
        )
        await context.append_result("Partial report retained after disconnect.")
        await context.emit({"type": "status", "data": {"phase": "searching", "detail": "Mock worker"}})
        entered.set()
        await release.wait()
        return {"status": "partial", "error": "One mocked agent failed"}

    from unittest.mock import AsyncMock, patch
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    from quip.services.chat_runs import ChatRunManager
    from quip.services.research.run_manager import ResearchRunManager

    old_manager = getattr(app.state, "chat_run_manager", None)
    app.state.chat_run_manager = ChatRunManager(factory, runner_mode="single_process")
    app.state.research_run_manager = ResearchRunManager(
        app.state.chat_run_manager,
        runner=fake_research,
    )
    request_task = None
    try:
        with patch("quip.services.completion.service._copy_attachments_to_sandbox", new_callable=AsyncMock), \
             patch("quip.services.completion.service.PromptBuilder.inject_rag", new_callable=AsyncMock, return_value=""):
            request_task = asyncio.create_task(client.post(
                "/api/chat/completions",
                headers=auth_headers,
                json={"chat_id": chat_id, "model": MODEL, "message": "Research this", "mode_hint": "research"},
            ))
            await asyncio.wait_for(entered.wait(), 3)
            request_task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await request_task
            release.set()
            await asyncio.sleep(0.05)

        persisted = await db_session.execute(
            select(ChatRun).where(ChatRun.chat_id == UUID(chat_id)).order_by(ChatRun.created_at.desc())
        )
        run = persisted.scalars().first()
        assert run is not None
        state = await client.get(
            f"/api/chats/{chat_id}/runs/{run.id}", headers=auth_headers
        )
        assert state.status_code == 200
        assert state.json()["status"] == "partial"
        assert state.json()["message"]["content"] == "Partial report retained after disconnect."
        assert state.json()["snapshot"]["sources"][0]["url"] == "https://example.test/source"
    finally:
        release.set()
        if request_task and not request_task.done():
            request_task.cancel()
        if hasattr(app.state, "research_run_manager"):
            del app.state.research_run_manager
        await app.state.chat_run_manager.close()
        if old_manager is None:
            del app.state.chat_run_manager
        else:
            app.state.chat_run_manager = old_manager


@pytest.mark.asyncio
async def test_oversized_unicode_sources_are_bounded_and_live_snapshot_matches_saved(db_session):
    chat, message, run, owner = await _seed_run(db_session, status="queued")
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    from quip.services.chat_runs import ChatRunManager, ChatRunSpec, read_run
    from quip.services.research.run_manager import ResearchRunManager, ResearchRunSpec
    from quip.services.research.types import ResearchEvent

    source_fixtures = [
        {
            "title": f"Источник {index} 🌐 " + "я" * 3000,
            "url": f"https://example.test/source-{index}/" + "a" * 1750,
        }
        for index in range(30)
    ]
    source_fixtures.append({"title": "too long url", "url": "https://example.test/" + "b" * 2100})

    async def fake_research(_context, *, emit, **_kwargs):
        await emit(ResearchEvent("status", {
            "phase": "searching", "detail": "🔬" * 3000,
        }))
        await emit(ResearchEvent("sources", {"sources": source_fixtures}))

    task_manager = ChatRunManager(factory, runner_mode="single_process")
    research_manager = ResearchRunManager(task_manager, runner=fake_research)
    subscription = await research_manager.start(ResearchRunSpec(
        run=ChatRunSpec(
            run_id=run.id, chat_id=chat.id, user_id=owner.id,
            assistant_message_id=message.id, task_kind="research",
        ),
        query="Large mocked source set", model=MODEL,
    ))
    try:
        events = [event async for event in subscription]
        persisted = await read_run(factory, run_id=run.id, chat_id=chat.id, user_id=owner.id)
        snapshots = [event["data"]["snapshot"] for event in events if event["type"] == "research_snapshot"]

        assert snapshots, "the live stream must include the same bounded durable snapshot"
        assert snapshots[-1] == persisted["snapshot"]
        assert persisted["snapshot"]["truncated"] is True
        assert len(json.dumps(persisted["snapshot"], ensure_ascii=False).encode("utf-8")) <= 48_000
        expected_urls = {source["url"] for source in source_fixtures[:-1]}
        stored_urls = [source["url"] for source in persisted["snapshot"]["sources"]]
        assert stored_urls
        assert all(url in expected_urls for url in stored_urls)
        assert all(len(source["title"].encode("utf-8")) <= 512 for source in persisted["snapshot"]["sources"])
        assert all(source["url"].endswith("a" * 1750) for source in persisted["snapshot"]["sources"])
    finally:
        await subscription.aclose()
        await task_manager.close()


@pytest.mark.asyncio
async def test_stop_endpoint_cancels_active_research_and_keeps_partial_text(client, auth_headers, db_session):
    set_setting("openrouter_api_key", "mock-key")
    set_setting("research_enabled", "true")
    set_setting("research_runner_mode", "single_process")
    set_setting("rag_enabled", "false")
    set_setting("sandbox_enabled", "false")
    set_setting("tool_gating_enabled", "false")
    created = await client.post("/api/chats", headers=auth_headers, json={"title": "Stop"})
    chat_id = created.json()["id"]
    entered = asyncio.Event()

    async def fake_research(context, **_kwargs):
        await context.append_result("Useful work before Stop.")
        entered.set()
        await asyncio.Event().wait()

    from unittest.mock import AsyncMock, patch
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    from quip.services.research.run_manager import ResearchRunManager

    old_manager = getattr(app.state, "chat_run_manager", None)
    old_research_manager = getattr(app.state, "research_run_manager", None)
    app.state.chat_run_manager = ChatRunManager(factory, runner_mode="single_process")
    app.state.research_run_manager = ResearchRunManager(app.state.chat_run_manager, runner=fake_research)
    request_task = None
    try:
        with patch("quip.services.completion.service._copy_attachments_to_sandbox", new_callable=AsyncMock), \
             patch("quip.services.completion.service.PromptBuilder.inject_rag", new_callable=AsyncMock, return_value=""):
            request_task = asyncio.create_task(client.post(
                "/api/chat/completions",
                headers=auth_headers,
                json={"chat_id": chat_id, "model": MODEL, "message": "Stop test", "mode_hint": "research"},
            ))
            await asyncio.wait_for(entered.wait(), 3)
            await asyncio.sleep(0)
            found = await db_session.execute(
                select(ChatRun).where(ChatRun.chat_id == UUID(chat_id)).order_by(ChatRun.created_at.desc())
            )
            run = found.scalars().first()
            assert run is not None
            stopped = await client.post(
                f"/api/chats/{chat_id}/runs/{run.id}/cancel", headers=auth_headers
            )
            assert stopped.status_code == 200
            assert stopped.json()["accepted"] is True
            response = await asyncio.wait_for(request_task, 3)
            assert response.status_code == 200

        state = await client.get(f"/api/chats/{chat_id}/runs/{run.id}", headers=auth_headers)
        assert state.json()["status"] == "cancelled"
        assert state.json()["message"]["content"] == "Useful work before Stop."
    finally:
        if request_task and not request_task.done():
            request_task.cancel()
        await app.state.chat_run_manager.close()
        if old_manager is None:
            del app.state.chat_run_manager
        else:
            app.state.chat_run_manager = old_manager
        if old_research_manager is None:
            del app.state.research_run_manager
        else:
            app.state.research_run_manager = old_research_manager


@pytest.mark.asyncio
async def test_usage_from_cancelled_research_is_still_logged(db_session):
    chat, message, run, owner = await _seed_run(db_session, status="queued")
    run_id = run.id
    chat_id, user_id, message_id = chat.id, owner.id, message.id
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    from quip.services.chat_runs import ChatRunManager, ChatRunSpec
    from quip.services.research.run_manager import ResearchRunManager, ResearchRunSpec
    from quip.services.research.types import ResearchEvent

    entered = asyncio.Event()

    async def fake_research(_context, *, emit, **_kwargs):
        await emit(ResearchEvent("usage", {
            "prompt_tokens": 12, "completion_tokens": 4, "cached_tokens": 0,
            "cost": 0.02, "provider": "mock-provider", "generation_id": "mock-generation",
            "subagent_generations": ["mock-generation"],
        }))
        entered.set()
        await asyncio.Event().wait()

    task_manager = ChatRunManager(factory, runner_mode="single_process")
    research_manager = ResearchRunManager(task_manager, runner=fake_research)
    subscription = await research_manager.start(ResearchRunSpec(
        run=ChatRunSpec(
            run_id=run_id,
            chat_id=chat_id,
            user_id=user_id,
            assistant_message_id=message_id,
            task_kind="research",
        ),
        query="Mocked cost accounting",
        model=MODEL,
    ))
    try:
        await asyncio.wait_for(entered.wait(), 1)
        assert await task_manager.request_cancel(run_id=run_id, chat_id=chat_id, user_id=user_id)
        deadline = asyncio.get_running_loop().time() + 2
        while True:
            db_session.expire_all()
            stored = await db_session.get(ChatRun, run_id)
            if stored and stored.status == "cancelled":
                break
            if asyncio.get_running_loop().time() >= deadline:
                raise TimeoutError("cancelled run did not reach a terminal state")
            await asyncio.sleep(0.01)
        costs = await db_session.execute(select(UsageLog).where(UsageLog.message_id == message_id))
        usage = costs.scalars().one()
        assert float(usage.cost) == 0.02
        assert usage.generation_id == "mock-generation"
    finally:
        await subscription.aclose()
        await task_manager.close()
