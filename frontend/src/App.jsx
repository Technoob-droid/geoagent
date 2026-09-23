import React, { useState, useEffect } from 'react';
import MapViewer from './components/MapViewer';
import ChatInterface from './components/ChatInterface';
import LayerCatalog from './components/LayerCatalog';

export default function App() {
  const [layers, setLayers] = useState([]);
  const [selectedDiscom, setSelectedDiscom] = useState('TPWODL');
  const [traceSummary, setTraceSummary] = useState(null);
  const [hiddenLayers, setHiddenLayers] = useState(new Set());
  const [opacities, setOpacities] = useState({});
  const [displayModes, setDisplayModes] = useState({}); // { [layerId]: 'points' | 'clusters' | 'heatmap' }
  const [zoomLayerId, setZoomLayerId] = useState(null);
  const [viewportBbox, setViewportBbox] = useState(null);

  useEffect(() => {
    fetch('/api/layers?base_only=true')
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


    const handleClearHierarchy = () => {
    const isHierarchyOrTrace = (id) => {
      const lower = (id || '').toLowerCase();
      return (
        lower.startsWith('tpwodl_') ||
        lower.startsWith('tpnodl_') ||
        lower.startsWith('tpsodl_') ||
        lower.startsWith('tpcedl_') ||
        lower.startsWith('trace_') ||
        lower.startsWith('downstream_') ||
        lower.startsWith('trace:') ||
        (selectedDiscom && lower.startsWith(selectedDiscom.toLowerCase() + '_'))
      );
    };

    // 1. Remove from layers
    setLayers((prev) => prev.filter((l) => !isHierarchyOrTrace(l.layer_id)));

    // 2. Remove from hidden layers set
    setHiddenLayers((prev) => {
      const next = new Set(prev);
      for (const id of next) {
        if (isHierarchyOrTrace(id)) {
          next.delete(id);
        }
      }
      return next;
    });
  };

  const handleLoadHierarchy = async (tier) => {
    try {
      const res = await fetch(`/api/hierarchy/${selectedDiscom}?level=${tier}`);
      const data = await res.json();
      if (data && data.layer_id) {
        // Ensure layer is not hidden
        setHiddenLayers((prev) => {
          const next = new Set(prev);
          next.delete(data.layer_id);
          return next;
        });

        // Add or replace layer in layers list
        setLayers((prev) => {
          const filtered = prev.filter((l) => l.layer_id !== data.layer_id);
          return [...filtered, data];
        });

        setOpacities((prev) => ({ ...prev, [data.layer_id]: 0.8 }));
        setDisplayModes((prev) => ({ ...prev, [data.layer_id]: 'points' }));
        
        // Trigger zoom to freshly loaded tier
        setZoomLayerId(null);
        setTimeout(() => {
          setZoomLayerId(data.layer_id);
        }, 100);
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
      const queryParam = `substation_id=${encodeURIComponent(target)}`;
      const res = await fetch(`/api/hierarchy/${selectedDiscom}/trace/downstream?${queryParam}`);
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

        // DSS, Feeders (LineStrings), and Consumers (LineStrings + Points)
        const pssCoords = data.root_substation?.coordinates;

        data.topology.forEach((feeder) => {
          if (feeder.dss_coordinates) {
            // Feeder Trunk Line: PSS -> DSS
            if (pssCoords) {
              traceGeoJson.features.push({
                type: 'Feature',
                geometry: {
                  type: 'LineString',
                  coordinates: [pssCoords, feeder.dss_coordinates]
                },
                properties: {
                  name: feeder.feeder_name || '11kV Feeder Line',
                  tier: 'Feeder',
                  type: '11kV Feeder Trunk',
                  voltage_kv: 11
                }
              });
            }

            // DSS Point
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
              // Service Drop Line: DSS -> Consumer Settlement
              if (feeder.dss_coordinates) {
                traceGeoJson.features.push({
                  type: 'Feature',
                  geometry: {
                    type: 'LineString',
                    coordinates: [feeder.dss_coordinates, c.coordinates]
                  },
                  properties: {
                    name: `Service Drop: ${c.village_name}`,
                    tier: 'Drop',
                    type: 'LT Service Line',
                    voltage_kv: 0.415
                  }
                });
              }

              // Consumer Node Point
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

        const traceLayerId = data.layer_id || `trace_${selectedDiscom.toLowerCase()}_${Date.now()}`;
        const newLayer = {
          layer_id: traceLayerId,
          name: `Trace: ${data.root_substation?.substation_name || 'Substation'}`,
          geom_type: 'GEOMETRYCOLLECTION',
          format: 'geojson',
          data: `/api/layers/${traceLayerId}/geojson`,
          feature_count: traceGeoJson.features.length
        };

        setLayers((prev) => {
          const filtered = prev.filter(l => !l.layer_id.startsWith('downstream_trace_') && !l.layer_id.startsWith('trace_'));
          return [...filtered, newLayer];
        });
        setOpacities((prev) => ({ ...prev, [traceLayerId]: 1.0 }));
        setDisplayModes((prev) => ({ ...prev, [traceLayerId]: 'all' }));
        setTraceSummary({
          discom: data.discom || selectedDiscom,
          rootSubstation: data.root_substation?.substation_name,
          rootId: data.root_substation?.substation_id,
          feederCount: data.feeder_count || data.topology.length,
          consumerCount: data.consumer_count || 0,
          layerId: traceLayerId
        });

        // Add a trace report message to the chat console
        setMessages((prev) => [
          ...prev,
          {
            role: 'assistant',
            content: `⚡ **Downstream Trace Completed**\n\n` +
              `• **DISCOM**: ${data.discom || selectedDiscom}\n` +
              `• **Root Substation**: ${data.root_substation?.substation_name} (${data.root_substation?.substation_id})\n` +
              `• **Outgoing Feeders**: ${data.feeder_count || data.topology.length}\n` +
              `• **Connected Consumer Settlements**: ${data.consumer_count || 0}\n` +
              `• **Trace Layer**: \`${traceLayerId}\` (High-voltage & Low-voltage spans materialized on map)`
          }
        ]);
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
              {/* Downstream Trace Summary HUD Card */}
      {traceSummary && (
        <div style={{
          position: 'absolute',
          top: '72px',
          left: '380px',
          zIndex: 100,
          background: 'rgba(15, 23, 42, 0.90)',
          backdropFilter: 'blur(12px)',
          border: '1px solid rgba(56, 189, 248, 0.35)',
          borderRadius: '12px',
          padding: '16px 20px',
          color: '#f8fafc',
          boxShadow: '0 8px 32px rgba(0, 0, 0, 0.45)',
          minWidth: '320px',
          maxWidth: '400px'
        }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '12px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <span style={{ fontSize: '18px' }}>⚡</span>
              <span style={{ fontWeight: 700, fontSize: '14px', letterSpacing: '0.05em', color: '#38bdf8', textTransform: 'uppercase' }}>
                Trace: {traceSummary.discom}
              </span>
            </div>
            <button 
              onClick={() => setTraceSummary(null)}
              style={{
                background: 'transparent',
                border: 'none',
                color: '#94a3b8',
                cursor: 'pointer',
                fontSize: '16px',
                lineHeight: 1
              }}
            >×</button>
          </div>

          <div style={{ fontSize: '13px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', borderBottom: '1px solid rgba(255,255,255,0.08)', paddingBottom: '6px' }}>
              <span style={{ color: '#94a3b8' }}>Root PSS</span>
              <span style={{ fontWeight: 600, color: '#f59e0b' }}>{traceSummary.rootSubstation}</span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', borderBottom: '1px solid rgba(255,255,255,0.08)', paddingBottom: '6px' }}>
              <span style={{ color: '#94a3b8' }}>Substation ID</span>
              <span style={{ fontFamily: 'monospace', color: '#cbd5e1' }}>{traceSummary.rootId}</span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', borderBottom: '1px solid rgba(255,255,255,0.08)', paddingBottom: '6px' }}>
              <span style={{ color: '#94a3b8' }}>Outgoing Feeders</span>
              <span style={{ fontWeight: 600, color: '#06b6d4' }}>{traceSummary.feederCount}</span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', borderBottom: '1px solid rgba(255,255,255,0.08)', paddingBottom: '6px' }}>
              <span style={{ color: '#94a3b8' }}>Consumer Settlements</span>
              <span style={{ fontWeight: 600, color: '#10b981' }}>{traceSummary.consumerCount}</span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', paddingTop: '2px' }}>
              <span style={{ color: '#94a3b8' }}>Active Layer</span>
              <span style={{ fontFamily: 'monospace', fontSize: '11px', color: '#94a3b8' }}>{traceSummary.layerId}</span>
            </div>
          </div>
        </div>
      )}

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
          selectedDiscom={selectedDiscom}
          onSelectDiscom={setSelectedDiscom}
          onLoadHierarchy={handleLoadHierarchy}
          onClearHierarchy={handleClearHierarchy}
          onRunTrace={handleRunTrace}
        />
      </div>
    </div>
  );
}