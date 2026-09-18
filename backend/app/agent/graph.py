import os
import json
import asyncio
import logging
from pathlib import Path
from typing import Literal
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent.parent.parent
load_dotenv(ROOT_DIR / ".env")

from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, ToolMessage
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from groq import RateLimitError, APIError

from backend.app.config import settings
from backend.app.agent.state import AgentState
from backend.app.agent.prompts import get_system_prompt
from backend.app.tools import ALL_SPATIAL_TOOLS

logger = logging.getLogger("geoagent.graph")

groq_key = os.getenv("GROQ_API_KEY")
if not groq_key:
    groq_key = getattr(settings, "GROQ_API_KEY", None)

logger.info(f"Initialized ChatGroq with key prefix: {groq_key[:7] if groq_key else 'MISSING'}")

# Model Cascade Definitions
primary_llm = ChatGroq(
    model="openai/gpt-oss-120b",
    temperature=0,
    max_tokens=1000,
    max_retries=0,
    groq_api_key=groq_key,
).bind_tools(ALL_SPATIAL_TOOLS)

fallback_llm_1 = ChatGroq(
    model="openai/gpt-oss-20b",
    temperature=0,
    max_tokens=1000,
    max_retries=0,
    groq_api_key=groq_key,
).bind_tools(ALL_SPATIAL_TOOLS)

# Use a valid Groq endpoint for fallback 2
fallback_llm_2 = ChatGroq(
    model="llama-3.1-8b-instant",
    temperature=0,
    max_tokens=1000,
    max_retries=0,
    groq_api_key=groq_key,
).bind_tools(ALL_SPATIAL_TOOLS)


async def agent_node(state: AgentState):
    """Executes the agent LLM decision step with schema-compliant message pruning."""
    raw_messages = state["messages"]

    # Prune tool response payloads while preserving tool name and call ID
    pruned_messages = []
    has_prior_tool = False
    for m in raw_messages:
        if getattr(m, "type", "") == "tool":
            has_prior_tool = True
            tool_name = getattr(m, "name", "tool_result") or "tool_result"
            try:
                data = json.loads(m.content)
                summary = {k: v for k, v in data.items() if k in ("status", "layer_id", "feature_count", "message")}
                pruned_messages.append(ToolMessage(
                    content=json.dumps(summary),
                    name=tool_name,
                    tool_call_id=m.tool_call_id
                ))
            except Exception:
                pruned_messages.append(ToolMessage(
                    content=str(m.content)[:250],
                    name=tool_name,
                    tool_call_id=m.tool_call_id
                ))
        else:
            pruned_messages.append(m)

    tail_messages = pruned_messages[-3:] if len(pruned_messages) > 3 else pruned_messages
    system_prompt = get_system_prompt()
    messages = [SystemMessage(content=system_prompt)] + tail_messages

    if has_prior_tool:
        logger.info("Applying 8s buffer to respect rolling TPM quota...")
        await asyncio.sleep(8)

    for llm_instance in [primary_llm, fallback_llm_1, fallback_llm_2]:
        try:
            response = await llm_instance.ainvoke(messages)
            return {"messages": [response]}
        except RateLimitError as e:
            logger.warning(f"Rate limit hit on {llm_instance.model_name}: {e}. Trying next...")
            await asyncio.sleep(2)
            continue
        except Exception as e:
            logger.error(f"Error calling {llm_instance.model_name}: {e}")
            continue

    logger.warning("All models throttled. Cooldown for 25s before final primary attempt...")
    await asyncio.sleep(25)
    response = await primary_llm.ainvoke(messages)
    return {"messages": [response]}


def should_continue(state: AgentState) -> Literal["tools", END]:
    """Determines whether another tool call is needed or if generation is complete."""
    last_message = state["messages"][-1]
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "tools"
    return END


workflow = StateGraph(AgentState)
workflow.add_node("agent", agent_node)
workflow.add_node("tools", ToolNode(ALL_SPATIAL_TOOLS))

workflow.set_entry_point("agent")
workflow.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
workflow.add_edge("tools", "agent")

agent_graph = workflow.compile()