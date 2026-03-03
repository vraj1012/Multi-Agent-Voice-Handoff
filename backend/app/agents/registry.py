"""
Agent Registry — Dynamic Agent Discovery & Mesh Configuration

This is the SINGLE SOURCE OF TRUTH for all agent identity in the system.
To white-label: edit ONLY this file to change names, domains, voices, and personas.

To add a new agent:
    1. Create a new folder in backend/app/agents/<agent_name>/
    2. Add agent.py with a create_agent(config) function
    3. Register it in AGENT_REGISTRY below

To remove an agent:
    1. Remove its entry from AGENT_REGISTRY
    2. (Optional) Delete the agent folder

The orchestration service reads this registry to dynamically build
the HandoffBuilder workflow — no changes needed in orchestration.py.
"""

from typing import Callable, Optional
from agent_framework import ChatAgent


class AgentConfig:
    """Configuration for a single agent in the mesh."""

    def __init__(
        self,
        name: str,
        factory: str,
        is_start_agent: bool = False,
        handoff_targets: Optional[list[str]] = None,
        # --- White-label fields ---
        voice_key: Optional[str] = None,
        domain_keywords: Optional[list[str]] = None,
        description: str = "",
        persona_style: str = "",
        greeting_examples: Optional[list[str]] = None,
        farewell_example: str = "",
        rag_collection: Optional[str] = None,
        knowledge_base_path: Optional[str] = None,
    ):
        """
        Args:
            name: Unique agent name (must match ChatAgent.name)
            factory: Import path to the create_agent() function,
                     e.g. "app.agents.receptionist.agent.create_agent"
            is_start_agent: If True, this agent is the entry point for conversations
            handoff_targets: List of agent names this agent can hand off to.
                           If None, defaults to ALL other agents (full mesh).
            voice_key: TTS voice preset key (e.g. "en-Grace_woman"). None = default voice.
            domain_keywords: Keywords that define this agent's expertise domain.
            description: Short description for LLM tool routing.
            persona_style: Personality descriptor (e.g. "warm and enthusiastic").
            greeting_examples: Example greetings for persona consistency.
            farewell_example: Example farewell message for this agent.
            rag_collection: ChromaDB collection name for this agent's knowledge base.
            knowledge_base_path: Path to knowledge base directory for ingestion.
        """
        self.name = name
        self.factory = factory
        self.is_start_agent = is_start_agent
        self.handoff_targets = handoff_targets
        self.voice_key = voice_key
        self.domain_keywords = domain_keywords or []
        self.description = description
        self.persona_style = persona_style
        self.greeting_examples = greeting_examples or []
        self.farewell_example = farewell_example
        self.rag_collection = rag_collection
        self.knowledge_base_path = knowledge_base_path


# =========================================================================
# AGENT REGISTRY — Edit this list to rebrand/white-label the system
# =========================================================================
AGENT_REGISTRY: list[AgentConfig] = [
    AgentConfig(
        name="Kate",
        factory="app.agents.receptionist.agent.create_agent",
        is_start_agent=True,
        handoff_targets=None,  # Can hand off to ALL other agents
        voice_key="en-Grace_woman",
        domain_keywords=[],  # Router — no domain of its own
        description="Front-desk receptionist that greets users and routes them to the appropriate specialist agent.",
        persona_style="friendly, warm, welcoming receptionist",
        greeting_examples=[
            "Hey! What can I do for you?",
            "Oh sure, let me get the right person for you!",
        ],
        farewell_example="It was so nice chatting with you! Have a wonderful day!",
    ),
    AgentConfig(
        name="Emily",
        factory="app.agents.technical_expert.agent.create_agent",
        is_start_agent=False,
        handoff_targets=None,  # Can hand off to ALL other agents
        voice_key="en-Emma_woman",
        domain_keywords=[
            "AI", "Machine Learning", "Coding", "Python", "Computers",
            "Error", "Bug", "Debug", "Software", "Hardware", "Tech",
            "Deploy", "Server", "Database", "API", "Network",
            "Security", "Protocol", "Password", "Program", "System",
            "cybersecurity", "neural networks", "data science",
        ],
        description="Technical Expert specializing in AI, ML, cybersecurity, and software development.",
        persona_style="warm, enthusiastic, deeply knowledgeable tech expert who loves explaining things in an approachable way",
        greeting_examples=[
            "Hey there! I'm Emily!",
            "Oh, great question!",
            "That's a fascinating topic!",
        ],
        farewell_example="It was awesome chatting with you! Take care and keep exploring tech!",
        rag_collection="technical_collection",
        knowledge_base_path="./knowledge/technical",
    ),
    AgentConfig(
        name="Sophia",
        factory="app.agents.agriculture_expert.agent.create_agent",
        is_start_agent=False,
        handoff_targets=None,  # Can hand off to ALL other agents
        voice_key="pt-Spk0_woman",
        domain_keywords=[
            "Plants", "Soil", "Farming", "Crops", "Agriculture",
            "pest control", "irrigation", "fertilizers", "plant diseases",
            "livestock", "gardening",
        ],
        description="Agriculture Expert specializing in crops, soil health, pest control, and farming techniques.",
        persona_style="warm, down-to-earth, genuinely passionate farming expert who shares tips like a friendly neighbor",
        greeting_examples=[
            "Hey! I'm Sophia!",
            "Oh, love that question!",
            "Farming is so rewarding!",
        ],
        farewell_example="It was so lovely chatting with you! Happy farming and take care!",
        rag_collection="agriculture_collection",
        knowledge_base_path="./knowledge/agriculture",
    ),
    # --- ADD NEW AGENTS HERE ---
    # AgentConfig(
    #     name="Alex",
    #     factory="app.agents.finance_expert.agent.create_agent",
    #     is_start_agent=False,
    #     handoff_targets=None,
    #     voice_key="en-Alex_man",
    #     domain_keywords=["Finance", "Stocks", "Investing", "Accounting"],
    #     description="Finance Expert specializing in investments and accounting.",
    #     persona_style="confident, clear, and professional finance advisor",
    #     greeting_examples=["Hey! I'm Alex!", "Great question about finance!"],
    #     farewell_example="Great chatting! Best of luck with your investments!",
    #     rag_collection="finance_collection",
    #     knowledge_base_path="./knowledge/finance",
    # ),
]


def load_agents() -> dict[str, ChatAgent]:
    """
    Dynamically import and instantiate all registered agents.
    Returns a dict of {agent_name: ChatAgent instance}.
    """
    import importlib

    agents = {}
    for config in AGENT_REGISTRY:
        # Dynamic import: "app.agents.receptionist.agent.create_agent"
        module_path, func_name = config.factory.rsplit(".", 1)
        module = importlib.import_module(module_path)
        factory_fn = getattr(module, func_name)

        agent = factory_fn(config)
        agents[config.name] = agent

    return agents


def get_start_agent_name() -> str:
    """Get the name of the designated start agent."""
    for config in AGENT_REGISTRY:
        if config.is_start_agent:
            return config.name
    # Fallback to first agent
    return AGENT_REGISTRY[0].name


def get_handoff_rules() -> dict[str, list[str]]:
    """
    Build handoff rules from registry config.
    Returns {source_agent_name: [target_agent_name, ...]}

    If an agent's handoff_targets is None, it gets full mesh (all others).
    """
    all_names = [c.name for c in AGENT_REGISTRY]
    rules = {}

    for config in AGENT_REGISTRY:
        if config.handoff_targets is None:
            # Full mesh — can hand off to every other agent
            rules[config.name] = [n for n in all_names if n != config.name]
        else:
            rules[config.name] = config.handoff_targets

    return rules


def get_agent_voice_map() -> dict[str, str]:
    """
    Build agent-name-to-voice-key mapping from registry.
    Used by VoiceOrchestrator to assign TTS voices.
    Returns {agent_name: voice_key} (only agents with a voice_key set).
    """
    return {
        config.name: config.voice_key
        for config in AGENT_REGISTRY
        if config.voice_key
    }


def get_agent_config_by_name(name: str) -> Optional[AgentConfig]:
    """Look up an agent's config by name."""
    for config in AGENT_REGISTRY:
        if config.name == name:
            return config
    return None


def get_all_agent_configs() -> list[AgentConfig]:
    """Return the full registry list."""
    return AGENT_REGISTRY
