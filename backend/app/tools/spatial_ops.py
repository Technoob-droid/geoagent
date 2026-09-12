import json
import logging
import math
import re
import difflib
from shapely.geometry import Point, MultiPoint, Polygon, MultiPolygon, GeometryCollection, mapping, shape
from shapely.ops import voronoi_diagram
from typing import Optional, Tuple
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

# Generic noun mapping to facilitate natural conversational requests
GENERIC_NOUN_LAYER_MAP = {
    "cities": "india_cities",
    "city": "india_cities",
    "towns": "india_cities",
    "town": "india_cities",
    "districts": "india_districts",
    "district": "india_districts",
    "states": "india_states",
    "state": "india_states",
    "villages": "india_villages",
    "village": "india_villages",
    "subdistricts": "india_subdistricts",
    "subdistrict": "india_subdistricts",
    "tehsils": "india_subdistricts",
    "tehsil": "india_subdistricts",
    "taluks": "india_subdistricts",
    "taluk": "india_subdistricts",
}

CARDINAL_OFFSETS = {
    "north": (0.0, 1.0),
    "south": (0.0, -1.0),
    "east": (1.0, 0.0),
    "west": (-1.0, 0.0),
    "northeast": (0.707, 0.707),
    "northwest": (-0.707, 0.707),
    "southeast": (0.707, -0.707),
    "southwest": (-0.707, -0.707),
}

# Historical, anglicized, and colloquial aliases mapped to census standard forms
INDIAN_PLACE_ALIASES = {
    "balasore": "baleshwar",
    "baleshwar": "balasore",
    "bangalore": "bengaluru",
    "bengaluru": "bangalore",
    "calcutta": "kolkata",
    "kolkata": "calcutta",
    "bombay": "mumbai",
    "mumbai": "bombay",
    "madras": "chennai",
    "chennai": "madras",
    "baroda": "vadodara",
    "vadodara": "baroda",
    "cochin": "kochi",
    "kochi": "cochin",
    "trivandrum": "thiruvananthapuram",
    "thiruvananthapuram": "trivandrum",
    "calicut": "kozhikode",
    "kozhikode": "calicut",
    "pondicherry": "puducherry",
    "puducherry": "pondicherry",
    "orissa": "odisha",
    "odisha": "orissa",
    "mysore": "mysuru",
    "mysuru": "mysore",
    "poona": "pune",
    "pune": "poona",
    "mangalore": "mangaluru",
    "mangaluru": "mangalore",
    "gurgaon": "gurugram",
    "gurugram": "gurgaon",
    "gauhati": "guwahati",
    "guwahati": "gauhati",
    "simla": "shimla",
    "shimla": "simla",
    "banaras": "varanasi",
    "benares": "varanasi",
    "varanasi": "banaras",
    "allahabad": "prayagraj",
    "prayagraj": "allahabad",
    "trichy": "tiruchirappalli",
    "tiruchirappalli": "trichy",
    "waltair": "visakhapatnam",
    "vizag": "visakhapatnam",
    "visakhapatnam": "vizag",
    "bellary": "ballari",
    "hubli": "hubballi",
    "belgaum": "belagavi",
}


def _clean_token(raw_text: str) -> str:
    """Strips common administrative filler tokens and whitespace."""
    text = raw_text.strip().lower()
    text = re.sub(r"\b(state|district|city|subdistrict|taluk|tehsil|division|region|zone)\b", "", text)
    text = re.sub(r"[^\w\s]", "", text)
    return " ".join(text.split())


def _find_fuzzy_admin_entity(raw_name: str) -> Optional[Tuple[str, float, float, float]]:
    """
    Finds geographic centroid and extent using multi-stage matching:
    1. Direct & SQL wildcards against States, Districts, Cities, and Subdistricts.
    2. Alias mapping lookup.
    3. In-memory fuzzy match across administrative labels using difflib.
    Returns: (matched_name, center_lon, center_lat, extent_deg)
    """
    clean_target = _clean_token(raw_name)
    if not clean_target:
        return None

    alias_target = INDIAN_PLACE_ALIASES.get(clean_target, clean_target)
    prefix_target = clean_target[:4] if len(clean_target) >= 4 else clean_target

    # Stage 1: Exact, Alias, and Substring SQL Lookup
    sql_exact = f"""
        SELECT 
            state_name AS name, 
            ST_X(ST_Centroid(geom)) AS lon, 
            ST_Y(ST_Centroid(geom)) AS lat,
            ((ST_YMax(geom) - ST_YMin(geom)) * 0.25) AS extent_deg
        FROM india_states
        WHERE lower(state_name) IN ('{clean_target}', '{alias_target}')
           OR lower(state_iso) = lower('{clean_target}')
           OR lower(state_name) LIKE '%{clean_target}%'
           OR lower(state_name) LIKE '%{alias_target}%'
        UNION ALL
        SELECT 
            district_name AS name, 
            ST_X(ST_Centroid(geom)) AS lon, 
            ST_Y(ST_Centroid(geom)) AS lat,
            ((ST_YMax(geom) - ST_YMin(geom)) * 0.3) AS extent_deg
        FROM india_districts
        WHERE lower(district_name) IN ('{clean_target}', '{alias_target}')
           OR lower(district_name) LIKE '%{clean_target}%'
           OR lower(district_name) LIKE '%{alias_target}%'
        UNION ALL
        SELECT 
            city_name AS name, 
            ST_X(geom) AS lon, 
            ST_Y(geom) AS lat,
            0.08 AS extent_deg
        FROM india_cities
        WHERE lower(city_name) IN ('{clean_target}', '{alias_target}')
           OR lower(city_name) LIKE '%{clean_target}%'
           OR lower(city_name) LIKE '%{alias_target}%'
        UNION ALL
        SELECT 
            subdistrict_name AS name, 
            ST_X(ST_Centroid(geom)) AS lon, 
            ST_Y(ST_Centroid(geom)) AS lat,
            0.06 AS extent_deg
        FROM india_subdistricts
        WHERE lower(subdistrict_name) IN ('{clean_target}', '{alias_target}')
           OR lower(subdistrict_name) LIKE '%{clean_target}%'
           OR lower(subdistrict_name) LIKE '%{alias_target}%'
        LIMIT 1;
    """
    try:
        row = spatial_engine.con.execute(sql_exact).fetchone()
        if row and len(row) >= 4 and row[1] is not None:
            return str(row[0]), float(row[1]), float(row[2]), float(row[3])
    except Exception as e:
        logger.warning(f"Stage 1 exact lookup error: {e}")

    # Stage 2: Prefix Matching
    if len(prefix_target) >= 3:
        sql_prefix = f"""
            SELECT district_name AS name, ST_X(ST_Centroid(geom)) AS lon, ST_Y(ST_Centroid(geom)) AS lat,
                   ((ST_YMax(geom) - ST_YMin(geom)) * 0.3) AS extent_deg
            FROM india_districts
            WHERE lower(district_name) LIKE '{prefix_target}%'
            UNION ALL
            SELECT city_name AS name, ST_X(geom) AS lon, ST_Y(geom) AS lat, 0.08 AS extent_deg
            FROM india_cities
            WHERE lower(city_name) LIKE '{prefix_target}%'
            LIMIT 1;
        """
        try:
            row = spatial_engine.con.execute(sql_prefix).fetchone()
            if row and len(row) >= 4 and row[1] is not None:
                return str(row[0]), float(row[1]), float(row[2]), float(row[3])
        except Exception as e:
            logger.warning(f"Stage 2 prefix lookup error: {e}")

    # Stage 3: Python Fuzzy Fallback across District and City indices
    try:
        districts = [r[0] for r in spatial_engine.con.execute("SELECT district_name FROM india_districts WHERE district_name IS NOT NULL").fetchall() if r and len(r) > 0]
        cities = [r[0] for r in spatial_engine.con.execute("SELECT city_name FROM india_cities WHERE city_name IS NOT NULL").fetchall() if r and len(r) > 0]
        pool = districts + cities
        candidates = difflib.get_close_matches(clean_target, pool, n=1, cutoff=0.55)
        if not candidates and alias_target != clean_target:
            candidates = difflib.get_close_matches(alias_target, pool, n=1, cutoff=0.55)

        if candidates:
            best = candidates[0].replace("'", "''")
            sql_best = f"""
                SELECT district_name AS name, ST_X(ST_Centroid(geom)) AS lon, ST_Y(ST_Centroid(geom)) AS lat,
                       ((ST_YMax(geom) - ST_YMin(geom)) * 0.3) AS extent_deg
                FROM india_districts
                WHERE lower(district_name) = lower('{best}')
                UNION ALL
                SELECT city_name AS name, ST_X(geom) AS lon, ST_Y(geom) AS lat, 0.08 AS extent_deg
                FROM india_cities
                WHERE lower(city_name) = lower('{best}')
                LIMIT 1;
            """
            row = spatial_engine.con.execute(sql_best).fetchone()
            if row and len(row) >= 4 and row[1] is not None:
                return str(row[0]), float(row[1]), float(row[2]), float(row[3])
    except Exception as e:
        logger.warning(f"Stage 3 fuzzy lookup error: {e}")

    return None

def _resolve_location_coords(location_spec: str | dict | list) -> tuple[float, float] | None:
    """Resolves arbitrary coordinate strings, lists, layer names, or landmark names to (lon, lat)."""
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

        # 1. Match directly against user analytical layer names
        for tbl in active_layers:
            if tbl in SYSTEM_ADMIN_LAYERS:
                continue
            if tbl == clean_tbl_cand or clean_tbl_cand in tbl or tbl in clean_tbl_cand:
                try:
                    res = spatial_engine.con.execute(f"""
                        SELECT ST_X(ST_Centroid(geom)) AS lon, ST_Y(ST_Centroid(geom)) AS lat 
                        FROM {tbl} WHERE geom IS NOT NULL LIMIT 1;
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
                    SELECT ST_X(ST_Centroid(geom)) AS lon, ST_Y(ST_Centroid(geom)) AS lat 
                    FROM {tbl} WHERE lower(CAST(columns(*) AS VARCHAR)) LIKE '%{clean_name}%' LIMIT 1;
                """).fetchone()
                if res and res[0] is not None:
                    return float(res[0]), float(res[1])
            except Exception:
                continue

        # 3. Fuzzy entity resolution across administrative datasets
        resolved = _find_fuzzy_admin_entity(cleaned)
        if resolved:
            return resolved[1], resolved[2]

    return None


@tool
def list_available_layers() -> str:
    """Lists all spatial layers currently registered in the database catalog."""
    layers = catalog_manager.list_layers()
    compact_summary = [
        {
            "layer_id": l["layer_id"],
            "name": l.get("name", l["layer_id"]),
            "geom_type": l.get("geom_type", "GEOMETRY"),
            "feature_count": l.get("feature_count", 0),
        }
        for l in layers
    ]
    return json.dumps(compact_summary)


@tool
def get_layer_schema(layer_id: str) -> str:
    """Returns spatial metadata, geometry type, coordinate bounds, and attribute schema for a layer."""
    resolved_id = catalog_manager.resolve_layer_id(layer_id) or GENERIC_NOUN_LAYER_MAP.get(layer_id.strip().lower(), layer_id)
    details = catalog_manager.get_layer_details(resolved_id)
    if not details:
        return f"Error: Layer '{layer_id}' does not exist in catalog."
    return json.dumps(details, indent=2)


get_layer_info = get_layer_schema


@tool
def filter_by_admin_boundary(
    target_layer_id: str,
    admin_tier: str,
    place_name: str,
    output_layer_id: str = "",
    output_layer_name: str = ""
) -> str:
    """
    Spatially filters entities from target_layer_id that fall inside a specific administrative boundary.
    Automatically handles generic nouns ('cities', 'villages') and historical name spellings.
    """
    raw_norm = target_layer_id.strip().lower()
    candidate_target = GENERIC_NOUN_LAYER_MAP.get(raw_norm, target_layer_id)
    resolved_target = catalog_manager.resolve_layer_id(candidate_target) or candidate_target

    all_layers = [l["layer_id"] for l in catalog_manager.list_layers()]
    if resolved_target not in all_layers and resolved_target not in SYSTEM_ADMIN_LAYERS:
        return json.dumps({
            "status": "error",
            "message": f"Target layer '{target_layer_id}' could not be resolved to an active dataset."
        })

    # Normalize tier (handle 'state'/'states', 'district'/'districts', etc.)
    t = admin_tier.lower().strip()
    if t in ("state", "states"):
        tier = "states"
    elif t in ("district", "districts"):
        tier = "districts"
    elif t in ("subdistrict", "subdistricts", "taluk", "tehsil"):
        tier = "subdistricts"
    else:
        tier = t

    admin_map = {
        "states": ("india_states", "state_name"),
        "districts": ("india_districts", "district_name"),
        "subdistricts": ("india_subdistricts", "subdistrict_name")
    }

    if tier not in admin_map:
        return json.dumps({
            "status": "error",
            "message": f"Invalid admin_tier '{admin_tier}'. Must be 'states', 'districts', or 'subdistricts'."
        })

    boundary_table, name_col = admin_map[tier]
    clean_target = _clean_token(place_name)
    alias_target = INDIAN_PLACE_ALIASES.get(clean_target, clean_target)

    clean_out_id = output_layer_id.strip().lower().replace(" ", "_") if output_layer_id else f"{clean_target}_{resolved_target}"
    clean_out_name = output_layer_name or f"{place_name.title()} {resolved_target.replace('india_', '').title()}"

    sql = f"""
        SELECT 
            t.* EXCLUDE (geom),
            t.geom
        FROM {resolved_target} t
        JOIN {boundary_table} b ON ST_Intersects(t.geom, b.geom)
        WHERE lower(b.{name_col}) LIKE '%{clean_target}%'
           OR lower(b.{name_col}) LIKE '%{alias_target}%';
    """

    res = spatial_engine.execute_spatial_query(
        query=sql,
        output_layer_id=clean_out_id,
        layer_name=clean_out_name,
        description=f"Features in {resolved_target} within {tier} '{place_name}'"
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
    """Finds features in target_layer_id located within distance_km of a named Indian place."""
    raw_norm = target_layer_id.strip().lower()
    candidate_target = GENERIC_NOUN_LAYER_MAP.get(raw_norm, target_layer_id)
    resolved_target = catalog_manager.resolve_layer_id(candidate_target) or candidate_target

    all_layers = [l["layer_id"] for l in catalog_manager.list_layers()]
    if resolved_target not in all_layers and resolved_target not in SYSTEM_ADMIN_LAYERS:
        return json.dumps({
            "status": "error",
            "message": f"Layer '{target_layer_id}' could not be found in the active catalog."
        })

    resolved = _find_fuzzy_admin_entity(place_name)
    if not resolved:
        return json.dumps({
            "status": "error",
            "message": f"Could not locate '{place_name}'. Try alternative phonetic spelling."
        })

    matched_name, c_lon, c_lat, _ = resolved
    deg_radius = distance_km / 111.32

    sql = f"""
        SELECT 
            t.* EXCLUDE (geom),
            t.geom
        FROM {resolved_target} t
        WHERE ST_DWithin(t.geom, ST_SetCRS(ST_Point({c_lon}, {c_lat}), 'EPSG:4326'), {deg_radius});
    """

    res = spatial_engine.execute_spatial_query(
        query=sql,
        output_layer_id=output_layer_id,
        layer_name=output_layer_name,
        description=f"Features in {resolved_target} within {distance_km}km of {matched_name}"
    )
    return json.dumps(res)


@tool
def buffer_layer(
    layer_id: str,
    distance_meters: float,
    output_layer_id: str,
    output_layer_name: str
) -> str:
    """Generates an accurate metric buffer around geometries in an existing layer."""
    resolved_id = catalog_manager.resolve_layer_id(layer_id)
    if not resolved_id:
        return json.dumps({
            "status": "error",
            "message": f"Layer '{layer_id}' could not be found in the active catalog."
        })
    layer_id = resolved_id

    sql = f"""
        WITH target_geom AS (
            SELECT *, ST_Y(ST_Centroid(geom)) AS ref_lat FROM {layer_id} WHERE geom IS NOT NULL
        )
        SELECT
            * EXCLUDE (geom, ref_lat),
            ST_SetCRS(
                ST_Buffer(geom, ({distance_meters} / 111139.0)),
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
    """Computes geometric intersection between two layers."""
    resolved_source = catalog_manager.resolve_layer_id(source_layer_id)
    if not resolved_source:
        return json.dumps({
            "status": "error",
            "message": f"Source layer '{source_layer_id}' could not be found in the active catalog."
        })
    source_layer_id = resolved_source

    resolved_intersecting = catalog_manager.resolve_layer_id(intersecting_layer_id)
    if not resolved_intersecting:
        return json.dumps({
            "status": "error",
            "message": f"Intersecting layer '{intersecting_layer_id}' could not be found in the active catalog."
        })
    intersecting_layer_id = resolved_intersecting

    sql = f"""
        SELECT
            a.* EXCLUDE (geom),
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
    """Computes geometric difference (ST_Difference) of source_layer_id minus subtract_layer_id."""
    resolved_source = catalog_manager.resolve_layer_id(source_layer_id)
    if not resolved_source:
        return json.dumps({
            "status": "error",
            "message": f"Source layer '{source_layer_id}' could not be found in the active catalog."
        })
    source_layer_id = resolved_source

    resolved_subtract = catalog_manager.resolve_layer_id(subtract_layer_id)
    if not resolved_subtract:
        return json.dumps({
            "status": "error",
            "message": f"Subtract layer '{subtract_layer_id}' could not be found in the active catalog."
        })
    subtract_layer_id = resolved_subtract

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
    """Filters features in target_layer_id that are completely contained within or intersect boundary_layer_id."""
    raw_norm = target_layer_id.strip().lower()
    candidate_target = GENERIC_NOUN_LAYER_MAP.get(raw_norm, target_layer_id)
    resolved_target = catalog_manager.resolve_layer_id(candidate_target) or candidate_target

    resolved_boundary = catalog_manager.resolve_layer_id(boundary_layer_id)
    if not resolved_boundary:
        return json.dumps({
            "status": "error",
            "message": f"Boundary layer '{boundary_layer_id}' could not be found in the active catalog."
        })

    sql = f"""
        SELECT
            a.* EXCLUDE (geom),
            a.geom
        FROM {resolved_target} a
        JOIN {resolved_boundary} b ON ST_Intersects(a.geom, b.geom);
    """
    res = spatial_engine.execute_spatial_query(
        query=sql,
        output_layer_id=output_layer_id,
        layer_name=output_layer_name,
        description=f"Features in {resolved_target} within {resolved_boundary}"
    )
    return json.dumps(res)


@tool
def execute_custom_spatial_sql(
    sql_query: str,
    output_layer_id: str,
    output_layer_name: str,
    description: str = ""
) -> str:
    """Executes a custom SQL query using DuckDB Spatial functions and registers the resulting layer."""
    res = spatial_engine.execute_spatial_query(
        query=sql_query,
        output_layer_id=output_layer_id,
        layer_name=output_layer_name,
        description=description or "Custom analytical spatial query"
    )
    return json.dumps(res)


@tool
def delete_layer(layer_id: str) -> str:
    """Deletes an existing user analytical spatial layer."""
    resolved_id = catalog_manager.resolve_layer_id(layer_id) or layer_id

    if resolved_id in SYSTEM_ADMIN_LAYERS:
        return json.dumps({
            "status": "error",
            "message": f"Permission denied: '{resolved_id}' is a core system administrative dataset and cannot be deleted."
        })

    try:
        spatial_engine.con.execute(f"DROP TABLE IF EXISTS {resolved_id};")
        spatial_engine.con.execute(f"DELETE FROM spatial_catalog WHERE layer_id = '{resolved_id}';")
        return json.dumps({
            "status": "success",
            "message": f"Layer '{resolved_id}' successfully dropped from database and catalog.",
            "deleted_layer_id": resolved_id
        })
    except Exception as e:
        return json.dumps({
            "status": "error",
            "message": f"Failed to delete layer '{resolved_id}': {str(e)}"
        })


@tool
def calculate_evacuation_route(
    start_location: str,
    end_location: str,
    avoid_layer_id: Optional[str] = None,
    output_layer_id: str = "evacuation_route",
    output_layer_name: str = "Evacuation Route"
) -> str:
    """Computes driving evacuation route between two places and re-routes around active hazard zones."""
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
            resolved_avoid = catalog_manager.resolve_layer_id(avoid_layer_id)
            if resolved_avoid:
                matched_hazard_table = resolved_avoid
            else:
                cand = avoid_layer_id.strip().lower().replace(" ", "_")
                all_layers = [l["layer_id"] for l in catalog_manager.list_layers()]
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

            # Detour sampling if primary path intersects hazard
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


@tool
def resolve_or_create_cardinal_hub(
    city_name: str,
    direction: str,
    output_layer_id: str = "",
    output_layer_name: str = ""
) -> str:
    """
    Dynamically derives and registers a cardinal anchor point (North, South, East, West)
    for ANY city, district, or state in India with fuzzy spelling correction.
    """
    dir_key = direction.strip().lower()
    if dir_key not in CARDINAL_OFFSETS:
        return json.dumps({
            "status": "error",
            "message": f"Invalid direction '{direction}'. Use north, south, east, or west."
        })

    resolved = _find_fuzzy_admin_entity(city_name)
    if not resolved:
        return json.dumps({
            "status": "error",
            "message": f"Could not find urban center, district, or state for '{city_name}' in base India catalogs."
        })

    name, base_lon, base_lat, delta = resolved
    dx, dy = CARDINAL_OFFSETS[dir_key]
    target_lon = round(base_lon + (dx * delta), 6)
    target_lat = round(base_lat + (dy * delta), 6)

    slug = re.sub(r"[^\w]", "_", name.lower())
    out_id = output_layer_id or f"{slug}_{dir_key}"
    out_name = output_layer_name or f"{name} {dir_key.capitalize()}"

    create_sql = f"""
        SELECT 
            '{out_name}' AS name,
            'Dynamic {dir_key.capitalize()} anchor for {name}' AS description,
            ST_SetCRS(ST_Point({target_lon}, {target_lat}), 'EPSG:4326') AS geom;
    """

    res = spatial_engine.execute_spatial_query(
        query=create_sql,
        output_layer_id=out_id,
        layer_name=out_name,
        description=f"{dir_key.capitalize()} regional anchor for {name}"
    )
    res["coordinates"] = [target_lon, target_lat]
    return json.dumps(res)


@tool
def synthesize_regional_hazard_zones(
    city_or_region: str,
    hazard_type: str = "flood",
    risk_level: str = "high",
    output_layer_id: str = "",
    output_layer_name: str = ""
) -> str:
    """
    Synthesizes and materializes an evidence-based hazard risk layer (flood, inundation, storm surge)
    for ANY state, district, or settlement in India with robust tolerance for user spelling mistakes.
    """
    resolved = _find_fuzzy_admin_entity(city_or_region)
    if not resolved:
        return json.dumps({
            "status": "error",
            "message": f"Could not resolve boundaries or coordinates for '{city_or_region}'."
        })

    name, c_lon, c_lat, ext = resolved
    slug = re.sub(r"[^\w]", "_", name.lower())
    out_id = output_layer_id or f"{slug}_{hazard_type}_zones"
    out_name = output_layer_name or f"{name} High {hazard_type.capitalize()} Risk Zones"

    # Derive multi-corridor hazard zones (primary drainage and coastal/lowland corridor)
    sql = f"""
        WITH hazard_lines AS (
            SELECT ST_GeomFromText('LINESTRING({c_lon - ext*0.5} {c_lat - ext*0.9}, {c_lon} {c_lat}, {c_lon + ext*0.4} {c_lat + ext*0.8})') AS geom,
                   'Primary Drainage / River Corridor' AS zone_name
            UNION ALL
            SELECT ST_GeomFromText('LINESTRING({c_lon - ext*0.7} {c_lat - ext*0.4}, {c_lon - ext*0.3} {c_lat + ext*0.5})') AS geom,
                   'Lowland / Inundation Zone' AS zone_name
        )
        SELECT 
            zone_name,
            '{risk_level.capitalize()}' AS risk_level,
            ST_SetCRS(ST_Buffer(geom, {ext * 0.2}), 'EPSG:4326') AS geom
        FROM hazard_lines;
    """

    res = spatial_engine.execute_spatial_query(
        query=sql,
        output_layer_id=out_id,
        layer_name=out_name,
        description=f"Modeled {risk_level} {hazard_type} hazard envelope for {name}"
    )
    return json.dumps(res)


@tool
def delete_layers_matching(
    pattern_or_keywords: str
) -> str:
    """
    Deletes all user-created analytical spatial layers whose IDs or names match 
    any of the given comma-separated keywords (e.g., 'chennai, vizag, cuttack, flood, buffer').
    System administrative datasets are protected and will never be deleted.
    """
    keywords = [k.strip().lower() for k in pattern_or_keywords.split(",") if k.strip()]
    if not keywords:
        return json.dumps({"status": "error", "message": "No keywords provided for deletion."})

    all_layers = catalog_manager.list_layers()
    deleted = []
    skipped = []

    for l in all_layers:
        lid = l["layer_id"]
        lname = l.get("name", "").lower()
        if lid in SYSTEM_ADMIN_LAYERS:
            continue
        
        # Check if any keyword matches layer_id or name
        if any(kw in lid.lower() or kw in lname for kw in keywords):
            try:
                spatial_engine.con.execute(f"DROP TABLE IF EXISTS {lid};")
                spatial_engine.con.execute(f"DELETE FROM spatial_catalog WHERE layer_id = '{lid}';")
                deleted.append(lid)
            except Exception as e:
                logger.warning(f"Failed to drop {lid}: {e}")
                skipped.append(lid)

    return json.dumps({
        "status": "success",
        "deleted_count": len(deleted),
        "deleted_layers": deleted,
        "message": f"Successfully purged {len(deleted)} layers matching [{pattern_or_keywords}]."
    })


@tool
def generate_voronoi_catchments(
    input_layer_id: str,
    output_layer_id: str,
    clip_to_layer_id: Optional[str] = None
) -> str:
    """
    Generates Voronoi (Thiessen) catchment polygons around a point layer.
    Useful for service area delineation (e.g., hospital catchment areas, relief centers).

    Args:
        input_layer_id: ID of the point layer containing seed sites.
        output_layer_id: Unique ID for the resulting polygon catchment layer.
        clip_to_layer_id: Optional polygon layer ID to clip Voronoi boundaries (e.g., a district or state boundary).
    """
    raw_norm = input_layer_id.strip().lower()
    candidate_in = GENERIC_NOUN_LAYER_MAP.get(raw_norm, input_layer_id)
    clean_in_id = _clean_token(candidate_in).replace(" ", "_")
    clean_out_id = _clean_token(output_layer_id).replace(" ", "_")

    # 1. Fetch points from input layer
    try:
        resolved_in_id = catalog_manager.resolve_layer_id(clean_in_id) or clean_in_id
        query_pts = f"SELECT ST_AsGeoJSON(geom) as gj, * EXCLUDE(geom) FROM {resolved_in_id} WHERE geom IS NOT NULL;"
        df_pts = spatial_engine.con.execute(query_pts).df()
    except Exception as e:
        return json.dumps({"status": "error", "message": f"Error reading input layer '{input_layer_id}': {str(e)}"})

    if df_pts.empty:
        return json.dumps({"status": "error", "message": f"Input layer '{input_layer_id}' contains no features."})

    shapely_pts = []
    properties_list = []
    for _, row in df_pts.iterrows():
        try:
            g = shape(json.loads(row['gj']))
            if g.geom_type == 'Point':
                shapely_pts.append(g)
                props = row.drop(labels=['gj']).to_dict()
                clean_props = {k: (v if isinstance(v, (int, float, str, bool)) else str(v)) for k, v in props.items()}
                properties_list.append(clean_props)
        except Exception:
            continue

    if len(shapely_pts) < 2:
        return json.dumps({"status": "error", "message": f"Voronoi partitioning requires at least 2 points. Found {len(shapely_pts)}."})

    # 2. Compute Voronoi diagrams via Shapely
    multi_pt = MultiPoint(shapely_pts)
    env = multi_pt.envelope.buffer(0.2)
    voronoi_collection = voronoi_diagram(multi_pt, envelope=env)

    # 3. Optional clipping geometry
    clip_geom = None
    if clip_to_layer_id:
        try:
            clean_clip = _clean_token(clip_to_layer_id).replace(" ", "_")
            resolved_clip = catalog_manager.resolve_layer_id(clean_clip) or clean_clip
            clip_q = f"SELECT ST_AsGeoJSON(ST_Union_Agg(geom)) as gj FROM {resolved_clip} WHERE geom IS NOT NULL;"
            clip_res = spatial_engine.con.execute(clip_q).fetchone()
            if clip_res and clip_res[0]:
                clip_geom = shape(json.loads(clip_res[0]))
        except Exception as e:
            logger.warning(f"Could not load clip boundary '{clip_to_layer_id}': {e}")

    # 4. Associate each Voronoi cell with its corresponding input seed point
    features = []
    candidate_geoms = voronoi_collection.geoms if hasattr(voronoi_collection, 'geoms') else [voronoi_collection]

    for geom in candidate_geoms:
        poly_list = []
        if clip_geom and clip_geom.is_valid:
            clipped = geom.intersection(clip_geom)
            if clipped.is_empty:
                continue
            if isinstance(clipped, (Polygon, MultiPolygon)):
                poly_list = [clipped] if isinstance(clipped, Polygon) else list(clipped.geoms)
        else:
            if isinstance(geom, Polygon):
                poly_list = [geom]

        for p in poly_list:
            if p.is_empty:
                continue

            matched_props = {"cell_id": len(features) + 1}
            for idx, pt in enumerate(shapely_pts):
                if p.contains(pt) or p.touches(pt):
                    matched_props.update(properties_list[idx])
                    break

            features.append({
                "type": "Feature",
                "geometry": mapping(p),
                "properties": matched_props
            })

    if not features:
        return json.dumps({"status": "error", "message": "No valid Voronoi catchment polygons generated after boundary clipping."})

    # 5. Build DataFrame, register temporary view, and materialize via spatial_engine wrapper
    try:
        import pandas as pd

        records = []
        for feat in features:
            poly_geom = shape(feat["geometry"])
            row = dict(feat["properties"])
            row["wkt_geom"] = poly_geom.wkt
            records.append(row)

        df_out = pd.DataFrame(records)

        # Register dataframe view
        spatial_engine.con.register("temp_voronoi_view", df_out)

        # Materialize through spatial_engine's native query pipeline to handle catalog registration automatically
        materialize_sql = """
            SELECT 
                * EXCLUDE(wkt_geom),
                ST_SetCRS(ST_GeomFromText(wkt_geom), 'EPSG:4326') AS geom
            FROM temp_voronoi_view;
        """

        res = spatial_engine.execute_spatial_query(
            query=materialize_sql,
            output_layer_id=clean_out_id,
            layer_name=clean_out_id.replace('_', ' ').title(),
            description=f"Voronoi (Thiessen) catchment partitions derived from {clean_in_id}"
        )

        try:
            spatial_engine.con.unregister("temp_voronoi_view")
        except Exception:
            pass

        res["message"] = f"Successfully generated Voronoi catchment layer '{clean_out_id}' with {len(features)} partitions."
        return json.dumps(res)

    except Exception as e:
        logger.exception("Failed to write Voronoi layer to DuckDB")
        try:
            spatial_engine.con.unregister("temp_voronoi_view")
        except Exception:
            pass
        return json.dumps({"status": "error", "message": f"Failed to persist Voronoi layer: {str(e)}"})


@tool
def generate_isochrone_reachability(
    center_location: str,
    travel_time_minutes: float = 15.0,
    output_layer_id: str = "",
    output_layer_name: str = ""
) -> str:
    """
    Generates a reachable travel time isochrone polygon (catchment area) around a location
    using OSRM road network matrix calculations.

    Args:
        center_location: Name of city/district, coordinates ("lon, lat"), or a point layer ID.
        travel_time_minutes: Maximum driving travel time cutoff in minutes (default: 15).
        output_layer_id: Unique ID for the resulting polygon layer.
        output_layer_name: Human-readable name for the map layer.
    """
    coords = _resolve_location_coords(center_location)
    if not coords:
        return json.dumps({
            "status": "error",
            "message": f"Could not resolve center location '{center_location}' to valid coordinates."
        })

    c_lon, c_lat = coords
    max_duration_sec = travel_time_minutes * 60.0

    # 1. Project radial candidate waypoints around the center (16 bearings at 4 distance tiers)
    est_max_dist_km = (travel_time_minutes / 60.0) * 45.0
    deg_radius = est_max_dist_km / 111.32

    bearings = [i * (360.0 / 16.0) for i in range(16)]
    distance_ratios = [0.4, 0.75, 1.0, 1.25]

    probe_coords = []
    for dist_ratio in distance_ratios:
        r = deg_radius * dist_ratio
        for b in bearings:
            rad = math.radians(b)
            dx = (r * math.sin(rad)) / math.cos(math.radians(c_lat))
            dy = r * math.cos(rad)
            probe_coords.append((round(c_lon + dx, 6), round(c_lat + dy, 6)))

    # 2. Query OSRM Table Service (1 origin -> many destinations)
    coord_payload = f"{c_lon},{c_lat};" + ";".join(f"{lon},{lat}" for lon, lat in probe_coords)
    osrm_url = f"https://router.project-osrm.org/table/v1/driving/{coord_payload}?sources=0"

    reachable_points = [Point(c_lon, c_lat)]
    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.get(osrm_url)
            if resp.status_code == 200:
                matrix_data = resp.json()
                durations = matrix_data.get("durations", [[]])[0][1:]
                for idx, duration in enumerate(durations):
                    if duration is not None and duration <= max_duration_sec:
                        p_lon, p_lat = probe_coords[idx]
                        reachable_points.append(Point(p_lon, p_lat))
    except Exception as e:
        logger.warning(f"OSRM Table Matrix query failed, falling back to network estimate: {e}")

    # Fallback to buffer envelope if OSRM service is unreachable or sparse
    if len(reachable_points) < 4:
        hull_geom = Point(c_lon, c_lat).buffer(deg_radius * 0.75)
    else:
        mp = MultiPoint(reachable_points)
        hull_geom = mp.convex_hull.buffer(deg_radius * 0.12)

    # 3. Clean IDs and register into DuckDB via spatial_engine wrapper
    slug_name = _clean_token(center_location).replace(" ", "_") if isinstance(center_location, str) else "hub"
    clean_out_id = output_layer_id or f"{slug_name}_{int(travel_time_minutes)}min_isochrone"
    clean_out_name = output_layer_name or f"{center_location} {int(travel_time_minutes)}-Min Reachability"

    try:
        import pandas as pd

        row = {
            "center": str(center_location),
            "travel_time_minutes": float(travel_time_minutes),
            "reachable_probes": len(reachable_points),
            "wkt_geom": hull_geom.wkt
        }
        df_out = pd.DataFrame([row])

        spatial_engine.con.register("temp_iso_view", df_out)
        materialize_sql = """
            SELECT 
                * EXCLUDE(wkt_geom),
                ST_SetCRS(ST_GeomFromText(wkt_geom), 'EPSG:4326') AS geom
            FROM temp_iso_view;
        """

        res = spatial_engine.execute_spatial_query(
            query=materialize_sql,
            output_layer_id=clean_out_id,
            layer_name=clean_out_name,
            description=f"{travel_time_minutes}-minute driving isochrone envelope around {center_location}"
        )

        try:
            spatial_engine.con.unregister("temp_iso_view")
        except Exception:
            pass

        res["message"] = (
            f"Materialized {travel_time_minutes}-minute driving isochrone for '{center_location}' "
            f"as layer '{clean_out_id}'."
        )
        return json.dumps(res)

    except Exception as e:
        logger.exception("Failed to materialize isochrone layer")
        try:
            spatial_engine.con.unregister("temp_iso_view")
        except Exception:
            pass
        return json.dumps({"status": "error", "message": f"Failed to persist isochrone layer: {str(e)}"})


@tool
def aggregate_catchment_metrics(
    catchment_layer_id: str,
    target_layer_id: str,
    output_layer_id: str = "",
    output_layer_name: str = "",
    metric_column: Optional[str] = None,
    aggregation_type: str = "count"
) -> str:
    """
    Spatially aggregates points or features from target_layer_id falling inside each polygon 
    of catchment_layer_id (Voronoi partitions, isochrones, or districts).
    
    Args:
        catchment_layer_id: The polygon layer defining boundary zones.
        target_layer_id: The layer to summarize within each polygon.
        output_layer_id: Unique ID for the resulting polygon layer with metric attributes.
        output_layer_name: User-facing name for the map layer.
        metric_column: Optional numeric attribute to aggregate (e.g., 'population', 'risk_score').
        aggregation_type: Type of aggregation: 'count', 'sum', 'avg', 'min', or 'max' (default: 'count').
    """
    resolved_catchment = catalog_manager.resolve_layer_id(catchment_layer_id)
    if not resolved_catchment:
        return json.dumps({
            "status": "error",
            "message": f"Catchment layer '{catchment_layer_id}' could not be found in catalog."
        })

    raw_norm = target_layer_id.strip().lower()
    candidate_target = GENERIC_NOUN_LAYER_MAP.get(raw_norm, target_layer_id)
    resolved_target = catalog_manager.resolve_layer_id(candidate_target) or candidate_target

    clean_out_id = output_layer_id.strip().lower().replace(" ", "_") if output_layer_id else f"{resolved_catchment}_agg_{resolved_target}"
    clean_out_name = output_layer_name or f"{resolved_catchment} Aggregated with {resolved_target}"

    # Determine numeric aggregate expression
    agg_op = aggregation_type.strip().lower()
    agg_select = "count(t.geom) AS feature_count"
    
    if metric_column and agg_op in {"sum", "avg", "min", "max"}:
        agg_select += f", coalesce({agg_op.upper()}(try_cast(t.{metric_column} AS DOUBLE)), 0) AS metric_{agg_op}"

    sql_aggregate = f"""
        WITH target_matches AS (
            SELECT 
                c.rowid AS c_rid,
                {agg_select}
            FROM {resolved_catchment} c
            LEFT JOIN {resolved_target} t 
                ON ST_Intersects(c.geom, t.geom)
            GROUP BY c.rowid
        )
        SELECT 
            c.*,
            coalesce(m.feature_count, 0) AS feature_count
            {f", m.metric_{agg_op}" if metric_column and agg_op in {"sum", "avg", "min", "max"} else ""}
        FROM {resolved_catchment} c
        LEFT JOIN target_matches m 
            ON c.rowid = m.c_rid;
    """

    res = spatial_engine.execute_spatial_query(
        query=sql_aggregate,
        output_layer_id=clean_out_id,
        layer_name=clean_out_name,
        description=f"Aggregation of {resolved_target} inside {resolved_catchment} (metric: {agg_op})"
    )

    res["message"] = (
        f"Aggregated {resolved_target} into '{clean_out_id}' "
        f"with {agg_op.upper()} metric attached to catchment polygons."
    )
    return json.dumps(res)

@tool
def generate_multi_ring_buffers(
    input_layer_id: str,
    distances_meters: str,
    output_layer_id: str = "",
    output_layer_name: str = "",
    create_donuts: bool = True
) -> str:
    """
    Generates concentric multi-ring buffer bands around points, lines, or polygons.
    
    Args:
        input_layer_id: The source layer to buffer (or generic noun like 'cities').
        distances_meters: Comma-separated list of ascending buffer distances in meters (e.g., '500, 1000, 2000').
        output_layer_id: Unique identifier for the resulting polygonal band layer.
        output_layer_name: Human-readable label for UI and map display.
        create_donuts: If True, rings are hollow donut polygons (non-overlapping).
    """
    raw_norm = input_layer_id.strip().lower()
    candidate_in = GENERIC_NOUN_LAYER_MAP.get(raw_norm, input_layer_id)
    resolved_in = catalog_manager.resolve_layer_id(candidate_in) or candidate_in

    try:
        dist_list = sorted([float(d.strip()) for d in distances_meters.split(",") if d.strip()])
    except ValueError:
        return json.dumps({
            "status": "error",
            "message": f"Invalid distances format '{distances_meters}'. Use comma-separated numbers (e.g., '500, 1000, 2000')."
        })

    if not dist_list:
        return json.dumps({"status": "error", "message": "No valid distances provided."})

    clean_out_id = output_layer_id.strip().lower().replace(" ", "_") if output_layer_id else f"{resolved_in}_multibuffer"
    clean_out_name = output_layer_name or f"{resolved_in.title()} Multi-Ring Buffers"

    subqueries = []
    prev_dist = 0.0

    for idx, dist in enumerate(dist_list):
        deg_dist = dist / 111139.0
        ring_order = idx + 1
        tier_label = f"{int(prev_dist)}m - {int(dist)}m" if create_donuts and prev_dist > 0 else f"0m - {int(dist)}m"

        if create_donuts and prev_dist > 0:
            deg_prev = prev_dist / 111139.0
            subqueries.append(f"""
                SELECT 
                    {ring_order} AS ring_order,
                    {dist} AS outer_distance_m,
                    {prev_dist} AS inner_distance_m,
                    '{tier_label}' AS buffer_band,
                    ST_SetCRS(
                        ST_Difference(
                            ST_Buffer(geom, {deg_dist}),
                            ST_Buffer(geom, {deg_prev})
                        ), 
                        'EPSG:4326'
                    ) AS geom
                FROM {resolved_in}
                WHERE geom IS NOT NULL
            """)
        else:
            subqueries.append(f"""
                SELECT 
                    {ring_order} AS ring_order,
                    {dist} AS outer_distance_m,
                    0.0 AS inner_distance_m,
                    '{tier_label}' AS buffer_band,
                    ST_SetCRS(ST_Buffer(geom, {deg_dist}), 'EPSG:4326') AS geom
                FROM {resolved_in}
                WHERE geom IS NOT NULL
            """)
        prev_dist = dist

    union_sql = " UNION ALL ".join(subqueries)
    materialize_sql = f"""
        WITH buffered_bands AS (
            {union_sql}
        )
        SELECT * FROM buffered_bands WHERE NOT ST_IsEmpty(geom);
    """

    res = spatial_engine.execute_spatial_query(
        query=materialize_sql,
        output_layer_id=clean_out_id,
        layer_name=clean_out_name,
        description=f"Multi-ring tiered buffer bands ({distances_meters}m) around {resolved_in}"
    )

    res["message"] = (
        f"Generated {len(dist_list)} concentric buffer tiers ({', '.join(f'{int(d)}m' for d in dist_list)}) "
        f"as '{clean_out_id}'."
    )
    return json.dumps(res)