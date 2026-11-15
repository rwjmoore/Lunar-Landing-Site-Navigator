// Mission planning panel: plain-language explanation, start-date calendar and mission rescue
// (POST /insights, /calendar, /rescue). Shown under the horizon view for backend analyses.
import { useEffect, useRef, useState } from 'react'
import { formatUtc, type Candidate, type Settings, type Site, type Vehicle } from './analysis'
import { planningSupported, requestCalendar, requestInsights, requestRescue, yearRange,
  type CalendarResult, type Insights, type Outage, type Outcome, type Rescue, type RescueOption } from './planningApi'

export type PlanTab = 'explain' | 'calendar' | 'rescue'
type Run = (site: Site, settings: Settings, previousVehicle?: Vehicle) => void

const tabs: { id: PlanTab; label: string }[] = [
  { id: 'explain', label: 'Why & what next' }, { id: 'calendar', label: 'Start dates' }, { id: 'rescue', label: 'Fix this mission' },
]

function duration(hours: number | null | undefined) {
  if (hours == null) return '—'
  return hours >= 72 ? `${(hours / 24).toFixed(1)} days` : `${hours.toFixed(0)} h`
}

const percent = (value: number | null | undefined) => value == null ? '—' : `${(value * 100).toFixed(0)}%`
const errorText = (error: unknown, fallback: string) => error instanceof Error ? error.message : fallback

/** Loads one planning result, cancelling it if the inputs change or the panel closes. */
function useRequest<T>(load: ((signal: AbortSignal) => Promise<T>) | null, deps: unknown[]) {
  const [state, setState] = useState<{ data?: T; error?: string; busy: boolean }>({ busy: false })
  useEffect(() => {
    if (!load) return
    const controller = new AbortController()
    setState({ busy: true })
    load(controller.signal).then(data => setState({ data, busy: false }))
      .catch(error => { if (!controller.signal.aborted) setState({ error: errorText(error, 'The request failed.'), busy: false }) })
    return () => controller.abort()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)
  return state
}

export function PlanningPanel({ apiUrl, site, settings, candidate, index, tab, onTab, supportedEndUtc, onRun }: {
  apiUrl: string; site: Site; settings: Settings; candidate: Candidate; index: number
  tab: PlanTab; onTab: (tab: PlanTab) => void; supportedEndUtc: string | null; onRun: Run
}) {
  const supported = planningSupported(settings)
  return <section className="planning" aria-label="Mission planning">
    <div className="planning-heading">
      <h2>Mission planning</h2>
      <div className="plan-tabs" role="tablist">
        {tabs.map(item => <button key={item.id} role="tab" aria-selected={tab === item.id} onClick={() => onTab(item.id)}>{item.label}</button>)}
      </div>
    </div>
    {tab === 'explain' && <Explain apiUrl={apiUrl} site={site} settings={settings} candidate={candidate} index={index} />}
    {tab !== 'explain' && !supported && <p className="plan-note">Start dates and mission rescue need hourly samples. Set the sample step to 1 h in Mission.</p>}
    {tab === 'calendar' && supported && <Calendar apiUrl={apiUrl} site={site} settings={settings} supportedEndUtc={supportedEndUtc} onRun={onRun} />}
    {tab === 'rescue' && supported && <RescuePanel apiUrl={apiUrl} site={site} settings={settings} candidate={candidate} onRun={onRun} />}
  </section>
}

// -- Why & what next (/insights) ---------------------------------------------------------

function Explain({ apiUrl, site, settings, candidate, index }: {
  apiUrl: string; site: Site; settings: Settings; candidate: Candidate; index: number
}) {
  const { data, error, busy } = useRequest<Insights>(signal => requestInsights(apiUrl, { site, ...settings }, signal), [])
  if (busy) return <p className="plan-note" role="status">Explaining the analysis…</p>
  if (error || !data) return <p className="plan-note form-error" role="alert">{error ?? 'No explanation available.'}</p>
  const at = Math.min(index, data.timestamps_utc.length - 1)
  const now = data.timestamps_utc[at]
  const next = (body: 'sun' | 'earth') => {
    const visible = (body === 'sun' ? candidate.series.sun_visible : candidate.series.earth_visible)[at]
    const hours = (body === 'sun' ? data.sun_hours_to_change : data.earth_hours_to_change)[at]
    const name = body === 'sun' ? 'Sun' : 'Earth'
    if (visible == null) return `${name}: visibility unknown`
    return hours == null ? `${name} ${visible ? 'stays visible' : 'stays hidden'} to the end of the mission`
      : `${name} ${visible ? 'sets' : 'rises'} in ${duration(hours)}`
  }
  return <div className="plan-body">
    <div className="plan-now" aria-live="polite">
      <span>At {formatUtc(now)}</span>
      <strong className="sun-ink">☀ {next('sun')}</strong>
      <strong className="earth-ink">◉ {next('earth')}</strong>
    </div>
    <ul className="plan-summary">{data.summary.map((line, i) => <li key={i}>{line}</li>)}</ul>
    <div className="plan-cards">
      <div className="plan-card">
        <h3>Sun and Earth together</h3>
        <p className="plan-figure">{percent(data.joint_visible_fraction)} <small>of the mission</small></p>
        <p>Longest window to charge and talk at once: <b>{duration(data.longest_joint_window_hours)}</b>
          {data.longest_joint_window_start_utc && <> from {formatUtc(data.longest_joint_window_start_utc)}</>}.</p>
      </div>
      {data.outages.map(outage => <OutageCard key={outage.body} outage={outage} />)}
    </div>
    <details className="provenance plan-events">
      <summary>All rise and set events ({data.events.length})</summary>
      <ol>{data.events.map((event, i) => <li key={i}>
        <time>{formatUtc(event.time_utc)}</time>
        <span className={event.body === 'sun' ? 'sun-ink' : 'earth-ink'}>{event.body === 'sun' ? 'Sun' : 'Earth'} {event.event === 'rise' ? 'rises' : 'sets'}</span>
      </li>)}</ol>
    </details>
  </div>
}

function OutageCard({ outage }: { outage: Outage }) {
  const sun = outage.body === 'sun'
  const d = outage.dominant
  return <div className="plan-card">
    <h3>{sun ? 'Longest darkness' : 'Longest Earth blackout'}</h3>
    <p className="plan-figure">{duration(outage.duration_hours)} <small>{formatUtc(outage.start_utc)} → {formatUtc(outage.end_utc)}</small></p>
    <p>{outage.text}</p>
    <dl className="margins">
      <div><dt>Main blocker</dt><dd>{d.azimuth_deg.toFixed(0)}° az, {(d.distance_m / 1000).toFixed(d.distance_m < 10_000 ? 1 : 0)} km away</dd></div>
      <div><dt>Blocked by terrain within 1 km</dt><dd>{percent(outage.near_share)}</dd></div>
      <div><dt>Below the Moon's own horizon</dt><dd>{percent(outage.below_limb_share)}</dd></div>
    </dl>
    {outage.below_limb_share >= 0.5 && <p className="caution">Mostly below the Moon's curved horizon: no mast height or short move can fix this part.</p>}
  </div>
}

// -- Start dates (/calendar) --------------------------------------------------------------

const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

function cellColor(status: string, margin: number | null) {
  if (status === 'feasible') return margin != null && margin >= 24 ? '#3f9d74' : margin != null && margin >= 6 ? '#2f7a5a' : '#25563f'
  if (status === 'infeasible') return margin != null && margin <= -48 ? '#8a3a3c' : '#5e2f31'
  return '#6b5332'
}

function Calendar({ apiUrl, site, settings, supportedEndUtc, onRun }: {
  apiUrl: string; site: Site; settings: Settings; supportedEndUtc: string | null; onRun: Run
}) {
  const missionYear = Number(settings.mission.start_utc.slice(0, 4))
  const [year, setYear] = useState(missionYear)
  const lastYear = Number((supportedEndUtc ?? '2040').slice(0, 4))
  const years = Array.from({ length: lastYear - 2026 + 1 }, (_, i) => 2026 + i)
  const range = yearRange(year, settings.mission.start_utc, settings.mission.duration_hours, supportedEndUtc)
  const { data, error, busy } = useRequest<CalendarResult>(range
    ? signal => requestCalendar(apiUrl, site, settings, range.from, range.to, signal) : null, [year, range?.from, range?.to])
  const byDay = new Map(data?.starts_utc.map((start, i) => [start.slice(5, 10), i]) ?? [])
  const choose = (start: string) => onRun(site, { ...settings, mission: { ...settings.mission, start_utc: start } })
  const requested = settings.mission.start_utc

  return <div className="plan-body">
    <div className="plan-toolbar">
      <p>Each square is a {duration(settings.mission.duration_hours)} mission starting that day at {requested.slice(11, 16)} UTC, with the current vehicle and limits. Click a day to analyse it.</p>
      <label>Year <select value={year} onChange={event => setYear(Number(event.target.value))}>
        {years.map(value => <option key={value} value={value}>{value}</option>)}</select></label>
    </div>
    {!range && <p className="plan-note">No {duration(settings.mission.duration_hours)} mission fits in {year}.</p>}
    {busy && <p className="plan-note" role="status">Evaluating every start date…</p>}
    {error && <p className="plan-note form-error" role="alert">{error}</p>}
    {data && !busy && <>
      <p className="plan-headline">
        <b>{data.feasible_count}</b> of {data.starts_utc.length} start dates meet every limit in {year}.
        {data.best_start_utc && <> Most slack: <button className="text-button" onClick={() => choose(data.best_start_utc!)}>
          {formatUtc(data.best_start_utc)}</button> ({data.best_worst_margin_hours! > 0 ? '+' : ''}{data.best_worst_margin_hours!.toFixed(0)} h margin).</>}
      </p>
      <div className="calendar-scroll" tabIndex={0} aria-label={`Start-date calendar for ${year}`}>
        <div className="calendar-grid">
          <span />{Array.from({ length: 31 }, (_, day) => <span key={day} className="calendar-day">{day + 1}</span>)}
          {months.map((month, m) => <div className="calendar-row" key={month}>
            <span className="calendar-month">{month}</span>
            {Array.from({ length: 31 }, (_, day) => {
              const i = byDay.get(`${String(m + 1).padStart(2, '0')}-${String(day + 1).padStart(2, '0')}`)
              if (i === undefined) return <span key={day} className="calendar-cell empty" />
              const start = data.starts_utc[i]
              const margin = data.worst_margin_hours[i]
              const title = `${formatUtc(start)} · ${data.status[i]} · darkness ${duration(data.max_darkness_hours[i])}, Earth blackout ${duration(data.max_earth_blackout_hours[i])}`
                + (margin != null ? ` · margin ${margin > 0 ? '+' : ''}${margin.toFixed(0)} h` : '')
              return <button key={day} className={`calendar-cell ${start === requested ? 'current' : ''}`} title={title} aria-label={title}
                style={{ background: cellColor(data.status[i], margin) }} onClick={() => choose(start)} />
            })}
          </div>)}
        </div>
      </div>
      <div className="interval-key">
        <span><i style={{ background: '#3f9d74' }} />Meets limits, ≥ 24 h slack</span>
        <span><i style={{ background: '#25563f' }} />Meets limits, little slack</span>
        <span><i style={{ background: '#5e2f31' }} />Fails a limit</span>
        <span><i style={{ background: '#6b5332' }} />Unknown</span>
        <span><i className="current-key" />Current start</span>
      </div>
    </>}
  </div>
}

// -- Fix this mission (/rescue) ---------------------------------------------------------

const kindTitles: Record<RescueOption['kind'], string> = {
  mast: 'Taller solar mast', antenna: 'Taller antenna', date_earlier: 'Start earlier', date_later: 'Start later',
  move_nearest: 'Move to the nearest good spot', move_best: 'Move to the best nearby spot',
}

function OutcomeLine({ outcome }: { outcome: Outcome }) {
  return <dl className="margins">
    <div><dt>Max darkness</dt><dd>{duration(outcome.max_darkness_hours)}</dd></div>
    <div><dt>Max Earth blackout</dt><dd>{duration(outcome.max_earth_blackout_hours)}</dd></div>
    <div><dt>Solar access · Earth visibility</dt><dd>{percent(outcome.sun_visible_fraction)} · {percent(outcome.earth_visible_fraction)}</dd></div>
  </dl>
}

function RescuePanel({ apiUrl, site, settings, candidate, onRun }: {
  apiUrl: string; site: Site; settings: Settings; candidate: Candidate; onRun: Run
}) {
  const [state, setState] = useState<{ data?: Rescue; error?: string; busy: boolean }>({ busy: false })
  const [elapsed, setElapsed] = useState(0)
  const operation = useRef<AbortController | null>(null)
  useEffect(() => () => operation.current?.abort(), [])
  useEffect(() => {
    if (!state.busy) return
    const started = Date.now()
    const timer = setInterval(() => setElapsed(Math.round((Date.now() - started) / 1000)), 500)
    return () => clearInterval(timer)
  }, [state.busy])

  async function search() {
    operation.current?.abort()
    const controller = new AbortController()
    operation.current = controller
    setElapsed(0)
    setState({ busy: true })
    try { setState({ data: await requestRescue(apiUrl, { site, ...settings }, controller.signal), busy: false }) }
    catch (error) { if (!controller.signal.aborted) setState({ error: errorText(error, 'Mission rescue failed.'), busy: false }) }
  }

  function apply(option: RescueOption) {
    const change = option.change
    if (option.kind === 'mast' && typeof change.solar_mast_height_m === 'number') {
      onRun(site, { ...settings, vehicle: { ...settings.vehicle, solar_panel_mast_height_m: change.solar_mast_height_m } }, settings.vehicle)
    } else if (option.kind === 'antenna' && typeof change.antenna_height_m === 'number') {
      onRun(site, { ...settings, vehicle: { ...settings.vehicle, antenna_height_m: change.antenna_height_m } })
    } else if (typeof change.start_utc === 'string') {
      onRun(site, { ...settings, mission: { ...settings.mission, start_utc: change.start_utc } })
    } else if (typeof change.latitude_deg === 'number' && typeof change.longitude_deg_east === 'number') {
      const name = `Rescue point, ${Math.round(Number(change.distance_m))} m from ${site.name}`
      onRun({ name, latitude_deg: change.latitude_deg, longitude_deg_east: change.longitude_deg_east }, settings)
    }
  }

  const failing = candidate.feasibility.status !== 'feasible'
  const { data, error, busy } = state
  return <div className="plan-body">
    <div className="plan-toolbar">
      <p>{failing ? 'Finds the smallest single change that makes this mission meet every limit: a taller mast or antenna, a different start date, or a spot up to 800 m away.'
        : 'This mission already meets every limit. A search shows how much extra slack each change would add.'}</p>
      <button className="primary" disabled={busy} onClick={search}>{busy ? `Searching… ${elapsed} s` : data ? 'Search again' : 'Find fixes'}</button>
    </div>
    {busy && <p className="plan-note" role="status">Checking mast heights, start dates within ±60 days and 80 nearby points. This usually takes 5–15 s.</p>}
    {error && <p className="plan-note form-error" role="alert">{error}</p>}
    {data && !busy && <>
      <div className="plan-cards">
        {data.options.map((option, i) => {
          const possible = option.kind.startsWith('move') || option.kind.startsWith('date') || Object.values(option.change).some(value => typeof value === 'number')
          return <div className={`plan-card ${option.fixes ? 'fixes' : ''}`} key={i}>
            <h3>{kindTitles[option.kind]} <span className={`status-pill ${option.outcome.status}`}>{option.fixes ? 'Fixes it' : !possible ? 'Not possible'
              : option.outcome.status === 'unknown' ? 'Uncertain' : 'Partly fixes'}</span></h3>
            <p>{option.text}</p>
            {possible && <OutcomeLine outcome={option.outcome} />}
            {option.change.terrain_detail === 'standard' && <p className="muted">Standard-detail terrain (40 m): mast effects there are less certain.</p>}
            {possible && <button onClick={() => apply(option)}>Apply and analyse <span aria-hidden="true">→</span></button>}
          </div>
        })}
      </div>
      {data.options.length === 0 && <p className="plan-note">No single change was found.</p>}
      {data.notes.map((note, i) => <p className="plan-note" key={i}>{note}</p>)}
    </>}
  </div>
}
