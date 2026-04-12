"""Tests for copying uploaded files into the sandbox workspace."""
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest


@pytest.mark.asyncio
async def test_copy_attachments_writes_to_sandbox(tmp_upload_dir):
    """Happy path: attachment metadata → sandbox_manager.copy_host_file called with right args."""
    from quip.routers.completion import _copy_attachments_to_sandbox

    user_id = uuid4()
    fake_file_id = uuid4()
    user_dir = tmp_upload_dir / str(user_id)
    user_dir.mkdir(parents=True)
    fake_file = user_dir / f"{fake_file_id}.epub"
    fake_file.write_bytes(b"PK\x03\x04fake epub content")

    fake_user = MagicMock(id=user_id)
    fake_chat = MagicMock(id=uuid4())
    attachments = [
        {
            "file_id": str(fake_file_id),
            "filename": "osvobodit_vedmu.epub",
            "file_type": "document",
            "content_type": "application/epub+zip",
            "storage_path": f"{user_id}/{fake_file_id}.epub",
        }
    ]

    fake_sandbox = MagicMock()
    with patch("quip.routers.completion.sandbox_manager") as sm, \
         patch("quip.routers.completion.get_setting", return_value="true"):
        sm.available = True
        sm.get_or_create = AsyncMock(return_value=fake_sandbox)
        sm.ensure_chat_dir = AsyncMock()
        sm.copy_host_file = AsyncMock(return_value=True)

        await _copy_attachments_to_sandbox(fake_user, fake_chat, attachments, AsyncMock())

        sm.get_or_create.assert_awaited_once()
        sm.ensure_chat_dir.assert_awaited_once()
        sm.copy_host_file.assert_awaited_once()
        args = sm.copy_host_file.await_args.args
        assert args[1] == str(fake_chat.id)
        assert args[3] == "osvobodit_vedmu.epub"
        assert args[2].name == f"{fake_file_id}.epub"


@pytest.mark.asyncio
async def test_copy_skipped_when_sandbox_disabled():
    """sandbox_enabled=false → helper exits early, no sandbox interaction."""
    from quip.routers.completion import _copy_attachments_to_sandbox

    attachments = [{"file_id": str(uuid4()), "filename": "x.txt", "storage_path": "u/x.txt"}]

    with patch("quip.routers.completion.sandbox_manager") as sm, \
         patch("quip.routers.completion.get_setting", return_value="false"):
        sm.available = True
        sm.get_or_create = AsyncMock()
        sm.copy_host_file = AsyncMock()

        await _copy_attachments_to_sandbox(MagicMock(id=uuid4()), MagicMock(id=uuid4()), attachments, AsyncMock())

        sm.get_or_create.assert_not_awaited()
        sm.copy_host_file.assert_not_awaited()


@pytest.mark.asyncio
async def test_copy_handles_filename_collisions(tmp_upload_dir):
    """Two attachments with the same filename → second one gets a disambiguating suffix."""
    from quip.routers.completion import _copy_attachments_to_sandbox

    user_id = uuid4()
    user_dir = tmp_upload_dir / str(user_id)
    user_dir.mkdir(parents=True)
    file_id_a = uuid4()
    file_id_b = uuid4()
    (user_dir / f"{file_id_a}.txt").write_bytes(b"a")
    (user_dir / f"{file_id_b}.txt").write_bytes(b"b")

    attachments = [
        {
            "file_id": str(file_id_a),
            "filename": "notes.txt",
            "file_type": "document",
            "content_type": "text/plain",
            "storage_path": f"{user_id}/{file_id_a}.txt",
        },
        {
            "file_id": str(file_id_b),
            "filename": "notes.txt",
            "file_type": "document",
            "content_type": "text/plain",
            "storage_path": f"{user_id}/{file_id_b}.txt",
        },
    ]

    with patch("quip.routers.completion.sandbox_manager") as sm, \
         patch("quip.routers.completion.get_setting", return_value="true"):
        sm.available = True
        sm.get_or_create = AsyncMock(return_value=MagicMock())
        sm.ensure_chat_dir = AsyncMock()
        sm.copy_host_file = AsyncMock(return_value=True)

        await _copy_attachments_to_sandbox(MagicMock(id=user_id), MagicMock(id=uuid4()), attachments, AsyncMock())

        assert sm.copy_host_file.await_count == 2
        dest_names = [call.args[3] for call in sm.copy_host_file.await_args_list]
        assert dest_names[0] == "notes.txt"
        assert dest_names[1] != "notes.txt"
        assert dest_names[1].startswith("notes_") and dest_names[1].endswith(".txt")
