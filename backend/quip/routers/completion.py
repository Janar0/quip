"""SSE streaming endpoint for chat completions — routes to OpenRouter or Ollama."""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from quip.database import get_db
from quip.models.user import User
from quip.schemas.chat import CompletionRequest, RegenerateRequest
from quip.services.permissions import get_current_user
from quip.services.completion import CompletionService

router = APIRouter(prefix="/api", tags=["completion"])


@router.post("/chat/completions")
async def chat_completion(
    req: CompletionRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await CompletionService.chat_completion(req, request, user, db)


@router.post("/chat/regenerate")
async def regenerate_message(
    req: RegenerateRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await CompletionService.regenerate(req, request, user, db)
