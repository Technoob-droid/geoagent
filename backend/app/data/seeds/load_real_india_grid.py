import json
import logging
import urllib.parse
import urllib.request

from backend.app.tools.catalog import catalog_manager
from backend.app.tools.engine import spatial_engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("load_real_connected_grid")

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# Overpass query to extract lines, distribution feeders, switches, and substations
OVERPASS_QUERY = """
[out:json][timeout:300];
area["ISO3166-1"="IN"][admin_level=2]->.india;
(
  way["power"="line"](area.india);
  way["power"="minor_line"](area.india);
  node["power"="switch"](area.india);
  node["power"="substation"](area.india);
  way["power"="substation"](area.india);
);
out body geom;
"""


def fetch_osm_power_network():
    logger.info("Fetching complete electrical network from Overpass API (this may take 1-2 minutes)...")
    req = urllib.request.Request(
        OVERPASS_URL,
        data=f"data={urllib.parse.quote(OVERPASS_QUERY)}".encode("utf-8"),
        headers={"User-Agent": "GeoAgent-Topological-Grid/2.0"},
    )
    with urllib.request.urlopen(req, timeout=360) as response:
        return json.loads(response.read().decode("utf-8"))


def parse_voltage(v_str, default_val=33.0):
    if not v_str:
        return default_val
    try:
        cleaned = (
            str(v_str)
            .replace("kV", "")
            .replace("kv", "")
            .replace(" ", "")
            .split(";")[0]
        )
        val = float(cleaned)
        return val / 1000.0 if val >= 1000 else val
    except Exception:
        return default_val


def classify_tier(voltage_kv):
    if voltage_kv >= 132.0:
        return "GSS"
    elif voltage_kv >= 33.0:
        return "PSS"
    else:
        return "DSS"


def load_connected_network():
    con = spatial_engine.con
    raw = fetch_osm_power_network()
    elements = raw.get("elements", [])
    logger.info(f"Retrieved {len(elements)} total grid elements.")

    feeders = []
    switches = []
    substations = []

    for el in elements:
        tags = el.get("tags", {})
        el_type = el.get("type")
        osm_id = str(el.get("id"))
        power_type = tags.get("power")

        # 1. Connected Transmission Lines & Distribution Feeders (LINESTRING)
        if el_type == "way" and power_type in ("line", "minor_line", "cable"):
            geom_coords = el.get("geometry", [])
            if len(geom_coords) >= 2:
                wkt_pts = ", ".join([f"{pt['lon']} {pt['lat']}" for pt in geom_coords])
                wkt = f"LINESTRING({wkt_pts})"
                v_kv = parse_voltage(tags.get("voltage"), 11.0 if power_type == "minor_line" else 132.0)
                tier = (
                    "EHV_TRANSMISSION"
                    if v_kv >= 132
                    else ("SUB_TRANSMISSION" if v_kv >= 33 else "DISTRIBUTION_FEEDER")
                )
                feeders.append((
                    f"FDR_{osm_id}",
                    tags.get("name") or f"Feeder-{osm_id}",
                    v_kv,
                    tier,
                    tags.get("operator", "State DISCOM / PGCIL"),
                    tags.get("cables", "3"),
                    "ENERGIZED",
                    wkt,
                ))

        # 2. Protection Switchgear (POINT)
        elif el_type == "node" and power_type == "switch":
            lat, lon = el.get("lat"), el.get("lon")
            if lat and lon:
                v_kv = parse_voltage(tags.get("voltage"), 33.0)
                switches.append((
                    f"SW_{osm_id}",
                    tags.get("name") or f"Switch-{osm_id}",
                    tags.get("switch", "circuit_breaker"),
                    v_kv,
                    "CLOSED",
                    "NORMAL",
                    float(lon),
                    float(lat),
                ))

        # 3. Substations (POINT)
        elif power_type == "substation":
            lat = el.get("lat") or (
                el.get("geometry", [{}])[0].get("lat") if el.get("geometry") else None
            )
            lon = el.get("lon") or (
                el.get("geometry", [{}])[0].get("lon") if el.get("geometry") else None
            )
            if lat and lon:
                v_kv = parse_voltage(tags.get("voltage"), 33.0)
                tier = classify_tier(v_kv)
                substations.append((
                    f"{tier}_{osm_id}",
                    tags.get("name") or f"Substation-{osm_id}",
                    tier,
                    v_kv,
                    tags.get("operator", "State DISCOM / PGCIL"),
                    tags.get("substation", "transmission"),
                    "OPERATIONAL",
                    float(lon),
                    float(lat),
                ))

    # Populate Substations
    con.execute("DROP TABLE IF EXISTS utility_substations_master;")
    con.execute("""
        CREATE TABLE utility_substations_master (
            substation_id VARCHAR PRIMARY KEY,
            substation_name VARCHAR,
            tier VARCHAR,
            voltage_kv DOUBLE,
            operator VARCHAR,
            substation_type VARCHAR,
            operational_status VARCHAR,
            geom GEOMETRY
        );
    """)
    for s in substations:
        con.execute(
            "INSERT INTO utility_substations_master VALUES (?, ?, ?, ?, ?, ?, ?, ST_Point(?, ?));",
            s,
        )

    # Populate Switchgear
    con.execute("DROP TABLE IF EXISTS utility_switchgear_master;")
    con.execute("""
        CREATE TABLE utility_switchgear_master (
            switch_id VARCHAR PRIMARY KEY,
            switch_name VARCHAR,
            switch_type VARCHAR,
            voltage_kv DOUBLE,
            switching_state VARCHAR,
            operational_status VARCHAR,
            geom GEOMETRY
        );
    """)
    for sw in switches:
        con.execute(
            "INSERT INTO utility_switchgear_master VALUES (?, ?, ?, ?, ?, ?, ST_Point(?, ?));",
            sw,
        )

    # Populate Feeders & Transmission Lines
    con.execute("DROP TABLE IF EXISTS utility_feeders_master;")
    con.execute("""
        CREATE TABLE utility_feeders_master (
            feeder_id VARCHAR PRIMARY KEY,
            feeder_name VARCHAR,
            voltage_kv DOUBLE,
            network_tier VARCHAR,
            operator VARCHAR,
            circuit_count VARCHAR,
            operational_status VARCHAR,
            geom GEOMETRY
        );
    """)
    for f in feeders:
        con.execute(
            "INSERT INTO utility_feeders_master VALUES (?, ?, ?, ?, ?, ?, ?, ST_GeomFromText(?));",
            f,
        )

    # Topological Snapping: Link Start and End Points to Substation IDs
    logger.info("Snapping feeders to terminal substations to establish network graph...")
    con.execute("""
        ALTER TABLE utility_feeders_master ADD COLUMN from_substation_id VARCHAR;
        ALTER TABLE utility_feeders_master ADD COLUMN to_substation_id VARCHAR;

        UPDATE utility_feeders_master f
        SET from_substation_id = (
            SELECT s.substation_id
            FROM utility_substations_master s
            WHERE ST_DWithin(ST_StartPoint(f.geom), s.geom, 0.005)
            ORDER BY ST_Distance(ST_StartPoint(f.geom), s.geom) ASC
            LIMIT 1
        );

        UPDATE utility_feeders_master f
        SET to_substation_id = (
            SELECT s.substation_id
            FROM utility_substations_master s
            WHERE ST_DWithin(ST_EndPoint(f.geom), s.geom, 0.005)
            ORDER BY ST_Distance(ST_EndPoint(f.geom), s.geom) ASC
            LIMIT 1
        );
    """)

    # Register all three tables in the catalog
    sub_count = con.execute("SELECT count(*) FROM utility_substations_master;").fetchone()[0]
    sw_count = con.execute("SELECT count(*) FROM utility_switchgear_master;").fetchone()[0]
    fdr_count = con.execute("SELECT count(*) FROM utility_feeders_master;").fetchone()[0]

    catalog_manager.register_layer(
        layer_id="utility_substations_master",
        name="All-India Substations (GSS/PSS/DSS)",
        table_name="utility_substations_master",
        geom_type="POINT",
        feature_count=sub_count,
        description="National electric grid substations across India classified by voltage tier (GSS/PSS/DSS).",
    )
    catalog_manager.register_layer(
        layer_id="utility_switchgear_master",
        name="All-India Protection Switchgear",
        table_name="utility_switchgear_master",
        geom_type="POINT",
        feature_count=sw_count,
        description="National circuit breakers, disconnectors, and RMU protection switchgear assets.",
    )
    catalog_manager.register_layer(
        layer_id="utility_feeders_master",
        name="All-India Transmission & Distribution Feeders",
        table_name="utility_feeders_master",
        geom_type="LINESTRING",
        feature_count=fdr_count,
        description="Connected physical transmission circuits and distribution feeder corridors with terminal topological foreign keys.",
    )

    logger.info(
        f"Topological grid generated: {sub_count:,} substations, {sw_count:,} switches, {fdr_count:,} connected feeders."
    )


if __name__ == "__main__":
    load_connected_network()