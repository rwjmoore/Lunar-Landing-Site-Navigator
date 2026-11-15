# planning.md — Planning tools: date calendar, explanations, mission rescue

> **Review status: SIGNED OFF (2026-11-15).** You asked for these to be built directly, so the approach and the implementation were reviewed together here. Any change to these tools' definitions or search needs a new review. No signed-off physics was changed: every tool is built from the signed-off horizon, sky and metric components. The new definitions to check are in §2.2, §3 and §4.

Code: `src/backend/app/planning/` (`calendar.py`, `insights.py`, `rescue.py`), endpoints in `src/backend/app/api/planning_service.py`. Tests: `tests/test_planning.py`, `tests/test_custom_points.py`. All three tools work at the curated sites **and at any custom point in the covered area** (`custom_points.md`).

## 1. What these tools add

| Tool | Question it answers | Endpoint |
|---|---|---|
| Date-flexibility calendar | "Which start dates work, and how much slack does a schedule slip cost?" | `POST /calendar` |
| Explanations | "Why did it fail, when does the Sun set next, when can we charge and talk at once?" | `POST /insights` |
| Mission rescue | "What is the smallest change that makes this mission pass?" | `POST /rescue` |

## 2. Date-flexibility calendar

### 2.1 Method

The site's Sun and Earth visibility is computed **once** over the whole hourly sky grid (131,496 hours, 2026–2040), using the signed-off horizon and visibility rules. Each candidate mission is then just a window of that series, so every start date can be evaluated at once.

For a mission of $D$ whole hours starting at grid hour $s$, the window is hours $s, s+1, \dots, s+D-1$, each worth one hour. (The approved time accounting also has a final sample at $s+D$ with weight 0, which contributes nothing; `docs/metrics.md` §3.1.)

- **Fractions:** running sums of "known" and "visible" hours give every window's fraction at once.
- **Longest outage:** for each window, the larger of (a) the longest obstructed run lying **wholly inside** the window, found with a range-maximum lookup over run lengths, and (b) the runs **clipped** at the window's two edges. Unknown hours break runs, as approved.
- **Feasibility:** the approved constraint rules (`docs/metrics.md` §4), including "coverage below 1 → unknown".

### 2.2 Definitions to review

- **Candidate starts** are whole UTC hours, `start_step_hours` apart (default 24), within an optional range.
- **Best start** = the feasible start with the largest **worst-case margin**, meaning the smallest signed margin across the enabled limits.
- The calendar requires **hourly sampling** and whole-hour durations. That keeps it exactly equal to `/analyze` for the same mission.

### 2.3 Evidence

- **Exactness:** for 600 random missions (2 sites × 3 durations × 100 starts), every metric equals `/analyze` **exactly** (difference 0) and every verdict agrees. A test checks 50 more on every run.
- **The run-finder** matches a brute-force scan on 900 random windows, including edge cases.
- **Speed:** every hourly start from 2026 to 2040 (131,000 missions) in **0.04 s**. Responses are capped at 20,000 starts to keep them small.

## 3. Explanations

All derived from one analysis; no new physics.

| Item | Definition |
|---|---|
| **Events** | A *rise* is obstructed → visible between consecutive samples, a *set* is visible → obstructed. Changes to or from "unknown" are not events. |
| **Hours to next change** | At each sample, hours until the state next differs; none if it doesn't change before the mission ends, or if the state is unknown. |
| **Joint Sun + Earth** | Joint state = obstructed if either body is obstructed, else unknown if either is unknown, else visible. **Joint fraction** uses the existing `VisibleFraction` metric. **Longest joint window** is the existing `LongestOutage` metric applied to the inverted joint series. |
| **Outage explanation** | For the longest darkness and the longest Earth blackout: the body's azimuth range while hidden; how far below the terrain horizon it went; the **10° azimuth sector** where it was hidden longest, and that sector's highest horizon point (its distance and latitude/longitude, from the stored blocking distance walked along the great circle); the share of hidden hours blocked by terrain **within 1 km**; and the share spent **below the Moon's own curved horizon**. |

**Below the Moon's own horizon.** For an observer at height $h$ above the 1,737.4 km sphere, the bare sphere's horizon (no terrain) lies at

$$
\alpha_\text{limb} = -\arccos\left(\frac{R}{R + h}\right)
$$

(about $-2.7^\circ$ for a lander 1.9 km above the reference sphere). A body below that is hidden by the Moon itself, so no mast height or short move can bring it back. Earth blackouts at our sites are mostly this case (65–78% of hidden hours), driven by libration. The explanation says so explicitly, so planners don't chase an impossible fix.

## 4. Mission rescue

For a mission failing (or uncertain against) its limits, each option changes **one thing** and reports the result:

| Option | How it is found |
|---|---|
| **Taller solar mast** (fixes darkness) | Smallest height on a 0.5 m grid above the current one, up to 20 m, found by **bisection**. Valid because raising the observer never raises the terrain horizon (tested in M2), so the Sun is never hidden longer at a greater height. Not offered if the darkness limit already passes. |
| **Taller antenna** (fixes Earth blackout) | The same, for Earth visibility. |
| **Earlier / later start** | The nearest feasible start before and after the requested one, searched hourly within ±`max_shift_days` (default 60), at the current heights. Uses the calendar. |
| **Move nearby** | The **nearest** passing point and the **best** passing point (largest worst-case margin) within ±800 m, found on demand (§4.1). |

### 4.1 Nearby search

On demand, at any point in the covered area, at the **requested** mast and antenna heights (`custom_points.md` §6):
1. **Screen** 80 candidates on a 9 × 9 grid, 200 m apart, with a cheap approximate horizon, for ranking only.
2. **Verify** the two most promising with the full exact horizon.

**Only verified results are reported.** A suggested point is an ordinary custom point, so `/analyze` can be run there to see its full result. A test confirms that doing so reproduces rescue's reported outcome exactly.

*(This replaced an earlier precomputed "local maps" design, which was limited to the four curated sites and a fixed 2 m reference height.)*

### 4.2 Evidence

- **The bisection is truly minimal:** for Site 01's failing case, a test confirms the found height passes and **every lower 0.5 m step fails**.
- **Nearby results are exact:** re-analysing the suggested point with `/analyze` gives the same darkness as rescue reported (tested).
- **Example**, Site 01, 2-week mission from 1 Dec 2030, 24 h darkness limit, 2 m mast. The baseline fails (252 h darkness). Rescue offers:
  - **raise the mast to 8 m → 6 h darkness**;
  - **start 37.4 days earlier** (24 Oct 2030), which meets every limit;
  - **move 566 m toward azimuth 182° → 0 h darkness** (high-detail terrain, ground 1,933 m).

  A first rescue takes about 13 s, of which the nearby search is about 8 s; repeats take about 7 s.

## 5. Assumptions and limits

- Everything inherits the signed-off physics: point-source Sun and Earth, LOLA terrain as ingested, the 0–20 m height range.
- The calendar and rescue need **hourly sampling** and whole-hour durations.
- **Rescue options change one thing at a time.** Combinations (e.g. a 5 m mast *and* a 3-day shift) aren't searched.
- **The nearby search** covers ±800 m at 200 m spacing and verifies at most two candidates exactly. Better spots between grid points, farther away, or ranked lower by the approximate screen can be missed.
- **"Dominant blocker"** describes the single highest horizon point in the sector where the body was hidden longest. It identifies *where* the blocking terrain is, not its name: there's no gazetteer of named lunar features in the data.

## 6. Review sign-off

| Stage | Reviewer | Date | Decision / comments |
|---|---|---|---|
| Calendar definitions (§2.2) and evidence (§2.3) | Randy Moore | 2026-11-15 | Approved |
| Explanation definitions (§3), incl. the limb rule | Randy Moore | 2026-11-15 | Approved |
| Rescue options and the on-demand nearby search (§4) | Randy Moore | 2026-11-15 | Approved |
