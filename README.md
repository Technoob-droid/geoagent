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
```
---

## Prerequisites

Before running the project locally, make sure you have:

- Python 3.11 or newer installed
- Node.js 18+ and npm installed
- A valid Groq API Key

---

## Environment Variables

Create a .env file in the project root with the following variables:

```env
GROQ_API_KEY=your_groq_api_key_here
GROQ_MODEL=llama-3.3-70b-versatile
DUCKDB_DATABASE_PATH=backend/app/data/storage/geoagent.duckdb
CORS_ORIGINS=http://localhost:5173,[http://127.0.0.1:5173](http://127.0.0.1:5173)
```

---

## Installation

### 1. Backend Setup Power SHell

```bash
# Create and activate virtual environment
python -m venv venv
.\venv\Scripts\Activate.ps1

# Install backend dependencies
pip install -r backend/requirements.txt

```

### 2. Database Initialization & Seeding

Populate your local DuckDB spatial database with administrative boundaries, baseline regional assets, and the hierarchical national electrical network

```bash
# Seed administrative layers and baseline utilities
python -m backend.app.data.seeds.load_utilities

# Seed the national multi-tier grid (GSS, PSS, DSS, Feeders, Switchgear)
python -m backend.app.data.seeds.load_national_grid
```

### 3. Frontend Setup
In a separate terminal tab
```bash
cd frontend
npm install
```
---

## Running the App

### 1. Start the FastAPI server:

```bash
uvicorn backend.app.main:app --reload --port 8000
```

Then open your browser at:

```text
API Base: http://localhost:8000

Interactive Swagger Docs: http://localhost:8000/docs
```
### 2. Start the Frontend Client

```bash
cd frontend
npm run dev
```
Then open your browser at:

```text
http://localhost:5173
```

---

## API Endpoints

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| **GET** | /api/layers | Lists all base and dynamic analytical layers in catalog |
| **GET** | /api/layers/{layer_id}/geojson | Streams layer features as standard GeoJSON |
| **POST** | /api/chat | Dispatches natural language spatial intent to LangGraph agent |
| **GET** | /api/layers/boundaries/query | Viewport-clipped bounding box queries for administrative boundaries |
| **GET** | /api/layers/tiles/{layer_id}/{z}/{x}/{y}.pbf | Dynamic vector tiles (MVT) for large-scale datasets |


Example request:

```bash
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Show all 33kV primary substations in West Bengal"}'
```
---

## How the Workflow Works

1. Natural Language Input: User enters a query (e.g., "Simulate outage of Kolaghat Thermal Power Station").

2. Intent & Schema Routing: LangGraph identifies topological needs and selects the appropriate tool (filter_utility_network, simulate_grid_outage, run_spatial_sql, etc.).

3. In-Memory Analytical Query: DuckDB Spatial executes the operation directly over local Parquet tables or DuckDB memory using spatial joins and geometric predicates (ST_Intersects, ST_DWithin).

4. Catalog Registration: The output table is registered as a new active layer with calculated counts, geometry types, and metadata in CatalogManager.

5. Real-Time Client Rendering: MapLibre GL JS loads the vector dataset via GeoJSON or MVT tiles and renders custom styling based on operational voltage tier and asset state.

---

## Contributing

Contributions are welcome. If you want to improve the app, add new travel features, or fix issues:

1. Fork the repository

2. Create your feature branch (git checkout -b feature/grid-contingency)

3. Commit your changes (git commit -m "feat: implement downstream path trace")

4. Push to the branch (git push origin feature/grid-contingency)

5. Open a Pull Request
