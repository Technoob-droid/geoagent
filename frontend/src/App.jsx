import React, { useState, useEffect } from 'react';
import MapViewer from './components/MapViewer';
import ChatInterface from './components/ChatInterface';
import LayerCatalog from './components/LayerCatalog';

export default function App() {
  const [layers, setLayers] = useState([]);
  const [hiddenLayers, setHiddenLayers] = useState(new Set());
  const [viewportBbox, setViewportBbox] = useState(null);

  useEffect(() => {
    fetch('/api/layers')
      .then((res) => res.json())
      .then((data) => {
        if (Array.isArray(data)) {
          setLayers(data);
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
  };

  const handleDeleteLayer = (layerId) => {
    setLayers((prev) => prev.filter((l) => l.layer_id !== layerId));
    setHiddenLayers((prev) => {
      const next = new Set(prev);
      next.delete(layerId);
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
          onViewportChange={setViewportBbox} 
        />
        <LayerCatalog 
          layers={layers} 
          hiddenLayers={hiddenLayers} 
          onToggleVisibility={handleToggleVisibility} 
        />
      </div>
    </div>
  );
}