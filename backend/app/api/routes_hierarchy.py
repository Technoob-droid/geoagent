from backend.app.tools.engine import spatial_engine
import json
import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from backend.app.tools import inspect_discom_hierarchy
from backend.app.tools.catalog import catalog_manager

logger = logging.getLogger("geoagent.api.hierarchy")
router = APIRouter(prefix="/api/hierarchy", tags=["hierarchy"])

class HierarchyInspectRequest(BaseModel):
    level: str = "Circle"
    target_circle: Optional[str] = None
    output_layer_id: Optional[str] = None

@router.get("/{discom}")
async def get_discom_hierarchy(
    discom: str,
    level: str = Query("Circle", description="Hierarchy level: Circle, Division, Subdivision, Section, GSS, PSS, DSS, Feeders, Consumers"),
    target_circle: Optional[str] = Query(None, description="Optional filter, e.g., 'SEEC SAMBALPUR'"),
    output_layer_id: Optional[str] = Query(None, description="Optional custom layer ID")
):
    """
    Retrieves or materializes a spatial layer for a specified DISCOM hierarchy tier.
    """
    try:
        raw_result = inspect_discom_hierarchy.invoke({
            "discom_name": discom,
            "level": level,
            "target_circle": target_circle,
            "output_layer_id": output_layer_id
        })
        res = json.loads(raw_result)
        if res.get("status") == "error":
            raise HTTPException(status_code=400, detail=res.get("message"))
        
        layer_id = res.get("layer_id")
        layer_meta = catalog_manager.get_layer_details(layer_id)
        
        res["tile_url"] = f"/api/layers/tiles/{layer_id}/{{z}}/{{x}}/{{y}}.pbf"
        res["metadata"] = layer_meta
        return res
    except Exception as e:
        logger.error(f"Error inspecting hierarchy for {discom}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/{discom}/inspect")
async def post_inspect_hierarchy(discom: str, req: HierarchyInspectRequest):
    """
    POST variant for inspecting and materializing DISCOM hierarchy tiers.
    """
    return await get_discom_hierarchy(
        discom=discom,
        level=req.level,
        target_circle=req.target_circle,
        output_layer_id=req.output_layer_id
    )


@router.get("/config/schema")
async def get_hierarchy_schema():
    """
    Returns layer schemas, zoom thresholds, geometry types, and default styling for all 9 tiers.
    """
    return {
        "Circle": {
            "tier_level": 1,
            "label": "Electrical Circle",
            "category": "administrative",
            "geom_type": "MULTIPOLYGON",
            "min_zoom": 4,
            "max_zoom": 10,
            "default_color": "#6366f1"
        },
        "Division": {
            "tier_level": 2,
            "label": "Operational Division",
            "category": "administrative",
            "geom_type": "MULTIPOLYGON",
            "min_zoom": 7,
            "max_zoom": 12,
            "default_color": "#0ea5e9"
        },
        "Subdivision": {
            "tier_level": 3,
            "label": "Subdivision (Block/Tehsil)",
            "category": "administrative",
            "geom_type": "MULTIPOLYGON",
            "min_zoom": 9,
            "max_zoom": 14,
            "default_color": "#10b981"
        },
        "Section": {
            "tier_level": 4,
            "label": "Utility Section",
            "category": "administrative",
            "geom_type": "MULTIPOLYGON",
            "min_zoom": 10,
            "max_zoom": 15,
            "default_color": "#f59e0b"
        },
        "GSS": {
            "tier_level": 5,
            "label": "Grid Substation (>=132kV)",
            "category": "electrical_node",
            "geom_type": "POINT",
            "min_zoom": 8,
            "max_zoom": 22,
            "default_color": "#dc2626"
        },
        "PSS": {
            "tier_level": 6,
            "label": "Primary Substation (33/11kV)",
            "category": "electrical_node",
            "geom_type": "POINT",
            "min_zoom": 9,
            "max_zoom": 22,
            "default_color": "#ea580c"
        },
        "DSS": {
            "tier_level": 7,
            "label": "Distribution Substation (11/0.415kV)",
            "category": "electrical_node",
            "geom_type": "POINT",
            "min_zoom": 11,
            "max_zoom": 22,
            "default_color": "#8b5cf6"
        },
        "Feeders": {
            "tier_level": 8,
            "label": "11kV / 33kV Feeder Lines",
            "category": "electrical_line",
            "geom_type": "MULTILINESTRING",
            "min_zoom": 10,
            "max_zoom": 22,
            "default_color": "#eab308"
        },
        "Consumers": {
            "tier_level": 9,
            "label": "Consumer Settlement Nodes",
            "category": "consumer_cluster",
            "geom_type": "POINT",
            "min_zoom": 12,
            "max_zoom": 22,
            "default_color": "#06b6d4"
        }
    }


@router.get("/{discom}/trace/downstream")
async def trace_downstream_network(
    discom: str,
    pss_name: Optional[str] = Query(None, description="Name or identifier of Primary Substation"),
    pss_id: Optional[str] = Query(None, description="Substation ID"),
    district_name: Optional[str] = Query(None, description="District name fallback, e.g. Sambalpur"),
    proximity_deg: float = Query(0.05, description="Feeder proximity buffer in degrees (~5km)"),
    lt_radius_deg: float = Query(0.03, description="DSS to consumer service radius in degrees (~3km)")
):
    """
    Downstream electrical trace: PSS -> Outgoing Feeders -> Terminal DSS -> Consumer Settlements.
    """
    from backend.app.tools.engine import spatial_engine

    from_clause = "utility_substations_master s"
    if pss_id:
        where_clause = f"s.substation_id = '{pss_id}'"
    elif pss_name:
        where_clause = f"UPPER(s.substation_name) LIKE UPPER('%{pss_name}%')"
    elif district_name:
        from_clause = "utility_substations_master s JOIN india_districts d ON ST_Intersects(s.geom, d.geom)"
        where_clause = f"UPPER(d.district_name) = UPPER('{district_name}') AND (s.voltage_kv < 132 OR UPPER(s.tier) = 'PSS')"
    else:
        where_clause = "UPPER(s.tier) = 'PSS' OR s.voltage_kv < 132"

    trace_sql = f"""
    WITH target_pss AS (
        SELECT s.substation_id, s.substation_name, s.voltage_kv, s.geom,
               ST_X(s.geom) AS lng, ST_Y(s.geom) AS lat
        FROM {from_clause}
        WHERE {where_clause}
        LIMIT 1
    ),
    feeders AS (
        SELECT 
            f.feeder_id,
            f.feeder_name,
            f.voltage_kv,
            f.geom AS feeder_geom,
            pss.substation_name AS parent_pss,
            pss.substation_id AS parent_pss_id,
            pss.lng AS pss_lng,
            pss.lat AS pss_lat
        FROM target_pss pss
        JOIN utility_feeders_master f 
          ON ST_DWithin(f.geom, pss.geom, {proximity_deg})
    ),
    dss AS (
        SELECT 
            cf.feeder_id || '_DSS' AS dss_id,
            cf.feeder_id,
            cf.feeder_name,
            cf.parent_pss,
            cf.parent_pss_id,
            cf.pss_lng,
            cf.pss_lat,
            ST_EndPoint(cf.feeder_geom) AS dss_geom,
            ST_X(ST_EndPoint(cf.feeder_geom)) AS dss_lng,
            ST_Y(ST_EndPoint(cf.feeder_geom)) AS dss_lat
        FROM feeders cf
    ),
    consumers AS (
        SELECT 
            d.dss_id,
            d.feeder_id,
            d.feeder_name,
            d.parent_pss,
            d.parent_pss_id,
            d.pss_lng,
            d.pss_lat,
            d.dss_lng,
            d.dss_lat,
            v.village_name AS consumer_node,
            ROUND(ST_Distance(v.geom, d.dss_geom) * 111.32, 2) AS distance_km,
            ST_X(v.geom) AS consumer_lng,
            ST_Y(v.geom) AS consumer_lat
        FROM dss d
        JOIN india_villages v 
          ON ST_DWithin(v.geom, d.dss_geom, {lt_radius_deg})
    )
    SELECT * FROM consumers
    ORDER BY feeder_id, distance_km;
    """

    try:
        df = spatial_engine.execute_query(trace_sql)
        if len(df) == 0:
            return {
                "status": "empty",
                "discom": discom,
                "message": "No connected network traced within the specified spatial proximity.",
                "substation": pss_name or pss_id or "default"
            }
        
        # Build hierarchical tree structure
        first_row = df.iloc[0]
        root_pss = {
            "substation_id": str(first_row["parent_pss_id"]),
            "substation_name": str(first_row["parent_pss"]),
            "coordinates": [float(first_row["pss_lng"]), float(first_row["pss_lat"])]
        }

        feeders_dict = {}
        for _, row in df.iterrows():
            f_id = row["feeder_id"]
            if f_id not in feeders_dict:
                feeders_dict[f_id] = {
                    "feeder_id": str(f_id),
                    "feeder_name": str(row["feeder_name"]),
                    "dss_id": str(row["dss_id"]),
                    "dss_coordinates": [float(row["dss_lng"]), float(row["dss_lat"])],
                    "consumers": []
                }
            feeders_dict[f_id]["consumers"].append({
                "village_name": str(row["consumer_node"]),
                "distance_km": float(row["distance_km"]),
                "coordinates": [float(row["consumer_lng"]), float(row["consumer_lat"])]
            })

        return {
            "status": "success",
            "discom": discom,
            "root_substation": root_pss,
            "feeder_count": len(feeders_dict),
            "consumer_count": len(df),
            "topology": list(feeders_dict.values())
        }
    except Exception as e:
        logger.error(f"Error executing downstream trace for {discom}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/network-summary/options")
async def get_network_summary_options(
    circle: Optional[str] = Query(None),
    division: Optional[str] = Query(None),
    subdivision: Optional[str] = Query(None),
    section: Optional[str] = Query(None),
    gss: Optional[str] = Query(None),
    hv_feeder: Optional[str] = Query(None),
    pss: Optional[str] = Query(None),
    mv_feeder: Optional[str] = Query(None),
    dss: Optional[str] = Query(None)
):
    """
    Cascading 10-tier options for TPWODL Network Summary filter panel:
    Circle -> Division -> Sub Division -> Section -> GSS -> HV Feeder -> PSS -> MV Feeder -> DSS -> LV Feeder
    """
    try:
        # 1. Circle list
        circles_df = spatial_engine.execute_query("SELECT circle_name FROM tpwodl_circles ORDER BY circle_name;")
        circles = circles_df['circle_name'].dropna().tolist() if not circles_df.empty else [
            "SEEC SAMBALPUR", "SEEC RAURKELA", "SEEC BARAGADA", "SEEC BALANGIR", "SEEC KALAHANDI"
        ]

        # 2. Administrative child tiers (Division, Sub Division, Section) derived via geometry of selected circle
        circle_geom_clause = ""
        if circle:
            circle_geom_clause = f"AND ST_Intersects(d.geom, (SELECT geom FROM tpwodl_circles WHERE circle_name = '{circle}' LIMIT 1))"

        divisions_query = f"""
            SELECT DISTINCT d.district_name as division_name
            FROM india_districts d
            WHERE d.state_name = 'Odisha' {circle_geom_clause}
            ORDER BY division_name;
        """
        divisions_df = spatial_engine.execute_query(divisions_query)
        divisions = divisions_df['division_name'].dropna().tolist() if not divisions_df.empty else []

        div_geom_clause = ""
        if division:
            div_geom_clause = f"AND ST_Intersects(sd.geom, (SELECT geom FROM india_districts WHERE district_name = '{division}' LIMIT 1))"
        elif circle:
            div_geom_clause = f"AND ST_Intersects(sd.geom, (SELECT geom FROM tpwodl_circles WHERE circle_name = '{circle}' LIMIT 1))"

        subdivisions_query = f"""
            SELECT DISTINCT sd.subdistrict_name
            FROM india_subdistricts sd
            WHERE 1=1 {div_geom_clause}
            LIMIT 50;
        """
        subdiv_df = spatial_engine.execute_query(subdivisions_query)
        subdivisions = subdiv_df['subdistrict_name'].dropna().tolist() if not subdiv_df.empty else []

        sections = [f"{sd} Section" for sd in subdivisions[:10]]

        # 3. Spatial bounding scope for electrical entities
        filter_scope_geom = "(SELECT geom FROM tpwodl_circles WHERE circle_name = 'SEEC SAMBALPUR' LIMIT 1)"
        if circle:
            filter_scope_geom = f"(SELECT geom FROM tpwodl_circles WHERE circle_name = '{circle}' LIMIT 1)"
        if division:
            filter_scope_geom = f"(SELECT geom FROM india_districts WHERE district_name = '{division}' LIMIT 1)"

        # 4. GSS (>= 132 kV)
        gss_query = f"""
            SELECT DISTINCT s.substation_name, s.substation_id
            FROM utility_substations_master s
            WHERE s.voltage_kv >= 132
              AND ST_Intersects(s.geom, {filter_scope_geom})
            ORDER BY s.substation_name
            LIMIT 50;
        """
        gss_df = spatial_engine.execute_query(gss_query)
        gss_list = [f"{r['substation_name']} ({r['substation_id']})" for _, r in gss_df.iterrows()] if not gss_df.empty else []

        # 5. HV Feeders (33 kV sub-transmission lines)
        hv_query = f"""
            SELECT DISTINCT f.feeder_name, f.feeder_id
            FROM utility_feeders_master f
            WHERE f.voltage_kv = 33
              AND ST_Intersects(f.geom, {filter_scope_geom})
            ORDER BY f.feeder_name
            LIMIT 50;
        """
        hv_df = spatial_engine.execute_query(hv_query)
        hv_feeders = [f"{r['feeder_name']} ({r['feeder_id']})" for _, r in hv_df.iterrows()] if not hv_df.empty else []

        # 6. PSS (33/11 kV Primary Substations)
        pss_query = f"""
            SELECT DISTINCT s.substation_name, s.substation_id
            FROM utility_substations_master s
            WHERE s.voltage_kv < 132 AND (UPPER(s.tier) = 'PSS' OR s.voltage_kv = 33)
              AND ST_Intersects(s.geom, {filter_scope_geom})
            ORDER BY s.substation_name
            LIMIT 50;
        """
        pss_df = spatial_engine.execute_query(pss_query)
        pss_list = [f"{r['substation_name']} ({r['substation_id']})" for _, r in pss_df.iterrows()] if not pss_df.empty else []

        # 7. MV Feeders (11 kV distribution lines)
        mv_query = f"""
            SELECT DISTINCT f.feeder_name, f.feeder_id
            FROM utility_feeders_master f
            WHERE f.voltage_kv = 11
              AND ST_Intersects(f.geom, {filter_scope_geom})
            ORDER BY f.feeder_name
            LIMIT 50;
        """
        mv_df = spatial_engine.execute_query(mv_query)
        mv_feeders = [f"{r['feeder_name']} ({r['feeder_id']})" for _, r in mv_df.iterrows()] if not mv_df.empty else []

        # 8. DSS & LV Feeders
        dss_list = [f"DSS_{f.split(' ')[0]}" for f in mv_feeders[:25]]
        lv_feeders = [f"LV_{f.split(' ')[0]}_C1" for f in mv_feeders[:25]]

        return {
            "status": "success",
            "circle": circles,
            "division": divisions,
            "subdivision": subdivisions,
            "section": sections,
            "gss": gss_list,
            "hv_feeder": hv_feeders,
            "pss": pss_list,
            "mv_feeder": mv_feeders,
            "dss": dss_list,
            "lv_feeder": lv_feeders
        }
    except Exception as e:
        logger.error(f"Error fetching network summary options: {e}")
        return {"status": "error", "message": str(e)}
