// Client for the planning endpoints (POST /calendar, /insights, /rescue; docs/API.md "Planning endpoints").
// These are separate from the v1 /analyze contract. Definitions: docs/physics/planning.md.
import { postJson, type AnalysisRequest, type Settings, type Site } from './analysis'

export type PlanStatus = 'feasible' | 'infeasible' | 'unknown'

export interface CalendarResult {
  starts_utc: string[]
  sun_visible_fraction: (number | null)[]
  max_darkness_hours: (number | null)[]
  earth_visible_fraction: (number | null)[]
  max_earth_blackout_hours: (number | null)[]
  status: PlanStatus[]
  worst_margin_hours: (number | null)[]
  feasible_count: number
  best_start_utc: string | null
  best_worst_margin_hours: number | null
}

export interface Blocker {
  sector_from_deg: number; sector_to_deg: number; hours: number; azimuth_deg: number
  distance_m: number; latitude_deg: number; longitude_deg_east: number; zone: 'near' | 'far'
}

export interface Outage {
  body: 'sun' | 'earth'; start_utc: string; end_utc: string; duration_hours: number; boundary_truncated: boolean
  azimuth_from_deg: number; azimuth_to_deg: number; max_deficit_deg: number
  near_share: number; below_limb_share: number; dominant: Blocker; text: string
}

export interface Insights {
  summary: string[]
  events: { time_utc: string; body: 'sun' | 'earth'; event: 'rise' | 'set' }[]
  timestamps_utc: string[]
  sun_hours_to_change: (number | null)[]
  earth_hours_to_change: (number | null)[]
  joint_visible_fraction: number | null
  longest_joint_window_hours: number | null
  longest_joint_window_start_utc: string | null
  longest_joint_window_end_utc: string | null
  outages: Outage[]
}

export interface Outcome {
  sun_visible_fraction: number | null; max_darkness_hours: number | null
  earth_visible_fraction: number | null; max_earth_blackout_hours: number | null; status: PlanStatus
}

export type OptionKind = 'mast' | 'antenna' | 'date_earlier' | 'date_later' | 'move_nearest' | 'move_best'

export interface RescueOption {
  kind: OptionKind
  fixes: boolean
  change: Record<string, number | string | null>
  outcome: Outcome
  text: string
}

export interface Rescue { baseline: Outcome; options: RescueOption[]; notes: string[]; computation_ms: number }

function check<T>(value: unknown, fields: string[], what: string): T {
  if (typeof value !== 'object' || value === null || fields.some(field => !(field in value))) {
    throw new Error(`The ${what} response was not in the expected format.`)
  }
  return value as T
}

const body = (request: AnalysisRequest) => ({
  site: { name: request.site.name, latitude_deg: request.site.latitude_deg, longitude_deg_east: request.site.longitude_deg_east },
  mission: request.mission, vehicle: request.vehicle, constraints: request.constraints,
})

export async function requestInsights(base: string, request: AnalysisRequest, signal: AbortSignal) {
  return check<Insights>(await postJson(base, '/insights', body(request), signal, 'explanation'),
    ['summary', 'events', 'outages', 'sun_hours_to_change'], 'explanation')
}

export async function requestRescue(base: string, request: AnalysisRequest, signal: AbortSignal) {
  return check<Rescue>(await postJson(base, '/rescue', body(request), signal, 'mission rescue'),
    ['baseline', 'options', 'notes'], 'mission rescue')
}

export async function requestCalendar(base: string, site: Site, settings: Settings, from: string, to: string, signal: AbortSignal) {
  const request = {
    site: { name: site.name, latitude_deg: site.latitude_deg, longitude_deg_east: site.longitude_deg_east },
    vehicle: settings.vehicle, constraints: settings.constraints,
    duration_hours: settings.mission.duration_hours, start_step_hours: 24, start_from_utc: from, start_to_utc: to,
  }
  return check<CalendarResult>(await postJson(base, '/calendar', request, signal, 'start-date calendar'),
    ['starts_utc', 'status', 'worst_margin_hours', 'feasible_count'], 'start-date calendar')
}

const hour = 3_600_000
const utc = (ms: number) => new Date(ms).toISOString().slice(0, 19) + 'Z'

/** Daily candidate starts in one calendar year, at the mission's time of day, clipped to the starts that fit. */
export function yearRange(year: number, missionStart: string, durationHours: number, supportedEndUtc: string | null) {
  const timeOfDay = missionStart.slice(11, 19)
  const first = Date.parse(`${year}-01-01T${timeOfDay}Z`)
  const supportedStart = Date.parse('2026-01-01T00:00:00Z')
  const end = Date.parse(supportedEndUtc ?? '2040-12-31T23:00:00Z')
  const lastFit = end - durationHours * hour
  const yearEnd = Date.parse(`${year}-12-31T${timeOfDay}Z`)
  const days = Math.floor((Math.min(yearEnd, lastFit) - first) / (24 * hour))
  if (first < supportedStart || days < 0) return null
  return { from: utc(first), to: utc(first + days * 24 * hour) }
}

/** Whether the planning tools can run for these settings (they need hourly samples and whole hours). */
export function planningSupported(settings: Settings) {
  return settings.mission.sample_step_seconds === 3600 && Number.isInteger(settings.mission.duration_hours)
}
