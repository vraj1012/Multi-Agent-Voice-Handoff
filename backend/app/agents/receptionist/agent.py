from agent_framework import ChatAgent
from app.core.adapter import DualChatClient
from app.agents.receptionist.prompts import build_receptionist_prompt
from app.agents.registry import get_all_agent_configs


def create_agent(config) -> ChatAgent:
    """Creates the Receptionist Agent from registry config.

    NOTE: Handoff tools are NOT passed here. The HandoffBuilder
    automatically registers handoff tools based on routing rules.
    """
    client = DualChatClient()

    # Get other agents for dynamic prompt generation
    all_configs = get_all_agent_configs()
    other_agents = [c for c in all_configs if c.name != config.name]

    prompt = build_receptionist_prompt(config, other_agents)

    return ChatAgent(
        name=config.name,
        description=config.description,
        instructions=prompt,
        chat_client=client,
    )
