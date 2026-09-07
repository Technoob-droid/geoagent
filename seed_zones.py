from backend.app.tools.engine import spatial_engine

zones = [
    ('kolkata_north', 'Kolkata North', 88.3750, 22.6100, 'North Kolkata reference hub (Shyambazar / Dum Dum)'),
    ('kolkata_south', 'Kolkata South', 88.3500, 22.5000, 'South Kolkata reference hub (Jadavpur / Garia / Tollygunge)'),
    ('kolkata_east', 'Kolkata East', 88.4200, 22.5700, 'East Kolkata reference hub (EM Bypass / Salt Lake / New Town)'),
    ('kolkata_west', 'Kolkata West', 88.3200, 22.5800, 'West Kolkata reference hub (Howrah / Hooghly riverside)')
]

for layer_id, name, lon, lat, desc in zones:
    clean_desc = desc.replace("'", "''")
    sql = f"""
        SELECT 
            '{name}' AS name, 
            '{clean_desc}' AS description, 
            ST_SetCRS(ST_Point({lon}, {lat}), 'EPSG:4326') AS geom
    """
    res = spatial_engine.execute_spatial_query(
        query=sql, 
        output_layer_id=layer_id, 
        layer_name=name, 
        description=desc
    )
    print(f"Created {layer_id}: {res.get('status')}")