# Backend — Lunar Landing Site Navigator API

FastAPI service that will compute terrain-aware Sun/Earth line-of-sight and mission metrics for a fixed set of lunar south-pole sites. See [docs/PROJECT_PLAN.md](../../docs/PROJECT_PLAN.md) for scope and [docs/SCIENCE_CONVENTIONS.md](../../docs/SCIENCE_CONVENTIONS.md) for the physics conventions.

**Status: M0 (skeleton) + metric framework.** Only `GET /health` exists. The reusable metric framework and constraint checks are implemented and tested on synthetic series; their definitions are **pending physics review** in [docs/metrics.md](../../docs/metrics.md). No physics (ephemeris, terrain, horizon) is implemented yet.

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
pip install -e ".[dev]"
```

## Commands

| Task | Command |
|---|---|
| Run all tests | `python -m pytest` |
| Run the API locally | `uvicorn app.main:app --reload` then open http://127.0.0.1:8000/health |
| Interactive API docs | http://127.0.0.1:8000/docs (served by FastAPI) |
| Refresh the lock file | `pip freeze --exclude-editable` into `requirements.lock` (keep the two header comment lines) |

## Layout

```text
src/backend/
├── app/
│   ├── main.py          # FastAPI app entry point
│   └── api/
│       ├── routes.py    # HTTP endpoints (only /health in M0)
│       └── schemas.py   # Pydantic models = the frontend/backend JSON contract
│   ├── metrics/
│   │   ├── core.py      # EvaluationContext, Metric interface, MetricResult, runner
│   │   ├── visibility.py# VisibleFraction, LongestOutage (reused for Sun and Earth)
│   │   └── registry.py  # the explicit list of active metrics
│   └── planning/
│       └── constraints.py # constraints by metric id, margins, feasibility
├── tests/
│   ├── test_health.py
│   ├── test_contract.py # validates docs/frontend-backend_interface.json against schemas.py
│   ├── test_metrics_core.py
│   ├── test_visibility_metrics.py
│   └── test_constraints.py
├── pyproject.toml       # dependency ranges
└── requirements.lock    # exact pinned versions of the tested environment
```

Physics modules (`astronomy/`, `coordinates/`, `terrain/`, `physics/`) are added in later milestones. They, like `metrics/` and `planning/`, stay independent of FastAPI. To add a metric, follow "Adding a metric" in [docs/metrics.md](../../docs/metrics.md).

## The JSON contract

[`docs/frontend-backend_interface.json`](../../docs/frontend-backend_interface.json) is the agreement with the frontend engineer. `app/api/schemas.py` mirrors it exactly, and `tests/test_contract.py` fails if the two drift apart, including if a field is added on one side only. Change both together.
