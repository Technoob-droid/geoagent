from backend.app.tools.engine import spatial_engine

def load_seed_data():
    print("Loading baseline geospatial seed datasets...")
    
    # 1. Kolkata Hospitals (Point data)
    spatial_engine.execute_spatial_query("""
        SELECT * FROM (VALUES
            (1, 'Apollo Gleneagles Hospital', 'Hospital', ST_Point(88.4013, 22.5697)),
            (2, 'AMRI Hospital Salt Lake', 'Hospital', ST_Point(88.4116, 22.5936)),
            (3, 'Fortis Hospital Anandapur', 'Hospital', ST_Point(88.4031, 22.5186)),
            (4, 'SSKM Hospital', 'Hospital', ST_Point(88.3418, 22.5398)),
            (5, 'Calcutta Medical College', 'Hospital', ST_Point(88.3619, 22.5735))
        ) AS t(id, name, amenity, geom);
    """, "kolkata_hospitals", "Kolkata Major Hospitals", "Key healthcare facilities in Kolkata")

    # 2. Simulated Flood Vulnerability Zones (Polygon data)
    spatial_engine.execute_spatial_query("""
        SELECT * FROM (VALUES
            (101, 'Salt Lake Sector V Inundation Zone', 'High', ST_GeomFromText('POLYGON((88.420 22.570, 88.440 22.570, 88.440 22.590, 88.420 22.590, 88.420 22.570))')),
            (102, 'EM Bypass Low-Lying Area', 'Moderate', ST_GeomFromText('POLYGON((88.390 22.510, 88.415 22.510, 88.415 22.540, 88.390 22.540, 88.390 22.510))'))
        ) AS t(id, zone_name, risk_level, geom);
    """, "kolkata_flood_zones", "Kolkata Flood Risk Zones", "Vulnerable flood zones along eastern Kolkata")

    print("Seed data loaded successfully!")

if __name__ == "__main__":
    load_seed_data()