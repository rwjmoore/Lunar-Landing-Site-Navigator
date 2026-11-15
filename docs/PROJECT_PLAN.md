# PROJECT_PLAN.md — Lunar Landing Site Navigator

> **Purpose:** Execution plan for an AI coding agent and a two-engineer team building a NASA Space Apps Challenge prototype.
>
> **Primary objective:** Deliver a deployable web application for rapid, explainable comparison of lunar south-pole landing sites and mission dates, using terrain-aware Sun/Earth line-of-sight (LOS) and configurable vehicle parameters.
>
> **Execution policy:** Implement the MVP end to end before adding stretch features. Prefer a scientifically defensible, well-tested result over a broad but unreliable prototype. Do not invent results or silently substitute simulated data for NASA-derived data.

## 1. Product vision

Mission design is iterative. Engineers and mission planners need to adjust landing locations, operating dates, and vehicle parameters quickly to understand whether a concept is feasible. This product lowers the barrier to performing those trade studies.

The application must let a user:
1. Choose one or more candidate sites near the lunar south pole, including a mission start time and duration.
2. Inspect a **360° local terrain horizon** and the Sun/Earth positions and trajectories over time.
3. See terrain-adjusted lighting, direct-to-Earth LOS, and derived operational metrics.
4. Change vehicle parameters (starting with **solar-panel mast height**) and see recomputed metrics and horizon geometry.
5. Compare candidates with a **transparent, constraint-aware score and reasons for failure**.
6. If time allows, explore nearby sites or alternative configurations through a basic optimizer.

**Core differentiation:** A fast, explainable engineering trade-study tool—not simply a lunar map or a visualization of astronomical tracks.

## 2. Scope and priorities

### P0 — Must ship (MVP)

| ID | Requirement | Acceptance criteria |
|---|---|---|
| R1 | Terrain-aware sunlight LOS | For a selected lunar surface site and requested timestamps, produce Sun azimuth/elevation, local horizon elevation by azimuth, and visible/obstructed status. |
| R2 | Terrain-aware Earth LOS | Produce corresponding Earth azimuth/elevation and visible/obstructed status for the same timestamps and site. |
| R3 | Temporal environment | Return consistent, timestamped time series over a configurable mission window, with explicit UTC convention and sample cadence. |
| R4 | Mission metrics and scoring | Show solar visibility fraction, maximum continuous darkness, Earth visibility fraction, maximum continuous Earth blackout, and an explainable feasible/infeasible assessment based on user-defined constraints. |
| R5 | Multiple-site comparison | Compare at least **two** candidate sites side by side using the same mission interval, assumptions, and metrics. A discrete comparison suffices; a dense heatmap is not required for MVP. |
| R6 | Web UI | A deployable app with site/time selection, 360° horizon visualization, animated or scrubbable Sun/Earth positions, metric breakdown, and comparison view. |
| R7 | Vehicle configuration | A solar-panel mast-height control changes the Sun observer location, its horizon/LOS results, and resulting metrics. Show baseline vs modified results. |
| R8 | Performance | **Target <5 seconds** for a warmed, cached or precomputed standard comparison query. Measure and report latency; document first-load and uncached limitations rather than misrepresenting them. |
| R9 | Reproducibility | Include pinned dependencies, data provenance, local setup, tests, and a deterministic demo case. |

**Power generation potential (P0, explicitly simplified):** Report solar access as a proxy for power-generation opportunity. If a power model is implemented, require documented vehicle power parameters and label outputs as idealized estimates. **Do not equate visibility percentage with electrical energy.**

### P1 — High-value extensions (only after P0 works)

- Separate antenna height from solar-panel mast height and recompute Earth LOS independently.
- Mission feasibility margins and **simultaneous** Sun/Earth visibility windows.
- **Mission Rescue:** recommend small changes to mast height, mission start date, or a predefined alternate site, with quantified trade-offs and physical explanations.
- Clickable south-pole 2D map; choosing an available site updates the analysis.
- Basic localized candidate search around a point, within a bounded set of terrain cells/locations.
- Source of dominant terrain horizon obstruction (bearing and approximate distance), if derived reliably from the terrain data.

### P2 — Nice to have / stretch

- Continuous landing-site suitability heatmap (requires bounded spatial coverage and clear metric assumptions).
- Terrain slope / landing-location grade.
- Usable landing area around a site, subject to DEM resolution and landing-dispersion assumptions.
- Distance to nearest permanently shadowed region (PSR), if an authoritative PSR mask is available.
- Terrain-aware walking/rover route distance to a PSR (not straight-line distance).
- Mission start-date flexibility across a longer window.
- Sensitivity to DEM resolution, site-location uncertainty, or timing uncertainty.
- More detailed spacecraft energy model (solar-array pointing, incident angle, generation, load, storage).
- LOS to additional lunar orbiting satellites **only if** a verified orbit/ephemeris source and coverage constraints are available; otherwise omit.

### Explicitly out of scope for MVP

- Full spacecraft trajectory design, launch window optimization, or Earth-to-Moon transfer mechanics. Only assess *surface mission start dates*.
- Guaranteed RF-link availability from geometric Earth LOS alone.
- Certification of safe landing zones from coarse topography alone.
- Global, high-resolution computation of every lunar surface location.
- Custom photorealistic 3D terrain engine or ROS/robotics middleware.
- Unvalidated AI-generated suitability scores.

## 3. Suggested technology stack

Choose the smallest implementation that both engineers can maintain.

- **Physics and processing:** Python, NumPy, SciPy; Rasterio / PyProj for georeferenced raster access and transformations.
- **Astronomy:** a single primary ephemeris adapter based on JPL Horizons or local SPICE (SpiceyPy); use the other as a validation reference if practical. Cache requests and retain kernel/source versions.
- **Backend/API:** FastAPI and typed Pydantic request/response models.
- **Frontend:** React + TypeScript, with a plotting library such as Plotly.js for horizon, time-series, and comparison charts.
- **Map:** lightweight 2D lunar south-pole map, using verified imagery/DEM raster layers or a simple projected map with correctly mapped coordinates.
- **Data:** local cached/preprocessed LOLA DEM crops and ephemeris samples; JSON or compressed array files are sufficient for the MVP. No database server is required.
- **Deployment:** one straightforward web deployment with a documented start command and a reproducible offline demonstration mode.

**Alternative:** If neither engineer is comfortable with React, a Python-first Dash + Plotly implementation is acceptable. Pick one frontend stack and do not build both.

## 4. Architecture and ownership

Keep the numerical core independent of the web framework.

```text
lunar-landing-site-navigator/
├── PROJECT_PLAN.md
├── README.md
├── backend/
│   ├── app/
│   │   ├── api/                # FastAPI endpoints + request/response schemas
│   │   ├── astronomy/          # Ephemeris adapters, UTC/time handling
│   │   ├── coordinates/        # Lunar frames and local azimuth/elevation
│   │   ├── terrain/            # DEM loading, reprojection, horizon profiles
│   │   ├── physics/            # Pure LOS/visibility and temporal metrics
│   │   ├── planning/           # Feasibility, explanations, scoring, optimization
│   │   └── data/               # Data-source adapters, caching, provenance
│   └── tests/
├── frontend/
│   └── src/
│       ├── components/        # Mission controls, horizon, timeline, metrics
│       ├── views/             # Single site, comparison, optional map
│       ├── api/               # Typed API client
│       └── types/             # Shared contract types
├── scripts/                   # Fetch, preprocess, validate and precompute
├── data/                      # Small manifests/sample assets; large files ignored
└── docs/                      # Conventions, assumptions, validation, demo
```

### Engineer / agent workstreams

**Workstream A — physics and data:** coordinate contracts; DEM ingestion; Sun/Earth positions; local horizon profile; LOS over time; metric generation; numerical validation; caching/precomputation.

**Workstream B — interface and product:** web shell; site and vehicle controls; 360° horizon graph; time scrubber; metrics; candidate comparison; map; deployment; demo.

**Shared contract first:** Agree on typed requests/responses and a representative fixture JSON before developing independently. Frontend must run against the fixture until live backend is ready.

See docs/frontend-backend_interface.json for the interface

### Domain model

The backend separates **user inputs**, the reusable **physical environment**, and **derived results**. Each layer has its own cache key, so recomputation is limited to what actually changed.

```text
Inputs (user-selected)
  Site              name, latitude_deg, longitude_deg_east, terrain artifact reference
  MissionWindow     start_utc, duration_hours, sample_step_seconds
  Vehicle           solar_panel_mast_height_m, antenna_height_m (see §5.7)
  Constraints       max_darkness_hours, max_earth_blackout_hours
  MissionCandidate  = Site + MissionWindow + Vehicle (+ display name)

Environment (physical, constraint-free, cacheable)
  HorizonProfile    (site, observer_height, DEM version, params) → azimuth_deg[], elevation_deg[],
                    source_range_m[], source_tier[], no_data[]
  SkyTrack          (site, mission window) → timestamps, sun_az/el[], earth_az/el[]
  Environment       = SkyTrack + HorizonProfile lookup for a given observer height

Results (derived)
  Visibility        (HorizonProfile, SkyTrack) → sun_visible[], earth_visible[] (true/false/unknown)
  Assessment        (MissionCandidate, Constraints) → metrics, feasibility, margins, diagnostics
```

Rules:

- **Terrain is static, sky is time-varying, metrics are aggregates.** Metrics (§5.5) are properties of an Assessment over a mission window, not of a location.
- **The horizon depends on observer height**, so it is keyed by height. Solar and Earth visibility may use different `HorizonProfile`s (mast vs antenna height).
- **Time series are stored as parallel arrays** (one NumPy array per quantity), never as lists of per-timestamp objects. This matches the API contract.
- **Baseline vs modified vehicle (R7)** = two Assessments that share one `SkyTrack` and differ only in `HorizonProfile`.
- **Comparison (R5)** = a list of Assessments built from one shared `MissionWindow` and `Constraints`, enforced by construction rather than by convention.
- **Changing constraints** re-runs only the Assessment step; Environment and Visibility are reused.
- Domain objects live in the numerical core (`physics/`, `planning/`) and are independent of FastAPI; `api/` maps an Assessment to the response contract (whose `candidate` object combines inputs and results for frontend convenience).

## 5. Core scientific model

### 5.1 Coordinate and time conventions — lock before implementation

Document and test:

- Lunar latitude/longitude sign and longitude direction/range (east-positive recommended), and reference radius/datum used by each dataset.
- Native CRS/projection and height definition of each DEM product. A south-polar stereographic DEM needs correct CRS metadata and map-to-world transformation.
- A single **Moon-centered Moon-fixed** Cartesian frame for terrain geometry; convert ephemeris directions into that frame with a verified frame definition.
- Local **east, north, up** directions at the observer; azimuth is **clockwise from north**, elevation is above the local geometric horizon.
- Time values are UTC ISO 8601 strings at the API boundary; internally use the timescale required by the ephemeris library and convert explicitly.
- Units: metres for distance and observer height, radians for internal angles, degrees for displayed azimuth/elevation, seconds/hours for durations.

Do not assume geocentric Earth conventions apply directly to lunar surface observations. Avoid treating the Moon as a flat plane when computing distant terrain obstruction.

### 5.2 Inputs and datasets to establish

The physics engine needs:

1. **Lunar terrain elevations:** LOLA-derived DEM around each candidate location, including its projection, elevation datum, resolution, coverage and no-data mask.
2. **Sun and Earth topocentric directions over time:** either directly returned by an appropriate lunar observer ephemeris query, or computed from Moon/Sun/Earth ephemerides and lunar orientation kernels. Do not request redundant absolute positions when the required apparent directions are directly available.
3. **Observer coordinates:** latitude, longitude, local surface height and independent sensor/solar-panel heights above local terrain.
4. **Mission window:** start time, duration, sample interval.
5. **Mission constraints:** darkness and communication blackout tolerances; any optional engineering parameters.

**Decision D1 (resolved) — astronomy backend:** **SpiceyPy (local SPICE kernels) is primary**; JPL Horizons is a validation reference only. Rationale: offline, deterministic, no runtime network dependency. Sun and Earth directions are computed **topocentrically from the site position in `MOON_ME`** (`spkcpo`, aberration `LT+S`). Topocentric treatment is mandatory for Earth: the lunar-radius parallax is 1737.4 / 384,400 ≈ 0.26°, which is not negligible near the horizon. Kernel set and frame details are recorded in `docs/SCIENCE_CONVENTIONS.md`. **M1 must still verify** 3–5 timestamps per demo site against Horizons before D1 is considered validated.

**Decision D2 (resolved) — terrain data and horizon radius:** Two-resolution terrain from NASA PGDA (Barker et al. LOLA products):

| Role | Product | Resolution | Range from observer |
|---|---|---|---|
| Near-field | 5 m/px LOLA mosaic, 87–90°S (PGDA 81), or per-site 5 m/px DEMs (PGDA 78) | 5 m | 0 – ~10 km |
| Far-field | 20 m/px LOLA DEM, 80–90°S (`LDEM_80S_20MPP_ADJ.TIF`, PGDA 90), downsampled offline to ~100 m | ~100 m | ~10 – 200 km |

**Horizon search radius: 200 km.** Justification: at the south pole the Sun's elevation stays within roughly ±1.5° of the local geometric horizon, so terrain *below* 0° still matters. A feature of relative height *h* at range *d* appears at elevation ≈ *h/d − d/(2R)*; for a 5 km massif to fall below −1.5° requires *d* ≈ 186 km. A small local crop would therefore overestimate illumination.

Demo sites should be chosen from the Mazarico et al. (2011) numbered sites that have Barker 5 m DEMs (Sites 1, 4, 7, 11) so published illumination results are available for validation. **M1 must still verify** that the selected files are downloadable, check their CRS/datum metadata, and inspect the `LDEC` count map for sparse/no-data coverage. Large source rasters are never committed or shipped; only per-site derived artifacts are (see §5.3).

### 5.3 360° terrain horizon projection

**Method: azimuthal ray-marching** (not full-raster projection). Projecting every DEM pixel within 200 km at 5–20 m resolution is ~10⁸ points per site per height; ray-marching samples only what each azimuth needs and naturally records the obstruction range.

For a selected site and observer height *h_obs*:

1. Place the observer at DEM surface height (bilinear interpolation) + *h_obs*, in Moon-fixed Cartesian coordinates on the 1737.4 km reference sphere.
2. Cast **1440 rays (0.25° azimuth spacing)**. Along each ray, step outward on the great circle with **range-adaptive spacing** (step ≈ local DEM pixel size, growing with range).
3. Convert each sample (azimuth, range) → lat/lon → polar-stereographic x/y; bilinearly sample terrain height from the appropriate resolution tier.
4. Compute each sample's elevation angle in the observer's local east/north/up basis (formula below).
5. Per ray, retain the **maximum elevation** and the **range (and position) of the sample that produced it**.
6. Skip samples within ~2 pixels of the observer to avoid self-occlusion artifacts from the observer's own cell.
7. Mark a ray **`no_data`** if any sample before its maximum falls on missing/out-of-coverage terrain. No-data must never be treated as unobstructed.
8. Produce `horizon_elevation_deg[azimuth]` with explicit 0°/360° seam handling.

**Near-field / far-field split.** Raising the observer by Δh changes the apparent elevation of terrain at range *d* by ≈ Δh·cos²α / *d* (≈0.57° at 1 km, 0.06° at 10 km, 0.01° at 50 km for Δh = 10 m). Therefore:

- **Far-field horizon (~10–200 km)** is precomputed **once per site** offline at the base observer height, storing per-azimuth max elevation and source range. At request time, apply the analytic Δh correction using the stored range.
- **Near-field horizon (0–~10 km)** is recomputed per observer height (solar mast, antenna) from the 5 m crop.
- **Combined horizon** = `max(near_field(h), far_field_corrected(h))` per azimuth bin. Keep both components available for diagnostics (P1 dominant-obstruction source).
- The exact near/far boundary is a tunable parameter; validate in M2 that moving it does not change results beyond a documented tolerance.

**Shipped per-site artifact** (small, e.g. `.npz`): near-field DEM crop (+ count/quality mask), far-field horizon profile with source ranges, and provenance metadata. Source GeoTIFFs stay out of the repo and the deployment.

**Performance expectation (unverified until M2 benchmark):** a 1440-ray near-field march is a few million bilinear samples, expected to run in well under a second with NumPy. If confirmed, horizons can be computed on demand for arbitrary observer heights; otherwise precompute a height ladder for the demo sites.

Cache profiles keyed by site, observer height, DEM version and processing parameters.

For relative vector **r**, local up **u**, and horizontal component **r_h**:

\[
\alpha = \operatorname{atan2}(\mathbf r\cdot\mathbf u,\|\mathbf r_h\|),\qquad
\mathbf r_h=\mathbf r-(\mathbf r\cdot\mathbf u)\mathbf u
\]

Use Moon-fixed geometry to capture curvature; a flat-plane approximation is not sufficient for long-range horizons. The horizon projection is a **scientific plotting profile**, not a photorealistic lunar streetscape.

### 5.4 Sun and Earth LOS over time

For each requested sample time, obtain local azimuth/elevation for Sun and Earth. Then evaluate:

\[
V_{body}(t)=\big[e_{body}(t)>H(a_{body}(t);\,h_{observer})\big]
\]

Implement interpolation of `H` across adjacent azimuth bins. Use the solar mast observer height for Sun LOS and antenna observer height for Earth LOS if independently modeled; otherwise document the shared-height simplification.

A point-source binary visibility approximation is acceptable for MVP; note the omitted apparent angular radii, partial solar disk exposure, and antenna/radio-link constraints. Because the Sun's angular radius (~0.27°) is comparable to its elevation excursion at the pole, **visible solar-disk fraction is a P1 priority**: compute it from the same horizon profile once binary LOS works.

Earth azimuth/elevation must be **topocentric** (see D1): the ~0.26° lunar-radius parallax is significant relative to Earth's near-horizon elevation at the south pole.

**Important physical rule:** Increasing solar-panel mast height must change the **local terrain-horizon clearance**, not the astronomical Sun's apparent elevation as reported by the UI (apart from negligible topocentric parallax). The mockup's previous apparent-altitude change is illustrative UI only, not valid physics.

### 5.5 Derived metrics

Return for every candidate over the *same sampled time window*:

- `sun_visible_fraction`: visible time / total modeled time.
- `max_continuous_darkness_hours`: longest interval with Sun obstructed.
- `earth_visible_fraction`: direct geometric Earth LOS fraction.
- `max_continuous_earth_blackout_hours`: longest interval with Earth obstructed.
- `joint_sun_earth_fraction` (P1): both visible simultaneously.
- `sun_clearance_deg` and `earth_clearance_deg` (optional series): body elevation minus terrain horizon in that azimuth.
- `solar_generation_opportunity`: clearly labeled visibility-based proxy for MVP; only calculate energy if a documented explicit power model is implemented.

Use time-aware interval accounting and define treatment of interval endpoints, missing samples, and intervals extending to mission boundaries. Display the sample cadence and DEM resolution.

### 5.6 Explainable scoring and failure diagnostics

Avoid arbitrary universal weighted scores that allow a fatal constraint violation to be compensated by unrelated advantages.

**MVP scoring approach:**

1. Evaluate each hard mission constraint, e.g. `max_darkness_hours <= configured_limit` and `max_earth_blackout_hours <= configured_limit`.
2. Mark a candidate **feasible** only if all enabled constraints pass.
3. Report per-constraint signed margins and list failed constraints with measured values, limits, and worst interval timestamps.
4. For feasible candidates, present an optional, explicitly defined ranking based on specified user priorities (e.g. higher sunlight fraction, higher Earth visibility, larger normalized constraint margin). Show the underlying metrics, not just one number.
5. If a score is displayed, document its exact formula, units, normalization, and meaning. A score is not a probability of mission success.

A diagnostic explanation should say **what failed, when, by how much, and which terrain direction contributed** when this can be established from stored horizon-source samples.

### 5.7 Vehicle model

Start with:

```text
VehicleConfiguration:
  solar_panel_mast_height_m: float  # P0; required, bounded >= 0
  antenna_height_m: float           # P1; independent from solar mast
  battery_capacity_wh: float?      # P2; only if energy model exists
  load_power_w: float?             # P2
  solar_peak_power_w: float?       # P2
```

When mast height changes:
- Recompute/retrieve the Sun horizon profile for that observer position.
- Recalculate Sun visibility, maximum darkness, and dependent feasibility/score.
- Keep Earth LOS unchanged unless antenna height or a deliberately shared observer height changes.
- Return **baseline and new** metrics and show the difference in the frontend.

Do not assume increasing mast height always makes an infeasible mission feasible; the result depends on obstruction geometry.

## 6. Frontend UX and visualization specifications

### Main screen: single-site mission analysis

**Left — Mission and vehicle configuration**
- Landing-site selector with latitude/longitude (and terrain altitude when derived from the DEM).
- UTC start time, mission duration, and time-step selection.
- Maximum permissible darkness and Earth blackout as mission constraints.
- Highlighted **Solar Panel Mast Height** slider and numeric input.
- Optional antenna height and other vehicle parameters when implemented.
- `Run Analysis` / responsive recomputation. Optional `Find Feasible Configuration` only when a working optimization backend exists.

**Center — 360° lunar horizon**
- A simplified, non-textured 360° panorama plotting terrain-horizon **elevation against azimuth** (0°–360°).
- Overlay current Sun and Earth markers with azimuth/elevation readouts.
- Overlay time-window trajectories with distinct colors, clear labeling, and a view of when tracks pass above/below terrain.
- Timeline scrubber with play/pause and timestamp; synchronize all plots and statuses.
- Compare baseline/current horizon curves when vehicle height changes; make the clearance effect visually obvious.
- Use an honest angular projection: horizontal axis = azimuth and vertical axis = elevation. If adding decorative imagery, do not obscure the underlying scale.

**Right — Mission assessment**
- Solar access (%), longest darkness (hours), Earth access (%), longest Earth blackout (hours).
- Feasible/infeasible indicator against user-defined constraints.
- Before/after deltas for vehicle changes.
- Clear description of the dominant constraint and relevant mission interval.

**Below — Temporal plots**
- Sun/Earth elevation vs time and, where useful, horizon clearance vs time.
- Continuous visibility/blackout interval timeline; important outages clickable to scrub the panorama.

### Multiple-site comparison

- Table containing consistent metrics, constraint status, and concise pros/cons for at least two selected sites.
- Selecting a row updates the panorama and timeline.
- P1/P2: south-polar map with clickable candidate locations, followed by heatmap if performance and coverage support it.

**UX principle:** The first page must explain a mission result in seconds without requiring the user to understand the underlying mathematics.

## 7. Backend ↔ frontend interface

Use typed JSON API responses; keep offline JSON fixtures for UI development and a deterministic demo. The following is the **proposed contract**; update both ends together if changed.

### API endpoints

| Endpoint | Purpose |
|---|---|
| `GET /health` | Readiness and dataset status. |
| `GET /sites` | List supported demo sites, coordinates, coverage and metadata. |
| `POST /analyze` | Evaluate one site, mission window, constraints and vehicle configuration. |
| `POST /compare` | Evaluate 2+ sites with consistent configuration and return comparable candidates. |
| `POST /optimize` (P1) | Bounded search over allowed site/date/height configurations with explicit objective/constraints. |
| `GET /data-provenance` | Describe DEM, ephemeris sources/versions and assumptions. |

### Example `POST /analyze` request

```json
{
  "site": {"name": "South Pole Site A", "latitude_deg": -89.92, "longitude_deg_east": 23.45},
  "mission": {"start_utc": "2030-11-20T12:00:00Z", "duration_hours": 336, "sample_step_seconds": 3600},
  "vehicle": {"solar_panel_mast_height_m": 2.0, "antenna_height_m": 2.0},
  "constraints": {"max_darkness_hours": 24, "max_earth_blackout_hours": 12}
}
```

### Example response shape (illustrative, no scientific results implied)

```json
{
  "candidate": {
    "name": "South Pole Site A",
    "location": {"latitude_deg": -89.92, "longitude_deg_east": 23.45, "surface_elevation_m": null},
    "vehicle": {"solar_panel_mast_height_m": 2.0, "antenna_height_m": 2.0},
    "metrics": {
      "sun_visible_fraction": null,
      "max_continuous_darkness_hours": null,
      "earth_visible_fraction": null,
      "max_continuous_earth_blackout_hours": null
    },
    "feasibility": {"status": "unknown", "failed_constraints": [], "margins": {}},
    "horizons": {
      "azimuth_deg": [],
      "sun_observer_horizon_elevation_deg": [],
      "earth_observer_horizon_elevation_deg": []
    },
    "series": {
      "timestamps_utc": [],
      "sun_azimuth_deg": [], "sun_elevation_deg": [], "sun_visible": [],
      "earth_azimuth_deg": [], "earth_elevation_deg": [], "earth_visible": []
    },
    "diagnostics": [],
    "provenance": {"dem_id": null, "ephemeris_id": null, "sample_step_seconds": 3600}
  },
  "computation_ms": null
}
```

Never ship `null` or placeholder metric values as real analysis results. Return a documented error or `status: unavailable` if a requested site/time lacks supported data.

## 8. Performance and precomputation strategy

The `<5 s` target applies to a documented standard workload, e.g. 2 supported preprocessed south-pole sites over a 14-day mission with hourly samples. Benchmark locally and in the deployed app. Distinguish cold vs warm runs.

- Cache ephemeris time series or reusable source vectors for the supported time range.
- Cache terrain horizon profiles by location and observer height; precompute a modest set of heights for the demo if necessary.
- Vectorize time-series LOS comparisons with NumPy.
- Keep DEM crops compact and bound horizon distance/azimuth resolution deliberately.
- Avoid live third-party network calls in the primary demo path.
- If arbitrary coordinates cannot reliably meet the response target, restrict live analysis to supported points and label unavailable map areas clearly.
- Store a small set of verified reference scenarios so the application remains demonstrable without external services.

## 9. Execution milestones (in order)

### M0 — Contract and project skeleton

**Tasks:** Select a stack; establish repository structure; create fixture JSON and type definitions; document local setup and commands; identify owners.

**Done when:** Frontend displays fixture output; backend serves `/health`; schema validation/tests run in CI or via one local command.

### M1 — Lock reference frames, data and scientific source

**Tasks:** Choose 2–3 demo sites (§5.2 D2); confirm availability, size and metadata of the D2 terrain products; cut per-site near-field crops and a downsampled far-field raster; obtain verified lunar-site Sun/Earth trajectories via SpiceyPy and cross-check against Horizons; implement and test local ENU mapping and azimuth/elevation conversion; complete the open items in `docs/SCIENCE_CONVENTIONS.md`.

**Done when:** A known site has a defensible sample topocentric Sun/Earth direction and terrain mapping, cross-checked against an independent reference.

**Hard gate:** If M1 is blocked, don't build a custom raster pipeline blindly. Reduce site coverage and use verified precomputed data.

### M2 — Physics MVP

**Tasks:** Build terrain horizon projection; calculate Sun/Earth LOS for a time series; derive all P0 metrics; add unit tests and provenance; cache calculations.

**Done when:** Two distinct supported sites produce reproducible horizon + Sun/Earth time-series results; physical consistency checks pass.

### M3 — Working end-to-end web demo

**Tasks:** Integrate `/analyze`; implement 360° horizon, Sun/Earth time scrubber, metric cards; implement two-site comparison.

**Done when:** User can select a supported site and timeframe, inspect the modeled horizon and Sun/Earth visibility, and compare two candidates.

### M4 — Vehicle trade studies

**Tasks:** Add mast-height configuration; recompute and display baseline vs adjusted horizon/visibility/metrics; show feasibility margins.

**Done when:** Changing solar-panel mast height produces physically consistent horizon changes and corresponding metric differences where warranted. No fabricated improvements.

### M5 — Explainability and mission assistance

**Tasks:** Show failed requirements, responsible time intervals, candidate pros/cons; optionally add the bounded optimizer over heights/dates/nearby available sites.

**Done when:** User can explain why a candidate fails and compare at least one feasible change *when the data supports one*.

### M6 — Deploy, test, demonstrate

**Tasks:** Verify startup/deployment, test cold and warm latency, audit units/labels, check edge cases, record demo, write submission explanation and source attributions.

**Done when:** Public URL works, results are reproducible, limitations are documented, and the final demo can run without external ephemeris service access.

### Suggested two-engineer timeline

| Phase | Physics/data engineer | Frontend/product engineer |
|---|---|---|
| Early | M1: dataset & coordinate conventions | M0: shell & fixture UI |
| Middle | M2: horizon + LOS + metrics | M3: panorama + timeline + comparison |
| Integration | M4: height + caching | M4: vehicle controls + before/after |
| Finish | Validation + M5 only if time | Demo, deployment + M5 only if time |

**Scope rule:** If the scientific engine or deployment is incomplete, skip the map heatmap, generalized optimizer, PSR routing, orbital satellites, and detailed power model.

## 10. Testing and scientific validation

### Required unit/invariant tests

- ENU basis is orthonormal and consistent with selected azimuth/elevation conventions.
- Coordinate round-trips and CRS conversions at representative south-polar coordinates.
- Horizon profile wraps correctly from 359.x° to 0°.
- Flat/unobstructed synthetic terrain yields expected LOS results.
- Synthetic ridge blocks a body at the expected azimuth/elevation.
- Increasing observer height does not reduce terrain geometric LOS under a fixed terrain model and sampling setup (check for numerical artifacts).
- Changing **solar-panel** mast height does not modify computed Earth LOS when antenna height is fixed.
- No-data/out-of-coverage terrain does not silently become unobstructed terrain.
- Darkness/blackout interval metrics behave correctly at the boundaries and for always-visible / never-visible cases.
- Two-site comparison uses identical mission duration, cadence, and constraints.
- API validates latitude, longitude, duration, cadence, and nonnegative vehicle heights.

### Validation against external scientific sources

- Cross-check multiple Sun/Earth azimuth/elevation samples against JPL Horizons or another verified planetary-geometry reference.
- Where compatible published products exist, compare terrain-related illumination results at matching sites, dates, observer heights and terrain resolutions. Planned references:
  - **Primary:** Mazarico et al. (2011) LOLA polar illumination and Earth-visibility maps (PGDA 69, 60 m and 240 m/px). Run the pipeline over a long window at a Mazarico numbered site and compare average Sun/Earth visibility; differences from resolution and averaging period must be documented, not tuned away.
  - **Secondary:** LROC WAC percentage-based south-pole illumination map (88–90°S, 100 m/px).
  - **Optional:** Bertone shape-from-shading products for Artemis III candidate regions (PGDA 104).
- Near/far-field split invariance: moving the split boundary must not change the combined horizon beyond a documented tolerance.
- Document discrepancies due to DEM coverage, frame definitions, sampling cadence, point-source approximation, and numerical approximations.
- Include a visible provenance/assumptions page in the app or README.

## 11. Final demo storyboard

Use **real computed values** from a verified south-pole site. Prefer a site near an area of scientific interest/possible water ice, but avoid asserting an ice deposit exists without an authoritative source.

1. **Locate:** Show the selected south-pole landing location, coordinates and nearby terrain. Explain what the model computes.
2. **Understand:** Display the 360° horizon, moving Sun and Earth, and mission time scrubber. Highlight a real obstruction interval.
3. **Assess:** Show solar access, Earth LOS, longest darkness/blackout, and why a user-defined constraint fails or passes.
4. **Change the vehicle:** Increase the solar-panel mast height and compare the updated terrain horizon and metrics to the baseline. If the improvement is negligible, present that result honestly and switch to a site/date scenario that illustrates a meaningful trade-off.
5. **Compare and rescue:** Compare an alternate candidate; if the optional optimizer is complete, search a bounded nearby region or allowed configurations and show the objective and constraints.
6. **Revisit constraints:** Change an engineering limit and show how the feasible set/ranking changes.
7. **Conclude:** Emphasize rapid engineering iteration and explain exactly which datasets support the analysis and what is not modeled.

**Demo safety net:** Save a verified, self-contained fixture for the chosen sites/dates so the demo is deterministic and does not rely on network ephemeris queries.

## 12. Data resources and references

- **Challenge:** [NASA Space Apps — Lunar Landing Site Navigator](https://www.spaceappschallenge.org/2026/challenges/lunar-landing-site-navigator/)
- **LROC QuickMap:** [Interactive lunar imagery and topographic datasets](https://quickmap.lroc.im-ldi.com/?prjExtent=-3232957.0155902%2C-1737400%2C3232957.0155902%2C1737400&earthShadowEnabled=true&proj=10&stack=3314&defs=N4IgzGCMAsIFygPYAcCGBjAlgFwJ70gF9Cg)
- **NASA Moon Trek:** [Interactive lunar terrain visualization](https://trek.nasa.gov/moon/)
- **JPL Horizons:** [Ephemeris and observer geometry](https://ssd.jpl.nasa.gov/horizons/)
- **NASA SPICE / NAIF:** [Planetary geometry kernels and toolkit](https://naif.jpl.nasa.gov/naif/)
- **LOLA / LRO:** [Lunar Orbiter Laser Altimeter](https://lola.gsfc.nasa.gov/)

**Numerical data products selected (D2 and validation):**

- [PGDA 81 — South Pole LOLA 5 m/px DEM mosaic, 87–90°S](https://pgda.gsfc.nasa.gov/products/81) ([files](https://pgda.gsfc.nasa.gov/data/LOLA_5mpp/87S/)) — Barker et al. (2021), *Planetary & Space Science*.
- [PGDA 78 — High-resolution LOLA topography for south-pole sites](https://pgda.gsfc.nasa.gov/products/78) — 5 m/px per-site DEMs, slope maps, 100 DEM clones (Sites 1, 4, 7, 11).
- [PGDA 90 — A new view of the lunar south pole from LOLA](https://pgda.gsfc.nasa.gov/products/90) — 20 m/px DEM, 80–90°S — Barker et al. (2023), *Planetary Science Journal*.
- [PGDA 69 — Lunar polar illumination](https://pgda.gsfc.nasa.gov/products/69) — Mazarico et al. (2011), *Icarus*; validation reference.
- [PGDA 104 — Shape-from-shading topography for Artemis III candidate regions](https://pgda.gsfc.nasa.gov/products/104) — optional validation/site list.
- [LROC WAC south-pole illumination percentage map](https://data.lroc.im-ldi.com/lroc/view_rdr/WAC_POLE_ILL_PCT_SOUTH) — secondary validation.

Cite each product as its PGDA page requests; record exact filenames, download dates and checksums in data provenance.

The linked mapping tools are **discovery and visualization references**, not automatically suitable numerical data feeds. Identify downloadable datasets and their licensing/attribution and coordinate metadata before using them in calculations.

## 13. Agent execution rules

1. **Start by auditing the repository** and identifying current code, tests, dependencies and supported tools. Do not overwrite working user code or add unnecessary framework layers. Inspect docs/AGENT.md for the coding practices of this project.
2. Maintain a short execution checklist in the PR/working notes. Implement milestone by milestone, and run relevant tests after every physics/API change.
3. Treat the specified science conventions and API contract as authoritative; when deviations are unavoidable, update documentation, tests, and both API consumers together.
4. **Never invent ephemeris results, terrain measurements, performance benchmarks, or validation outcomes.** Mock data is permitted only in clearly labeled fixture/demo code and must never masquerade as real results.
5. Prioritize correctness and provenance of physical results before rendering polish or additional optimizers.
6. Keep network access optional at runtime by using cached/precomputed data for the demo.
7. Prefer a working two-site discrete comparison over an unfinished continuous heatmap.
8. Add only the features supported by real data and testable backend interfaces; do not create UI controls that falsely claim to work.
9. For every completed milestone, provide: changed files, commands/tests run, observed results, known limitations, and next highest-priority task.
10. **Completion definition:** A reviewer can run or open the app, select two supported sites, inspect time-dependent terrain-aware Sun/Earth LOS, change solar-panel mast height, observe accurate before/after metrics, and understand the mission feasibility outcome without reading source code.
