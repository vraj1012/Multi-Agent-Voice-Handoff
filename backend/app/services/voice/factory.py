"""
Voice Factory — Loads the active STT/TTS/VAD providers based on configuration.
"""
from typing import Optional
import logging

from app.core.config import settings
from app.services.voice.interfaces import STTProvider, TTSProvider, VADProvider

from typing import Optional
import logging

from app.core.config import settings
from app.services.voice.interfaces import STTProvider, TTSProvider, VADProvider

logger = logging.getLogger(__name__)

class VoiceFactory:
    _stt_instance: Optional[STTProvider] = None
    _tts_instance: Optional[TTSProvider] = None
    _vad_instance: Optional[VADProvider] = None

    @classmethod
    def get_stt_provider(cls) -> STTProvider:
        if cls._stt_instance is None:
            # Lazy import
            from app.services.voice.providers.stt_whisper import FasterWhisperSTT
            logger.info("Loading Local FasterWhisper STT provider...")
            cls._stt_instance = FasterWhisperSTT()
        return cls._stt_instance

    @classmethod
    def get_tts_provider(cls) -> TTSProvider:
        if cls._tts_instance is None:
            # Lazy import
            from app.services.voice.providers.tts_vibevoice import VibeVoiceTTS
            logger.info("Loading Local VibeVoice TTS provider...")
            cls._tts_instance = VibeVoiceTTS()
        return cls._tts_instance

    @classmethod
    def get_vad_provider(cls) -> VADProvider:
        if cls._vad_instance is None:
            # Lazy import
            from app.services.voice.providers.vad_silero import SileroVAD
            logger.info("Loading Local Silero VAD provider...")
            cls._vad_instance = SileroVAD()
        return cls._vad_instance
