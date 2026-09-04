import json
from typing import List, Dict, Any, Optional
from backend.app.tools.engine import spatial_engine

class LayerCatalogManager:
    """Manages discoverability and inspection of spatial datasets for the LLM agent."""

    @staticmethod
    def list_layers() -> List[Dict[str, Any]]:
        """Returns all registered layers with summary metadata."""
        rows = spatial_engine.con.execute("""
            SELECT layer_id, name, description, geom_type, feature_count, bbox_json, columns_json
            FROM spatial_catalog
            ORDER BY created_at DESC;
        """).fetchall()

        layers = []
        for r in rows:
            layers.append({
                "layer_id": r[0],
                "name": r[1],
                "description": r[2],
                "geom_type": r[3],
                "feature_count": r[4],
                "bbox": json.loads(r[5]) if r[5] else None,
                "columns": json.loads(r[6]) if r[6] else []
            })
        return layers

    @staticmethod
    def get_layer_details(layer_id: str) -> Optional[Dict[str, Any]]:
        """Returns detailed schema, bounds, and sample records for a layer."""
        row = spatial_engine.con.execute(f"""
            SELECT layer_id, name, description, geom_type, feature_count, bbox_json, columns_json
            FROM spatial_catalog
            WHERE layer_id = '{layer_id}';
        """).fetchone()

        if not row:
            return None

        # Sample 3 non-geometry rows for LLM context grounding
        sample_rows = spatial_engine.con.execute(f"""
            SELECT * EXCLUDE (geom)
            FROM {layer_id}
            LIMIT 3;
        """).fetchdf().to_dict(orient="records")

        return {
            "layer_id": row[0],
            "name": row[1],
            "description": row[2],
            "geom_type": row[3],
            "feature_count": row[4],
            "bbox": json.loads(row[5]) if row[5] else None,
            "columns": json.loads(row[6]) if row[6] else [],
            "sample_data": sample_rows
        }

    @staticmethod
    def get_catalog_summary_prompt() -> str:
        """Constructs a concise summary string to inject into the Agent's system context."""
        layers = LayerCatalogManager.list_layers()
        if not layers:
            return "No layers currently loaded in the database."

        summary_lines = ["Currently available active layers:"]
        for lyr in layers:
            summary_lines.append(
                f"- ID: `{lyr['layer_id']}` | Name: {lyr['name']} | Type: {lyr['geom_type']} | Features: {lyr['feature_count']} | Columns: {', '.join(lyr['columns'])}"
            )
        return "\n".join(summary_lines)

    @staticmethod
    def delete_layer(layer_id: str) -> bool:
        """Drops the layer table and deletes its metadata record from spatial_catalog."""
        try:
            spatial_engine.con.execute(f"DROP TABLE IF EXISTS {layer_id};")
            spatial_engine.con.execute(f"DELETE FROM spatial_catalog WHERE layer_id = '{layer_id}';")
            return True
        except Exception:
            return False

catalog_manager = LayerCatalogManager()