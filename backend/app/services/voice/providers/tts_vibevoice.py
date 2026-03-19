"""TTS Provider — VibeVoice (local, CUDA/CPU)."""
import os
import sys
import copy
import torch
import logging
import threading
import numpy as np
from pathlib import Path
from typing import Optional, Dict, Any

# Add VibeVoice to path (4 levels up from this file)
_BACKEND_DIR = Path(__file__).resolve().parents[4]
VIBEVOICE_PATH = str(_BACKEND_DIR / "vibevoice_model" / "VibeVoice")
sys.path.append(VIBEVOICE_PATH)

try:
    from vibevoice.modular.modeling_vibevoice_streaming_inference import (
        VibeVoiceStreamingForConditionalGenerationInference,
    )
    from vibevoice.processor.vibevoice_streaming_processor import VibeVoiceStreamingProcessor
    from vibevoice.modular.streamer import AudioStreamer
except ImportError:
    pass

from app.core.config import settings
from app.services.voice.interfaces import TTSProvider

logger = logging.getLogger(__name__)


class VibeVoiceTTS(TTSProvider):
    def __init__(self):
        self.model_path = settings.TTS_MODEL_PATH
        self.device = settings.DEVICE
        self.sample_rate = 24000
        self.inference_steps = 4

        self.processor: Optional[VibeVoiceStreamingProcessor] = None
        self.model: Optional[VibeVoiceStreamingForConditionalGenerationInference] = None
        self.voice_presets: Dict[str, Path] = {}
        self.default_voice_key: Optional[str] = None
        self._voice_cache = {}

        self._load_model()
        self._load_voices()

    def _load_model(self):
        logger.info(f"Loading VibeVoice from {self.model_path} on {self.device}")
        load_dtype = torch.bfloat16 if self.device == "cuda" else torch.float32
        attn_primary = "flash_attention_2" if self.device == "cuda" else "sdpa"

        self.processor = VibeVoiceStreamingProcessor.from_pretrained(self.model_path)

        try:
            self.model = VibeVoiceStreamingForConditionalGenerationInference.from_pretrained(
                self.model_path, torch_dtype=load_dtype,
                device_map=self.device, attn_implementation=attn_primary,
            )
        except Exception as e:
            if attn_primary == 'flash_attention_2':
                logger.info(f"flash_attention_2 unavailable, falling back to sdpa")
                self.model = VibeVoiceStreamingForConditionalGenerationInference.from_pretrained(
                    self.model_path, torch_dtype=load_dtype,
                    device_map=self.device, attn_implementation='sdpa',
                )
            else:
                raise

        self.model.eval()
        self.model.set_ddpm_inference_steps(num_steps=self.inference_steps)
        logger.info("VibeVoice loaded.")
        
        # --- WARMUP ---
        # The first PyTorch CUDA forward pass allocates memory and sets up CuDNN,
        # which takes ~20-30 seconds. We do a dummy pass here so it happens during
        # server startup instead of blocking the user's first interaction.
        if self.device == "cuda":
            logger.info("Warming up VibeVoice CUDA graph (this may take 20-30s)...")
            try:
                dummy_text = "Warmup."
                processed = self.processor(
                    text=dummy_text, return_tensors="pt", padding=True, return_attention_mask=True
                )
                inputs = {k: v.to(self.device) if hasattr(v, "to") else v for k, v in processed.items()}
                # Run a tiny generation step
                self.model.generate(
                    **inputs, max_new_tokens=10, 
                    tokenizer=self.processor.tokenizer,
                    generation_config={"do_sample": False, "temperature": 1.0, "top_p": 1.0},
                    verbose=False
                )
                logger.info("VibeVoice CUDA warmup complete.")
            except Exception as e:
                logger.warning(f"VibeVoice warmup failed (will try again on first request): {e}")

    def _load_voices(self):
        voices_dir = _BACKEND_DIR / "vibevoice_model" / "VibeVoice" / "demo" / "voices" / "streaming_model"
        if not voices_dir.exists():
            logger.warning(f"Voices directory not found: {voices_dir}")
            return

        for pt_path in voices_dir.rglob("*.pt"):
            self.voice_presets[pt_path.stem] = pt_path

        if self.voice_presets:
            self.default_voice_key = next(iter(self.voice_presets))
            logger.info(f"Loaded {len(self.voice_presets)} voices. Default: {self.default_voice_key}")

    def _ensure_voice_cached(self, key: str):
        if key not in self._voice_cache and key in self.voice_presets:
            self._voice_cache[key] = torch.load(
                self.voice_presets[key], map_location=torch.device(self.device), weights_only=False
            )
        return self._voice_cache.get(key)

    def get_available_voices(self) -> Dict[str, Any]:
        return {k: str(v) for k, v in self.voice_presets.items()}

    def synthesize(self, text: str, voice_key: str = None) -> bytes:
        if not text.strip() or not self.model:
            return b""

        voice_key = voice_key or self.default_voice_key
        prefilled = self._ensure_voice_cached(voice_key)
        if not prefilled:
            return b""

        processed = self.processor.process_input_with_cached_prompt(
            text=text.strip(), cached_prompt=prefilled,
            padding=True, return_tensors="pt", return_attention_mask=True,
        )
        inputs = {k: v.to(self.device) if hasattr(v, "to") else v for k, v in processed.items()}

        streamer = AudioStreamer(batch_size=1, stop_signal=None, timeout=None)
        stop_event = threading.Event()
        generated_audio = []

        def run_gen():
            try:
                self.model.generate(
                    **inputs, max_new_tokens=None, cfg_scale=1.5,
                    tokenizer=self.processor.tokenizer,
                    generation_config={"do_sample": False, "temperature": 1.0, "top_p": 1.0},
                    audio_streamer=streamer, stop_check_fn=stop_event.is_set,
                    verbose=False, refresh_negative=True,
                    all_prefilled_outputs=copy.deepcopy(prefilled),
                )
            except Exception as e:
                logger.error(f"TTS generation error: {e}")
                if self.device == "cuda":
                    streamer.end()
                    logger.error(f"TTS CUDA generation failed permanently. CPU fallback is disabled.")
                else:
                    streamer.end()

        t = threading.Thread(target=run_gen, daemon=True)
        t.start()

        try:
            for chunk in streamer.get_stream(0):
                chunk = chunk.detach().cpu().to(torch.float32).numpy() if torch.is_tensor(chunk) else np.asarray(chunk, dtype=np.float32)
                if chunk.ndim > 1:
                    chunk = chunk.reshape(-1)
                peak = np.max(np.abs(chunk)) if chunk.size else 0.0
                if peak > 1.0:
                    chunk = chunk / peak
                generated_audio.append(chunk)
        finally:
            stop_event.set()
            streamer.end()
            t.join()

        if not generated_audio:
            return b""

        pcm = (np.concatenate(generated_audio) * 32767.0).astype(np.int16)
        return pcm.tobytes()
