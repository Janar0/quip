"""Build message history for chat completions."""
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from quip.models.chat import Chat, Message
from quip.models.file import File

HISTORY_LIMIT = 100


class HistoryService:
    """Builds message history arrays for LLM API calls."""

    @staticmethod
    async def build_file_path_map(
        messages: list[Message], db: AsyncSession
    ) -> dict[str, str]:
        """Single batched query: resolve file storage_paths across all messages."""
        all_file_ids: set[UUID] = set()
        for m in messages:
            for a in (m.meta or {}).get("attachments", []):
                fid = a.get("file_id")
                if fid:
                    try:
                        all_file_ids.add(UUID(fid))
                    except (ValueError, TypeError):
                        pass
        if not all_file_ids:
            return {}
        result = await db.execute(
            select(File.id, File.storage_path).where(File.id.in_(all_file_ids))
        )
        return {str(fid): sp for fid, sp in result.all()}

    @staticmethod
    async def build(
        db: AsyncSession,
        chat: Chat,
        branch_from_message_id: UUID | None,
        user_msg: Message | None = None,
    ) -> tuple[list[Message], dict[str, str]]:
        """Return (ordered_messages, file_path_map).

        Strategy:
        - Branch edit (branch_from_message_id): walk ancestry chain from user_msg → root.
        - Normal flow: flat list, capped at HISTORY_LIMIT, ordered by created_at ascending.
        """
        if branch_from_message_id or user_msg:
            all_msgs_result = await db.execute(
                select(Message).where(Message.chat_id == chat.id)
            )
            id_to_msg = {m.id: m for m in all_msgs_result.scalars().all()}

            start = user_msg if user_msg else None
            if not start and branch_from_message_id:
                start = id_to_msg.get(branch_from_message_id)

            chain: list[Message] = []
            curr: Message | None = start
            while curr:
                chain.append(curr)
                curr = id_to_msg.get(curr.parent_id) if curr.parent_id else None
            chain.reverse()
            messages = chain
        else:
            msg_result = await db.execute(
                select(Message)
                .where(Message.chat_id == chat.id)
                .order_by(Message.created_at.desc())
                .limit(HISTORY_LIMIT)
            )
            messages = list(reversed(msg_result.scalars().all()))

        file_path_map = await HistoryService.build_file_path_map(messages, db)
        return messages, file_path_map

    @staticmethod
    async def build_for_regenerate(
        db: AsyncSession,
        chat: Chat,
        orig_msg: Message,
    ) -> tuple[list[Message], dict[str, str]]:
        """Walk ancestry from orig_msg.parent → root. Returns (chain, file_path_map)."""
        all_msgs_result = await db.execute(
            select(Message).where(Message.chat_id == chat.id)
        )
        id_to_msg = {m.id: m for m in all_msgs_result.scalars().all()}

        chain: list[Message] = []
        curr: Message | None = (
            id_to_msg.get(orig_msg.parent_id) if orig_msg.parent_id else None
        )
        while curr:
            chain.append(curr)
            curr = id_to_msg.get(curr.parent_id) if curr.parent_id else None
        chain.reverse()

        file_path_map = await HistoryService.build_file_path_map(chain, db)
        return chain, file_path_map
