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

from backend.app.config import settings
from backend.app.agent.state import AgentState
from backend.app.agent.prompts import get_system_prompt
from backend.app.tools import ALL_SPATIAL_TOOLS

logger = logging.getLogger("geoagent.graph")

groq_key = os.getenv("GROQ_API_KEY")
if not groq_key:
    groq_key = getattr(settings, "GROQ_API_KEY", None)

logger.info(f"Initialized ChatGroq with key prefix: {groq_key[:7] if groq_key else 'MISSING'}")

# Bind spatial tools to Groq model
llm = ChatGroq(
    model="openai/gpt-oss-20b",
    temperature=0,
    groq_api_key=groq_key,
).bind_tools(ALL_SPATIAL_TOOLS)


async def agent_node(state: AgentState) -> dict:
    """Evaluates conversation and invokes spatial tools with a tight 4-message window."""
    sys_prompt = get_system_prompt()

    # Limit message history to the last 4 messages to stay safely below the 8,000 TPM limit
    raw_messages = list(state["messages"])
    recent_messages = raw_messages[-4:] if len(raw_messages) > 4 else raw_messages

    # Trim leading orphaned ToolMessages if history was sliced mid-tool-call
    while recent_messages and isinstance(recent_messages[0], ToolMessage):
        recent_messages = recent_messages[1:]

    messages = [SystemMessage(content=sys_prompt)] + recent_messages

    response = await llm.ainvoke(messages)
    return {"messages": [response]}


def post_tool_evaluator(state: AgentState) -> dict:
    """Inspects tool messages to record generated/deleted layers and detect runtime errors."""
    messages = state["messages"]
    new_layers = list(state.get("new_layers") or [])
    deleted_layers = list(state.get("deleted_layers") or [])
    error_count = state.get("error_count", 0)

    for msg in reversed(messages):
        if isinstance(msg, ToolMessage):
            try:
                payload = json.loads(msg.content)
                if isinstance(payload, dict):
                    # Layer creation success
                    if payload.get("status") == "success" and "layer_id" in payload:
                        if not any(l["layer_id"] == payload["layer_id"] for l in new_layers):
                            new_layers.append(payload)
                    # Layer deletion success
                    elif payload.get("status") == "success" and "deleted_layer_id" in payload:
                        del_id = payload["deleted_layer_id"]
                        if del_id not in deleted_layers:
                            deleted_layers.append(del_id)
                        new_layers = [l for l in new_layers if l.get("layer_id") != del_id]
                    # Error detection and logging
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
    if state.get("error_count", 0) > 3:
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