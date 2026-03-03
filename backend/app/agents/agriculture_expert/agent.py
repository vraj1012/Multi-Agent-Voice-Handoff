from agent_framework import ChatAgent
from app.core.adapter import DualChatClient
from app.core.config import settings
from app.agents.shared_prompts import build_expert_prompt
from app.agents.registry import get_all_agent_configs
from app.rag.tools import create_rag_tool


def create_agent(config) -> ChatAgent:
    """Creates the Agriculture Expert from registry config."""
    client = DualChatClient()

    # Build prompt from registry config
    all_configs = get_all_agent_configs()
    other_agents = [c for c in all_configs if c.name != config.name]
    prompt = build_expert_prompt(config, other_agents)

    # Create RAG tool for this agent's domain
    tools = []
    if config.rag_collection:
        rag_tool = create_rag_tool(config.rag_collection)
        tools.append(rag_tool)

    return ChatAgent(
        name=config.name,
        description=config.description,
        instructions=prompt,
        chat_client=client,
        tools=tools,
    )
