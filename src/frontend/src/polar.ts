import { normalizeLongitude, type Site } from './analysis'

export const MOON_RADIUS_KM = 1737.4
export const MAP_NORTH_EDGE = -80
const RAD = Math.PI / 180
type Coordinate = Omit<Site, 'name'>
export interface Point { x: number; y: number }

export function project(location: Coordinate): Point {
  const rho = 2 * MOON_RADIUS_KM * Math.tan((90 + location.latitude_deg) * RAD / 2)
  const longitude = location.longitude_deg_east * RAD
  return { x: rho * Math.sin(longitude), y: rho * Math.cos(longitude) }
}

export function unproject({ x, y }: Point): Coordinate {
  const rho = Math.hypot(x, y)
  return {
    latitude_deg: 2 * Math.atan(rho / (2 * MOON_RADIUS_KM)) / RAD - 90,
    longitude_deg_east: rho === 0 ? 0 : normalizeLongitude(Math.atan2(x, y) / RAD),
  }
}

export function localDirection(location: Coordinate, azimuth: number): Point {
  // The projection is conformal, with local north pointing radially away from the pole.
  const angle = (location.longitude_deg_east + azimuth) * RAD
  return { x: Math.sin(angle), y: Math.cos(angle) }
}

export function groundDistance(a: Coordinate, b: Coordinate) {
  const latA = a.latitude_deg * RAD
  const latB = b.latitude_deg * RAD
  const deltaLon = (a.longitude_deg_east - b.longitude_deg_east) * RAD
  const h = Math.sin((latA - latB) / 2) ** 2 + Math.cos(latA) * Math.cos(latB) * Math.sin(deltaLon / 2) ** 2
  return 2 * MOON_RADIUS_KM * Math.asin(Math.min(1, Math.sqrt(h)))
}

export const mapRadius = project({ latitude_deg: MAP_NORTH_EDGE, longitude_deg_east: 0 }).y

export function fitToMap({ x, y }: Point): Point {
  const ratio = Math.max(1, Math.hypot(x, y) / (mapRadius * 0.99))
  return { x: x / ratio, y: y / ratio }
}
