import os
import shutil
import tempfile
import zipfile
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, Response
from starlette.background import BackgroundTasks

from backend.app.tools.engine import spatial_engine
from backend.app.tools.catalog import catalog_manager

router = APIRouter(tags=["export"])

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


def _cleanup_file(path: str):
    """Background task to remove temporary exported file."""
    if os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            pass


def _verify_table_exists(resolved_id: str):
    """Verify table existence in DuckDB metadata."""
    check_table = spatial_engine.con.execute(f"""
        SELECT count(*) FROM information_schema.tables WHERE table_name = '{resolved_id}';
    """).fetchone()
    if not check_table or check_table[0] == 0:
        raise HTTPException(status_code=404, detail=f"Layer '{resolved_id}' does not exist.")


@router.get("/api/layers/{layer_id}/export/{export_format}")
@router.get("/api/export/{export_format}/{layer_id}")
async def export_layer(layer_id: str, export_format: str, background_tasks: BackgroundTasks):
    """
    Exports an active analytical or administrative layer from DuckDB into:
    - CSV (with geometry materialized as WKT)
    - GeoJSON
    - ESRI Shapefile (.zip bundle)
    - GeoPackage (.gpkg)
    """
    fmt = export_format.lower().strip()
    resolved_id = catalog_manager.resolve_layer_id(layer_id) or layer_id.strip().lower()

    try:
        _verify_table_exists(resolved_id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database verification error: {str(e)}")

    # -------------------------------------------------------------
    # 1. CSV Export (Geometry converted to WKT)
    # -------------------------------------------------------------
    if fmt == "csv":
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=f"_{resolved_id}.csv")
        temp_file.close()
        csv_path = temp_file.name.replace("\\", "/")

        try:
            cols = [
                r[0]
                for r in spatial_engine.con.execute(f"DESCRIBE {resolved_id};").fetchall()
            ]
            if "geom" in cols:
                select_cols = ", ".join(
                    [f"ST_AsText(geom) AS wkt_geometry" if c == "geom" else f'"{c}"' for c in cols]
                )
                sql = f"COPY (SELECT {select_cols} FROM {resolved_id}) TO '{csv_path}' (HEADER, DELIMITER ',');"
            else:
                sql = f"COPY (SELECT * FROM {resolved_id}) TO '{csv_path}' (HEADER, DELIMITER ',');"

            spatial_engine.con.execute(sql)
            background_tasks.add_task(_cleanup_file, temp_file.name)

            return FileResponse(
                path=temp_file.name,
                filename=f"{resolved_id}.csv",
                media_type="text/csv",
            )
        except Exception as e:
            _cleanup_file(temp_file.name)
            raise HTTPException(status_code=500, detail=f"CSV export failed: {str(e)}")

    # -------------------------------------------------------------
    # 2. GeoJSON Export
    # -------------------------------------------------------------
    elif fmt in ("geojson", "json"):
        try:
            geojson_sql = f"""
                SELECT json_build_object(
                    'type', 'FeatureCollection',
                    'features', coalesce(
                        json_group_array(
                            json_build_object(
                                'type', 'Feature',
                                'geometry', json(ST_AsGeoJSON(geom)),
                                'properties', to_json(
                                    (SELECT as_struct FROM (SELECT * EXCLUDE (geom)) as_struct)
                                )
                            )
                        ),
                        json_array()
                    )
                )
                FROM {resolved_id}
                WHERE geom IS NOT NULL;
            """
            result = spatial_engine.con.execute(geojson_sql).fetchone()
            payload = result[0] if result and result[0] else '{"type":"FeatureCollection","features":[]}'
            return Response(
                content=payload,
                media_type="application/geo+json",
                headers={"Content-Disposition": f'attachment; filename="{resolved_id}.geojson"'},
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"GeoJSON export failed: {str(e)}")

    # -------------------------------------------------------------
    # 3. Shapefile Export (.zip bundle)
    # -------------------------------------------------------------
    elif fmt in ("shapefile", "shp"):
        temp_dir = tempfile.mkdtemp(prefix=f"shp_{resolved_id}_")
        shp_filepath = os.path.join(temp_dir, f"{resolved_id}.shp").replace("\\", "/")
        prj_filepath = os.path.join(temp_dir, f"{resolved_id}.prj")
        zip_filepath = os.path.join(temp_dir, f"{resolved_id}_shapefile.zip")

        try:
            export_sql = f"""
                COPY (
                    SELECT * FROM {resolved_id} WHERE geom IS NOT NULL
                ) TO '{shp_filepath}'
                WITH (FORMAT GDAL, DRIVER 'ESRI Shapefile');
            """
            spatial_engine.con.execute(export_sql)

            if not os.path.exists(prj_filepath):
                with open(prj_filepath, "w", encoding="utf-8") as f:
                    f.write(WGS84_PRJ)

            with zipfile.ZipFile(zip_filepath, "w", zipfile.ZIP_DEFLATED) as zipf:
                for root, _, files in os.walk(temp_dir):
                    for file in files:
                        if file.endswith((".shp", ".shx", ".dbf", ".prj", ".cpg")):
                            zipf.write(os.path.join(root, file), arcname=file)

            background_tasks.add_task(_cleanup_dir, temp_dir)

            return FileResponse(
                path=zip_filepath,
                filename=f"{resolved_id}_shapefile.zip",
                media_type="application/zip",
            )
        except Exception as e:
            _cleanup_dir(temp_dir)
            raise HTTPException(status_code=500, detail=f"Shapefile generation failed: {str(e)}")

    # -------------------------------------------------------------
    # 4. GeoPackage Export (.gpkg)
    # -------------------------------------------------------------
    elif fmt in ("gpkg", "geopackage"):
        temp_dir = tempfile.mkdtemp(prefix=f"gpkg_{resolved_id}_")
        gpkg_filepath = os.path.join(temp_dir, f"{resolved_id}.gpkg").replace("\\", "/")

        try:
            export_sql = f"""
                COPY (
                    SELECT * FROM {resolved_id} WHERE geom IS NOT NULL
                ) TO '{gpkg_filepath}'
                WITH (FORMAT GDAL, DRIVER 'GPKG');
            """
            spatial_engine.con.execute(export_sql)
            background_tasks.add_task(_cleanup_dir, temp_dir)

            return FileResponse(
                path=gpkg_filepath,
                filename=f"{resolved_id}.gpkg",
                media_type="application/geopackage+sqlite3",
            )
        except Exception as e:
            _cleanup_dir(temp_dir)
            raise HTTPException(status_code=500, detail=f"GeoPackage export failed: {str(e)}")

    else:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported export format '{export_format}'. Supported formats: csv, geojson, shapefile, gpkg",
        )