from fastapi import APIRouter, WebSocket, Depends
from app.services.pipeline import ConversationPipeline
from helpers.utils import get_logger
from app.auth.jwt_auth import get_current_user_ws

logger = get_logger(__name__)

router = APIRouter(prefix="/conv", tags=["conversation"])

@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, current_user: str = Depends(get_current_user_ws)):
    """
    WebSocket endpoint for voice conversation.
    
    Query Parameters:
        lang (str): Language code (en, am). Default: en
    """
    lang = websocket.query_params.get("lang", "en")
    logger.info(f"WebSocket connection request received with lang={lang}")
    
    pipeline = ConversationPipeline(websocket, lang=lang)
    await pipeline.run()

