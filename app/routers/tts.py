from helpers.tts import text_to_speech_bhashini
from helpers.utils import get_logger
import uuid
import base64
from fastapi import APIRouter, HTTPException, Depends
from app.models.requests import TTSRequest
from app.models.responses import TTSResponse
from app.auth.jwt_auth import get_current_user

logger = get_logger(__name__)

router = APIRouter(prefix="/tts", tags=["tts"])

@router.post("/", response_model=TTSResponse)
async def tts(request: TTSRequest, current_user: str = Depends(get_current_user)):
    """Handles text to speech conversion using Bhashini service."""
    
    if not request.text:
        raise HTTPException(status_code=400, detail="text is required")
    
    try:
        audio_data = text_to_speech_bhashini(request.text, request.lang_code, gender='female', sampling_rate=8000)
        
        # Base64 encode the binary audio data for JSON serialization
        if isinstance(audio_data, bytes):
            audio_data = base64.b64encode(audio_data).decode('utf-8')
        
        return TTSResponse(
            status='success',
            audio_content=audio_data,
            session_id=request.session_id or str(uuid.uuid4())
        )
    except Exception as e:
        logger.error(f"TTS error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"TTS failed: {str(e)}")
