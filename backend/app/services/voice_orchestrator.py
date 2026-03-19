"""Voice Orchestrator — STT -> Agent Mesh -> TTS pipeline."""
import re
import io
import time
import asyncio
import logging
import functools
from typing import Dict, Any, Optional, List

from app.services.voice.factory import VoiceFactory
from app.services.orchestration import get_orchestration_service
from app.agents.registry import get_agent_voice_map, get_start_agent_name

logger = logging.getLogger(__name__)

# Farewell detection phrases
EXACT_FAREWELLS = {
    "bye", "goodbye", "good bye", "bye bye", "see you", "see ya",
    "take care", "thanks bye", "thank you bye", "ok bye", "okay bye",
    "that's all", "thats all", "that is all", "i'm done", "im done",
    "nothing else", "no more questions", "end call",
    "that's enough", "thats enough", "that is enough",
    "ok that's enough", "okay that's enough", "ok thats enough",
    "ok that's enough bye", "okay thats enough bye",
}
FAREWELL_PHRASES = [
    "bye", "goodbye", "good bye", "see you later", "see ya",
    "that's enough", "thats enough", "that is enough",
    "i have to go", "gotta go", "have a nice day",
    "have a good day", "talk to you later", "catch you later",
    "end the call", "hang up", "no more questions",
]
# Word-level keywords: if ANY of these appear as a word, it's a farewell
FAREWELL_KEYWORDS = {"bye", "goodbye", "farewell", "byebye"}

# Topic switch detection
EXPLICIT_SWITCHES = [
    "never mind", "forget that", "forget it",
    "change the topic", "different topic", "another topic",
    "switch to", "instead of",
]
INTERRUPT_WORDS = ["wait", "hold on", "stop"]
TOPIC_PHRASES = [
    "talk about", "tell me about", "explain",
    "what about", "let's discuss", "lets discuss",
]


class VoiceOrchestrator:
    def __init__(self):
        logger.info("Initializing Voice Orchestrator...")
        self.stt = VoiceFactory.get_stt_provider()
        self.tts = VoiceFactory.get_tts_provider()
        self.agent_service = get_orchestration_service()
        self.agent_service.reset()  # Reset global state for new call
        # Load voice mapping from registry — single source of truth
        self.agent_voices = get_agent_voice_map()
        logger.info(f"Voice Orchestrator initialized. Voices: {list(self.agent_voices.keys())}")

    # Batch processing (REST API)

    async def process_voice_turn(self, audio_data: bytes, filename: str = "input.wav") -> Dict[str, Any]:
        """Full voice turn: STT -> Agent -> TTS. Returns combined response."""
        start_time = time.time()

        audio_file = io.BytesIO(audio_data)
        audio_file.name = filename

        try:
            user_text = self.stt.transcribe(audio_file)
        except Exception as e:
            logger.error(f"STT error: {e}")
            return self._error_response("Sorry, I couldn't understand that.", start_time)

        if not user_text.strip():
            return {
                "text_response": "", "audio_response": b"", "agent_name": "System",
                "handoff_occurred": False, "messages": [],
                "time_taken": time.time() - start_time, "silent": True,
            }

        logger.info(f"User: {user_text}")

        try:
            agent_result = await self.agent_service.process_message(user_text)
        except Exception as e:
            logger.error(f"Agent error: {e}")
            return self._error_response("I'm having trouble right now.", start_time)

        agent_messages = agent_result.get("messages", [])
        handoff_occurred = agent_result.get("handoff_occurred", False)

        if handoff_occurred:
            agent_messages = self._ensure_handoff_bridge(agent_messages, agent_result)

        combined_audio = b""
        combined_text_parts = []
        final_agent = "System"

        for msg in agent_messages:
            agent_name, text = msg["agent"], msg["text"]
            if not text or not text.strip():
                continue
            text = self._truncate_for_voice(text)
            combined_text_parts.append(f"{agent_name}: {text}")
            final_agent = agent_name
            voice_key = self._get_voice_for_agent(agent_name)

            try:
                audio_bytes = self.tts.synthesize(text, voice_key=voice_key)
                if audio_bytes:
                    if combined_audio:
                        combined_audio += b'\x00\x00' * int(0.2 * 24000)
                    combined_audio += audio_bytes
            except Exception as e:
                logger.error(f"TTS error for {agent_name}: {e}")

        return {
            "text_response": " | ".join(combined_text_parts),
            "audio_response": combined_audio,
            "agent_name": final_agent,
            "handoff_occurred": handoff_occurred,
            "handoff_target": agent_result.get("handoff_target"),
            "messages": agent_messages,
            "time_taken": time.time() - start_time,
        }

    # Streaming processing (WebSocket)

    async def process_voice_turn_streaming(self, audio_data: bytes, filename: str = "input.wav", was_interrupted: bool = False):
        """Streaming voice turn: STT -> Agent -> sentence-level TTS chunks."""
        start_time = time.time()

        audio_file = io.BytesIO(audio_data)
        audio_file.name = filename

        try:
            loop = asyncio.get_event_loop()
            user_text = await loop.run_in_executor(None, self.stt.transcribe, audio_file)
        except Exception as e:
            logger.error(f"STT error: {e}")
            yield {"type": "text", "content": "Sorry, I couldn't understand that.", "agent": "System"}
            try:
                yield {"type": "audio", "content": self.tts.synthesize("Sorry, I couldn't understand that.")}
            except:
                pass
            return

        # Clean text
        user_text = user_text.strip()
        
        # Whisper Hallucination Filter
        clean_check = re.sub(r'[^a-zA-Z\s]', '', user_text).strip().lower()
        hallucinations = [
            "thank you", "thanks", "thank you for watching", "thanks for watching",
            "please subscribe", "subscribe", "bye", "you", "okay", "amem", "amen"
        ]
        if clean_check in hallucinations:
            logger.info(f"Filtered Whisper hallucination: '{user_text}'")
            user_text = ""

        if not user_text:
            yield {"type": "status", "content": "silent"}
            return

        logger.info(f"User: {user_text}")
        yield {"type": "transcript", "role": "user", "content": user_text}

        # Context tagging
        is_farewell = self._is_farewell(user_text)
        if is_farewell:
            user_text = (
                f"[FAREWELL: The user is saying goodbye. Give a warm, brief farewell (1 sentence). "
                f"Do NOT ask follow-up questions.]\n\n{user_text}"
            )

        current_agent = self.agent_service.active_agent_name
        is_topic_switch = self._is_topic_switch(user_text) and current_agent.lower() != get_start_agent_name().lower()
        if is_topic_switch and not is_farewell:
            logger.info(f"Topic switch detected (agent: {current_agent})")
            user_text = (
                f"[TOPIC SWITCH: The user wants to change the topic. "
                f"If the new topic is OUTSIDE your domain, use your handoff tools to connect them to the right expert. "
                f"If the new topic is WITHIN your domain, ask a confirmation question before answering. "
                f"Do NOT answer a new topic directly without confirming first.]\n\n{user_text}"
            )

        if was_interrupted:
            user_text = (
                f"[SYSTEM: The user just instantly interrupted you mid-sentence. "
                f"If they are attempting to switch to a new topic (like 'can we talk about cyber security'), you MUST NOT answer their question yet. "
                f"Instead, you MUST pause and ask them a follow-up question in this exact format: 'Do you want to switch the topic to [their new topic] or continue talking about [the topic you were just discussing]?' "
                f"If they are just asking for clarification on the current topic, simply answer them.]\n\n{user_text}"
            )

        # Agent processing
        try:
            agent_result = await self.agent_service.process_message(user_text)
        except Exception as e:
            logger.error(f"Agent error: {e}")
            yield {"type": "text", "content": "I'm having trouble right now.", "agent": "System"}
            try:
                yield {"type": "audio", "content": self.tts.synthesize("I'm having trouble right now.")}
            except:
                pass
            return

        agent_messages = agent_result.get("messages", [])
        handoff_occurred = agent_result.get("handoff_occurred", False)

        if handoff_occurred:
            agent_messages = self._ensure_handoff_bridge(agent_messages, agent_result)

        yield {
            "type": "metadata",
            "content": {
                "handoff": handoff_occurred,
                "handoff_target": agent_result.get("handoff_target"),
                "agent_count": len(agent_messages),
            }
        }

        # Stream TTS sentence-by-sentence
        for msg in agent_messages:
            agent_name, text = msg["agent"], msg["text"]
            if not text or not text.strip():
                continue

            text = self._sanitize_for_voice(text)
            text = self._truncate_for_voice(text)
            voice_key = self._get_voice_for_agent(agent_name)

            yield {
                "type": "text", "content": text, "agent": agent_name,
                "handoff": handoff_occurred,
                "handoff_target": agent_result.get("handoff_target"),
            }

            # Try true streaming first
            try:
                chunk_idx = 0
                audio_buffer = b""
                async for audio_bytes in self.tts.synthesize_stream(text.strip(), voice_key=voice_key):
                    if audio_bytes:
                        audio_buffer += audio_bytes
                        # Send when we have ~40ms of audio (24000 seq/sec * 2 bytes = 48000 bytes/sec)
                        if len(audio_buffer) >= 2000:
                            yield {"type": "audio", "content": audio_buffer, "agent": agent_name, "chunk": chunk_idx}
                            audio_buffer = b""
                            chunk_idx += 1
                
                # Yield remainder
                if audio_buffer:
                    yield {"type": "audio", "content": audio_buffer, "agent": agent_name, "chunk": chunk_idx}
            except NotImplementedError:
                # Fallback: Stream TTS sentence-by-sentence (low latency with CUDA)
                for i, sentence in enumerate(self._split_into_sentences(text)):
                    if not sentence.strip():
                        continue
                    try:
                        loop = asyncio.get_event_loop()
                        audio_bytes = await loop.run_in_executor(
                            None, functools.partial(self.tts.synthesize, sentence.strip(), voice_key=voice_key)
                        )
                        if audio_bytes:
                            yield {"type": "audio", "content": audio_bytes, "agent": agent_name, "chunk": i}
                    except Exception as e:
                        logger.error(f"TTS error for {agent_name} chunk {i}: {e}")
            except Exception as e:
                logger.error(f"TTS stream error for {agent_name}: {e}", exc_info=True)

        if is_farewell:
            yield {"type": "status", "content": "call_ended"}
        else:
            yield {"type": "status", "content": "listening"}
        logger.info(f"Voice turn complete in {time.time() - start_time:.2f}s")

    # Helper methods

    @staticmethod
    def _ensure_handoff_bridge(agent_messages, agent_result):
        """Inject source agent's bridge announcement if missing."""
        target = agent_result.get("handoff_target", "the expert")
        source = agent_result.get("handoff_source", get_start_agent_name())
        names = [m.get("agent", "").lower() for m in agent_messages]
        has_source = any(source.lower() in n for n in names)

        if not agent_messages:
            return [{"agent": source, "text": f"My friend {target} is an expert in this field. Let me connect you."}]
        elif not has_source:
            bridge = {"agent": source, "text": f"My friend {target} is an expert in this field. Let me connect you."}
            agent_messages.insert(0, bridge)
        return agent_messages

    @staticmethod
    def _is_farewell(text: str) -> bool:
        text_lower = text.lower().strip()
        # 1. Exact match
        if text_lower in EXACT_FAREWELLS:
            return True
        # 2. Phrase-level match
        if any(p in text_lower for p in FAREWELL_PHRASES):
            return True
        # 3. Word-level match — catches "ok thats enough bye" etc.
        words = set(re.split(r'\W+', text_lower))
        if words & FAREWELL_KEYWORDS:
            return True
        return False

    @staticmethod
    def _is_topic_switch(text: str) -> bool:
        """Detect unambiguous topic switches (not normal conversation starters)."""
        text_lower = text.lower().strip()
        if any(p in text_lower for p in EXPLICIT_SWITCHES):
            return True
        if any(w in text_lower for w in INTERRUPT_WORDS):
            return any(p in text_lower for p in TOPIC_PHRASES)
        return False

    @staticmethod
    def _sanitize_for_voice(text: str) -> str:
        """Strip formatting not suitable for spoken audio."""
        text = re.sub(r'(?m)^\s*\d+[.\)]\s*', '', text)
        text = re.sub(r'(?m)^\s*[-*•]\s*', '', text)
        text = re.sub(r'(?m)^\s*#{1,4}\s*', '', text)
        text = re.sub(r'\*{1,2}(.*?)\*{1,2}', r'\1', text)
        text = re.sub(r'_{1,2}(.*?)_{1,2}', r'\1', text)
        text = re.sub(r'\n+', ' ', text)
        text = re.sub(r'\s{2,}', ' ', text)
        return text.strip()

    @staticmethod
    def _split_into_sentences(text: str, min_words: int = 5) -> List[str]:
        """Split text into sentence chunks for streaming TTS."""
        raw_parts = re.split(r'(?<=[.!?])\s+', text.strip())
        if not raw_parts:
            return [text] if text.strip() else []

        sentences, current = [], ""
        for part in raw_parts:
            current = f"{current} {part}".strip() if current else part
            if len(current.split()) >= min_words:
                sentences.append(current)
                current = ""

        if current:
            if sentences:
                sentences[-1] += " " + current
            else:
                sentences.append(current)
        return sentences

    @staticmethod
    def _truncate_for_voice(text: str, max_chars: int = 300) -> str:
        """Truncate at last sentence boundary within limit."""
        if len(text) <= max_chars:
            return text
        truncated = text[:max_chars]
        for sep in ['. ', '! ', '? ']:
            last = truncated.rfind(sep)
            if last > 0:
                return truncated[:last + 1]
        last_space = truncated.rfind(' ')
        return truncated[:last_space] + '...' if last_space > 0 else truncated + '...'

    def _get_voice_for_agent(self, agent_name: str) -> Optional[str]:
        """Map agent name to TTS voice key from registry."""
        for name, key in self.agent_voices.items():
            if name.lower() in agent_name.lower():
                return key
        return None

    def _error_response(self, message: str, start_time: float) -> Dict[str, Any]:
        try:
            audio = self.tts.synthesize(message)
        except:
            audio = b""
        return {
            "text_response": message, "audio_response": audio,
            "agent_name": "System", "handoff_occurred": False,
            "messages": [{"agent": "System", "text": message}],
            "time_taken": time.time() - start_time,
        }


# Singleton
_voice_orchestrator = None

def get_voice_orchestrator():
    global _voice_orchestrator
    if _voice_orchestrator is None:
        _voice_orchestrator = VoiceOrchestrator()
    return _voice_orchestrator
