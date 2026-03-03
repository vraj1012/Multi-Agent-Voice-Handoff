# Phase-wise Project Blueprint & Testing Strategy

This blueprint outlines the development lifecycle for the **Multi-Agent Voice Orchestration System**, broken down into 4 key phases. Each phase includes specific deliverables and a testing strategy.

## Phase 1: Foundation & Infrastructure Setup
**Goal**: Establish the core backend, environment configuration, and basic connectivity.

### Tasks
1.  **Environment Setup**:
    -   Verify `maf_a2a` virtual environment functionality.
    -   Install any missing dependencies from `requirements.txt`.
    -   Configure `.env` with API keys (OpenAI, Azure, etc.).
2.  **Base App Structure**:
    -   Initialize `FastAPI` app in `backend/app/main.py`.
    -   Create health check endpoint (`/health`).
3.  **Service Wrappers**:
    -   Implement basic wrappers for **Whisper** (STT), **VibeVoice** (TTS), and **Silero** (VAD) in `backend/app/services/`.

### Testing Strategy (Phase 1)
-   **Unit Tests**:
    -   Test environment variable loading (`test_config.py`).
    -   Test `/health` endpoint returns `200 OK`.
-   **Integration Tests**:
    -   Script to verify Whisper can load model and transcribe a sample audio file.
    -   Script to verify VibeVoice can generate audio from text.

---

## Phase 2: Core Orchestration & Agent Mesh
**Goal**: Implement the Microsoft Agent Framework and the orchestration logic.

### Tasks
1.  **RAG Infrastructure [NEW]**:
    -   Setup **ChromaDB** (or similar) in `backend/app/rag/engine.py`.
    -   Create ingestion pipeline in `backend/app/rag/ingestion.py` to watch `knowledge/` folders.
    -   Implement collection separation logic (one collection per agent).
2.  **Agent Implementation**:
    -   Develop `Receptionist` agent (Intent classification).
    -   Develop `Technical Expert` (Connect to 'technical' collection).
    -   Develop `Agriculture Expert` (Connect to 'agriculture' collection).
3.  **Orchestration Logic**:
    -   Implement `Orchestrator` to route messages based on agent output/intent.
    -   Set up the "Handoff" mechanism (passing context between agents).
4.  **Websocket Layer**:
    -   Create `backend/app/api/v1/websocket.py` to handle real-time audio streams.

### Testing Strategy (Phase 2)
-   **Unit Tests**:
    -   Mock agent inputs to verify routing logic (e.g., query "Crop disease" -> Agriculture Expert).
-   **Functional Tests**:
    -   Simulate a conversation flow via text input to ensure correct agent is triggered.
    -   Verify context retention after handoff.

---

## Phase 3: Frontend Development & Integration
**Goal**: Build the user interface for voice interaction.

### Tasks
1.  **Frontend Setup**:
    -   Initialize `React` project with `Vite`.
    -   Set up `TailwindCSS` for styling.
2.  **Components**:
    -   `VoiceRecorder.tsx`: Handle microphone permissions, recording, and visualization.
    -   `ChatInterface.tsx`: Display transcriptions and agent responses.
3.  **Integration**:
    -   Connect Frontend WebSocket to Backend.
    -   Handle binary audio data (playing received TTS audio).

### Testing Strategy (Phase 3)
-   **UI Tests**:
    -   Verify microphone permission prompts.
    -   Visual check of recording state indicators.
-   **End-to-End (E2E) Tests**:
    -   Speak into the frontend -> Backend routes -> Agent responds -> Audio plays back.

---

## Phase 4: Optimization & Deployment
**Goal**: Polish the application for production-readiness.

### Tasks
1.  **Performance Tuning**:
    -   Optimize VAD implementation for latency.
    -   Implement caching for frequent queries in `Technical Expert`.
2.  **Documentation**:
    -   Finalize API documentation (Swagger/ReDoc).
    -   Update `README.md` with final screenshots.
3.  **Containerization** (Optional):
    -   Create `Dockerfile` for backend.
    -   Create `docker-compose.yml` for full stack.

### Testing Strategy (Phase 4)
-   **Load Testing**:
    -   Simulate multiple concurrent websocket connections using `Locust` or custom script.
-   **User Acceptance Testing (UAT)**:
    -   Real-world scenario testing with actual users to gauge response time and accuracy.
