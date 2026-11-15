# Backend — Lunar Landing Site Navigator API

FastAPI service that computes terrain-aware Sun/Earth line of sight and mission metrics for curated lunar south-pole sites. Developer reference for the backend; for an overview and the **installation guide**, see the [root README](../../README.md). Scope: [docs/PROJECT_PLAN.md](../../docs/PROJECT_PLAN.md); conventions: [docs/SCIENCE_CONVENTIONS.md](../../docs/SCIENCE_CONVENTIONS.md); API reference: [docs/API.md](../../docs/API.md).

**Status:** the physics core is reviewed and validated against NASA's published illumination maps ([docs/physics/validation.md](../../docs/physics/validation.md)), and the API serves `/health`, `/sites`, `/analyze`, `/compare` and `/data-provenance`.

| Component | Code | Explainer | Review |
|---|---|---|---|
| Metric framework and constraints | `app/metrics/`, `app/planning/` | [docs/metrics.md](../../docs/metrics.md) | Partially reviewed |
| P1 Coordinates and local geometry | `app/coordinates/` | [docs/physics/frames.md](../../docs/physics/frames.md) | Signed off |
| P2 Sun/Earth directions (sky grid) | `app/astronomy/`, `pipeline/build_sky_grid.py` | [docs/physics/sky.md](../../docs/physics/sky.md) | Signed off |
| P3 Terrain ingest | `app/terrain/`, `pipeline/build_terrain.py` | [docs/physics/terrain.md](../../docs/physics/terrain.md) | Signed off |
| M2 Horizon, visibility, analysis | `app/physics/`, `pipeline/build_far_horizons.py` | [docs/physics/horizon.md](../../docs/physics/horizon.md) | Signed off |
| Validation against NASA maps | `pipeline/validate_illumination.py` | [docs/physics/validation.md](../../docs/physics/validation.md) | Signed off |
| M3 API | `app/api/` | [docs/API.md](../../docs/API.md) | — |

## Two halves: runtime and offline pipeline

- **`app/`** is the hosted server. It needs only FastAPI, Pydantic and NumPy, and reads precomputed or built files: the sky grid and far horizons (committed) and the per-site terrain grids (built in setup).
- **`pipeline/`** is the offline data pipeline: downloads, SPICE, terrain conversion, validation. It needs the `pipeline` extra and is never installed on the server. See [PROJECT_PLAN.md §8.1](../../docs/PROJECT_PLAN.md).

## Setup

Follow **Installation** in the [root README](../../README.md). In short, from `src/backend` with Python 3.12+:

```bash
python -m venv .venv
```

Activate it, then:

```bash
pip install -r requirements.lock
```

```bash
pip install -e . --no-deps
```

```bash
python -m pipeline.fetch_data
```

```bash
python -m pipeline.build_terrain
```

`fetch_data` downloads the files listed in `data/manifests/` and verifies their SHA-256 checksums; the default is the terrain only (about 1 GB, enough to run the API). `python -m pipeline.fetch_data --all` adds the SPICE kernels and NASA validation maps. Tests that need data you haven't fetched are skipped, not failed.

## Commands

| Task | Command |
|---|---|
| Run all tests | `python -m pytest` |
| Run the API locally | `uvicorn app.main:app --reload` then open http://127.0.0.1:8000/sites (needs the built data; see Setup) |
| Interactive API docs | http://127.0.0.1:8000/docs (served by FastAPI) |
| Download source data (terrain; `--all` for everything) | `python -m pipeline.fetch_data` |
| Rebuild the sky grid | `python -m pipeline.build_sky_grid` |
| Cross-check against JPL Horizons (network) | `python -m pipeline.horizons_check` |
| Regenerate P2 review evidence and plot | `python -m pipeline.sky_evidence` |
| Build terrain artifacts and site list | `python -m pipeline.build_terrain` |
| Regenerate P3 review evidence and images | `python -m pipeline.terrain_evidence` |
| Precompute far-zone horizons | `python -m pipeline.build_far_horizons` |
| Regenerate M2 review evidence and horizon plots (~2 min) | `python -m pipeline.horizon_evidence` |
| Validate against NASA illumination maps (~5 min) | `python -m pipeline.validate_illumination` |
| Refresh the lock file | `pip freeze --exclude-editable` into `requirements.lock` (keep the two header comment lines) |

## Layout

```text
src/backend/
├── app/                    # runtime server (FastAPI + NumPy)
│   ├── main.py             # FastAPI app: startup data loading, error handler, CORS (LLSN_CORS_ORIGINS)
│   ├── api/
│   │   ├── routes.py       # HTTP endpoints (docs/API.md)
│   │   ├── schemas.py      # Pydantic models = the frontend/backend JSON contract + requests
│   │   └── service.py      # site matching, analysis, Assessment -> contract mapping
│   ├── astronomy/
│   │   └── sky.py          # sky grid loading, mission sampling, topocentric Sun/Earth az/el
│   ├── coordinates/
│   │   └── frames.py       # site <-> position, east/north/up, az/el, great circles
│   ├── terrain/
│   │   └── grid.py         # polar stereographic projection, TerrainGrid, bilinear height lookup
│   ├── physics/
│   │   ├── horizon.py      # ray casting, far-field candidates, per-height horizon (cached)
│   │   ├── visibility.py   # Sun/Earth vs horizon: visible / obstructed / unknown
│   │   └── analysis.py     # one-call analysis -> Assessment
│   ├── metrics/
│   │   ├── core.py         # EvaluationContext, Metric interface, MetricResult, runner
│   │   ├── visibility.py   # VisibleFraction, LongestOutage (reused for Sun and Earth)
│   │   └── registry.py     # the explicit list of active metrics
│   └── planning/
│       └── constraints.py  # constraints by metric id, margins, feasibility
├── pipeline/               # offline only (SpiceyPy, rasterio, pyproj, matplotlib)
│   ├── fetch_data.py       # downloads data/manifests/ files with checksum verification
│   ├── checksums.py        # SHA-256 verification against data/manifests/
│   ├── spice_kernels.py    # checksum-verified DE421 kernel loading
│   ├── build_terrain.py    # terrain artifacts + data/sites/south_pole_sites.json
│   ├── terrain_evidence.py # P3 evidence tables and images
│   ├── build_far_horizons.py # data/horizons/<site>_far.npz
│   ├── horizon_evidence.py # M2 evidence tables and horizon plots
│   ├── validate_illumination.py # comparison with NASA's published illumination maps
│   ├── build_sky_grid.py   # builds data/sky/ grid
│   ├── horizons_check.py   # JPL Horizons cross-check
│   └── sky_evidence.py     # P2 evidence tables and plot
├── tests/
│   ├── test_health.py
│   ├── test_api.py         # /sites, /analyze, /compare, errors, provenance (real data)
│   ├── test_fetch_data.py  # download, skip and corrupted-download handling
│   ├── test_contract.py    # validates docs/frontend-backend_interface.json against schemas.py
│   ├── test_frames.py
│   ├── test_sky_runtime.py # synthetic grids, no SPICE
│   ├── test_sky_spice.py   # real grid vs SPICE (skipped without kernels)
│   ├── test_terrain_grid.py # synthetic grids, projection vs pyproj
│   ├── test_terrain_data.py # real artifacts vs source GeoTIFFs (skipped if not built)
│   ├── test_horizon_synthetic.py # sphere, wall, ridge, monotonicity, no-data, visibility rules
│   ├── test_horizon_sites.py # real-site tolerances, mast/Earth independence, reproducibility
│   ├── test_metrics_core.py
│   ├── test_visibility_metrics.py
│   └── test_constraints.py
├── pyproject.toml          # dependency ranges (runtime, dev, pipeline extras)
└── requirements.lock       # exact pinned versions of the tested environment
```

All physics and metric modules stay independent of FastAPI. To add a metric, follow "Adding a metric" in [docs/metrics.md](../../docs/metrics.md).

## The JSON contract

[`docs/frontend-backend_interface.json`](../../docs/frontend-backend_interface.json) is the agreement with the frontend engineer. `app/api/schemas.py` mirrors it exactly, and `tests/test_contract.py` fails if the two drift apart, including if a field is added on one side only. Change both together.

Requests will need mission starts on a whole UTC hour and whole-hour steps, within 2026-01-01 to 2040-12-31 (see [docs/physics/sky.md](../../docs/physics/sky.md) §3).
