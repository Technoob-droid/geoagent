import os
import duckdb

BOUNDARIES_BASE = "backend/data/boundaries"

con = duckdb.connect()
con.execute("INSTALL spatial; LOAD spatial;")

con.execute(f"CREATE VIEW india_states AS SELECT * FROM read_parquet('{BOUNDARIES_BASE}/states/india_states.parquet');")
con.execute(f"CREATE VIEW india_districts AS SELECT * FROM read_parquet('{BOUNDARIES_BASE}/districts/india_districts.parquet');")
con.execute(f"CREATE VIEW india_subdistricts AS SELECT * FROM read_parquet('{BOUNDARIES_BASE}/subdistricts/india_subdistricts.parquet');")
con.execute(f"CREATE VIEW india_cities AS SELECT * FROM read_parquet('{BOUNDARIES_BASE}/cities/india_cities.parquet');")
con.execute(f"CREATE VIEW india_villages AS SELECT * FROM read_parquet('{BOUNDARIES_BASE}/villages/india_villages.parquet');")

print("=== 1. Summary of Boundary Layers ===")
for tbl in ["india_states", "india_districts", "india_subdistricts", "india_cities", "india_villages"]:
    cnt = con.execute(f"SELECT count(*) FROM {tbl};").fetchone()[0]
    print(f"• {tbl:<20}: {cnt:,} rows")

print("\n=== 2. Cross-Boundary Spatial Join Test ===")
query = """
    SELECT c.city_name, s.state_name
    FROM india_cities c
    JOIN india_states s ON ST_Intersects(c.geom, s.geom)
    WHERE s.state_name = 'Maharashtra'
    LIMIT 5;
"""
print("Cities within Maharashtra boundary polygon:")
print(con.execute(query).df())

print("\n=== 3. Village Spatial Point Query Test ===")
query_villages = """
    SELECT v.village_name, d.district_name, d.state_iso
    FROM india_villages v
    JOIN india_districts d ON ST_Intersects(v.geom, d.geom)
    WHERE d.district_name = 'Pune'
    LIMIT 5;
"""
print("Villages physically inside Pune District:")
print(con.execute(query_villages).df())

con.close()