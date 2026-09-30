from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import HTTPException

from quip.models.chat import Chat, Message
from quip.models.file import DocumentChunk, File
from quip.models.user import User
from quip.models.voice import VoiceCall
from quip.services.voice.context import VoiceContextService


async def _chat(db_session, *, user_id=None, workspace_id=None):
    user_id = user_id or uuid4()
    chat = Chat(id=uuid4(), user_id=user_id, workspace_id=workspace_id, title="Context")
    db_session.add(chat)
    await db_session.flush()
    return chat


@pytest.mark.asyncio
async def test_voice_context_retrieves_older_same_chat_fact_with_sources(db_session):
    user = User(id=uuid4(), email="context@quip.dev", username="context-user", name="Context", role="user", is_active=True)
    db_session.add(user)
    chat = await _chat(db_session, user_id=user.id)
    now = datetime.now(UTC)
    old = Message(
        id=uuid4(), chat_id=chat.id, role="assistant", content="The project codename is Amber Heron.",
        created_at=now - timedelta(days=4),
    )
    recent_user = Message(
        id=uuid4(), chat_id=chat.id, role="user", content="We should continue the project.",
        created_at=now - timedelta(minutes=1),
    )
    recent_assistant = Message(
        id=uuid4(), chat_id=chat.id, role="assistant", content="I will keep working on it.",
        created_at=now,
    )
    intervening = [
        Message(
            id=uuid4(), chat_id=chat.id, role="user" if index % 2 == 0 else "assistant",
            content=f"Routine update {index}.", created_at=now - timedelta(days=3) + timedelta(seconds=index),
        )
        for index in range(90)
    ]
    db_session.add_all([old, *intervening, recent_user, recent_assistant])
    await db_session.commit()

    packet = await VoiceContextService().build_task_context(
        db_session, user, chat, "What was the project codename Amber Heron?"
    )

    assert any(item.source_id == str(old.id) for item in packet.retrieved)
    assert "Amber Heron" in " ".join(item.text for item in packet.retrieved)
    assert [item.source_id for item in packet.recent][-2:] == [str(recent_user.id), str(recent_assistant.id)]
    assert all(item.source_id != str(old.id) for item in packet.recent)
    assert packet.estimated_tokens <= 6000
    assert "context only" in packet.instruction.lower()


@pytest.mark.asyncio
async def test_voice_context_retrieves_only_owned_chat_and_workspace_documents(db_session):
    from quip.models.workspace import Workspace

    owner = User(id=uuid4(), email="doc-owner@quip.dev", username="doc-owner", name="Owner", role="user", is_active=True)
    other = User(id=uuid4(), email="doc-other@quip.dev", username="doc-other", name="Other", role="user", is_active=True)
    db_session.add_all([owner, other])
    await db_session.flush()
    workspace = Workspace(id=uuid4(), owner_id=owner.id, name="Private", is_personal=True)
    db_session.add(workspace)
    await db_session.flush()
    chat = await _chat(db_session, user_id=owner.id, workspace_id=workspace.id)
    own_file = File(
        id=uuid4(), user_id=owner.id, workspace_id=workspace.id, chat_id=chat.id,
        filename="notes.txt", storage_path="/unused", file_type="document", embedding_status="completed",
    )
    private_file = File(
        id=uuid4(), user_id=other.id, workspace_id=workspace.id, chat_id=chat.id,
        filename="other.txt", storage_path="/unused", file_type="document", embedding_status="completed",
    )
    db_session.add_all([own_file, private_file])
    await db_session.flush()
    own_chunk = DocumentChunk(id=uuid4(), file_id=own_file.id, chat_id=chat.id, chunk_index=0, content="Aurora launch date is 18 October.")
    private_chunk = DocumentChunk(id=uuid4(), file_id=private_file.id, chat_id=chat.id, chunk_index=0, content="Aurora private password is secret.")
    db_session.add_all([own_chunk, private_chunk])
    await db_session.commit()

    packet = await VoiceContextService().build_task_context(db_session, owner, chat, "Find Aurora launch date")

    assert any(item.source_id == str(own_chunk.id) for item in packet.retrieved)
    assert all(item.source_id != str(private_chunk.id) for item in packet.retrieved)
    assert all("private password" not in item.text.lower() for item in packet.retrieved)


@pytest.mark.asyncio
async def test_voice_context_rejects_foreign_chat_without_disclosing_it(db_session):
    owner = User(id=uuid4(), email="context-owner@quip.dev", username="ctx-owner", name="Owner", role="user", is_active=True)
    other = User(id=uuid4(), email="context-other@quip.dev", username="ctx-other", name="Other", role="user", is_active=True)
    db_session.add_all([owner, other])
    await db_session.flush()
    foreign_chat = await _chat(db_session, user_id=other.id)

    with pytest.raises(HTTPException) as error:
        await VoiceContextService().build_task_context(db_session, owner, foreign_chat, "private fact")

    assert error.value.status_code == 404
    assert error.value.detail == "Chat not found"


@pytest.mark.asyncio
async def test_voice_context_summary_is_versioned_and_does_not_mutate_history(db_session):
    user = User(id=uuid4(), email="summary@quip.dev", username="summary-user", name="Summary", role="user", is_active=True)
    db_session.add(user)
    chat = await _chat(db_session, user_id=user.id)
    messages = [
        Message(id=uuid4(), chat_id=chat.id, role="user", content="Constraint: never publish private files.", created_at=datetime.now(UTC) - timedelta(days=2)),
        Message(id=uuid4(), chat_id=chat.id, role="assistant", content="Decision: use an isolated branch.", created_at=datetime.now(UTC) - timedelta(days=1)),
        Message(id=uuid4(), chat_id=chat.id, role="user", content="Current short turn", created_at=datetime.now(UTC)),
    ]
    db_session.add_all(messages)
    await db_session.commit()
    original_contents = [m.content for m in messages]

    service = VoiceContextService()
    first = await service.build_task_context(db_session, user, chat, "continue the work")
    await db_session.refresh(chat)
    stored_summary = (chat.meta or {}).get("voice_context_summary")
    second = await service.build_task_context(db_session, user, chat, "continue the work")

    assert stored_summary["version"] == 1
    assert stored_summary["through_message_id"] == str(messages[-1].id)
    assert first.summary == second.summary
    assert "Constraint" in first.summary and "Decision" in first.summary
    assert [m.content for m in messages] == original_contents

    newer = Message(id=uuid4(), chat_id=chat.id, role="assistant", content="Next step: keep tests mocked.", created_at=datetime.now(UTC) + timedelta(seconds=1))
    db_session.add(newer)
    await db_session.commit()
    await service.build_task_context(db_session, user, chat, "continue the work")
    await db_session.refresh(chat)
    assert chat.meta["voice_context_summary"]["version"] == 2
    assert chat.meta["voice_context_summary"]["through_message_id"] == str(newer.id)


@pytest.mark.asyncio
async def test_voice_context_caps_prompt_budget_even_for_huge_history(db_session):
    user = User(id=uuid4(), email="large-context@quip.dev", username="large-context", name="Large", role="user", is_active=True)
    db_session.add(user)
    chat = await _chat(db_session, user_id=user.id)
    base = datetime.now(UTC) - timedelta(days=1)
    db_session.add_all([
        Message(id=uuid4(), chat_id=chat.id, role="user", content=(f"history datum {i}. " + "x" * 4000), created_at=base + timedelta(seconds=i))
        for i in range(25)
    ])
    await db_session.commit()

    packet = await VoiceContextService().build_task_context(
        db_session, user, chat, "history datum 3", task_state={"goal": "finish", "progress": "y" * 10000}
    )

    assert packet.estimated_tokens <= 6000
    assert sum(len(item.text) for item in packet.recent) <= 12_800
    assert len(packet.task_state.get("progress", "")) <= 4_000


@pytest.mark.asyncio
async def test_voice_context_endpoint_is_owned_and_returns_bounded_packet(client, auth_headers, db_session):
    from sqlalchemy import select

    response = await client.post("/api/chats", headers=auth_headers, json={"title": "Voice context"})
    assert response.status_code == 201
    chat_id = __import__("uuid").UUID(response.json()["id"])
    user = await db_session.scalar(select(User).where(User.email == "test@quip.dev"))
    call = VoiceCall(
        id=uuid4(), user_id=user.id, chat_id=chat_id, provider="qwen",
        model="catalog-model-fixture", status="connecting",
    )
    db_session.add(call)
    await db_session.commit()

    owned = await client.get(f"/api/voice/calls/{call.id}/context", headers=auth_headers)
    foreign = await client.get(f"/api/voice/calls/{uuid4()}/context", headers=auth_headers)

    assert owned.status_code == 200, owned.text
    assert owned.json()["chat_id"] == str(chat_id)
    assert owned.json()["estimated_tokens"] <= 6000
    assert foreign.status_code == 404
