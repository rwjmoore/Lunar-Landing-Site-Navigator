import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { coordinates, normalizeLongitude, formatUtc, type Candidate, type Site, type Visibility } from './analysis'
import { Canvas } from './canvas'
import type { Sector } from './MapView'

const SUN = '#ffd166'
const EARTH = '#77beff'
const SKYLINE = '#c4ccd8'
type Profile = Candidate['horizons']
type Point = { x: number; y: number }
type Track = { name: string; color: string; azimuth: number[]; elevation: number[]; visibility: Visibility[] }
type Bounds = { left: number; right: number; top: number; bottom: number }

function trace(ctx: CanvasRenderingContext2D, points: Point[]) {
  ctx.beginPath()
  points.forEach(({ x, y }, i) => i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y))
}

function lunarProfile(ctx: CanvasRenderingContext2D, profile: Profile, field: keyof Profile, x: (angle: number) => number,
  y: (elevation: number) => number, bounds: Bounds, color: string, style: 'fill' | 'dash' | 'baseline') {
  const values = profile[field]
  if (values.length < 2) return
  let points: Point[] = []
  const gradient = ctx.createLinearGradient(0, bounds.top, 0, bounds.bottom)
  gradient.addColorStop(0, '#8c96a68a')
  gradient.addColorStop(1, '#8c96a612')
  ctx.lineWidth = style === 'fill' ? 1.9 : 1.3
  ctx.strokeStyle = color
  ctx.setLineDash(style === 'fill' ? [] : style === 'dash' ? [5, 5] : [3, 4])
  function drawSegment() {
    if (points.length < 2) return
    if (style === 'fill') {
      trace(ctx, points)
      ctx.lineTo(points[points.length - 1].x, bounds.bottom)
      ctx.lineTo(points[0].x, bounds.bottom)
      ctx.closePath()
      ctx.fillStyle = gradient
      ctx.fill()
    }
    trace(ctx, points)
    ctx.stroke()
  }
  for (const offset of [-360, 0, 360, 720]) {
    profile.azimuth_deg.forEach((az, i) => {
      const elevation = values[i]
      if (elevation !== null) points.push({ x: x(az + offset), y: y(elevation) })
      else { drawSegment(); points = [] }
    })
  }
  drawSegment()
  ctx.setLineDash([])
}

function shadeGaps(ctx: CanvasRenderingContext2D, profile: Profile, x: (angle: number) => number, bounds: Bounds) {
  const { azimuth_deg: azimuths, sun_observer_horizon_elevation_deg: sun, earth_observer_horizon_elevation_deg: earth } = profile
  if (azimuths.length < 2 || ![...sun, ...earth].some(value => value !== null)) return
  ctx.fillStyle = '#c8a45c16'
  ctx.strokeStyle = '#c8a45c39'
  ctx.lineWidth = 0.7
  for (const offset of [-360, 0, 360, 720]) {
    azimuths.forEach((angle, i) => {
      const next = (i + 1) % azimuths.length
      if (sun[i] !== null && sun[next] !== null && earth[i] !== null && earth[next] !== null) return
      const left = Math.max(bounds.left, x(angle + offset))
      const right = Math.min(bounds.right, x(azimuths[next] + offset + (next === 0 ? 360 : 0)))
      if (right <= left) return
      ctx.fillRect(left, bounds.top, right - left, bounds.bottom - bounds.top)
      ctx.beginPath()
      ctx.moveTo(left, bounds.top)
      ctx.lineTo(left, bounds.bottom)
      ctx.stroke()
    })
  }
}

function visibilityStyle(state: Visibility | undefined) {
  return state === true ? [] : state === false ? [5, 4] : [1, 5]
}

function paintTrack(ctx: CanvasRenderingContext2D, track: Track, t: number, sector: Sector,
  x: (angle: number) => number, y: (elevation: number) => number) {
  ctx.strokeStyle = track.color
  ctx.lineWidth = 1.65
  for (const offset of [-360, 0, 360, 720]) {
    let pen: number | undefined
    let previous: Visibility | undefined
    for (let i = 1; i < track.azimuth.length; i++) {
      const from = track.azimuth[i - 1] + offset
      const to = from + normalizeLongitude(track.azimuth[i] + offset - from + 180) - 180
      if (Math.max(from, to) < sector.start || Math.min(from, to) > sector.start + sector.width) {
        if (pen !== undefined) ctx.stroke()
        pen = undefined
        continue
      }
      const state = track.visibility[i - 1]
      if (pen === undefined || Math.abs(from - pen) > 0.001 || state !== previous) {
        if (pen !== undefined) ctx.stroke()
        ctx.setLineDash(visibilityStyle(state))
        ctx.beginPath()
        ctx.moveTo(x(from), y(track.elevation[i - 1]))
      }
      ctx.lineTo(x(to), y(track.elevation[i]))
      pen = to
      previous = state
    }
    if (pen !== undefined) ctx.stroke()
  }
  ctx.setLineDash([])
  if (track.azimuth[t] === undefined) return
  const angle = sector.start + normalizeLongitude(track.azimuth[t] - sector.start)
  if (angle > sector.start + sector.width) return
  const cx = x(angle)
  const cy = y(track.elevation[t])
  ctx.fillStyle = track.color
  ctx.beginPath()
  ctx.arc(cx, cy, 5.7, 0, Math.PI * 2)
  const state = track.visibility[t]
  if (state === true) {
    ctx.shadowBlur = 13
    ctx.shadowColor = track.color
    ctx.fill()
    ctx.shadowBlur = 0
  } else {
    ctx.fillStyle = '#141518'
    ctx.fill()
  }
  ctx.strokeStyle = state === true ? '#f7f7f8' : track.color
  ctx.lineWidth = 1.5
  ctx.setLineDash(state === null ? [2, 2] : [])
  ctx.stroke()
  ctx.setLineDash([])
}

function elevationAxis(values: number[]) {
  let low = values.length ? -4 : -15
  let high = values.length ? 4 : 20
  for (const value of values) {
    low = Math.min(low, value - 0.4)
    high = Math.max(high, value + 0.4)
  }
  const step = [1, 2, 5, 10, 15, 20, 30, 45].find(value => value >= (high - low) / 7) ?? 45
  return { low: Math.floor(low / step) * step, high: Math.ceil(high / step) * step, step }
}

function grid(ctx: CanvasRenderingContext2D, bounds: Bounds, axis: ReturnType<typeof elevationAxis>) {
  const { left, right, top, bottom } = bounds
  const y = (elevation: number) => bottom - (elevation - axis.low) / (axis.high - axis.low) * (bottom - top)
  ctx.font = '11px Inter, system-ui'
  ctx.textAlign = 'right'
  ctx.fillStyle = '#babdc7'
  for (let el = axis.low; el <= axis.high; el += axis.step) {
    const height = y(el)
    ctx.lineWidth = 1
    ctx.strokeStyle = el === 0 ? '#484b53' : '#262830'
    trace(ctx, [{ x: left, y: height }, { x: right, y: height }])
    ctx.stroke()
    ctx.fillText(`${el}°`, left - 7, height + 4)
  }
  return y
}

function Chart({ candidate, baseline, tracks, sector, index }: {
  candidate: Candidate | undefined; baseline: Candidate | undefined; tracks: Track[]; sector: Sector; index: number
}) {
  const profile = candidate?.horizons
  const sunProfile = profile?.sun_observer_horizon_elevation_deg ?? []
  const earthProfile = profile?.earth_observer_horizon_elevation_deg ?? []
  const isKnown = (value: number | null): value is number => value !== null
  const sunAvailable = sunProfile.filter(isKnown).length >= 2
  const earthAvailable = earthProfile.filter(isKnown).length >= 2
  const hasGaps = (sunAvailable || earthAvailable) && (sunProfile.includes(null) || earthProfile.includes(null))
  const showEarth = earthAvailable && (!sunAvailable || earthProfile.some((value, i) => value !== sunProfile[i]))
  const baselineProfile = baseline?.horizons.sun_observer_horizon_elevation_deg
  const draw = useCallback((ctx: CanvasRenderingContext2D, w: number, h: number) => {
    const bounds = { left: w < 450 ? 41 : 52, right: w - 19, top: 20, bottom: h - 50 }
    const { left, right, top, bottom } = bounds
    const x = (angle: number) => left + (angle - sector.start) / sector.width * (right - left)
    const elevations = [...sunProfile, ...earthProfile, ...(baselineProfile ?? []), ...tracks.flatMap(track => track.elevation)].filter(isKnown)
    const y = grid(ctx, bounds, elevationAxis(elevations))
    ctx.textAlign = 'center'
    const divisions = w < 410 ? 3 : 6
    for (let i = 0; i <= divisions; i++) {
      const angle = sector.start + i / divisions * sector.width
      const px = x(angle)
      trace(ctx, [{ x: px, y: top }, { x: px, y: bottom }])
      ctx.strokeStyle = '#272931'
      ctx.stroke()
      const label = sector.start === 0 && sector.width === 360 && i === divisions ? 360 : normalizeLongitude(Number(angle.toFixed(1)))
      ctx.fillText(`${label}°`, px, bottom + 17)
    }
    ctx.fillText(w < 435 ? 'Azimuth from local north (°)' : 'Azimuth clockwise from local north (°)', (left + right) / 2, h - 11)
    ctx.save()
    ctx.translate(13, (top + bottom) / 2)
    ctx.rotate(-Math.PI / 2)
    ctx.fillText('Elevation (°)', 0, 0)
    ctx.restore()

    ctx.save()
    ctx.beginPath()
    ctx.rect(left, top, right - left, bottom - top)
    ctx.clip()
    if (profile) {
      shadeGaps(ctx, profile, x, bounds)
      if (sunAvailable) lunarProfile(ctx, profile, 'sun_observer_horizon_elevation_deg', x, y, bounds, SKYLINE, 'fill')
      if (showEarth) lunarProfile(ctx, profile, 'earth_observer_horizon_elevation_deg', x, y, bounds, '#93adb9', 'dash')
    }
    if (baseline) lunarProfile(ctx, baseline.horizons, 'sun_observer_horizon_elevation_deg', x, y, bounds, '#d2a1ed', 'baseline')
    tracks.forEach(track => paintTrack(ctx, track, index, sector, x, y))
    ctx.restore()
  }, [baseline, baselineProfile, earthProfile, index, profile, sector, showEarth, sunAvailable, sunProfile, tracks])

  const noData = !sunAvailable && !earthAvailable && !tracks.some(track => track.elevation.length)
  return <>
    <div className="plot">
      <Canvas paint={draw} role="img" aria-label="Local terrain and Sun and Earth tracks by azimuth and elevation in degrees" />
      {noData && <div className="plot-empty">
        <span className="empty-symbol" aria-hidden="true">⌁</span>
        <strong>Terrain data missing</strong>
        <span>No verified analysis loaded for this waypoint. Sun and Earth visibility are unknown.</span>
      </div>}
    </div>
    <div className="plot-key">
      <span><i style={{ backgroundColor: SUN }} /> Sun</span><span><i style={{ backgroundColor: EARTH }} /> Earth</span>
      <span><i className="legend-line" /> Solar mast horizon</span>
      {showEarth && <span><i className="legend-line antenna" /> Antenna horizon</span>}
      {baseline && <span><i className="legend-line baseline" /> Baseline mast</span>}
      {hasGaps && <span className="caution"><i className="legend-gap" /> Missing terrain</span>}
      {(!sunAvailable || !earthAvailable) && !noData && <span className="caution">{!sunAvailable && !earthAvailable ? 'Terrain data missing' : !sunAvailable ? 'Solar mast terrain missing' : 'Antenna terrain missing'}</span>}
      {tracks.some(track => track.azimuth.length > 1) && <span className="trace-key">Solid visible · dashed obstructed · dotted unknown</span>}
    </div>
  </>
}

function labelVisibility(state: Visibility | undefined) {
  if (state === true) return 'Visible'
  if (state === false) return 'Obstructed'
  return 'Unknown'
}

function ElevationChart({ tracks, times, index, onSeek }: { tracks: Track[]; times: string[]; index: number; onSeek: (index: number) => void }) {
  const millis = useMemo(() => times.map(value => Date.parse(value)), [times])
  const timeRatio = useCallback((i: number) => (millis[i] - millis[0]) / (millis[millis.length - 1] - millis[0] || 1), [millis])
  const chart = useCallback((ctx: CanvasRenderingContext2D, w: number, h: number) => {
    const bounds = { left: 44, right: w - 16, top: 13, bottom: h - 64 }
    const y = grid(ctx, bounds, elevationAxis(tracks.flatMap(track => track.elevation)))
    const x = (i: number) => bounds.left + timeRatio(i) * (bounds.right - bounds.left)
    if (!times.length) return
    tracks.forEach(track => {
      trace(ctx, track.elevation.map((el, i) => ({ x: x(i), y: y(el) })))
      ctx.lineWidth = 1.5
      ctx.strokeStyle = track.color
      ctx.stroke()
    })
    tracks.forEach((track, row) => {
      const top = bounds.bottom + 12 + row * 15
      ctx.fillStyle = track.color
      ctx.textAlign = 'right'
      ctx.fillText(track.name, bounds.left - 6, top + 8)
      track.visibility.slice(0, -1).forEach((state, i) => {
        ctx.fillStyle = state === true ? track.color : state === false ? '#4f5663' : '#84643f'
        ctx.fillRect(x(i), top, x(i + 1) - x(i) + 0.4, 8)
      })
    })
    const current = x(index)
    trace(ctx, [{ x: current, y: bounds.top }, { x: current, y: bounds.bottom + 36 }])
    ctx.lineWidth = 1.2
    ctx.strokeStyle = '#e5ecf8'
    ctx.stroke()
    ctx.fillStyle = '#babdc7'
    ctx.textAlign = 'left'
    ctx.fillText(times[0].slice(5, 10), bounds.left, h - 7)
    ctx.textAlign = 'center'
    ctx.fillText('Mission time (UTC)', (bounds.left + bounds.right) / 2, h - 7)
    ctx.textAlign = 'right'
    ctx.fillText(times[times.length - 1].slice(5, 10), bounds.right, h - 7)
  }, [tracks, times, index, timeRatio])

  return <section className="elevation-panel" aria-label="Sun and Earth elevation over time">
    <h3>Sun &amp; Earth elevation</h3>
    {times.length > 0 ? <><Canvas paint={chart} role="img" aria-label="Sun and Earth elevations and visibility intervals by mission time. Use the mission time slider to choose a sample."
      onClick={event => {
        const rect = event.currentTarget.getBoundingClientRect()
        const ratio = Math.max(0, Math.min(1, (event.clientX - rect.left - 44) / (rect.width - 60)))
        let nearest = 0
        millis.forEach((_, i) => { if (Math.abs(ratio - timeRatio(i)) < Math.abs(ratio - timeRatio(nearest))) nearest = i })
        onSeek(nearest)
      }} /><div className="interval-key"><span>Visibility intervals</span><span><i className="visible" /> Visible</span>
        <span><i /> Obstructed</span><span><i className="unknown" /> Unknown</span></div></> : <p className="muted">No time series available.</p>}
  </section>
}

const emptyTimes: string[] = []

export function HorizonView({ site, candidate, baseline, index, onSeek, sector, full, onFull, onSector,
  onSectorLimits, onLoad, message }: {
  site: Site; candidate: Candidate | undefined; baseline: Candidate | undefined; index: number; onSeek: (sample: number) => void;
  sector: Sector; full: boolean; onFull: () => void; onSector: () => void; onSectorLimits: (limits: Sector) => void;
  onLoad: (file: File) => void; message: string;
}) {
  const fileInput = useRef<HTMLInputElement>(null)
  const [playing, setPlaying] = useState(false)
  const times = candidate?.series.timestamps_utc ?? emptyTimes
  const current = Math.max(0, Math.min(index, times.length - 1))
  const tracks = useMemo(() => {
    if (!candidate) return []
    const s = candidate.series
    return [
      { name: 'Sun', color: SUN, azimuth: s.sun_azimuth_deg, elevation: s.sun_elevation_deg, visibility: s.sun_visible },
      { name: 'Earth', color: EARTH, azimuth: s.earth_azimuth_deg, elevation: s.earth_elevation_deg, visibility: s.earth_visible },
    ]
  }, [candidate])
  const view = useMemo(() => full ? { start: 0, width: 360 } : sector, [full, sector])
  const firstSample = times[0] ? Date.parse(times[0]) : 0
  const hours = times[current] ? (Date.parse(times[current]) - firstSample) / 3_600_000 : 0
  const lastHours = times.length ? (Date.parse(times[times.length - 1]) - firstSample) / 3_600_000 : 0

  useEffect(() => {
    if (!playing || current >= times.length - 1) return
    const timer = window.setTimeout(() => onSeek(current + 1), 115)
    return () => window.clearTimeout(timer)
  }, [playing, current, times.length, onSeek])
  const active = playing && current < times.length - 1

  function seek(sample: number) {
    setPlaying(false)
    onSeek(sample)
  }

  return <div className="horizon-content">
    <div className="horizon-toolbar">
      <div className="button-row"><button className={full ? 'primary' : ''} aria-pressed={full} onClick={onFull}>Full 360°</button>
        <button className={!full ? 'primary' : ''} aria-pressed={!full} onClick={onSector}>View sector</button>
        <span className="sector-reading">{full ? '0° → 360°' : `${sector.start}° → ${normalizeLongitude(sector.start + sector.width)}°`}</span></div>
      <div className="selected-site horizon-site" aria-label="Analysed waypoint"><strong>{site.name}</strong><span>{coordinates(site)}</span></div>
      <div className="sector-inputs">
        <label>Sector start <input type="number" min={0} max={359} value={sector.start}
          onChange={e => onSectorLimits({ ...sector, start: Math.max(0, Math.min(359, Math.round(Number(e.target.value)))) })} /></label>
        <label>Sector width <input type="number" min={1} max={360} value={sector.width}
          onChange={e => onSectorLimits({ ...sector, width: Math.max(1, Math.min(360, Math.round(Number(e.target.value)))) })} /></label>
      </div>
    </div>
    <Chart candidate={candidate} baseline={baseline} tracks={tracks} sector={view} index={current} />
    <div className="timeline">
      <div className="timeline-top">
        <div className="button-row"><button aria-label={active ? 'Pause playback' : 'Play mission'} disabled={times.length < 2}
          onClick={() => { if (!active && current >= times.length - 1) onSeek(0); setPlaying(!active) }}>{active ? 'Ⅱ Pause' : '▶ Play'}</button>
          <button aria-label="Previous sample" disabled={current <= 0} onClick={() => seek(current - 1)}>◀</button>
          <button aria-label="Next sample" disabled={current >= times.length - 1} onClick={() => seek(current + 1)}>▶</button></div>
        {times[current] ? <time dateTime={times[current]}>{formatUtc(times[current])}</time> : <strong>No UTC samples loaded</strong>}
        {times.length > 0 && <span className="mission-day">Day {(hours / 24).toFixed(1)} / {(lastHours / 24).toFixed(1)}</span>}
      </div>
      <input type="range" aria-label="Mission time" min={0} max={Math.max(0, times.length - 1)} disabled={times.length < 2}
        value={current} aria-valuetext={times[current] && formatUtc(times[current])} onChange={e => seek(Number(e.target.value))} />
      <div className="body-readouts">
        {[{ name: 'Sun', color: SUN }, { name: 'Earth', color: EARTH }].map(({ name, color }, i) => {
          const track = tracks[i]
          const state = track?.visibility[current]
          return <div key={name}><strong style={{ color }}>{name}</strong><span className={`los-state ${state == null ? 'caution' : ''}`}>{labelVisibility(state)}</span>
            {track?.azimuth[current] !== undefined && <span className="body-angle">{track.azimuth[current].toFixed(1)}° az · {track.elevation[current].toFixed(1)}° el</span>}</div>
        })}
      </div>
    </div>
    <ElevationChart tracks={tracks} times={times} index={current} onSeek={seek} />
    <div className="analysis-footer"><p role="status">{message}</p>
      <input ref={fileInput} type="file" accept=".json,application/json" hidden onChange={event => {
        const file = event.target.files?.[0]
        if (file) onLoad(file)
        event.currentTarget.value = ''
      }} /><button onClick={() => fileInput.current?.click()}>Load analysis JSON</button></div>
  </div>
}
