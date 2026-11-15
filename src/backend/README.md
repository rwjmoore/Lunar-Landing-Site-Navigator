# Backend — Lunar Landing Site Navigator API

FastAPI service that will compute terrain-aware Sun/Earth line-of-sight and mission metrics for a fixed set of lunar south-pole sites. See [docs/PROJECT_PLAN.md](../../docs/PROJECT_PLAN.md) for scope and [docs/SCIENCE_CONVENTIONS.md](../../docs/SCIENCE_CONVENTIONS.md) for the physics conventions.

**Status: M1 in progress.** Only `GET /health` exists. Implemented and tested:

| Component | Code | Explainer | Review |
|---|---|---|---|
| Metric framework and constraints | `app/metrics/`, `app/planning/` | [docs/metrics.md](../../docs/metrics.md) | Partially reviewed |
| P1 Coordinates and local geometry | `app/coordinates/` | [docs/physics/frames.md](../../docs/physics/frames.md) | Signed off |
| P2 Sun/Earth directions (sky grid) | `app/astronomy/`, `pipeline/` | [docs/physics/sky.md](../../docs/physics/sky.md) | Signed off |

Terrain (P3) and the horizon/visibility physics (M2) are not implemented yet.

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

The SPICE kernels are not in the repo. Download the files listed in [data/manifests/kernels.json](../../data/manifests/kernels.json) from `source_base_url` + each `path` into `data/kernels/`. The pipeline verifies their SHA-256 checksums before use. Without them, the SPICE validation tests are skipped and everything else still runs.

## Commands

| Task | Command |
|---|---|
| Run all tests | `python -m pytest` |
| Run the API locally | `uvicorn app.main:app --reload` then open http://127.0.0.1:8000/health |
| Interactive API docs | http://127.0.0.1:8000/docs (served by FastAPI) |
| Rebuild the sky grid | `python -m pipeline.build_sky_grid` |
| Cross-check against JPL Horizons (network) | `python -m pipeline.horizons_check` |
| Regenerate P2 review evidence and plot | `python -m pipeline.sky_evidence` |
| Refresh the lock file | `pip freeze --exclude-editable` into `requirements.lock` (keep the two header comment lines) |

## Layout

```text
src/backend/
├── app/                    # runtime server (FastAPI + NumPy)
│   ├── main.py             # FastAPI app entry point
│   ├── api/
│   │   ├── routes.py       # HTTP endpoints (only /health so far)
│   │   └── schemas.py      # Pydantic models = the frontend/backend JSON contract
│   ├── astronomy/
│   │   └── sky.py          # sky grid loading, mission sampling, topocentric Sun/Earth az/el
│   ├── coordinates/
│   │   └── frames.py       # site <-> position, east/north/up, az/el, great circles
│   ├── metrics/
│   │   ├── core.py         # EvaluationContext, Metric interface, MetricResult, runner
│   │   ├── visibility.py   # VisibleFraction, LongestOutage (reused for Sun and Earth)
│   │   └── registry.py     # the explicit list of active metrics
│   └── planning/
│       └── constraints.py  # constraints by metric id, margins, feasibility
├── pipeline/               # offline only (SpiceyPy, matplotlib)
│   ├── spice_kernels.py    # checksum-verified DE421 kernel loading
│   ├── build_sky_grid.py   # builds data/sky/ grid
│   ├── horizons_check.py   # JPL Horizons cross-check
│   └── sky_evidence.py     # P2 evidence tables and plot
├── tests/
│   ├── test_health.py
│   ├── test_contract.py    # validates docs/frontend-backend_interface.json against schemas.py
│   ├── test_frames.py
│   ├── test_sky_runtime.py # synthetic grids, no SPICE
│   ├── test_sky_spice.py   # real grid vs SPICE (skipped without kernels)
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
