import { useState } from 'react'
import { coordinates, formatMetric, metricLabels, sameSite, type Candidate, type Metrics, type Site } from './analysis'
import { PolarLocator, type Sector } from './MapView'

const constraintLabels: Record<string, string> = {
  max_darkness_hours: 'Maximum darkness', max_continuous_darkness_hours: 'Maximum darkness',
  max_earth_blackout_hours: 'Maximum Earth blackout', max_continuous_earth_blackout_hours: 'Maximum Earth blackout',
}

function constraintLabel(key: string) {
  return constraintLabels[key] ?? key.replaceAll('_', ' ')
}

const statusLabels = { feasible: 'Feasible', infeasible: 'Infeasible', unknown: 'Unknown', unavailable: 'Unavailable' }

function formatDelta(key: keyof Metrics, current: number, baseline: number) {
  const delta = current - baseline
  const sign = delta >= 0 ? '+' : '−'
  return key.endsWith('_fraction') ? `${sign}${(Math.abs(delta) * 100).toFixed(1)} pp` : `${sign}${Math.abs(delta).toFixed(1)} h`
}

function Metric({ field, candidate, baseline }: { field: keyof Metrics; candidate?: Candidate; baseline?: Candidate }) {
  const value = candidate?.metrics[field]
  const previous = baseline?.metrics[field]
  const isSun = field === 'sun_visible_fraction'
  const isEarth = field === 'earth_visible_fraction'
  const solarMetric = isSun || field === 'max_continuous_darkness_hours'
  const partial = (solarMetric ? candidate?.series.sun_visible : candidate?.series.earth_visible)?.includes(null)
  const caption = isSun ? (partial ? 'Share of known time with Sun LOS' : 'Fraction of mission with Sun LOS')
    : isEarth ? (partial ? 'Share of known time with Earth LOS' : 'Direct geometric Earth LOS')
    : partial ? 'Hours in known intervals' : 'Hours'
  return <div className="metric">
    <span className="metric-label">
      {isSun && <span className="sun-ink" aria-hidden="true">☀</span>}{isEarth && <span className="earth-ink" aria-hidden="true">◉</span>}
      {metricLabels[field]}
    </span>
    <strong aria-label={value == null ? `${metricLabels[field]} unavailable` : undefined}>{formatMetric(field, value)}</strong>
    <small>{caption}</small>
    {baseline && <small className="metric-delta">{formatMetric(field, previous)} at baseline
      {value != null && previous != null && <b>{formatDelta(field, value, previous)}</b>}</small>}
  </div>
}

export function SiteAnalysis({ site, candidate, baseline, sector, source, onClose, onInspect }: {
  site: Site; candidate?: Candidate; baseline?: Candidate; sector: Sector; source?: string;
  onClose?: () => void; onInspect?: () => void;
}) {
  const sun = candidate?.horizons.sun_observer_horizon_elevation_deg ?? []
  const earth = candidate?.horizons.earth_observer_horizon_elevation_deg ?? []
  const hasSun = sun.filter(value => value !== null).length >= 2
  const hasEarth = earth.filter(value => value !== null).length >= 2
  const gaps = sun.includes(null) || earth.includes(null)
  const unknownSamples = candidate?.series.sun_visible.includes(null) || candidate?.series.earth_visible.includes(null)
  const note = !hasSun && !hasEarth ? 'Terrain data missing. Sun and Earth visibility are unknown.'
    : !hasSun ? 'Solar mast terrain data missing. Sun visibility is unknown.'
    : !hasEarth ? 'Antenna terrain data missing. Earth visibility is unknown.'
    : gaps ? 'Terrain coverage is incomplete. Visibility is unknown where terrain data is missing.'
    : unknownSamples ? 'Some visibility samples are unknown.' : null
  const status = candidate?.feasibility.status ?? 'unknown'
  const failures = candidate?.feasibility.failed_constraints ?? []
  const margins = Object.entries(candidate?.feasibility.margins ?? {})
  const provenance = candidate?.provenance

  return <aside className="site-analysis panel" aria-label="Site Analysis">
    <div className="side-heading"><h2>Site Analysis</h2>{onClose && <button aria-label="Close site details" onClick={onClose}>×</button>}</div>
    <div className="side-content">
      <div className="side-site"><strong>{site.name}</strong><span>{coordinates(site)}</span></div>
      {source && <span className={`source-label ${source === 'Demo data' ? 'caution' : ''}`}>{source}</span>}
      <div className="metric-list">
        <Metric field="sun_visible_fraction" candidate={candidate} baseline={baseline} />
        <Metric field="earth_visible_fraction" candidate={candidate} baseline={baseline} />
        <div className="metric-pair"><Metric field="max_continuous_darkness_hours" candidate={candidate} baseline={baseline} />
          <Metric field="max_continuous_earth_blackout_hours" candidate={candidate} baseline={baseline} /></div>
      </div>
      {baseline && candidate && <p className="baseline-note">Solar mast {baseline.vehicle.solar_panel_mast_height_m} m → {candidate.vehicle.solar_panel_mast_height_m} m</p>}
      <div className="assessment">
        <strong>Feasibility <span className={`status-pill ${status}`}>{statusLabels[status]}</span></strong>
        {note && <p>{note}</p>}
        {failures.length > 0 && <div className="failure-list"><span>Failed constraints</span><ul>
          {failures.map((failure, i) => <li key={i}>{constraintLabel(failure)}</li>)}
        </ul></div>}
        {margins.length > 0 && <dl className="margins">{margins.map(([key, value]) => <div key={key}>
          <dt>{constraintLabel(key)} margin</dt><dd>{value > 0 ? '+' : ''}{value.toFixed(1)}{key.endsWith('_hours') ? ' h' : ''}</dd>
        </div>)}</dl>}
        {candidate?.diagnostics.map((text, i) => <p key={i}>{text}</p>)}
      </div>
      {!onInspect && <PolarLocator site={site} sector={sector} />}
      <details className="provenance">
        <summary>Sources &amp; assumptions</summary>
        <dl>
          <div><dt>Terrain model</dt><dd>{provenance?.dem_id ?? 'Unavailable'}</dd></div>
          <div><dt>Ephemeris</dt><dd>{provenance?.ephemeris_id ?? 'Unavailable'}</dd></div>
          {candidate && <><div><dt>Sample step</dt><dd>{candidate.provenance.sample_step_seconds / 3600} h</dd></div>
          <div><dt>Solar mast / antenna</dt><dd>{candidate.vehicle.solar_panel_mast_height_m} / {candidate.vehicle.antenna_height_m} m</dd></div></>}
          {candidate?.location.surface_elevation_m != null && <div><dt>Surface elevation</dt><dd>{candidate.location.surface_elevation_m.toFixed(1)} m</dd></div>}
        </dl>
        <p>Solar access indicates illumination opportunity. Earth visibility measures geometric line of sight. Power generation and radio performance require separate models.</p>
      </details>
      {onInspect && <button className="primary inspect-button" onClick={onInspect}>Inspect Horizon <span aria-hidden="true">→</span></button>}
    </div>
  </aside>
}

export interface Row { site: Site; candidate?: Candidate }
type SortField = keyof Metrics | 'site' | 'status' | 'constraint'
const columns: { key: SortField; title: string }[] = [
  { key: 'site', title: 'Site' }, { key: 'sun_visible_fraction', title: 'Solar access' },
  { key: 'earth_visible_fraction', title: 'Earth visibility' },
  { key: 'max_continuous_darkness_hours', title: 'Darkness (h)' },
  { key: 'max_continuous_earth_blackout_hours', title: 'Blackout (h)' },
  { key: 'status', title: 'Feasibility' }, { key: 'constraint', title: 'Main constraint' },
]

function reason(row: Row) {
  const { candidate } = row
  if (!candidate) return 'No analysis loaded'
  const failure = candidate.feasibility.failed_constraints[0]
  if (failure) return constraintLabel(failure)
  if (candidate.feasibility.status === 'feasible') return 'Constraints met'
  if (candidate.feasibility.status === 'infeasible') return 'Failed constraints'
  if (candidate.feasibility.status === 'unavailable') return 'Analysis unavailable'
  return 'Insufficient coverage'
}

function sortValue(row: Row, key: SortField) {
  if (key === 'site') return row.site.name
  if (key === 'constraint') return row.candidate ? reason(row) : null
  if (key === 'status') {
    const status = row.candidate?.feasibility.status
    return status === 'feasible' ? 0 : status === 'infeasible' ? 1 : null
  }
  return row.candidate?.metrics[key] ?? null
}

export function Rankings({ rows, active, onSelect, compare, busy, summary, message }: {
  rows: Row[]; active?: Site; onSelect: (row: Row) => void; compare?: () => void; busy: boolean; summary: string; message: string;
}) {
  const [sort, setSort] = useState<{ key: SortField; ascending: boolean }>({ key: 'sun_visible_fraction', ascending: false })
  const ordered = rows.slice().sort((a, b) => {
    const left = sortValue(a, sort.key)
    const right = sortValue(b, sort.key)
    if (left === null || right === null) return left === right ? 0 : left === null ? 1 : -1
    const order = typeof left === 'number' && typeof right === 'number' ? left - right : String(left).localeCompare(String(right))
    return sort.ascending ? order : -order
  })
  return <div className="rankings-content">
    <div className="ranking-toolbar"><p>{summary}</p>{compare && <button className="primary" disabled={busy} onClick={compare}>{busy ? 'Analyzing sites…' : 'Run comparison'}</button>}</div>
    <div className="table-scroll" tabIndex={0} aria-label="Candidate site comparison">
      <table className="comparison-table">
        <thead><tr>{columns.map(({ key, title }) => <th key={key} scope="col" aria-sort={sort.key !== key ? 'none' : sort.ascending ? 'ascending' : 'descending'}>
          <button onClick={() => setSort({ key, ascending: sort.key === key ? !sort.ascending : true })}>{title}
            <span aria-hidden="true">{sort.key !== key ? '↕' : sort.ascending ? '↑' : '↓'}</span></button>
        </th>)}</tr></thead>
        <tbody>{ordered.map(row => {
          const status = row.candidate?.feasibility.status ?? 'unknown'
          const selected = active !== undefined && sameSite(active, row.site)
          return <tr key={`${row.site.latitude_deg}/${row.site.longitude_deg_east}`} className={selected ? 'selected' : ''} onClick={() => onSelect(row)}>
            <th scope="row"><button aria-label={`Open site analysis for ${row.site.name}`} aria-pressed={selected} onClick={e => { e.stopPropagation(); onSelect(row) }}>
              <strong>{row.site.name}</strong><span>{coordinates(row.site)}</span></button></th>
            {columns.filter(({ key }) => key in metricLabels).map(({ key }) => <td className="metric-cell" key={key}>
              {formatMetric(key as keyof Metrics, row.candidate?.metrics[key as keyof Metrics])}</td>)}
            <td><span className={`status-pill ${status}`}>{statusLabels[status]}</span></td><td>{reason(row)}</td>
          </tr>
        })}
        {ordered.length === 0 && <tr><td colSpan={columns.length} className="table-empty"><strong>No candidates to compare</strong>
          <p>Comparison needs terrain analysis for at least two sites under the same mission settings.</p></td></tr>}
        </tbody>
      </table>
    </div>
    {message && <p className="ranking-message" role="status">{message}</p>}
  </div>
}
