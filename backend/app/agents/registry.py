"""Agent Registry — Dynamic Agent Discovery & Mesh Configuration."""

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
        """Initialize AgentConfig."""
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


# AGENT REGISTRY — Edit this list to rebrand/white-label the system
AGENT_REGISTRY: list[AgentConfig] = [
    AgentConfig(
        name="Kate",
        factory="app.agents.receptionist.agent.create_agent",
        is_start_agent=True,
        handoff_targets=None,  # Can hand off to ALL other agents
        voice_key="Amitabh_Bachchan_general",  # Audio prompt for voice cloning
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
        voice_key="emily_tech",  # Audio prompt for voice cloning
        domain_keywords=[
            "AI", "Machine Learning", "Coding", "Python", "Computers",
            "Error", "Bug", "Debug", "Software", "Hardware", "Tech",
            "Deploy", "Server", "Database", "API", "Network",
            "Security", "Protocol", "Password", "Program", "System",
            "cybersecurity", "neural networks", "data science",
            "error 999", "diagnose", "traceback", "fix error",
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
        voice_key="sophia_agri",  # Audio prompt for voice cloning
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

]


def load_agents() -> dict[str, ChatAgent]:
    """Dynamically import and instantiate all registered agents."""
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
    """Build handoff rules from registry config."""
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
    """Build agent-name-to-voice-key mapping from registry."""
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
