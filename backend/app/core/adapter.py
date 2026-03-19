"""DualChatClient — Universal LLM adapter for Azure/Gemini/Ollama."""
import json
import logging
from typing import Any, List, Optional

from agent_framework import BaseChatClient, FunctionCallContent, TextContent
from agent_framework._types import ChatMessage, ChatResponse, ChatResponseUpdate, Role

from app.core.config import settings
import openai
from openai import AsyncAzureOpenAI, AsyncOpenAI
import google.generativeai as genai

logger = logging.getLogger(__name__)


class DualChatClient(BaseChatClient):
    """Universal LLM adapter supporting Azure, Gemini, and Ollama."""
    __function_invoking_chat_client__ = True

    def __init__(self):
        super().__init__()
        self.provider = settings.LLM_PROVIDER.upper()
        self.azure_client = None
        self.openai_client = None

        if self.provider == "GEMINI":
            genai.configure(api_key=settings.GEMINI_API_KEY)
        elif self.provider == "OLLAMA":
            self.openai_client = AsyncOpenAI(base_url=settings.OLLAMA_URL, api_key="ollama")
        elif self.provider == "AZURE":
            self.azure_client = AsyncAzureOpenAI(
                api_key=settings.AZURE_OPENAI_API_KEY,
                api_version=settings.AZURE_OPENAI_API_VERSION,
                azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
            )

    # Non-streaming (batch)

    async def _inner_get_response(self, messages: List[ChatMessage], *, options: Optional[Any] = None, **kwargs) -> ChatResponse:
        tools = kwargs.get("tools", None)
        tool_choice = kwargs.get("tool_choice", None)
        if options and isinstance(options, dict):
            tools = options.get("tools", tools)
            tool_choice = options.get("tool_choice", tool_choice)
        elif options and hasattr(options, "tools"):
            tools = options.tools

        final_tools = self._convert_tools(tools) if tools else None
        prepared = self._prepare_messages(messages)

        if self.provider == "GEMINI":
            text, tc = await self._run_gemini(prepared)
        elif self.provider == "OLLAMA":
            text, tc = await self._run_ollama(prepared)
        else:
            text, tc = await self._run_azure(prepared, final_tools, tool_choice)

        msg = ChatMessage(role=Role.ASSISTANT, text=text or "")
        if tc:
            msg.tool_calls = tc
            msg.additional_properties = msg.additional_properties or {}
            msg.additional_properties["tool_calls"] = tc
        return ChatResponse(messages=[msg])

    # Streaming (with internal tool execution loop)

    async def _inner_get_streaming_response(self, messages, *, options=None, **kwargs):
        raw_tools = kwargs.get("tools", None)
        tool_choice = kwargs.get("tool_choice", None)
        if options and isinstance(options, dict):
            raw_tools = options.get("tools", raw_tools)
            tool_choice = options.get("tool_choice", tool_choice)
        elif options and hasattr(options, "tools"):
            raw_tools = options.tools

        azure_tools, tool_map = self._build_tool_registry(raw_tools)
        prepared = self._prepare_messages(messages)
        
        if azure_tools:
            logger.info(f"DualChatClient: Tool calling available with {len(azure_tools)} tools.")
        else:
            logger.warning("DualChatClient: NO TOOLS found in streaming request context.")

        MAX_TOOL_ROUNDS = 5
        final_text = ""

        for round_num in range(MAX_TOOL_ROUNDS):
            if self.provider == "GEMINI":
                response_text, tool_calls = await self._run_gemini(prepared)
            elif self.provider == "OLLAMA":
                response_text, tool_calls = await self._run_ollama(prepared)
            else:
                response_text, tool_calls = await self._run_azure(prepared, azure_tools, tool_choice)
            
            response_text = response_text or ""

            handoff_calls, regular_calls = [], []
            if tool_calls:
                for tc in tool_calls:
                    name = tc.function.name if hasattr(tc, 'function') else ''
                    if name.startswith('handoff_to_') or name not in tool_map:
                        handoff_calls.append(tc)
                    else:
                        regular_calls.append(tc)

            # Execute regular tools internally and loop back
            if regular_calls and not handoff_calls:
                prepared.append({
                    "role": "assistant", "content": response_text or None,
                    "tool_calls": [
                        {"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                        for tc in regular_calls
                    ]
                })
                for tc in regular_calls:
                    try:
                        args = json.loads(tc.function.arguments) if isinstance(tc.function.arguments, str) else tc.function.arguments
                        result = tool_map[tc.function.name](**args)
                    except Exception as e:
                        result = f"Error: {e}"
                        logger.error(f"Tool error '{tc.function.name}': {e}")
                    prepared.append({"role": "tool", "content": str(result), "tool_call_id": tc.id})
                continue

            # Build final response with handoff tool calls
            final_text = response_text
            contents = []
            if final_text:
                contents.append(TextContent(text=final_text))

            for tc in handoff_calls:
                try:
                    name = tc.function.name if hasattr(tc, 'function') else ''
                    args = tc.function.arguments if hasattr(tc, 'function') else '{}'
                    if isinstance(args, str):
                        try: args = json.loads(args)
                        except: args = {}
                    fcc = FunctionCallContent(call_id=tc.id if hasattr(tc, 'id') else '', name=name, arguments=args)
                    if not hasattr(fcc, 'function_name') or not fcc.function_name:
                        fcc.function_name = name
                    contents.append(fcc)
                    logger.info(f"Handoff: {name}({args})")
                except Exception as e:
                    logger.warning(f"Failed to convert handoff call: {e}")

            yield ChatResponseUpdate(
                contents=contents if contents else [TextContent(text=final_text or "")],
                role=Role.ASSISTANT,
            )
            return

        yield ChatResponseUpdate(
            contents=[TextContent(text=final_text or "Could not formulate a response.")],
            role=Role.ASSISTANT,
        )

    # Provider implementations

    async def _run_azure(self, messages, tools=None, tool_choice=None):
        try:
            kwargs = {"model": settings.AZURE_DEPLOYMENT_NAME, "messages": messages, "temperature": 0.7}
            if tools: kwargs["tools"] = tools
            if tool_choice: kwargs["tool_choice"] = tool_choice
            response = await self.azure_client.chat.completions.create(**kwargs)
            msg = response.choices[0].message
            return msg.content, msg.tool_calls
        except Exception as e:
            logger.error(f"Azure error: {e}")
            if "content_filter" in str(e):
                return "I can't discuss that specific phrasing.", None
            return "I'm having trouble reaching the cloud.", None

    async def _run_gemini(self, messages):
        try:
            system = None
            history = []
            for m in messages:
                if m["role"] == "system": system = m["content"]
                elif m["role"] == "user": history.append({"role": "user", "parts": [m["content"]]})
                elif m["role"] == "assistant": history.append({"role": "model", "parts": [m["content"]]})
            model = genai.GenerativeModel(model_name="gemini-pro", system_instruction=system)
            result = await model.generate_content_async(contents=history)
            return result.text, None
        except Exception as e:
            logger.error(f"Gemini error: {e}")
            return "I'm having trouble right now.", None

    async def _run_ollama(self, messages):
        try:
            response = await self.openai_client.chat.completions.create(
                model=settings.OLLAMA_MODEL, messages=messages, temperature=0.7
            )
            return response.choices[0].message.content, None
        except Exception as e:
            logger.error(f"Ollama error: {e}")
            return "Local model is offline.", None

    # Helpers

    @staticmethod
    def _prepare_messages(messages):
        prepared = []
        for msg in messages:
            role = msg.role if hasattr(msg, 'role') else 'user'
            content = getattr(msg, 'text', None)
            if content is None and hasattr(msg, 'contents'):
                content = str(msg.contents)
            prepared.append({"role": str(role), "content": str(content)})
        return prepared

    @staticmethod
    def _convert_tools(tools):
        result = []
        for tool in tools:
            if hasattr(tool, "parameters"):
                try:
                    schema = tool.parameters() if callable(tool.parameters) else tool.parameters
                    result.append({"type": "function", "function": {"name": tool.name, "description": tool.description, "parameters": schema}})
                except Exception as e:
                    logger.warning(f"Tool conversion failed: {e}")
            elif isinstance(tool, dict):
                result.append(tool)
        return result

    @staticmethod
    def _build_tool_registry(raw_tools):
        if not raw_tools:
            return None, {}
        
        # Bolster handoff tool descriptions with domain keywords from registry
        from app.agents.registry import get_agent_config_by_name

        azure_tools = []
        tool_map = {}
        for tool in raw_tools:
            name = tool.name
            desc = tool.description
            
            # Bolster description if it's a handoff tool
            if name.startswith('handoff_to_'):
                target_name = name.replace('handoff_to_', '')
                config = get_agent_config_by_name(target_name)
                if config and config.domain_keywords:
                    keywords = ", ".join(config.domain_keywords)
                    desc = f"{desc}. MANDATORY use this tool for all questions about: {keywords}."

            if hasattr(tool, "parameters"):
                try:
                    schema = tool.parameters() if callable(tool.parameters) else tool.parameters
                    azure_tools.append({"type": "function", "function": {"name": name, "description": desc, "parameters": schema}})
                    if hasattr(tool, 'func'):
                        tool_map[name] = tool.func
                except Exception as e:
                    logger.warning(f"Tool conversion failed: {e}")
            elif isinstance(tool, dict):
                # If already a dict, try to bolster internal description
                if 'function' in tool and tool['function'].get('name', '').startswith('handoff_to_'):
                    orig_desc = tool['function'].get('description', '')
                    target_name = tool['function']['name'].replace('handoff_to_', '')
                    config = get_agent_config_by_name(target_name)
                    if config and config.domain_keywords:
                        keywords = ", ".join(config.domain_keywords)
                        tool['function']['description'] = f"{orig_desc}. MANDATORY use this tool for all questions about: {keywords}."
                azure_tools.append(tool)
        return azure_tools, tool_map
