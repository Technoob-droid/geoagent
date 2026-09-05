import React, { useState, useEffect, useRef } from 'react';
import { Search, MapPin, Loader2, X } from 'lucide-react';

export default function PlaceSearch({ onSelectPlace }) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isOpen, setIsOpen] = useState(false);
  const dropdownRef = useRef(null);

  useEffect(() => {
    const handleClickOutside = (event) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target)) {
        setIsOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  useEffect(() => {
    if (query.trim().length < 2) {
      setResults([]);
      setIsOpen(false);
      return;
    }

    const timer = setTimeout(async () => {
      setIsLoading(true);
      try {
        const res = await fetch(`/api/layers/resolver/search?query=${encodeURIComponent(query.trim())}`);
        const data = await res.json();
        setResults(data.results || []);
        setIsOpen(true);
      } catch (err) {
        console.error('Resolver search failed:', err);
      } finally {
        setIsLoading(false);
      }
    }, 250);

    return () => clearTimeout(timer);
  }, [query]);

  const handleSelect = (place) => {
    onSelectPlace(place);
    setQuery(place.name);
    setIsOpen(false);
  };

  const handleClear = () => {
    setQuery('');
    setResults([]);
    setIsOpen(false);
  };

  return (
    <div ref={dropdownRef} className="relative w-64 text-xs">
      <div className="flex items-center bg-slate-900/90 backdrop-blur-md border border-slate-700/80 rounded-lg px-2.5 py-1.5 shadow-lg focus-within:border-indigo-500 transition">
        <Search className="w-3.5 h-3.5 text-slate-400 mr-2 shrink-0" />
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search State or District..."
          className="bg-transparent text-slate-200 placeholder-slate-500 focus:outline-none w-full text-xs"
        />
        {isLoading && <Loader2 className="w-3 h-3 text-indigo-400 animate-spin mr-1 shrink-0" />}
        {query && !isLoading && (
          <button type="button" onClick={handleClear} className="text-slate-500 hover:text-slate-300">
            <X className="w-3 h-3" />
          </button>
        )}
      </div>

      {isOpen && results.length > 0 && (
        <div className="absolute top-full left-0 right-0 mt-1.5 bg-slate-900 border border-slate-700 rounded-lg shadow-2xl py-1 z-50 max-h-60 overflow-y-auto">
          {results.map((r, idx) => (
            <button
              key={`${r.name}-${idx}`}
              type="button"
              onClick={() => handleSelect(r)}
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
  );
}