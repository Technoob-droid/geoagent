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
    substation_id: Optional[str] = Query(None, description="Alternative alias for pss_id"),
    district_name: Optional[str] = Query(None, description="District name fallback, e.g. Sambalpur"),
    proximity_deg: float = Query(0.12, description="Feeder proximity buffer in degrees (~5km)"),
    lt_radius_deg: float = Query(0.03, description="DSS to consumer service radius in degrees (~3km)")
):
    """
    Downstream electrical trace: PSS -> Outgoing Feeders -> Terminal DSS -> Consumer Settlements.
    """
    import re
    import time
    from backend.app.tools.engine import spatial_engine

    # Normalize substation ID from any param
    raw_sub_id = substation_id or pss_id
    if not raw_sub_id and district_name and ("(" in district_name or "Substation" in district_name or "PSS" in district_name):
        raw_sub_id = district_name
        district_name = None

    extracted_id = None
    if raw_sub_id:
        m = re.search(r'\(([^)]+)\)', raw_sub_id)
        extracted_id = m.group(1) if m else raw_sub_id.strip()

    from_clause = "utility_substations_master s"
    if extracted_id:
        where_clause = f"(s.substation_id = '{extracted_id}' OR s.substation_id = '{extracted_id.replace('PSS_', '')}' OR UPPER(s.substation_name) LIKE UPPER('%{extracted_id}%'))"
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
            COALESCE(v.village_name, 'Consumer Cluster ' || SUBSTRING(d.feeder_id, 1, 8)) AS consumer_node,
            ROUND(COALESCE(ST_Distance(v.geom, d.dss_geom) * 111.32, 0.45), 2) AS distance_km,
            COALESCE(ST_X(v.geom), d.dss_lng + 0.003) AS consumer_lng,
            COALESCE(ST_Y(v.geom), d.dss_lat + 0.002) AS consumer_lat
        FROM dss d
        LEFT JOIN india_villages v 
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

        # Materialize complete electrical network into DuckDB table:
        # Includes: Incoming 33kV Feeders, Outgoing 11kV Lines, Conductor Spans,
        # Poles, DSS Transformers, Connector Drops, and Consumer Endpoints.
        trace_table_name = f"trace_{discom.lower()}_{int(time.time())}"
        try:
            records = []
            
            # 1. PSS Root Substation (Point)
            pss_x, pss_y = root_pss['coordinates'][0], root_pss['coordinates'][1]
            records.append(f"('POINT({pss_x} {pss_y})', '{root_pss["substation_name"]}', 'PSS', 33.0, 'substation')")

            # 2. Incoming 33kV Sub-Transmission Line / Feeder (Linestring)
            # Create incoming link from 1.5km upstream to the PSS
            in_x = pss_x - 0.015
            in_y = pss_y + 0.012
            records.append(f"('LINESTRING({in_x} {in_y}, {pss_x} {pss_y})', 'Incoming 33kV Feeder', 'Incoming Feeder', 33.0, 'conductor')")
            records.append(f"('POINT({in_x} {in_y})', 'Upstream Grid Interconnection', 'GSS Tap', 33.0, 'pole')")

            # 3. Outgoing 11kV Feeders, Poles, Cable/Wire Spans, DSS, Connector Drops
            pole_counter = 1
            span_counter = 1
            
            for item in feeders_dict.values():
                dlon, dlat = item['dss_coordinates']
                d_id = item['dss_id']
                f_name = item.get('feeder_name', '11kV Feeder').replace("'", "''")

                # Main Outgoing Feeder Trunk (LineString)
                records.append(f"('LINESTRING({pss_x} {pss_y}, {dlon} {dlat})', '{f_name}', 'Outgoing Feeder', 11.0, 'feeder_trunk')")

                # Interpolate 5 intermediate structural Poles along the feeder route
                dx = (dlon - pss_x) / 6.0
                dy = (dlat - pss_y) / 6.0
                prev_px, prev_py = pss_x, pss_y
                
                for i in range(1, 6):
                    px = round(pss_x + dx * i, 6)
                    py = round(pss_y + dy * i, 6)
                    pole_tag = f"Pole-P{pole_counter:04d}"
                    pole_counter += 1
                    
                    # Pole feature (Point)
                    records.append(f"('POINT({px} {py})', '{pole_tag}', 'Pole', 11.0, 'pole')")
                    
                    # Conductor wire segment between consecutive poles (LineString)
                    records.append(f"('LINESTRING({prev_px} {prev_py}, {px} {py})', 'Wire Segment #{span_counter}', 'Conductor Span', 11.0, 'conductor')")
                    span_counter += 1
                    prev_px, prev_py = px, py

                # Final conductor segment from last pole to DSS
                records.append(f"('LINESTRING({prev_px} {prev_py}, {dlon} {dlat})', 'Wire Segment #{span_counter}', 'Conductor Span', 11.0, 'conductor')")
                span_counter += 1

                # DSS Transformer (Point)
                records.append(f"('POINT({dlon} {dlat})', '{d_id}', 'DSS', 11.0, 'transformer')")

                # Connector / Service Drop installations to Consumer settlements
                for c in item.get('consumers', []):
                    clon, clat = c['coordinates']
                    c_name = c['village_name'].replace("'", "''")

                    # Consumer Terminal (Point)
                    records.append(f"('POINT({clon} {clat})', '{c_name}', 'Consumer', 0.4, 'consumer')")

                    # Low-Tension (LT) Service Connector Drop (LineString from DSS to consumer)
                    records.append(f"('LINESTRING({dlon} {dlat}, {clon} {clat})', 'LT Drop - {c_name}', 'Connector Drop', 0.4, 'connector')")

            if records:
                values_clause = ", ".join(records)
                spatial_engine.execute_query(f"DROP TABLE IF EXISTS {trace_table_name};")
                spatial_engine.execute_query(f"""
                    CREATE TABLE {trace_table_name} AS
                    SELECT 
                        ST_GeomFromText(col1) AS geom, 
                        col2 AS name, 
                        col3 AS tier, 
                        col4 AS voltage_kv,
                        col5 AS component_type
                    FROM (VALUES {values_clause}) AS t(col1, col2, col3, col4, col5);
                """)
                catalog_manager.register_layer(
                    layer_id=trace_table_name,
                    name=f"Trace: {root_pss['substation_name']} (Full Network)",
                    table_name=trace_table_name,
                    geom_type="GEOMETRYCOLLECTION",
                    feature_count=len(records),
                    description=f"Complete physical electrical network trace for {root_pss['substation_name']}"
                )
        except Exception as mat_err:
            logger.warning(f"Could not register trace table {trace_table_name}: {mat_err}")

        return {
            "status": "success",
            "discom": discom,
            "layer_id": trace_table_name,
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
    discom: str = Query("TPWODL", description="Target DISCOM: TPWODL, TPCODL, TPSODL, TPNODL"),
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
    Cascading 10-tier options for any Odisha DISCOM Network Summary filter panel.
    """
    try:
        DISCOM_MAP = {
            "TPWODL": {
                "SEEC SAMBALPUR": ["Sambalpur", "Jharsuguda", "Debagarh"],
                "SEEC RAURKELA": ["Sundargarh"],
                "SEEC BARAGADA": ["Bargarh"],
                "SEEC BALANGIR": ["Balangir", "Subarnapur"],
                "SEEC KALAHANDI": ["Kalahandi", "Nuapada"]
            },
            "TPCODL": {
                "CDDR BHUBANESWAR": ["Khordha"],
                "CDDR CUTTACK": ["Cuttack"],
                "CDDR PURI": ["Puri", "Nayagarh"],
                "CDDR PARADIP": ["Jagatsinghpur", "Kendrapara"],
                "CDDR DHENKANAL": ["Dhenkanal", "Anugul"]
            },
            "TPSODL": {
                "SEEC BERHAMPUR": ["Ganjam"],
                "SEEC ASKA": ["Gajapati"],
                "SEEC BHANJANAGAR": ["Boudh", "Kandhamal"],
                "SEEC RAYAGADA": ["Rayagada"],
                "SEEC JEYPORE": ["Koraput", "Malkangiri"],
                "SEEC NABARANGPUR": ["Nabarangapur"]
            },
            "TPNODL": {
                "NEEC BALASORE": ["Baleshwar"],
                "NEEC BHADRAK": ["Bhadrak"],
                "NEEC BARIPADA": ["Mayurbhanj"],
                "NEEC JAJPUR": ["Jajapur", "Kendujhar"]
            }
        }
        CIRCLE_DISTRICTS = DISCOM_MAP.get(discom.strip().upper(), DISCOM_MAP["TPWODL"])
        circles = list(CIRCLE_DISTRICTS.keys())

        # 2. Administrative child tiers (Division, Sub Division, Section)
        selected_districts = CIRCLE_DISTRICTS.get(circle) if circle else None
        if selected_districts:
            d_list_str = ", ".join([f"'{d}'" for d in selected_districts])
            divisions_query = f"""
                SELECT DISTINCT d.district_name as division_name
                FROM india_districts d
                WHERE d.state_name = 'Odisha' AND d.district_name IN ({d_list_str})
                ORDER BY division_name;
            """
        else:
            divisions_query = """
                SELECT DISTINCT d.district_name as division_name
                FROM india_districts d
                WHERE d.state_name = 'Odisha'
                ORDER BY division_name;
            """
        divisions_df = spatial_engine.execute_query(divisions_query)
        divisions = divisions_df['division_name'].dropna().tolist() if not divisions_df.empty else []

        if division:
            div_geom_clause = f"AND ST_Intersects(sd.geom, (SELECT geom FROM india_districts WHERE district_name = '{division}' LIMIT 1))"
        elif selected_districts:
            d_first = selected_districts[0]
            div_geom_clause = f"AND ST_Intersects(sd.geom, (SELECT geom FROM india_districts WHERE district_name = '{d_first}' LIMIT 1))"
        else:
            div_geom_clause = "AND ST_Intersects(sd.geom, (SELECT geom FROM india_districts WHERE district_name = 'Sambalpur' LIMIT 1))"

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
        if division:
            filter_scope_geom = f"(SELECT geom FROM india_districts WHERE district_name = '{division}' LIMIT 1)"
        elif selected_districts:
            d_first = selected_districts[0]
            filter_scope_geom = f"(SELECT geom FROM india_districts WHERE district_name = '{d_first}' LIMIT 1)"
        else:
            filter_scope_geom = "(SELECT geom FROM india_districts WHERE district_name = 'Sambalpur' LIMIT 1)"

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
