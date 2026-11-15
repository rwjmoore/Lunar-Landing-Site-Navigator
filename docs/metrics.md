# metrics.md — Mission metrics and constraints

> **Review status: PARTIALLY REVIEWED** (see §6; the coverage rule is accepted, the rest is pending). The metric framework is software structure, but the metric *definitions* (§3) and constraint *rules* (§4) decide what results mean, so they go through the physics review gate. Do not treat them as final until signed off in §6.

Code: `src/backend/app/metrics/` (framework + metrics) and `src/backend/app/planning/constraints.py` (pass/fail).

## 1. Why a framework

Fidelity will grow by adding metrics: visible solar-disk fraction, energy generated, minimum battery charge, and so on. The framework makes each metric a small self-contained unit so adding one does not touch scoring, the API, or other metrics.

The JSON contract with the frontend is **unchanged**: the API still outputs the four fixed metric fields. Moving the contract to a generic metric list is deferred (see `PROJECT_PLAN.md` §5.5).

## 2. How it works

```text
EvaluationContext                     Metric (one per quantity)            MetricResult
  offsets_s[]   sample times ───────►   id, label, units, requires  ──►   value, units, coverage,
  weights_s[]   seconds per sample      compute(context)                   worst_interval, notes
  series{name: array}

Constraint(metric_id, "<=" | ">=", limit) + MetricResult ──► ConstraintResult(value, margin, passed)
All ConstraintResults ──► feasibility: feasible | infeasible | unknown
```

- **EvaluationContext** holds the mission time grid and named time series (one NumPy array per quantity, all the same length). Metrics read series by name; they never compute physics themselves.
- **Metric** is any object with `id`, `label`, `units`, `requires` (the series names it reads) and `compute(context)`. Missing required series fail loudly before any metric runs.
- **Registry** (`app/metrics/registry.py`) is one explicit tuple listing the active metrics. No automatic discovery.
- **Reuse:** the four MVP metrics are two classes, each instantiated for Sun and for Earth. A future joint Sun+Earth metric is the same classes pointed at a `joint_visible` series.

### Adding a metric

1. Write a class with `id`, `label`, `units`, `requires`, `compute(context) -> MetricResult` in `app/metrics/`.
2. If it needs a new time series (e.g. `power_w`), that series must be produced by the physics layer and placed in the context.
3. Add an instance to `DEFAULT_METRICS` in `registry.py`.
4. Add tests covering normal, edge and unknown-data cases.
5. Document its definition in §3 of this file and get it reviewed.

Any metric can immediately be used in a `Constraint` by its `id`.

## 3. Metric definitions

### 3.1 Time accounting (from `SCIENCE_CONVENTIONS.md` §2)

**Symbols used below**

| Symbol | Meaning | Units |
|---|---|---|
| $D$ | Mission duration | s |
| $\Delta t$ | Sample step | s |
| $N$ | Number of samples | — |
| $k$ | Sample index, $k = 0, 1, \dots, N-1$ | — |
| $t_k$ | Time of sample $k$, measured from mission start | s |
| $w_k$ | Weight of sample $k$: how much mission time it represents | s |
| $s_k$ | Visibility state of sample $k$ (§3.2) | — |

**Sample times.** Samples are taken every $\Delta t$ starting at mission start:

$$
N = \left\lfloor \frac{D}{\Delta t} \right\rfloor + 1,
\qquad
t_k = k \, \Delta t
$$

**Sample weights.** Each sample stands for the time from itself to the next sample, $[t_k,\ t_k + \Delta t)$, cut off at mission end:

$$
w_k = \min\left(\Delta t,\ D - t_k\right)
$$

The weights always add up to the mission duration: $\sum_k w_k = D$.

**Worked example.** $D = 3\ \text{h}$, $\Delta t = 1\ \text{h}$ gives $N = 4$ samples at $0, 1, 2, 3\ \text{h}$ with weights $1, 1, 1, 0\ \text{h}$.

> **Note:** when $D$ is an exact multiple of $\Delta t$, the last sample sits exactly at mission end and has weight $0$. Its state still appears in the output series but contributes no time to any metric.

### 3.2 Visibility states

Each visibility series has one value per sample:

| $s_k$ | Meaning |
|---|---|
| $1$ | Visible |
| $0$ | Obstructed |
| $-1$ | Unknown (no-data terrain or missing information) |

Any other value is rejected as an error.

**Coverage** is the share of mission time whose state is known. Every metric result reports it:

$$
c = \frac{\displaystyle\sum_{k \,:\, s_k \neq -1} w_k}{\displaystyle\sum_{k} w_k}
\qquad 0 \le c \le 1
$$

### 3.3 Visible fraction

Metric ids: `sun_visible_fraction`, `earth_visible_fraction`.

The share of **known** mission time during which the body is visible:

$$
f = \frac{\text{time visible}}{\text{time known}}
  = \frac{\displaystyle\sum_{k \,:\, s_k = 1} w_k}{\displaystyle\sum_{k \,:\, s_k \neq -1} w_k}
$$

- Units: fraction, $0 \le f \le 1$.
- Unknown samples are left out of both the top and the bottom of the fraction.
- If no time is known (the bottom is $0$), the value is `None` (not computable), never $0$ or $1$.

**Example.** States $1, 1, 0, -1$ with weights of $1\ \text{h}$ each: $f = 2/3$ and $c = 3/4$.

### 3.4 Longest outage

Metric ids: `max_continuous_darkness_hours` (Sun), `max_continuous_earth_blackout_hours` (Earth).

An **outage** is a run of consecutive obstructed samples, from index $i$ to index $j$, that cannot be extended in either direction:

$$
s_i = s_{i+1} = \dots = s_j = 0
$$

Its duration is the total weight of its samples. The metric is the longest one, in hours:

$$
d(i, j) = \sum_{k=i}^{j} w_k,
\qquad
L = \frac{1}{3600} \max_{\text{outages}} d(i, j)
$$

- Units: hours. $L = 0$ if there are no outages.
- **Unknown samples break runs.** With $c < 1$ the true longest outage may be longer than reported, and a note is attached.
- The worst outage is reported with its sample indices and start/end times. If several tie, the earliest is reported.
- An outage that starts at the first sample or ends at the last sample is flagged **boundary-truncated**: it may continue outside the mission window.
- If no time is known, the value is `None`.

**Example.** Hourly states $1, 1, 0, 0, 0, 1, 1$: one outage at samples $2$–$4$, so $L = 3\ \text{h}$, from $t = 2\ \text{h}$ to $t = 5\ \text{h}$.

## 4. Constraint rules

A constraint is `(metric_id, comparator, limit)`, with the limit in the metric's units. Example: `("max_continuous_darkness_hours", "<=", 24)` means "the longest darkness must be at most 24 h".

**Signed margin.** For metric value $v$ and limit $\ell$, the margin $m$ is in the metric's units, and positive means passing:

$$
m =
\begin{cases}
\ell - v & \text{for an upper limit } (v \le \ell) \\
v - \ell & \text{for a lower limit } (v \ge \ell)
\end{cases}
$$

*Example:* longest darkness $v = 20\ \text{h}$ against $\ell = 24\ \text{h}$ gives $m = +4\ \text{h}$ (passing with 4 h to spare).

**Outcome of each constraint:**

- **Passed** when $m \ge 0$, so a value exactly at the limit passes.
- **Unknown (`passed = None`)** when:
  - the value is `None`, or
  - the metric's coverage is $c < 1$. *Rationale:* unknown samples could hide a longer outage or change a fraction, so neither pass nor fail is certain. This is conservative: a site with any no-data in the window cannot be called feasible. **Accepted in review (2026-11-14)**, knowing that sites with small data gaps will show as "unknown".
- Referencing a metric id that was not computed is an error, not a silent pass.

**Overall feasibility** combines all constraint outcomes:

1. If any constraint failed → `infeasible`.
2. Otherwise, if any constraint is unknown → `unknown`.
3. Otherwise (all passed) → `feasible`.

## 5. Not covered here

- Producing the visibility series (terrain horizon vs Sun/Earth position). That is P4/P5 physics with its own explainer.
- Ranking among feasible candidates (plan §5.6 step 4).
- Mapping results to the API response (done when `/analyze` is built).

## 6. Review sign-off

| Section | Reviewer | Date | Decision / comments |
|---|---|---|---|
| §3 Metric definitions | | | |
| §4 Constraint rules: coverage $c < 1$ → unknown | Randy Moore | 2026-11-14 | Accepted |
| §4 Constraint rules: remainder (margins, tie passes, aggregation) | | | |
