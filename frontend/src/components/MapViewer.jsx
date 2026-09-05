import React, { useEffect, useRef, useState } from 'react';
import maplibregl from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';

const PALETTE = [
  { fill: '#38bdf8', stroke: '#0284c7' }, // Sky
  { fill: '#a855f7', stroke: '#7e22ce' }, // Purple
  { fill: '#f43f5e', stroke: '#be123c' }, // Rose
  { fill: '#10b981', stroke: '#047857' }, // Emerald
  { fill: '#f59e0b', stroke: '#b45309' }, // Amber
  { fill: '#6366f1', stroke: '#4338ca' }  // Indigo
];

function getLayerColor(index) {
  return PALETTE[index % PALETTE.length];
}

function computeBBox(geojson) {
  if (!geojson || !geojson.features || geojson.features.length === 0) return null;
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;

  const traverseCoords = (coords) => {
    if (typeof coords[0] === 'number') {
      const [x, y] = coords;
      if (x < minX) minX = x;
      if (y < minY) minY = y;
      if (x > maxX) maxX = x;
      if (y > maxY) maxY = y;
    } else {
      coords.forEach(traverseCoords);
    }
  };

  geojson.features.forEach((f) => {
    if (f.geometry && f.geometry.coordinates) {
      traverseCoords(f.geometry.coordinates);
    }
  });

  if (minX === Infinity) return null;
  return [minX, minY, maxX, maxY];
}

export default function MapViewer({
  layers = [],
  hiddenLayers = new Set(),
  opacities = {},
  displayModes = {},
  zoomLayerId = null,
  onViewportChange
}) {
  const mapContainer = useRef(null);
  const mapRef = useRef(null);
  const popupRef = useRef(null);
  const [mapReady, setMapReady] = useState(false);
  const loadedLayersRef = useRef(new Map());
  const initialZoomDoneRef = useRef(false);

  // Initialize Map
  useEffect(() => {
    if (mapRef.current) return;

    const map = new maplibregl.Map({
      container: mapContainer.current,
      style: 'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json',
      center: [88.3639, 22.5726],
      zoom: 11
    });

    map.addControl(new maplibregl.NavigationControl(), 'bottom-right');

    map.on('load', () => {
      mapRef.current = map;
      setMapReady(true);
    });

    map.on('moveend', () => {
      if (onViewportChange) {
        const bounds = map.getBounds();
        onViewportChange([
          bounds.getWest(),
          bounds.getSouth(),
          bounds.getEast(),
          bounds.getNorth()
        ]);
      }
    });

    // Feature Click Popup & Cluster Zoom
    map.on('click', (e) => {
      const allInteractiveLayers = [];
      loadedLayersRef.current.forEach((_, layerId) => {
        [
          `${layerId}-cluster-circles`,
          `${layerId}-point-circle`,
          `${layerId}-unclustered-points`,
          `${layerId}-polygon-fill`,
          `${layerId}-line`
        ].forEach((subId) => {
          if (map.getLayer(subId)) allInteractiveLayers.push(subId);
        });
      });

      if (allInteractiveLayers.length === 0) return;

      const features = map.queryRenderedFeatures(e.point, {
        layers: allInteractiveLayers
      });

      if (!features || features.length === 0) {
        if (popupRef.current) popupRef.current.remove();
        return;
      }

      const topFeature = features[0];
      const clickedLayerId = topFeature.layer.id;

      // Click on cluster -> zoom into cluster
      if (clickedLayerId.endsWith('-cluster-circles')) {
        const sourceName = topFeature.layer.source;
        const source = map.getSource(sourceName);
        if (source && source.getClusterExpansionZoom) {
          source.getClusterExpansionZoom(topFeature.properties.cluster_id, (err, zoom) => {
            if (err) return;
            map.easeTo({
              center: topFeature.geometry.coordinates,
              zoom: zoom + 0.5
            });
          });
        }
        return;
      }

      // Format feature properties into a clean dark table
      const props = topFeature.properties || {};
      const layerBaseName = clickedLayerId.replace(
        /-point-circle|-unclustered-points|-polygon-fill|-line|-cluster-circles/g,
        ''
      );

      const rows = Object.entries(props)
        .filter(([key]) => key !== 'cluster' && key !== 'cluster_id' && key !== 'point_count' && key !== 'point_count_abbreviated')
        .map(
          ([k, v]) => `
          <tr style="border-bottom: 1px solid rgba(255,255,255,0.06);">
            <td style="padding: 3px 6px; font-weight: 600; color: #94a3b8; font-size: 11px;">${k}</td>
            <td style="padding: 3px 6px; color: #e2e8f0; font-size: 11px; word-break: break-all;">${v}</td>
          </tr>`
        )
        .join('');

      const popupHtml = `
        <div style="font-family: ui-sans-serif, system-ui, sans-serif; min-width: 170px; max-width: 280px; max-height: 220px; overflow-y: auto;">
          <div style="font-size: 11px; font-weight: bold; color: #38bdf8; text-transform: uppercase; margin-bottom: 6px; letter-spacing: 0.05em;">
            ${layerBaseName}
          </div>
          ${
            rows
              ? `<table style="width: 100%; border-collapse: collapse; text-align: left;">${rows}</table>`
              : `<div style="font-size: 11px; color: #94a3b8;">No attributes available</div>`
          }
        </div>
      `;

      if (popupRef.current) popupRef.current.remove();

      popupRef.current = new maplibregl.Popup({
        closeButton: true,
        closeOnClick: true,
        className: 'geoagent-map-popup'
      })
        .setLngLat(e.lngLat)
        .setHTML(popupHtml)
        .addTo(map);
    });

    // Pointer cursor on hover over features
    map.on('mousemove', (e) => {
      const allInteractiveLayers = [];
      loadedLayersRef.current.forEach((_, layerId) => {
        [
          `${layerId}-cluster-circles`,
          `${layerId}-point-circle`,
          `${layerId}-unclustered-points`,
          `${layerId}-polygon-fill`,
          `${layerId}-line`
        ].forEach((subId) => {
          if (map.getLayer(subId)) allInteractiveLayers.push(subId);
        });
      });

      if (allInteractiveLayers.length === 0) {
        map.getCanvas().style.cursor = '';
        return;
      }

      const features = map.queryRenderedFeatures(e.point, {
        layers: allInteractiveLayers
      });
      map.getCanvas().style.cursor = features.length > 0 ? 'pointer' : '';
    });

    return () => {
      if (popupRef.current) popupRef.current.remove();
      map.remove();
      mapRef.current = null;
    };
  }, []);

  // Synchronize Spatial Layers
  useEffect(() => {
    if (!mapReady || !mapRef.current) return;
    const map = mapRef.current;

    const syncLayers = async () => {
      const currentIds = new Set(layers.map((l) => l.layer_id));

      // 1. Remove deleted layers
      for (const [id] of loadedLayersRef.current.entries()) {
        if (!currentIds.has(id)) {
          [
            `${id}-polygon-fill`,
            `${id}-polygon-stroke`,
            `${id}-line`,
            `${id}-point-circle`,
            `${id}-cluster-circles`,
            `${id}-cluster-counts`,
            `${id}-unclustered-points`,
            `${id}-heatmap`
          ].forEach((lid) => {
            if (map.getLayer(lid)) map.removeLayer(lid);
          });
          if (map.getSource(id)) map.removeSource(id);
          loadedLayersRef.current.delete(id);
        }
      }

      // 2. Load active layers
      for (let i = 0; i < layers.length; i++) {
        const layer = layers[i];
        const layerId = layer.layer_id;
        const geomType = layer.geom_type?.toUpperCase() || 'POLYGON';
        const isPoint = geomType === 'POINT' || geomType === 'MULTIPOINT';
        const color = getLayerColor(i);
        const mode = displayModes[layerId] || 'points';
        const isHidden = hiddenLayers.has(layerId);
        const alpha = opacities[layerId] ?? 0.75;

        if (!loadedLayersRef.current.has(layerId)) {
          try {
            const res = await fetch(`/api/layers/${layerId}/geojson`);
            if (!res.ok) continue;
            const data = await res.json();

            map.addSource(layerId, {
              type: 'geojson',
              data,
              cluster: isPoint,
              clusterRadius: 50,
              clusterMaxZoom: 14
            });

            if (isPoint) {
              // Points
              map.addLayer({
                id: `${layerId}-point-circle`,
                type: 'circle',
                source: layerId,
                filter: ['!', ['has', 'point_count']],
                layout: {
                  visibility: !isHidden && mode === 'points' ? 'visible' : 'none'
                },
                paint: {
                  'circle-radius': 8,
                  'circle-color': color.fill,
                  'circle-stroke-width': 2,
                  'circle-stroke-color': '#ffffff',
                  'circle-opacity': alpha
                }
              });

              // Heatmap
              map.addLayer({
                id: `${layerId}-heatmap`,
                type: 'heatmap',
                source: layerId,
                maxzoom: 17,
                layout: {
                  visibility: !isHidden && mode === 'heatmap' ? 'visible' : 'none'
                },
                paint: {
                  'heatmap-weight': 1,
                  'heatmap-intensity': [
                    'interpolate',
                    ['linear'],
                    ['zoom'],
                    0, 2,
                    9, 4,
                    15, 8
                  ],
                  'heatmap-color': [
                    'interpolate',
                    ['linear'],
                    ['heatmap-density'],
                    0, 'rgba(0, 0, 0, 0)',
                    0.05, '#38bdf8',
                    0.2, '#34d399',
                    0.5, '#facc15',
                    0.7, '#fb923c',
                    1.0, '#f43f5e'
                  ],
                  'heatmap-radius': [
                    'interpolate',
                    ['linear'],
                    ['zoom'],
                    0, 25,
                    10, 50,
                    15, 100
                  ],
                  'heatmap-opacity': alpha
                }
              });

              // Cluster circles
              map.addLayer({
                id: `${layerId}-cluster-circles`,
                type: 'circle',
                source: layerId,
                filter: ['has', 'point_count'],
                layout: {
                  visibility: !isHidden && mode === 'clusters' ? 'visible' : 'none'
                },
                paint: {
                  'circle-color': [
                    'step',
                    ['get', 'point_count'],
                    color.fill,
                    5, '#6366f1',
                    20, '#f43f5e'
                  ],
                  'circle-radius': [
                    'step',
                    ['get', 'point_count'],
                    18,
                    5, 24,
                    20, 32
                  ],
                  'circle-opacity': alpha,
                  'circle-stroke-width': 2,
                  'circle-stroke-color': '#ffffff'
                }
              });

              // Cluster count labels
              map.addLayer({
                id: `${layerId}-cluster-counts`,
                type: 'symbol',
                source: layerId,
                filter: ['has', 'point_count'],
                layout: {
                  visibility: !isHidden && mode === 'clusters' ? 'visible' : 'none',
                  'text-field': '{point_count_abbreviated}',
                  'text-size': 13
                },
                paint: {
                  'text-color': '#ffffff'
                }
              });

              // Unclustered points in cluster mode
              map.addLayer({
                id: `${layerId}-unclustered-points`,
                type: 'circle',
                source: layerId,
                filter: ['!', ['has', 'point_count']],
                layout: {
                  visibility: !isHidden && mode === 'clusters' ? 'visible' : 'none'
                },
                paint: {
                  'circle-color': color.fill,
                  'circle-radius': 7,
                  'circle-stroke-width': 2,
                  'circle-stroke-color': '#ffffff',
                  'circle-opacity': alpha
                }
              });
            } else if (geomType === 'LINESTRING' || geomType === 'MULTILINESTRING') {
              map.addLayer({
                id: `${layerId}-line`,
                type: 'line',
                source: layerId,
                layout: {
                  visibility: isHidden ? 'none' : 'visible'
                },
                paint: {
                  'line-color': color.stroke,
                  'line-width': 3,
                  'line-opacity': alpha
                }
              });
            } else {
              // Polygons
              map.addLayer({
                id: `${layerId}-polygon-fill`,
                type: 'fill',
                source: layerId,
                layout: {
                  visibility: isHidden ? 'none' : 'visible'
                },
                paint: {
                  'fill-color': color.fill,
                  'fill-opacity': alpha * 0.55
                }
              });

              map.addLayer({
                id: `${layerId}-polygon-stroke`,
                type: 'line',
                source: layerId,
                layout: {
                  visibility: isHidden ? 'none' : 'visible'
                },
                paint: {
                  'line-color': color.stroke,
                  'line-width': 2,
                  'line-opacity': alpha
                }
              });
            }

            loadedLayersRef.current.set(layerId, { geojson: data, geomType, color });

            if (!initialZoomDoneRef.current) {
              const bbox = computeBBox(data);
              if (bbox) {
                map.fitBounds(
                  [[bbox[0], bbox[1]], [bbox[2], bbox[3]]],
                  { padding: 80, maxZoom: 14, duration: 1000 }
                );
                initialZoomDoneRef.current = true;
              }
            }
          } catch (err) {
            console.error(`[MapViewer] Failed to load layer ${layerId}:`, err);
          }
        }
      }
    };

    syncLayers();
  }, [layers, mapReady]);

  // Synchronize dynamic visibility / mode changes
  useEffect(() => {
    if (!mapReady || !mapRef.current) return;
    const map = mapRef.current;

    layers.forEach((layer) => {
      const layerId = layer.layer_id;
      const isHidden = hiddenLayers.has(layerId);
      const alpha = opacities[layerId] ?? 0.75;
      const mode = displayModes[layerId] || 'points';
      const geomType = layer.geom_type?.toUpperCase();
      const isPoint = geomType === 'POINT' || geomType === 'MULTIPOINT';

      if (isPoint) {
        const showPoints = !isHidden && mode === 'points';
        const showClusters = !isHidden && mode === 'clusters';
        const showHeatmap = !isHidden && mode === 'heatmap';

        if (map.getLayer(`${layerId}-point-circle`)) {
          map.setLayoutProperty(`${layerId}-point-circle`, 'visibility', showPoints ? 'visible' : 'none');
          if (showPoints) map.setPaintProperty(`${layerId}-point-circle`, 'circle-opacity', alpha);
        }

        if (map.getLayer(`${layerId}-cluster-circles`)) {
          map.setLayoutProperty(`${layerId}-cluster-circles`, 'visibility', showClusters ? 'visible' : 'none');
          map.setLayoutProperty(`${layerId}-cluster-counts`, 'visibility', showClusters ? 'visible' : 'none');
          map.setLayoutProperty(`${layerId}-unclustered-points`, 'visibility', showClusters ? 'visible' : 'none');
          if (showClusters) {
            map.setPaintProperty(`${layerId}-cluster-circles`, 'circle-opacity', alpha);
            map.setPaintProperty(`${layerId}-unclustered-points`, 'circle-opacity', alpha);
          }
        }

        if (map.getLayer(`${layerId}-heatmap`)) {
          map.setLayoutProperty(`${layerId}-heatmap`, 'visibility', showHeatmap ? 'visible' : 'none');
          if (showHeatmap) map.setPaintProperty(`${layerId}-heatmap`, 'heatmap-opacity', alpha);
        }
      } else {
        const visibility = isHidden ? 'none' : 'visible';
        if (map.getLayer(`${layerId}-polygon-fill`)) {
          map.setLayoutProperty(`${layerId}-polygon-fill`, 'visibility', visibility);
          if (!isHidden) map.setPaintProperty(`${layerId}-polygon-fill`, 'fill-opacity', alpha * 0.55);
        }
        if (map.getLayer(`${layerId}-polygon-stroke`)) {
          map.setLayoutProperty(`${layerId}-polygon-stroke`, 'visibility', visibility);
          if (!isHidden) map.setPaintProperty(`${layerId}-polygon-stroke`, 'line-opacity', alpha);
        }
        if (map.getLayer(`${layerId}-line`)) {
          map.setLayoutProperty(`${layerId}-line`, 'visibility', visibility);
          if (!isHidden) map.setPaintProperty(`${layerId}-line`, 'line-opacity', alpha);
        }
      }
    });
  }, [layers, hiddenLayers, opacities, displayModes, mapReady]);

  // Handle Zoom to Layer Request
  useEffect(() => {
    if (!zoomLayerId || !mapRef.current) return;
    const item = loadedLayersRef.current.get(zoomLayerId);
    if (!item || !item.geojson) return;

    const bbox = computeBBox(item.geojson);
    if (bbox) {
      mapRef.current.fitBounds(
        [[bbox[0], bbox[1]], [bbox[2], bbox[3]]],
        { padding: 60, maxZoom: 15, duration: 1200 }
      );
    }
  }, [zoomLayerId]);

  return (
    <>
      <style>{`
        .geoagent-map-popup .maplibregl-popup-content {
          background-color: #0f172a !important;
          border: 1px solid #334155 !important;
          border-radius: 8px !important;
          padding: 10px !important;
          box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.6) !important;
        }
        .geoagent-map-popup .maplibregl-popup-close-button {
          color: #94a3b8 !important;
          font-size: 16px !important;
          padding: 3px 6px !important;
        }
        .geoagent-map-popup .maplibregl-popup-close-button:hover {
          color: #f8fafc !important;
          background: transparent !important;
        }
        .geoagent-map-popup .maplibregl-popup-tip {
          border-top-color: #0f172a !important;
        }
      `}</style>
      <div
        ref={mapContainer}
        style={{ width: '100%', height: '100%', position: 'absolute', top: 0, left: 0 }}
      />
    </>
  );
}