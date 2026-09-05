import json
import logging
from typing import List, Dict, Any, Optional
from backend.app.tools.engine import spatial_engine

logger = logging.getLogger("geoagent.catalog")

# Base system catalog describing all pre-ingested administrative boundaries
ADMIN_BOUNDARIES_CATALOG = [
    {
        "layer_id": "india_states",
        "name": "India States & UTs (ADM1)",
        "description": "Administrative boundaries for all 36 States and Union Territories of India.",
        "geom_type": "MULTIPOLYGON",
        "feature_count": 36,
        "columns": ["state_name", "raw_state_name", "state_iso", "shape_id", "geom"],
        "is_system": True
    },
    {
        "layer_id": "india_districts",
        "name": "India Districts (ADM2)",
        "description": "Administrative boundaries for 735 Indian Districts with state ISO references.",
        "geom_type": "MULTIPOLYGON",
        "feature_count": 735,
        "columns": ["district_name", "raw_district_name", "state_iso", "shape_id", "geom"],
        "is_system": True
    },
    {
        "layer_id": "india_subdistricts",
        "name": "India Sub-districts / Tehsils (ADM3)",
        "description": "Administrative boundaries for 6,824 Sub-districts, Tehsils, and Taluks across India.",
        "geom_type": "MULTIPOLYGON",
        "feature_count": 6824,
        "columns": ["subdistrict_name", "raw_subdistrict_name", "parent_iso", "shape_id", "geom"],
        "is_system": True
    },
    {
        "layer_id": "india_cities",
        "name": "India Cities & Urban Settlements",
        "description": "Populated city centers, statutory towns, municipal corporations, and major urban agglomerations.",
        "geom_type": "POINT",
        "feature_count": 214,
        "columns": ["city_name", "state_name", "country", "feature_class", "population", "geom"],
        "is_system": True
    },
    {
        "layer_id": "india_villages",
        "name": "India Revenue Villages & Populated Places (ADM4)",
        "description": "557,995 rural revenue villages and populated places indexed with state codes.",
        "geom_type": "POINT",
        "feature_count": 557995,
        "columns": ["village_name", "raw_name", "state_code", "feature_code", "geom"],
        "is_system": True
    }
]


class CatalogManager:
    def __init__(self):
        self.engine = spatial_engine

    def list_layers(self) -> List[Dict[str, Any]]:
        """
        Lists all available layers, merging base administrative boundary layers
        with user-generated analytical layers stored in spatial_catalog.
        """
        layers = list(ADMIN_BOUNDARIES_CATALOG)

        try:
            rows = self.engine.con.execute("""
                SELECT layer_id, name, description, geom_type, feature_count, bbox_json, columns_json, created_at 
                FROM spatial_catalog 
                ORDER BY created_at DESC;
            """).fetchall()

            for r in rows:
                layers.append({
                    "layer_id": r[0],
                    "name": r[1],
                    "description": r[2],
                    "geom_type": r[3],
                    "feature_count": r[4],
                    "bbox": json.loads(r[5]) if r[5] else None,
                    "columns": json.loads(r[6]) if r[6] else [],
                    "created_at": str(r[7]),
                    "is_system": False
                })
        except Exception as e:
            logger.error(f"Error listing layers from spatial_catalog: {e}")

        return layers

    def get_layer_details(self, layer_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieves schema, feature counts, and column metadata for a specific layer.
        """
        for admin_layer in ADMIN_BOUNDARIES_CATALOG:
            if admin_layer["layer_id"] == layer_id:
                return admin_layer

        try:
            row = self.engine.con.execute(f"""
                SELECT layer_id, name, description, geom_type, feature_count, bbox_json, columns_json, created_at 
                FROM spatial_catalog 
                WHERE layer_id = '{layer_id}';
            """).fetchone()

            if row:
                return {
                    "layer_id": row[0],
                    "name": row[1],
                    "description": row[2],
                    "geom_type": row[3],
                    "feature_count": row[4],
                    "bbox": json.loads(row[5]) if row[5] else None,
                    "columns": json.loads(row[6]) if row[6] else [],
                    "created_at": str(row[7]),
                    "is_system": False
                }
        except Exception as e:
            logger.error(f"Error fetching details for layer '{layer_id}': {e}")

        return None

    def get_catalog_summary_for_llm(self) -> str:
        """
        Formats a compact catalog summary containing only active analytical layers
        (capped to the most recent 5) to keep token payloads strictly under 8,000 TPM limits.
        """
        all_layers = self.list_layers()
        if not all_layers:
            return "No analytical layers active."

        analytical_layers = [
            l for l in all_layers 
            if not l.get("is_system", False) and not l["layer_id"].startswith("india_")
        ]

        if not analytical_layers:
            return "No custom analytical layers created yet."

        recent_layers = analytical_layers[:5]
        summary_lines = []
        for l in recent_layers:
            desc = (l.get("description") or "User layer")[:50]
            summary_lines.append(
                f"- '{l['layer_id']}' ({l.get('geom_type', 'GEOMETRY')}, {l.get('feature_count', 0)} rows): {desc}"
            )
        return "\n".join(summary_lines)

    def get_catalog_summary_prompt(self) -> str:
        """Alias for prompt templates."""
        return self.get_catalog_summary_for_llm()


catalog_manager = CatalogManager()