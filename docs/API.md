# API.md — Backend API reference (M3)

For the frontend engineer. The response body of `/analyze` follows the agreed **v1 contract** in [`frontend-backend_interface.json`](frontend-backend_interface.json) exactly; proposed v2 changes are in `PROJECT_PLAN.md` §7.2 and are **not** implemented yet. Interactive docs are served at `/docs` when the API runs.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Readiness and which datasets loaded |
| GET | `/sites` | Supported sites, supported dates and request limits |
| POST | `/analyze` | One site: 360° horizons, Sun/Earth time series, metrics, feasibility |
| POST | `/compare` | 2–4 sites under one shared mission, vehicle and constraints |
| GET | `/data-provenance` | Data sources, checksums, build provenance, modelling assumptions |

## `POST /analyze` request

```json
{
  "site": {"name": "Shackleton rim", "latitude_deg": -89.780403, "longitude_deg_east": 203.803049},
  "mission": {"start_utc": "2030-11-20T12:00:00Z", "duration_hours": 336, "sample_step_seconds": 3600},
  "vehicle": {"solar_panel_mast_height_m": 2.0, "antenna_height_m": 2.0},
  "constraints": {"max_darkness_hours": 24, "max_earth_blackout_hours": 100}
}
```

| Field | Rule |
|---|---|
| `site.latitude_deg`, `longitude_deg_east` | Must be within **100 m** of a supported site (get them from `GET /sites`); `name` is optional and echoed back |
| `mission.start_utc` | ISO 8601 UTC with `Z`, on a **whole hour**, within **2026-01-01T00:00Z to 2040-12-31T23:00Z** |
| `mission.duration_hours` | > 0, at most 8,784 (366 days); the whole mission must lie in the supported dates |
| `mission.sample_step_seconds` | A whole number of hours: 3600, 7200, … |
| `vehicle.*_height_m` | 0 to 20 m above local ground |
| `constraints.*` | Hours, ≥ 0; omit or `null` to disable. With no constraints, `feasibility.status` is `"unknown"` |

Unknown fields are rejected.

## `POST /analyze` response

The v1 contract. Notes on the values:

- `candidate.location` is the **supported site's** exact coordinates and ground height (metres above the 1,737.4 km sphere), not the requested ones.
- `horizons.azimuth_deg`: 1,440 directions, 0.25° apart, clockwise from north. `sun_observer_horizon_elevation_deg` is the terrain skyline seen from the solar-mast height, `earth_observer_…` from the antenna height (`PROJECT_PLAN.md` §7.1 explains how to draw it).
- `series`: one entry per sample, `floor(duration / step) + 1` samples including both ends. Angles in degrees; `*_visible` booleans compare each body's centre with its horizon.
- `metrics`: fractions in 0–1, durations in hours (`docs/metrics.md`).
- `feasibility.failed_constraints`: metric ids that failed; `margins`: metric id → signed margin in hours (positive = passing).
- `diagnostics`: human-readable lines, e.g. each constraint's value, margin and the timing of its worst outage.
- `computation_ms`: server time for the request.

## `POST /compare`

Request: `sites` (2–4 of the same objects as `site` above) plus one shared `mission`, `vehicle` and `constraints`. Response: `{"candidates": [ … ], "computation_ms": …}`, one `candidate` per site in request order, each exactly as in `/analyze`. Every candidate shares the same timestamps. *(This response shape is new in M3 and should be confirmed with the frontend engineer.)*

## Errors

Validation errors (wrong types, out-of-range fields, unknown fields) return **422** with FastAPI's standard `detail` list. Service errors return:

```json
{"error": "<code>", "message": "<explanation>", "...": "details"}
```

| Status | `error` | When | Details included |
|---|---|---|---|
| 404 | `site_unavailable` | No supported site within 100 m, or outside 88–90°S | `nearest_site`, `nearest_distance_m`, `supported` list |
| 422 | `mission_out_of_range` | Start not on a whole hour, mission outside the supported dates, or unreadable `start_utc` | `supported_start_utc`, `supported_end_utc`, `sample_step_seconds_multiple` |
| 503 | `data_unavailable` | Server data not loaded, or a result would contain "unknown" visibility (not expressible in v1) | `missing` |

## Performance (measured 2026-11-14, in-process, the plan's standard workload: 2 sites, 14 days, hourly)

| Case | Time | Response size |
|---|---|---|
| First request for a mast/antenna height (horizons computed) | about 1.5 s | 126 KB |
| Repeat request (horizons cached) | about 5 ms | 126 KB |
| New solar-mast **and** antenna heights for both sites | about 3.0 s | 126 KB |
| One-year mission, cached | about 70 ms | 1.4 MB |

Horizons are cached per site and height for the server's lifetime. Network time is not included.

## Cross-origin access

Set `LLSN_CORS_ORIGINS` to the frontend's origin(s), comma separated, before starting the server, e.g. `LLSN_CORS_ORIGINS=https://app.example.org,http://localhost:5173`. With it unset, no cross-origin access is allowed.
