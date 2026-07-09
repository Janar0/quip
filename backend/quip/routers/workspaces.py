from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from quip.database import get_db
from quip.models.chat import Chat
from quip.models.file import File
from quip.models.user import User
from quip.models.workspace import Workspace, WorkspaceMember
from quip.schemas.chat import ChatResponse
from quip.schemas.workspace import (
    WorkspaceCreate,
    WorkspaceFileResponse,
    WorkspaceResponse,
    WorkspaceUpdate,
)
from quip.services.permissions import get_current_user
from quip.services.workspaces import (
    ensure_personal_workspace,
    get_workspace_for_user,
    require_workspace_owner,
)

router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])


@router.get("", response_model=list[WorkspaceResponse])
async def list_workspaces(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await ensure_personal_workspace(user, db)
    await db.commit()
    result = await db.execute(
        select(Workspace)
        .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
        .where(WorkspaceMember.user_id == user.id)
        .order_by(Workspace.is_personal.desc(), Workspace.updated_at.desc())
    )
    return result.scalars().all()


@router.post("", response_model=WorkspaceResponse, status_code=status.HTTP_201_CREATED)
async def create_workspace(
    data: WorkspaceCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    workspace = Workspace(owner_id=user.id, is_personal=False, **data.model_dump())
    db.add(workspace)
    await db.flush()
    db.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role="owner"))
    await db.commit()
    await db.refresh(workspace)
    return workspace


@router.get("/{workspace_id}", response_model=WorkspaceResponse)
async def get_workspace(
    workspace_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await get_workspace_for_user(workspace_id, user.id, db)


@router.patch("/{workspace_id}", response_model=WorkspaceResponse)
async def update_workspace(
    workspace_id: UUID,
    data: WorkspaceUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    workspace = await require_workspace_owner(workspace_id, user.id, db)
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(workspace, key, value)
    await db.commit()
    await db.refresh(workspace)
    return workspace


@router.delete("/{workspace_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workspace(
    workspace_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    workspace = await require_workspace_owner(workspace_id, user.id, db)
    if workspace.is_personal:
        raise HTTPException(status_code=400, detail="The personal workspace cannot be deleted")
    personal = await ensure_personal_workspace(user, db)
    await db.execute(update(Chat).where(Chat.workspace_id == workspace.id).values(workspace_id=personal.id))
    await db.execute(update(File).where(File.workspace_id == workspace.id).values(workspace_id=personal.id))
    await db.execute(delete(WorkspaceMember).where(WorkspaceMember.workspace_id == workspace.id))
    await db.delete(workspace)
    await db.commit()


@router.get("/{workspace_id}/overview")
async def workspace_overview(
    workspace_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    chat_limit: int = Query(default=12, ge=1, le=50),
    file_limit: int = Query(default=20, ge=1, le=100),
):
    workspace = await get_workspace_for_user(workspace_id, user.id, db)
    chats = await db.execute(
        select(Chat)
        .where(
            Chat.workspace_id == workspace.id,
            Chat.user_id == user.id,
            Chat.archived.is_(False),
        )
        .order_by(Chat.updated_at.desc())
        .limit(chat_limit)
    )
    files = await db.execute(
        select(File)
        .where(File.workspace_id == workspace.id, File.user_id == user.id)
        .order_by(File.created_at.desc())
        .limit(file_limit)
    )
    return {
        "workspace": WorkspaceResponse.model_validate(workspace),
        "chats": [ChatResponse.model_validate(chat) for chat in chats.scalars().all()],
        "files": [WorkspaceFileResponse.model_validate(file) for file in files.scalars().all()],
    }
