"""Tenant-isolation tests for tools that read uploaded file data."""

import json

import pytest

from quip.models.chat import Chat, Message
from quip.models.file import DocumentImage, File
from quip.models.user import User
from quip.services.completion.history import HistoryService
from quip.services.image_gen import _read_image_to_base64
from quip.services.tools import execute_tool_call


@pytest.mark.asyncio
async def test_history_does_not_resolve_legacy_cross_user_attachment(db_session):
    """Old malicious attachment metadata cannot reopen another tenant's file."""
    owner = User(
        email="history-owner@test.dev",
        username="history-owner",
        name="History Owner",
        role="user",
    )
    other = User(
        email="history-other@test.dev",
        username="history-other",
        name="History Other",
        role="user",
    )
    db_session.add_all([owner, other])
    await db_session.flush()
    other_chat = Chat(user_id=other.id, title="Other chat")
    db_session.add(other_chat)
    await db_session.flush()
    owner_file = File(
        user_id=owner.id,
        chat_id=other_chat.id,
        filename="legacy-secret.txt",
        content_type="text/plain",
        size=6,
        file_type="document",
        storage_path="owner/legacy-secret.txt",
        embedding_status="completed",
    )
    db_session.add(owner_file)
    await db_session.flush()
    poisoned_message = Message(
        chat_id=other_chat.id,
        role="user",
        content="legacy",
        meta={"attachments": [{"file_id": str(owner_file.id)}]},
    )
    db_session.add(poisoned_message)
    await db_session.commit()

    path_map = await HistoryService.build_file_path_map(
        [poisoned_message], other_chat, db_session
    )

    assert path_map == {}


@pytest.mark.asyncio
async def test_image_edit_reader_requires_file_owner(db_session, tmp_upload_dir):
    owner = User(
        email="image-owner@test.dev",
        username="image-owner",
        name="Image Owner",
        role="user",
    )
    other = User(
        email="image-other@test.dev",
        username="image-other",
        name="Image Other",
        role="user",
    )
    db_session.add_all([owner, other])
    await db_session.flush()

    storage_path = f"{owner.id}/source.png"
    absolute_path = tmp_upload_dir / storage_path
    absolute_path.parent.mkdir(parents=True)
    absolute_path.write_bytes(b"owner-image")
    file_record = File(
        user_id=owner.id,
        filename="source.png",
        content_type="image/png",
        size=11,
        file_type="image",
        storage_path=storage_path,
        embedding_status="skipped",
    )
    db_session.add(file_record)
    await db_session.commit()

    url = f"/api/files/{file_record.id}"
    assert await _read_image_to_base64(url, db_session, user_id=other.id) is None
    assert await _read_image_to_base64(url, db_session, user_id=owner.id) is not None


@pytest.mark.asyncio
async def test_document_image_tool_requires_file_owner(db_session, tmp_upload_dir):
    owner = User(
        email="doc-owner@test.dev",
        username="doc-owner",
        name="Document Owner",
        role="user",
    )
    other = User(
        email="doc-other@test.dev",
        username="doc-other",
        name="Document Other",
        role="user",
    )
    db_session.add_all([owner, other])
    await db_session.flush()

    storage_path = f"{owner.id}/document-image.png"
    absolute_path = tmp_upload_dir / storage_path
    absolute_path.parent.mkdir(parents=True)
    absolute_path.write_bytes(b"document-image")
    file_record = File(
        user_id=owner.id,
        filename="document.pdf",
        content_type="application/pdf",
        size=100,
        file_type="document",
        storage_path=f"{owner.id}/document.pdf",
        embedding_status="completed",
    )
    db_session.add(file_record)
    await db_session.flush()
    db_session.add(
        DocumentImage(
            file_id=file_record.id,
            ref="img_1",
            page=1,
            storage_path=storage_path,
            mime="image/png",
        )
    )
    await db_session.commit()

    arguments = json.dumps({"file_id": str(file_record.id), "ref": "img_1"})
    denied_raw = await execute_tool_call(
        None,
        None,
        "chat-id",
        "get_document_image",
        arguments,
        db=db_session,
        user_id=other.id,
    )
    allowed_raw = await execute_tool_call(
        None,
        None,
        "chat-id",
        "get_document_image",
        arguments,
        db=db_session,
        user_id=owner.id,
    )

    assert json.loads(denied_raw)["error"] == "image not found: img_1"
    assert json.loads(allowed_raw)["image_data_url"].startswith(
        "data:image/png;base64,"
    )
