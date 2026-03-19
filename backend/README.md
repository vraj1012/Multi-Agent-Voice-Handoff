# Multi-Agent Voice Handoff — Backend

A **white-labeled**, fully configurable multi-agent voice orchestration system. Multiple AI agents collaborate via real-time voice, with automatic handoff between domain experts — all driven from a **single configuration file**.

> **White-Label Ready:** To rebrand, rename agents, change domains, or swap voices — edit **only** [`app/agents/registry.py`](app/agents/registry.py). Everything else auto-generates from that config.

---

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [System Flow](#system-flow)
- [File-by-File Reference](#file-by-file-reference)
- [Configuration](#configuration)
- [Getting Started](#getting-started)
- [API Reference](#api-reference)
- [White-Labeling Guide](#white-labeling-guide)

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        CLIENT (any)                             │
│  WebSocket: ws://host:8000/api/v1/ws/voice  (real-time)        │
│  REST API:  http://host:8000/api/v1/voice/chat  (batch)        │
│  Text API:  http://host:8000/api/v1/chat  (text-only)          │
└──────────────┬──────────────────────────────────────────────────┘
               │
┌──────────────▼──────────────────────────────────────────────────┐
│                      BACKEND (FastAPI)                          │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  API Layer                                               │   │
│  │  ├── websocket_router.py   (real-time voice streaming)   │   │
│  │  ├── voice_router.py       (batch voice REST endpoint)   │   │
│  │  └── endpoints.py          (text chat + health check)    │   │
│  └──────────────┬───────────────────────────────────────────┘   │
│                 │                                               │
│  ┌──────────────▼───────────────────────────────────────────┐   │
│  │  Service Layer                                           │   │
│  │  ├── voice/stream_manager.py  (VAD, turn detection,      │   │
│  │  │                             barge-in, buffering)      │   │
│  │  ├── voice_orchestrator.py    (STT → Agent → TTS pipe)   │   │
│  │  └── orchestration.py         (multi-agent handoff       │   │
│  │                                workflow engine)          │   │
│  └──────────────┬───────────────────────────────────────────┘   │
│                 │                                               │
│  ┌──────────────▼───────────────────────────────────────────┐   │
│  │  Agent Layer (config-driven from registry.py)            │   │
│  │  ├── registry.py        ← SINGLE SOURCE OF TRUTH        │   │
│  │  ├── shared_prompts.py  (template-based prompt builder)  │   │
│  │  ├── receptionist/      (router agent)                   │   │
│  │  ├── technical_expert/  (domain expert + RAG)            │   │
│  │  └── agriculture_expert/(domain expert + RAG)            │   │
│  └──────────────┬───────────────────────────────────────────┘   │
│                 │                                               │
│  ┌──────────────▼───────────────────────────────────────────┐   │
│  │  Core Layer                                              │   │
│  │  ├── config.py       (pydantic settings from .env)       │   │
│  │  ├── adapter.py      (universal LLM adapter)             │   │
│  │  └── llm_factory.py  (LLM client factory)                │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  Voice Providers (swappable via Factory pattern)         │   │
│  │  ├── stt_whisper.py    (FasterWhisper Medium / Turbo)    │   │
│  │  ├── tts_chatterbox.py (Chatterbox Turbo / VibeVoice)    │   │
│  │  └── vad_ten.py        (TEN VAD / Silero VAD)            │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  RAG Layer (Retrieval-Augmented Generation)              │   │
│  │  ├── engine.py       (ChromaDB query/storage)            │   │
│  │  ├── embeddings.py   (sentence-transformers)             │   │
│  │  ├── ingestion.py    (PDF/TXT → chunks → vectors)        │   │
│  │  └── tools.py        (AIFunction wrapper for agents)     │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

---

## System Flow

### Real-Time Voice Call (WebSocket)

```
1. Client connects to  ws://host:8000/api/v1/ws/voice
2. Client streams raw PCM audio chunks (16kHz, 16-bit mono, 512 samples/chunk)

3. StreamManager receives each chunk:
   ├── VAD (Silero or TEN VAD) checks: is the user speaking?
   ├── Buffers audio while speech is detected
   ├── After ~1.3s of silence → end-of-turn detected
   └── If user speaks during AI playback → barge-in triggered

4. VoiceOrchestrator processes the completed turn:
   ├── STT: FasterWhisper (Medium or Large-v3-Turbo) transcribes audio → text
   ├── Context tagging: farewell detection, topic switch detection
   ├── OrchestrationService processes message through agent mesh:
   │   ├── Active agent receives message
   │   ├── Agent may call handoff_to_<Name>() → triggers handoff
   │   ├── Agent may call search_knowledge_base() → RAG lookup
   │   └── Response collected with agent name
   └── TTS: VibeVoice or Chatterbox Turbo synthesizes response

5. Each TTS audio chunk is streamed back to client via WebSocket
6. Client plays audio; can interrupt (barge-in) at any time
7. Loop back to step 2
```

### Agent Handoff Flow

```
User: "Tell me about machine learning"
         │
    ┌────▼────┐
    │  Kate   │  (Receptionist / Router)
    │         │  "Oh, Emily is great with that!"
    └────┬────┘
         │ handoff_to_Emily()
    ┌────▼────┐
    │  Emily  │  (Technical Expert)
    │         │  Searches knowledge base → answers question
    └─────────┘

User: "What about growing tomatoes?"
         │
    ┌────▼────┐
    │  Emily  │  Detects out-of-domain
    │         │  "That's more Sophia's thing!"
    └────┬────┘
         │ handoff_to_Sophia()
    ┌────▼────┐
    │ Sophia  │  (Agriculture Expert)
    │         │  Searches knowledge base → answers question
    └─────────┘
```

---

## File-by-File Reference

### Entry Point

| File | Purpose |
|------|---------|
| `app/main.py` | FastAPI application entry point. Registers CORS middleware, mounts all routers (REST, voice, WebSocket). |

### API Layer — `app/api/v1/`

| File | Purpose |
|------|---------|
| `endpoints.py` | Text-only chat endpoint (`POST /api/v1/chat`) and root health check. Uses `settings.PROJECT_NAME` for the welcome message. |
| `voice_router.py` | Batch voice endpoint (`POST /api/v1/voice/chat`). Accepts audio file upload, returns synthesized audio response with metadata headers. Also has `/voice/health` to verify models are loaded. |
| `websocket_router.py` | Real-time bidirectional voice streaming (`WS /api/v1/ws/voice`). Creates a `StreamManager` per connection. Runs concurrent receive and process loops. |

### Service Layer — `app/services/`

| File | Purpose |
|------|---------|
| `voice_orchestrator.py` | The main voice pipeline: STT → Agent → TTS. Handles farewell detection, topic-switch tagging, interrupt context. Streams TTS sentence-by-sentence. |
| `orchestration.py` | Multi-agent handoff workflow engine. Builds the `HandoffBuilder` workflow from `registry.py` config. Processes messages through the active agent. |
| `voice/stream_manager.py` | Real-time audio buffer management. Receives raw PCM chunks, runs VAD (Silero/TEN) for turn detection, implements sliding-window barge-in. |
| `voice/factory.py` | Factory pattern for voice providers. Lazily initializes singleton instances of STT, TTS, and VAD. Swap providers by changing imports or config here. |
| `voice/interfaces.py` | Abstract base classes defining the contracts for `STTProvider`, `TTSProvider`, and `VADProvider`. |
| `voice/recorder.py` | Records full conversations (user + agent audio) to numbered WAV files in `recordings/`. |

### Voice Providers — `app/services/voice/providers/`

| File | Purpose |
|------|---------|
| `stt_whisper.py` | **FasterWhisper** STT provider. Loads Whisper models (Medium or Large-v3-Turbo) on GPU/CPU. |
| `tts_chatterbox.py` | **(New)** Nitro-speed Chatterbox TTS provider with zero-shot voice cloning support. |
| `tts_vibevoice.py` | **VibeVoice** TTS provider. Loads the Microsoft VibeVoice streaming model locally. |
| `vad_ten.py` | **(New)** C-native TEN VAD for ultra-fast response times. |
| `vad_silero.py` | **Silero VAD** provider. Provides real-time per-chunk speech detection. |

### Agent Layer — `app/agents/`

| File | Purpose |
|------|---------|
| `registry.py` | **⭐ Single source of truth** for all agent identity. Defines `AgentConfig` with: name, voice_key, experts, rag_collection, etc. |
| `shared_prompts.py` | Shared `build_expert_prompt(config, other_agents)` template function. Generates system prompts dynamically. |
| `receptionist/agent.py` | Factory function that creates the receptionist/router agent from registry config. |
| `receptionist/prompts.py` | Router agent's prompt generator with dynamic routing rules. |
| `technical_expert/agent.py` | Factory function that creates a domain expert agent (with optional RAG). |
| `agriculture_expert/agent.py` | Domain expert factory for agriculture domain. |

### Core Layer — `app/core/`

| File | Purpose |
|------|---------|
| `config.py` | Pydantic `Settings` class that reads from `.env`. Defines server, AI models, LLM provider, and API keys. |
| `adapter.py` | `DualChatClient` — universal LLM adapter supporting Azure OpenAI, Gemini, and Ollama. |
| `llm_factory.py` | `LLMFactory` — synchronous LLM client factory. |

### RAG Layer — `app/rag/`

| File | Purpose |
|------|---------|
| `engine.py` | `RAGEngine` — ChromaDB wrapper for collection management and similarity search. |
| `embeddings.py` | `EmbeddingService` — generates vector embeddings using `sentence-transformers`. |
| `ingestion.py` | `IngestionService` — reads documents, chunks them, and stores them in the vector database. |
| `tools.py` | `create_rag_tool(collection_name)` — wraps RAG queries as an `AIFunction` for agents. |

### Utility Scripts — `scripts/`

| File | Purpose |
|------|---------|
| `ingest_knowledge.py` | CLI script to ingest knowledge base documents into ChromaDB. |
| `interactive_voice_client.py` | Standalone Python voice client for real-time testing with mic audio and barge-in support. |

### Other Files

| File | Purpose |
|------|---------|
| `.env` | Environment variables (API keys, model sizes, server config). |
| `.env.example` | Template `.env` with placeholder values. |
| `.gitignore` | Protects sensitive files and local models from version control. |

---

## Configuration

### Environment Variables (`.env`)

Copy `.env.example` to `.env` and configure:

```bash
cp .env.example .env
```

| Variable | Description | Default / Recommended |
|----------|-------------|---------|
| `LLM_PROVIDER` | LLM backend: `AZURE`, `GEMINI`, or `OLLAMA` | `AZURE` |
| `AZURE_OPENAI_API_KEY` | Azure OpenAI API key | — |
| `AZURE_OPENAI_ENDPOINT` | Azure endpoint URL | — |
| `AZURE_DEPLOYMENT_NAME` | Azure model deployment name | `gpt-4.1-mini` |
| `GEMINI_API_KEY` | Google Gemini API key | — |
| `OLLAMA_URL` | Local Ollama server URL | `http://localhost:11434` |
| `OLLAMA_MODEL` | Ollama model name | `llama3:8b-instruct-q4_K_M` |
| `WHISPER_MODEL_SIZE` | Whisper model: `medium` or `large-v3-turbo` | `large-v3-turbo` |
| `TTS_MODEL_PATH` | TTS model path or HuggingFace ID | `microsoft/VibeVoice-Realtime-0.5B` |
| `HOST` / `PORT` | Server bind address | `0.0.0.0:8000` |
| `CHROMA_DB_PATH` | ChromaDB persistence directory | `./chroma_db` |

### Dependencies

Core Python packages required:

```
fastapi
uvicorn
pydantic-settings
openai
google-generativeai
faster-whisper
torch
sentence-transformers
chromadb
PyPDF2
numpy
sounddevice
websockets
```

---

## Getting Started

### 1. Setup Environment
```bash
cd backend
cp .env.example .env
# Edit .env with your API keys and preferred model sizes
```

### 2. Ingest Knowledge Base (Optional)
```bash
# Place .pdf/.txt files in knowledge folders
python scripts/ingest_knowledge.py
```

### 3. Start the Server
```bash
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### 4. Test with the Voice Client
```bash
python scripts/interactive_voice_client.py
```

---

## API Reference

### WebSocket — Real-Time Voice
**`WS /api/v1/ws/voice`**
- **Client → Server:** Raw PCM audio bytes (16kHz, 16-bit mono)
- **Server → Client:** Binary audio (24kHz PCM) or JSON status messages

**JSON Status Messages:**
```json
{"type": "status", "content": "processing|listening|interrupted|call_ended|silent"}
{"type": "text", "content": "agent response text", "agent": "AgentName", "handoff": false}
{"type": "metadata", "content": {"handoff": false, "handoff_target": null, "agent_count": 1}}
{"type": "audio", "content": "<binary>", "agent": "AgentName", "chunk": 0}
```

### REST — Batch Voice
**`POST /api/v1/voice/chat`**
Upload an audio file, receive synthesized audio response.
- **Response Headers**: `X-Agent-Name`, `X-Response-Text`, `X-Handoff`, `X-Time-Taken`

### REST — Text Chat
**`POST /api/v1/chat`**
```json
{"message": "Tell me about machine learning"}
// Returns: {"agent": "Emily", "message": "...", "handoff_occurred": true}
```

---

## White-Labeling Guide

### How to Rebrand
Edit **only** `app/agents/registry.py`:
- Rename agents, update personas, and set the `voice_key` to match your desired identity.
- Everything auto-generates from this config (system prompts, handoff logic, etc.).

### Custom Voices (Voice Cloning)
The **Chatterbox TTS** provider supports zero-shot voice cloning:
1. Record ~10 seconds of source audio (WAV).
2. Save to `backend/app/agents/voices/<voice_name>.wav`.
3. Set `voice_key="<voice_name>"` in `registry.py`.

### Swapping Voice Models
The system is modularly designed via the Factory pattern in `app/services/voice/factory.py`.
- To use **TEN VAD** instead of Silero, or **Chatterbox TTS** instead of VibeVoice, simply update the provider initialization in the factory.

### Adding a New Agent

1. Create `app/agents/<your_agent>/agent.py`:
   ```python
   from agent_framework import ChatAgent
   from app.core.adapter import DualChatClient
   from app.agents.shared_prompts import build_expert_prompt
   from app.agents.registry import get_all_agent_configs
   from app.rag.tools import create_rag_tool

   def create_agent(config):
       client = DualChatClient()
       all_configs = get_all_agent_configs()
       other_agents = [c for c in all_configs if c.name != config.name]
       prompt = build_expert_prompt(config, other_agents)
       tools = []
       if config.rag_collection:
           tools.append(create_rag_tool(config.rag_collection))
       return ChatAgent(
           name=config.name,
           description=config.description,
           instructions=prompt,
           chat_client=client,
           tools=tools,
       )
   ```

2. Add an entry to `AGENT_REGISTRY` in `registry.py`.

3. (Optional) Add knowledge base files to `knowledge/<domain>/` and run ingestion.

That's it — the system automatically handles the rest.
