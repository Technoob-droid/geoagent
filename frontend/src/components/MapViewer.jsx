import React, { useEffect, useRef, useState } from 'react';
import maplibregl from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import { Ruler, Pentagon, MapPin, X } from 'lucide-react';

const CURRENT_LOCATION = [88.3639, 22.5726]; // Kolkata coordinates [lng, lat]

const PALETTE = [
  { fill: '#38bdf8', stroke: '#0284c7' },
  { fill: '#a855f7', stroke: '#7e22ce' },
  { fill: '#f43f5e', stroke: '#be123c' },
  { fill: '#10b981', stroke: '#047857' },
  { fill: '#f59e0b', stroke: '#b45309' },
  { fill: '#6366f1', stroke: '#4338ca' }
];

function getLayerColor(index) {
  return PALETTE[index % PALETTE.length];
}

function haversineDistance(c1, c2) {
  const toRad = (v) => (v * Math.PI) / 180;
  const R = 6371;
  const dLat = toRad(c2[1] - c1[1]);
  const dLng = toRad(c2[0] - c1[0]);
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(c1[1])) * Math.cos(toRad(c2[1])) * Math.sin(dLng / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(a));
}

function calculatePolygonArea(coords) {
  if (coords.length < 3) return 0;
  const toRad = (v) => (v * Math.PI) / 180;
  const R = 6371;
  let total = 0;

  for (let i = 0; i < coords.length; i++) {
    const p1 = coords[i];
    const p2 = coords[(i + 1) % coords.length];
    total += toRad(p2[0] - p1[0]) * (2 + Math.sin(toRad(p1[1])) + Math.sin(toRad(p2[1])));
  }
  return Math.abs((total * R * R) / 2);
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

  // User coordinate tracking (defaults to central Kolkata)
  const [userCoord, setUserCoord] = useState(CURRENT_LOCATION);
  const userCoordRef = useRef(CURRENT_LOCATION);
  userCoordRef.current = userCoord;

  // Measurement tool state
  const [measureMode, setMeasureMode] = useState(null);
  const [measurePoints, setMeasurePoints] = useState([]);
  const [measureResult, setMeasureResult] = useState(null);
  const measurePointsRef = useRef([]);
  measurePointsRef.current = measurePoints;

  // Initialize Map
  useEffect(() => {
    if (mapRef.current) return;

    const map = new maplibregl.Map({
      container: mapContainer.current,
      style: 'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json',
      center: CURRENT_LOCATION,
      zoom: 11
    });

    map.addControl(new maplibregl.NavigationControl(), 'bottom-right');

    const geolocate = new maplibregl.GeolocateControl({
      positionOptions: { enableHighAccuracy: true },
      trackUserLocation: true,
      showUserLocation: true
    });
    map.addControl(geolocate, 'bottom-right');

    geolocate.on('geolocate', (pos) => {
      const coords = [pos.coords.longitude, pos.coords.latitude];
      setUserCoord(coords);
      const src = map.getSource('user-current-location');
      if (src) {
        src.setData({
          type: 'FeatureCollection',
          features: [
            {
              type: 'Feature',
              geometry: { type: 'Point', coordinates: coords },
              properties: { title: 'My Current Location' }
            }
          ]
        });
      }
    });

    map.on('load', () => {
      // User location source & pulsing halo
      map.addSource('user-current-location', {
        type: 'geojson',
        data: {
          type: 'FeatureCollection',
          features: [
            {
              type: 'Feature',
              geometry: { type: 'Point', coordinates: CURRENT_LOCATION },
              properties: { title: 'My Current Location' }
            }
          ]
        }
      });

      map.addLayer({
        id: 'user-location-halo',
        type: 'circle',
        source: 'user-current-location',
        paint: {
          'circle-radius': 22,
          'circle-color': '#38bdf8',
          'circle-opacity': 0.25,
          'circle-stroke-width': 1.5,
          'circle-stroke-color': '#0284c7'
        }
      });

      map.addLayer({
        id: 'user-location-center',
        type: 'circle',
        source: 'user-current-location',
        paint: {
          'circle-radius': 8,
          'circle-color': '#0ea5e9',
          'circle-stroke-width': 3,
          'circle-stroke-color': '#ffffff'
        }
      });

      // Measurement overlay source & layers
      map.addSource('measure-geojson', {
        type: 'geojson',
        data: { type: 'FeatureCollection', features: [] }
      });

      map.addLayer({
        id: 'measure-polygon',
        type: 'fill',
        source: 'measure-geojson',
        paint: {
          'fill-color': '#ec4899',
          'fill-opacity': 0.25
        }
      });

      map.addLayer({
        id: 'measure-lines',
        type: 'line',
        source: 'measure-geojson',
        paint: {
          'line-color': '#ec4899',
          'line-width': 2.5,
          'line-dasharray': [2, 1.5]
        }
      });

      map.addLayer({
        id: 'measure-points',
        type: 'circle',
        source: 'measure-geojson',
        paint: {
          'circle-radius': 5,
          'circle-color': '#ffffff',
          'circle-stroke-width': 2,
          'circle-stroke-color': '#ec4899'
        }
      });

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
      if (measurePointsRef.current.modeActive) return;

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

      const props = topFeature.properties || {};
      const layerBaseName = clickedLayerId.replace(
        /-point-circle|-unclustered-points|-polygon-fill|-line|-cluster-circles/g,
        ''
      );

      const rows = Object.entries(props)
        .filter(([k]) => !['cluster', 'cluster_id', 'point_count', 'point_count_abbreviated'].includes(k))
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

    return () => {
      if (popupRef.current) popupRef.current.remove();
      map.remove();
      mapRef.current = null;
    };
  }, []);

  // Synchronize Map Layers from Server
  useEffect(() => {
    if (!mapReady || !mapRef.current) return;
    const map = mapRef.current;

    const syncLayers = async () => {
      const currentIds = new Set(layers.map((l) => l.layer_id));

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
              map.addLayer({
                id: `${layerId}-point-circle`,
                type: 'circle',
                source: layerId,
                filter: ['!', ['has', 'point_count']],
                layout: { visibility: !isHidden && mode === 'points' ? 'visible' : 'none' },
                paint: {
                  'circle-radius': 8,
                  'circle-color': color.fill,
                  'circle-stroke-width': 2,
                  'circle-stroke-color': '#ffffff',
                  'circle-opacity': alpha
                }
              });

              map.addLayer({
                id: `${layerId}-heatmap`,
                type: 'heatmap',
                source: layerId,
                maxzoom: 17,
                layout: { visibility: !isHidden && mode === 'heatmap' ? 'visible' : 'none' },
                paint: {
                  'heatmap-weight': 1,
                  'heatmap-intensity': ['interpolate', ['linear'], ['zoom'], 0, 2, 9, 4, 15, 8],
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
                  'heatmap-radius': ['interpolate', ['linear'], ['zoom'], 0, 25, 10, 50, 15, 100],
                  'heatmap-opacity': alpha
                }
              });

              map.addLayer({
                id: `${layerId}-cluster-circles`,
                type: 'circle',
                source: layerId,
                filter: ['has', 'point_count'],
                layout: { visibility: !isHidden && mode === 'clusters' ? 'visible' : 'none' },
                paint: {
                  'circle-color': ['step', ['get', 'point_count'], color.fill, 5, '#6366f1', 20, '#f43f5e'],
                  'circle-radius': ['step', ['get', 'point_count'], 18, 5, 24, 20, 32],
                  'circle-opacity': alpha,
                  'circle-stroke-width': 2,
                  'circle-stroke-color': '#ffffff'
                }
              });

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
                paint: { 'text-color': '#ffffff' }
              });

              map.addLayer({
                id: `${layerId}-unclustered-points`,
                type: 'circle',
                source: layerId,
                filter: ['!', ['has', 'point_count']],
                layout: { visibility: !isHidden && mode === 'clusters' ? 'visible' : 'none' },
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
                layout: { visibility: isHidden ? 'none' : 'visible' },
                paint: {
                  'line-color': color.stroke,
                  'line-width': 3,
                  'line-opacity': alpha
                }
              });
            } else {
              map.addLayer({
                id: `${layerId}-polygon-fill`,
                type: 'fill',
                source: layerId,
                layout: { visibility: isHidden ? 'none' : 'visible' },
                paint: {
                  'fill-color': color.fill,
                  'fill-opacity': alpha * 0.55
                }
              });

              map.addLayer({
                id: `${layerId}-polygon-stroke`,
                type: 'line',
                source: layerId,
                layout: { visibility: isHidden ? 'none' : 'visible' },
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
            console.error(`Failed to load layer ${layerId}:`, err);
          }
        }
      }
    };

    syncLayers();
  }, [layers, mapReady]);

  // Synchronize dynamic visibility / displayMode
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

  // Handle Measurement Drawing Clicks
  useEffect(() => {
    if (!mapReady || !mapRef.current) return;
    const map = mapRef.current;

    measurePointsRef.current.modeActive = !!measureMode;

    const onMapClick = (e) => {
      if (!measureMode) return;
      const pt = [e.lngLat.lng, e.lngLat.lat];
      setMeasurePoints((prev) => [...prev, pt]);
    };

    map.on('click', onMapClick);
    return () => {
      map.off('click', onMapClick);
    };
  }, [measureMode, mapReady]);

  // Update Measurement GeoJSON Features & Metrics
  useEffect(() => {
    if (!mapReady || !mapRef.current) return;
    const map = mapRef.current;
    const source = map.getSource('measure-geojson');
    if (!source) return;

    if (measurePoints.length === 0) {
      source.setData({ type: 'FeatureCollection', features: [] });
      setMeasureResult(null);
      return;
    }

    const features = [];

    measurePoints.forEach((coord) => {
      features.push({
        type: 'Feature',
        geometry: { type: 'Point', coordinates: coord }
      });
    });

    if (measureMode === 'distance' && measurePoints.length >= 2) {
      features.push({
        type: 'Feature',
        geometry: { type: 'LineString', coordinates: measurePoints }
      });

      let totalKm = 0;
      for (let i = 0; i < measurePoints.length - 1; i++) {
        totalKm += haversineDistance(measurePoints[i], measurePoints[i + 1]);
      }
      setMeasureResult(
        totalKm >= 1 ? `${totalKm.toFixed(2)} km` : `${(totalKm * 1000).toFixed(0)} m`
      );
    } else if (measureMode === 'area' && measurePoints.length >= 3) {
      const ring = [...measurePoints, measurePoints[0]];
      features.push({
        type: 'Feature',
        geometry: { type: 'Polygon', coordinates: [ring] }
      });

      const areaKm2 = calculatePolygonArea(measurePoints);
      setMeasureResult(
        areaKm2 >= 1
          ? `${areaKm2.toFixed(2)} km²`
          : `${(areaKm2 * 1000000).toLocaleString(undefined, { maximumFractionDigits: 0 })} m²`
      );
    } else {
      setMeasureResult(null);
    }

    source.setData({ type: 'FeatureCollection', features });
  }, [measurePoints, measureMode, mapReady]);

  // Action: Start from Current Location
  const handleStartFromCurrentLocation = () => {
    const origin = userCoordRef.current;
    setMeasureMode('distance');
    setMeasurePoints([origin]);
    if (mapRef.current) {
      mapRef.current.flyTo({ center: origin, zoom: 13, duration: 800 });
    }
  };

  const handleResetMeasure = () => {
    setMeasureMode(null);
    setMeasurePoints([]);
    setMeasureResult(null);
  };

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

      {/* Floating Measurement Toolbar */}
      <div className="absolute top-4 left-4 z-20 flex items-center space-x-1.5 bg-slate-900/90 backdrop-blur-md border border-slate-800 rounded-lg p-1.5 shadow-xl text-xs">
        <button
          type="button"
          onClick={() => {
            setMeasureMode(measureMode === 'distance' ? null : 'distance');
            setMeasurePoints([]);
          }}
          className={`flex items-center space-x-1.5 px-2.5 py-1.5 rounded transition ${
            measureMode === 'distance'
              ? 'bg-pink-600 text-white font-medium'
              : 'text-slate-300 hover:bg-slate-800'
          }`}
          title="Measure distance along polyline"
        >
          <Ruler className="w-3.5 h-3.5" />
          <span>Distance</span>
        </button>

        <button
          type="button"
          onClick={() => {
            setMeasureMode(measureMode === 'area' ? null : 'area');
            setMeasurePoints([]);
          }}
          className={`flex items-center space-x-1.5 px-2.5 py-1.5 rounded transition ${
            measureMode === 'area'
              ? 'bg-pink-600 text-white font-medium'
              : 'text-slate-300 hover:bg-slate-800'
          }`}
          title="Measure polygon surface area"
        >
          <Pentagon className="w-3.5 h-3.5" />
          <span>Area</span>
        </button>

        <button
          type="button"
          onClick={handleStartFromCurrentLocation}
          className="flex items-center space-x-1.5 px-2.5 py-1.5 rounded text-sky-400 hover:bg-slate-800 transition"
          title="Start distance measurement directly from your current position"
        >
          <MapPin className="w-3.5 h-3.5 text-sky-400" />
          <span>From Here</span>
        </button>

        {measureMode && (
          <button
            type="button"
            onClick={handleResetMeasure}
            className="p-1.5 text-slate-400 hover:text-rose-400 hover:bg-slate-800 rounded transition"
            title="Clear measurement"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        )}

        {/* Live Calculation Output Badge */}
        {measureResult && (
          <div className="ml-2 pl-2 border-l border-slate-700 text-emerald-400 font-mono font-semibold px-2">
            {measureResult}
          </div>
        )}
      </div>

      <div
        ref={mapContainer}
        style={{ width: '100%', height: '100%', position: 'absolute', top: 0, left: 0 }}
      />
    </>
  );
}