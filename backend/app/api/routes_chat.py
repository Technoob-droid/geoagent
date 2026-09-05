import json
import logging
from typing import Optional, Dict, Any, List, Union
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from langchain_core.messages import HumanMessage

from backend.app.agent.graph import agent_graph

logger = logging.getLogger("geoagent.chat")
router = APIRouter(prefix="/api/chat", tags=["chat"])


class ChatRequest(BaseModel):
    # Support multiple possible field names from different client payloads
    prompt: Optional[str] = None
    message: Optional[str] = None
    query: Optional[str] = None
    viewport_bbox: Optional[Union[Dict[str, float], List[float], Any]] = None
    active_layers: Optional[List[str]] = Field(default_factory=list)

    def get_prompt_text(self) -> str:
        text = self.prompt or self.message or self.query
        if not text:
            return "Show all districts in West Bengal"
        return text.strip()


@router.post("")
async def stream_agent_chat(request: ChatRequest):
    """
    Streams agent thoughts, tool calls, and created/deleted layers via Server-Sent Events (SSE).
    Supports token streaming as well as full-message emission fallbacks.
    """
    user_prompt = request.get_prompt_text()

    # Normalize viewport_bbox if passed as an array [min_x, min_y, max_x, max_y]
    bbox_dict = None
    if isinstance(request.viewport_bbox, list) and len(request.viewport_bbox) == 4:
        bbox_dict = {
            "min_x": request.viewport_bbox[0],
            "min_y": request.viewport_bbox[1],
            "max_x": request.viewport_bbox[2],
            "max_y": request.viewport_bbox[3]
        }
    elif isinstance(request.viewport_bbox, dict):
        bbox_dict = request.viewport_bbox

    async def sse_generator():
        initial_state = {
            "messages": [HumanMessage(content=user_prompt)],
            "viewport_bbox": bbox_dict,
            "active_layers": request.active_layers or [],
            "new_layers": [],
            "error_count": 0
        }

        has_streamed_token = False

        try:
            async for event in agent_graph.astream_events(initial_state, version="v2"):
                kind = event["event"]

                # 1. Stream incremental text tokens
                if kind == "on_chat_model_stream":
                    chunk = event["data"]["chunk"]
                    if hasattr(chunk, "content") and chunk.content:
                        has_streamed_token = True
                        payload = {"type": "token", "content": chunk.content}
                        yield f"data: {json.dumps(payload)}\n\n"

                # 2. Fallback: If chat model completed in one shot without incremental tokens
                elif kind == "on_chat_model_end":
                    output = event["data"].get("output")
                    if output and hasattr(output, "content") and output.content and not has_streamed_token:
                        payload = {"type": "token", "content": output.content}
                        yield f"data: {json.dumps(payload)}\n\n"
                    has_streamed_token = False

                # 3. Stream tool invocation announcements
                elif kind == "on_tool_start":
                    payload = {
                        "type": "tool_start",
                        "tool": event["name"],
                        "input": event["data"].get("input")
                    }
                    yield f"data: {json.dumps(payload)}\n\n"

                # 4. Stream tool execution completions, created layers, and deleted layers
                elif kind == "on_tool_end":
                    tool_output = event["data"].get("output")
                    output_data = None
                    try:
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

                    # Trigger client map to add new layer
                    if isinstance(output_data, dict) and output_data.get("status") == "success" and "layer_id" in output_data:
                        layer_event = {
                            "type": "new_layer",
                            "layer": output_data
                        }
                        yield f"data: {json.dumps(layer_event)}\n\n"

                    # Trigger client map to remove layer
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