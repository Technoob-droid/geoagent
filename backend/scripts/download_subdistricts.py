import os
import json
import urllib.request
import unicodedata
import duckdb

RAW_DIR = "backend/data/raw"
OUT_DIR = "backend/data/boundaries/subdistricts"
TARGET_GEOJSON = os.path.join(RAW_DIR, "india_subdistricts.geojson")
TARGET_PARQUET = os.path.join(OUT_DIR, "india_subdistricts.parquet").replace("\\", "/")

os.makedirs(RAW_DIR, exist_ok=True)
os.makedirs(OUT_DIR, exist_ok=True)

HEADERS = {"User-Agent": "Mozilla/5.0"}

def strip_accents(text):
    if not text:
        return ""
    return "".join(
        c for c in unicodedata.normalize("NFD", str(text))
        if unicodedata.category(c) != "Mn"
    )

def download_and_ingest_subdistricts():
    api_url = "https://www.geoboundaries.org/api/current/gbOpen/IND/ADM3/"
    print("Resolving download URL for India Sub-districts (ADM3)...")
    
    req = urllib.request.Request(api_url, headers=HEADERS)
    with urllib.request.urlopen(req) as resp:
        metadata = json.loads(resp.read().decode("utf-8"))
    
    dl_url = metadata["gjDownloadURL"]
    print(f"Streaming ADM3 dataset from: {dl_url}")

    dl_req = urllib.request.Request(dl_url, headers=HEADERS)
    with urllib.request.urlopen(dl_req) as resp, open(TARGET_GEOJSON, "wb") as f:
        f.write(resp.read())

    size_mb = os.path.getsize(TARGET_GEOJSON) / (1024 * 1024)
    print(f"✓ Downloaded raw ADM3 GeoJSON ({size_mb:.2f} MB)")

    print("Normalizing names and converting to GeoParquet...")
    con = duckdb.connect()
    con.execute("INSTALL spatial; LOAD spatial;")
    con.create_function("normalize_name", strip_accents, ["VARCHAR"], "VARCHAR")

    norm_geojson = TARGET_GEOJSON.replace("\\", "/")

    con.execute(f"""
        CREATE OR REPLACE TABLE india_subdistricts AS
        SELECT
            normalize_name(shapeName) AS subdistrict_name,
            shapeName AS raw_subdistrict_name,
            shapeISO AS parent_iso,
            shapeID AS shape_id,
            geom
        FROM ST_Read('{norm_geojson}');
    """)

    con.execute(f"COPY india_subdistricts TO '{TARGET_PARQUET}' (FORMAT PARQUET);")

    count = con.execute("SELECT count(*) FROM india_subdistricts;").fetchone()[0]
    out_size_mb = os.path.getsize(TARGET_PARQUET) / (1024 * 1024)
    print(f"✓ Ingested {count} Sub-districts / Tehsils into {TARGET_PARQUET} ({out_size_mb:.2f} MB)")
    con.close()

if __name__ == "__main__":
    download_and_ingest_subdistricts()