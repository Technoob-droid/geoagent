import io
import os
import zipfile
import tempfile
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response, StreamingResponse
from backend.app.tools.engine import spatial_engine
from backend.app.tools.catalog import catalog_manager

router = APIRouter(prefix="/api/layers", tags=["layers"])


@router.get("")
async def get_all_layers():
    """Returns metadata for all available layers in the spatial catalog."""
    return catalog_manager.list_layers()


@router.get("/{layer_id}/schema")
async def get_layer_schema(layer_id: str):
    """Returns column names, types, and sample data for a layer."""
    details = catalog_manager.get_layer_details(layer_id)
    if not details:
        raise HTTPException(status_code=404, detail=f"Layer '{layer_id}' not found.")
    return details


@router.get("/{layer_id}/geojson")
async def get_layer_geojson(layer_id: str):
    """Exports and streams the layer as a GeoJSON FeatureCollection."""
    geojson = spatial_engine.get_layer_as_geojson(layer_id)
    if not geojson:
        raise HTTPException(status_code=404, detail=f"Layer '{layer_id}' not found or empty.")
    return geojson


@router.get("/{layer_id}/export/csv")
async def export_layer_csv(layer_id: str):
    """
    Exports a spatial layer as CSV with attributes and WKT (Well-Known Text) geometry.
    """
    details = catalog_manager.get_layer_details(layer_id)
    if not details:
        raise HTTPException(status_code=404, detail=f"Layer '{layer_id}' not found.")

    conn = getattr(spatial_engine, "con", None) or getattr(spatial_engine, "conn", None)
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection unavailable.")

    clean_name = "".join(c for c in details.get("name", layer_id) if c.isalnum() or c in ("_", "-")).strip() or layer_id

    try:
        df = conn.execute(f"""
            SELECT 
                * EXCLUDE (geom),
                ST_AsText(geom) AS wkt_geom
            FROM {layer_id}
            WHERE geom IS NOT NULL
        """).df()

        csv_buffer = io.StringIO()
        df.to_csv(csv_buffer, index=False)
        csv_data = csv_buffer.getvalue()

        return Response(
            content=csv_data,
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{clean_name}.csv"'},
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"CSV export failed: {str(e)}")


@router.get("/{layer_id}/export/shapefile")
async def export_layer_shapefile(layer_id: str):
    """
    Exports a spatial layer as a zipped ESRI Shapefile archive (.shp, .shx, .dbf, .prj).
    """
    details = catalog_manager.get_layer_details(layer_id)
    if not details:
        raise HTTPException(status_code=404, detail=f"Layer '{layer_id}' not found.")

    conn = getattr(spatial_engine, "con", None) or getattr(spatial_engine, "conn", None)
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection unavailable.")

    clean_name = "".join(c for c in details.get("name", layer_id) if c.isalnum() or c in ("_", "-")).strip() or layer_id

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            shp_path = os.path.join(tmpdir, f"{clean_name}.shp").replace("\\", "/")

            conn.execute(f"""
                COPY (
                    SELECT * FROM {layer_id} WHERE geom IS NOT NULL
                ) TO '{shp_path}'
                WITH (FORMAT GDAL, DRIVER 'ESRI Shapefile', SRS 'EPSG:4326');
            """)

            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
                for root, _, files in os.walk(tmpdir):
                    for file in files:
                        file_path = os.path.join(root, file)
                        zip_file.write(file_path, arcname=file)

            zip_buffer.seek(0)
            return StreamingResponse(
                zip_buffer,
                media_type="application/zip",
                headers={"Content-Disposition": f'attachment; filename="{clean_name}_shp.zip"'},
            )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Shapefile export failed: {str(e)}")