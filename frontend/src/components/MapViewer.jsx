import React, { useEffect, useRef, useState } from 'react';
import maplibregl from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import { Ruler, Pentagon, MapPin, X, Search, Loader2, BarChart3 } from 'lucide-react';
import { COLOR_PALETTES, buildInterpolateColor } from '../utils/colorRamps';
import { DISCOM_HIERARCHY_CONFIG } from '../config/hierarchyConfig';

const CURRENT_LOCATION = [88.3639, 22.5726]; // Kolkata coordinates [lng, lat]

// Layers served via DuckDB vector tiles rather than GeoJSON payloads
const VECTOR_TILE_LAYERS = new Set([
  'india_villages',
  'india_cities',
  'villages',
  'cities',
  'utility_feeders_master',
  'utility_substations_master',
  'utility_switchgear_master'
]);

const PALETTE = [
  { fill: '#38bdf8', stroke: '#0284c7' },
  { fill: '#a855f7', stroke: '#7e22ce' },
  { fill: '#f43f5e', stroke: '#be123c' },
  { fill: '#10b981', stroke: '#047857' },
  { fill: '#f59e0b', stroke: '#b45309' },
  { fill: '#6366f1', stroke: '#4338ca' }
];

const METRIC_PRIORITY_KEYS = [
  'feature_count',
  'metric_sum',
  'metric_avg',
  'metric_max',
  'metric_min',
  'ring_order',
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
  const hoverPopupRef = useRef(null);
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
              // Register custom high-contrast electric bolt SVG/canvas icon
        const addBoltImage = () => {
          if (map.hasImage('bolt-icon')) return;
          const size = 32;
          const canvas = document.createElement('canvas');
          canvas.width = size;
          canvas.height = size;
          const ctx = canvas.getContext('2d');
          
          ctx.save();
          ctx.scale(size / 32, size / 32);
          ctx.beginPath();
          ctx.moveTo(19, 2);
          ctx.lineTo(8, 17);
          ctx.lineTo(15, 17);
          ctx.lineTo(13, 30);
          ctx.lineTo(26, 13);
          ctx.lineTo(18, 13);
          ctx.closePath();
          
          ctx.strokeStyle = '#000000';
          ctx.lineWidth = 3;
          ctx.lineJoin = 'round';
          ctx.stroke();
          
          ctx.fillStyle = '#facc15';
          ctx.fill();
          ctx.restore();

          const imageData = ctx.getImageData(0, 0, size, size);
          map.addImage('bolt-icon', imageData, { pixelRatio: 2 });
        };
        addBoltImage();
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
          `${layerId}-vector-points`,
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
        /-point-circle|-unclustered-points|-vector-points|-polygon-fill|-line|-cluster-circles/g,
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

    // Mouse hover tooltip listeners
    map.on('mousemove', (e) => {
      if (measurePointsRef.current.modeActive) return;

      const activeIds = [];
      loadedLayersRef.current.forEach((_, layerId) => {
        [
          `${layerId}-vector-points`,
          `${layerId}-point-circle`,
          `${layerId}-unclustered-points`,
          `${layerId}-polygon-fill`,
          `${layerId}-line`
        ].forEach((subId) => {
          if (map.getLayer(subId)) activeIds.push(subId);
        });
      });

      if (activeIds.length === 0) return;

      const features = map.queryRenderedFeatures(e.point, { layers: activeIds });

      if (!features || features.length === 0) {
        map.getCanvas().style.cursor = '';
        if (hoverPopupRef.current) {
          hoverPopupRef.current.remove();
          hoverPopupRef.current = null;
        }
        return;
      }

      map.getCanvas().style.cursor = 'pointer';

      const top = features[0];
      const props = top.properties || {};
      const layerId = top.layer.id.replace(
        /-point-circle|-unclustered-points|-vector-points|-polygon-fill|-line/g,
        ''
      );

      const primaryName =
        props.village_name ||
        props.name ||
        props.NAME ||
        props.city_name ||
        props.district_name ||
        props.state_name ||
        'Feature';

      const secondaryDetail =
        props.state_code ? `State Code: ${props.state_code}` :
        props.type ? `Type: ${props.type}` :
        props.feature_code ? `Code: ${props.feature_code}` : '';

      const tooltipContent = `
        <div style="font-family: ui-sans-serif, system-ui, sans-serif; font-size: 11px; padding: 2px 4px; pointer-events: none;">
          <div style="font-weight: 700; color: #38bdf8; text-transform: uppercase; font-size: 9px; letter-spacing: 0.05em;">
            ${layerId}
          </div>
          <div style="font-weight: 600; color: #f8fafc; font-size: 12px; margin-top: 2px;">
            ${primaryName}
          </div>
          ${
            secondaryDetail
              ? `<div style="color: #94a3b8; font-size: 10px; margin-top: 1px;">${secondaryDetail}</div>`
              : ''
          }
        </div>
      `;

      if (!hoverPopupRef.current) {
        hoverPopupRef.current = new maplibregl.Popup({
          closeButton: false,
          closeOnClick: false,
          className: 'geoagent-map-hover-tooltip',
          offset: 12
        });
      }

      hoverPopupRef.current
        .setLngLat(e.lngLat)
        .setHTML(tooltipContent)
        .addTo(map);
    });

    map.on('mouseleave', () => {
      map.getCanvas().style.cursor = '';
      if (hoverPopupRef.current) {
        hoverPopupRef.current.remove();
        hoverPopupRef.current = null;
      }
    });

    return () => {
      if (popupRef.current) popupRef.current.remove();
      if (hoverPopupRef.current) hoverPopupRef.current.remove();
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
            `${id}-collection-lines`,
            `${id}-collection-points`,
            `${id}-point-circle`, `${id}-point-icon`,
            `${id}-vector-points`,
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
        const useVectorTiles = VECTOR_TILE_LAYERS.has(layerId.toLowerCase()) || layer.format === 'mvt';

        // Check if layer is already loaded in ref or already mounted on map
        if (!loadedLayersRef.current.has(layerId) && !map.getSource(layerId)) {
          try {
            if (useVectorTiles) {
              const tileUrl = `${window.location.origin}/api/layers/tiles/${layerId}/{z}/{x}/{y}.pbf`;

                if (!map.getSource(layerId)) {
                  map.addSource(layerId, {
                    type: 'vector',
                    tiles: [tileUrl],
                    minzoom: 0,
                    maxzoom: 16
                  });
                }

              const isLineLayer = geomType === 'LINESTRING' || geomType === 'MULTILINESTRING' || layerId.includes('feeder');
              const isVillageLayer = layerId.toLowerCase().includes('village');

              if (isLineLayer) {
                const vectorLineId = `${layerId}-vector-line`;
                if (!map.getLayer(vectorLineId)) {
                  map.addLayer({
                    id: vectorLineId,
                    type: 'line',
                    source: layerId,
                    'source-layer': layerId,
                    minzoom: 1,
                    layout: {
                      visibility: isHidden ? 'none' : 'visible',
                      'line-join': 'round',
                      'line-cap': 'round'
                    },
                    paint: {
                      'line-width': [
                        'interpolate', ['linear'], ['zoom'],
                        3, 1.0,
                        8, 1.8,
                        13, 3.2
                      ],
                      'line-color': [
                        'step',
                        ['coalesce', ['get', 'voltage_kv'], 33],
                        '#10b981',        // < 33 kV (Green)
                        33, '#06b6d4',    // 33 kV (Cyan)
                        66, '#3b82f6',    // 66 kV (Blue)
                        132, '#8b5cf6',   // 132 kV (Violet)
                        220, '#f59e0b',   // 220 kV (Amber)
                        400, '#ef4444',   // 400 kV (Red)
                        765, '#ec4899'    // 765 kV+ (Pink)
                      ],
                      'line-opacity': alpha
                    }
                  });
                }
              } else {
                const vectorLayerId = `${layerId}-vector-points`;
                if (!map.getLayer(vectorLayerId)) {
                  map.addLayer({
                    id: vectorLayerId,
                    type: 'circle',
                    source: layerId,
                    'source-layer': layerId,
                    minzoom: 1,
                    layout: { visibility: isHidden ? 'none' : 'visible' },
                    paint: {
                      'circle-radius': isVillageLayer
                        ? [
                            'interpolate',
                            ['linear'],
                            ['zoom'],
                            1, 0.5,
                            4, 0.8,
                            7, 1.8,
                            11, 3.5,
                            14, 6
                          ]
                        : [
                            'interpolate',
                            ['linear'],
                            ['zoom'],
                            2, 4.5,
                            6, 6.5,
                            10, 9
                          ],
                      'circle-color': color.fill,
                      'circle-stroke-width': 1,
                      'circle-stroke-color': color.stroke,
                      'circle-opacity': alpha
                    }
                  });
                }
              }
              loadedLayersRef.current.set(layerId, { isVector: true, geomType, color });
            } else {
              // Load as Standard GeoJSON for analytical outputs
              const res = await fetch(`/api/layers/${layerId}/geojson`);
              if (!res.ok) continue;
              const data = await res.json();

              // Inspect feature types in dataset
              const featureTypes = new Set(
                (data.features || []).map(f => f.geometry?.type).filter(Boolean)
              );
              let activeGeom = geomType;
              if (featureTypes.has('LineString') && featureTypes.has('Point')) {
                activeGeom = 'GEOMETRYCOLLECTION';
              } else if (featureTypes.has('LineString') || featureTypes.has('MultiLineString')) {
                if (!featureTypes.has('Polygon') && !featureTypes.has('MultiPolygon')) {
                  activeGeom = 'LINESTRING';
                }
              }

              if (!map.getSource(layerId)) {
                const isTraceLayer = layerId.toLowerCase().includes('trace_') || layerId.toLowerCase().includes('downstream_');
                map.addSource(layerId, {
                  type: 'geojson',
                  data,
                  cluster: isPoint && activeGeom !== 'GEOMETRYCOLLECTION' && !isTraceLayer,
                  clusterRadius: 50,
                  clusterMaxZoom: 14
                });
              }

                if (activeGeom === 'POINT' || (isPoint && activeGeom !== 'GEOMETRYCOLLECTION')) {
                  const isSubstationMaster = layerId.toLowerCase().includes('substation') || layerId.toLowerCase().includes('trace_');
                  const isSwitchgearMaster = layerId.toLowerCase().includes('switchgear');

                  const circleColorExpr = isSubstationMaster
                    ? [
                        'match',
                        ['coalesce', ['get', 'tier'], ''],
                        'GSS', '#e11d48',
                        'PSS', '#f59e0b',
                        'DSS', '#10b981',
                        'Consumer', '#0ea5e9',
                        color.fill
                      ]
                    : isSwitchgearMaster
                    ? [
                        'match',
                        ['coalesce', ['get', 'status'], ''],
                        'CLOSED', '#10b981',
                        'OPEN', '#ef4444',
                        'TRIPPED', '#f97316',
                        color.fill
                      ]
                    : color.fill;

                  const circleRadiusExpr = isSubstationMaster
                    ? [
                        'match',
                        ['coalesce', ['get', 'tier'], ''],
                        'GSS', 9,
                        'PSS', 7,
                        'DSS', 5,
                        'Consumer', 3.5,
                        8
                      ]
                    : isSwitchgearMaster
                    ? 5.5
                    : 8;

                if (!map.getLayer(`${layerId}-point-circle`)) {
                  map.addLayer({
                    id: `${layerId}-point-circle`,
                    type: 'circle',
                    source: layerId,
                    filter: ['!', ['has', 'point_count']],
                    layout: { visibility: !isHidden && mode === 'points' ? 'visible' : 'none' },
                    paint: {
                      'circle-radius': circleRadiusExpr,
                      'circle-color': circleColorExpr,
                      'circle-stroke-width': 2,
                      'circle-stroke-color': '#ffffff',
                      'circle-opacity': alpha
                    }
                  });
                }

                                  const isUtilityPoint = isSubstationMaster || isSwitchgearMaster || layerId.toLowerCase().includes('utility') || layerId.toLowerCase().includes('pss') || layerId.toLowerCase().includes('gss') || layerId.toLowerCase().includes('generation') || layerId.toLowerCase().includes('wb_33kv');
                  if (isUtilityPoint && !map.getLayer(`${layerId}-point-icon`)) {
                    map.addLayer({
                      id: `${layerId}-point-icon`,
                      type: 'symbol',
                      source: layerId,
                      filter: ['!', ['has', 'point_count']],
                      layout: {
                        visibility: !isHidden && mode === 'points' ? 'visible' : 'none',
                        'icon-image': 'bolt-icon',
                        'icon-size': 0.7,
                        'icon-allow-overlap': true,
                        'icon-ignore-placement': true
                      }
                    });
                  }

                  if (!map.getLayer(`${layerId}-heatmap`)) {
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
                }

                if (!map.getLayer(`${layerId}-cluster-circles`)) {
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
                }

                if (!map.getLayer(`${layerId}-cluster-counts`)) {
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
                }

                if (!map.getLayer(`${layerId}-unclustered-points`)) {
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
                }
              } else if (activeGeom === 'LINESTRING' || activeGeom === 'MULTILINESTRING') {
                const isFeederMaster = layerId.toLowerCase().includes('feeder');

                const lineColorExpr = isFeederMaster
                  ? [
                      'match',
                      ['coalesce', ['get', 'feeder_type'], ''],
                      'INTER_STATE_TRUNK', '#a855f7',
                      'SUB_TRANSMISSION', '#f59e0b',
                      'PRIMARY_DISTRIBUTION', '#06b6d4',
                      color.stroke
                    ]
                  : [
                      'match',
                      ['coalesce', ['get', 'impact_status'], ''],
                      'SEVERED_TRANSMISSION', '#ff3344',
                      'FAILED_CORRIDOR', '#ff3344',
                      color.stroke
                    ];

                const lineWidthExpr = isFeederMaster
                  ? [
                      'match',
                      ['coalesce', ['get', 'feeder_type'], ''],
                      'INTER_STATE_TRUNK', 4,
                      'SUB_TRANSMISSION', 2.5,
                      'PRIMARY_DISTRIBUTION', 1.5,
                      3
                    ]
                  : 3.5;

                if (!map.getLayer(`${layerId}-line`)) {
                  map.addLayer({
                    id: `${layerId}-line`,
                    type: 'line',
                    source: layerId,
                    layout: { visibility: isHidden ? 'none' : 'visible' },
                    paint: {
                      'line-color': lineColorExpr,
                      'line-width': lineWidthExpr,
                      'line-opacity': alpha
                    }
                  });
                }
              } else if (activeGeom === 'GEOMETRYCOLLECTION' || activeGeom === 'GEOMETRY') {
                if (!map.getLayer(`${layerId}-collection-lines`)) {
                  map.addLayer({
                    id: `${layerId}-collection-lines`,
                    type: 'line',
                    source: layerId,
                    filter: ['==', '$type', 'LineString'],
                    layout: { visibility: isHidden ? 'none' : 'visible' },
                    paint: {
                      'line-color': [
                        'match',
                        ['coalesce', ['get', 'tier'], ''],
                        'Incoming Feeder', '#f59e0b',
                        'Outgoing Feeder', '#06b6d4',
                        'Conductor Span', '#94a3b8',
                        'Connector Drop', '#10b981',
                        '#38bdf8'
                      ],
                      'line-width': [
                        'match',
                        ['coalesce', ['get', 'tier'], ''],
                        'Incoming Feeder', 4.0,
                        'Outgoing Feeder', 3.0,
                        'Conductor Span', 2.0,
                        'Connector Drop', 1.5,
                        2.5
                      ],
                      'line-dasharray': [
                        'match',
                        ['coalesce', ['get', 'tier'], ''],
                        'Connector Drop', ['literal', [2, 2]],
                        ['literal', [1]]
                      ],
                      'line-opacity': alpha
                    }
                  });
                }

                if (!map.getLayer(`${layerId}-collection-points`)) {
                  map.addLayer({
                    id: `${layerId}-collection-points`,
                    type: 'circle',
                    source: layerId,
                    filter: ['==', '$type', 'Point'],
                    layout: { visibility: isHidden ? 'none' : 'visible' },
                    paint: {
                      'circle-radius': [
                        'match',
                        ['coalesce', ['get', 'tier'], ''],
                        'PSS', 8,
                        'DSS', 6,
                        'Pole', 3.5,
                        'Consumer', 4,
                        5
                      ],
                      'circle-color': [
                        'match',
                        ['coalesce', ['get', 'tier'], ''],
                        'PSS', '#f59e0b',
                        'DSS', '#10b981',
                        'Pole', '#64748b',
                        'Consumer', '#0ea5e9',
                        '#f59e0b'
                      ],
                      'circle-stroke-width': 1.5,
                      'circle-stroke-color': '#ffffff',
                      'circle-opacity': alpha
                    }
                  });
                }
              } else {
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

                if (!map.getLayer(`${layerId}-polygon-fill`)) {
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
                }

                if (!map.getLayer(`${layerId}-polygon-stroke`)) {
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
              }

              loadedLayersRef.current.set(layerId, { isVector: false, geojson: data, geomType, color });

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
            }
          } catch (err) {
            console.error(`Failed to load layer ${layerId}:`, err);
          }
        } else {
          const existing = loadedLayersRef.current.get(layerId);
          if (existing && !existing.isVector && existing.geomType !== 'POINT' && !isHidden) {
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
      const useVectorTiles = VECTOR_TILE_LAYERS.has(layerId.toLowerCase()) || layer.format === 'mvt';

      if (useVectorTiles) {
        const vectorPointId = `${layerId}-vector-points`;
        const vectorLineId = `${layerId}-vector-line`;
        if (map.getLayer(vectorPointId)) {
          map.setLayoutProperty(vectorPointId, 'visibility', isHidden ? 'none' : 'visible');
          if (!isHidden) {
            map.setPaintProperty(vectorPointId, 'circle-opacity', alpha);
          }
        }
        if (map.getLayer(vectorLineId)) {
          map.setLayoutProperty(vectorLineId, 'visibility', isHidden ? 'none' : 'visible');
          if (!isHidden) {
            map.setPaintProperty(vectorLineId, 'line-opacity', alpha);
          }
        }
      } else if (isPoint) {
        const showPoints = !isHidden && mode === 'points';
        const showClusters = !isHidden && mode === 'clusters';
        const showHeatmap = !isHidden && mode === 'heatmap';

                  if (map.getLayer(`${layerId}-point-icon`)) {
            map.setLayoutProperty(`${layerId}-point-icon`, 'visibility', showPoints ? 'visible' : 'none');
          }
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
          ? `${areaKm2.toFixed(2)} kmÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â²`
          : `${(areaKm2 * 1000000).toLocaleString(undefined, { maximumFractionDigits: 0 })} mÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â²`
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
        .geoagent-map-hover-tooltip .maplibregl-popup-content {
          background-color: rgba(15, 23, 42, 0.92) !important;
          border: 1px solid #334155 !important;
          border-radius: 6px !important;
          padding: 6px 10px !important;
          box-shadow: 0 4px 15px rgba(0, 0, 0, 0.5) !important;
          pointer-events: none !important;
        }
        .geoagent-map-hover-tooltip .maplibregl-popup-tip {
          border-top-color: rgba(15, 23, 42, 0.92) !important;
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