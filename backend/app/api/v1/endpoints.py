from fastapi import APIRouter
from pydantic import BaseModel
from app.services.orchestration import get_orchestration_service
from app.core.config import settings

router = APIRouter()


class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    agent: str
    message: str
    handoff_occurred: bool = False


@router.get("/")
def read_root():
    return {"message": f"Welcome to {settings.PROJECT_NAME} API"}


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """Send a message to the multi-agent handoff system."""
    service = get_orchestration_service()
    result = await service.process_message(request.message)
    return ChatResponse(**result)
