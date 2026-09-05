import json
import logging
from typing import Optional
import httpx
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


def _resolve_location_coords(location_spec: str | dict | list) -> tuple[float, float] | None:
    """
    Resolves arbitrary coordinate strings, lists, layer names, or landmark names to (lon, lat).
    """
    if isinstance(location_spec, (list, tuple)) and len(location_spec) >= 2:
        return float(location_spec[0]), float(location_spec[1])

    if isinstance(location_spec, str):
        cleaned = location_spec.strip()
        if "," in cleaned:
            parts = [p.strip() for p in cleaned.split(",")]
            try:
                return float(parts[0]), float(parts[1])
            except ValueError:
                pass

        clean_name = cleaned.replace("'", "''").lower()
        clean_tbl_cand = clean_name.replace(" ", "_")
        active_layers = [l["layer_id"] for l in catalog_manager.list_layers()]

        # 1. Match directly against user layer table names (e.g., "kolkata_center")
        for tbl in active_layers:
            if tbl in SYSTEM_ADMIN_LAYERS:
                continue
            if tbl == clean_tbl_cand or clean_tbl_cand in tbl or tbl in clean_tbl_cand:
                try:
                    res = spatial_engine.con.execute(f"""
                        SELECT 
                            ST_X(ST_Centroid(geom)) AS lon, 
                            ST_Y(ST_Centroid(geom)) AS lat 
                        FROM {tbl} 
                        WHERE geom IS NOT NULL
                        LIMIT 1;
                    """).fetchone()
                    if res and res[0] is not None:
                        return float(res[0]), float(res[1])
                except Exception:
                    pass

        # 2. Match feature attributes across user-generated layers
        for tbl in active_layers:
            if tbl in SYSTEM_ADMIN_LAYERS:
                continue
            try:
                res = spatial_engine.con.execute(f"""
                    SELECT 
                        ST_X(ST_Centroid(geom)) AS lon, 
                        ST_Y(ST_Centroid(geom)) AS lat 
                    FROM {tbl} 
                    WHERE lower(CAST(columns(*) AS VARCHAR)) LIKE '%{clean_name}%'
                    LIMIT 1;
                """).fetchone()
                if res and res[0] is not None:
                    return float(res[0]), float(res[1])
            except Exception:
                continue

        # 3. Fallback to base admin boundary datasets
        admin_lookups = [
            ("india_cities", "city_name"),
            ("india_districts", "district_name"),
            ("india_villages", "village_name"),
        ]
        for tbl, col in admin_lookups:
            try:
                res = spatial_engine.con.execute(f"""
                    SELECT 
                        ST_X(ST_Centroid(geom)) AS lon, 
                        ST_Y(ST_Centroid(geom)) AS lat 
                    FROM {tbl} 
                    WHERE lower({col}) = lower('{clean_name}') 
                       OR lower({col}) LIKE '%{clean_name}%'
                    LIMIT 1;
                """).fetchone()
                if res and res[0] is not None:
                    return float(res[0]), float(res[1])
            except Exception:
                continue

    return None


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
    deg_radius = distance_km / 111.32  # Geodesic degree approximation

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
    Generates an accurate metric buffer around geometries in an existing layer.
    Uses latitude-scaled geodesic degree calculation to prevent axis distortion.
    """
    # 1 degree lat ≈ 111,139 meters; scale longitude degrees by cos(latitude)
    sql = f"""
        WITH target_geom AS (
            SELECT *, ST_Y(ST_Centroid(geom)) AS ref_lat FROM {layer_id} WHERE geom IS NOT NULL
        )
        SELECT
            * EXCLUDE (geom, ref_lat),
            ST_SetCRS(
                ST_Buffer(
                    geom,
                    ({distance_meters} / 111139.0)
                ),
                'EPSG:4326'
            ) AS geom
        FROM target_geom;
    """
    res = spatial_engine.execute_spatial_query(
        query=sql,
        output_layer_id=output_layer_id,
        layer_name=output_layer_name,
        description=f"Geodesic buffer of {layer_id} at {distance_meters}m"
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


@tool
def calculate_evacuation_route(
    start_location: str,
    end_location: str,
    avoid_layer_id: Optional[str] = None,
    output_layer_id: str = "evacuation_route",
    output_layer_name: str = "Evacuation Route"
) -> str:
    """
    Computes an optimal road evacuation route between two locations using OSRM,
    checks for collision against active hazard layers, and attempts an automatic
    waypoint detour if a collision is detected.

    Args:
        start_location: Start coordinates ('lon, lat') or name of a landmark/city.
        end_location: End coordinates ('lon, lat') or name of a landmark/city.
        avoid_layer_id: Optional ID or keyword of a hazard/flood layer to avoid.
        output_layer_id: Snake_case identifier for the output route layer.
        output_layer_name: Human-readable name for display on the map.
    """
    clean_output_id = output_layer_id.strip().lower().replace(" ", "_")

    start_coords = _resolve_location_coords(start_location)
    end_coords = _resolve_location_coords(end_location)

    if not start_coords:
        return json.dumps({
            "status": "error",
            "message": f"Could not resolve start location '{start_location}' to valid coordinates."
        })
    if not end_coords:
        return json.dumps({
            "status": "error",
            "message": f"Could not resolve end location '{end_location}' to valid coordinates."
        })

    s_lon, s_lat = start_coords
    e_lon, e_lat = end_coords

    def query_osrm(coords_list: list[tuple[float, float]]) -> dict | None:
        coord_str = ";".join(f"{lon},{lat}" for lon, lat in coords_list)
        url = f"https://router.project-osrm.org/route/v1/driving/{coord_str}?overview=full&geometries=geojson"
        with httpx.Client(timeout=10.0) as client:
            r = client.get(url)
            if r.status_code == 200:
                data = r.json()
                if data.get("routes"):
                    return data["routes"][0]
        return None

    try:
        primary_route = query_osrm([(s_lon, s_lat), (e_lon, e_lat)])
        if not primary_route:
            return json.dumps({
                "status": "error",
                "message": f"No driving route found between {start_location} and {end_location}."
            })

        active_route = primary_route
        geom_json = json.dumps(active_route["geometry"]).replace("'", "''")
        distance_km = round(active_route["distance"] / 1000.0, 2)
        duration_min = round(active_route["duration"] / 60.0, 1)

        matched_hazard_table = None
        intersects_hazard = False
        hazard_intersect_count = 0
        detour_applied = False

        if avoid_layer_id:
            cand = avoid_layer_id.strip().lower().replace(" ", "_")
            all_layers = [l["layer_id"] for l in catalog_manager.list_layers()]
            if cand in all_layers:
                matched_hazard_table = cand
            else:
                for lay in all_layers:
                    if cand in lay or lay in cand or "flood" in lay:
                        matched_hazard_table = lay
                        break

        if matched_hazard_table:
            check_sql = f"""
                SELECT count(*) 
                FROM {matched_hazard_table} 
                WHERE ST_Intersects(geom, ST_GeomFromGeoJSON('{geom_json}'))
            """
            hazard_intersect_count = spatial_engine.con.execute(check_sql).fetchone()[0]
            intersects_hazard = hazard_intersect_count > 0

            # Detour sampling if route intersects hazard
            if intersects_hazard:
                extent_info = spatial_engine.con.execute(f"""
                    SELECT 
                        ST_XMin(ST_Extent(geom)) AS min_x,
                        ST_YMin(ST_Extent(geom)) AS min_y,
                        ST_XMax(ST_Extent(geom)) AS max_x,
                        ST_YMax(ST_Extent(geom)) AS max_y
                    FROM {matched_hazard_table}
                    WHERE ST_Intersects(geom, ST_GeomFromGeoJSON('{geom_json}'));
                """).fetchone()

                if extent_info and extent_info[0] is not None:
                    min_x, min_y, max_x, max_y = extent_info
                    mid_x = (min_x + max_x) / 2.0
                    mid_y = (min_y + max_y) / 2.0
                    offset_x = (max_x - min_x) * 0.75 or 0.02
                    offset_y = (max_y - min_y) * 0.75 or 0.02

                    candidate_waypoints = [
                        (mid_x + offset_x, mid_y),
                        (mid_x - offset_x, mid_y),
                        (mid_x, mid_y + offset_y),
                        (mid_x, mid_y - offset_y),
                    ]

                    for wp_lon, wp_lat in candidate_waypoints:
                        alt_route = query_osrm([(s_lon, s_lat), (wp_lon, wp_lat), (e_lon, e_lat)])
                        if not alt_route:
                            continue
                        alt_geom_str = json.dumps(alt_route["geometry"]).replace("'", "''")
                        alt_hits = spatial_engine.con.execute(f"""
                            SELECT count(*) 
                            FROM {matched_hazard_table} 
                            WHERE ST_Intersects(geom, ST_GeomFromGeoJSON('{alt_geom_str}'))
                        """).fetchone()[0]

                        if alt_hits == 0:
                            active_route = alt_route
                            geom_json = alt_geom_str
                            distance_km = round(active_route["distance"] / 1000.0, 2)
                            duration_min = round(active_route["duration"] / 60.0, 1)
                            intersects_hazard = False
                            hazard_intersect_count = 0
                            detour_applied = True
                            break

        # Persist route via spatial engine
        query_sql = f"""
            SELECT 
                1 AS route_id,
                '{start_location}' AS origin,
                '{end_location}' AS destination,
                {distance_km} AS distance_km,
                {duration_min} AS duration_min,
                {intersects_hazard} AS passes_through_hazard,
                {hazard_intersect_count} AS intersecting_hazard_features,
                {detour_applied} AS detour_applied,
                ST_SetCRS(ST_GeomFromGeoJSON('{geom_json}'), 'EPSG:4326') AS geom
        """

        res = spatial_engine.execute_spatial_query(
            query=query_sql,
            output_layer_id=clean_output_id,
            layer_name=output_layer_name,
            description=f"Evacuation route ({distance_km} km, ~{duration_min} min). Detour: {detour_applied}"
        )

        res.update({
            "origin": start_location,
            "destination": end_location,
            "distance_km": distance_km,
            "duration_min": duration_min,
            "checked_against_layer": matched_hazard_table,
            "passes_through_hazard": intersects_hazard,
            "detour_applied": detour_applied,
            "instruction": "Route is created and displayed on the map. Finish immediately. Do not call this tool again.",
            "message": (
                f"Route generated ({distance_km} km, ~{duration_min} min). "
                f"Detour applied: {detour_applied}. "
                f"Hazard collision: {'YES (intersects hazard)' if intersects_hazard else 'NO (clear)'}."
            )
        })
        return json.dumps(res)

    except Exception as e:
        logger.exception("Evacuation routing error")
        return json.dumps({"status": "error", "message": str(e)})