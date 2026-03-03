# Proposed Project Folder Structure

This document outlines the recommended directory structure to separate the application into a Frontend and a Backend, following industry standards.

## Overview
- **`/backend`**: Contains the FastAPI application, agents, and python logic.
- **`/frontend`**: Contains the client-side code (Suggested: React/Vite).

## Directory Tree

```text
Multi_Agent_MAF_Handoff_new/
├── backend/                        # Python/FastAPI Backend
│   ├── app/
│   │   ├── rag/                    # [NEW] RAG System
│   │   │   ├── __init__.py
│   │   │   ├── engine.py           # Core Retrieval Logic (ChromaDB/VectorDB)
│   │   │   ├── ingestion.py        # Document Loader & Splitter
│   │   │   └── embeddings.py       # Embedding Model Wrapper
│   │   ├── agents/                 # Microsoft Agent Framework Agents
│   │   │   ├── __init__.py
│   │   │   ├── receptionist/       # Receptionist Agent
│   │   │   │   ├── __init__.py
│   │   │   │   ├── agent.py        # Agent Logic
│   │   │   │   └── tools.py        # Specific tools
│   │   │   ├── technical_expert/   # Technical Expert Agent
│   │   │   │   ├── __init__.py
│   │   │   │   ├── agent.py
│   │   │   │   ├── tools.py
│   │   │   │   └── knowledge/      # [NEW] Agent-Specific Documents (PDF/TXT)
│   │   │   └── agriculture_expert/ # User update: Industry -> Agriculture
│   │   │       ├── __init__.py
│   │   │       ├── agent.py
│   │   │       ├── tools.py
│   │   │       └── knowledge/      # [NEW] Agent-Specific Documents
│   │   ├── core/                   # Core configurations
│   │   │   ├── config.py           # Env settings, API keys
│   │   │   └── security.py         # Auth/Security protocols
│   │   ├── services/               # External Integrations
│   │   │   ├── orchestration.py    # Main Handoff Logic
│   │   │   ├── stt_service.py      # OpenAI Whisper Wrapper
│   │   │   ├── tts_service.py      # VibeVoice Wrapper
│   │   │   └── vad_service.py      # Silero VAD Wrapper
│   │   ├── api/                    # API Routes
│   │   │   └── v1/
│   │   │       ├── endpoints.py
│   │   │       └── websocket.py    # Real-time voice socket
│   │   ├── models/                 # Pydantic data models
│   │   │   └── schemas.py
│   │   └── main.py                 # Application Entry Point
│   ├── tests/                      # Pytest tests
│   ├── .env                        # Backend environment variables
│   ├── requirements.txt            # Python dependencies
│   └── Dockerfile                  # Backend containerization
│
├── frontend/                       # Client-Side Application
│   ├── public/                     # Static assets
│   │   └── ...
│   ├── src/
│   │   ├── components/             # Reusable UI components
│   │   │   ├── VoiceRecorder.tsx   # Controls recording/VAD visualization
│   │   │   └── ChatInterface.tsx   # Text fallback/History view
│   │   ├── hooks/                  # Custom Hooks
│   │   │   └── useWebsocket.ts     # Manage real-time connection to backend
│   │   ├── services/               # API Calls
│   │   │   └── api.ts
│   │   ├── App.tsx                 # Main Layout
│   │   └── main.tsx                # Entry Point
│   ├── .env                        # Frontend environment variables
│   ├── package.json                # Node dependencies
│   └── vite.config.ts              # Build configuration
│
└── README.md                       # Main Project Documentation
```

## Rationale
1.  **Backend Separation**: Keeping Python dependencies isolated in `backend/` ensures clean containerization and deployment.
2.  **Frontend Scalability**: A dedicated `frontend/` allows for modern build tools (Vite, Webpack) without conflicting with Python environments.
3.  **Modular Services**: The `app/services` structure allows easy swapping of STT/TTS providers (e.g., if you switch from Whisper to something else later).
