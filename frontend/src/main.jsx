import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App.jsx';
import './index.css';
import 'maplibre-gl/dist/maplibre-gl.css';

const rootElement = document.getElementById('root');
if (!rootElement) {
  console.error("Root element not found!");
} else {
  ReactDOM.createRoot(document.getElementById('root')).render(
    <React.StrictMode>
      <App />
    </React.StrictMode>
  );
}