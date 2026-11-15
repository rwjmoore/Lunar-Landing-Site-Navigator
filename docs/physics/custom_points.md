# custom_points.md — Analysis anywhere in the south-polar area

> **Review status: SIGNED OFF (2026-11-15).** Any change to coverage, tiers or the nearby search needs a new review. Option B, approved 2026-11-14: the server keeps the 40 m south-polar terrain and computes horizons on demand for any point in the covered area. No signed-off physics was changed: the same ray caster runs on new points. Reviewed: the coverage limit (§2), the standard-detail tier (§3), and the decision to ship the 40 m map to the server (§5).

Code: `src/backend/app/physics/point_terrain.py`; routing in `src/backend/app/api/service.py` (`terrain_for`). Tests: `tests/test_custom_points.py`.

## 1. What changed

Before, the API only analysed the four curated sites, because only their precomputed horizons were on the server. Now **any latitude/longitude in the covered area** can be analysed: `/analyze`, `/compare`, `/calendar`, `/insights` and `/rescue` all accept it. Routing:

| Requested point | Terrain used | Speed |
|---|---|---|
| Within 100 m of a curated site | That site's precomputed horizon (unchanged) | milliseconds |
| Inside one of the 5 m site maps | **High detail**, computed on demand: 5 m near zone + far zone cast directly over the 40 m map | about 3 s first time, then cached |
| Anywhere else in the covered area | **Standard detail**, computed on demand: the whole ray over the 40 m map | about 2 s first time, then cached |
| Outside the covered area | Refused: `404 site_unavailable` with the coverage edge | — |

The 16 most recently used custom points are kept in memory with their horizons.

## 2. Coverage

Every horizon ray is 200 km long (`PROJECT_PLAN.md` §5.2) and must stay inside the 40 m map, which spans ±304 km from the pole. So a point must lie within **100 km of the pole** on the map, leaving a 4 km margin. In latitude:

$$
\varphi_\text{edge} = 2\arctan\left(\frac{100\ \text{km}}{2R}\right) - 90^\circ \approx -86.70^\circ
$$

Custom points are accepted **south of 86.70°S** and outside 0.001° of the pole (the P1 pole guard). `GET /sites` publishes the edge as `custom_point_north_edge_latitude_deg`.

## 3. The standard-detail tier

Outside the four 5 m maps, the only terrain is the 40 m map. The ray is cast over it from **80 m** (two pixels, so the observer's own pixels can't block it) out to 200 km, with the step at 0.5% of distance up to the 40 m pixel size. This is exactly the configuration of **validation comparison A**, which matched NASA's published illumination and Earth-visibility maps at 100 random points with mean differences of −0.1 and +0.4 percentage points and correlations above 0.99 (`validation.md` §9.1).

**What it does not resolve:** bumps smaller than about 40 m within the first few hundred metres. Those drive mast-height effects (M2 found Site 01's sunlight going from 47% to 85% between a 2 m and a 10 m mast, set by terrain within 1 km). So **mast-height trade-offs at standard-detail points are less certain**. Every standard-detail response says so in its diagnostics, and its `dem_id` says "standard detail".

## 4. Evidence

| Check | Result |
|---|---|
| On-demand point placed exactly at each curated site (high detail, far zone cast directly) vs the curated precomputed horizon, same ground height | **0.00000°** at all four sites |
| Same, using the point's own exact ground height | Up to 0.0024° (Site 01): the site list rounds ground height to 1 cm, and 5 mm against terrain 83 m away is about 0.003°. Far below the terrain's 0.3–0.5 m uncertainty. |
| Standard-detail step halving at 5 scattered points (approved tolerance 0.015°) | worst 0.0013–0.0111° |
| Coverage edge | −86.70°S; every 200 km ray stays inside the map |
| Custom point via the API | Echoes the requested coordinates and name, "standard detail" in `dem_id` and diagnostics |
| Points outside coverage | Refused with the coverage edge |

## 5. Hosting impact (reverses part of `PROJECT_PLAN.md` §8.1)

The server now needs the **40 m regional map** (`data/artifacts/terrain/region_80s_40m/`, 882 MB as 32-bit floats), built by `setup.bat` / `pipeline.build_terrain`. It's **memory-mapped**, so only the parts actually read occupy memory. Server disk goes from about 200 MB to about 1.1 GB. A later optimisation could store it as 16-bit integers with 0.25 m steps (about 440 MB), but that would be a data change needing its own review.

## 6. Mission rescue's nearby search, now on demand

Replaces the earlier precomputed "local maps", which were limited to the four sites and a 2 m reference height:
1. **Screen** 80 candidates on a 9 × 9 grid, 200 m apart (±800 m), using a cheap **approximate** horizon: the candidate's own terrain out to 2 km (5 m map where available, plus the 40 m map) combined with the original point's horizon beyond 2 km, on 1° rays. This is used only to **rank** candidates.
2. **Verify** the two most promising (nearest passing, best margin) with the **full exact horizon** at the **requested** mast and antenna heights. **Only verified results are reported**, and a test confirms that re-analysing a suggested point reproduces the reported outcome exactly.

It works at any point in coverage. A first rescue takes about **13 s** (7 s on repeat); the mast and date options alone take about 5 s.

## 7. Review sign-off

| Stage | Reviewer | Date | Decision / comments |
|---|---|---|---|
| Coverage limit (§2) and routing (§1) | Randy Moore | 2026-11-15 | Approved |
| Standard-detail tier and its caveat (§3) | Randy Moore | 2026-11-15 | Approved |
| Server hosts the 40 m map (§5) | Randy Moore | 2026-11-15 | Approved |
| On-demand nearby search (§6) | Randy Moore | 2026-11-15 | Approved |
