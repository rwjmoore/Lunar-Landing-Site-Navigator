# frames.md — Coordinates and local geometry (P1)

> **Review status: SIGNED OFF (2026-11-14).** Implemented in `src/backend/app/coordinates/frames.py`, tested against the checks in §7 (`tests/test_frames.py`), with evidence in §7.1. Any change to this component's behaviour needs a new review.

## 1. What this component does

Every later physics step needs four geometric operations:

| Operation | Used by |
|---|---|
| Site (latitude, longitude, height) ↔ Moon-fixed position vector | Everything |
| Local **east / north / up** directions at a site | Azimuth/elevation, ray casting |
| Any vector → **azimuth / elevation** as seen from a site | Sun/Earth directions (P2), terrain horizon (M2) |
| Walk a **great circle** from a site in a given direction for a given distance | Horizon ray casting (M2) |

This component is pure geometry. It uses no data files, no ephemeris and no terrain.

## 2. Reference body and frame

| Item | Choice | Why |
|---|---|---|
| Frame | `MOON_ME` (mean Earth / polar axis), Moon-centered, Moon-fixed | The LOLA terrain data is delivered in MOON_ME |
| $+Z$ axis | Lunar north pole | Frame definition |
| $+X$ axis | Toward $0^\circ$ longitude (mean Earth direction) | Frame definition |
| Body shape | **Sphere**, $R = 1737.4\ \text{km}$ | LOLA heights are relative to this sphere, so no ellipsoid is needed |
| Latitude $\varphi$ | Planetocentric (angle from the equatorial plane, seen from the Moon's center) | Matches LOLA products |
| Longitude $\lambda$ | East-positive, stored in $[0^\circ, 360^\circ)$ | `SCIENCE_CONVENTIONS.md` §3 |
| Height $h$ | Above the reference sphere, in metres | Matches LOLA heights |

Internally all angles are radians and all distances metres; degrees appear only at the API boundary.

## 3. Site ↔ position vector

A site at latitude $\varphi$, longitude $\lambda$ and height $h$ has the Moon-fixed position

$$
\mathbf{p} = (R + h)
\begin{pmatrix}
\cos\varphi \cos\lambda \\
\cos\varphi \sin\lambda \\
\sin\varphi
\end{pmatrix}
$$

The inverse, for a position $\mathbf{p} = (x, y, z)$ with length $r = \lVert\mathbf{p}\rVert$:

$$
\varphi = \arcsin\left(\frac{z}{r}\right),
\qquad
\lambda = \operatorname{atan2}(y,\ x) \bmod 360^\circ,
\qquad
h = r - R
$$

## 4. Local east / north / up directions

At a site, three perpendicular unit vectors describe "which way is which":

$$
\hat{\mathbf{u}} =
\begin{pmatrix}
\cos\varphi \cos\lambda \\
\cos\varphi \sin\lambda \\
\sin\varphi
\end{pmatrix},
\qquad
\hat{\mathbf{e}} =
\begin{pmatrix}
-\sin\lambda \\
\cos\lambda \\
0
\end{pmatrix},
\qquad
\hat{\mathbf{n}} =
\begin{pmatrix}
-\sin\varphi \cos\lambda \\
-\sin\varphi \sin\lambda \\
\cos\varphi
\end{pmatrix}
$$

- **Up** $\hat{\mathbf{u}}$ points straight away from the Moon's center.
- **East** $\hat{\mathbf{e}}$ is horizontal and points toward increasing longitude.
- **North** $\hat{\mathbf{n}}$ is horizontal and points toward the north pole. Near the south pole that means "away from the pole".

They form a right-handed set: $\hat{\mathbf{e}} \times \hat{\mathbf{n}} = \hat{\mathbf{u}}$.

These are the closed-form results of the definition in `SCIENCE_CONVENTIONS.md` §5 ($\hat{\mathbf{e}} \propto \hat{\mathbf{z}} \times \hat{\mathbf{u}}$, $\hat{\mathbf{n}} = \hat{\mathbf{u}} \times \hat{\mathbf{e}}$). The closed form needs no normalization, so it stays numerically clean near the pole.

**Pole guard.** Exactly at a pole, longitude is undefined, so "north" has no single direction. The code rejects sites with $\lvert\varphi\rvert > 89.999^\circ$ (`SCIENCE_CONVENTIONS.md` §5). Demo sites are well inside this limit.

## 5. Azimuth and elevation

To find where a target appears from a site, take the vector from the site to the target, $\mathbf{r} = \mathbf{p}_\text{target} - \mathbf{p}_\text{site}$, and measure its components along the local directions:

$$
E = \mathbf{r}\cdot\hat{\mathbf{e}},
\qquad
N = \mathbf{r}\cdot\hat{\mathbf{n}},
\qquad
U = \mathbf{r}\cdot\hat{\mathbf{u}}
$$

Then:

$$
\text{azimuth } A = \operatorname{atan2}(E,\ N) \bmod 360^\circ,
\qquad
\text{elevation } \alpha = \operatorname{atan2}\left(U,\ \sqrt{E^2 + N^2}\right)
$$

- Azimuth is **clockwise from north**: north $= 0^\circ$, east $= 90^\circ$, south $= 180^\circ$, west $= 270^\circ$.
- Elevation is measured from the site's local horizontal plane: $+90^\circ$ is straight up, negative is below.
- This is the same formula as `PROJECT_PLAN.md` §5.3, since $\sqrt{E^2+N^2}$ is the length of the horizontal component $\lVert\mathbf{r}_h\rVert$.
- Because $\mathbf{r}$ is taken from the **site**, not the Moon's center, the result is topocentric. That's what gives Earth's ~0.26° parallax correctly (P2).

## 6. Walking a great circle (for ray casting)

The horizon ray at azimuth $\theta$ must sample the terrain lying in the vertical plane that contains the site's "up" and the horizontal direction $\theta$. That plane passes through the Moon's center, because it contains $\hat{\mathbf{u}}$, which points along the site's position vector. A plane through the center cuts the sphere in a **great circle**. So the correct ray path is the great circle leaving the site at azimuth $\theta$, not a path of constant compass heading.

The unit direction (from the Moon's center) of the point an angular distance $\delta$ along that great circle is

$$
\hat{\mathbf{d}}(\theta, \delta) = \cos\delta \ \hat{\mathbf{u}} + \sin\delta \left(\cos\theta \ \hat{\mathbf{n}} + \sin\theta \ \hat{\mathbf{e}}\right),
\qquad
\delta = \frac{s}{R}
$$

where $s$ is the distance along the reference sphere's surface. Its latitude and longitude follow from §3, and the terrain height there is applied later (M2).

This vector form is equivalent to the standard "destination point" formula of spherical trigonometry. It reuses the east/north/up directions and avoids special cases near the pole.

**A useful exact result: how fast the surface drops away.** For a site with $h = 0$, a point on the sphere at angular distance $\delta$ appears at elevation exactly

$$
\alpha = -\frac{\delta}{2} \approx -\frac{s}{2R}
$$

(the tangent–chord angle theorem). This is the curvature term in the horizon-radius estimate in `PROJECT_PLAN.md` §5.2, so this test also confirms that estimate's geometry.

## 7. How it will be checked

**Exact or known-answer tests:**

| Check | Expected |
|---|---|
| Site at $\varphi = 0, \lambda = 0$ | $\hat{\mathbf{u}} = (1,0,0)$, $\hat{\mathbf{e}} = (0,1,0)$, $\hat{\mathbf{n}} = (0,0,1)$ |
| East/north/up at many sites, including $\varphi = -89.9^\circ$ | Unit length, mutually perpendicular, $\hat{\mathbf{e}}\times\hat{\mathbf{n}} = \hat{\mathbf{u}}$ |
| Target displaced along $\hat{\mathbf{n}}$, $\hat{\mathbf{e}}$, $-\hat{\mathbf{n}}$, $-\hat{\mathbf{e}}$ | Azimuth $0^\circ, 90^\circ, 180^\circ, 270^\circ$, elevation $0^\circ$ |
| Target displaced along $\hat{\mathbf{u}}$ | Elevation $90^\circ$ |
| Site → position → site round trip | Same $\varphi, \lambda, h$, including longitudes near $0^\circ/360^\circ$ |
| Great circle with $\delta = 0$ | Returns the site itself |
| Great circle from the equator, heading north, $\delta = 90^\circ$ | Reaches the north pole |
| Point reached at azimuth $\theta$, viewed from the site | Azimuth is exactly $\theta$ (any $\delta$ below $180^\circ$) |
| Point on the sphere at angular distance $\delta$, viewed from a site at $h = 0$ | Elevation is exactly $-\delta/2$ |
| Pole guard | $\lvert\varphi\rvert > 89.999^\circ$ is rejected |

**Evidence I'll bring back for sign-off:** the test results, plus one small table of azimuth/elevation values for a realistic south-pole site (e.g. elevation of a 5 km peak at 50, 100 and 186 km), compared against the hand formula $h/d - d/(2R)$.

### 7.1 Evidence (2026-11-14)

**Tests:** `src/backend/tests/test_frames.py`, 60 test cases covering every row of the table above, all passing (`python -m pytest`, full suite 95 passed). Tolerances: $10^{-12}$ for unit vectors and round-trip angles, $10^{-9}$ for azimuths and the $-\delta/2$ check (relative), $10^{-6}\ \text{m}$ for round-trip heights. Orthonormality was checked at 7 sites, including $\varphi = -89.9^\circ$ and $+89.9^\circ$. The azimuth-preserving check used 48 azimuths × 5 distances up to $\delta = 3\ \text{rad}$ at 3 sites.

**Realistic south-pole example.** Site at $\varphi = -89.5^\circ$, $\lambda = 300^\circ$, $h = 0$, looking at azimuth $123^\circ$ toward a peak $5\ \text{km}$ high at surface distance $s$. "Exact" is computed by the code; "hand formula" is the small-angle estimate from `PROJECT_PLAN.md` §5.2:

| Distance $s$ (km) | Peak height (km) | Exact elevation (code) | Hand formula $h/s - s/(2R)$ | Difference |
|---|---|---|---|---|
| 10 | 5 | $+26.3672^\circ$ | $+28.4830^\circ$ | $-2.1158^\circ$ |
| 50 | 5 | $+4.8776^\circ$ | $+4.9051^\circ$ | $-0.0275^\circ$ |
| 100 | 5 | $+1.2086^\circ$ | $+1.2159^\circ$ | $-0.0073^\circ$ |
| 186 | 5 | $-1.5308^\circ$ | $-1.5267^\circ$ | $-0.0041^\circ$ |
| 200 | 5 | $-1.8693^\circ$ | $-1.8654^\circ$ | $-0.0039^\circ$ |

**Reading the table:**
- From $50\ \text{km}$ out, code and hand formula agree to within $0.03^\circ$, so the geometry matches the independent estimate.
- At $10\ \text{km}$ they differ by $2^\circ$. That is expected: the hand formula assumes small angles, and a 5 km peak at 10 km is at about $26^\circ$. The code uses no small-angle approximation, which is why the ray casting will use it rather than the formula.
- At $186\ \text{km}$ the peak sits at $-1.53^\circ$, confirming the 200 km horizon radius chosen in `PROJECT_PLAN.md` §5.2.

## 8. Assumptions and limits

- **Sphere, not ellipsoid.** The Moon's flattening is about 0.0012, but LOLA heights are defined against the 1737.4 km sphere, so using the same sphere is consistent with the data. Verified against the GeoTIFF metadata in P3.
- **No refraction.** The Moon has no meaningful atmosphere, so light travels in straight lines.
- **Frame realization.** MOON_ME as realized by the chosen ephemeris (DE421 recommended, see P2). This component doesn't depend on that choice.
- **Pole exclusion** as described in §4.
- **Float64 throughout.** At lunar-radius magnitudes this keeps position precision far below a millimetre.

## 9. Review sign-off

| Stage | Reviewer | Date | Decision / comments |
|---|---|---|---|
| Approach (§2–§6) | Randy Moore | 2026-11-14 | Approved |
| Implementation and evidence (§7) | Randy Moore | 2026-11-14 | Signed off |
