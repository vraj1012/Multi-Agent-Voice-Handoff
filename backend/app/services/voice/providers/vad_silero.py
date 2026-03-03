"""
VAD Provider — Silero VAD (local, PyTorch).
"""
import torch
import logging
import numpy as np
from app.services.voice.interfaces import VADProvider

logger = logging.getLogger(__name__)


class SileroVAD(VADProvider):
    def __init__(self):
        logger.info("Loading Silero VAD model...")
        self.model, utils = torch.hub.load(
            repo_or_dir='snakers4/silero-vad',
            model='silero_vad',
            force_reload=False,
            trust_repo=True,
            verbose=False,
        )
        self.get_speech_timestamps, self.save_audio, self.read_audio, self.VADIterator, self.collect_chunks = utils
        self.model.eval()
        logger.info("Silero VAD loaded.")

    def detect_speech_segments(self, audio_path: str, sampling_rate: int = 16000):
        """Returns speech timestamps as list of {start, end} in samples."""
        try:
            wav = self.read_audio(audio_path, sampling_rate=sampling_rate)
            return self.get_speech_timestamps(wav, self.model, sampling_rate=sampling_rate)
        except Exception as e:
            logger.error(f"Speech detection error: {e}")
            return []

    def is_speech_now(self, audio_chunk: np.ndarray, sampling_rate: int = 16000) -> bool:
        """Real-time speech check on a single audio chunk (float32 numpy)."""
        try:
            tensor = torch.from_numpy(audio_chunk) if isinstance(audio_chunk, np.ndarray) else audio_chunk
            if len(tensor.shape) == 1:
                tensor = tensor.unsqueeze(0)

            window_size = 512 if sampling_rate == 16000 else 256
            if tensor.shape[-1] < window_size:
                return False

            probs = []
            for i in range(0, tensor.shape[-1], window_size):
                end = i + window_size
                if end > tensor.shape[-1]:
                    break
                probs.append(self.model(tensor[..., i:end], sampling_rate).item())

            return max(probs) > 0.5 if probs else False
        except Exception as e:
            logger.error(f"VAD error: {e}")
            return False
