import os
import shutil
import tempfile
import zipfile
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from starlette.background import BackgroundTasks

from backend.app.tools.engine import spatial_engine
from backend.app.tools.catalog import catalog_manager

router = APIRouter(prefix="/api/export", tags=["export"])

# Standard ESRI WKT string for WGS84 (EPSG:4326)
WGS84_PRJ = (
    'GEOGCS["GCS_WGS_1984",'
    'DATUM["D_WGS_1984",'
    'SPHEROID["WGS_1984",6378137.0,298.257223563]],'
    'PRIMEM["Greenwich",0.0],'
    'UNIT["Degree",0.0174532925199433]]'
)


def _cleanup_dir(path: str):
    """Background task to remove temporary exported directory."""
    if os.path.exists(path):
        shutil.rmtree(path, ignore_errors=True)


@router.get("/shapefile/{layer_id}")
async def export_layer_as_shapefile(layer_id: str, background_tasks: BackgroundTasks):
    """
    Exports an active analytical or administrative layer from DuckDB
    as a zipped ESRI Shapefile bundle (.shp, .shx, .dbf, .prj).
    """
    resolved_id = catalog_manager.resolve_layer_id(layer_id) or layer_id.strip().lower()

    # 1. Verify layer exists in DuckDB
    try:
        check_table = spatial_engine.con.execute(f"""
            SELECT count(*) FROM information_schema.tables WHERE table_name = '{resolved_id}';
        """).fetchone()
        if not check_table or check_table[0] == 0:
            raise HTTPException(status_code=404, detail=f"Layer '{resolved_id}' does not exist.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database verification error: {str(e)}")

    # 2. Setup temporary workspace directory
    temp_dir = tempfile.mkdtemp(prefix=f"shp_{resolved_id}_")
    shp_filename = f"{resolved_id}.shp"
    shp_filepath = os.path.join(temp_dir, shp_filename).replace("\\", "/")
    prj_filepath = os.path.join(temp_dir, f"{resolved_id}.prj")
    zip_filepath = os.path.join(temp_dir, f"{resolved_id}_shapefile.zip")

    # 3. Export to Shapefile using DuckDB Spatial GDAL driver
    try:
        export_sql = f"""
            COPY (
                SELECT * FROM {resolved_id} WHERE geom IS NOT NULL
            ) TO '{shp_filepath}'
            WITH (FORMAT GDAL, DRIVER 'ESRI Shapefile');
        """
        spatial_engine.con.execute(export_sql)

        # 4. Guarantee .prj file exists for GIS compatibility
        if not os.path.exists(prj_filepath):
            with open(prj_filepath, "w", encoding="utf-8") as f:
                f.write(WGS84_PRJ)

        # 5. Bundle generated files (.shp, .shx, .dbf, .prj, .cpg) into a .zip
        with zipfile.ZipFile(zip_filepath, "w", zipfile.ZIP_DEFLATED) as zipf:
            for root, _, files in os.walk(temp_dir):
                for file in files:
                    if file.endswith((".shp", ".shx", ".dbf", ".prj", ".cpg")):
                        file_full_path = os.path.join(root, file)
                        zipf.write(file_full_path, arcname=file)

        background_tasks.add_task(_cleanup_dir, temp_dir)

        return FileResponse(
            path=zip_filepath,
            filename=f"{resolved_id}_shapefile.zip",
            media_type="application/zip",
        )

    except Exception as e:
        _cleanup_dir(temp_dir)
        raise HTTPException(status_code=500, detail=f"Failed to generate Shapefile bundle: {str(e)}")