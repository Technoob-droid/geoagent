import logging
from typing import List, Dict, Any
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langchain_openai import ChatOpenAI  # Or your configured LLM provider
from backend.app.config import settings
from backend.app.tools.catalog import catalog_manager
from backend.app.tools.spatial_ops import (
    list_available_layers,
    get_layer_schema,
    filter_by_admin_boundary,
    find_near_place,
    buffer_layer,
    spatial_intersection,
    spatial_difference,
    spatial_filter_within,
    execute_custom_spatial_sql,
    delete_layer
)

logger = logging.getLogger("geoagent.planner")

TOOLS = [
    list_available_layers,
    get_layer_schema,
    filter_by_admin_boundary,
    find_near_place,
    buffer_layer,
    spatial_intersection,
    spatial_difference,
    spatial_filter_within,
    execute_custom_spatial_sql,
    delete_layer
]

SYSTEM_PROMPT_TEMPLATE = """You are GeoAgent, an autonomous GIS and geospatial analysis assistant specialized in Indian geography and spatial queries.

You have direct access to a high-performance DuckDB spatial database with multi-tier administrative boundaries and settlements:
- `india_states`: 36 States and Union Territories (ADM1 polygons)
- `india_districts`: 735 Districts (ADM2 polygons)
- `india_subdistricts`: 6,824 Sub-districts / Tehsils / Taluks (ADM3 polygons)
- `india_cities`: Populated cities and urban centers (points)
- `india_villages`: ~558,000 Revenue villages and rural settlements (points)

Current Database Catalog:
{catalog_summary}

Operational Guidelines:
1. **Administrative Queries**:
   - When asked for entities within a state, district, or tehsil (e.g., "villages in Pune", "cities in Maharashtra"), prefer `filter_by_admin_boundary`.
   - When asked for proximity (e.g., "cities within 50 km of Kolkata"), use `find_near_place`.
2. **Layer Naming Convention**:
   - Always choose clear, lowercase, underscore-separated `output_layer_id` names (e.g., `pune_villages`, `kolkata_buffer_50km`).
3. **Geometry & CRS Integrity**:
   - All spatial data is standardized in WGS84 (`EPSG:4326`).
4. **Execution Flow**:
   - Call the appropriate tool. Once the tool returns success, summarize the findings (total features found, layer ID created) and confirm it is visible on the map.
"""


class GeoAgentPlanner:
    def __init__(self):
        # Configure model based on settings
        self.llm = ChatOpenAI(
            model=getattr(settings, "LLM_MODEL", "gpt-4o"),
            temperature=0.1,
            api_key=getattr(settings, "OPENAI_API_KEY", None)
        )
        self.llm_with_tools = self.llm.bind_tools(TOOLS)

    def plan_and_execute(self, user_prompt: str, history: List[Dict[str, str]] = None) -> Dict[str, Any]:
        catalog_summary = catalog_manager.get_catalog_summary_for_llm()
        system_prompt = SYSTEM_PROMPT_TEMPLATE.format(catalog_summary=catalog_summary)

        messages = [SystemMessage(content=system_prompt)]

        if history:
            for msg in history:
                if msg.get("role") == "user":
                    messages.append(HumanMessage(content=msg["content"]))
                elif msg.get("role") == "assistant":
                    messages.append(AIMessage(content=msg["content"]))

        messages.append(HumanMessage(content=user_prompt))

        # 1. Agent planning step
        ai_msg = self.llm_with_tools.invoke(messages)
        messages.append(ai_msg)

        tool_calls = getattr(ai_msg, "tool_calls", [])
        results = []

        # 2. Tool dispatch loop
        tool_dict = {t.name: t for t in TOOLS}
        for tool_call in tool_calls:
            tool_name = tool_call["name"]
            tool_args = tool_call["args"]

            if tool_name in tool_dict:
                try:
                    tool_output = tool_dict[tool_name].invoke(tool_args)
                    results.append({
                        "tool": tool_name,
                        "args": tool_args,
                        "output": tool_output
                    })
                except Exception as e:
                    results.append({
                        "tool": tool_name,
                        "args": tool_args,
                        "error": str(e)
                    })

        # 3. Final synthesis
        if tool_calls:
            final_response = self.llm.invoke(messages + [
                HumanMessage(content=f"Tool execution results: {results}. Provide a concise response to the user.")
            ])
            return {
                "response": final_response.content,
                "tool_executions": results
            }

        return {
            "response": ai_msg.content,
            "tool_executions": []
        }


geo_agent = GeoAgentPlanner()