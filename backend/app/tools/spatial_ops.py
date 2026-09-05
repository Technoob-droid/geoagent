import json
import logging
from typing import Optional
from langchain_core.tools import tool
from backend.app.tools.engine import spatial_engine
from backend.app.tools.catalog import catalog_manager

logger = logging.getLogger("geoagent.tools")

SYSTEM_ADMIN_LAYERS = {
    "india_states",
    "india_districts",
    "india_subdistricts",
    "india_cities",
    "india_villages",
}


@tool
def list_available_layers() -> str:
    """
    Lists all spatial layers currently registered in the database catalog,
    including base administrative boundary layers (States, Districts, Sub-districts,
    Cities, Villages) and active user-generated analytical layers.
    """
    layers = catalog_manager.list_layers()
    return json.dumps(layers, indent=2)


@tool
def get_layer_schema(layer_id: str) -> str:
    """
    Returns spatial metadata, geometry type, coordinate bounds, and attribute schema for a layer.
    """
    details = catalog_manager.get_layer_details(layer_id)
    if not details:
        return f"Error: Layer '{layer_id}' does not exist in catalog."
    return json.dumps(details, indent=2)


get_layer_info = get_layer_schema


@tool
def filter_by_admin_boundary(
    target_layer_id: str,
    admin_tier: str,
    place_name: str,
    output_layer_id: str,
    output_layer_name: str
) -> str:
    """
    Spatially filters entities from target_layer_id (e.g., 'india_villages', 'india_cities',
    'india_subdistricts', or user layers) that fall inside a specific administrative entity.

    Parameters:
    - target_layer_id: The table or layer to filter (e.g., 'india_villages', 'india_cities').
    - admin_tier: One of 'states', 'districts', 'subdistricts'.
    - place_name: The name of the boundary entity (e.g., 'Pune', 'Maharashtra', 'Haveli').
    - output_layer_id: Unique table ID for the output layer (e.g., 'villages_pune').
    - output_layer_name: Display title for the map viewer.
    """
    admin_map = {
        "states": ("india_states", "state_name"),
        "districts": ("india_districts", "district_name"),
        "subdistricts": ("india_subdistricts", "subdistrict_name")
    }

    tier = admin_tier.lower().strip()
    if tier not in admin_map:
        return json.dumps({
            "status": "error",
            "message": f"Invalid admin_tier '{admin_tier}'. Must be one of: {list(admin_map.keys())}"
        })

    boundary_table, name_col = admin_map[tier]
    clean_name = place_name.strip().replace("'", "''")

    sql = f"""
        SELECT 
            t.* EXCLUDE (geom),
            t.geom
        FROM {target_layer_id} t
        JOIN {boundary_table} b ON ST_Intersects(t.geom, b.geom)
        WHERE lower(b.{name_col}) = lower('{clean_name}')
    """

    res = spatial_engine.execute_spatial_query(
        query=sql,
        output_layer_id=output_layer_id,
        layer_name=output_layer_name,
        description=f"Features in {target_layer_id} within {admin_tier} '{place_name}'"
    )
    return json.dumps(res)


@tool
def find_near_place(
    target_layer_id: str,
    source_tier: str,
    place_name: str,
    distance_km: float,
    output_layer_id: str,
    output_layer_name: str
) -> str:
    """
    Finds features in target_layer_id located within a given distance (in kilometers)
    of a named Indian city, district, or settlement.

    Parameters:
    - target_layer_id: The layer to search (e.g., 'india_cities', 'india_villages').
    - source_tier: Origin tier: 'cities', 'districts', 'states', or 'subdistricts'.
    - place_name: Target landmark or place name (e.g., 'Kolkata', 'Pune').
    - distance_km: Radius in kilometers.
    - output_layer_id: Output table identifier.
    - output_layer_name: Visual layer name.
    """
    tier_map = {
        "cities": ("india_cities", "city_name"),
        "districts": ("india_districts", "district_name"),
        "subdistricts": ("india_subdistricts", "subdistrict_name"),
        "states": ("india_states", "state_name")
    }

    tier = source_tier.lower().strip()
    if tier not in tier_map:
        return json.dumps({
            "status": "error",
            "message": f"Invalid source_tier '{source_tier}'. Must be one of: {list(tier_map.keys())}"
        })

    src_tbl, src_col = tier_map[tier]
    clean_name = place_name.strip().replace("'", "''")
    deg_radius = distance_km / 111.32  # Standard geodesic degree approximation

    sql = f"""
        SELECT 
            t.* EXCLUDE (geom),
            t.geom
        FROM {target_layer_id} t
        WHERE EXISTS (
            SELECT 1 
            FROM {src_tbl} s
            WHERE lower(s.{src_col}) = lower('{clean_name}')
              AND ST_DWithin(t.geom, s.geom, {deg_radius})
        )
    """

    res = spatial_engine.execute_spatial_query(
        query=sql,
        output_layer_id=output_layer_id,
        layer_name=output_layer_name,
        description=f"Features in {target_layer_id} within {distance_km}km of {place_name}"
    )
    return json.dumps(res)


@tool
def buffer_layer(
    layer_id: str,
    distance_meters: float,
    output_layer_id: str,
    output_layer_name: str
) -> str:
    """
    Generates a metric buffer around geometries in an existing layer.
    Handles metric reprojection automatically: EPSG:4326 -> EPSG:3857 -> EPSG:4326.
    """
    sql = f"""
        SELECT
            * EXCLUDE (geom),
            ST_SetCRS(
                ST_Transform(
                    ST_Buffer(
                        ST_Transform(geom, 'EPSG:4326', 'EPSG:3857'),
                        {distance_meters}
                    ),
                    'EPSG:3857', 'EPSG:4326'
                ),
                'EPSG:4326'
            ) AS geom
        FROM {layer_id}
        WHERE geom IS NOT NULL;
    """
    res = spatial_engine.execute_spatial_query(
        query=sql,
        output_layer_id=output_layer_id,
        layer_name=output_layer_name,
        description=f"Buffer of {layer_id} at {distance_meters}m"
    )
    return json.dumps(res)


@tool
def spatial_intersection(
    source_layer_id: str,
    intersecting_layer_id: str,
    output_layer_id: str,
    output_layer_name: str
) -> str:
    """
    Computes geometric intersection between two layers.
    Retains attributes and output geometries with unified EPSG:4326.
    """
    sql = f"""
        SELECT
            a.* EXCLUDE (geom),
            b.* EXCLUDE (geom, id),
            ST_SetCRS(ST_Intersection(a.geom, b.geom), 'EPSG:4326') AS geom
        FROM {source_layer_id} a
        JOIN {intersecting_layer_id} b ON ST_Intersects(a.geom, b.geom)
        WHERE NOT ST_IsEmpty(ST_Intersection(a.geom, b.geom));
    """
    res = spatial_engine.execute_spatial_query(
        query=sql,
        output_layer_id=output_layer_id,
        layer_name=output_layer_name,
        description=f"Intersection of {source_layer_id} and {intersecting_layer_id}"
    )
    return json.dumps(res)


@tool
def spatial_difference(
    source_layer_id: str,
    subtract_layer_id: str,
    output_layer_id: str,
    output_layer_name: str
) -> str:
    """
    Computes geometric difference (ST_Difference) of source_layer_id minus subtract_layer_id.
    """
    sql = f"""
        WITH dissolved_sub AS (
            SELECT ST_Union_Agg(geom) AS geom 
            FROM {subtract_layer_id}
            WHERE geom IS NOT NULL
        )
        SELECT 
            a.* EXCLUDE (geom),
            ST_SetCRS(ST_Difference(a.geom, s.geom), 'EPSG:4326') AS geom
        FROM {source_layer_id} a, dissolved_sub s
        WHERE a.geom IS NOT NULL 
          AND NOT ST_IsEmpty(ST_Difference(a.geom, s.geom));
    """
    res = spatial_engine.execute_spatial_query(
        query=sql,
        output_layer_id=output_layer_id,
        layer_name=output_layer_name,
        description=f"Difference of {source_layer_id} minus {subtract_layer_id}"
    )
    return json.dumps(res)


@tool
def spatial_filter_within(
    target_layer_id: str,
    boundary_layer_id: str,
    output_layer_id: str,
    output_layer_name: str
) -> str:
    """
    Filters features in target_layer_id that are completely contained within or intersect boundary_layer_id geometries.
    """
    sql = f"""
        SELECT
            a.* EXCLUDE (geom),
            a.geom
        FROM {target_layer_id} a
        JOIN {boundary_layer_id} b ON ST_Intersects(a.geom, b.geom);
    """
    res = spatial_engine.execute_spatial_query(
        query=sql,
        output_layer_id=output_layer_id,
        layer_name=output_layer_name,
        description=f"Features in {target_layer_id} within {boundary_layer_id}"
    )
    return json.dumps(res)


@tool
def execute_custom_spatial_sql(
    sql_query: str,
    output_layer_id: str,
    output_layer_name: str,
    description: str = ""
) -> str:
    """
    Executes a custom SQL query using DuckDB Spatial functions and registers the resulting layer.
    The query must produce a valid geometry column named 'geom'.
    """
    res = spatial_engine.execute_spatial_query(
        query=sql_query,
        output_layer_id=output_layer_id,
        layer_name=output_layer_name,
        description=description or "Custom analytical spatial query"
    )
    return json.dumps(res)


@tool
def delete_layer(layer_id: str) -> str:
    """
    Deletes an existing user analytical spatial layer.
    Core administrative layers cannot be dropped.
    """
    if layer_id in SYSTEM_ADMIN_LAYERS:
        return json.dumps({
            "status": "error",
            "message": f"Permission denied: '{layer_id}' is a core system administrative dataset and cannot be deleted."
        })

    try:
        spatial_engine.con.execute(f"DROP TABLE IF EXISTS {layer_id};")
        spatial_engine.con.execute(f"DELETE FROM spatial_catalog WHERE layer_id = '{layer_id}';")
        return json.dumps({
            "status": "success",
            "message": f"Layer '{layer_id}' successfully dropped from database and catalog.",
            "deleted_layer_id": layer_id
        })
    except Exception as e:
        return json.dumps({
            "status": "error",
            "message": f"Failed to delete layer '{layer_id}': {str(e)}"
        })