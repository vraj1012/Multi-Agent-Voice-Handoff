"""TTS Provider — Chatterbox TTS (local, CUDA/CPU) for voice cloning."""
import logging
import numpy as np
import torch
from pathlib import Path
from typing import Optional, Dict, Any, AsyncGenerator
import asyncio

from app.core.config import settings
from app.services.voice.interfaces import TTSProvider

logger = logging.getLogger(__name__)

# Voice prompt directory (contains per-agent .wav/.flac reference files)
# Path: providers/tts_chatterbox.py → providers/ → voice/ → services/ → app/ → agents/voices
_VOICES_DIR = Path(__file__).resolve().parents[3] / "agents" / "voices"


class ChatterboxTTSProvider(TTSProvider):
    def __init__(self):
        self.device = "cuda"  # Enforce GPU-only execution as requested
        self.sample_rate = 24000  # Chatterbox native output rate

        self.model = None
        self.voice_prompts: Dict[str, Path] = {}
        self.default_voice_key: Optional[str] = None

        self._load_model()
        self._load_voices()

    def _load_model(self):
        logger.info(f"Loading Chatterbox TTS on {self.device}...")
        from chatterbox.tts import ChatterboxTTS
        self.model = ChatterboxTTS.from_pretrained(self.device)
        self.sample_rate = self.model.sr
        logger.info(f"Chatterbox TTS loaded (sample_rate={self.sample_rate}).")

        # --- WARMUP ---
        # The first PyTorch CUDA forward pass allocates memory and sets up CuDNN,
        # which takes ~20-30 seconds. We do a dummy pass here so it happens during
        # server startup instead of blocking the user's first interaction.
        if self.device == "cuda":
            logger.info("Warming up Chatterbox CUDA graph (this may take 20-30s)...")
            try:
                # Run a dummy generation step
                self.model.generate(
                    text="Warmup.",
                    audio_prompt_path=None,
                    exaggeration=0.5,
                    cfg_weight=0.5,
                    temperature=0.8,
                )
                logger.info("Chatterbox CUDA warmup complete.")
            except Exception as e:
                logger.warning(f"Chatterbox warmup failed: {e}")

    def _load_voices(self):
        """Discover voice prompt audio files in the voices directory."""
        if not _VOICES_DIR.exists():
            logger.warning(f"Voices directory not found: {_VOICES_DIR}")
            return

        for audio_file in _VOICES_DIR.iterdir():
            if audio_file.suffix.lower() in (".wav", ".flac", ".mp3", ".ogg"):
                self.voice_prompts[audio_file.stem] = audio_file

        if self.voice_prompts:
            self.default_voice_key = next(iter(self.voice_prompts))
            logger.info(
                f"Loaded {len(self.voice_prompts)} voice prompts: "
                f"{list(self.voice_prompts.keys())}. Default: {self.default_voice_key}"
            )

    def get_available_voices(self) -> Dict[str, Any]:
        """Return a dictionary of available voice prompts."""
        return {k: str(v) for k, v in self.voice_prompts.items()}

    @staticmethod
    def _tensor_to_pcm(wav_tensor: Any) -> bytes:
        # Convert tensor to PCM int16 bytes
        if torch.is_tensor(wav_tensor):
            audio_np = wav_tensor.detach().cpu().to(torch.float32).numpy()
        else:
            audio_np = np.asarray(wav_tensor, dtype=np.float32)

        # Flatten to 1D
        if audio_np.ndim > 1:
            audio_np = audio_np.reshape(-1)

        # Normalize to avoid clipping
        peak = np.max(np.abs(audio_np)) if audio_np.size else 0.0
        if peak > 1.0:
            audio_np = audio_np / peak

        # Convert to int16 PCM
        pcm = (audio_np * 32767.0).astype(np.int16)
        return pcm.tobytes()

    def synthesize(self, text: str, voice_key: Optional[str] = None) -> bytes:
        """Synthesize text to audio using Chatterbox TTS."""
        if not text.strip() or not self.model:
            return b""

        # Resolve voice prompt path
        audio_prompt_path = None
        if voice_key and voice_key in self.voice_prompts:
            audio_prompt_path = str(self.voice_prompts[voice_key])
        elif self.default_voice_key and self.default_voice_key in self.voice_prompts:
            audio_prompt_path = str(self.voice_prompts[self.default_voice_key])

        try:
            # Generate audio tensor
            wav_tensor = self.model.generate(
                text=text.strip(),
                audio_prompt_path=audio_prompt_path,
                exaggeration=0.5,
                cfg_weight=0.5,
                temperature=0.8,
            )
            return self._tensor_to_pcm(wav_tensor)

        except Exception as e:
            logger.error(f"TTS generation error: {e}", exc_info=True)
            return b""

    async def synthesize_stream(self, text: str, voice_key: Optional[str] = None) -> AsyncGenerator[bytes, None]:
        """
        By user request, we bypass chunk-level streaming (which causes inner-sentence stitching jitter)
        in favor of sentence-level streaming. This yields the full sentence audio at once for gapless playback.
        """
        if not text.strip() or not self.model:
            return

        loop = asyncio.get_event_loop()
        import functools
        
        # Offload the synchronous whole-sentence generation to a thread
        audio_data = await loop.run_in_executor(
            None, 
            functools.partial(self.synthesize, text, voice_key=voice_key)
        )
        
        if audio_data:
            yield audio_data
