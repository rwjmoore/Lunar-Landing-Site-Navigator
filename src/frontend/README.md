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

- The app opens in map mode. You can choose any point within the displayed polar coverage. Waypoints without an analysis show missing terrain and unknown Sun and Earth visibility. The bundled basemap is available offline. The **HD** map button (off by default) loads sharper LROC tiles over it when online.
- **Explore demo** loads two synthetic scenarios. It supports UTC playback, comparison, and a mast change from 2 m to 6 m at the default mission settings. The same banner labels the illustrations across all three views.
- **Load analysis JSON** in Horizon Analysis imports one `AnalyzeResponse` matching the [repository contract](../../docs/frontend-backend_interface.json). The empty contract fixture is valid and exercises the missing-data state. The reader also accepts nullable elevations, optional per-observer `*_observer_no_data` masks, and nullable visibility as proposed in the project plan. It draws gaps and preserves unknown visibility. A local import carries its own timestamps, heights, and provenance and is excluded from shared-mission ranking.

## Live data integration

The backend (see the [root README](../../README.md) and [docs/API.md](../../docs/API.md)) serves `GET /sites`, `POST /analyze` and the planning endpoints below. Configure the frontend at build time, or put these variables in `.env.local` for development.

| Variable | Value |
| --- | --- |
| `VITE_API_BASE_URL` | The API base URL, e.g. `http://127.0.0.1:8000`, or `/` for an API on the same origin. |
| `VITE_INDEPENDENT_ANTENNA` | Optional. The antenna height can be changed independently by default; set `false` only for a backend that does not support it. |

On startup the frontend loads the supported sites from `GET /sites`, so their coordinates always match the backend's terrain data; no site list needs configuring. If the list can't be loaded, the map shows why. When serving the API on another origin, start it with `LLSN_CORS_ORIGINS` set to the frontend's origin (e.g. `http://localhost:5173`).

The frontend sends the plan's coordinate-based request and checks the response against the requested location (within the backend's published site-match tolerance), UTC samples, cadence, and vehicle. When the API rejects a request, its own explanation is shown, e.g. why a mission is out of range. The mast comparison uses two analyses with the same mission and constraints. A live site comparison runs one `/analyze` request per supported site with identical settings.

### Custom points and mission planning

- **Custom points.** If `GET /sites` reports `custom_points_available`, the map draws a green dashed ring at `custom_point_north_edge_latitude_deg` (86.7°S today). Any point inside it can be analysed: the backend computes its terrain horizon on demand, which takes a few seconds the first time. Points outside it show a coverage message.
- **Mission planning panel** (under the horizon view, for backend analyses; `src/Planning.tsx`, API client `src/planningApi.ts`):
  - **Why & what next** (`POST /insights`): time to the next sunset/sunrise and Earthset/Earthrise at the timeline position, a plain-language summary, the longest joint Sun + Earth window, and what blocked the worst outages.
  - **Start dates** (`POST /calendar`): one square per day of the chosen year, coloured by whether a mission starting then meets the limits and by how much slack. Click a day to analyse it.
  - **Fix this mission** (`POST /rescue`, about 5–15 s): the smallest single change (mast, antenna, start date, or a spot up to 800 m away), each with **Apply and analyse**.
  - Start dates and rescue need hourly sampling.

### Testing against a local backend

1. Start the backend from `src/backend` (PowerShell): `$env:LLSN_CORS_ORIGINS="http://localhost:5173"; .venv\Scripts\python -m uvicorn app.main:app`
2. Create `src/frontend/.env.local` containing `VITE_API_BASE_URL=http://127.0.0.1:8000`.
3. Start the frontend as above and open the printed URL. The four supported sites appear on the map; select one and run the mission.

## Basemap provenance

**Live imagery (since 2026-11-15):** with the **HD** button on, the map draws tiles from the public LROC Lunaserv WMS (`https://wms.im-ldi.com/`, projection `IAU2000:30120`): the LROC WAC South Pole Summer mosaic (~100 m/px) everywhere, and the controlled LROC NAC south-pole average mosaic (1 m/px, 84–90°S) at closer zooms. The map key names the imagery under the view centre and says when it is enlarged beyond native detail. The bundled image below remains the instant, offline base underneath. Audit and evidence: [docs/imagery.md](../../docs/imagery.md).


The local WebP is a 1,408 × 1,408 pixel crop of `WAC_ROI_SOUTH_SUMMER_064P.TIF` at its native ~474 m per pixel, identified by SHA-256 `f368c1d315fe49616dd7f0d52856c1520ed0a1677ee4d1f450ba1c60a13b1330`. Source pixel bounds are `(2334, 2334, 3742, 3742)` using zero-based, right/bottom exclusive coordinates. The raster uses spherical south polar stereographic with a radius of 1,737.4 km, central meridian 0°E, and scale factor 1. The map reads coordinates and distances in this projection and restricts selection to 80–90°S. The raster is for navigation. The analysis horizon comes from the backend's elevation data. [LROC WAC South Pole Summer Mosaic](https://data.lroc.im-ldi.com/lroc/view_rdr/WAC_ROI_SOUTH_SUMMER), Speyerer et al. (2020), [Lunar Surface Science Workshop abstract 5132](https://www.hou.usra.edu/meetings/lunarsurface2020/pdf/5132.pdf).
