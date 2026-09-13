import math
from typing import Tuple

def tile_to_bbox_4326(z: int, x: int, y: int) -> Tuple[float, float, float, float]:
    """
    Computes (min_lon, min_lat, max_lon, max_lat) in WGS84 EPSG:4326 degrees for slippy tile (z, x, y).
    """
    n = 2.0 ** z
    min_lon = x / n * 360.0 - 180.0
    max_lon = (x + 1) / n * 360.0 - 180.0
    
    lat_rad_top = math.atan(math.sinh(math.pi * (1 - 2 * y / n)))
    lat_rad_bottom = math.atan(math.sinh(math.pi * (1 - 2 * (y + 1) / n)))
    
    max_lat = math.degrees(lat_rad_top)
    min_lat = math.degrees(lat_rad_bottom)
    
    return min_lon, min_lat, max_lon, max_lat