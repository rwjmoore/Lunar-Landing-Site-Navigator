# API.md — Backend API reference (M3)

For the frontend engineer. The response body of `/analyze` follows the agreed **v1 contract** in [`frontend-backend_interface.json`](frontend-backend_interface.json) exactly; proposed v2 changes are in `PROJECT_PLAN.md` §7.2 and are **not** implemented yet. Interactive docs are served at `/docs` when the API runs.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Readiness and which datasets loaded |
| GET | `/sites` | Curated sites, custom-point coverage, supported dates and request limits |
| POST | `/analyze` | One site: 360° horizons, Sun/Earth time series, metrics, feasibility |
| POST | `/compare` | 2–4 sites under one shared mission, vehicle and constraints |
| POST | `/calendar` | **Planning:** one mission length evaluated at many start dates |
| POST | `/insights` | **Planning:** plain-language explanation of an analysis |
| POST | `/rescue` | **Planning:** smallest single change that makes a mission pass |
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
| `site.latitude_deg`, `longitude_deg_east` | Any point **south of 86.70°S** (the edge is `custom_point_north_edge_latitude_deg` in `GET /sites`). Within **100 m** of a curated site, that site's precomputed terrain is used; elsewhere the horizon is computed on demand ([custom_points.md](physics/custom_points.md)). `name` is optional and echoed back |
| `mission.start_utc` | ISO 8601 UTC with `Z`, on a **whole hour**, within **2026-01-01T00:00Z to 2040-12-31T23:00Z** |
| `mission.duration_hours` | > 0, at most 8,784 (366 days); the whole mission must lie in the supported dates |
| `mission.sample_step_seconds` | A whole number of hours: 3600, 7200, … |
| `vehicle.*_height_m` | 0 to 20 m above local ground |
| `constraints.*` | Hours, ≥ 0; omit or `null` to disable. With no constraints, `feasibility.status` is `"unknown"` |

Unknown fields are rejected.

## `POST /analyze` response

The v1 contract. Notes on the values:

- `candidate.location`: for a curated site, the **site's** exact coordinates; for a custom point, the requested ones. `elevation_m` is the ground height in metres above the 1,737.4 km sphere.
- Custom points: `provenance.dem_id` says `high detail` (inside a 5 m site map) or `standard detail` (40 m map only), and standard-detail results add a diagnostic that mast-height effects there are less certain.
- `horizons.azimuth_deg`: 1,440 directions, 0.25° apart, clockwise from north. `sun_observer_horizon_elevation_deg` is the terrain skyline seen from the solar-mast height, `earth_observer_…` from the antenna height (`PROJECT_PLAN.md` §7.1 explains how to draw it).
- `series`: one entry per sample, `floor(duration / step) + 1` samples including both ends. Angles in degrees; `*_visible` booleans compare each body's centre with its horizon.
- `metrics`: fractions in 0–1, durations in hours (`docs/metrics.md`).
- `feasibility.failed_constraints`: metric ids that failed; `margins`: metric id → signed margin in hours (positive = passing).
- `diagnostics`: human-readable lines, e.g. each constraint's value, margin and the timing of its worst outage.
- `computation_ms`: server time for the request.

## `POST /compare`

Request: `sites` (2–4 of the same objects as `site` above) plus one shared `mission`, `vehicle` and `constraints`. Response: `{"candidates": [ … ], "computation_ms": …}`, one `candidate` per site in request order, each exactly as in `/analyze`. Every candidate shares the same timestamps. *(This response shape is new in M3 and should be confirmed with the frontend engineer.)*

## Planning endpoints

New endpoints, separate from the v1 `/analyze` contract (which is unchanged). Definitions and evidence: [docs/physics/planning.md](physics/planning.md). All three use **hourly sampling**.

### `POST /calendar` — which start dates work?

```json
{
  "site": {"latitude_deg": -89.463163, "longitude_deg_east": 222.510447},
  "vehicle": {"solar_panel_mast_height_m": 2.0, "antenna_height_m": 2.0},
  "constraints": {"max_darkness_hours": 24, "max_earth_blackout_hours": 200},
  "duration_hours": 336,
  "start_step_hours": 24,
  "start_from_utc": "2030-01-01T00:00:00Z",
  "start_to_utc": "2031-01-01T00:00:00Z"
}
```

- `duration_hours`: whole hours. `start_step_hours`: 1–720 (default 24). `start_from_utc` / `start_to_utc`: optional whole UTC hours; the defaults span every start that fits in 2026–2040.
- **Response:** parallel arrays, one entry per candidate start: `starts_utc`, `sun_visible_fraction`, `max_darkness_hours`, `earth_visible_fraction`, `max_earth_blackout_hours`, `status` (`feasible` / `infeasible` / `unknown`), `worst_margin_hours` (smallest signed margin; positive = passing). Plus `feasible_count`, `best_start_utc` and `best_worst_margin_hours`.
- Each entry equals what `/analyze` returns for that start.
- At most 20,000 starts per request (e.g. every 24 h across 2026–2040 is 5,479); more returns `422 too_many_starts`.
- Typically well under a second.
- **UI idea:** a calendar heat-map colored by status or margin, with the requested date highlighted.

### `POST /insights` — why, and what happens next?

Request: identical to `/analyze`. Response:

| Field | Meaning |
|---|---|
| `summary` | Plain-language lines: sunlight and Earth visibility, joint windows, what happens first, why the worst outages happened |
| `events` | Every Sun/Earth `rise` and `set` with its time |
| `sun_hours_to_change`, `earth_hours_to_change` | Per timestamp (matching `timestamps_utc`): hours until the next sunset/sunrise or Earthset/Earthrise; `null` if none before the mission ends |
| `joint_visible_fraction`, `longest_joint_window_hours` + start/end | When the Sun and Earth are visible **together** (charge and talk at once) |
| `outages` | For the longest darkness and Earth blackout: azimuth range, max depth below the horizon, the **dominant blocker** (sector, direction, distance, lat/lon, near/far), the share blocked within 1 km, the share **below the Moon's own horizon** (not fixable by mast or move), and a `text` explanation |

**UI ideas:** a "next sunset in 12 h" countdown on the timeline scrubber; draw a line from the site to `dominant` on the map; show `summary` as the first thing a user reads.

### `POST /rescue` — what's the smallest fix?

Request: identical to `/analyze`, plus an optional `max_shift_days` (1–366, default 60). Response:
- `baseline`: the mission's metrics and status as requested;
- `options`: each changes **one** thing: `kind` (`mast`, `antenna`, `date_earlier`, `date_later`, `move_nearest`, `move_best`), `fixes` (true if every limit then passes), `change` (e.g. `{"solar_mast_height_m": 8.0}` or `{"start_utc": …, "shift_hours": …}` or the moved-to point's coordinates, distance and bearing), `outcome` (metrics and status after the change) and `text`;
- `notes`: caveats, e.g. when no nearby point or shifted start passes.

Move options search ±800 m on demand at the requested heights; `change` also carries `terrain_detail` (`high` / `standard`) and the point's ground height. Every reported move is exact: `/analyze` at that point gives the same outcome. A first rescue takes about **13 s** (about 7 s on repeat). **Show a progress indicator.** **UI idea:** a "Fix this mission" button on any failing result, listing the options as cards with a one-click "apply" for mast and date changes.

## Errors

Validation errors (wrong types, out-of-range fields, unknown fields) return **422** with FastAPI's standard `detail` list. Service errors return:

```json
{"error": "<code>", "message": "<explanation>", "...": "details"}
```

| Status | `error` | When | Details included |
|---|---|---|---|
| 404 | `site_unavailable` | Coordinates outside the covered area (north of 86.70°S or at the pole), or the server has no regional terrain and no curated site is within 100 m | `supported` list, `custom_point_north_edge_latitude_deg` (or `nearest_site`, `nearest_distance_m`) |
| 422 | `mission_out_of_range` | Start not on a whole hour, mission outside the supported dates, or unreadable `start_utc` | `supported_start_utc`, `supported_end_utc`, `sample_step_seconds_multiple` |
| 422 | `too_many_starts` | A `/calendar` request would evaluate more than 20,000 start dates | — |
| 503 | `data_unavailable` | Server data not loaded, or a result would contain "unknown" visibility (not expressible in v1) | `missing` |

## Performance (measured 2026-11-14, in-process, the plan's standard workload: 2 sites, 14 days, hourly)

| Case | Time | Response size |
|---|---|---|
| First request for a mast/antenna height (horizons computed) | about 1.5 s | 126 KB |
| Repeat request (horizons cached) | about 5 ms | 126 KB |
| New solar-mast **and** antenna heights for both sites | about 3.0 s | 126 KB |
| One-year mission, cached | about 70 ms | 1.4 MB |

| Custom point, first request (horizon computed on demand) | about 2–3 s | 126 KB |

Horizons are cached per site and height for the server's lifetime, and for the 16 most recently used custom points. Network time is not included.

## Cross-origin access

Set `LLSN_CORS_ORIGINS` to the frontend's origin(s), comma separated, before starting the server, e.g. `LLSN_CORS_ORIGINS=https://app.example.org,http://localhost:5173`. With it unset, no cross-origin access is allowed.
