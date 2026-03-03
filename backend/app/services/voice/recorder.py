"""
Conversation Recorder
Records full conversations (user audio + agent audio) to WAV files.
Saves to Multi_Agent_MAF_Handoff_new/recordings/ with numbered filenames.
"""
import os
import struct
import time
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Recordings folder — outside the backend directory
RECORDINGS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "recordings"


class ConversationRecorder:
    """Records a single conversation session to a WAV file."""
    
    # Audio params
    USER_SAMPLE_RATE = 16000    # STT input rate
    AGENT_SAMPLE_RATE = 24000   # TTS output rate
    TARGET_SAMPLE_RATE = 24000  # Final file rate
    CHANNELS = 1
    SAMPLE_WIDTH = 2  # 16-bit

    def __init__(self):
        RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
        
        self._audio_segments: list = []  # List of (pcm_bytes, sample_rate, label)
        self._session_start = datetime.now()
        self._filename = self._generate_filename()
        
        logger.info(f"Conversation recorder initialized: {self._filename}")
    
    def _generate_filename(self) -> str:
        """Generate filename: {number}_{datetime}.wav"""
        # Count existing recordings
        existing = list(RECORDINGS_DIR.glob("*.wav"))
        next_num = len(existing) + 1
        
        dt_str = self._session_start.strftime("%Y-%m-%d_%H-%M-%S")
        return f"{next_num:03d}_{dt_str}.wav"
    
    def add_user_audio(self, pcm_data: bytes):
        """Add user's speech audio (16kHz PCM16)."""
        if pcm_data:
            self._audio_segments.append((pcm_data, self.USER_SAMPLE_RATE, "user"))
            logger.debug(f"Recorded user audio: {len(pcm_data)} bytes")
    
    def add_agent_audio(self, pcm_data: bytes):
        """Add agent's TTS audio (24kHz PCM16)."""
        if pcm_data:
            self._audio_segments.append((pcm_data, self.AGENT_SAMPLE_RATE, "agent"))
            logger.debug(f"Recorded agent audio: {len(pcm_data)} bytes")
    
    def add_silence(self, duration_ms: int = 500):
        """Add silence gap between turns."""
        samples = int(self.TARGET_SAMPLE_RATE * duration_ms / 1000)
        silence = b'\x00\x00' * samples
        self._audio_segments.append((silence, self.TARGET_SAMPLE_RATE, "silence"))
    
    @staticmethod
    def _resample_pcm(pcm_data: bytes, from_rate: int, to_rate: int) -> bytes:
        """Simple resample by linear interpolation (16-bit PCM)."""
        if from_rate == to_rate:
            return pcm_data
        
        import numpy as np
        
        samples = np.frombuffer(pcm_data, dtype=np.int16).astype(np.float32)
        
        # Calculate new length
        ratio = to_rate / from_rate
        new_length = int(len(samples) * ratio)
        
        # Linear interpolation
        old_indices = np.arange(len(samples))
        new_indices = np.linspace(0, len(samples) - 1, new_length)
        resampled = np.interp(new_indices, old_indices, samples)
        
        return resampled.astype(np.int16).tobytes()
    
    def save(self) -> Optional[str]:
        """Save the recorded conversation to a WAV file. Returns the filepath."""
        if not self._audio_segments:
            logger.warning("No audio to save.")
            return None
        
        # Combine all segments at target sample rate
        combined = b""
        for pcm_data, rate, label in self._audio_segments:
            resampled = self._resample_pcm(pcm_data, rate, self.TARGET_SAMPLE_RATE)
            combined += resampled
        
        if not combined:
            return None
        
        # Build WAV
        filepath = RECORDINGS_DIR / self._filename
        data_size = len(combined)
        
        header = struct.pack(
            '<4sI4s4sIHHIIHH4sI',
            b'RIFF',
            36 + data_size,
            b'WAVE',
            b'fmt ',
            16,
            1,  # PCM
            self.CHANNELS,
            self.TARGET_SAMPLE_RATE,
            self.TARGET_SAMPLE_RATE * self.CHANNELS * self.SAMPLE_WIDTH,
            self.CHANNELS * self.SAMPLE_WIDTH,
            self.SAMPLE_WIDTH * 8,
            b'data',
            data_size
        )
        
        with open(filepath, 'wb') as f:
            f.write(header + combined)
        
        duration = data_size / (self.TARGET_SAMPLE_RATE * self.CHANNELS * self.SAMPLE_WIDTH)
        logger.info(f"💾 Conversation saved: {filepath} ({duration:.1f}s, {len(self._audio_segments)} segments)")
        
        return str(filepath)
