from typing import Annotated, Sequence, TypedDict, List, Dict, Any, Optional
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

class AgentState(TypedDict):
    # Appends new messages without overwriting history
    messages: Annotated[Sequence[BaseMessage], add_messages]
    
    # Active map viewport bbox: {"minx": float, "miny": float, "maxx": float, "maxy": float}
    viewport_bbox: Optional[Dict[str, float]]
    
    # List of active layers currently displayed or available on the map
    active_layers: List[str]
    
    # Tracks newly materialized layers produced during the current turn
    new_layers: List[Dict[str, Any]]
    
    # Error counter to prevent infinite self-correction loops
    error_count: int