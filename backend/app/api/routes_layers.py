import io
import os
import json
import zipfile
import tempfile
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response, StreamingResponse
from backend.app.tools.engine import spatial_engine
from backend.app.tools.catalog import catalog_manager

router = APIRouter(prefix="/api/layers", tags=["layers"])

BOUNDARIES_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../data/boundaries")
).replace("\\", "/")

STATES_PARQUET = f"{BOUNDARIES_DIR}/states/india_states.parquet"
DISTRICTS_PARQUET = f"{BOUNDARIES_DIR}/districts/india_districts.parquet"
SUBDISTRICTS_PARQUET = f"{BOUNDARIES_DIR}/subdistricts/india_subdistricts.parquet"
CITIES_PARQUET = f"{BOUNDARIES_DIR}/cities/india_cities.parquet"
VILLAGES_PARQUET = f"{BOUNDARIES_DIR}/villages/india_villages.parquet"


@router.get("")
async def get_all_layers():
    """Returns metadata for all available layers in the spatial catalog."""
    return catalog_manager.list_layers()


@router.get("/resolver/search")
async def resolve_place(query: str = Query(..., min_length=2)):
    """
    Fuzzy searches Indian states, districts, sub-districts, cities, and villages.
    """
    conn = getattr(spatial_engine, "con", None) or getattr(spatial_engine, "conn", None)
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection unavailable.")

    clean_q = query.strip().replace("'", "''")

    sql = f"""
        SELECT 
            city_name AS name,
            state_name AS parent,
            'city' AS type,
            ST_X(geom) AS center_x,
            ST_Y(geom) AS center_y,
            ST_XMin(geom) AS min_x,
            ST_YMin(geom) AS min_y,
            ST_XMax(geom) AS max_x,
            ST_YMax(geom) AS max_y
        FROM read_parquet('{CITIES_PARQUET}')
        WHERE lower(city_name) LIKE lower('%{clean_q}%')
        UNION ALL
        SELECT 
            district_name AS name,
            state_iso AS parent,
            'district' AS type,
            ST_X(ST_Centroid(geom)) AS center_x,
            ST_Y(ST_Centroid(geom)) AS center_y,
            ST_XMin(geom) AS min_x,
            ST_YMin(geom) AS min_y,
            ST_XMax(geom) AS max_x,
            ST_YMax(geom) AS max_y
        FROM read_parquet('{DISTRICTS_PARQUET}')
        WHERE lower(district_name) LIKE lower('%{clean_q}%')
        UNION ALL
        SELECT 
            subdistrict_name AS name,
            parent_iso AS parent,
            'subdistrict' AS type,
            ST_X(ST_Centroid(geom)) AS center_x,
            ST_Y(ST_Centroid(geom)) AS center_y,
            ST_XMin(geom) AS min_x,
            ST_YMin(geom) AS min_y,
            ST_XMax(geom) AS max_x,
            ST_YMax(geom) AS max_y
        FROM read_parquet('{SUBDISTRICTS_PARQUET}')
        WHERE lower(subdistrict_name) LIKE lower('%{clean_q}%')
        UNION ALL
        SELECT 
            state_name AS name,
            'India' AS parent,
            'state' AS type,
            ST_X(ST_Centroid(geom)) AS center_x,
            ST_Y(ST_Centroid(geom)) AS center_y,
            ST_XMin(geom) AS min_x,
            ST_YMin(geom) AS min_y,
            ST_XMax(geom) AS max_x,
            ST_YMax(geom) AS max_y
        FROM read_parquet('{STATES_PARQUET}')
        WHERE lower(state_name) LIKE lower('%{clean_q}%')
        UNION ALL
        SELECT 
            village_name AS name,
            state_code AS parent,
            'village' AS type,
            ST_X(geom) AS center_x,
            ST_Y(geom) AS center_y,
            ST_X(geom) AS min_x,
            ST_Y(geom) AS min_y,
            ST_X(geom) AS max_x,
            ST_Y(geom) AS max_y
        FROM read_parquet('{VILLAGES_PARQUET}')
        WHERE lower(village_name) LIKE lower('{clean_q}%')
        LIMIT 10;
    """
    try:
        rows = conn.execute(sql).df().to_dict(orient="records")
        return {"results": rows}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Resolver search failed: {str(e)}")


@router.get("/boundaries/query")
async def query_boundaries_by_bbox(
    level: str = Query("states", pattern="^(states|districts|subdistricts|cities|villages)$"),
    min_x: float = Query(...),
    min_y: float = Query(...),
    max_x: float = Query(...),
    max_y: float = Query(...)
):
    """
    Dynamic spatial viewport streaming across all administrative and settlement tiers.
    """
    conn = getattr(spatial_engine, "con", None) or getattr(spatial_engine, "conn", None)
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection unavailable.")

    if level == "states":
        parquet_file = STATES_PARQUET
        name_col = "state_name"
        extra_cols = "state_iso, shape_id,"
    elif level == "districts":
        parquet_file = DISTRICTS_PARQUET
        name_col = "district_name"
        extra_cols = "state_iso, shape_id,"
    elif level == "subdistricts":
        parquet_file = SUBDISTRICTS_PARQUET
        name_col = "subdistrict_name"
        extra_cols = "parent_iso AS state_iso, shape_id,"
    elif level == "cities":
        parquet_file = CITIES_PARQUET
        name_col = "city_name"
        extra_cols = "state_name AS state_iso, feature_class AS shape_id,"
    else:
        parquet_file = VILLAGES_PARQUET
        name_col = "village_name"
        extra_cols = "state_code AS state_iso, feature_code AS shape_id,"

    sql = f"""
        SELECT 
            {name_col} AS name,
            {extra_cols}
            ST_AsGeoJSON(geom) AS geojson_geom
        FROM read_parquet('{parquet_file}')
        WHERE ST_Intersects(
            geom, 
            ST_MakeEnvelope({min_x}, {min_y}, {max_x}, {max_y})
        )
        LIMIT 500;
    """

    try:
        df = conn.execute(sql).df()
        features = []
        for _, row in df.iterrows():
            try:
                geometry = json.loads(row["geojson_geom"])
            except Exception:
                continue

            features.append({
                "type": "Feature",
                "geometry": geometry,
                "properties": {
                    "name": row["name"],
                    "state_iso": row.get("state_iso", ""),
                    "shape_id": row.get("shape_id", ""),
                    "level": level
                }
            })

        return {
            "type": "FeatureCollection",
            "features": features
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Boundary query failed: {str(e)}")


@router.get("/{layer_id}/geojson")
async def get_layer_geojson(layer_id: str):
    """
    Returns the complete GeoJSON FeatureCollection for an administrative view 
    or materialized user analytical layer.
    """
    geojson_data = spatial_engine.get_layer_as_geojson(layer_id)
    if not geojson_data:
        raise HTTPException(
            status_code=404,
            detail=f"Layer '{layer_id}' not found or contains no valid geometry."
        )
    return geojson_data