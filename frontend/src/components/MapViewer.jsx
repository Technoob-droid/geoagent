import React, { useEffect, useRef } from 'react';
import maplibregl from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';

export default function MapViewer({
  layers = [],
  hiddenLayers = new Set(),
  opacities = {},
  zoomLayerId = null,
  onViewportChange
}) {
  const mapContainer = useRef(null);
  const mapRef = useRef(null);
  const loadedLayersRef = useRef(new Set());
  const popupRef = useRef(null);
  const layerDataCache = useRef(new Map());

  // 1. Initialize MapLibre Canvas
  useEffect(() => {
    if (mapRef.current) return;

    const map = new maplibregl.Map({
      container: mapContainer.current,
      style: 'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json',
      center: [88.3639, 22.5726], // Kolkata
      zoom: 11
    });

    map.addControl(new maplibregl.NavigationControl(), 'top-right');

    const updateViewport = () => {
      if (!onViewportChange) return;
      const bounds = map.getBounds();
      onViewportChange({
        min_lon: bounds.getWest(),
        min_lat: bounds.getSouth(),
        max_lon: bounds.getEast(),
        max_lat: bounds.getNorth()
      });
    };

    map.on('moveend', updateViewport);
    map.on('load', updateViewport);

    mapRef.current = map;

    return () => {
      if (popupRef.current) popupRef.current.remove();
      map.remove();
      mapRef.current = null;
    };
  }, [onViewportChange]);

  // 2. Add, Update & Remove Backend GeoJSON Layers
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    const currentLayerIds = new Set(layers.map((l) => l.layer_id));

    // Teardown deleted layers from MapLibre canvas
    if (loadedLayersRef.current) {
      for (const layerId of Array.from(loadedLayersRef.current)) {
        if (!currentLayerIds.has(layerId)) {
          const sourceId = `src-${layerId}`;
          const layerIdFill = `layer-${layerId}-fill`;
          const layerIdLine = `layer-${layerId}-line`;
          const layerIdPoint = `layer-${layerId}-point`;

          if (map.getLayer(layerIdPoint)) map.removeLayer(layerIdPoint);
          if (map.getLayer(layerIdFill)) map.removeLayer(layerIdFill);
          if (map.getLayer(layerIdLine)) map.removeLayer(layerIdLine);
          if (map.getSource(sourceId)) map.removeSource(sourceId);

          loadedLayersRef.current.delete(layerId);
          layerDataCache.current.delete(layerId);
        }
      }
    }

    const renderLayers = async () => {
      for (const layer of layers) {
        const sourceId = `src-${layer.layer_id}`;
        const layerIdFill = `layer-${layer.layer_id}-fill`;
        const layerIdLine = `layer-${layer.layer_id}-line`;
        const layerIdPoint = `layer-${layer.layer_id}-point`;

        if (loadedLayersRef.current.has(layer.layer_id) || map.getSource(sourceId)) {
          continue;
        }

        loadedLayersRef.current.add(layer.layer_id);

        try {
          const res = await fetch(`/api/layers/${layer.layer_id}/geojson`);
          if (!res.ok) {
            loadedLayersRef.current.delete(layer.layer_id);
            continue;
          }
          const geojson = await res.json();
          layerDataCache.current.set(layer.layer_id, geojson);

          if (!map.getSource(sourceId)) {
            map.addSource(sourceId, {
              type: 'geojson',
              data: geojson
            });

            const initialOpacity = opacities[layer.layer_id] ?? 0.75;

            // Point Styling
            map.addLayer({
              id: layerIdPoint,
              type: 'circle',
              source: sourceId,
              filter: ['==', '$type', 'Point'],
              paint: {
                'circle-radius': 7,
                'circle-color': '#0284c7',
                'circle-stroke-width': 2,
                'circle-stroke-color': '#ffffff',
                'circle-opacity': initialOpacity,
                'circle-stroke-opacity': initialOpacity
              }
            });

            // Polygon Fill
            map.addLayer({
              id: layerIdFill,
              type: 'fill',
              source: sourceId,
              filter: ['==', '$type', 'Polygon'],
              paint: {
                'fill-color': '#e11d48',
                'fill-opacity': initialOpacity * 0.5
              }
            });

            // Polygon / Line Border
            map.addLayer({
              id: layerIdLine,
              type: 'line',
              source: sourceId,
              paint: {
                'line-color': '#be123c',
                'line-width': 2,
                'line-opacity': initialOpacity
              }
            });
          }
        } catch (err) {
          loadedLayersRef.current.delete(layer.layer_id);
          console.error(`Error loading layer ${layer.layer_id}:`, err);
        }
      }
    };

    if (map.isStyleLoaded()) {
      renderLayers();
    } else {
      map.once('load', renderLayers);
    }
  }, [layers, opacities]);

  // 3. Fit Bounds on Requested Layer
  useEffect(() => {
    if (!zoomLayerId || !mapRef.current) return;
    const map = mapRef.current;
    const geojson = layerDataCache.current.get(zoomLayerId);

    if (!geojson || !geojson.features || geojson.features.length === 0) return;

    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;

    const traverseCoords = (coords) => {
      if (typeof coords[0] === 'number') {
        const [lon, lat] = coords;
        if (lon < minX) minX = lon;
        if (lat < minY) minY = lat;
        if (lon > maxX) maxX = lon;
        if (lat > maxY) maxY = lat;
      } else {
        coords.forEach(traverseCoords);
      }
    };

    geojson.features.forEach((f) => {
      if (f.geometry && f.geometry.coordinates) {
        traverseCoords(f.geometry.coordinates);
      }
    });

    if (minX !== Infinity && minY !== Infinity) {
      // For single points, zoom to center instead of collapsing bounds
      if (minX === maxX && minY === maxY) {
        map.flyTo({
          center: [minX, minY],
          zoom: 14,
          duration: 1000
        });
      } else {
        map.fitBounds(
          [
            [minX, minY],
            [maxX, maxY]
          ],
          {
            padding: 80,
            maxZoom: 15,
            duration: 1200
          }
        );
      }
    }
  }, [zoomLayerId]);

  // 4. Handle Dynamic Visibility Toggling
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded()) return;

    layers.forEach((layer) => {
      const visibilityValue = hiddenLayers.has(layer.layer_id) ? 'none' : 'visible';
      const subLayers = [
        `layer-${layer.layer_id}-point`,
        `layer-${layer.layer_id}-fill`,
        `layer-${layer.layer_id}-line`
      ];

      subLayers.forEach((id) => {
        if (map.getLayer(id)) {
          map.setLayoutProperty(id, 'visibility', visibilityValue);
        }
      });
    });
  }, [hiddenLayers, layers]);

  // 5. Handle Dynamic Opacity Changes
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded()) return;

    layers.forEach((layer) => {
      const opacity = opacities[layer.layer_id] ?? 0.75;
      const pointLayer = `layer-${layer.layer_id}-point`;
      const fillLayer = `layer-${layer.layer_id}-fill`;
      const lineLayer = `layer-${layer.layer_id}-line`;

      if (map.getLayer(pointLayer)) {
        map.setPaintProperty(pointLayer, 'circle-opacity', opacity);
        map.setPaintProperty(pointLayer, 'circle-stroke-opacity', opacity);
      }
      if (map.getLayer(fillLayer)) {
        map.setPaintProperty(fillLayer, 'fill-opacity', opacity * 0.5);
      }
      if (map.getLayer(lineLayer)) {
        map.setPaintProperty(lineLayer, 'line-opacity', opacity);
      }
    });
  }, [opacities, layers]);

  // 6. Feature Inspection Popups & Cursor Management
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    const interactiveLayerIds = [];
    layers.forEach((l) => {
      if (!hiddenLayers.has(l.layer_id)) {
        interactiveLayerIds.push(`layer-${l.layer_id}-point`);
        interactiveLayerIds.push(`layer-${l.layer_id}-fill`);
      }
    });

    const handleFeatureClick = (e) => {
      const availableLayers = interactiveLayerIds.filter((id) => map.getLayer(id));
      if (availableLayers.length === 0) return;

      const features = map.queryRenderedFeatures(e.point, { layers: availableLayers });
      if (!features || features.length === 0) return;

      const feature = features[0];
      const props = feature.properties || {};
      const coordinates = [e.lngLat.lng.toFixed(5), e.lngLat.lat.toFixed(5)];

      const title =
        props.name ||
        props.hospital_name ||
        props.title ||
        feature.layer.id.replace('layer-', '').replace(/-fill|-point/, '');

      const propertyRows = Object.entries(props)
        .filter(([k]) => !['geom', 'geometry', 'id'].includes(k.toLowerCase()))
        .slice(0, 8)
        .map(
          ([k, v]) => `
          <div style="display:flex; justify-content:space-between; gap:12px; font-size:11px; margin-bottom:3px;">
            <span style="color:#94a3b8; text-transform:capitalize;">${k.replace(/_/g, ' ')}</span>
            <span style="color:#f8fafc; font-weight:500; max-width:140px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${v}</span>
          </div>
        `
        )
        .join('');

      const popupHtml = `
        <div style="background-color:#0f172a; color:#e2e8f0; border:1px solid #334155; border-radius:6px; padding:10px 12px; font-family:sans-serif; min-width:180px; box-shadow:0 10px 15px -3px rgba(0,0,0,0.5);">
          <div style="font-weight:600; font-size:13px; color:#38bdf8; margin-bottom:4px; border-bottom:1px solid #1e293b; padding-bottom:4px;">
            ${title}
          </div>
          <div style="margin-bottom:6px;">
            ${propertyRows}
          </div>
          <div style="display:flex; justify-content:space-between; font-size:10px; color:#64748b; border-top:1px solid #1e293b; pt-1;">
            <span>Coordinates:</span>
            <span>${coordinates[0]}, ${coordinates[1]}</span>
          </div>
        </div>
      `;

      if (!popupRef.current) {
        popupRef.current = new maplibregl.Popup({
          closeButton: true,
          closeOnClick: true,
          className: 'geoagent-feature-popup'
        });
      }

      popupRef.current.setLngLat(e.lngLat).setHTML(popupHtml).addTo(map);
    };

    const handleMouseEnter = () => {
      map.getCanvas().style.cursor = 'pointer';
    };

    const handleMouseLeave = () => {
      map.getCanvas().style.cursor = '';
    };

    map.on('click', handleFeatureClick);

    interactiveLayerIds.forEach((id) => {
      if (map.getLayer(id)) {
        map.on('mouseenter', id, handleMouseEnter);
        map.on('mouseleave', id, handleMouseLeave);
      }
    });

    return () => {
      map.off('click', handleFeatureClick);
      interactiveLayerIds.forEach((id) => {
        if (map.getLayer(id)) {
          map.off('mouseenter', id, handleMouseEnter);
          map.off('mouseleave', id, handleMouseLeave);
        }
      });
    };
  }, [layers, hiddenLayers]);

  return (
    <div
      ref={mapContainer}
      className="w-full h-full absolute inset-0"
      style={{ width: '100%', height: '100%' }}
    />
  );
}