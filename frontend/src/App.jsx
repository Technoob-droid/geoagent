import React, { useState, useEffect } from 'react';
import MapViewer from './components/MapViewer';
import ChatInterface from './components/ChatInterface';
import LayerCatalog from './components/LayerCatalog';

export default function App() {
  const [layers, setLayers] = useState([]);
  const [hiddenLayers, setHiddenLayers] = useState(new Set());
  const [opacities, setOpacities] = useState({});
  const [displayModes, setDisplayModes] = useState({}); // { [layerId]: 'points' | 'clusters' | 'heatmap' }
  const [zoomLayerId, setZoomLayerId] = useState(null);
  const [viewportBbox, setViewportBbox] = useState(null);

  useEffect(() => {
    fetch('/api/layers')
      .then((res) => res.json())
      .then((data) => {
        if (Array.isArray(data)) {
          setLayers(data);
          const initialOpacities = {};
          const initialModes = {};
          data.forEach((l) => {
            initialOpacities[l.layer_id] = 0.75;
            initialModes[l.layer_id] = 'points';
          });
          setOpacities(initialOpacities);
          setDisplayModes(initialModes);
        }
      })
      .catch((err) => console.error('Failed to fetch layers:', err));
  }, []);

const handleClearChat = async () => {
    try {
      // 1. Purge analytical layers on the backend DuckDB instance
      await fetch('/api/layers/purge', { method: 'DELETE' });

      // 2. Fetch the remaining base catalog layers rather than zeroing out state
      const res = await fetch('/api/layers');
      const remainingLayers = await res.json();

      if (Array.isArray(remainingLayers)) {
        setLayers(remainingLayers);

        const retainedOpacities = {};
        const retainedModes = {};
        remainingLayers.forEach((l) => {
          retainedOpacities[l.layer_id] = opacities[l.layer_id] ?? 0.75;
          retainedModes[l.layer_id] = displayModes[l.layer_id] ?? 'points';
        });

        setOpacities(retainedOpacities);
        setDisplayModes(retainedModes);

        // Retain hidden states only for existing layers
        setHiddenLayers((prev) => {
          const next = new Set();
          remainingLayers.forEach((l) => {
            if (prev.has(l.layer_id)) next.add(l.layer_id);
          });
          return next;
        });
      }
    } catch (err) {
      console.error('Failed to clear analytical layers:', err);
    }
  };

  const handleNewLayer = (newLayer) => {
    setLayers((prev) => {
      const exists = prev.some((l) => l.layer_id === newLayer.layer_id);
      if (exists) return prev;
      return [...prev, newLayer];
    });
    setOpacities((prev) => ({
      ...prev,
      [newLayer.layer_id]: 0.75
    }));
    setDisplayModes((prev) => ({
      ...prev,
      [newLayer.layer_id]: 'points'
    }));
  };

  const handleDeleteLayer = (layerId) => {
    setLayers((prev) => prev.filter((l) => l.layer_id !== layerId));
    setHiddenLayers((prev) => {
      const next = new Set(prev);
      next.delete(layerId);
      return next;
    });
    setOpacities((prev) => {
      const next = { ...prev };
      delete next[layerId];
      return next;
    });
    setDisplayModes((prev) => {
      const next = { ...prev };
      delete next[layerId];
      return next;
    });
  };

  const handleToggleVisibility = (layerId) => {
    setHiddenLayers((prev) => {
      const next = new Set(prev);
      if (next.has(layerId)) {
        next.delete(layerId);
      } else {
        next.add(layerId);
      }
      return next;
    });
  };

  const handleOpacityChange = (layerId, value) => {
    setOpacities((prev) => ({
      ...prev,
      [layerId]: parseFloat(value)
    }));
  };

  const handleDisplayModeChange = (layerId, mode) => {
    setDisplayModes((prev) => ({
      ...prev,
      [layerId]: mode
    }));
  };

  const handleZoomToLayer = (layerId) => {
    setZoomLayerId(null);
    setTimeout(() => {
      setZoomLayerId(layerId);
    }, 10);
  };

  const handleExportLayer = async (layerId, layerName, format = 'geojson') => {
    try {
      const cleanName = layerName || layerId;
      let url = '';
      let defaultFilename = '';

      if (format === 'geojson') {
        url = `/api/layers/${layerId}/geojson`;
        defaultFilename = `${cleanName}.geojson`;
      } else if (format === 'csv') {
        url = `/api/layers/${layerId}/export/csv`;
        defaultFilename = `${cleanName}.csv`;
      } else if (format === 'shapefile') {
        url = `/api/layers/${layerId}/export/shapefile`;
        defaultFilename = `${cleanName}_shp.zip`;
      }

      const res = await fetch(url);
      if (!res.ok) throw new Error(`Export failed with status: ${res.status}`);

      let blob;
      if (format === 'geojson') {
        const data = await res.json();
        blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/geo+json' });
      } else {
        blob = await res.blob();
      }

      const downloadUrl = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = downloadUrl;
      link.download = defaultFilename;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(downloadUrl);
    } catch (err) {
      console.error(`Export (${format}) failed for layer ${layerId}:`, err);
    }
  };


  const handleLoadHierarchy = async (tier) => {
    try {
      const res = await fetch(`/api/hierarchy/TPWODL?level=${tier}`);
      const data = await res.json();
      if (data && data.layer_id) {
        setLayers((prev) => {
          const exists = prev.some((l) => l.layer_id === data.layer_id);
          if (exists) return prev;
          return [...prev, data];
        });
        setOpacities((prev) => ({ ...prev, [data.layer_id]: 0.8 }));
        setDisplayModes((prev) => ({ ...prev, [data.layer_id]: 'points' }));
        if (data.layer_id) {
          setZoomLayerId(data.layer_id);
        }
      }
    } catch (err) {
      console.error('Failed to load hierarchy tier:', err);
    }
  };

  const handleRunTrace = async (substationOrDistrict) => {
    try {
      let target = substationOrDistrict?.trim() || 'Sambalpur';
      // If user selected from dropdown format: "Substation-150791254 (PSS_150791254)"
      const match = target.match(/\(([^)]+)\)/);
      if (match) {
        target = match[1]; // Extracts "PSS_150791254"
      }
      const queryParam = `substation_id=${encodeURIComponent(target)}&district_name=Sambalpur`;
      const res = await fetch(`/api/hierarchy/TPWODL/trace/downstream?${queryParam}`);
      const data = await res.json();
      if (data && data.status === 'success' && data.topology) {
        // Materialize downstream trace GeoJSON into a dedicated analytical layer
        const traceGeoJson = {
          type: 'FeatureCollection',
          features: []
        };

        // Root PSS
        if (data.root_substation && data.root_substation.coordinates) {
          traceGeoJson.features.push({
            type: 'Feature',
            geometry: {
              type: 'Point',
              coordinates: data.root_substation.coordinates
            },
            properties: {
              name: data.root_substation.substation_name,
              tier: 'PSS',
              type: 'Primary Substation'
            }
          });
        }

        // DSS & Consumers
        data.topology.forEach((feeder) => {
          if (feeder.dss_coordinates) {
            traceGeoJson.features.push({
              type: 'Feature',
              geometry: {
                type: 'Point',
                coordinates: feeder.dss_coordinates
              },
              properties: {
                name: feeder.dss_id,
                parent_feeder: feeder.feeder_name,
                tier: 'DSS',
                type: 'Distribution Substation'
              }
            });
          }
          (feeder.consumers || []).forEach((c) => {
            if (c.coordinates) {
              traceGeoJson.features.push({
                type: 'Feature',
                geometry: {
                  type: 'Point',
                  coordinates: c.coordinates
                },
                properties: {
                  name: c.village_name,
                  distance_km: c.distance_km,
                  tier: 'Consumer',
                  type: 'Energized Consumer Node'
                }
              });
            }
          });
        });

        const traceLayerId = data.layer_id || `trace_tpwodl_${Date.now()}`;
        const newLayer = {
          layer_id: traceLayerId,
          name: `Trace: ${data.root_substation?.substation_name || 'Substation'}`,
          geom_type: 'POINT',
          format: 'geojson',
          data: `/api/layers/${traceLayerId}/geojson`,
          feature_count: data.consumer_count ? (data.consumer_count + (data.feeder_count || 0) + 1) : traceGeoJson.features.length
        };

        setLayers((prev) => {
          // Clear any prior trace layers to avoid stale 404 requests
          const filtered = prev.filter(l => !l.layer_id.startsWith('downstream_trace_') && !l.layer_id.startsWith('trace_'));
          return [...filtered, newLayer];
        });
        setOpacities((prev) => ({ ...prev, [traceLayerId]: 1.0 }));
        setDisplayModes((prev) => ({ ...prev, [traceLayerId]: 'points' }));
        setZoomLayerId(traceLayerId);
      }
    } catch (err) {
      console.error('Failed to run downstream trace:', err);
    }
  };

  return (
    <div style={{ display: 'flex', width: '100vw', height: '100vh', overflow: 'hidden', backgroundColor: '#020617' }}>
      {/* Left Chat & Execution Console */}
      <div style={{ width: '420px', minWidth: '420px', height: '100%', zIndex: 10 }}>
        <ChatInterface
          onNewLayerDiscovered={handleNewLayer}
          onLayerDeleted={handleDeleteLayer}
          onClearChat={handleClearChat}
          viewportBbox={viewportBbox}
        />
      </div>

      {/* Right Map Canvas Container */}
      <div style={{ flex: 1, height: '100%', position: 'relative', overflow: 'hidden' }}>
        <MapViewer 
          layers={layers} 
          hiddenLayers={hiddenLayers} 
          opacities={opacities}
          displayModes={displayModes}
          zoomLayerId={zoomLayerId}
          onViewportChange={setViewportBbox} 
        />
        <LayerCatalog 
          layers={layers} 
          hiddenLayers={hiddenLayers} 
          opacities={opacities}
          displayModes={displayModes}
          onToggleVisibility={handleToggleVisibility} 
          onOpacityChange={handleOpacityChange}
          onDisplayModeChange={handleDisplayModeChange}
          onZoomToLayer={handleZoomToLayer}
          onExportLayer={handleExportLayer}
          onLoadHierarchy={handleLoadHierarchy}
          onRunTrace={handleRunTrace}
        />
      </div>
    </div>
  );
}