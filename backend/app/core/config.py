from pydantic_settings import BaseSettings
from functools import lru_cache

class Settings(BaseSettings):
    API_V1_STR: str = "/api/v1"
    PROJECT_NAME: str = "Multi-Agent Voice Handoff"
    
    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    
    # AI Config
    WHISPER_MODEL_SIZE: str = "medium"
    DEVICE: str = "cuda" # Switch to GPU
    COMPUTE_TYPE: str = "float16" # Optimal for GPU
    
    TTS_MODEL_PATH: str = "microsoft/VibeVoice-Realtime-0.5B"

    # RAG Config
    CHROMA_DB_PATH: str = "backend/chroma_db"
    RAG_COLLECTION_TECHNICAL: str = "technical_collection"
    RAG_COLLECTION_AGRICULTURE: str = "agriculture_collection"
    
    # Knowledge Directories
    KNOWLEDGE_BASE_TECHNICAL: str = "backend/knowledge/technical"
    KNOWLEDGE_BASE_AGRICULTURE: str = "backend/knowledge/agriculture"
    
    EMBEDDING_MODEL_NAME: str = "all-MiniLM-L6-v2" # Fast local embeddings

    # LLM Configuration
    LLM_PROVIDER: str = "AZURE" # AZURE, OPENAI, GEMINI, OLLAMA
    
    # Azure OpenAI
    AZURE_OPENAI_API_KEY: str = ""
    AZURE_OPENAI_ENDPOINT: str = ""
    AZURE_OPENAI_API_VERSION: str = "2024-05-01-preview"
    AZURE_DEPLOYMENT_NAME: str = "gpt-4"

    # OpenAI
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4-turbo"

    # Gemini
    GEMINI_API_KEY: str = ""
    
    # Ollama (Local)
    OLLAMA_URL: str = "http://localhost:11434/v1"
    OLLAMA_MODEL: str = "llama3"

    class Config:
        env_file = ".env"
        env_file_encoding = 'utf-8' # Ensure encoding is handled
        extra = "ignore" # Ignore extra fields in .env

@lru_cache()
def get_settings():
    return Settings()

settings = get_settings()

# Purpose: It reads variables from your .env file (like API keys, host, port) and makes them available to the code as Python variables.
