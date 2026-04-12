"""Tests for the completion endpoint — multimodal messages, RAG injection, streaming.

Model: google/gemini-2.0-flash-001 (mocked — no real API calls).
"""
import json
import pytest
from io import BytesIO
from unittest.mock import patch, AsyncMock

from quip.providers.openrouter import StreamChunk, UsageInfo
from quip.services.config import set_setting
from quip.models.file import File, DocumentChunk
from quip.models.chat import Chat, Message

MODEL = "google/gemini-2.0-flash-001"


def _png_bytes():
    from PIL import Image
    buf = BytesIO()
    Image.new("RGB", (1, 1), "red").save(buf, format="PNG")
    return buf.getvalue()


def _parse_sse(body: str) -> list[tuple[str, dict]]:
    """Parse SSE response into (event_name, data_dict) pairs."""
    events = []
    for block in body.strip().split("\n\n"):
        ev = ""
        data = ""
        for line in block.split("\n"):
            if line.startswith("event: "):
                ev = line[7:]
            elif line.startswith("data: "):
                data = line[6:]
        if ev and data:
            events.append((ev, json.loads(data)))
    return events


async def _fake_stream(**kwargs):
    """Minimal mock stream yielding one content chunk."""
    yield StreamChunk(content="Hello from Gemini!")
    yield StreamChunk(finish_reason="stop")
    yield StreamChunk(usage=UsageInfo(
        prompt_tokens=10, completion_tokens=5, cost=0.0001, provider="Google",
    ))


# ── Tests ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_completion_creates_chat(client, auth_headers):
    """POST without chat_id → creates a new chat, streams SSE response."""
    set_setting("openrouter_api_key", "test-key")
    set_setting("rag_enabled", "false")
    set_setting("artifacts_enabled", "false")
    set_setting("sandbox_enabled", "false")

    with patch("quip.routers.completion.openrouter.stream_completion", new=_fake_stream):
        res = await client.post(
            "/api/chat/completions",
            headers=auth_headers,
            json={"model": MODEL, "message": "Hi there"},
        )

    assert res.status_code == 200
    events = _parse_sse(res.text)

    # First event should be "chat" with ids
    chat_ev = next(e for name, e in events if name == "chat")
    assert "chat_id" in chat_ev
    assert "message_id" in chat_ev

    # Should contain the streamed content
    content_events = [e for name, e in events if name == "content"]
    assert any("Gemini" in e["text"] for e in content_events)

    # Should end with "done"
    assert events[-1][0] == "done"


@pytest.mark.asyncio
async def test_completion_with_image_attachment(client, auth_headers, tmp_upload_dir):
    """Upload image → attach via file_ids → provider receives multimodal content."""
    set_setting("openrouter_api_key", "test-key")
    set_setting("rag_enabled", "false")
    set_setting("artifacts_enabled", "false")
    set_setting("sandbox_enabled", "false")

    # Upload image
    res = await client.post(
        "/api/files/upload",
        headers=auth_headers,
        files=[("files", ("photo.png", _png_bytes(), "image/png"))],
    )
    file_id = res.json()["files"][0]["id"]

    # Capture what messages the provider receives
    captured_messages = []

    async def capturing_stream(**kwargs):
        captured_messages.extend(kwargs.get("messages", []))
        yield StreamChunk(content="I see a red pixel!")
        yield StreamChunk(finish_reason="stop")
        yield StreamChunk(usage=UsageInfo(prompt_tokens=20, completion_tokens=8, cost=0.0002))

    with patch("quip.routers.completion.openrouter.stream_completion", new=capturing_stream):
        res = await client.post(
            "/api/chat/completions",
            headers=auth_headers,
            json={"model": MODEL, "message": "What do you see?", "file_ids": [file_id]},
        )

    assert res.status_code == 200
    assert "red pixel" in res.text

    # The user message should be multimodal (content is a list, not a string)
    user_msgs = [m for m in captured_messages if m["role"] == "user"]
    assert len(user_msgs) >= 1
    last_user = user_msgs[-1]
    assert isinstance(last_user["content"], list), "Image attachment should produce multimodal content"

    content_types = [p["type"] for p in last_user["content"]]
    assert "text" in content_types
    assert "image_url" in content_types

    # Verify base64 data URI
    img_part = next(p for p in last_user["content"] if p["type"] == "image_url")
    assert img_part["image_url"]["url"].startswith("data:image/png;base64,")


@pytest.mark.asyncio
async def test_completion_with_rag_context(client, auth_headers, tmp_upload_dir, db_session):
    """Upload doc + seed chunks → completion injects RAG context into system prompt."""
    set_setting("openrouter_api_key", "test-key")
    set_setting("rag_enabled", "true")
    set_setting("artifacts_enabled", "false")
    set_setting("sandbox_enabled", "false")

    # Create a chat first
    res = await client.post("/api/chats", headers=auth_headers, json={"title": "RAG Test"})
    chat_id = res.json()["id"]

    # Upload a document to this chat (skip background processing)
    with patch("quip.routers.files._process_file_background", new_callable=AsyncMock):
        res = await client.post(
            "/api/files/upload",
            headers=auth_headers,
            files=[("files", ("facts.txt", b"Capital of France is Paris.", "text/plain"))],
            data={"chat_id": chat_id},
        )
    file_id = res.json()["files"][0]["id"]

    # Manually mark file as embedded and seed a chunk
    from uuid import UUID
    from sqlalchemy import select, update

    await db_session.execute(
        update(File).where(File.id == UUID(file_id)).values(embedding_status="completed")
    )
    db_session.add(DocumentChunk(
        file_id=UUID(file_id), chat_id=UUID(chat_id),
        chunk_index=0, content="Capital of France is Paris.",
        embedding=[1.0, 0.0, 0.0], token_count=7,
    ))
    await db_session.commit()

    # Capture messages sent to provider
    captured = []

    async def capturing_stream(**kwargs):
        captured.extend(kwargs.get("messages", []))
        yield StreamChunk(content="Paris!")
        yield StreamChunk(finish_reason="stop")

    with patch("quip.services.rag.get_embeddings", new_callable=AsyncMock,
               return_value=[[0.9, 0.1, 0.0]]), \
         patch("quip.routers.completion.openrouter.stream_completion", new=capturing_stream):
        res = await client.post(
            "/api/chat/completions",
            headers=auth_headers,
            json={"chat_id": chat_id, "model": MODEL, "message": "What is the capital of France?"},
        )

    assert res.status_code == 200

    # System prompt should contain RAG context
    system_msgs = [m for m in captured if m["role"] == "system"]
    assert len(system_msgs) >= 1
    sys_content = system_msgs[0]["content"]
    assert "[Retrieved Context]" in sys_content
    assert "Capital of France is Paris." in sys_content


@pytest.mark.asyncio
async def test_completion_links_files_to_new_chat(client, auth_headers, tmp_upload_dir, db_session):
    """Files uploaded without chat_id get linked when completion creates a chat."""
    set_setting("openrouter_api_key", "test-key")
    set_setting("rag_enabled", "false")
    set_setting("artifacts_enabled", "false")
    set_setting("sandbox_enabled", "false")

    # Upload file without chat_id
    res = await client.post(
        "/api/files/upload",
        headers=auth_headers,
        files=[("files", ("orphan.txt", b"data", "text/plain"))],
    )
    file_id = res.json()["files"][0]["id"]

    with patch("quip.routers.completion.openrouter.stream_completion", new=_fake_stream):
        res = await client.post(
            "/api/chat/completions",
            headers=auth_headers,
            json={"model": MODEL, "message": "Process this", "file_ids": [file_id]},
        )

    assert res.status_code == 200
    events = _parse_sse(res.text)
    chat_id = next(e for name, e in events if name == "chat")["chat_id"]

    # Verify file is now linked to the new chat
    from uuid import UUID
    from sqlalchemy import select

    result = await db_session.execute(select(File).where(File.id == UUID(file_id)))
    file_rec = result.scalar_one()
    assert file_rec.chat_id == UUID(chat_id)


@pytest.mark.asyncio
async def test_completion_saves_attachment_metadata(client, auth_headers, tmp_upload_dir, db_session):
    """File attachment metadata is saved in the user message's meta field."""
    set_setting("openrouter_api_key", "test-key")
    set_setting("rag_enabled", "false")
    set_setting("artifacts_enabled", "false")
    set_setting("sandbox_enabled", "false")

    # Upload an image
    res = await client.post(
        "/api/files/upload",
        headers=auth_headers,
        files=[("files", ("pic.png", _png_bytes(), "image/png"))],
    )
    file_id = res.json()["files"][0]["id"]

    with patch("quip.routers.completion.openrouter.stream_completion", new=_fake_stream):
        res = await client.post(
            "/api/chat/completions",
            headers=auth_headers,
            json={"model": MODEL, "message": "Describe", "file_ids": [file_id]},
        )

    assert res.status_code == 200
    events = _parse_sse(res.text)
    chat_id = next(e for name, e in events if name == "chat")["chat_id"]

    # Check user message has attachment metadata in DB
    from uuid import UUID
    from sqlalchemy import select

    result = await db_session.execute(
        select(Message).where(
            Message.chat_id == UUID(chat_id),
            Message.role == "user",
        )
    )
    user_msg = result.scalar_one()
    assert user_msg.meta is not None
    assert "attachments" in user_msg.meta
    att = user_msg.meta["attachments"][0]
    assert att["file_id"] == file_id
    assert att["file_type"] == "image"
    assert att["content_type"] == "image/png"


@pytest.mark.asyncio
async def test_build_multimodal_message_openrouter(tmp_upload_dir):
    """_build_multimodal_message produces correct OpenRouter format."""
    from quip.routers.completion import _build_multimodal_message

    # Create test image on disk
    user_dir = tmp_upload_dir / "user1"
    user_dir.mkdir()
    img_path = user_dir / "img.png"
    img_path.write_bytes(_png_bytes())

    msg = {"role": "user", "content": "What is this?"}
    attachments = [{
        "file_id": "some-id",
        "file_type": "image",
        "content_type": "image/png",
        "storage_path": "user1/img.png",
    }]

    result = _build_multimodal_message(msg, attachments, is_ollama=False)
    assert isinstance(result["content"], list)
    types = [p["type"] for p in result["content"]]
    assert "text" in types
    assert "image_url" in types
    img_part = next(p for p in result["content"] if p["type"] == "image_url")
    assert img_part["image_url"]["url"].startswith("data:image/png;base64,")


@pytest.mark.asyncio
async def test_build_multimodal_message_ollama(tmp_upload_dir):
    """_build_multimodal_message produces correct Ollama format (images list)."""
    from quip.routers.completion import _build_multimodal_message

    user_dir = tmp_upload_dir / "user1"
    user_dir.mkdir()
    img_path = user_dir / "img.png"
    img_path.write_bytes(_png_bytes())

    msg = {"role": "user", "content": "Describe"}
    attachments = [{
        "file_id": "some-id",
        "file_type": "image",
        "content_type": "image/png",
        "storage_path": "user1/img.png",
    }]

    result = _build_multimodal_message(msg, attachments, is_ollama=True)
    assert "images" in result
    assert len(result["images"]) == 1
    assert result["content"] == "Describe"  # text stays as string


def test_build_multimodal_no_images():
    """Message without image attachments passes through unchanged."""
    from quip.routers.completion import _build_multimodal_message

    msg = {"role": "user", "content": "Just text"}
    attachments = [{"file_type": "document", "content_type": "text/plain"}]

    result = _build_multimodal_message(msg, attachments, is_ollama=False)
    assert result["content"] == "Just text"
