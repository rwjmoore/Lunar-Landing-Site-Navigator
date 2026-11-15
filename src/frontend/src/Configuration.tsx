import { useCallback, useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react'
import { sameSite, type Settings, type Site, type Vehicle } from './analysis'

export type Drawer = 'mission' | 'vehicle'
const titles = { mission: 'Mission Configuration', vehicle: 'Vehicle Configuration' }
const minUtc = '2026-01-01T00:00'
const maxUtc = '2040-12-31T23:00'
const maxMast = 20

export function EdgeDrawers({ open, pinned, onChange, mission, vehicle }: {
  open: Drawer | null; pinned: boolean; onChange: (drawer: Drawer | null, pinned?: boolean) => void;
  mission: ReactNode; vehicle: ReactNode;
}) {
  const timer = useRef<number | undefined>(undefined)
  const triggers = useRef<Partial<Record<Drawer, HTMLButtonElement | null>>>({})
  const headings = useRef<Partial<Record<Drawer, HTMLHeadingElement | null>>>({})
  const clear = useCallback(() => window.clearTimeout(timer.current), [])

  const close = useCallback((restoreFocus: boolean) => {
    clear()
    onChange(null)
    if (open && restoreFocus) triggers.current[open]?.focus()
  }, [clear, onChange, open])

  useEffect(() => {
    if (!open) return
    function escape(event: KeyboardEvent) {
      if (event.key === 'Escape' && !event.defaultPrevented) {
        event.preventDefault()
        close(true)
      }
    }
    window.addEventListener('keydown', escape)
    return () => { window.removeEventListener('keydown', escape); clear() }
  }, [clear, close, open])

  function leave(drawer: Drawer) {
    clear()
    if (!pinned && open === drawer) timer.current = window.setTimeout(() => {
      const panel = document.getElementById(`${drawer}-drawer`)
      if (!panel?.contains(document.activeElement)) close(false)
    }, 240)
  }

  return <>
    <div className="edge-triggers" aria-label="Mission and vehicle configuration">
      {(['mission', 'vehicle'] as const).map(drawer => <button key={drawer} ref={el => { triggers.current[drawer] = el }}
        aria-label={titles[drawer]} aria-expanded={open === drawer} aria-controls={`${drawer}-drawer`}
        className={open === drawer ? 'open' : ''}
        onPointerEnter={event => { clear(); if (event.pointerType === 'mouse' && !pinned) onChange(drawer) }}
        onPointerLeave={() => leave(drawer)} onClick={() => {
          if (open === drawer && pinned) { close(false); return }
          clear()
          onChange(drawer, true)
          requestAnimationFrame(() => headings.current[drawer]?.focus())
        }}><span aria-hidden="true">{drawer === 'mission' ? '◷' : '◇'}</span>{drawer === 'mission' ? 'Mission' : 'Vehicle'}</button>)}
    </div>
    {(['mission', 'vehicle'] as const).map(drawer => <aside className={`drawer ${open === drawer ? 'open' : ''}`} id={`${drawer}-drawer`}
      aria-labelledby={`${drawer}-title`} inert={open !== drawer} aria-hidden={open !== drawer}
      onPointerEnter={clear} onPointerLeave={() => leave(drawer)} onBlur={event => {
        if (!event.currentTarget.contains(event.relatedTarget)) leave(drawer)
      }} key={drawer}>
      <div className="drawer-heading"><h2 ref={el => { headings.current[drawer] = el }} tabIndex={-1} id={`${drawer}-title`}>{titles[drawer]}</h2>
        <div className="button-row"><button aria-label={pinned ? 'Unpin drawer' : 'Pin drawer'} title={pinned ? 'Unpin drawer' : 'Pin drawer'}
          aria-pressed={open === drawer && pinned} onClick={() => onChange(drawer, !pinned)}><span aria-hidden="true">⌖</span></button>
          <button aria-label="Close drawer" onClick={() => close(true)}>×</button></div></div>
      {drawer === 'mission' ? mission : vehicle}
    </aside>)}
  </>
}

function readWaypoint(form: HTMLFormElement, selected: Site): Site {
  const values = new FormData(form)
  const latitude = values.get('latitude')
  const longitude = values.get('longitude')
  const latitude_deg = Number(latitude)
  const longitude_deg_east = Number(longitude)
  if (!latitude || !longitude || !Number.isFinite(latitude_deg) || !Number.isFinite(longitude_deg_east)
    || latitude_deg < -90 || latitude_deg > -80 || longitude_deg_east < -180 || longitude_deg_east >= 360) {
    throw new Error('Enter a latitude from −90° to −80° and east longitude from −180° up to 360°.')
  }
  const point = { name: 'Selected waypoint', latitude_deg, longitude_deg_east }
  return sameSite(point, selected) ? selected : point
}

export function MissionFields({ site, sites, settings, onSelect, onRun, busy }: {
  site: Site; sites: Site[]; settings: Settings; onSelect: (site: Site) => void;
  onRun: (site: Site, settings: Settings) => void; busy: boolean;
}) {
  const form = useRef<HTMLFormElement>(null)
  const [error, setError] = useState('')
  const [latitude, setLatitude] = useState(String(Number(site.latitude_deg.toFixed(8))))
  const [longitude, setLongitude] = useState(String(Number(site.longitude_deg_east.toFixed(8))))
  const { mission, constraints } = settings

  useEffect(() => {
    setLatitude(String(Number(site.latitude_deg.toFixed(8))))
    setLongitude(String(Number(site.longitude_deg_east.toFixed(8))))
    setError('')
  }, [site.latitude_deg, site.longitude_deg_east])

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    try {
      const point = readWaypoint(event.currentTarget, site)
      const data = new FormData(event.currentTarget)
      const rawStart = String(data.get('start') ?? '')
      const start = Date.parse(`${rawStart}:00Z`)
      const duration_hours = Number(data.get('duration'))
      const sample_step_seconds = Number(data.get('cadence'))
      const max_darkness_hours = Number(data.get('darkness'))
      const max_earth_blackout_hours = Number(data.get('blackout'))
      const lastSample = start + Math.floor(duration_hours * 3600 / sample_step_seconds) * sample_step_seconds * 1000
      if (!/^\d{4}-\d\d-\d\dT\d\d:00$/.test(rawStart) || !Number.isFinite(start)
        || rawStart < minUtc || rawStart > maxUtc || lastSample > Date.parse(`${maxUtc}:00Z`)
        || start + duration_hours * 3_600_000 > Date.parse('2041-01-01T00:00:00Z')) {
        throw new Error('Use a whole UTC hour and keep the mission within 2026–2040.')
      }
      setError('')
      onRun(point, { ...settings, mission: { start_utc: `${rawStart}:00Z`, duration_hours, sample_step_seconds },
        constraints: { max_darkness_hours, max_earth_blackout_hours } })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Check the mission fields.')
    }
  }

  const durations = [...new Set([336, 720, 1440, mission.duration_hours])].sort((a, b) => a - b)
  const siteOption = sites.findIndex(item => sameSite(item, { latitude_deg: Number(latitude), longitude_deg_east: Number(longitude) }))
  return <form ref={form} onSubmit={submit} className="config-form">
    {sites.length > 0 && <label>Waypoint<select aria-label="Choose a waypoint" value={siteOption} onChange={event => {
      const selected = sites[Number(event.target.value)]
      if (!selected) { setLatitude(''); setLongitude(''); return }
      setLatitude(String(selected.latitude_deg))
      setLongitude(String(selected.longitude_deg_east))
    }}><option value={-1}>Custom coordinates</option>{sites.map((item, i) => <option value={i} key={i}>{item.name}</option>)}</select></label>}
    <div className="coordinates-input">
      <label>Latitude (°)<input name="latitude" type="number" step="any" min={-90} max={-80} required value={latitude} onChange={e => setLatitude(e.target.value)} /></label>
      <label>East longitude (°)<input name="longitude" type="number" step="any" min={-180} max={359.99999999999994} required value={longitude} onChange={e => setLongitude(e.target.value)} /></label>
    </div>
    <button className="text-button waypoint-action" type="button" onClick={() => {
      if (!form.current) return
      try { const point = readWaypoint(form.current, site); setError(''); onSelect(point) }
      catch (err) { setError(err instanceof Error ? err.message : 'Check the waypoint coordinates.') }
    }}>Select waypoint</button>
    <label>Mission start (UTC)<input type="datetime-local" name="start" min={minUtc} max={maxUtc} step={3600} required defaultValue={mission.start_utc.slice(0, 16)} /></label>
    <label>Duration<select name="duration" defaultValue={mission.duration_hours}>{durations.map(value => <option key={value} value={value}>
      {value % 24 === 0 ? `${value / 24} days` : `${value} hours`}</option>)}</select></label>
    <label>Sampling interval<select name="cadence" defaultValue={mission.sample_step_seconds}>{[...new Set([3600, 7200, 10800, 21600, mission.sample_step_seconds])].map(value => <option key={value} value={value}>
      {value === 3600 ? '1 hour' : `${value / 3600} hours`}</option>)}</select></label>
    <div className="form-divider" />
    <label>Maximum darkness tolerance (h)<input name="darkness" type="number" min={0} step="any" required defaultValue={constraints.max_darkness_hours} /></label>
    <label>Maximum Earth blackout tolerance (h)<input name="blackout" type="number" min={0} step="any" required defaultValue={constraints.max_earth_blackout_hours} /></label>
    {error && <p className="form-error" role="alert">{error}</p>}
    <button className="primary form-submit" disabled={busy}>{busy ? 'Analyzing…' : 'Run Analysis'}</button>
  </form>
}

export function VehicleFields({ vehicle, independentAntenna, onApply, busy, demo }: {
  vehicle: Vehicle; independentAntenna: boolean; onApply: (vehicle: Vehicle) => void; busy: boolean; demo: boolean;
}) {
  const [mast, setMast] = useState(String(vehicle.solar_panel_mast_height_m))
  const [antenna, setAntenna] = useState(String(vehicle.antenna_height_m))
  return <form className="config-form" onSubmit={event => {
    event.preventDefault()
    onApply({ solar_panel_mast_height_m: Number(mast), antenna_height_m: Number(antenna) })
  }}>
    <p className="muted">The solar mast height sets the observer position for the terrain horizon.</p>
    <div className="height-field"><label htmlFor="mast-height">Solar panel mast height (m)</label>
      <input id="mast-height" aria-label="Solar panel mast height in metres" type="number" min={0} max={maxMast} step="any" required value={mast} onChange={e => setMast(e.target.value)} />
      <input type="range" aria-label="Adjust solar panel mast height" min={0} max={maxMast} step={0.5} value={Number(mast)} onChange={e => setMast(e.target.value)} />
    </div>
    <label>Antenna height (m)<input type="number" min={0} max={maxMast} step="any" required disabled={!independentAntenna} value={antenna} onChange={e => setAntenna(e.target.value)} /></label>
    {!independentAntenna && <p className="muted field-note">Antenna height is fixed for this configuration.</p>}
    {demo && <p className="caution field-note">Demo snapshots are available at 2 m and 6 m.</p>}
    <button className="primary form-submit" disabled={busy}>{busy ? 'Analyzing…' : 'Apply vehicle configuration'}</button>
  </form>
}
