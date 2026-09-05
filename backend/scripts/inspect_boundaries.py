import duckdb

con = duckdb.connect()
con.execute("INSTALL spatial; LOAD spatial;")

print("=== Schema of States Parquet ===")
print(con.execute("DESCRIBE SELECT * FROM read_parquet('backend/data/boundaries/states/india_states.parquet');").df())

print("\n=== Sample States ===")
print(con.execute("SELECT state_name, state_iso FROM read_parquet('backend/data/boundaries/states/india_states.parquet') LIMIT 10;").df())

print("\n=== Search for Maharashtra in States ===")
print(con.execute("SELECT state_name, state_iso FROM read_parquet('backend/data/boundaries/states/india_states.parquet') WHERE lower(state_name) LIKE '%mah%';").df())

print("\n=== Search for Maharashtra in Districts ===")
print(con.execute("SELECT district_name, state_iso FROM read_parquet('backend/data/boundaries/districts/india_districts.parquet') WHERE lower(district_name) LIKE '%mah%' OR lower(state_iso) LIKE '%mah%';").df())