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
│  │  ├── stt_whisper.py    (FasterWhisper, GPU-accelerated)  │   │
│  │  ├── tts_vibevoice.py  (VibeVoice, local CUDA/CPU)      │   │
│  │  └── vad_silero.py     (Silero VAD, real-time)           │   │
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
   ├── VAD (Silero) checks: is the user speaking?
   ├── Buffers audio while speech is detected
   ├── After ~1.3s of silence → end-of-turn detected
   └── If user speaks during AI playback → barge-in triggered

4. VoiceOrchestrator processes the completed turn:
   ├── STT: FasterWhisper transcribes buffered audio → text
   ├── Context tagging: farewell detection, topic switch detection
   ├── OrchestrationService processes message through agent mesh:
   │   ├── Active agent receives message
   │   ├── Agent may call handoff_to_<Name>() → triggers handoff
   │   ├── Agent may call search_knowledge_base() → RAG lookup
   │   └── Response collected with agent name
   └── TTS: VibeVoice synthesizes response sentence-by-sentence

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
| `voice_router.py` | Batch voice endpoint (`POST /api/v1/voice/chat`). Accepts audio file upload, returns synthesized audio response with metadata headers. Also has `/voice/health` to verify STT/TTS/VAD models are loaded. |
| `websocket_router.py` | Real-time bidirectional voice streaming (`WS /api/v1/ws/voice`). Creates a `StreamManager` per connection. Runs concurrent receive and process loops. Handles barge-in messages and saves conversation recordings on disconnect. |

### Service Layer — `app/services/`

| File | Purpose |
|------|---------|
| `voice_orchestrator.py` | The main voice pipeline: STT → Agent → TTS. Handles farewell detection, topic-switch tagging, interrupt context. Streams TTS sentence-by-sentence. Loads voice mapping from registry (`get_agent_voice_map()`). |
| `orchestration.py` | Multi-agent handoff workflow engine. Builds the `HandoffBuilder` workflow from `registry.py` config. Processes messages through the active agent, handles handoff chains (with loop protection), and rebuilds the workflow on each handoff. |
| `voice/stream_manager.py` | Real-time audio buffer management. Receives raw PCM chunks, runs Silero VAD for turn detection, implements sliding-window barge-in (6/12 frames), and tracks estimated client playback timing. |
| `voice/factory.py` | Factory pattern for voice providers. Lazily initializes singleton instances of STT (FasterWhisper), TTS (VibeVoice), and VAD (Silero). Swap providers by changing the import here. |
| `voice/interfaces.py` | Abstract base classes defining the contracts for `STTProvider`, `TTSProvider`, and `VADProvider`. Any new provider must implement these interfaces. |
| `voice/recorder.py` | Records full conversations (user + agent audio) to numbered WAV files in `recordings/`. Handles sample-rate conversion between user audio (16kHz) and agent audio (24kHz). |

### Voice Providers — `app/services/voice/providers/`

| File | Purpose |
|------|---------|
| `stt_whisper.py` | **FasterWhisper** STT provider. Loads the Whisper model (configurable size) on GPU/CPU. Transcribes with VAD filtering and hallucination rejection (`no_speech_prob`, `language_probability` thresholds). |
| `tts_vibevoice.py` | **VibeVoice** TTS provider. Loads the Microsoft VibeVoice streaming model locally. Supports multiple voice presets (`.pt` files), voice caching, and threaded generation. Falls back from CUDA → CPU on error. |
| `vad_silero.py` | **Silero VAD** provider. Provides both file-level speech segmentation and real-time per-chunk speech detection (512-sample windows at 16kHz). |

### Agent Layer — `app/agents/`

| File | Purpose |
|------|---------|
| `registry.py` | **⭐ Single source of truth** for all agent identity. Defines `AgentConfig` with: name, factory path, voice_key, domain_keywords, description, persona_style, greeting_examples, farewell_example, rag_collection. Provides helpers: `load_agents()`, `get_start_agent_name()`, `get_handoff_rules()`, `get_agent_voice_map()`, `get_agent_config_by_name()`. |
| `shared_prompts.py` | Shared `build_expert_prompt(config, other_agents)` template function. Generates system prompts dynamically from registry config — voice mode rules, persona, handoff rules, topic-switch handling, farewell handling, and knowledge base instructions. |
| `receptionist/agent.py` | Factory function that creates the receptionist/router agent from registry config. |
| `receptionist/prompts.py` | `build_receptionist_prompt(config, other_agents)` — generates the router agent's prompt with dynamic routing rules and handoff examples for all registered expert agents. |
| `technical_expert/agent.py` | Factory function that creates a domain expert agent from registry config. Creates RAG tool if `rag_collection` is set. |
| `technical_expert/prompts.py` | Re-exports `build_expert_prompt` from `shared_prompts.py`. |
| `agriculture_expert/agent.py` | Same factory pattern as technical_expert, driven by registry config. |
| `agriculture_expert/prompts.py` | Re-exports `build_expert_prompt` from `shared_prompts.py`. |

### Core Layer — `app/core/`

| File | Purpose |
|------|---------|
| `config.py` | Pydantic `Settings` class that reads from `.env`. Defines all configurable values: server (host, port), AI models (Whisper size, device, compute type), LLM provider (Azure/Gemini/Ollama), RAG paths, and API keys. |
| `adapter.py` | `DualChatClient` — universal LLM adapter supporting Azure OpenAI, Gemini, and Ollama. Handles both batch and streaming responses, internal tool execution loops, and handoff tool passthrough to the agent framework. |
| `llm_factory.py` | `LLMFactory` — synchronous LLM client factory (used for non-streaming calls). Returns configured Azure/OpenAI/Gemini/Ollama clients. |

### RAG Layer — `app/rag/`

| File | Purpose |
|------|---------|
| `engine.py` | `RAGEngine` — ChromaDB wrapper. Manages collections, adds documents with embeddings, and queries by embedding similarity. |
| `embeddings.py` | `EmbeddingService` — uses `sentence-transformers` (`all-MiniLM-L6-v2` by default) to generate vector embeddings for RAG documents and queries. |
| `ingestion.py` | `IngestionService` — reads PDF/TXT files from knowledge directories, chunks them (~500 chars with overlap), generates embeddings, and stores in ChromaDB. |
| `tools.py` | `create_rag_tool(collection_name)` — wraps RAG queries as an `AIFunction` that agents can call via `search_knowledge_base()`. |

### Utility Scripts — `scripts/`

| File | Purpose |
|------|---------|
| `ingest_knowledge.py` | CLI script to ingest knowledge base documents into ChromaDB. Run: `python scripts/ingest_knowledge.py` from `backend/`. |
| `interactive_voice_client.py` | Standalone Python voice client for testing. Connects to the WebSocket, captures mic audio, plays back agent responses, supports barge-in and device selection. No browser needed. |

### Other Files

| File | Purpose |
|------|---------|
| `.env` | Environment variables (API keys, model paths, server config). **Never commit this.** |
| `.env.example` | Template `.env` with placeholder values. Copy this to `.env` and fill in your keys. |
| `.gitignore` | Protects `.env`, `__pycache__`, model files, and recordings from being committed. |

---

## Configuration

### Environment Variables (`.env`)

Copy `.env.example` to `.env` and configure:

```bash
cp .env.example .env
```

| Variable | Description | Default |
|----------|-------------|---------|
| `LLM_PROVIDER` | LLM backend: `AZURE`, `GEMINI`, or `OLLAMA` | `AZURE` |
| `AZURE_OPENAI_API_KEY` | Azure OpenAI API key | — |
| `AZURE_OPENAI_ENDPOINT` | Azure endpoint URL | — |
| `AZURE_DEPLOYMENT_NAME` | Azure model deployment name | `gpt-4.1-mini` |
| `GEMINI_API_KEY` | Google Gemini API key | — |
| `OLLAMA_URL` | Local Ollama server URL | `http://localhost:11434` |
| `OLLAMA_MODEL` | Ollama model name | `llama3:8b-instruct-q4_K_M` |
| `WHISPER_MODEL_SIZE` | Whisper model: `tiny`, `base`, `small`, `medium`, `large` | `medium` |
| `TTS_MODEL_PATH` | VibeVoice model path or HuggingFace ID | `microsoft/VibeVoice-Realtime-0.5B` |
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
sounddevice        # only for interactive_voice_client.py
websockets         # only for interactive_voice_client.py
```

The VibeVoice TTS model must be placed at `backend/vibevoice_model/VibeVoice/`.

---

## Getting Started

### 1. Setup Environment

```bash
cd backend
cp .env.example .env
# Edit .env with your API keys
```

### 2. Ingest Knowledge Base (Optional)

```bash
# Place .pdf/.txt files in knowledge/technical/ and knowledge/agriculture/
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

Or connect any WebSocket client to `ws://localhost:8000/api/v1/ws/voice`.

---

## API Reference

### WebSocket — Real-Time Voice

**`WS /api/v1/ws/voice`**

- **Client → Server:** Raw PCM audio bytes (16kHz, 16-bit mono, 512 samples/chunk)
- **Server → Client:** Binary audio (24kHz PCM) or JSON status messages

JSON message types from server:
```json
{"type": "status", "content": "processing|listening|interrupted|call_ended|silent"}
{"type": "text", "content": "agent response text", "agent": "AgentName", "handoff": false}
{"type": "metadata", "content": {"handoff": false, "handoff_target": null, "agent_count": 1}}
{"type": "audio", "content": "<binary>", "agent": "AgentName", "chunk": 0}
```

Client can send JSON for barge-in:
```json
{"type": "barge_in"}
```

### REST — Batch Voice

**`POST /api/v1/voice/chat`**

Upload an audio file, receive synthesized audio response.

- **Request:** `multipart/form-data` with `file` field
- **Response:** `audio/wav` body with metadata headers:
  - `X-Agent-Name`, `X-Response-Text`, `X-Handoff`, `X-Time-Taken`

### REST — Text Chat

**`POST /api/v1/chat`**

```json
// Request
{"message": "Tell me about machine learning"}

// Response
{"agent": "Emily", "message": "...", "handoff_occurred": true}
```

### Health Checks

- `GET /health` — Server health
- `GET /api/v1/voice/health` — Voice models loaded status

---

## White-Labeling Guide

### How to Rebrand

Edit **only** `app/agents/registry.py`:

```python
AGENT_REGISTRY = [
    AgentConfig(
        name="Sarah",                    # ← Change agent name
        factory="app.agents.receptionist.agent.create_agent",
        is_start_agent=True,
        voice_key="en-Grace_woman",      # ← Change voice
        description="Friendly front-desk assistant.",
        persona_style="cheerful and professional",
        greeting_examples=["Hi there! I'm Sarah!"],
        farewell_example="Great talking to you! Bye!",
    ),
    AgentConfig(
        name="Max",                      # ← Change agent name
        factory="app.agents.technical_expert.agent.create_agent",
        voice_key="en-Emma_woman",
        domain_keywords=["Finance", "Stocks", "Investing"],  # ← Change domain
        description="Finance Expert specializing in investments.",
        persona_style="confident and knowledgeable advisor",
        rag_collection="finance_collection",
        knowledge_base_path="./knowledge/finance",
    ),
    # Add/remove agents as needed
]
```

**Everything auto-generates from this config:**
- System prompts (persona, handoff rules, domain routing)
- Voice-to-agent mapping
- Handoff tool names (`handoff_to_Max`, `handoff_to_Sarah`)
- RAG knowledge base bindings

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

That's it — no other files need to change.
