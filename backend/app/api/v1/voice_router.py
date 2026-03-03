"""
Voice Endpoints — API for voice interaction.
"""
import io
from typing import Any
from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from fastapi.responses import Response, JSONResponse

from app.services.voice.factory import VoiceFactory
from app.services.voice_orchestrator import get_voice_orchestrator, VoiceOrchestrator

router = APIRouter()

@router.post("/chat", summary="Voice Chat: Audio Input -> Audio + Text Output")
async def voice_chat(
    file: UploadFile = File(...),
    orchestrator: VoiceOrchestrator = Depends(get_voice_orchestrator)
):
    """
    Process uploaded audio file (WAV/MP3/M4A).
    Returns synthesized audio response (WAV) with JSON metadata in headers.
    
    Headers:
    - X-Agent-Name: Name of the responding agent
    - X-Response-Text: Transcribed text response (JSON encoded if complex)
    - X-Handoff: "true" or "false"
    """
    if not file:
        raise HTTPException(status_code=400, detail="No file uploaded")
        
    try:
        # Read audio file into memory
        audio_bytes = await file.read()
        
        # Process turn
        result = await orchestrator.process_voice_turn(audio_bytes, filename=file.filename)
        
        if "error" in result:
             # Just log error but return what we have (e.g. text fallback)
             pass
             
        # Return audio as the body
        # Metadata in headers for simple client consumption without multipart parsing
        headers = {
            "X-Agent-Name": result["agent_name"],
            "X-Response-Text": result["text_response"],  # Care with encoding non-ascii
            "X-Handoff": str(result["handoff_occurred"]).lower(),
            "X-Time-Taken": str(result["time_taken"])
        }
        
        if result.get("handoff_target"):
            headers["X-Handoff-Target"] = result["handoff_target"]
            
        return Response(
            content=result["audio_response"], 
            media_type="audio/wav",
            headers=headers
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/health", summary="Voice Service Health Check")
async def voice_health():
    """Verify STT/TTS/VAD models are loaded."""
    try:
        stt = VoiceFactory.get_stt_provider()
        tts = VoiceFactory.get_tts_provider()
        vad = VoiceFactory.get_vad_provider()
        return {
            "status": "ok", 
            "stt_provider": stt.__class__.__name__,
            "tts_provider": tts.__class__.__name__,
            "vad_provider": vad.__class__.__name__
        }
    except Exception as e:
         raise HTTPException(status_code=503, detail=f"Voice services unavailable: {e}")
