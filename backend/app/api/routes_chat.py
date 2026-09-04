import json
import logging
from typing import Optional, Dict, Any, List
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from langchain_core.messages import HumanMessage

from backend.app.agent.graph import agent_graph

logger = logging.getLogger("geoagent.chat")
router = APIRouter(prefix="/api/chat", tags=["chat"])

class ChatRequest(BaseModel):
    prompt: str
    viewport_bbox: Optional[Dict[str, float]] = None
    active_layers: Optional[List[str]] = []

@router.post("")
async def stream_agent_chat(request: ChatRequest):
    """
    Streams agent thoughts, tool calls, and created/deleted layers via Server-Sent Events (SSE).
    """
    async def sse_generator():
        initial_state = {
            "messages": [HumanMessage(content=request.prompt)],
            "viewport_bbox": request.viewport_bbox,
            "active_layers": request.active_layers or [],
            "new_layers": [],
            "error_count": 0
        }

        try:
            # Stream events using LangGraph v2 astream_events API
            async for event in agent_graph.astream_events(initial_state, version="v2"):
                kind = event["event"]

                # 1. Stream agent text tokens
                if kind == "on_chat_model_stream":
                    chunk = event["data"]["chunk"]
                    if hasattr(chunk, "content") and chunk.content:
                        payload = {"type": "token", "content": chunk.content}
                        yield f"data: {json.dumps(payload)}\n\n"

                # 2. Stream tool invocation announcements
                elif kind == "on_tool_start":
                    payload = {
                        "type": "tool_start",
                        "tool": event["name"],
                        "input": event["data"].get("input")
                    }
                    yield f"data: {json.dumps(payload)}\n\n"

                # 3. Stream tool execution completions, created layers, and deleted layers
                elif kind == "on_tool_end":
                    tool_output = event["data"].get("output")
                    output_data = None
                    try:
                        # Parse JSON string output if applicable
                        if hasattr(tool_output, "content"):
                            output_data = json.loads(tool_output.content)
                        elif isinstance(tool_output, str):
                            output_data = json.loads(tool_output)
                        elif isinstance(tool_output, dict):
                            output_data = tool_output
                    except Exception:
                        output_data = str(tool_output)

                    payload = {
                        "type": "tool_end",
                        "tool": event["name"],
                        "output": output_data
                    }
                    yield f"data: {json.dumps(payload)}\n\n"

                    # If this tool materialized a successful spatial layer, send immediate map trigger
                    if isinstance(output_data, dict) and output_data.get("status") == "success" and "layer_id" in output_data:
                        layer_event = {
                            "type": "new_layer",
                            "layer": output_data
                        }
                        yield f"data: {json.dumps(layer_event)}\n\n"

                    # If this tool deleted a spatial layer, send immediate map removal trigger
                    elif isinstance(output_data, dict) and output_data.get("status") == "success" and "deleted_layer_id" in output_data:
                        layer_event = {
                            "type": "delete_layer",
                            "layer_id": output_data["deleted_layer_id"]
                        }
                        yield f"data: {json.dumps(layer_event)}\n\n"

        except Exception as e:
            logger.error(f"Error during agent execution stream: {e}", exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

        yield "data: [DONE]\n\n"

    return StreamingResponse(
        sse_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )