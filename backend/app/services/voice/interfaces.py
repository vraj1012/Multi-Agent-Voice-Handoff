"""
Core interfaces for Voice Services.
This defines the contract that all STT, TTS, and VAD providers must implement.
"""
from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any, AsyncGenerator
import numpy as np

class STTProvider(ABC):
    """Abstract base class for Speech-to-Text providers."""
    
    @abstractmethod
    def transcribe(self, audio_source: Any) -> str:
        """
        Transcribe audio to text.
        Args:
            audio_source: File path, binary stream, or numpy array.
        Returns:
            Transcribed text string.
        """
        pass

class TTSProvider(ABC):
    """Abstract base class for Text-to-Speech providers."""
    
    @abstractmethod
    def synthesize(self, text: str, voice_key: Optional[str] = None) -> bytes:
        """
        Synthesize text to audio.
        Args:
            text: Text to speak.
            voice_key: Optional specific voice/speaker ID.
        Returns:
            Audio bytes (PCM WAV or similar format).
        """
        pass
        
    @abstractmethod
    def get_available_voices(self) -> Dict[str, Any]:
        """Return a dictionary of available voice presets."""
        pass

    async def synthesize_stream(self, text: str, voice_key: Optional[str] = None) -> AsyncGenerator[bytes, None]:
        """
        Synthesize text to audio in streaming chunks.
        Args:
            text: Text to speak.
            voice_key: Optional specific voice/speaker ID.
        Yields:
            Audio bytes (PCM WAV or similar format) in chunks.
        """
        raise NotImplementedError("This TTS provider does not support streaming synthesis.")

class VADProvider(ABC):
    """Abstract base class for Voice Activity Detection providers."""
    
    @abstractmethod
    def detect_speech_segments(self, audio_path: str, sampling_rate: int = 16000) -> List[Dict[str, int]]:
        """
        Detect speech segments in an audio file.
        Returns:
            List of dicts with 'start' and 'end' timestamps (in samples).
        """
        pass
        
    @abstractmethod
    def is_speech_now(self, audio_chunk: np.ndarray, sampling_rate: int = 16000) -> bool:
        """
        Real-time check if the current audio chunk contains speech.
        """
        pass
