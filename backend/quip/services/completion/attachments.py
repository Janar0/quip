"""Best-effort mirroring of validated attachments into the chat sandbox."""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from quip.models.chat import Chat
from quip.models.user import User

logger = logging.getLogger(__name__)


async def copy_attachments_to_sandbox(
    user: User,
    chat: Chat,
    attachments: list[dict],
    db: AsyncSession,
    *,
    sandbox_manager,
    get_skill_by_name,
    get_upload_dir,
) -> None:
    if not attachments:
        return
    sb_skill = get_skill_by_name("sandbox")
    if not (sb_skill and sb_skill.enabled):
        return
    if not sandbox_manager.available:
        return

    upload_dir = get_upload_dir()
    try:
        sandbox = await sandbox_manager.get_or_create(user.id, db)
        await sandbox_manager.ensure_chat_dir(sandbox, str(chat.id))
    except Exception as e:
        logger.warning("Failed to get/create sandbox for file copy: %s", e)
        return

    chat_id = str(chat.id)
    used_names: set[str] = set()
    for att in attachments:
        storage_path = att.get("storage_path", "")
        if not storage_path:
            continue
        host_path = upload_dir / storage_path
        dest = att.get("filename") or host_path.name
        if dest in used_names:
            short = str(att.get("file_id", "")).replace("-", "")[:6] or "dup"
            stem, dot, ext = dest.rpartition(".")
            dest = f"{stem}_{short}.{ext}" if dot else f"{dest}_{short}"
        used_names.add(dest)
        try:
            await sandbox_manager.copy_host_file(sandbox, chat_id, host_path, dest)
        except Exception as e:
            logger.warning("copy_host_file failed for %s: %s", dest, e)
