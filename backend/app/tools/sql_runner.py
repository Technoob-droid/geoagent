import json
import re
from langchain_core.tools import tool
from backend.app.tools.engine import spatial_engine

FORBIDDEN_PATTERNS = [
    r"\bDROP\s+DATABASE\b",
    r"\bATTACH\b",
    r"\bDETACH\b",
    r"\bCOPY\b",
    r"\bEXPORT\b",
    r"\bINSTALL\b",
    r"\bLOAD\b",
    r"\bPRAGMA\b"
]

@tool
def run_spatial_sql(
    sql_query: str,
    output_layer_id: str,
    output_layer_name: str,
    description: str = ""
) -> str:
    """
    Executes an analytical DuckDB Spatial SQL query and saves the output as a named layer.
    
    CRITICAL REQUIREMENTS:
    1. The query MUST output a geometry column named 'geom' in EPSG:4326.
    2. Write read/filter/aggregate SQL (SELECT ... FROM ...).
    3. Do NOT include CREATE TABLE statements; the engine handles materialization automatically.
    """
    # Guard against destructive or system commands
    for pattern in FORBIDDEN_PATTERNS:
        if re.search(pattern, sql_query, re.IGNORECASE):
            return json.dumps({
                "status": "error",
                "error": f"Security violation: Query contains disallowed statement matching '{pattern}'."
            })

    if not re.search(r"\bSELECT\b", sql_query, re.IGNORECASE):
        return json.dumps({
            "status": "error",
            "error": "Invalid SQL: Query must be a SELECT statement."
        })

    res = spatial_engine.execute_spatial_query(
        query=sql_query,
        output_layer_id=output_layer_id,
        layer_name=output_layer_name,
        description=description
    )
    return json.dumps(res)