import os
import urllib.request
import zipfile
import unicodedata
import duckdb

RAW_DIR = "backend/data/raw"
OUT_DIR = "backend/data/boundaries/villages"
ZIP_PATH = os.path.join(RAW_DIR, "IN.zip")
TXT_PATH = os.path.join(RAW_DIR, "IN.txt")
PARQUET_OUT = os.path.join(OUT_DIR, "india_villages.parquet").replace("\\", "/")

os.makedirs(RAW_DIR, exist_ok=True)
os.makedirs(OUT_DIR, exist_ok=True)

GEONAMES_URL = "https://download.geonames.org/export/dump/IN.zip"
HEADERS = {"User-Agent": "Mozilla/5.0"}

def strip_accents(text):
    if not text:
        return ""
    return "".join(
        c for c in unicodedata.normalize("NFD", str(text))
        if unicodedata.category(c) != "Mn"
    )

def download_and_ingest_villages():
    if not os.path.exists(TXT_PATH):
        print("Downloading India Populated Places & Villages gazetteer (~15 MB compressed)...")
        req = urllib.request.Request(GEONAMES_URL, headers=HEADERS)
        with urllib.request.urlopen(req) as resp, open(ZIP_PATH, "wb") as f:
            f.write(resp.read())

        print("Extracting IN.zip...")
        with zipfile.ZipFile(ZIP_PATH, "r") as z:
            z.extract("IN.txt", RAW_DIR)
        print("✓ Extraction complete.")
    else:
        print("Found existing extracted IN.txt.")

    print("Parsing and indexing into GeoParquet with strict EPSG:4326...")
    con = duckdb.connect()
    con.execute("INSTALL spatial; LOAD spatial;")
    con.create_function("normalize_name", strip_accents, ["VARCHAR"], "VARCHAR")

    txt_norm = TXT_PATH.replace("\\", "/")

    con.execute(f"""
        CREATE OR REPLACE TABLE raw_places AS
        SELECT
            column00 AS geoname_id,
            column01 AS raw_name,
            column02 AS ascii_name,
            TRY_CAST(column04 AS DOUBLE) AS latitude,
            TRY_CAST(column05 AS DOUBLE) AS longitude,
            column06 AS feature_class,
            column07 AS feature_code,
            column10 AS state_code
        FROM read_csv(
            '{txt_norm}',
            header = false,
            delim = '\t',
            auto_detect = false,
            columns = {{
                'column00': 'VARCHAR',
                'column01': 'VARCHAR',
                'column02': 'VARCHAR',
                'column03': 'VARCHAR',
                'column04': 'VARCHAR',
                'column05': 'VARCHAR',
                'column06': 'VARCHAR',
                'column07': 'VARCHAR',
                'column08': 'VARCHAR',
                'column09': 'VARCHAR',
                'column10': 'VARCHAR',
                'column11': 'VARCHAR',
                'column12': 'VARCHAR',
                'column13': 'VARCHAR',
                'column14': 'VARCHAR',
                'column15': 'VARCHAR',
                'column16': 'VARCHAR',
                'column17': 'VARCHAR',
                'column18': 'VARCHAR'
            }}
        );
    """)

    # Explicitly stamp ST_SetCRS(..., 'EPSG:4326') on geometries
    con.execute(f"""
        CREATE OR REPLACE TABLE india_villages AS
        SELECT
            normalize_name(ascii_name) AS village_name,
            raw_name,
            state_code,
            feature_code,
            ST_SetCRS(ST_Point(longitude, latitude), 'EPSG:4326') AS geom
        FROM raw_places
        WHERE feature_class = 'P'
          AND latitude IS NOT NULL
          AND longitude IS NOT NULL
          AND longitude BETWEEN 68.0 AND 98.0
          AND latitude BETWEEN 6.0 AND 38.0;
    """)

    con.execute(f"COPY india_villages TO '{PARQUET_OUT}' (FORMAT PARQUET);")

    count = con.execute("SELECT count(*) FROM india_villages;").fetchone()[0]
    size_mb = os.path.getsize(PARQUET_OUT) / (1024 * 1024)
    print(f"✓ Ingested {count:,} Populated Places & Villages with EPSG:4326 into {PARQUET_OUT} ({size_mb:.2f} MB)")
    con.close()

if __name__ == "__main__":
    download_and_ingest_villages()