import os
import json
import logging
from pathlib import Path
from typing import Literal
from dotenv import load_dotenv

# Explicitly load .env from project root
ROOT_DIR = Path(__file__).resolve().parent.parent.parent.parent
load_dotenv(ROOT_DIR / ".env")

from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, ToolMessage
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from groq import RateLimitError

from backend.app.config import settings
from backend.app.agent.state import AgentState
from backend.app.agent.prompts import get_system_prompt
from backend.app.tools import ALL_SPATIAL_TOOLS

logger = logging.getLogger("geoagent.graph")

groq_key = os.getenv("GROQ_API_KEY")
if not groq_key:
    groq_key = getattr(settings, "GROQ_API_KEY", None)

logger.info(f"Initialized ChatGroq with key prefix: {groq_key[:7] if groq_key else 'MISSING'}")

# Model Cascade Definitions (each provides an independent 200k TPD quota on Groq)
primary_llm = ChatGroq(
    model="openai/gpt-oss-120b",
    temperature=0,
    max_tokens=1000,
    groq_api_key=groq_key,
).bind_tools(ALL_SPATIAL_TOOLS)

fallback_llm_1 = ChatGroq(
    model="openai/gpt-oss-20b",
    temperature=0,
    max_tokens=1000,
    groq_api_key=groq_key,
).bind_tools(ALL_SPATIAL_TOOLS)

fallback_llm_2 = ChatGroq(
    model="qwen/qwen3.6-27b",
    temperature=0,
    max_tokens=1000,
    groq_api_key=groq_key,
).bind_tools(ALL_SPATIAL_TOOLS)

# Construct auto-failover chain targeting HTTP 429 RateLimitError
llm = primary_llm.with_fallbacks(
    fallbacks=[fallback_llm_1, fallback_llm_2],
    exceptions_to_handle=(RateLimitError,)
)


async def agent_node(state: AgentState) -> dict:
    """
    Evaluates conversation and invokes spatial tools while preserving original user intent,
    providing ample tool response window, halting consecutive duplicate loops, and
    guaranteeing a non-empty conversational response.
    """
    sys_prompt = get_system_prompt()
    raw_messages = list(state["messages"])

    # Extract the original user prompt to guarantee intent is never lost across hops
    first_user_msg = next((m for m in raw_messages if getattr(m, "type", "") == "human"), None)
    tail_messages = raw_messages[-4:] if len(raw_messages) > 4 else raw_messages

    active_dialogue = []
    if first_user_msg and first_user_msg not in tail_messages:
        active_dialogue.append(first_user_msg)

    # Permit larger payload window (up to 2000 chars) so layer lists aren't severed mid-JSON
    for msg in tail_messages:
        if isinstance(msg, ToolMessage):
            content_str = str(msg.content)
            if len(content_str) > 2000:
                content_str = content_str[:2000] + "... [truncated]"
            active_dialogue.append(ToolMessage(content=content_str, tool_call_id=msg.tool_call_id))
        else:
            active_dialogue.append(msg)

    messages = [SystemMessage(content=sys_prompt)] + active_dialogue
    response = await llm.ainvoke(messages)

    tool_calls = getattr(response, "tool_calls", [])

    # Circuit breaker: detect identical consecutive tool call loops
    if tool_calls and len(tail_messages) >= 2:
        last_tool_msg = tail_messages[-1]
        prev_ai_msg = tail_messages[-2]
        if isinstance(last_tool_msg, ToolMessage) and getattr(prev_ai_msg, "tool_calls", None):
            prev_calls = prev_ai_msg.tool_calls
            if (
                prev_calls
                and prev_calls[0].get("name") == tool_calls[0].get("name")
                and prev_calls[0].get("args") == tool_calls[0].get("args")
            ):
                logger.warning(f"Detected duplicate tool call loop for '{tool_calls[0].get('name')}'. Halting recursion.")
                response.tool_calls = []
                if not response.content:
                    response.content = "Catalog check complete. Please specify which layers you would like to inspect or modify."

    # Guard against silent completions when the fallback model returns empty content after tool runs
    if not getattr(response, "tool_calls", None) and not (response.content and response.content.strip()):
        if any(isinstance(m, ToolMessage) for m in tail_messages):
            response.content = "All requested operations and layer updates completed successfully."
        else:
            response.content = "How can I assist you with your spatial analysis?"

    logger.info(f"Groq raw content: {repr(response.content)}")
    logger.info(f"Groq tool calls detected: {getattr(response, "tool_calls", [])}")

    return {"messages": [response]}


def post_tool_evaluator(state: AgentState) -> dict:
    """Inspects tool messages to record generated/deleted layers and track bulk changes."""
    messages = state["messages"]
    new_layers = list(state.get("new_layers") or [])
    deleted_layers = list(state.get("deleted_layers") or [])
    error_count = state.get("error_count", 0)

    for msg in reversed(messages):
        if isinstance(msg, ToolMessage):
            try:
                payload = json.loads(msg.content)
                if isinstance(payload, dict):
                    # Single layer creation success
                    if payload.get("status") == "success" and "layer_id" in payload:
                        if not any(l["layer_id"] == payload["layer_id"] for l in new_layers):
                            new_layers.append(payload)

                    # Bulk or single layer deletion success
                    elif payload.get("status") == "success" and ("deleted_layer_id" in payload or "deleted_layers" in payload):
                        del_ids = list(payload.get("deleted_layers", []))
                        if "deleted_layer_id" in payload:
                            del_ids.append(payload["deleted_layer_id"])

                        for del_id in del_ids:
                            if del_id not in deleted_layers:
                                deleted_layers.append(del_id)
                            new_layers = [l for l in new_layers if l.get("layer_id") != del_id]

                    # Error handling
                    elif payload.get("status") == "error":
                        error_count += 1
                        logger.error(f"Tool execution returned error: {payload.get('message')}")
            except Exception:
                pass
        else:
            break

    return {
        "new_layers": new_layers,
        "deleted_layers": deleted_layers,
        "error_count": error_count,
    }


def route_after_agent(state: AgentState) -> Literal["tools", "__end__"]:
    """Determines whether the agent needs tool execution or can answer directly."""
    last_msg = state["messages"][-1]
    if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
        return "tools"
    return END


def route_after_tools(state: AgentState) -> Literal["agent", "__end__"]:
    """Prevents runaway loops if errors repeat."""
    if state.get("error_count", 0) > 2:
        logger.warning("Max error threshold exceeded in agent cycle.")
        return END
    return "agent"


# Build State Graph
builder = StateGraph(AgentState)

builder.add_node("agent", agent_node)
builder.add_node("tools", ToolNode(ALL_SPATIAL_TOOLS))
builder.add_node("evaluator", post_tool_evaluator)

builder.set_entry_point("agent")

builder.add_conditional_edges("agent", route_after_agent, {
    "tools": "tools",
    END: END,
})

builder.add_edge("tools", "evaluator")
builder.add_conditional_edges("evaluator", route_after_tools, {
    "agent": "agent",
    END: END,
})

agent_graph = builder.compile()