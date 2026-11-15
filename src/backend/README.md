# Backend — Lunar Landing Site Navigator API

FastAPI service that will compute terrain-aware Sun/Earth line-of-sight and mission metrics for a fixed set of lunar south-pole sites. See [docs/PROJECT_PLAN.md](../../docs/PROJECT_PLAN.md) for scope and [docs/SCIENCE_CONVENTIONS.md](../../docs/SCIENCE_CONVENTIONS.md) for the physics conventions.

**Status: M1 and M2 physics signed off and validated against NASA's published illumination maps** ([docs/physics/validation.md](../../docs/physics/validation.md)). **M3: the API serves `/sites`, `/analyze`, `/compare` and `/data-provenance`**; see [docs/API.md](../../docs/API.md). Only `GET /health` exists. Implemented and tested:

| Component | Code | Explainer | Review |
|---|---|---|---|
| Metric framework and constraints | `app/metrics/`, `app/planning/` | [docs/metrics.md](../../docs/metrics.md) | Partially reviewed |
| P1 Coordinates and local geometry | `app/coordinates/` | [docs/physics/frames.md](../../docs/physics/frames.md) | Signed off |
| P2 Sun/Earth directions (sky grid) | `app/astronomy/`, `pipeline/` | [docs/physics/sky.md](../../docs/physics/sky.md) | Signed off |

| P3 Terrain ingest | `app/terrain/`, `pipeline/build_terrain.py` | [docs/physics/terrain.md](../../docs/physics/terrain.md) | Signed off |

| M2 Horizon, visibility, analysis | `app/physics/`, `pipeline/build_far_horizons.py` | [docs/physics/horizon.md](../../docs/physics/horizon.md) | Signed off |

`app/physics/analysis.py` runs the full chain (site + mission + vehicle + constraints → horizons, Sun/Earth visibility, metrics, feasibility); it is not wired to the API yet (M3).

## Two halves: runtime and offline pipeline

- **`app/`** is the hosted server. It needs only FastAPI, Pydantic and NumPy, and reads precomputed files such as `data/sky/sky_grid_de421_2026_2040_1h.npz`.
- **`pipeline/`** is the offline data pipeline (SPICE now, terrain later). It needs the `pipeline` extra and is never installed on the server. See [PROJECT_PLAN.md §8.1](../../docs/PROJECT_PLAN.md).

## Setup

Requires Python 3.12+. All commands run from `src/backend`.

```bash
python -m venv .venv
```

Activate it (Windows PowerShell: `.venv\Scripts\Activate.ps1`; bash: `source .venv/Scripts/activate` on Windows or `source .venv/bin/activate` elsewhere), then install either the exact tested versions or the latest compatible ones:

```bash
pip install -r requirements.lock && pip install -e . --no-deps
```

```bash
pip install -e ".[dev,pipeline]"
```

The SPICE kernels and terrain GeoTIFFs are not in the repo. Download the files listed in [data/manifests/kernels.json](../../data/manifests/kernels.json) into `data/kernels/` and those in [data/manifests/terrain.json](../../data/manifests/terrain.json) (about 1 GB) into `data/raw/terrain/`, each from `source_base_url` + its `path`. The pipeline verifies SHA-256 checksums before use. Without them, the SPICE and real-terrain tests are skipped and everything else still runs.

## Commands

| Task | Command |
|---|---|
| Run all tests | `python -m pytest` |
| Run the API locally | `uvicorn app.main:app --reload` then open http://127.0.0.1:8000/sites (needs the built data; see Setup) |
| Interactive API docs | http://127.0.0.1:8000/docs (served by FastAPI) |
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
