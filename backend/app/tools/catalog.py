import json
import logging
import difflib
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

    def resolve_layer_id(self, input_name: str) -> Optional[str]:
        """
        Resolves an input layer name or ID to an exact existing layer_id.
        Matches exact names/slugs, checks token set containment, and uses a strict
        0.80 cutoff for difflib to prevent unrelated prefix hijacking.
        """
        if not input_name:
            return None

        clean_input = input_name.strip().strip("'\"`").lower()
        slug_input = clean_input.replace(" ", "_").replace("-", "_")

        all_layers = self.list_layers()
        if not all_layers:
            return None

        # 1. Exact match against layer_id, display name, or slug
        for layer in all_layers:
            lid = layer["layer_id"].lower()
            lname = layer.get("name", "").lower()
            if clean_input in (lid, lname) or slug_input == lid:
                return layer["layer_id"]

        # 2. Token set containment
        input_tokens = set(clean_input.replace("_", " ").split())
        for layer in all_layers:
            lid_tokens = set(layer["layer_id"].lower().replace("_", " ").split())
            lname_tokens = set(layer.get("name", "").lower().replace("_", " ").split())
            if input_tokens == lid_tokens or (lname_tokens and input_tokens == lname_tokens):
                return layer["layer_id"]

        # 3. Fuzzy match candidates with strict 0.80 cutoff
        candidates = {}
        for layer in all_layers:
            candidates[layer["layer_id"].lower()] = layer["layer_id"]
            if layer.get("name"):
                candidates[layer["name"].lower()] = layer["layer_id"]

        matches = difflib.get_close_matches(clean_input, candidates.keys(), n=1, cutoff=0.80)
        if matches:
            return candidates[matches[0]]

        slug_matches = difflib.get_close_matches(slug_input, candidates.keys(), n=1, cutoff=0.80)
        if slug_matches:
            return candidates[slug_matches[0]]

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

    def register_layer(
        self,
        layer_id: str,
        name: str,
        table_name: str,
        geom_type: str,
        feature_count: int,
        description: Optional[str] = None
    ):
        """
        Registers or updates an analytical layer in the spatial_catalog table.
        """
        desc = description or f"User generated layer: {name}"
        try:
            # Ensure spatial_catalog table exists
            self.engine.con.execute("""
                CREATE TABLE IF NOT EXISTS spatial_catalog (
                    layer_id VARCHAR PRIMARY KEY,
                    name VARCHAR,
                    description VARCHAR,
                    geom_type VARCHAR,
                    feature_count BIGINT,
                    bbox_json VARCHAR,
                    columns_json VARCHAR,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)

            # Fetch columns from the materialized table
            cols = [
                r[0] for r in self.engine.con.execute(
                    f"SELECT column_name FROM information_schema.columns WHERE table_name = '{table_name}';"
                ).fetchall()
            ]

            # Upsert into spatial_catalog
            self.engine.con.execute(f"""
                DELETE FROM spatial_catalog WHERE layer_id = '{layer_id}';
                INSERT INTO spatial_catalog (layer_id, name, description, geom_type, feature_count, bbox_json, columns_json, created_at)
                VALUES (
                    '{layer_id}',
                    '{name.replace("'", "''")}',
                    '{desc.replace("'", "''")}',
                    '{geom_type}',
                    {feature_count},
                    NULL,
                    '{json.dumps(cols)}',
                    CURRENT_TIMESTAMP
                );
            """)
            logger.info(f"Registered layer '{layer_id}' in spatial_catalog ({feature_count} features).")
        except Exception as e:
            logger.error(f"Failed to register layer '{layer_id}': {e}")

    def add_layer(self, *args, **kwargs):
        """Alias for register_layer to prevent naming mismatches."""
        return self.register_layer(*args, **kwargs)

    def unregister_layer(self, layer_id: str):
        """Removes a layer from spatial_catalog."""
        try:
            self.engine.con.execute(f"DELETE FROM spatial_catalog WHERE layer_id = '{layer_id}';")
        except Exception as e:
            logger.error(f"Failed to unregister layer '{layer_id}': {e}")


catalog_manager = CatalogManager()