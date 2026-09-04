from fastapi import APIRouter, HTTPException
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