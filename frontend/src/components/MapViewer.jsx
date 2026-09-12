import React, { useEffect, useRef, useState } from 'react';
import maplibregl from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import { Ruler, Pentagon, MapPin, X, Search, Loader2, BarChart3 } from 'lucide-react';
import { COLOR_PALETTES, buildInterpolateColor } from '../utils/colorRamps';

const CURRENT_LOCATION = [88.3639, 22.5726]; // Kolkata coordinates [lng, lat]

const PALETTE = [
  { fill: '#38bdf8', stroke: '#0284c7' },
  { fill: '#a855f7', stroke: '#7e22ce' },
  { fill: '#f43f5e', stroke: '#be123c' },
  { fill: '#10b981', stroke: '#047857' },
  { fill: '#f59e0b', stroke: '#b45309' },
  { fill: '#6366f1', stroke: '#4338ca' }
];

const METRIC_PRIORITY_KEYS = [
  'feature_count',    // Prioritizes aggregated counts (e.g., villages exposed)
  'metric_sum',
  'metric_avg',
  'metric_max',
  'metric_min',
  'ring_order',       // Falls back to buffer ring tier when no count is present
  'count',
  'population',
  'risk_score'
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

function extractChoroplethDomain(geojson) {
  if (!geojson || !geojson.features || geojson.features.length === 0) return null;

  // Find candidate numeric property
  const sampleProps = geojson.features[0]?.properties || {};
  let selectedProp = null;

  for (const k of METRIC_PRIORITY_KEYS) {
    if (k in sampleProps && typeof Number(sampleProps[k]) === 'number' && !isNaN(Number(sampleProps[k]))) {
      selectedProp = k;
      break;
    }
  }

  if (!selectedProp) {
    for (const [key, val] of Object.entries(sampleProps)) {
      const num = Number(val);
      if (!isNaN(num) && !['cell_id', 'id', 'gid', 'cartodb_id'].includes(key.toLowerCase())) {
        selectedProp = key;
        break;
      }
    }
  }

  if (!selectedProp) return null;

  const values = geojson.features
    .map((f) => Number(f.properties?.[selectedProp]))
    .filter((v) => !isNaN(v));

  if (values.length === 0) return null;

  const min = Math.min(...values);
  const max = Math.max(...values);

  return { property: selectedProp, min, max };
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

  // User coordinate tracking
  const [userCoord, setUserCoord] = useState(CURRENT_LOCATION);
  const userCoordRef = useRef(CURRENT_LOCATION);
  userCoordRef.current = userCoord;

  // Active Choropleth Legend State
  const [activeLegend, setActiveLegend] = useState(null);

  // Measurement tool state
  const [measureMode, setMeasureMode] = useState(null);
  const [measurePoints, setMeasurePoints] = useState([]);
  const [measureResult, setMeasureResult] = useState(null);
  const measurePointsRef = useRef([]);
  measurePointsRef.current = measurePoints;

  // Place Search & Auto-Zoom State
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState([]);
  const [isSearching, setIsSearching] = useState(false);
  const [isSearchOpen, setIsSearchOpen] = useState(false);
  const searchDropdownRef = useRef(null);

  const updateViewportBoundaries = async () => {
    const map = mapRef.current;
    if (!map) return;

    const zoom = map.getZoom();
    const bounds = map.getBounds();
    const level = zoom >= 7.5 ? 'districts' : 'states';

    const minX = bounds.getWest();
    const minY = bounds.getSouth();
    const maxX = bounds.getEast();
    const maxY = bounds.getNorth();

    try {
      const res = await fetch(
        `/api/layers/boundaries/query?level=${level}&min_x=${minX}&min_y=${minY}&max_x=${maxX}&max_y=${maxY}`
      );
      if (!res.ok) return;
      const geojson = await res.json();

      const src = map.getSource('admin-boundaries-source');
      if (src) {
        src.setData(geojson);
      }
    } catch (err) {
      console.error('Failed to stream administrative boundaries:', err);
    }
  };

  useEffect(() => {
    const handleClickOutside = (e) => {
      if (searchDropdownRef.current && !searchDropdownRef.current.contains(e.target)) {
        setIsSearchOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  useEffect(() => {
    if (searchQuery.trim().length < 2) {
      setSearchResults([]);
      setIsSearchOpen(false);
      return;
    }

    const timer = setTimeout(async () => {
      setIsSearching(true);
      try {
        const res = await fetch(`/api/layers/resolver/search?query=${encodeURIComponent(searchQuery.trim())}`);
        if (res.ok) {
          const data = await res.json();
          setSearchResults(data.results || []);
          setIsSearchOpen(true);
        }
      } catch (err) {
        console.error('Place resolver search failed:', err);
      } finally {
        setIsSearching(false);
      }
    }, 250);

    return () => clearTimeout(timer);
  }, [searchQuery]);

  const handleSelectPlace = (place) => {
    const map = mapRef.current;
    if (!map) return;

    setIsSearchOpen(false);
    setSearchQuery(place.name);

    if (place.min_x != null && place.min_y != null && place.max_x != null && place.max_y != null) {
      map.fitBounds(
        [
          [place.min_x, place.min_y],
          [place.max_x, place.max_y]
        ],
        { padding: 50, duration: 1200 }
      );
    } else if (place.center_x != null && place.center_y != null) {
      map.flyTo({
        center: [place.center_x, place.center_y],
        zoom: place.type === 'state' ? 6 : 9,
        duration: 1200
      });
    }
  };

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
      map.addSource('admin-boundaries-source', {
        type: 'geojson',
        data: { type: 'FeatureCollection', features: [] }
      });

      map.addLayer({
        id: 'admin-boundaries-fill',
        type: 'fill',
        source: 'admin-boundaries-source',
        paint: {
          'fill-color': '#6366f1',
          'fill-opacity': 0.04
        }
      });

      map.addLayer({
        id: 'admin-boundaries-line',
        type: 'line',
        source: 'admin-boundaries-source',
        paint: {
          'line-color': '#818cf8',
          'line-width': 1.2,
          'line-opacity': 0.45
        }
      });

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
      updateViewportBoundaries();
    });

    map.on('moveend', () => {
      updateViewportBoundaries();
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

      let detectedLegend = null;

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
              // Check for continuous numerical metrics for choropleth mapping
              const domain = extractChoroplethDomain(data);
              const isChoropleth = domain && domain.min !== domain.max;

              const fillColorExpr = isChoropleth
                ? buildInterpolateColor(domain.property, domain.min, domain.max, COLOR_PALETTES.viridis)
                : color.fill;

              if (isChoropleth && !isHidden) {
                detectedLegend = {
                  layerName: layer.name || layerId,
                  property: domain.property,
                  min: domain.min,
                  max: domain.max,
                  palette: COLOR_PALETTES.viridis
                };
              }

              map.addLayer({
                id: `${layerId}-polygon-fill`,
                type: 'fill',
                source: layerId,
                layout: { visibility: isHidden ? 'none' : 'visible' },
                paint: {
                  'fill-color': fillColorExpr,
                  'fill-opacity': alpha * 0.7
                }
              });

              map.addLayer({
                id: `${layerId}-polygon-stroke`,
                type: 'line',
                source: layerId,
                layout: { visibility: isHidden ? 'none' : 'visible' },
                paint: {
                  'line-color': isChoropleth ? '#ffffff' : color.stroke,
                  'line-width': isChoropleth ? 1.5 : 2,
                  'line-opacity': alpha
                }
              });
            }

            loadedLayersRef.current.set(layerId, { geojson: data, geomType, color });

            // Do not auto-zoom on base countrywide background layers
            const isBaseAdmin = [
              'india_states',
              'india_districts',
              'india_subdistricts',
              'india_cities',
              'india_villages'
            ].includes(layerId);

            const bbox = computeBBox(data);
            if (bbox) {
              if (!isBaseAdmin) {
                // Smoothly zoom into any newly materialized user/analytical layer
                map.fitBounds(
                  [[bbox[0], bbox[1]], [bbox[2], bbox[3]]],
                  { padding: 80, maxZoom: 13, duration: 1200 }
                );
              } else if (!initialZoomDoneRef.current) {
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
        } else {
          // If layer already loaded, evaluate active legend candidate
          const existing = loadedLayersRef.current.get(layerId);
          if (existing && existing.geomType !== 'POINT' && !isHidden) {
            const domain = extractChoroplethDomain(existing.geojson);
            if (domain && domain.min !== domain.max && !detectedLegend) {
              detectedLegend = {
                layerName: layer.name || layerId,
                property: domain.property,
                min: domain.min,
                max: domain.max,
                palette: COLOR_PALETTES.viridis
              };
            }
          }
        }
      }

      setActiveLegend(detectedLegend);
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
          if (!isHidden) map.setPaintProperty(`${layerId}-polygon-fill`, 'fill-opacity', alpha * 0.7);
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

      {/* Top Floating Control Bar */}
      <div className="absolute top-4 left-4 z-20 flex flex-wrap items-center gap-2">
        <div className="flex items-center space-x-1.5 bg-slate-900/90 backdrop-blur-md border border-slate-800 rounded-lg p-1.5 shadow-xl text-xs">
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

          {measureResult && (
            <div className="ml-2 pl-2 border-l border-slate-700 text-emerald-400 font-mono font-semibold px-2">
              {measureResult}
            </div>
          )}
        </div>

        {/* Nationwide Place Resolver Search Bar */}
        <div ref={searchDropdownRef} className="relative w-64 text-xs">
          <div className="flex items-center bg-slate-900/90 backdrop-blur-md border border-slate-800 rounded-lg px-2.5 py-2 shadow-xl focus-within:border-indigo-500 transition">
            <Search className="w-3.5 h-3.5 text-slate-400 mr-2 shrink-0" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search State or District..."
              className="bg-transparent text-slate-200 placeholder-slate-500 focus:outline-none w-full text-xs"
            />
            {isSearching && <Loader2 className="w-3 h-3 text-indigo-400 animate-spin mr-1 shrink-0" />}
            {searchQuery && !isSearching && (
              <button
                type="button"
                onClick={() => {
                  setSearchQuery('');
                  setSearchResults([]);
                  setIsSearchOpen(false);
                }}
                className="text-slate-500 hover:text-slate-300"
              >
                <X className="w-3 h-3" />
              </button>
            )}
          </div>

          {isSearchOpen && searchResults.length > 0 && (
            <div className="absolute top-full left-0 right-0 mt-1.5 bg-slate-900 border border-slate-800 rounded-lg shadow-2xl py-1 z-50 max-h-60 overflow-y-auto">
              {searchResults.map((r, idx) => (
                <button
                  key={`${r.name}-${idx}`}
                  type="button"
                  onClick={() => handleSelectPlace(r)}
                  className="w-full text-left px-3 py-2 hover:bg-slate-800 flex items-center justify-between text-slate-200 transition"
                >
                  <div className="flex items-center space-x-2 truncate">
                    <MapPin className="w-3 h-3 text-indigo-400 shrink-0" />
                    <span className="font-medium truncate">{r.name}</span>
                    <span className="text-[10px] text-slate-400 truncate">({r.parent})</span>
                  </div>
                  <span className="text-[9px] uppercase tracking-wider px-1.5 py-0.5 rounded bg-slate-800 text-slate-400 shrink-0 ml-2 border border-slate-700">
                    {r.type}
                  </span>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Floating Dynamic Choropleth Legend */}
      {activeLegend && (
        <div className="absolute bottom-6 left-4 z-20 bg-slate-900/90 backdrop-blur-md border border-slate-800 rounded-lg p-3 shadow-xl text-xs w-60">
          <div className="flex items-center space-x-1.5 text-slate-300 font-semibold uppercase tracking-wider text-[10px] mb-1.5">
            <BarChart3 className="w-3.5 h-3.5 text-indigo-400" />
            <span className="truncate">{activeLegend.layerName}</span>
          </div>

          <div className="text-[10px] text-slate-400 font-mono mb-2 truncate">
            Metric: <span className="text-sky-300 font-medium">{activeLegend.property}</span>
          </div>

          {/* Color Gradient Strip */}
          <div
            className="h-2.5 w-full rounded-sm shadow-inner"
            style={{
              background: `linear-gradient(to right, ${activeLegend.palette.join(', ')})`
            }}
          />

          {/* Min and Max Range */}
          <div className="flex justify-between items-center text-[10px] text-slate-400 font-mono mt-1">
            <span>{activeLegend.min}</span>
            <span>{((activeLegend.min + activeLegend.max) / 2).toFixed(1)}</span>
            <span>{activeLegend.max}</span>
          </div>
        </div>
      )}

      <div
        ref={mapContainer}
        style={{ width: '100%', height: '100%', position: 'absolute', top: 0, left: 0 }}
      />
    </>
  );
}