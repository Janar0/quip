from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from quip.models.chat import Chat
from quip.models.file import File
from quip.models.user import User
from quip.models.workspace import Workspace, WorkspaceMember


async def ensure_personal_workspace(user: User, db: AsyncSession) -> Workspace:
    """Return the user's personal workspace and adopt pre-workspace data."""
    result = await db.execute(
        select(Workspace)
        .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
        .where(
            WorkspaceMember.user_id == user.id,
            Workspace.is_personal.is_(True),
        )
        .limit(1)
    )
    workspace = result.scalar_one_or_none()
    if workspace is None:
        workspace = Workspace(
            owner_id=user.id,
            name="Personal",
            description="Your chats, files, and generated artifacts.",
            is_personal=True,
        )
        db.add(workspace)
        await db.flush()
        db.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role="owner"))
        await db.flush()

    await db.execute(
        update(Chat)
        .where(Chat.user_id == user.id, Chat.workspace_id.is_(None))
        .values(workspace_id=workspace.id)
    )
    await db.execute(
        update(File)
        .where(File.user_id == user.id, File.workspace_id.is_(None))
        .values(workspace_id=workspace.id)
    )
    return workspace


async def get_workspace_for_user(
    workspace_id: UUID,
    user_id: UUID,
    db: AsyncSession,
) -> Workspace:
    result = await db.execute(
        select(Workspace)
        .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
        .where(Workspace.id == workspace_id, WorkspaceMember.user_id == user_id)
    )
    workspace = result.scalar_one_or_none()
    if workspace is None:
        # Deliberately do not reveal whether another tenant owns this ID.
        raise HTTPException(status_code=404, detail="Workspace not found")
    return workspace


async def require_workspace_owner(
    workspace_id: UUID,
    user_id: UUID,
    db: AsyncSession,
) -> Workspace:
    workspace = await get_workspace_for_user(workspace_id, user_id, db)
    if workspace.owner_id != user_id:
        raise HTTPException(status_code=403, detail="Workspace owner access required")
    return workspace
