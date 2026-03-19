"""VAD Provider — TEN VAD (lightweight, C-native via ten_vad)."""
import logging
import numpy as np
from typing import List, Dict
from ten_vad import TenVad
from app.services.voice.interfaces import VADProvider

logger = logging.getLogger(__name__)


class TenVAD(VADProvider):
    def __init__(self, hop_size: int = 256, threshold: float = 0.5):
        """
        Args:
            hop_size: Frame size in samples — 160 (10ms) or 256 (16ms) at 16kHz.
            threshold: Speech probability threshold (0.0–1.0).
        """
        logger.info("Loading TEN VAD model (hop_size=%d)...", hop_size)
        self.hop_size = hop_size
        self.threshold = threshold
        self.vad = TenVad(hop_size=hop_size)
        logger.info("TEN VAD loaded.")

    @staticmethod
    def _to_int16(audio: np.ndarray) -> np.ndarray:
        """Convert float32 [-1,1] audio to int16 as required by TEN VAD."""
        if audio.dtype == np.int16:
            return audio
        return np.clip(audio * 32767, -32768, 32767).astype(np.int16)

    def detect_speech_segments(self, audio_path: str, sampling_rate: int = 16000) -> List[Dict[str, int]]:
        """Detect speech segments in an audio file.
        Returns list of dicts with 'start' and 'end' timestamps (in samples).
        """
        try:
            import wave
            import struct

            with wave.open(audio_path, "rb") as wf:
                n_channels = wf.getnchannels()
                sample_width = wf.getsampwidth()
                frame_rate = wf.getframerate()
                n_frames = wf.getnframes()
                raw = wf.readframes(n_frames)

            # Convert to float32
            if sample_width == 2:
                fmt = f"<{n_frames * n_channels}h"
                samples = np.array(struct.unpack(fmt, raw), dtype=np.float32) / 32768.0
            else:
                samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0

            if n_channels > 1:
                samples = samples.reshape(-1, n_channels).mean(axis=1)

        except Exception as e:
            logger.error(f"Error reading audio file: {e}")
            return []

        # Convert to int16 for TEN VAD
        audio_i16 = self._to_int16(samples)
        segments = []
        in_speech = False
        seg_start = 0

        for i in range(0, len(audio_i16), self.hop_size):
            end = i + self.hop_size
            if end > len(audio_i16):
                break
            frame = audio_i16[i:end]
            prob, flags = self.vad.process(frame)

            if prob >= self.threshold and not in_speech:
                in_speech = True
                seg_start = i
            elif prob < self.threshold and in_speech:
                in_speech = False
                segments.append({"start": seg_start, "end": i})

        if in_speech:
            segments.append({"start": seg_start, "end": len(audio_i16)})

        return segments

    def is_speech_now(self, audio_chunk: np.ndarray, sampling_rate: int = 16000) -> bool:
        """Real-time check if the current audio chunk contains speech."""
        try:
            chunk_i16 = self._to_int16(audio_chunk)
            probs = []

            for i in range(0, len(chunk_i16), self.hop_size):
                end = i + self.hop_size
                if end > len(chunk_i16):
                    break
                frame = chunk_i16[i:end]
                prob, flags = self.vad.process(frame)
                probs.append(prob)

            return max(probs) > self.threshold if probs else False
        except Exception as e:
            logger.error(f"VAD error: {e}")
            return False
