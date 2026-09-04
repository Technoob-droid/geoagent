import React from 'react';
import { Layers, Eye, EyeOff, MapPin, Square, AlertCircle } from 'lucide-react';

export default function LayerCatalog({ layers = [], hiddenLayers = new Set(), onToggleVisibility }) {
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

  return (
    <div className="absolute top-4 right-14 w-80 max-h-[calc(100vh-2rem)] bg-slate-900/90 backdrop-blur-md border border-slate-800 rounded-lg shadow-xl flex flex-col z-20 overflow-hidden">
      {/* Header */}
      <div className="p-3 border-b border-slate-800 flex items-center justify-between text-xs font-semibold text-slate-300 tracking-wider uppercase">
        <div className="flex items-center space-x-2">
          <Layers className="w-4 h-4 text-indigo-400" />
          <span>Active Map Layers ({layers.length})</span>
        </div>
      </div>

      {/* Layer List */}
      <div className="flex-1 overflow-y-auto p-2 space-y-1.5 divide-y divide-slate-800/40">
        {layers.length === 0 ? (
          <div className="text-center py-6 text-xs text-slate-500">
            No active spatial layers
          </div>
        ) : (
          layers.map((layer) => {
            const isHidden = hiddenLayers.has(layer.layer_id);
            return (
              <div
                key={layer.layer_id}
                className={`pt-1.5 first:pt-0 flex items-center justify-between p-2 rounded transition border ${
                  isHidden
                    ? 'bg-slate-950/40 border-slate-900 opacity-60'
                    : 'bg-slate-950/80 border-slate-800/80 hover:border-slate-700'
                }`}
              >
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

                <button
                  type="button"
                  onClick={() => onToggleVisibility && onToggleVisibility(layer.layer_id)}
                  className={`p-1.5 rounded transition ml-2 shrink-0 ${
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
            );
          })
        )}
      </div>
    </div>
  );
}