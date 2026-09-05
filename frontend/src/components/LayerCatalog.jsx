import React, { useState } from 'react';
import { Layers, Eye, EyeOff, MapPin, Square, AlertCircle, Sliders, Focus, Download, ChevronDown } from 'lucide-react';

export default function LayerCatalog({
  layers = [],
  hiddenLayers = new Set(),
  opacities = {},
  onToggleVisibility,
  onOpacityChange,
  onZoomToLayer,
  onExportLayer
}) {
  const [activeExportMenu, setActiveExportMenu] = useState(null);

  const getGeomIcon = (geomType) => {
    switch (geomType?.toUpperCase()) {
      case 'POINT':
      case 'MULTIPOINT':
        return <MapPin className="w-3.5 h-3.5 text-sky-400" />;
      case 'POLYGON':
      case 'MULTIPOLYGON':
        return <AlertCircle className="w-3.5 h-3.5 text-rose-400" />;
      default:
        return <Square className="w-3.5 h-3.5 text-indigo-400" />;
    }
  };

  const handleExportSelect = (layerId, layerName, format) => {
    if (onExportLayer) {
      onExportLayer(layerId, layerName, format);
    }
    setActiveExportMenu(null);
  };

  return (
    <div className="absolute top-4 right-14 w-80 max-h-[calc(100vh-2rem)] bg-slate-900/90 backdrop-blur-md border border-slate-800 rounded-lg shadow-xl flex flex-col z-20 overflow-visible">
      {/* Header */}
      <div className="p-3 border-b border-slate-800 flex items-center justify-between text-xs font-semibold text-slate-300 tracking-wider uppercase">
        <div className="flex items-center space-x-2">
          <Layers className="w-4 h-4 text-indigo-400" />
          <span>Active Map Layers ({layers.length})</span>
        </div>
      </div>

      {/* Layer List */}
      <div className="flex-1 overflow-y-auto p-2 space-y-2">
        {layers.length === 0 ? (
          <div className="text-center py-6 text-xs text-slate-500">
            No active spatial layers
          </div>
        ) : (
          layers.map((layer) => {
            const isHidden = hiddenLayers.has(layer.layer_id);
            const currentOpacity = opacities[layer.layer_id] ?? 0.75;
            const isMenuOpen = activeExportMenu === layer.layer_id;

            return (
              <div
                key={layer.layer_id}
                className={`p-2.5 rounded transition border relative ${
                  isHidden
                    ? 'bg-slate-950/40 border-slate-900 opacity-60'
                    : 'bg-slate-950/80 border-slate-800/80 hover:border-slate-700'
                }`}
              >
                {/* Top row: Icon, title, feature info, actions */}
                <div className="flex items-center justify-between">
                  <div className="flex items-start space-x-2.5 overflow-hidden">
                    <div className="mt-0.5 shrink-0">
                      {getGeomIcon(layer.geom_type)}
                    </div>
                    <div className="overflow-hidden">
                      <p className="text-xs font-medium text-slate-200 truncate">
                        {layer.name || layer.layer_id}
                      </p>
                      <p className="text-[10px] text-slate-400">
                        {layer.feature_count} features • {layer.geom_type}
                      </p>
                    </div>
                  </div>

                  {/* Actions: Export Dropdown, Zoom to layer, Visibility toggle */}
                  <div className="flex items-center space-x-1 ml-2 shrink-0 relative">
                    <div className="relative">
                      <button
                        type="button"
                        onClick={() => setActiveExportMenu(isMenuOpen ? null : layer.layer_id)}
                        className={`p-1.5 rounded transition flex items-center space-x-0.5 ${
                          isMenuOpen
                            ? 'text-emerald-300 bg-slate-800'
                            : 'text-slate-400 hover:text-emerald-300 hover:bg-slate-800'
                        }`}
                        title="Export Layer"
                      >
                        <Download className="w-3.5 h-3.5" />
                        <ChevronDown className="w-2.5 h-2.5" />
                      </button>

                      {/* Export Format Popover */}
                      {isMenuOpen && (
                        <div className="absolute right-0 top-full mt-1 w-32 bg-slate-900 border border-slate-700 rounded shadow-xl py-1 z-30">
                          <button
                            type="button"
                            onClick={() => handleExportSelect(layer.layer_id, layer.name, 'geojson')}
                            className="w-full text-left px-3 py-1.5 text-[11px] text-slate-300 hover:bg-slate-800 hover:text-emerald-400 transition"
                          >
                            GeoJSON (.geojson)
                          </button>
                          <button
                            type="button"
                            onClick={() => handleExportSelect(layer.layer_id, layer.name, 'csv')}
                            className="w-full text-left px-3 py-1.5 text-[11px] text-slate-300 hover:bg-slate-800 hover:text-emerald-400 transition"
                          >
                            CSV with WKT (.csv)
                          </button>
                          <button
                            type="button"
                            onClick={() => handleExportSelect(layer.layer_id, layer.name, 'shapefile')}
                            className="w-full text-left px-3 py-1.5 text-[11px] text-slate-300 hover:bg-slate-800 hover:text-emerald-400 transition"
                          >
                            Shapefile (.zip)
                          </button>
                        </div>
                      )}
                    </div>

                    <button
                      type="button"
                      onClick={() => onZoomToLayer && onZoomToLayer(layer.layer_id)}
                      className="p-1.5 rounded transition text-slate-400 hover:text-sky-300 hover:bg-slate-800"
                      title="Fit map to layer bounds"
                    >
                      <Focus className="w-3.5 h-3.5" />
                    </button>
                    <button
                      type="button"
                      onClick={() => onToggleVisibility && onToggleVisibility(layer.layer_id)}
                      className={`p-1.5 rounded transition ${
                        isHidden
                          ? 'text-slate-500 hover:text-slate-300 hover:bg-slate-800'
                          : 'text-emerald-400 hover:text-emerald-300 hover:bg-slate-800'
                      }`}
                      title={isHidden ? 'Show layer' : 'Hide layer'}
                    >
                      {isHidden ? (
                        <EyeOff className="w-3.5 h-3.5" />
                      ) : (
                        <Eye className="w-3.5 h-3.5" />
                      )}
                    </button>
                  </div>
                </div>

                {/* Bottom row: Opacity Slider */}
                {!isHidden && (
                  <div className="mt-2.5 pt-2 border-t border-slate-800/60 flex items-center space-x-2">
                    <Sliders className="w-3 h-3 text-slate-500 shrink-0" />
                    <input
                      type="range"
                      min="0.05"
                      max="1"
                      step="0.05"
                      value={currentOpacity}
                      onChange={(e) =>
                        onOpacityChange && onOpacityChange(layer.layer_id, e.target.value)
                      }
                      className="w-full h-1 bg-slate-800 rounded-lg appearance-none cursor-pointer accent-indigo-500"
                    />
                    <span className="text-[10px] text-slate-400 w-7 text-right font-mono">
                      {Math.round(currentOpacity * 100)}%
                    </span>
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}