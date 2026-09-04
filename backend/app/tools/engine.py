import duckdb
import json
import logging
from typing import Dict, Any, Optional
from backend.app.config import settings

logger = logging.getLogger("geoagent.spatial_engine")

class DuckDBSpatialEngine:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or settings.DUCKDB_DATABASE_PATH
        self.con = duckdb.connect(self.db_path)
        self._init_spatial_extension()
        self._init_catalog_table()

    def _init_spatial_extension(self):
        """Installs and loads the DuckDB spatial extension."""
        try:
            self.con.execute("INSTALL spatial; LOAD spatial;")
            logger.info("DuckDB Spatial extension loaded successfully.")
        except Exception as e:
            logger.error(f"Failed to load spatial extension: {e}")
            raise

    def _init_catalog_table(self):
        """Initializes internal catalog tracking available analytical layers."""
        self.con.execute("""
            CREATE TABLE IF NOT EXISTS spatial_catalog (
                layer_id VARCHAR PRIMARY KEY,
                name VARCHAR,
                description VARCHAR,
                geom_type VARCHAR,
                feature_count INTEGER,
                bbox_json VARCHAR,
                columns_json VARCHAR,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

    def execute_spatial_query(
        self,
        query: str,
        output_layer_id: str,
        layer_name: str,
        description: str = ""
    ) -> Dict[str, Any]:
        """
        Executes a spatial query, stores the result as an in-database table,
        and computes feature count and extent (bounding box in WGS84).
        """
        try:
            # Drop old table if exists and materialize output
            self.con.execute(f"DROP TABLE IF EXISTS {output_layer_id};")
            self.con.execute(f"CREATE TABLE {output_layer_id} AS {query};")

            # Check feature count
            count_res = self.con.execute(f"SELECT COUNT(*) FROM {output_layer_id};").fetchone()
            count = count_res[0] if count_res else 0

            if count == 0:
                return {
                    "status": "warning",
                    "layer_id": output_layer_id,
                    "layer_name": layer_name,
                    "feature_count": 0,
                    "message": f"Query ran successfully but produced 0 features in '{output_layer_id}'."
                }

            # Inspect columns
            cols_info = self.con.execute(f"DESCRIBE {output_layer_id};").fetchall()
            columns = [c[0] for c in cols_info]
            geom_col = next((c for c in columns if c.lower() in ["geom", "geometry"]), None)

            if not geom_col:
                return {
                    "status": "error",
                    "error": f"Table '{output_layer_id}' was created but does not contain a 'geom' column."
                }

            # Extract 2D Bounding Box in WGS84
            bbox_query = f"""
                SELECT 
                    ST_XMin(ST_Extent({geom_col})) as minx,
                    ST_YMin(ST_Extent({geom_col})) as miny,
                    ST_XMax(ST_Extent({geom_col})) as maxx,
                    ST_YMax(ST_Extent({geom_col})) as maxy
                FROM {output_layer_id}
                WHERE {geom_col} IS NOT NULL;
            """
            bbox_row = self.con.execute(bbox_query).fetchone()
            bbox = {
                "minx": float(bbox_row[0]) if bbox_row and bbox_row[0] is not None else -180.0,
                "miny": float(bbox_row[1]) if bbox_row and bbox_row[1] is not None else -90.0,
                "maxx": float(bbox_row[2]) if bbox_row and bbox_row[2] is not None else 180.0,
                "maxy": float(bbox_row[3]) if bbox_row and bbox_row[3] is not None else 90.0,
            }

            # Detect geometry type (sample first row)
            geom_type_res = self.con.execute(
                f"SELECT ST_GeometryType({geom_col}) FROM {output_layer_id} WHERE {geom_col} IS NOT NULL LIMIT 1;"
            ).fetchone()
            geom_type = geom_type_res[0] if geom_type_res else "GEOMETRY"

            # Register/Update in spatial catalog
            self.con.execute(f"""
                INSERT OR REPLACE INTO spatial_catalog (
                    layer_id, name, description, geom_type, feature_count, bbox_json, columns_json
                ) VALUES (
                    '{output_layer_id}', 
                    '{layer_name}', 
                    '{description}', 
                    '{geom_type}', 
                    {count}, 
                    '{json.dumps(bbox)}', 
                    '{json.dumps(columns)}'
                );
            """)

            return {
                "status": "success",
                "layer_id": output_layer_id,
                "layer_name": layer_name,
                "geom_type": geom_type,
                "feature_count": count,
                "bbox": bbox,
                "columns": columns
            }

        except Exception as e:
            logger.error(f"Error executing spatial query: {e}")
            return {"status": "error", "error": str(e)}

    def get_layer_as_geojson(self, layer_id: str) -> Optional[Dict[str, Any]]:
        """
        Exports a materialized layer as a standard GeoJSON FeatureCollection.
        """
        try:
            # 1. Check table existence
            table_check = self.con.execute(f"""
                SELECT COUNT(*) 
                FROM information_schema.tables 
                WHERE table_name = '{layer_id}';
            """).fetchone()

            if not table_check or table_check[0] == 0:
                logger.warning(f"Table '{layer_id}' not found in database.")
                return None

            # 2. Extract column schema
            cols = [c[0] for c in self.con.execute(f"DESCRIBE {layer_id};").fetchall()]
            non_geom_cols = [c for c in cols if c.lower() not in ["geom", "geometry"]]
            
            quoted_non_geom = [f'"{c}"' for c in non_geom_cols]
            prop_select = ", ".join(quoted_non_geom) if quoted_non_geom else "NULL as _dummy"

            # 3. Retrieve attributes along with GeoJSON geometry string
            sql = f"""
                SELECT 
                    {prop_select},
                    ST_AsGeoJSON(geom) as geojson_geom
                FROM {layer_id}
                WHERE geom IS NOT NULL;
            """
            rows = self.con.execute(sql).fetchall()

            features = []
            for row in rows:
                geom_json_str = row[-1]
                if not geom_json_str:
                    continue

                props = {}
                if non_geom_cols:
                    for i, col_name in enumerate(non_geom_cols):
                        props[col_name] = row[i]

                features.append({
                    "type": "Feature",
                    "geometry": json.loads(geom_json_str),
                    "properties": props
                })

            return {
                "type": "FeatureCollection",
                "features": features
            }

        except Exception as e:
            logger.error(f"Error generating GeoJSON for layer '{layer_id}': {e}", exc_info=True)
            return None

# Singleton spatial engine instance
spatial_engine = DuckDBSpatialEngine()