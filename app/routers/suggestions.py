from fastapi import APIRouter, BackgroundTasks, HTTPException, Depends
from fastapi.responses import JSONResponse
from app.utils import get_cache
from app.tasks.suggestions import create_suggestions
from helpers.utils import get_logger
from app.models.requests import SuggestionsRequest
from app.models.responses import SuggestionsResponse
from typing import Optional
from app.auth.jwt_auth import get_current_user

logger = get_logger(__name__)

router = APIRouter(prefix="/suggest", tags=["suggest"])

@router.post("/", response_model=SuggestionsResponse)
async def suggest(request: SuggestionsRequest, background_tasks: BackgroundTasks, current_user: str = Depends(get_current_user)):
    """Get suggestions for a chat session. If not available, trigger generation."""
    
    logger.info(f"Getting suggestions for session {request.session_id} in language {request.target_lang}")
    
    suggestions = await get_cache(f"suggestions_{request.session_id}_{request.target_lang}")
    
    if not suggestions:
        logger.info(f"No cached suggestions found, triggering background generation")
        background_tasks.add_task(create_suggestions, request.session_id, request.target_lang)
        suggestions = []
    
    return SuggestionsResponse(
        status='success',
        suggestions=suggestions,
        session_id=request.session_id
    )