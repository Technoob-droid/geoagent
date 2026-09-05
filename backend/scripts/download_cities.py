import os
import urllib.request
import zipfile
import duckdb

RAW_DIR = "backend/data/raw"
os.makedirs(RAW_DIR, exist_ok=True)

ZIP_PATH = os.path.join(RAW_DIR, "ne_populated_places.zip")
extract_dir = os.path.join(RAW_DIR, "ne_populated_places")
shp_path = os.path.join(extract_dir, "ne_10m_populated_places.shp").replace("\\", "/")
parquet_out = "backend/data/boundaries/cities/india_cities.parquet"

con = duckdb.connect()
con.execute("INSTALL spatial; LOAD spatial;")

con.execute(f"""
    CREATE OR REPLACE TABLE india_cities AS
    SELECT
        NAME AS city_name,
        ADM1NAME AS state_name,
        SOV0NAME AS country,
        FEATURECLA AS feature_class,
        POP_MAX AS population,
        ST_SetCRS(geom, 'EPSG:4326') AS geom
    FROM ST_Read('{shp_path}')
    WHERE SOV0NAME = 'India' OR ADM0NAME = 'India';
""")

con.execute(f"COPY india_cities TO '{parquet_out}' (FORMAT PARQUET);")
print(f"✓ Re-indexed cities with EPSG:4326.")
con.close()