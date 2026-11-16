# elevation_overlay.md — Elevation and slope heat map on the Lunar Map

> **Review status: SIGNED OFF (2026-11-16).** A display feature: the overlay shows the same LOLA terrain the physics uses, but **no analysis reads these tiles**. Horizons and visibility always sample the LOLA grids directly (`app/terrain/grid.py`). Reviewed: the slope definition (§4) and the caveats (§5). Any change to the tile data, encoding or slope definition needs a new review.

Code: `src/backend/pipeline/build_elevation_tiles.py` (builder), `src/backend/app/terrain/elevation_tiles.py` (tile scheme and encoding), `src/frontend/src/elevation.ts` and `MapView.tsx` (drawing). Tests: `tests/test_elevation_tiles.py`.

## 1. What it shows

The Lunar Map's **Terrain overlay** panel (bottom left) switches between **Imagery only**, **Elevation** and **Slope**.
- **Opacity:** adjustable, so the imagery shows through.
- **Legend:** gives the colour range.
- **Cursor readout:** shows the height (and slope) under the cursor.
- **Default:** the overlay is off, and nothing downloads until it's switched on.

## 2. Data

| Zoom levels | Source | Tile pixel | Coverage |
|---|---|---|---|
| 0–5 | LOLA `LDEM_80S_40MPP_ADJ`, 40 m (the same map as the far-zone physics) | 1,250 m → 39 m | 80–90°S |
| 6–8 | LOLA 5 m site maps (the same maps as the near-zone physics) | 19.5 m → 4.9 m | 16 × 16 km around each of the 4 sites |

- **How tiles are made:** the finest level of each source is sampled at pixel centres with the same bilinear lookup the physics uses. Every coarser tile is the 2 × 2 mean of its four children, so zoomed-out views are true area averages, not aliased point samples.
- **Outside the site maps:** zooming past level 5 enlarges the 40 m tiles.
- **Overlapping site maps:** the 5 m maps for Sites 01 and 04 overlap (about 6 × 11 km). There, each pixel uses the map whose centre is nearest, so each site's surroundings come from its own map, the one its physics uses. The two NASA products agree closely in the overlap: median difference 0.12 m, 99th percentile 1.1 m, worst 7.4 m on steep slopes.

## 3. Tiles and encoding

- **Same grid as the imagery:** tiles use the imagery's tile grid (`imagery.ts`: a quadtree over ±320 km in the map's south-polar stereographic projection, 512 px tiles), so the overlay lines up exactly with the map.
- **Heights, not colours:** each tile stores heights in 0.25 m steps, packed losslessly into PNG colour channels: h = (256 R + G) × 0.25 − 8,192 m, and A = 0 means no data. This range covers −8,192 m to +8,191.75 m, while LOLA's south-polar range is about −7,254 m to +7,007 m.
- **Why heights:** the browser can then:
  - stretch the colours to the heights in view, using the 2nd–98th percentile of sampled pixels and updating once the view settles;
  - compute slope;
  - read the height under the cursor.
- **Colour scales:** viridis for height and inferno for slope. Both are perceptually uniform and colour-blind safe.
- **Serving:** the tiles are built offline by `python -m pipeline.build_elevation_tiles` (`setup.bat` runs it) into `data/artifacts/elevation_tiles/` (gitignored), and the API serves them as static files at `/tiles/elevation/`.

## 4. Slope

- **Definition:** slope = atan(|∇h|), in degrees, where ∇h comes from central differences of the tile's heights over 2 pixels. At tile edges it uses one-sided differences.
- **Scale dependence:** slope is computed **at the tile's own pixel size**, so it's a property of the zoom level. At level 5 it's slope over about 80 m, and at level 8 over about 10 m. Steeper local slopes average out at coarser zooms.
- **Rounding noise:** 0.25 m height steps add up to about 0.2° of noise at 40 m pixels and about 1.5° at 5 m pixels.
- **Colour range:** fixed at 0–40°.

## 5. Caveats

- **Interpolated texture:** about 90% of pixels in the 5 m site maps are interpolated between altimeter tracks (`terrain.md`), so fine texture near the sites is partly smooth interpolation, not measured detail.
- **Height reference:** heights are relative to the 1,737.4 km sphere, not a "sea level".
- **Not a hazard map:** the slope view is a visual aid, not a landing-hazard assessment. It doesn't resolve boulders or account for the vehicle's footprint.

## 6. Evidence

| Check | Result |
|---|---|
| Height encoding round trip | ≤ 0.125 m error; no-data preserved |
| PNG writer | Byte-exact round trip (decoded without an imaging library) |
| Built level-5 and level-8 tiles at Site 04 vs the LOLA grids sampled at the same points (level 8 vs Site 04's own map) | ≤ 0.125 m |
| Pyramid orientation (north children on top) and tile grid identical to the frontend's | Tested |
| API serves the manifest and tiles (404 for missing tiles) | Tested |

## 7. Review sign-off

| Stage | Reviewer | Date | Decision / comments |
|---|---|---|---|
| Slope definition and its scale dependence (§4), caveats (§5) | Randy Moore | 2026-11-16 | Approved |
