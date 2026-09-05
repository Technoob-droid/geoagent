import os
import urllib.request
import json

RAW_DIR = "backend/data/raw"
os.makedirs(RAW_DIR, exist_ok=True)

HEADERS = {"User-Agent": "Mozilla/5.0"}

def fetch_geoboundary(adm_level: str, filename: str, label: str):
    print(f"Resolving official download URL for {label} ({adm_level})...")
    api_url = f"https://www.geoboundaries.org/api/current/gbOpen/IND/{adm_level}/"
    
    req = urllib.request.Request(api_url, headers=HEADERS)
    with urllib.request.urlopen(req) as response:
        metadata = json.loads(response.read().decode("utf-8"))
    
    download_url = metadata["gjDownloadURL"]
    print(f"Streaming from: {download_url}")
    
    target_path = os.path.join(RAW_DIR, filename)
    dl_req = urllib.request.Request(download_url, headers=HEADERS)
    with urllib.request.urlopen(dl_req) as resp, open(target_path, "wb") as f:
        f.write(resp.read())
    
    size_mb = os.path.getsize(target_path) / (1024 * 1024)
    print(f"✓ {label} saved successfully: {size_mb:.2f} MB")

if __name__ == "__main__":
    fetch_geoboundary("ADM1", "india_states.geojson", "India States & UTs")
    fetch_geoboundary("ADM2", "india_districts.geojson", "India Districts")