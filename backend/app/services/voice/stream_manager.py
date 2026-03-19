"""
Stream Manager — Real-time audio buffering, VAD, turn detection, and barge-in.
"""
import logging
import struct
import time
import numpy as np
from typing import Optional, List, Dict, Any, AsyncGenerator

from app.services.voice.factory import VoiceFactory
from app.services.voice_orchestrator import get_voice_orchestrator
from app.services.voice.recorder import ConversationRecorder

logger = logging.getLogger(__name__)


class StreamManager:
    def __init__(self):
        self.vad = VoiceFactory.get_vad_provider()
        self.orchestrator = get_voice_orchestrator()

        self.buffer: List[bytes] = []
        self.sample_rate = 16000
        self.is_speaking = False
        self.silence_frames = 0
        self.speech_frames = 0

        # VAD thresholds
        self.SILENCE_THRESHOLD = 40       # ~1.3s silence to end turn (tolerates natural pauses)
        self.MIN_SPEECH_FRAMES = 5        # ~160ms min speech (filters out noise, still captures "yes", "no")

        # Post-turn cooldown: ignore speech for N seconds after a response completes
        self._cooldown_until = 0.0
        self.POST_TURN_COOLDOWN = 2.0     # 2 seconds cooldown after each turn

        # Barge-in state
        self._cancelled = False
        self._is_responding = False
        self.was_interrupted = False
        self._turn_just_completed = False

        # Sliding window barge-in (tolerates natural syllable gaps)
        self._barge_in_window = []
        self.BARGE_IN_WINDOW_SIZE = 12    # Last 12 frames (~384ms)
        self.BARGE_IN_SPEECH_REQUIRED = 6 # 6+ speech frames to trigger

        # Client playback timing estimation
        self._total_audio_bytes_sent = 0
        self._playback_end_time = 0.0
        self.TTS_SAMPLE_RATE = 24000
        self.TTS_SAMPLE_WIDTH = 2

        self.recorder = ConversationRecorder()

    @property
    def is_audio_playing_on_client(self) -> bool:
        # Only allow barge-in if we've actually sent audio and haven't reached its estimated end time
        return time.time() < self._playback_end_time

    def check_barge_in_vad(self, chunk: bytes) -> bool:
        """Sliding window barge-in: triggers when 6+ of last 12 frames are speech with RMS >= 500."""
        if not self.is_audio_playing_on_client:
            return False

        try:
            audio_int16 = np.frombuffer(chunk, dtype=np.int16)
            audio_float32 = audio_int16.astype(np.float32) / 32768.0

            rms = np.sqrt(np.mean(audio_int16.astype(np.float32)**2))
            if rms < 500:
                self._barge_in_window.append(False)
                if len(self._barge_in_window) > self.BARGE_IN_WINDOW_SIZE:
                    self._barge_in_window.pop(0)
                return False

            is_speech = self.vad.is_speech_now(audio_float32, self.sample_rate)
            self._barge_in_window.append(is_speech)
            if len(self._barge_in_window) > self.BARGE_IN_WINDOW_SIZE:
                self._barge_in_window.pop(0)

            speech_count = sum(self._barge_in_window)

            if speech_count >= self.BARGE_IN_SPEECH_REQUIRED:
                logger.info(f"Barge-in triggered ({speech_count} speech frames in window)")
                self._barge_in_window.clear()
                self.cancel_current_response()
                return True

        except Exception as e:
            logger.error(f"Barge-in VAD error: {e}")

        return False

    def cancel_current_response(self):
        """Cancel ongoing TTS on barge-in."""
        if self._is_responding or self.is_audio_playing_on_client:
            self._cancelled = True
            self.was_interrupted = True
            self._playback_end_time = 0.0
            self._cooldown_until = 0.0  # Immediately start listening to capture what they interrupted with

    def is_cancelled(self) -> bool:
        return self._cancelled

    def save_recording(self) -> Optional[str]:
        return self.recorder.save()

    @staticmethod
    def _build_wav(pcm_data: bytes, sample_rate: int = 16000, channels: int = 1, sample_width: int = 2) -> bytes:
        """Wrap raw PCM bytes in a WAV header."""
        data_size = len(pcm_data)
        header = struct.pack(
            '<4sI4s4sIHHIIHH4sI',
            b'RIFF', 36 + data_size, b'WAVE', b'fmt ', 16, 1,
            channels, sample_rate, sample_rate * channels * sample_width,
            channels * sample_width, sample_width * 8, b'data', data_size
        )
        return header + pcm_data

    async def process_chunk(self, chunk: bytes) -> AsyncGenerator[Dict[str, Any], None]:
        """Process audio chunk. Yields events when a turn completes."""
        # During cooldown period, skip VAD entirely to prevent phantom turns
        if time.time() < self._cooldown_until:
            return

        self.buffer.append(chunk)

        try:
            audio_int16 = np.frombuffer(chunk, dtype=np.int16)
            audio_float32 = audio_int16.astype(np.float32) / 32768.0
            is_speech = self.vad.is_speech_now(audio_float32, self.sample_rate)

            if is_speech:
                if not self.is_speaking:
                    self.is_speaking = True
                self.silence_frames = 0
                self.speech_frames += 1
            else:
                if self.is_speaking:
                    self.silence_frames += 1

                    if self.silence_frames > self.SILENCE_THRESHOLD:
                        # End of turn
                        self.is_speaking = False
                        self.silence_frames = 0

                        if self.speech_frames < self.MIN_SPEECH_FRAMES:
                            logger.debug(f"Discarding speech: only {self.speech_frames} frames (min: {self.MIN_SPEECH_FRAMES})")
                            self.buffer = []
                            self.speech_frames = 0
                            return

                        self.speech_frames = 0
                        self._cancelled = False
                        self._is_responding = True
                        self._total_audio_bytes_sent = 0

                        full_audio_pcm = b"".join(self.buffer)
                        self.buffer = []
                        self.recorder.add_user_audio(full_audio_pcm)
                        full_audio_wav = self._build_wav(full_audio_pcm, self.sample_rate)

                        yield {"type": "status", "content": "processing"}

                        was_interrupted = self.was_interrupted
                        self.was_interrupted = False
                        try:
                            async for event in self.orchestrator.process_voice_turn_streaming(
                                full_audio_wav, was_interrupted=was_interrupted
                            ):
                                if self._cancelled:
                                    yield {"type": "status", "content": "interrupted"}
                                    yield {"type": "status", "content": "listening"}
                                    break

                                evt_type = event.get("type")
                                
                                # Intercept and record textual transcripts
                                if evt_type == "transcript" and event.get("role") == "user":
                                    self.recorder.add_transcript("User", event["content"])
                                elif evt_type == "text":
                                    self.recorder.add_transcript(event.get("agent", "Agent"), event["content"])
                                    
                                if evt_type == "status" and event.get("content") == "silent":
                                    yield {"type": "status", "content": "listening"}
                                    break
                                elif evt_type == "audio" and not self._cancelled:
                                    audio_bytes = event["content"]
                                    self._total_audio_bytes_sent += len(audio_bytes)
                                    self.recorder.add_agent_audio(audio_bytes)
                                    
                                    # Extend playback end time as we send chunks so barge-in knows we are playing
                                    playback_secs = len(audio_bytes) / (self.TTS_SAMPLE_RATE * self.TTS_SAMPLE_WIDTH)
                                    now = time.time()
                                    if self._playback_end_time < now:
                                        self._playback_end_time = now + playback_secs
                                    else:
                                        # Add to existing queue time
                                        self._playback_end_time += playback_secs
                                        
                                    yield {"type": "audio", "content": audio_bytes}
                                else:
                                    yield event
                        finally:
                            self._is_responding = False
                            self._cancelled = False
                            self.recorder.add_silence(500)
                            # Drain stale buffered audio to prevent phantom second turn
                            self.buffer = []
                            self.speech_frames = 0
                            self.silence_frames = 0
                            self.is_speaking = False
                            self._turn_just_completed = True
                            # Start cooldown to ignore noise/echo after response
                            self._cooldown_until = time.time() + self.POST_TURN_COOLDOWN

        except Exception as e:
            logger.error(f"Error processing chunk: {e}", exc_info=True)
            self._is_responding = False
