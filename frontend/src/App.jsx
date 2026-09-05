import React, { useState, useEffect } from 'react';
import MapViewer from './components/MapViewer';
import ChatInterface from './components/ChatInterface';
import LayerCatalog from './components/LayerCatalog';

export default function App() {
  const [layers, setLayers] = useState([]);
  const [hiddenLayers, setHiddenLayers] = useState(new Set());
  const [opacities, setOpacities] = useState({});
  const [zoomLayerId, setZoomLayerId] = useState(null);
  const [viewportBbox, setViewportBbox] = useState(null);

  useEffect(() => {
    fetch('/api/layers')
      .then((res) => res.json())
      .then((data) => {
        if (Array.isArray(data)) {
          setLayers(data);
          const initialOpacities = {};
          data.forEach((l) => {
            initialOpacities[l.layer_id] = 0.75;
          });
          setOpacities(initialOpacities);
        }
      })
      .catch((err) => console.error('Failed to fetch layers:', err));
  }, []);

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

  const handleZoomToLayer = (layerId) => {
    setZoomLayerId(null);
    setTimeout(() => {
      setZoomLayerId(layerId);
    }, 10);
  };

  const handleExportLayer = async (layerId, layerName) => {
    try {
      const res = await fetch(`/api/layers/${layerId}/geojson`);
      if (!res.ok) throw new Error('Failed to fetch layer GeoJSON');
      const data = await res.json();

      const blob = new Blob([JSON.stringify(data, null, 2)], {
        type: 'application/geo+json'
      });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `${layerName || layerId}.geojson`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
    } catch (err) {
      console.error(`Export failed for layer ${layerId}:`, err);
    }
  };

  return (
    <div style={{ display: 'flex', width: '100vw', height: '100vh', overflow: 'hidden', backgroundColor: '#020617' }}>
      {/* Left Chat & Execution Console */}
      <div style={{ width: '420px', minWidth: '420px', height: '100%', zIndex: 10 }}>
        <ChatInterface
          onNewLayerDiscovered={handleNewLayer}
          onLayerDeleted={handleDeleteLayer}
          viewportBbox={viewportBbox}
        />
      </div>

      {/* Right Map Canvas Container */}
      <div style={{ flex: 1, height: '100%', position: 'relative', overflow: 'hidden' }}>
        <MapViewer 
          layers={layers} 
          hiddenLayers={hiddenLayers} 
          opacities={opacities}
          zoomLayerId={zoomLayerId}
          onViewportChange={setViewportBbox} 
        />
        <LayerCatalog 
          layers={layers} 
          hiddenLayers={hiddenLayers} 
          opacities={opacities}
          onToggleVisibility={handleToggleVisibility} 
          onOpacityChange={handleOpacityChange}
          onZoomToLayer={handleZoomToLayer}
          onExportLayer={handleExportLayer}
        />
      </div>
    </div>
  );
}