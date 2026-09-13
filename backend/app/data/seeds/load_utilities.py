import logging
from pathlib import Path
import duckdb
from backend.app.config import settings

logger = logging.getLogger("geoagent.seeds.utilities")

def seed_utility_network():
    db_path = Path(settings.DUCKDB_DATABASE_PATH)
    print(f"Connecting to DuckDB database at: {db_path.resolve()}")
    conn = duckdb.connect(str(db_path), read_only=False)

    conn.execute("INSTALL spatial; LOAD spatial;")

    # 1. Generation Assets (Point sources)
    conn.execute("""
        CREATE OR REPLACE TABLE utility_generation AS 
        SELECT 
            facility_id,
            facility_name,
            fuel_type,
            capacity_mw,
            ST_SetCRS(ST_Point(lon, lat), 'EPSG:4326') AS geom
        FROM (VALUES
            ('GEN_01', 'Kolaghat Thermal Power Station', 'Thermal', 1260.0, 87.8722, 22.4283),
            ('GEN_02', 'Budge Budge Generating Station', 'Thermal', 750.0, 88.1500, 22.4833),
            ('GEN_03', 'Bakreswar Thermal Power Plant', 'Thermal', 1050.0, 87.3800, 23.8300),
            ('GEN_04', 'Purulia Pumped Storage Hydro', 'Hydro', 900.0, 86.3500, 23.2300),
            ('GEN_05', 'Sagardighi Thermal Power Plant', 'Thermal', 1600.0, 88.1100, 24.3500)
        ) AS t(facility_id, facility_name, fuel_type, capacity_mw, lon, lat);
    """)

    # 2. Transmission Corridors (High-voltage LineStrings)
    conn.execute("""
        CREATE OR REPLACE TABLE utility_transmission_lines AS 
        SELECT 
            line_id,
            line_name,
            voltage_kv,
            source_facility_id,
            ST_SetCRS(ST_GeomFromText(wkt), 'EPSG:4326') AS geom
        FROM (VALUES
            ('TX_400_01', 'Kolaghat - Howrah 400kV Trunk', 400, 'GEN_01', 'LINESTRING(87.8722 22.4283, 88.1200 22.5100, 88.2731 22.5958)'),
            ('TX_220_02', 'Budge Budge - Kolkata South Grid', 220, 'GEN_02', 'LINESTRING(88.1500 22.4833, 88.2800 22.5200, 88.3522 22.5626)'),
            ('TX_400_03', 'Bakreswar - Durgapur - Burdwan Link', 400, 'GEN_03', 'LINESTRING(87.3800 23.8300, 87.3100 23.5500, 87.8500 23.2300)')
        ) AS t(line_id, line_name, voltage_kv, source_facility_id, wkt);
    """)

    # 3. Distribution Substations (Point distribution nodes)
    conn.execute("""
        CREATE OR REPLACE TABLE utility_substations AS 
        SELECT 
            substation_id,
            substation_name,
            voltage_ratio,
            district,
            capacity_mva,
            ST_SetCRS(ST_Point(lon, lat), 'EPSG:4326') AS geom
        FROM (VALUES
            ('SUB_01', 'Howrah Central Substation', '132/33kV', 'Howrah', 150.0, 88.2731, 22.5958),
            ('SUB_02', 'Esplanade Main Substation', '132/33kV', 'Kolkata', 200.0, 88.3522, 22.5626),
            ('SUB_03', 'Salt Lake Sector V Substation', '33/11kV', 'North 24 Parganas', 80.0, 88.4332, 22.5726),
            ('SUB_04', 'Baruipur Distribution Hub', '33/11kV', 'South 24 Parganas', 60.0, 88.4432, 22.3550),
            ('SUB_05', 'Bally Primary Substation', '33/11kV', 'Howrah', 50.0, 88.3410, 22.6500)
        ) AS t(substation_id, substation_name, voltage_ratio, district, capacity_mva, lon, lat);
    """)

    conn.close()
    print("Utility tables successfully initialized in backend/app/data/storage/geoagent.duckdb.")

if __name__ == "__main__":
    seed_utility_network()