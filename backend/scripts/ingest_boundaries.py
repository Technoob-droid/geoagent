import os
import duckdb
import unicodedata

RAW_DIR = "backend/data/raw"
BOUNDARIES_DIR = "backend/data/boundaries"
DB_PATH = "backend/data/geoagent.duckdb"

os.makedirs(f"{BOUNDARIES_DIR}/states", exist_ok=True)
os.makedirs(f"{BOUNDARIES_DIR}/districts", exist_ok=True)

def strip_accents(text):
    if not text:
        return ""
    return "".join(
        c for c in unicodedata.normalize("NFD", str(text))
        if unicodedata.category(c) != "Mn"
    )

con = duckdb.connect(DB_PATH)
con.execute("INSTALL spatial; LOAD spatial;")

# Register string normalization UDF in DuckDB
con.create_function("normalize_name", strip_accents, ["VARCHAR"], "VARCHAR")

def run_ingest():
    print("Converting & Normalizing India States (ADM1)...")
    states_geojson = os.path.join(RAW_DIR, "india_states.geojson").replace("\\", "/")
    states_parquet = f"{BOUNDARIES_DIR}/states/india_states.parquet".replace("\\", "/")

    con.execute(f"""
        CREATE OR REPLACE TABLE india_states AS
        SELECT
            normalize_name(shapeName) AS state_name,
            shapeName AS raw_state_name,
            shapeISO AS state_iso,
            shapeID AS shape_id,
            geom
        FROM ST_Read('{states_geojson}');
    """)

    con.execute(f"""
        COPY india_states TO '{states_parquet}' (FORMAT PARQUET);
    """)
    state_count = con.execute("SELECT count(*) FROM india_states;").fetchone()[0]
    print(f"✓ Ingested {state_count} States/UTs with normalized ASCII names.")

    print("Converting & Normalizing India Districts (ADM2)...")
    dist_geojson = os.path.join(RAW_DIR, "india_districts.geojson").replace("\\", "/")
    dist_parquet = f"{BOUNDARIES_DIR}/districts/india_districts.parquet".replace("\\", "/")

    con.execute(f"""
        CREATE OR REPLACE TABLE india_districts AS
        SELECT
            normalize_name(shapeName) AS district_name,
            shapeName AS raw_district_name,
            shapeISO AS state_iso,
            shapeID AS shape_id,
            geom
        FROM ST_Read('{dist_geojson}');
    """)

    con.execute(f"""
        COPY india_districts TO '{dist_parquet}' (FORMAT PARQUET);
    """)
    dist_count = con.execute("SELECT count(*) FROM india_districts;").fetchone()[0]
    print(f"✓ Ingested {dist_count} Districts with normalized ASCII names.")

    con.close()

if __name__ == "__main__":
    run_ingest()