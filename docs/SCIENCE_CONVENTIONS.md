# SCIENCE_CONVENTIONS.md — Lunar Landing Site Navigator

> **Purpose:** The single authoritative statement of coordinate, time, unit, data and geometry conventions used by the physics engine. Code and tests must match this document; if a convention changes, update this file, the tests, and the API contract together (see `PROJECT_PLAN.md` §13).
>
> **Status markers:** **LOCKED** = decided, implement as written. **TO VERIFY (M1)** = decided in principle, but must be confirmed against real data/metadata before M1 is done. Replace each TO VERIFY with the observed value and the date/source of verification.

## 1. Units

| Quantity | Internal | API / display |
|---|---|---|
| Distance, height | metres | metres |
| Angles | radians | degrees |
| Time instants | SPICE ephemeris time (TDB seconds past J2000) | UTC, ISO 8601 with `Z` suffix |
| Durations | seconds | hours |

**LOCKED.** Conversions happen only at the API boundary and in plotting.

## 2. Time

- API timestamps are UTC ISO 8601 strings (e.g. `2030-11-20T12:00:00Z`). **LOCKED.**
- Internally, convert UTC → TDB with SPICE (`str2et` / `utc2et`) using the loaded leapseconds kernel. Never do manual UTC↔TDB arithmetic. **LOCKED.**
- Sample times are `start + k × sample_step_seconds` for `k = 0 … N−1`, with `N = floor(duration / step) + 1`. Each sample represents the interval `[t_k, t_k + step)` for duration accounting; the final sample's interval is truncated at mission end. **LOCKED** (revisit only with a documented reason).

## 3. Lunar body model and reference frame

- **Body-fixed frame: `MOON_ME`** (mean Earth / polar axis), because the LOLA DEM products are delivered in MOON_ME. **LOCKED.**
- **Reference surface: sphere, R = 1737.4 km.** DEM heights are relative to this sphere. **LOCKED**: every terrain file declares this sphere, and the 5 m and 40 m products agree to under 0.25 m on average (`docs/physics/terrain.md` §8.1).
- **Coordinates:** planetocentric latitude; **east-positive longitude**, range `[0°, 360°)` internally. The API accepts `longitude_deg_east` in `[−180°, 360°)` and normalizes. **LOCKED.**
- **Frame realization:** the PGDA DEMs are MOON_ME as realized with DE421, and the ephemeris uses DE421 too, so no offset is needed. **LOCKED** (§11).

## 4. Terrain data (decision D2)

| Tier | Product | Native resolution | Used range | Status |
|---|---|---|---|---|
| Near-field | PGDA 78 per-site 5 m DEMs (`SiteNN_final_adj_5mpp_surf.tif`, 16 × 16 km each) | 5 m | 0 – per-site radius, max 8 km (7.9925 km; Site 04: 6.305 km) | **LOCKED** |
| Far-field | PGDA 90 `LDEM_80S_40MPP_ADJ.TIF` (80–90°S, ±304 km) | 40 m | 8 – 200 km | **LOCKED** |
| Count map | Matching `LDEC` (LOLA returns per pixel), inspection only | 5 m | — | **LOCKED** |

Files and checksums: `data/manifests/terrain.json`. Details and evidence: `docs/physics/terrain.md`.

- **Projection:** `+proj=stere +lat_0=-90 +lat_ts=-90 +lon_0=0 +x_0=0 +y_0=0 +R=1737400`, read from every file and enforced by the build. **LOCKED.**
- **Sampling:** bilinear interpolation between pixel centres (files are pixel-registered). **LOCKED.**
- **No-data:** NaN pixels, or points outside coverage, are **unknown**, never zero height and never unobstructed. Interpolated pixels (`LDEC` = 0, ~90% of 5 m pixels) are used as heights, not masked; the measured fraction is reported in provenance. **LOCKED** (approved in P3).
- **Repository policy:** source GeoTIFFs are never committed. Only derived per-site artifacts (near-field crop, far-field horizon profile, provenance) are versioned or shipped. **LOCKED.**

## 5. Local observer frame and angles

At observer position **p** (Moon-fixed Cartesian, metres):

- **up** `u = p / |p|` (radial, on the reference sphere).
- **east** `e = normalize(ẑ × u)` where ẑ is the MOON_ME +Z (north pole) axis.
- **north** `n = u × e`.
- Exactly at a pole, `ẑ × u` is degenerate. Demo sites must not be at exactly ±90°; the API rejects `|latitude| > 89.999°` unless a pole-specific basis is implemented. **LOCKED.**

For a relative vector `r = target − p`:

- **Elevation** `α = atan2(r·u, |r − (r·u)u|)`, positive above the local geometric horizon.
- **Azimuth** `A = atan2(r·e, r·n)` mapped to `[0°, 360°)`, **clockwise from north** (north = 0°, east = 90°).

**LOCKED.** Unit tests must cover orthonormality of (e, n, u), a target due east giving A = 90°, and a target straight up giving α = 90°.

## 6. Observer heights

- Observer height = DEM surface height at the site (bilinear) + vehicle height above local terrain.
- **Solar observer** uses `solar_panel_mast_height_m`; **Earth observer** uses `antenna_height_m` (P1). Until P1, if one height is shared, the API response must say so. **LOCKED.**
- Vehicle heights change **only** the horizon geometry, never the reported astronomical azimuth/elevation of Sun or Earth (apart from negligible topocentric parallax). **LOCKED.**

## 7. Horizon profile

- **Method:** azimuthal ray-marching, 1440 rays (0.25° spacing), great-circle paths, range-adaptive step ≈ local DEM pixel size. **LOCKED** (spacing tunable via config).
- **Radius:** 200 km. Rationale: the pole Sun's elevation stays within about ±1.5°; terrain of relative height *h* at range *d* appears at ≈ *h/d − d/(2R)*, and a 5 km massif drops below −1.5° only at *d* ≈ 186 km. **LOCKED.**
- **Self-occlusion guard:** ignore samples within 2 near-field pixels (10 m) of the observer. **LOCKED** (value tunable, test sensitivity in M2).
- **Near/far split** at ~10 km (tunable):
  - Near-field (0 – split): recomputed per observer height from the 5 m crop.
  - Far-field (split – 200 km): precomputed once per site at base height; store per-azimuth max elevation **and source range**; apply the height correction Δα ≈ −Δh·cos²α / d at request time.
  - Combined horizon = per-azimuth max of near and corrected far.
- **Per-azimuth outputs:** elevation (deg), source range (m), source tier (near/far), `no_data` flag.
- **Visibility test:** a body at (A, α) is visible iff `α > H(A)`, where `H` is linearly interpolated between adjacent bins with 0°/360° wrap. If either adjacent bin is `no_data`, visibility is **unknown**, not true. **LOCKED.**

## 8. Ephemeris (decision D1)

- **Primary: SpiceyPy with local kernels.** JPL Horizons is used only for validation. **LOCKED.**
- **Geometry:** topocentric. **LOCKED.** Implemented in two stages (see `PROJECT_PLAN.md` §8.1):
  - *Offline sky grid:* SPICE computes Moon-centered `SUN` and `EARTH` vectors in frame `MOON_ME`, aberration correction `LT+S`, on a fixed hourly UTC grid over the supported date range.
  - *Runtime:* topocentric vector = Moon-centered vector − observer MOON_ME position; then convert to (A, α) with §5.
  - *Reference check:* the P2 gate compares this method against direct `spkcpo` queries at the observer position (same frame and correction). Acceptance tolerance **0.001°** (approved; measured worst 2.7e-5°, see §11).
- **Why topocentric matters:** Earth's lunar-radius parallax is ~0.26° (1737.4 / 384,400 rad), which is significant near the horizon. For the Sun it is negligible, but the same code path is used for consistency.
- **Kernel set: DE421** (`naif0012.tls`, `de421.bsp`, `moon_pa_de421_1900-2050.bpc`, `moon_080317.tf`, `moon_assoc_me.tf`). **LOCKED**; checksums in `data/manifests/kernels.json`. DE421 was chosen because the LOLA DEMs use MOON_ME as realized by DE421.
- **Supported dates:** whole UTC hours from 2026-01-01T00:00Z to 2040-12-31T23:00Z. Missions must start on a whole hour and step by whole hours. **LOCKED.**
- **Validation:** Sun/Earth apparent az/el compared against JPL Horizons at test locations on body 301. Acceptance threshold **0.01°** (approved; measured worst 0.00003°, see §11). Explainer and evidence: `docs/physics/sky.md`.

## 9. Visibility model and metrics

- **MVP:** binary point-source visibility of the body center. **LOCKED.**
- **P1:** visible solar-disk fraction using the Sun's apparent angular radius (~0.27°) against the horizon profile. This is a priority because the Sun's angular size is comparable to its elevation excursion at the pole.
- **Interval accounting:** each sample contributes `sample_step_seconds` (truncated at mission end, §2). "Continuous darkness/blackout" is the longest run of consecutive non-visible samples × step. Intervals touching the mission start/end are reported but flagged as boundary-truncated. Samples with **unknown** visibility are excluded from fractions and break runs; the response reports the unknown fraction. **LOCKED.**

## 10. Validation references

| Reference | What we compare | Status |
|---|---|---|
| JPL Horizons | Sun/Earth topocentric azimuth/elevation | M1 |
| Mazarico et al. (2011), PGDA 69 (60 m and 240 m/px) | Long-window Sun visibility and Earth visibility at numbered sites | M2 |
| LROC WAC south-pole illumination % (88–90°S, 100 m/px) | Sun visibility | M2, secondary |
| Bertone SfS, PGDA 104 | Terrain/illumination at Artemis III regions | optional |

Discrepancies are documented with probable causes (resolution, averaging period, point-source approximation, DEM version). They are never tuned away.

## 11. Verification log

Record each TO VERIFY resolution here: item, observed value, source, date, who verified.

| Item | Observed | Source | Date | By |
|---|---|---|---|---|
| Kernel set (§8) | DE421: `naif0012.tls`, `de421.bsp`, `moon_pa_de421_1900-2050.bpc`, `moon_080317.tf`, `moon_assoc_me.tf`; checksums in `data/manifests/kernels.json` | NAIF generic kernels | 2026-11-14 | Claude (download), Randy Moore (DE421 approved; P2 signed off 2026-11-14) |
| Terrain projection and datum (§3, §4) | All 9 files: south polar stereographic on R = 1,737,400 m, NaN no-data (none present); 5 m vs 40 m mean height difference −0.24 to +0.17 m | GeoTIFF metadata; `docs/physics/terrain.md` §8.1 | 2026-11-14 | Claude (measured) |
| Ephemeris tolerances (§8) | Grid method vs SPICE at site: worst 2.7e-5° (tolerance 0.001°); vs JPL Horizons: worst 0.00003° (tolerance 0.01°) | `docs/physics/sky.md` §7.1 | 2026-11-14 | Claude (measured); tolerances approved by Randy Moore |
| Frame realization (§3) | `moon_080317.tf` defines `MOON_ME` relative to `MOON_ME_DE421`, matching the LOLA DEM frame; no DE421/DE440 offset needed | `moon_080317.tf` frame definitions | 2026-11-14 | Claude |
