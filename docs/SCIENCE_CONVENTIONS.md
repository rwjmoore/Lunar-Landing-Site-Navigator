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
- **Reference surface: sphere, R = 1737.4 km.** DEM heights are relative to this sphere. **TO VERIFY (M1)** against each product's metadata/label.
- **Coordinates:** planetocentric latitude; **east-positive longitude**, range `[0°, 360°)` internally. The API accepts `longitude_deg_east` in `[−180°, 360°)` and normalizes. **LOCKED.**
- **Frame realization:** the PGDA DEMs are MOON_ME as realized with DE421. If the ephemeris uses DE440, document the DE421 vs DE440 MOON_ME offset (expected to be metre-level, negligible at our angular scales). **TO VERIFY (M1).**

## 4. Terrain data (decision D2)

| Tier | Product | Native resolution | Used range | Status |
|---|---|---|---|---|
| Near-field | PGDA 81 5 m/px mosaic (87–90°S) or PGDA 78 per-site 5 m DEMs | 5 m | 0 – ~10 km | **TO VERIFY (M1)**: filenames, size, CRS |
| Far-field | PGDA 90 `LDEM_80S_20MPP_ADJ.TIF` (80–90°S), downsampled offline | 20 m → ~100 m | ~10 – 200 km | **TO VERIFY (M1)**: availability, CRS |
| Quality mask | Matching `LDEC` (LOLA returns per pixel) | as above | as above | **TO VERIFY (M1)** |

- **Projection:** south polar stereographic, x/y in metres. Exact projection parameters (center, scale factor, sphere radius) must be read from the GeoTIFF CRS, never hard-coded from memory. **TO VERIFY (M1).**
- **Sampling:** bilinear interpolation of heights. **LOCKED.**
- **No-data:** pixels flagged as no-data, or outside coverage, are **unknown**, never zero height and never unobstructed. Whether low `LDEC` counts (interpolated pixels) should also be flagged is **TO VERIFY (M1)** after inspecting the count maps.
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
  - *Reference check:* the P2 gate compares this method against direct `spkcpo` queries at the observer position (same frame and correction). Acceptance tolerance **TO VERIFY (M1)**.
- **Why topocentric matters:** Earth's lunar-radius parallax is ~0.26° (1737.4 / 384,400 rad), which is significant near the horizon. For the Sun it is negligible, but the same code path is used for consistency.
- **Kernel set** (exact filenames and versions recorded in provenance): **TO VERIFY (M1)** against the NAIF generic kernels site.
  - Leapseconds (LSK).
  - Planetary ephemeris (SPK): DE440 or DE421.
  - Lunar orientation: binary PCK for `MOON_PA` matching the chosen DE.
  - Lunar frames kernel (FK) defining `MOON_ME` relative to `MOON_PA` for that DE.
- **Validation:** 3–5 timestamps per demo site compared against Horizons (observer defined as a surface site on body 301). Record agreement in degrees. Acceptance threshold: **TO VERIFY (M1)**, expected ≤ 0.01°.

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
| | | | | |
