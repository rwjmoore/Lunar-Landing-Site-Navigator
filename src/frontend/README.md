# LunarSight frontend

LunarSight is the React, TypeScript, and Vite interface for the Lunar Landing Site Navigator. It provides a selectable south-pole map, a 360° horizon and UTC playback view, mission and vehicle drawers, and a sortable site comparison.

## Windows setup

From the repository root, run this command in PowerShell.

```powershell
powershell.exe -NoProfile -ExecutionPolicy RemoteSigned -File .\src\frontend\install.ps1 -Start
```

The installer downloads a verified Node.js runtime and pinned pnpm into `src/frontend/.frontend-tools`, then installs the packages in `pnpm-lock.yaml`. Later runs reuse the tools and cached packages. Open the **Local** URL printed by Vite and choose **Explore demo**. Press **Ctrl+C** to stop the server. Omit `-Start` to install only.

## Manual setup

Run these commands from `src/frontend` if you already have Node.js 22.12 or newer and pnpm.

```sh
pnpm install --frozen-lockfile
pnpm run dev
pnpm run build
```

`pnpm run check` runs TypeScript validation. `pnpm run build` also writes a static site to `dist/`. Serve that directory with any static server. For a local production preview, run `pnpm run preview`.

## Data modes

- The app opens in map mode. You can choose any point within the displayed polar coverage. Waypoints without an analysis show missing terrain and unknown Sun and Earth visibility. The basemap is available offline.
- **Explore demo** loads two synthetic scenarios. It supports UTC playback, comparison, and a mast change from 2 m to 6 m at the default mission settings. The same banner labels the illustrations across all three views.
- **Load analysis JSON** in Horizon Analysis imports one `AnalyzeResponse` matching the [repository contract](../../docs/frontend-backend_interface.json). The empty contract fixture is valid and exercises the missing-data state. The reader also accepts nullable elevations, optional per-observer `*_observer_no_data` masks, and nullable visibility as proposed in the project plan. It draws gaps and preserves unknown visibility. A local import carries its own timestamps, heights, and provenance and is excluded from shared-mission ranking.

## Live data integration

This checkout serves `/health`. When the backend provides `POST /analyze`, configure the deployed frontend at build time or put these variables in `.env.local` for development.

| Variable | Value |
| --- | --- |
| `VITE_API_BASE_URL` | The API base URL, or `/` for an API on the same origin. |
| `VITE_SUPPORTED_SITES` | A JSON array of prepared backend sites, each with `name`, `latitude_deg`, and `longitude_deg_east`. Leave the array empty until terrain coverage is confirmed. |
| `VITE_INDEPENDENT_ANTENNA` | Set to `true` when the API supports independently changing antenna height. |

Provide CORS access for the frontend origin when serving the API separately. The frontend sends the plan's coordinate-based request and checks the response against the requested location, UTC samples, cadence, and vehicle. The mast comparison uses two analyses with the same mission and constraints. A live site comparison runs one `/analyze` request per prepared site with identical settings. The `/sites` and `/compare` response schemas are pending.

## Basemap provenance

The local WebP is a 1,408 × 1,408 pixel crop of `WAC_ROI_SOUTH_SUMMER_064P.TIF` at its native ~474 m per pixel, identified by SHA-256 `f368c1d315fe49616dd7f0d52856c1520ed0a1677ee4d1f450ba1c60a13b1330`. Source pixel bounds are `(2334, 2334, 3742, 3742)` using zero-based, right/bottom exclusive coordinates. The raster uses spherical south polar stereographic with a radius of 1,737.4 km, central meridian 0°E, and scale factor 1. The map reads coordinates and distances in this projection and restricts selection to 80–90°S. The raster is for navigation. The analysis horizon comes from the backend's elevation data. [LROC WAC South Pole Summer Mosaic](https://data.lroc.im-ldi.com/lroc/view_rdr/WAC_ROI_SOUTH_SUMMER), Speyerer et al. (2020), [Lunar Surface Science Workshop abstract 5132](https://www.hou.usra.edu/meetings/lunarsurface2020/pdf/5132.pdf).
