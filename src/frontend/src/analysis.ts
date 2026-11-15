export interface Site {
  name: string
  latitude_deg: number
  longitude_deg_east: number
}

export interface Mission {
  start_utc: string
  duration_hours: number
  sample_step_seconds: number
}

export interface Vehicle {
  solar_panel_mast_height_m: number
  antenna_height_m: number
}

export interface Constraints {
  max_darkness_hours: number
  max_earth_blackout_hours: number
}

export interface Settings {
  mission: Mission
  vehicle: Vehicle
  constraints: Constraints
}

export type AnalysisRequest = Settings & { site: Site }
export type Visibility = boolean | null
export type Feasibility = 'feasible' | 'infeasible' | 'unknown' | 'unavailable'

export interface Metrics {
  sun_visible_fraction: number | null
  max_continuous_darkness_hours: number | null
  earth_visible_fraction: number | null
  max_continuous_earth_blackout_hours: number | null
}

export interface Candidate {
  name: string
  location: Omit<Site, 'name'> & { surface_elevation_m: number | null }
  vehicle: Vehicle
  metrics: Metrics
  feasibility: { status: Feasibility; failed_constraints: string[]; margins: Record<string, number> }
  horizons: {
    azimuth_deg: number[]
    sun_observer_horizon_elevation_deg: (number | null)[]
    earth_observer_horizon_elevation_deg: (number | null)[]
  }
  series: {
    timestamps_utc: string[]
    sun_azimuth_deg: number[]
    sun_elevation_deg: number[]
    sun_visible: Visibility[]
    earth_azimuth_deg: number[]
    earth_elevation_deg: number[]
    earth_visible: Visibility[]
  }
  diagnostics: string[]
  provenance: { dem_id: string | null; ephemeris_id: string | null; sample_step_seconds: number }
}

export const initialSite: Site = { name: 'South Pole waypoint', latitude_deg: -89.92, longitude_deg_east: 23.45 }

export const defaultSettings: Settings = {
  mission: { start_utc: '2030-11-20T12:00:00Z', duration_hours: 336, sample_step_seconds: 3600 },
  vehicle: { solar_panel_mast_height_m: 2, antenna_height_m: 2 },
  constraints: { max_darkness_hours: 24, max_earth_blackout_hours: 12 },
}

export const metricLabels = {
  sun_visible_fraction: 'Solar access',
  earth_visible_fraction: 'Earth visibility',
  max_continuous_darkness_hours: 'Max darkness',
  max_continuous_earth_blackout_hours: 'Max Earth blackout',
} satisfies Record<keyof Metrics, string>

export function normalizeLongitude(degrees: number) {
  return ((degrees % 360) + 360) % 360
}

export function sameSite(a: Omit<Site, 'name'>, b: Omit<Site, 'name'>) {
  const delta = normalizeLongitude(a.longitude_deg_east - b.longitude_deg_east + 180) - 180
  return Math.abs(a.latitude_deg - b.latitude_deg) < 1e-6 && Math.abs(delta) < 1e-6
}

export function coordinates(site: Omit<Site, 'name'>) {
  const lat = `${Math.abs(site.latitude_deg).toFixed(4)}°${site.latitude_deg < 0 ? 'S' : 'N'}`
  const lon = normalizeLongitude(Number(site.longitude_deg_east.toFixed(4))).toFixed(4)
  return `${lat} · ${lon}°E`
}

export function candidateSite(candidate: Candidate): Site {
  return { name: candidate.name, latitude_deg: candidate.location.latitude_deg, longitude_deg_east: candidate.location.longitude_deg_east }
}

export function settingsKey({ mission, constraints, vehicle }: Settings) {
  return JSON.stringify([
    mission.start_utc, mission.duration_hours, mission.sample_step_seconds,
    constraints.max_darkness_hours, constraints.max_earth_blackout_hours,
    vehicle.solar_panel_mast_height_m, vehicle.antenna_height_m,
  ])
}

export function analysisKey(site: Site, settings: Settings) {
  return `${site.latitude_deg.toFixed(6)},${normalizeLongitude(Number(site.longitude_deg_east.toFixed(6))).toFixed(6)}:${settingsKey(settings)}`
}

export function formatMetric(key: keyof Metrics, value: number | null | undefined) {
  if (value == null) return '—'
  return key.endsWith('_fraction') ? `${(value * 100).toFixed(1)}%` : `${value.toFixed(1)} h`
}

export function formatUtc(utc: string) {
  return `${utc.slice(0, 10)} ${utc.slice(11, 16)} UTC`
}

const isNumber = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value)
const inRange = (value: unknown, min: number, max: number) => isNumber(value) && value >= min && value <= max
const isString = (value: unknown): value is string => typeof value === 'string'
const isBoolean = (value: unknown): value is boolean => typeof value === 'boolean'
const isVisibility = (value: unknown): value is Visibility => value === null || isBoolean(value)
const isAzimuth = (value: unknown): value is number => isNumber(value) && value >= 0 && value < 360
const isElevation = (value: unknown): value is number => inRange(value, -90, 90)
const isUtc = (value: unknown): value is string => isString(value)
  && /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?Z$/.test(value) && Number.isFinite(Date.parse(value))
  && new Date(value).toISOString().slice(0, 19) === value.slice(0, 19)

function requireField(condition: unknown, field: string): asserts condition {
  if (!condition) throw new Error(`Invalid analysis data for ${field}.`)
}

function object(value: unknown, field: string): Record<string, unknown> {
  requireField(typeof value === 'object' && value !== null && !Array.isArray(value), field)
  return value as Record<string, unknown>
}

function array<T>(value: unknown, predicate: (item: unknown) => item is T, field: string, length?: number): T[] {
  requireField(Array.isArray(value) && (length === undefined || value.length === length) && value.every(predicate), field)
  return value
}

function readSite(value: unknown): Site {
  const site = object(value, 'site')
  const { name, latitude_deg, longitude_deg_east } = site
  requireField(isString(name) && name.trim() && isNumber(latitude_deg) && isNumber(longitude_deg_east)
    && inRange(latitude_deg, -90, 90) && longitude_deg_east >= -180 && longitude_deg_east < 360, 'site coordinates')
  return { name, latitude_deg, longitude_deg_east }
}

function readHorizon(profile: Record<string, unknown>, azimuth: number[], body: 'sun' | 'earth') {
  const field = `${body}_observer_horizon_elevation_deg`
  const heights = array(profile[field], (value): value is number | null => value === null || isElevation(value), field, azimuth.length)
  const maskField = `${body}_observer_no_data`
  const mask = profile[maskField] === undefined ? undefined : array(profile[maskField], isBoolean, maskField, azimuth.length)
  return heights.map((value, i) => mask?.[i] ? null : value)
}

function hasTerrainAt(azimuths: number[], heights: (number | null)[], degrees: number) {
  if (azimuths.length < 2) return false
  let lo = 0
  let hi = azimuths.length
  while (lo < hi) {
    const mid = (lo + hi) >>> 1
    if (azimuths[mid] <= degrees) lo = mid + 1
    else hi = mid
  }
  const left = (lo + azimuths.length - 1) % azimuths.length
  return heights[left] !== null && heights[lo % azimuths.length] !== null
}

export function readAnalysis(value: unknown): Candidate {
  const response = object(value, 'response')
  const candidate = object(response.candidate, 'candidate')
  const location = object(candidate.location, 'location')
  const site = readSite({ ...location, name: candidate.name })
  const { surface_elevation_m } = location
  requireField(surface_elevation_m === null || isNumber(surface_elevation_m), 'surface elevation')

  const { solar_panel_mast_height_m, antenna_height_m } = object(candidate.vehicle, 'vehicle')
  requireField(isNumber(solar_panel_mast_height_m) && solar_panel_mast_height_m >= 0
    && isNumber(antenna_height_m) && antenna_height_m >= 0, 'observer heights')

  const rawMetrics = object(candidate.metrics, 'metrics')
  const metrics = {} as Metrics
  for (const key of Object.keys(metricLabels) as (keyof Metrics)[]) {
    const metric = rawMetrics[key]
    requireField(metric === null || (isNumber(metric) && metric >= 0 && (!key.endsWith('_fraction') || metric <= 1)), metricLabels[key])
    metrics[key] = metric
  }

  const profile = object(candidate.horizons, 'horizons')
  const azimuth_deg = array(profile.azimuth_deg, isAzimuth, 'horizon azimuths')
  requireField(azimuth_deg.every((value, i) => !i || value > azimuth_deg[i - 1]), 'ordered horizon azimuths')
  const sunHorizon = readHorizon(profile, azimuth_deg, 'sun')
  const earthHorizon = readHorizon(profile, azimuth_deg, 'earth')
  const series = object(candidate.series, 'time series')
  const timestamps_utc = array(series.timestamps_utc, isUtc, 'UTC timestamps')
  requireField(timestamps_utc.every((time, i) => !i || Date.parse(time) > Date.parse(timestamps_utc[i - 1])), 'ordered UTC timestamps')
  const n = timestamps_utc.length
  const sun_azimuth_deg = array(series.sun_azimuth_deg, isAzimuth, 'Sun azimuths', n)
  const earth_azimuth_deg = array(series.earth_azimuth_deg, isAzimuth, 'Earth azimuths', n)
  const sun_elevation_deg = array(series.sun_elevation_deg, isElevation, 'Sun elevations', n)
  const earth_elevation_deg = array(series.earth_elevation_deg, isElevation, 'Earth elevations', n)
  const sun_visible = array(series.sun_visible, isVisibility, 'Sun visibility', n)
    .map((state, i) => hasTerrainAt(azimuth_deg, sunHorizon, sun_azimuth_deg[i]) ? state : null)
  const earth_visible = array(series.earth_visible, isVisibility, 'Earth visibility', n)
    .map((state, i) => hasTerrainAt(azimuth_deg, earthHorizon, earth_azimuth_deg[i]) ? state : null)

  const sunKnown = sun_visible.some(state => state !== null)
  const earthKnown = earth_visible.some(state => state !== null)
  if (!sunKnown) {
    metrics.sun_visible_fraction = null
    metrics.max_continuous_darkness_hours = null
  }
  if (!earthKnown) {
    metrics.earth_visible_fraction = null
    metrics.max_continuous_earth_blackout_hours = null
  }

  const assessment = object(candidate.feasibility, 'feasibility')
  const { status: receivedStatus } = assessment
  requireField(receivedStatus === 'feasible' || receivedStatus === 'infeasible' || receivedStatus === 'unknown' || receivedStatus === 'unavailable', 'feasibility status')
  const lostAssessment = receivedStatus !== 'unavailable' && !sunKnown && !earthKnown
  const incomplete = receivedStatus === 'feasible' && (sun_visible.includes(null) || earth_visible.includes(null))
  const status: Feasibility = lostAssessment || incomplete ? 'unknown' : receivedStatus
  const failures = array(assessment.failed_constraints, isString, 'failed constraints')
  const rawMargins = object(assessment.margins, 'constraint margins')
  const margins: Record<string, number> = Object.fromEntries(Object.entries(rawMargins).map(([key, value]) => {
    requireField(isNumber(value), 'constraint margins')
    return [key, value]
  }))
  const { dem_id, ephemeris_id, sample_step_seconds } = object(candidate.provenance, 'provenance')
  requireField((dem_id === null || isString(dem_id)) && (ephemeris_id === null || isString(ephemeris_id))
    && isNumber(sample_step_seconds) && Number.isInteger(sample_step_seconds) && sample_step_seconds > 0, 'data sources or cadence')
  return {
    name: site.name,
    location: { latitude_deg: site.latitude_deg, longitude_deg_east: site.longitude_deg_east, surface_elevation_m },
    vehicle: { solar_panel_mast_height_m, antenna_height_m },
    metrics,
    feasibility: { status, failed_constraints: lostAssessment ? [] : failures, margins: lostAssessment ? {} : margins },
    horizons: { azimuth_deg, sun_observer_horizon_elevation_deg: sunHorizon, earth_observer_horizon_elevation_deg: earthHorizon },
    series: { timestamps_utc, sun_azimuth_deg, sun_elevation_deg, sun_visible, earth_azimuth_deg, earth_elevation_deg, earth_visible },
    diagnostics: array(candidate.diagnostics, isString, 'diagnostics'),
    provenance: { dem_id, ephemeris_id, sample_step_seconds },
  }
}

export interface SiteCatalog {
  sites: Site[]
  /** The backend's published distance within which requested coordinates match a site. */
  toleranceM: number
}

function readSiteList(value: unknown): Site[] {
  const result = array(value, (item): item is unknown => true, 'site list').map(readSite)
  if (result.some((site, i) => site.latitude_deg < -89.999 || site.latitude_deg > -80
    || result.slice(0, i).some(other => sameSite(site, other)))) {
    throw new Error('The service listed sites outside 89.999°S to 80°S, or duplicate sites.')
  }
  return result
}

/** Reads the body of GET /sites (docs/API.md). Extra fields are ignored. */
export function readSiteCatalog(value: unknown): SiteCatalog {
  const body = object(value, 'site catalog')
  requireField(isNumber(body.site_match_tolerance_m) && body.site_match_tolerance_m > 0, 'site match tolerance')
  return { sites: readSiteList(body.sites), toleranceM: body.site_match_tolerance_m }
}

/** Surface distance between two locations on the 1737.4 km reference sphere, in metres. */
export function surfaceDistanceM(a: Omit<Site, 'name'>, b: Omit<Site, 'name'>) {
  const rad = Math.PI / 180
  const h = Math.sin((a.latitude_deg - b.latitude_deg) * rad / 2) ** 2
    + Math.cos(a.latitude_deg * rad) * Math.cos(b.latitude_deg * rad)
    * Math.sin((a.longitude_deg_east - b.longitude_deg_east) * rad / 2) ** 2
  return 2 * 1_737_400 * Math.asin(Math.min(1, Math.sqrt(h)))
}

/** Turns an error reply into a readable message, using the API's own explanation when it gives one. */
async function replyError(reply: Response, action: string) {
  let body: unknown
  try { body = await reply.json() } catch { body = undefined }
  const fields = typeof body === 'object' && body !== null ? body as Record<string, unknown> : {}
  if (isString(fields.message) && fields.message.trim()) {
    const text = fields.message.trim().replace(/\.$/, '')
    return new Error(fields.error === 'site_unavailable'
      ? `This waypoint is not a supported site: ${text}.`
      : `${text.charAt(0).toUpperCase()}${text.slice(1)}.`)
  }
  if (Array.isArray(fields.detail)) {  // FastAPI request validation (422)
    const problems = fields.detail.flatMap(item => typeof item === 'object' && item !== null
      && isString((item as Record<string, unknown>).msg) ? [(item as Record<string, string>).msg] : [])
    if (problems.length) return new Error(`The service rejected the ${action}: ${problems.join('; ')}.`)
  }
  return new Error(`The ${action} failed (${reply.status}). Try again.`)
}

async function send(url: string, init: RequestInit, action: string) {
  try {
    return await fetch(url, init)
  } catch (error) {
    if (init.signal?.aborted) throw error
    throw new Error(`The analysis service could not be reached for the ${action}. Check that it is running.`)
  }
}

export async function requestSites(base: string, signal: AbortSignal): Promise<SiteCatalog> {
  const reply = await send(`${base.replace(/\/+$/, '')}/sites`, { signal }, 'site list')
  if (!reply.ok) throw await replyError(reply, 'site list request')
  return readSiteCatalog(await reply.json())
}

export async function requestAnalysis(base: string, request: AnalysisRequest, signal: AbortSignal, toleranceM: number) {
  const reply = await send(`${base.replace(/\/+$/, '')}/analyze`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(request), signal,
  }, 'analysis')
  if (!reply.ok) throw await replyError(reply, 'analysis request')
  const candidate = readAnalysis(await reply.json())
  const { mission, vehicle } = request
  const times = candidate.series.timestamps_utc
  const expectedCount = Math.floor(mission.duration_hours * 3600 / mission.sample_step_seconds) + 1
  const start = Date.parse(mission.start_utc)
  // The backend answers with its supported site's exact coordinates, matched within its published tolerance.
  if (surfaceDistanceM(candidate.location, request.site) > toleranceM
    || candidate.vehicle.solar_panel_mast_height_m !== vehicle.solar_panel_mast_height_m
    || candidate.vehicle.antenna_height_m !== vehicle.antenna_height_m
    || candidate.provenance.sample_step_seconds !== mission.sample_step_seconds
    || (times.length && (times.length !== expectedCount || times.some((time, i) => Date.parse(time) !== start + i * mission.sample_step_seconds * 1000)))) {
    throw new Error('The analysis response did not match the requested waypoint, mission window, or vehicle.')
  }
  return candidate
}
