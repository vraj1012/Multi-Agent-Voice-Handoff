"""Orchestration Service — White-labeled multi-agent handoff workflow."""
import re
import logging
from typing import Optional, List

from agent_framework import (
    HandoffBuilder, HandoffAgentUserRequest, WorkflowOutputEvent,
    RequestInfoEvent, HandoffSentEvent, AgentRunUpdateEvent,
    Workflow, ChatAgent,
)
from app.agents.registry import load_agents, get_start_agent_name, get_handoff_rules

logger = logging.getLogger(__name__)


def _extract_response(events: list, agents: Optional[dict] = None) -> dict:
    """Extract agent name, response text, and handoff info from workflow events."""
    agent_name = "Unknown"
    response_text = ""
    handoff_occurred = False
    handoff_target = None
    pending_requests = []

    for event in events:
        if isinstance(event, HandoffSentEvent):
            handoff_occurred = True

        if isinstance(event, AgentRunUpdateEvent):
            data = event.data
            text = getattr(data, 'text', None)
            author = getattr(data, 'author_name', None) or getattr(event, 'executor_id', None)
            if text:
                response_text = text
                if author:
                    agent_name = author

            for content in (getattr(data, 'contents', []) or []):
                func_name = ''
                for attr in ('function_name', 'name', 'tool_name'):
                    val = getattr(content, attr, None)
                    if val and isinstance(val, str) and val.strip():
                        func_name = val.strip()
                        break
                if func_name.startswith('handoff_to_'):
                    handoff_occurred = True
                    target_candidate = func_name.replace('handoff_to_', '')
                    
                    # Case-insensitive agent lookup
                    handoff_target = None
                    if agents:
                        for name in agents.keys():
                            if name.lower() == target_candidate.lower():
                                handoff_target = name
                                break
                    
                    if not handoff_target:
                        handoff_target = target_candidate # Fallback
                        
                    logger.info(f"Handoff detected: {author} -> {handoff_target}")

        if isinstance(event, RequestInfoEvent):
            request_data = event.data
            if isinstance(request_data, HandoffAgentUserRequest):
                pending_requests.append(event)
                if request_data.agent_response:
                    resp_text = getattr(request_data.agent_response, 'text', None)
                    if resp_text:
                        response_text = resp_text
                    for msg in reversed(getattr(request_data.agent_response, 'messages', [])):
                        txt = getattr(msg, 'text', None)
                        author = getattr(msg, 'author_name', None)
                        if txt:
                            response_text = txt
                            if author:
                                agent_name = author
                            break
                if agent_name == "Unknown":
                    agent_name = event.source_executor_id or agent_name

    return {
        "agent": agent_name, "message": response_text,
        "handoff_occurred": handoff_occurred, "handoff_target": handoff_target,
        "_pending_requests": pending_requests,
    }


class OrchestrationService:
    """Manages multi-agent handoff workflow. Config-driven via registry.py."""

    def __init__(self):
        logger.info("Initializing OrchestrationService...")
        self.agents: dict[str, ChatAgent] = load_agents()
        self.start_agent_name: str = get_start_agent_name()
        self.handoff_rules: dict[str, list[str]] = get_handoff_rules()

        logger.info(f"Agents: {list(self.agents.keys())}, start: {self.start_agent_name}")

        self.active_agent_name = self.start_agent_name
        self.workflow: Workflow = self._build_workflow()
        self._pending_requests: List = []
        self._is_started = False

    def _build_workflow(self) -> Workflow:
        """Build HandoffBuilder workflow from registry config."""
        builder = HandoffBuilder(
            name="voice_agent_handoff",
            participants=list(self.agents.values()),
        ).with_start_agent(self.agents[self.active_agent_name])

        for source_name, target_names in self.handoff_rules.items():
            source = self.agents[source_name]
            targets = [self.agents[t] for t in target_names if t in self.agents]
            if targets:
                builder = builder.add_handoff(source, targets)

        return builder.build()

    async def process_message(self, user_message: str) -> dict:
        """Process user message through handoff workflow."""
        MAX_TURNS = 3
        current_message = user_message
        agent_messages: List[dict] = []
        handoff_occurred = False
        handoff_target = None
        handoff_source = None
        consecutive_handoffs = 0  # Guard against handoff ping-pong loops

        try:
            for turn in range(MAX_TURNS):
                events = []

                if not self._is_started:
                    async for event in self.workflow.run_stream(current_message):
                        events.append(event)
                    self._is_started = True
                elif self._pending_requests:
                    responses = {
                        req.request_id: HandoffAgentUserRequest.create_response(current_message)
                        for req in self._pending_requests
                    }
                    async for event in self.workflow.send_responses_streaming(responses):
                        events.append(event)
                else:
                    break

                result = _extract_response(events, self.agents)
                self._pending_requests = result.pop("_pending_requests", [])

                result_agent = result['agent']
                result_text = result['message']

                if result_text and result_text.strip():
                    valid_agent = result_agent if result_agent != "Unknown" else "System"
                    if agent_messages and agent_messages[-1]["agent"] == valid_agent:
                        agent_messages[-1]["text"] += " " + result_text.strip()
                    else:
                        agent_messages.append({"agent": valid_agent, "text": result_text.strip()})

                if result['handoff_occurred']:
                    handoff_occurred = True
                    handoff_target = result.get('handoff_target')
                    handoff_source = self.active_agent_name
                    consecutive_handoffs += 1
                    logger.info(f"Handoff: {handoff_source} -> {handoff_target} (chain #{consecutive_handoffs})")

                    if handoff_target not in self.agents:
                        logger.error(f"Unknown handoff target: {handoff_target}")
                        break

                    # Break handoff loops: if we've already had 2+ consecutive handoffs,
                    # stop bouncing — the current target must answer
                    if consecutive_handoffs >= 2:
                        logger.warning(f"Handoff loop detected ({consecutive_handoffs} consecutive). Forcing {handoff_target} to answer.")
                        break

                    source_announcement = result_text.strip() if result_text else ""

                    self.active_agent_name = handoff_target
                    self.workflow = self._build_workflow()
                    self._is_started = False
                    self._pending_requests = []

                    # Strip system tags and topic-switch phrasing
                    clean = re.sub(r'\[TOPIC SWITCH:.*?\]\s*', '', user_message, flags=re.DOTALL)
                    clean = re.sub(r'\[INTERRUPTED:.*?\]\s*', '', clean, flags=re.DOTALL)
                    clean = re.sub(r'\[FAREWELL:.*?\]\s*', '', clean, flags=re.DOTALL)
                    clean = re.sub(r'\b(switch to|instead of|never mind|forget that)\b', '', clean, flags=re.IGNORECASE)
                    clean = re.sub(r'\s+', ' ', clean).strip()

                    current_message = (
                        f"[HANDOFF CONTEXT: You have been transferred this conversation by {handoff_source}. "
                        f"{handoff_source} said: \"{source_announcement}\". "
                        f"{handoff_source} routed this question to YOU because it is in your area of expertise. "
                        f"Answer the user's question directly. Do NOT hand off back to {handoff_source} for this question. "
                        f"Only use handoff tools if a FUTURE question is clearly in a DIFFERENT agent's domain "
                        f"(not {handoff_source}'s).]\n\n"
                        f"User's question: {clean}"
                    )
                    continue
                else:
                    consecutive_handoffs = 0  # Reset on non-handoff turn
                    break

            final_agent = agent_messages[-1]["agent"] if agent_messages else "System"
            combined = " ".join(m["text"] for m in agent_messages).strip()

            logger.info(f"Response: {len(agent_messages)} message(s), agent: {final_agent}")

            return {
                "agent": final_agent, "message": combined,
                "messages": agent_messages,
                "handoff_occurred": handoff_occurred,
                "handoff_target": handoff_target,
                "handoff_source": handoff_source,
            }

        except Exception as e:
            logger.error(f"Error processing message: {e}", exc_info=True)
            return {
                "agent": "System",
                "message": "I'm sorry, something went wrong.",
                "messages": [{"agent": "System", "text": "I'm sorry, something went wrong."}],
                "handoff_occurred": False,
            }

    def reset(self):
        """Reset for a new conversation."""
        self.active_agent_name = self.start_agent_name
        self._pending_requests = []
        self._is_started = False
        self.workflow = self._build_workflow()


_orchestration_service: Optional[OrchestrationService] = None

def get_orchestration_service() -> OrchestrationService:
    global _orchestration_service
    if _orchestration_service is None:
        _orchestration_service = OrchestrationService()
    return _orchestration_service
