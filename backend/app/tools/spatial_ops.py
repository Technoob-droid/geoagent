import json
from langchain_core.tools import tool
from backend.app.tools.engine import spatial_engine
from backend.app.tools.catalog import catalog_manager


@tool
def list_available_layers() -> str:
    """
    Lists all spatial layers currently registered in the database catalog along with their geometries and feature counts.
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
        return f"Error: Layer '{layer_id}' does not exist."
    return json.dumps(details, indent=2)


get_layer_info = get_layer_schema


@tool
def buffer_layer(
    layer_id: str,
    distance_meters: float,
    output_layer_id: str,
    output_layer_name: str
) -> str:
    """
    Generates a metric buffer around geometries in an existing layer.
    Handles metric reprojection automatically: OGC:CRS84 -> EPSG:3857 -> OGC:CRS84.
    """
    sql = f"""
        SELECT
            * EXCLUDE (geom),
            ST_Transform(
                ST_Buffer(
                    ST_Transform(geom, 'OGC:CRS84', 'EPSG:3857'),
                    {distance_meters}
                ),
                'EPSG:3857', 'OGC:CRS84'
            ) as geom
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
    Computes the geometric intersection between two layers.
    Retains attributes from both layers and returns the overlapping geometry fragments.
    """
    sql = f"""
        SELECT
            a.* EXCLUDE (geom),
            b.* EXCLUDE (geom, id),
            ST_Intersection(a.geom, b.geom) as geom
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
    Computes the geometric difference (ST_Difference) of source_layer_id minus subtract_layer_id.
    Retains the areas of source_layer_id that do not fall within subtract_layer_id.
    """
    sql = f"""
        WITH dissolved_sub AS (
            SELECT ST_Union_Agg(geom) AS geom 
            FROM {subtract_layer_id}
            WHERE geom IS NOT NULL
        )
        SELECT 
            a.* EXCLUDE (geom),
            ST_Difference(a.geom, s.geom) AS geom
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
def delete_layer(layer_id: str) -> str:
    """
    Deletes an existing spatial layer, dropping its table from DuckDB 
    and removing it from the active map layer catalog.
    """
    success = catalog_manager.delete_layer(layer_id)
    if success:
        return json.dumps({
            "status": "success",
            "message": f"Layer '{layer_id}' successfully dropped from database and catalog.",
            "deleted_layer_id": layer_id
        })
    return json.dumps({
        "status": "error",
        "message": f"Failed to delete layer '{layer_id}'."
    })


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
            a.*
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