"""
STT Provider — FasterWhisper with GPU acceleration.
"""
import logging
from faster_whisper import WhisperModel
from app.core.config import settings
from app.services.voice.interfaces import STTProvider

logger = logging.getLogger(__name__)


class FasterWhisperSTT(STTProvider):
    def __init__(self):
        logger.info(f"Loading Whisper model: {settings.WHISPER_MODEL_SIZE} on {settings.DEVICE}")
        self.model = WhisperModel(
            settings.WHISPER_MODEL_SIZE,
            device=settings.DEVICE,
            compute_type=settings.COMPUTE_TYPE,
        )
        logger.info("Whisper model loaded.")

    def transcribe(self, audio_source) -> str:
        """Transcribe audio. Returns empty string on failure or hallucination."""
        try:
            segments, info = self.model.transcribe(
                audio_source,
                beam_size=5,
                language="en",
                vad_filter=True,
            )

            if info.language_probability < 0.5:
                return ""

            texts = [s.text for s in segments if s.no_speech_prob < 0.6]
            return " ".join(texts).strip()
        except Exception as e:
            logger.error(f"Transcription error: {e}")
            return ""
