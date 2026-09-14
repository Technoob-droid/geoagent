# GeoAgent: Autonomous Geospatial AI & National Utility Digital Twin

**GeoAgent** is an autonomous spatial GIS analyst and cartographic AI platform designed for multi-tier geospatial operations, contingency simulations, and interactive exploration of administrative geography and utility networks across India.

Powered by **DuckDB Spatial**, **FastAPI**, **LangGraph**, and **MapLibre GL JS**, GeoAgent translates natural language instructions into targeted topological queries, materialized vector map layers, and analytical visualizations.

---

## Key Capabilities

### 1. National Utility Grid "Digital Twin"
- **Multi-Tier Substation Hierarchy (`utility_substations_master`)**: Models Grid Sub-Stations (GSS: 765kV / 400kV / 220kV / 132kV), Primary Sub-Stations (PSS: 66kV / 33kV), and Distribution Sub-Stations (DSS: 11kV) across regional clusters (West Bengal, Maharashtra, Delhi NCR, Karnataka).
- **Corridors & Trunks (`utility_feeders_master`)**: Traces high-voltage transmission lines (400kV inter-state trunks) down to 33kV sub-transmission corridors and 11kV primary distribution circuits.
- **Protection Switchgear (`utility_switchgear_master`)**: Tracks Circuit Breakers (CBs), Isolators, and Ring Main Units (RMUs) with operational switching states (`CLOSED`, `OPEN`, `TRIPPED`).
- **N-1 Contingency & Outage Simulation**: Simulates asset failure footprints (such as generation plant trips), automatically computing downstream unserved load (MVA) and identifying de-energized substations.

### 2. Autonomous Spatial Operations
- **Dynamic Voltage Styling**: Automated MapLibre symbology rendering nodes and lines dynamically based on operational voltage levels, equipment tiers, and switchgear operational health.
- **Hierarchical Network Filtering**: Query network assets directly via natural language (e.g., *"Show all 33kV primary substations in West Bengal"* or *"Filter all 400kV transmission corridors across India"*).
- **Administrative Geography & Spatial Joins**: Complete administrative coverage across India States (ADM1), Districts (ADM2), Sub-districts / Tehsils (ADM3), Cities, and Revenue Villages.
- **Topological Operations**: Point-in-polygon containment, geodesic metric buffers (EPSG:3857), Voronoi catchments, and travel-time reachability envelopes.

---

## Architecture & Tech Stack

| Component | Technology | Purpose |
| :--- | :--- | :--- |
| **Spatial Database** | DuckDB + DuckDB Spatial | In-process columnar database executing spatial SQL queries over local Parquet/DuckDB storage |
| **Agent Framework** | LangGraph / LangChain + Groq | Autonomous tool dispatch, topological intent routing, and conversational synthesis |
| **Backend API** | FastAPI + Uvicorn | GeoJSON vector streaming, boundary query serving, dynamic MVT vector tiles, catalog registry |
| **Frontend Map** | React + MapLibre GL JS + Tailwind CSS | GPU-accelerated cartographic viewer, LOD tile management, custom symbology, active layer controls |

---

## Repository Structure

```text
geoagent/
├── backend/
│   ├── app/
│   │   ├── agent/                 # LangGraph workflows and prompts
│   │   │   ├── graph.py
│   │   │   └── prompts.py
│   │   ├── api/                   # FastAPI endpoints (layers, chat, tiles)
│   │   │   └── routes.py
│   │   ├── config.py              # Application settings and environment configuration
│   │   ├── data/
│   │   │   ├── seeds/             # Seed scripts for boundaries, utilities, and grid assets
│   │   │   │   ├── load_boundaries.py
│   │   │   │   ├── load_utilities.py
│   │   │   │   └── load_national_grid.py
│   │   │   └── storage/           # DuckDB database file (geoagent.duckdb)
│   │   ├── main.py                # Backend entry point
│   │   └── tools/                 # DuckDB engine, spatial operations, catalog manager
│   │       ├── catalog.py
│   │       ├── engine.py
│   │       ├── spatial_ops.py
│   │       └── sql_runner.py
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── ChatConsole.jsx    # Natural language prompt interface
│   │   │   ├── LayerDrawer.jsx    # Interactive map layer manager
│   │   │   └── MapViewer.jsx      # MapLibre GL map container and style rules
│   │   ├── App.jsx
│   │   └── main.jsx
│   ├── package.json
│   └── vite.config.js
├── .env.example
├── .gitignore
├── README.md
└── seed_zones.py