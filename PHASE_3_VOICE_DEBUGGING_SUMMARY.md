# 🎙️ Phase 3: Voice Pipeline — Complete Feature Summary

This document covers all voice pipeline features implemented in Phase 3, including debugging, barge-in, topic switching, auto call termination, and conversation recording.

---

## 1. **Voice Pipeline Stability**
- **WAV Headers**: `_build_wav()` in `stream_manager.py` wraps raw PCM audio in valid WAV headers for FasterWhisper STT.
- **VAD Tuning (Noise Filtering)**:
  - Removed energy fallback in `vad_silero.py` to stop false triggers on background noise.
  - `MIN_SPEECH_FRAMES = 6` (~192ms) — captures short words like "yes", "no", "bye".
  - `SILENCE_THRESHOLD = 40` (~1.3s silence) for natural pauses.
- **Silent Response for Noise**: Returns `silent=True` when STT yields empty text, avoiding repeated "I didn't hear anything" responses.
- **STT Model**: Upgraded Whisper from `small` → `medium` for better transcription accuracy.

## 2. **Server-Side Barge-In Detection (VAD)**
- **Architecture**: Moved barge-in detection entirely to the server (`StreamManager.check_barge_in_vad()`).
- **Silero VAD + RMS**: Uses Silero VAD for speech detection + RMS ≥ 500 minimum volume filter to block speaker echo and distant voices.
- **Sliding Window**: Instead of requiring consecutive speech frames (which fails on natural syllable gaps), uses a sliding window of last 12 frames — triggers when 6+ are speech (~192ms real speech in ~384ms window).
- **Playback-Aware**: Tracks total audio bytes sent, estimates client playback duration, and keeps barge-in detection active even after server finishes TTS streaming.
- **Client-Side Instant Stop**: Audio playback is broken into 20ms sub-chunks with abort flag checked between each. `stream.abort()` flushes hardware audio buffer for near-instant silence.

## 3. **Topic Switch Handling (Code-Level)**
- **Detection in Code**: `_is_topic_switch()` in `voice_orchestrator.py` detects topic-switch language before sending to the LLM.
- **Two Categories**:
  - **Explicit switches**: "never mind", "forget that", "switch to", "instead", "different topic"
  - **Interrupt + topic change**: "wait" or "hold on" combined with "talk about", "tell me about", etc.
- **Agent-Aware**: Only triggers for specialist agents (Emily, Sophia), NOT Kate (router).
- **[TOPIC SWITCH] Context**: Prepended to user message, explicitly forbidding handoff tools and requiring confirmation.
- **Handoff Clean-Up**: System tags (`[TOPIC SWITCH]`, `[INTERRUPTED]`, `[FAREWELL]`) are stripped from messages before forwarding to handoff targets. Topic-switch phrasing ("switch to", "instead of") is also removed.
- **Handoff Context**: Explicitly tells receiving agent "This is a DIRECT HANDOFF — NOT a topic switch. Answer immediately."

## 4. **Auto Call Termination**
- **Farewell Detection**: `_is_farewell()` in `voice_orchestrator.py` matches goodbye phrases.
- **Flow**: Farewell detected → `[FAREWELL]` context prepended → agent gives brief goodbye → server sends `call_ended` status → client waits for all audio to finish playing → disconnects.
- **Playback Completion**: Client uses `playback_busy` flag to ensure farewell audio finishes completely before disconnecting.

## 5. **Conversation Recording**
- `ConversationRecorder` captures user + agent audio and saves as WAV files.
- Recordings stored in `backend/recordings/` folder, named `NNN_YYYY-MM-DD_HH-MM-SS.wav`.

## 6. **Natural Speech Style**
- All agent prompts updated with human-like expressions: conversational fillers ("So,", "Well,", "You know,"), contractions, enthusiasm, warmth, and genuine reactions.
- Explicit anti-robotic rules: avoids "Certainly!", "I'd be happy to assist", "Here's some information".
- Code-level sanitization strips numbered lists and formatting as a safety net.

## 7. **LLM & TTS Configuration**
- **STT**: FasterWhisper `medium` model on CUDA.
- **TTS**: VibeVoice-Realtime-0.5B with SDPA attention fallback.
- **LLM**: Azure GPT-4.1-mini for agent reasoning.

---

## How to Run

```bash
# Terminal 1: Start Server
cd backend
conda activate maf_a2a
python -m uvicorn app.main:app --reload

# Terminal 2: Voice Client
cd backend
python scripts/interactive_voice_client.py
```