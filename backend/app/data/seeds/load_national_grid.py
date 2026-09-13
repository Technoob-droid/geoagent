import logging
from pathlib import Path
import duckdb
from backend.app.config import settings

logger = logging.getLogger("geoagent.seeds.national_grid")


def seed_national_grid():
    db_path = Path(settings.DUCKDB_DATABASE_PATH)
    print(f"Connecting to DuckDB database at: {db_path.resolve()}")
    conn = duckdb.connect(str(db_path), read_only=False)
    conn.execute("INSTALL spatial; LOAD spatial;")

    # 1. Master Substations (GSS, PSS, DSS across India)
    conn.execute("""
        CREATE OR REPLACE TABLE utility_substations_master AS
        SELECT
            substation_id,
            substation_name,
            tier,
            voltage_kv,
            capacity_mva,
            state,
            district,
            operational_status,
            ST_SetCRS(ST_Point(lon, lat), 'EPSG:4326') AS geom
        FROM (VALUES
            -- West Bengal Cluster
            ('GSS_WB_01', 'Kolaghat 400kV Switchyard', 'GSS', 400.0, 1200.0, 'West Bengal', 'Purba Medinipur', 'OPERATIONAL', 87.8722, 22.4283),
            ('GSS_WB_02', 'Jeerat 400kV Substation', 'GSS', 400.0, 1000.0, 'West Bengal', 'Hooghly', 'OPERATIONAL', 88.4500, 23.0100),
            ('GSS_WB_03', 'Howrah 220kV GSS', 'GSS', 220.0, 600.0, 'West Bengal', 'Howrah', 'OPERATIONAL', 88.2731, 22.5958),
            ('GSS_WB_04', 'New Town 220kV GIS Substation', 'GSS', 220.0, 500.0, 'West Bengal', 'North 24 Parganas', 'OPERATIONAL', 88.4650, 22.5850),
            ('PSS_WB_01', 'Domjur 33/11kV Primary Substation', 'PSS', 33.0, 50.0, 'West Bengal', 'Howrah', 'OPERATIONAL', 88.2180, 22.6390),
            ('PSS_WB_02', 'Uluberia 33/11kV Primary Substation', 'PSS', 33.0, 40.0, 'West Bengal', 'Howrah', 'OPERATIONAL', 88.1090, 22.4720),
            ('PSS_WB_03', 'Salt Lake Sector V 33/11kV PSS', 'PSS', 33.0, 60.0, 'West Bengal', 'North 24 Parganas', 'OPERATIONAL', 88.4310, 22.5780),
            ('DSS_WB_01', 'Domjur Market 11kV Distribution Substation', 'DSS', 11.0, 0.5, 'West Bengal', 'Howrah', 'OPERATIONAL', 88.2210, 22.6410),
            ('DSS_WB_02', 'Uluberia Industrial Area 11kV DSS', 'DSS', 11.0, 1.0, 'West Bengal', 'Howrah', 'OPERATIONAL', 88.1120, 22.4740),
            ('DSS_WB_03', 'Salt Lake Tech Park 11kV DSS', 'DSS', 11.0, 1.5, 'West Bengal', 'North 24 Parganas', 'OPERATIONAL', 88.4340, 22.5800),

            -- Maharashtra Cluster
            ('GSS_MH_01', 'Padghe 765/400kV Substation', 'GSS', 765.0, 3000.0, 'Maharashtra', 'Thane', 'OPERATIONAL', 73.1900, 19.3400),
            ('GSS_MH_02', 'Kalwa 400/220kV GSS', 'GSS', 400.0, 1500.0, 'Maharashtra', 'Thane', 'OPERATIONAL', 73.0100, 19.1900),
            ('PSS_MH_01', 'Navi Mumbai Vashi 33kV PSS', 'PSS', 33.0, 80.0, 'Maharashtra', 'Thane', 'OPERATIONAL', 72.9980, 19.0760),
            ('DSS_MH_01', 'Vashi Sector 17 Distribution Center', 'DSS', 11.0, 1.0, 'Maharashtra', 'Thane', 'OPERATIONAL', 73.0020, 19.0790),

            -- Delhi NCR Cluster
            ('GSS_DL_01', 'Mandola 400kV GSS', 'GSS', 400.0, 1600.0, 'Delhi', 'North East Delhi', 'OPERATIONAL', 77.2600, 28.7800),
            ('GSS_DL_02', 'Bawana 400kV Substation', 'GSS', 400.0, 1200.0, 'Delhi', 'North West Delhi', 'OPERATIONAL', 77.0400, 28.7900),
            ('PSS_DL_01', 'Rohini Sector 10 33kV PSS', 'PSS', 33.0, 50.0, 'Delhi', 'North West Delhi', 'OPERATIONAL', 77.1120, 28.7110),
            ('DSS_DL_01', 'Rohini D-Mall 11kV DSS', 'DSS', 11.0, 0.8, 'Delhi', 'North West Delhi', 'OPERATIONAL', 77.1150, 28.7130),

            -- Karnataka Cluster
            ('GSS_KA_01', 'Nelamangala 400/220kV GSS', 'GSS', 400.0, 1500.0, 'Karnataka', 'Bangalore Rural', 'OPERATIONAL', 77.3800, 13.1000),
            ('GSS_KA_02', 'Hoody 220kV Substation', 'GSS', 220.0, 600.0, 'Karnataka', 'Bangalore Urban', 'OPERATIONAL', 77.7100, 12.9900),
            ('PSS_KA_01', 'Whitefield 66/11kV PSS', 'PSS', 66.0, 60.0, 'Karnataka', 'Bangalore Urban', 'OPERATIONAL', 77.7490, 12.9690),
            ('DSS_KA_01', 'ITPL Main 11kV DSS', 'DSS', 11.0, 2.0, 'Karnataka', 'Bangalore Urban', 'OPERATIONAL', 77.7510, 12.9710)
        ) AS t(substation_id, substation_name, tier, voltage_kv, capacity_mva, state, district, operational_status, lon, lat);
    """)

    # 2. Master Feeders & Corridors (Trunks, 33kV, 11kV)
    conn.execute("""
        CREATE OR REPLACE TABLE utility_feeders_master AS
        SELECT
            feeder_id,
            feeder_name,
            voltage_kv,
            feeder_type,
            source_substation_id,
            target_substation_id,
            circuit_type,
            operational_status,
            ST_SetCRS(ST_GeomFromText(wkt), 'EPSG:4326') AS geom
        FROM (VALUES
            -- 400kV Trunks
            ('FDR_400_01', 'Kolaghat - Howrah 400kV Line', 400.0, 'INTER_STATE_TRUNK', 'GSS_WB_01', 'GSS_WB_03', 'DOUBLE_CIRCUIT', 'IN_SERVICE', 'LINESTRING(87.8722 22.4283, 88.0800 22.5100, 88.2731 22.5958)'),
            ('FDR_400_02', 'Padghe - Kalwa 400kV Line', 400.0, 'INTER_STATE_TRUNK', 'GSS_MH_01', 'GSS_MH_02', 'DOUBLE_CIRCUIT', 'IN_SERVICE', 'LINESTRING(73.1900 19.3400, 73.1000 19.2600, 73.0100 19.1900)'),
            ('FDR_400_03', 'Mandola - Bawana 400kV Ring Line', 400.0, 'INTER_STATE_TRUNK', 'GSS_DL_01', 'GSS_DL_02', 'DOUBLE_CIRCUIT', 'IN_SERVICE', 'LINESTRING(77.2600 28.7800, 77.1500 28.8100, 77.0400 28.7900)'),
            ('FDR_400_04', 'Nelamangala - Hoody 400/220kV Corridor', 400.0, 'INTER_STATE_TRUNK', 'GSS_KA_01', 'GSS_KA_02', 'DOUBLE_CIRCUIT', 'IN_SERVICE', 'LINESTRING(77.3800 13.1000, 77.5500 13.0400, 77.7100 12.9900)'),

            -- 33kV Sub-Transmission Corridors
            ('FDR_33_01', 'Howrah - Domjur 33kV Sub-Transmission', 33.0, 'SUB_TRANSMISSION', 'GSS_WB_03', 'PSS_WB_01', 'DOUBLE_CIRCUIT', 'IN_SERVICE', 'LINESTRING(88.2731 22.5958, 88.2400 22.6180, 88.2180 22.6390)'),
            ('FDR_33_02', 'Howrah - Uluberia 33kV Feeder', 33.0, 'SUB_TRANSMISSION', 'GSS_WB_03', 'PSS_WB_02', 'DOUBLE_CIRCUIT', 'IN_SERVICE', 'LINESTRING(88.2731 22.5958, 88.1900 22.5300, 88.1090 22.4720)'),
            ('FDR_33_03', 'Kalwa - Vashi 33kV Feeder', 33.0, 'SUB_TRANSMISSION', 'GSS_MH_02', 'PSS_MH_01', 'DOUBLE_CIRCUIT', 'IN_SERVICE', 'LINESTRING(73.0100 19.1900, 73.0030 19.1300, 72.9980 19.0760)'),
            ('FDR_33_04', 'Bawana - Rohini 33kV Feeder', 33.0, 'SUB_TRANSMISSION', 'GSS_DL_02', 'PSS_DL_01', 'DOUBLE_CIRCUIT', 'IN_SERVICE', 'LINESTRING(77.0400 28.7900, 77.0800 28.7500, 77.1120 28.7110)'),
            ('FDR_66_01', 'Hoody - Whitefield 66kV Feeder', 66.0, 'SUB_TRANSMISSION', 'GSS_KA_02', 'PSS_KA_01', 'DOUBLE_CIRCUIT', 'IN_SERVICE', 'LINESTRING(77.7100 12.9900, 77.7300 12.9800, 77.7490 12.9690)'),

            -- 11kV Distribution Feeders
            ('FDR_11_01', 'Domjur Town 11kV Primary Feeder', 11.0, 'PRIMARY_DISTRIBUTION', 'PSS_WB_01', 'DSS_WB_01', 'SINGLE_CIRCUIT', 'IN_SERVICE', 'LINESTRING(88.2180 22.6390, 88.2195 22.6400, 88.2210 22.6410)'),
            ('FDR_11_02', 'Uluberia Industrial 11kV Feeder', 11.0, 'PRIMARY_DISTRIBUTION', 'PSS_WB_02', 'DSS_WB_02', 'SINGLE_CIRCUIT', 'IN_SERVICE', 'LINESTRING(88.1090 22.4720, 88.1105 22.4730, 88.1120 22.4740)'),
            ('FDR_11_03', 'Vashi Commercial 11kV Feeder', 11.0, 'PRIMARY_DISTRIBUTION', 'PSS_MH_01', 'DSS_MH_01', 'SINGLE_CIRCUIT', 'IN_SERVICE', 'LINESTRING(72.9980 19.0760, 73.0000 19.0775, 73.0020 19.0790)'),
            ('FDR_11_04', 'Rohini Sector 10 Local Feeder', 11.0, 'PRIMARY_DISTRIBUTION', 'PSS_DL_01', 'DSS_DL_01', 'SINGLE_CIRCUIT', 'IN_SERVICE', 'LINESTRING(77.1120 28.7110, 77.1135 28.7120, 77.1150 28.7130)'),
            ('FDR_11_05', 'ITPL Main Tech Park 11kV Feeder', 11.0, 'PRIMARY_DISTRIBUTION', 'PSS_KA_01', 'DSS_KA_01', 'SINGLE_CIRCUIT', 'IN_SERVICE', 'LINESTRING(77.7490 12.9690, 77.7500 12.9700, 77.7510 12.9710)')
        ) AS t(feeder_id, feeder_name, voltage_kv, feeder_type, source_substation_id, target_substation_id, circuit_type, operational_status, wkt);
    """)

    # 3. Master Switchgear & Circuit Breakers (CBs)
    conn.execute("""
        CREATE OR REPLACE TABLE utility_switchgear_master AS
        SELECT
            switchgear_id,
            switchgear_type,
            parent_substation_id,
            bay_name,
            voltage_kv,
            status,
            ST_SetCRS(ST_Point(lon, lat), 'EPSG:4326') AS geom
        FROM (VALUES
            ('CB_GSS_WB01_01', 'CIRCUIT_BREAKER', 'GSS_WB_01', '400kV Line Bay 1 (Howrah Trunk)', 400.0, 'CLOSED', 87.8725, 22.4285),
            ('CB_GSS_WB03_01', 'CIRCUIT_BREAKER', 'GSS_WB_03', '400kV Receiving Bay 1', 400.0, 'CLOSED', 88.2728, 22.5955),
            ('CB_GSS_WB03_02', 'CIRCUIT_BREAKER', 'GSS_WB_03', '220/33kV Trafo Bay 1', 220.0, 'CLOSED', 88.2733, 22.5960),
            ('CB_GSS_MH01_01', 'CIRCUIT_BREAKER', 'GSS_MH_01', '765kV Inter-tie Bay', 765.0, 'CLOSED', 73.1902, 19.3402),
            ('CB_PSS_WB01_01', 'CIRCUIT_BREAKER', 'PSS_WB_01', '33kV Incomer Bay', 33.0, 'CLOSED', 88.2178, 22.6388),
            ('CB_PSS_WB01_02', 'CIRCUIT_BREAKER', 'PSS_WB_01', '11kV Outgoing Feeder 1 Bay', 11.0, 'CLOSED', 88.2182, 22.6392),
            ('CB_PSS_WB02_01', 'CIRCUIT_BREAKER', 'PSS_WB_02', '11kV Industrial Feeder Bay', 11.0, 'OPEN', 88.1092, 22.4722),
            ('CB_PSS_DL01_01', 'CIRCUIT_BREAKER', 'PSS_DL_01', '11kV Urban Feeder Bay', 11.0, 'CLOSED', 77.1122, 28.7112),
            ('RMU_DSS_WB01_01', 'RMU', 'DSS_WB_01', '11kV Ring Main Unit - Market', 11.0, 'CLOSED', 88.2211, 22.6411),
            ('RMU_DSS_KA01_01', 'RMU', 'DSS_KA_01', '11kV ITPL Auto-Sectionalizer', 11.0, 'CLOSED', 77.7511, 12.9711)
        ) AS t(switchgear_id, switchgear_type, parent_substation_id, bay_name, voltage_kv, status, lon, lat);
    """)

    conn.close()
    print("National grid tables (utility_substations_master, utility_feeders_master, utility_switchgear_master) created successfully.")


if __name__ == "__main__":
    seed_national_grid()