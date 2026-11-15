<p align="center"><img src="src/frontend/src/assets/lunarsight.svg" alt="LunarSight logo: a telescope beneath the Moon" width="320"></p>

# Lunar Landing Site Navigator

An explainable, terrain-aware lunar mission planning tool. Understand why a lunar landing mission fails its sunlight or communication requirements, and discover changes that could make it feasible.

Built for the [NASA Space Apps Challenge 2026: Lunar Landing Site Navigator](https://www.spaceappschallenge.org/2026/challenges/lunar-landing-site-navigator/).

## What it does

For a candidate landing site near the lunar south pole, a mission window and a vehicle (solar-mast and antenna heights), it computes:

- the **360° terrain horizon** around the site, from NASA LOLA laser-altimeter terrain out to 200 km;
- the **Sun's and Earth's positions** every hour, from JPL's DE421 ephemeris;
- **when the Sun and Earth are visible** above the terrain;
- **mission metrics**: sunlight fraction, longest darkness, Earth-visibility fraction, longest Earth blackout;
- a **feasibility verdict** against your limits, with margins and the timing of the worst outages;
- side-by-side **comparison** of several sites under identical assumptions;
- a **date-flexibility calendar**: the same mission evaluated at every possible start date from 2026 to 2040;
- **plain-language explanations**: when the Sun next sets, when the Sun and Earth are visible together, and what terrain (direction, distance, location) caused the worst outages, including whether it's the Moon's own curvature that no fix can beat;
- **mission rescue**: the smallest single change (taller mast, taller antenna, earlier or later start, or a nearby point) that makes a failing mission pass.

Raising the solar mast changes the horizon, not the Sun: at some sites going from a 2 m to a 10 m mast lifts sunlight from 47% to 85% of the year. Showing trade-offs like that is the point of the tool.

## Status

| Part | State |
|---|---|
| Physics core (frames, Sun/Earth ephemeris, terrain, horizon, visibility, metrics) | Done, reviewed, and **validated against NASA's published south-pole illumination maps** (mean difference 0.1 percentage points, correlation 0.99) |
| Backend API (`/sites`, `/analyze`, `/compare`, `/data-provenance`) | Done ([docs/API.md](docs/API.md)) |
| Planning tools (`/calendar`, `/insights`, `/rescue`) | Signed off ([docs/physics/planning.md](docs/physics/planning.md)); in the UI under Horizon Analysis |
| Frontend ("LunarSight": map, 360° horizon, comparison) | Working against the live API; in active development (`src/frontend/`) |
| Deployment | Not yet |

Supported today: **four curated south-pole sites** plus **custom points anywhere south of 86.70°S** (computed on demand from the 40 m terrain map; [docs/physics/custom_points.md](docs/physics/custom_points.md)), mission dates **2026–2040**, mast and antenna heights **0–20 m**. See `GET /sites` for exact coordinates.

## Repository layout

```text
Lunar-Landing-Site-Navigator/
├── README.md               # this file
├── setup.bat               # Windows: one-time install of backend, data and frontend
├── start.bat               # Windows: start API + web app together
├── docs/                   # plan, API reference, physics explainers with evidence
├── data/
│   ├── manifests/          # every external source file, with URL and SHA-256 (committed)
│   ├── sites/              # supported site list (committed)
│   ├── sky/                # precomputed Sun/Earth sky grid, 7 MB (committed)
│   ├── horizons/           # precomputed far-terrain horizons per site (committed)
│   ├── kernels/            # SPICE kernels (downloaded, gitignored)
│   ├── raw/                # NASA terrain and validation maps (downloaded, gitignored)
│   └── artifacts/          # terrain grids built from raw data (generated, gitignored)
└── src/
    ├── backend/            # Python: FastAPI server (app/) and offline data pipeline (pipeline/)
    └── frontend/           # web UI (separate engineer)
```

The backend has two halves: **`app/`** is the server and needs only FastAPI, Pydantic and NumPy; **`pipeline/`** is the offline data pipeline, which uses heavier tools (SpiceyPy, rasterio, pyproj) and never runs on the server. More detail in [src/backend/README.md](src/backend/README.md).

## Quick start on Windows

From the repository root:

```bash
setup.bat
```

```bash
start.bat
```

- **`setup.bat`** (once) installs the backend's Python environment, downloads and verifies NASA's terrain data (about 1 GB, 15–20 minutes the first time), builds the terrain grids, installs the frontend's Node.js and packages, and points the frontend at the local API. Re-running it is safe and takes about 20 seconds.
- **`start.bat`** (every time) opens two windows, **LunarSight API** (http://127.0.0.1:8000) and **LunarSight Web** (http://localhost:5173), waits until both respond, then opens the app in your browser. **Close both windows to stop the app.** `start.bat nobrowser` starts without opening a browser.

Requirements: Python 3.12+, about 2.6 GB of disk, internet access for setup. If several Pythons are installed, setup uses the **newest stable 3.12+** it finds via the Python launcher (`py -3`), `python` or `python3`, skipping alpha/beta/rc builds; `setup.bat --which-python` shows which one it would pick. An existing `src\backend\.venv` is reused; delete it to rebuild with a different Python. Node.js does **not** need to be installed: setup downloads a checksum-verified copy into `src/frontend/.frontend-tools/`. For macOS/Linux, or to understand each step, follow the manual installation below.

## Installation

### Requirements

- **Python 3.12 or newer** (tested on 3.13)
- **About 2.5 GB of free disk space**: 1 GB of downloaded terrain, 1.1 GB of grids built from it, 0.3 GB for the Python environment
- **Internet access** for the one-time data download
- Windows, macOS or Linux

### Step 1: Get the code

```bash
git clone https://github.com/rwjmoore/Lunar-Landing-Site-Navigator.git
```

```bash
cd Lunar-Landing-Site-Navigator/src/backend
```

All remaining commands run from `src/backend`.

### Step 2: Create a virtual environment and install dependencies

```bash
python -m venv .venv
```

Activate it:

| Shell | Command |
|---|---|
| Windows PowerShell | `.venv\Scripts\Activate.ps1` |
| Windows cmd | `.venv\Scripts\activate.bat` |
| macOS / Linux, or Git Bash on Windows | `source .venv/bin/activate` (Git Bash: `source .venv/Scripts/activate`) |

Install the exact versions the project was tested with, plus the project itself:

```bash
pip install -r requirements.lock
```

```bash
pip install -e . --no-deps
```

This includes everything: the server, the tests and the data pipeline. (To install the latest compatible versions instead of the pinned ones, use `pip install -e ".[dev,pipeline]"`.)

> **PowerShell note:** if activation is blocked by the execution policy, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once, or call the venv's Python directly, e.g. `.venv\Scripts\python -m pytest`.

### Step 3: Download the terrain data (about 1 GB, one time)

```bash
python -m pipeline.fetch_data
```

This downloads NASA's LOLA terrain maps listed in `data/manifests/terrain.json` into `data/raw/terrain/` and verifies every file's SHA-256 checksum. Re-running skips files that are already present and correct, and an interrupted download never leaves a partial file in place. At 1 MB/s it takes about 15–20 minutes.

Other data groups, needed only for rebuilding or re-validating:

| Command | Downloads | Size | Needed for |
|---|---|---|---|
| `python -m pipeline.fetch_data` | terrain | ~1.04 GB | **running the API** (step 4) |
| `python -m pipeline.fetch_data kernels` | SPICE kernels (DE421) | ~19 MB | rebuilding the sky grid |
| `python -m pipeline.fetch_data validation` | NASA illumination maps | ~102 MB | rerunning the NASA validation |
| `python -m pipeline.fetch_data --all` | all of the above | ~1.16 GB | everything |

### Step 4: Build the terrain grids

```bash
python -m pipeline.build_terrain
```

This converts the downloaded GeoTIFFs into the grids the server reads (`data/artifacts/terrain/`), checking each file's projection on the way. It takes a few seconds. The sky grid and the far-terrain horizons are already in the repository, so nothing else needs building.

### Step 5: Check the installation

```bash
python -m pytest
```

You should see **no failures**. With the terrain downloaded and built, most of the ~200 tests pass in under a minute; the few that need optional data (the SPICE kernels, the validation maps) are **skipped**, not failed. With `--all` data fetched, all 207 run. *(For reference, a fresh clone before steps 3–4 gives 129 passed, 78 skipped.)*

## Running the API

```bash
uvicorn app.main:app --reload
```

Then open:

- **http://127.0.0.1:8000/docs**: interactive documentation; use **POST /analyze → Try it out** to run a real analysis from the browser;
- **http://127.0.0.1:8000/sites**: the supported sites and their exact coordinates;
- **http://127.0.0.1:8000/health**: confirms the data loaded (`sky_grid`, `sites` and `terrain` should all say loaded).

An example request, also usable on the `/docs` page:

```json
{
  "site": {"name": "Shackleton rim", "latitude_deg": -89.780403, "longitude_deg_east": 203.803049},
  "mission": {"start_utc": "2030-11-20T12:00:00Z", "duration_hours": 336, "sample_step_seconds": 3600},
  "vehicle": {"solar_panel_mast_height_m": 2.0, "antenna_height_m": 2.0},
  "constraints": {"max_darkness_hours": 24, "max_earth_blackout_hours": 100}
}
```

The first request at a given mast height takes about 1.5 s per site (the horizon is computed); repeats take milliseconds. To let a separately hosted frontend call the API, set `LLSN_CORS_ORIGINS` to its origin(s) before starting, e.g. `LLSN_CORS_ORIGINS=http://localhost:5173`. Full request rules and error codes: [docs/API.md](docs/API.md).

Stop the server with **Ctrl+C**.

## Running the full app (API + web app)

`start.bat` does all of this on Windows. Manually, in two terminals:

**Terminal 1, the API**, from `src/backend`, allowing the web app's address to call it:

| Shell | Command |
|---|---|
| PowerShell | `$env:LLSN_CORS_ORIGINS="http://localhost:5173"; .venv\Scripts\python -m uvicorn app.main:app` |
| macOS / Linux | `LLSN_CORS_ORIGINS=http://localhost:5173 .venv/bin/python -m uvicorn app.main:app` |

**Terminal 2, the web app**, from `src/frontend`, after a one-time install:
1. Install: on Windows `powershell -NoProfile -ExecutionPolicy RemoteSigned -File install.ps1`; elsewhere, with Node.js 22.12+ and pnpm, `pnpm install --frozen-lockfile`.
2. Create `src/frontend/.env.local` containing `VITE_API_BASE_URL=http://127.0.0.1:8000`.
3. Start: on Windows `powershell -NoProfile -ExecutionPolicy RemoteSigned -File install.ps1 -Start`; elsewhere `pnpm run dev`.

Open http://localhost:5173. The four supported sites appear on the map; pick one, open **Mission**, and choose **Run Analysis**. **Explore demo** shows a clearly labelled synthetic scenario that works without the API. More in [src/frontend/README.md](src/frontend/README.md).

## Rebuilding and re-validating the data

None of this is needed to run the API. Each step is described in its physics explainer.

| Task | Command | Needs |
|---|---|---|
| Rebuild the Sun/Earth sky grid | `python -m pipeline.build_sky_grid` | kernels |
| Cross-check Sun/Earth against JPL Horizons | `python -m pipeline.horizons_check` | internet |
| Rebuild the far-terrain horizons (~40 s) | `python -m pipeline.build_far_horizons` | terrain |
| Reproduce the validation against NASA's maps (~5 min) | `python -m pipeline.validate_illumination` | terrain, validation |
| Regenerate review evidence and plots | `python -m pipeline.sky_evidence`, `terrain_evidence`, `horizon_evidence` | as above |

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `/health` shows `terrain: missing`, or `/analyze` returns `503 data_unavailable` | Steps 3–4 weren't run. Run `python -m pipeline.fetch_data` then `python -m pipeline.build_terrain`. |
| `checksum mismatch` during download | The file changed or the download was corrupted; nothing is kept. Re-run the command. If it persists, the source has changed and the manifest needs review. |
| Many tests **skipped** | Expected without the optional data groups; run `python -m pipeline.fetch_data --all` and step 4 to run them all. |
| `404 site_unavailable` | The requested coordinates aren't within 100 m of a supported site. Copy exact coordinates from `GET /sites`. |
| `422 mission_out_of_range` | The start must be on a whole UTC hour, and the mission must lie within 2026-01-01 to 2040-12-31. |
| `ModuleNotFoundError` | The virtual environment isn't active, or step 2's `pip install -e . --no-deps` was skipped. |
| `start.bat` says a port is already in use | The app (or something else) is already running on 8000 or 5173. Close the old LunarSight windows first. |
| The web app says the site list couldn't be loaded | The API isn't running, or was started without `LLSN_CORS_ORIGINS=http://localhost:5173`. Use `start.bat`, or see "Running the full app". |

## Documentation

| Document | What's in it |
|---|---|
| [docs/PROJECT_PLAN.md](docs/PROJECT_PLAN.md) | Scope, architecture, decisions, milestones, API contract and proposed v2 changes |
| [docs/API.md](docs/API.md) | API reference for the frontend: requests, responses, errors, performance |
| [docs/SCIENCE_CONVENTIONS.md](docs/SCIENCE_CONVENTIONS.md) | Coordinate, time, unit and data conventions, with a verification log |
| [docs/metrics.md](docs/metrics.md) | Metric definitions and constraint rules |
| [docs/physics/frames.md](docs/physics/frames.md) | Coordinates and local geometry |
| [docs/physics/sky.md](docs/physics/sky.md) | Sun and Earth directions (DE421), checked against SPICE and JPL Horizons |
| [docs/physics/terrain.md](docs/physics/terrain.md) | LOLA terrain ingest and the demo sites |
| [docs/physics/horizon.md](docs/physics/horizon.md) | Horizon ray casting and visibility |
| [docs/physics/validation.md](docs/physics/validation.md) | Validation against NASA's published illumination maps |
| [docs/physics/planning.md](docs/physics/planning.md) | Date calendar, explanations and mission rescue |
| [src/backend/README.md](src/backend/README.md) | Backend layout and developer commands |

Every physics component has an explainer with equations, assumptions, test evidence and a review sign-off. Changes to a signed-off component need a new review.

## Data sources and credits

All data is from NASA and is used with the citations its providers request. Exact files and checksums are in `data/manifests/`.

- **Terrain:** LOLA south-pole elevation maps from NASA GSFC's Planetary Geodesy Data Archive. Barker, M. K., et al. (2021), *Planetary & Space Science* 203, 105119, doi:10.1016/j.pss.2020.105119; Barker et al. (2023), *Planetary Science Journal*.
- **Site numbering and validation maps:** Mazarico, E., et al. (2011), Illumination conditions of the lunar polar regions using LOLA topography, *Icarus* 211, 1066–1081, doi:10.1016/j.icarus.2010.10.030.
- **Ephemeris:** JPL DE421 planetary ephemeris and lunar orientation, distributed by NASA's NAIF as SPICE kernels; cross-checked against JPL Horizons.

## License

Not yet specified.
