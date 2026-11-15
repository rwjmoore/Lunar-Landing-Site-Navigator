// Map imagery: tiled LROC mosaics from the public Lunaserv WMS (https://wms.im-ldi.com/), requested in the
// map's own projection so no reprojection happens in the browser. Visual imagery only: terrain, horizons and
// visibility always come from the LOLA-based backend, never from image brightness.
//
// Verified 2026-11-15 from the service's GetCapabilities and test requests (docs/imagery.md):
// - IAU2000:30120 is the Moon south-polar stereographic projection (sphere R = 1,737,400 m, centred at 90°S, 0°E),
//   the same projection as polar.ts. (IAU2000:30118 is the NORTH-polar one: it returns blank south-pole tiles.)
// - The service sends `Access-Control-Allow-Origin: *` and advertises Fees: None, AccessConstraints: None.

export const WMS_URL = 'https://wms.im-ldi.com/'
export const IMAGERY_SRS = 'IAU2000:30120'

export interface ImageryLayer {
  id: 'wac' | 'nac'
  wmsLayer: string
  label: string
  nativeKmPerPixel: number
  /** Highest pyramid level requested; deeper zooms enlarge these tiles (no detail exists beyond them). */
  maxLevel: number
  minLevel: number
  /** Projected radius of the layer's coverage around the pole, in km (null = the whole map). */
  coverageKm: number | null
  citation: string
}

// 512 px tiles: the server renders one in about the same time as a 256 px tile (~3 s), so 4x the area per request.
const TILE_PX = 512
/** Pyramid root: one tile spanning ±320 km, which contains the whole 80–90°S map (radius ≈ 304 km). */
const ROOT_KM = 640
const ROOT_MIN = -ROOT_KM / 2

// Coverage edge of the NAC mosaic (84°S), in projected km: 2 R tan((90 - 84)° / 2).
const NAC_EDGE_KM = 2 * 1737.4 * Math.tan(3 * Math.PI / 180)

export const layers: ImageryLayer[] = [
  {
    id: 'wac', wmsLayer: 'luna_wac_roi_south_summer', label: 'LROC WAC South Pole Summer mosaic',
    nativeKmPerPixel: 0.1, minLevel: 0, maxLevel: 4, coverageKm: null,
    citation: 'NASA/GSFC/ASU, LROC WAC South Pole Summer mosaic (Speyerer et al.)',
  },
  {
    // Requested from WAC's finest level (78 m tile pixels) down to 0.61 m; coarser NAC tiles add little and render slowly.
    id: 'nac', wmsLayer: 'luna_nac_pole_control_south', label: 'LROC NAC controlled south-pole mosaic (average)',
    nativeKmPerPixel: 0.001, minLevel: 4, maxLevel: 11, coverageKm: NAC_EDGE_KM,
    citation: 'NASA/GSFC/ASU, NAC_POLE_SOUTH_CM_AVG (Archinal et al. 2023, LPSC 54 #2333)',
  },
]

export interface Bounds { minX: number; maxX: number; minY: number; maxY: number }
export interface Tile { layer: ImageryLayer; level: number; col: number; row: number; bounds: Bounds; key: string; url: string }

/** The pyramid level whose tiles show at most one image pixel per device pixel at this scale. */
export function levelFor(devicePixelsPerKm: number) {
  return Math.max(0, Math.ceil(Math.log2(ROOT_KM * devicePixelsPerKm / TILE_PX)))
}

function tileBounds(level: number, col: number, row: number): Bounds {
  const span = ROOT_KM / 2 ** level
  return { minX: ROOT_MIN + col * span, maxX: ROOT_MIN + (col + 1) * span, minY: ROOT_MIN + row * span, maxY: ROOT_MIN + (row + 1) * span }
}

/** Distances from the pole to a box's nearest and farthest points, in km. */
function radialRange(b: Bounds) {
  const nx = Math.max(b.minX, Math.min(0, b.maxX))
  const ny = Math.max(b.minY, Math.min(0, b.maxY))
  const fx = Math.max(Math.abs(b.minX), Math.abs(b.maxX))
  const fy = Math.max(Math.abs(b.minY), Math.abs(b.maxY))
  return { near: Math.hypot(nx, ny), far: Math.hypot(fx, fy) }
}

function wmsUrl(layer: ImageryLayer, b: Bounds, transparent: boolean) {
  const m = (km: number) => Math.round(km * 1000 * 1000) / 1000   // metres, to the millimetre
  const params = new URLSearchParams({
    SERVICE: 'WMS', VERSION: '1.1.1', REQUEST: 'GetMap', STYLES: '', SRS: IMAGERY_SRS, LAYERS: layer.wmsLayer,
    BBOX: [m(b.minX), m(b.minY), m(b.maxX), m(b.maxY)].join(','), WIDTH: String(TILE_PX), HEIGHT: String(TILE_PX),
    FORMAT: transparent ? 'image/png' : 'image/jpeg', ...(transparent ? { TRANSPARENT: 'TRUE' } : {}),
  })
  return `${WMS_URL}?${params}`
}

/** Tiles of one layer and level that overlap the view (and the layer's coverage), nearest the view centre first. */
export function tilesFor(layer: ImageryLayer, level: number, view: Bounds): Tile[] {
  const span = ROOT_KM / 2 ** level
  const count = 2 ** level
  const clamp = (v: number) => Math.max(0, Math.min(count - 1, v))
  const c0 = clamp(Math.floor((view.minX - ROOT_MIN) / span))
  const c1 = clamp(Math.floor((view.maxX - ROOT_MIN) / span))
  const r0 = clamp(Math.floor((view.minY - ROOT_MIN) / span))
  const r1 = clamp(Math.floor((view.maxY - ROOT_MIN) / span))
  const cx = (view.minX + view.maxX) / 2
  const cy = (view.minY + view.maxY) / 2
  const result: Tile[] = []
  for (let col = c0; col <= c1; col++) {
    for (let row = r0; row <= r1; row++) {
      const bounds = tileBounds(level, col, row)
      const { near, far } = radialRange(bounds)
      if (layer.coverageKm !== null && near >= layer.coverageKm) continue
      // Tiles crossing the coverage edge are PNG so the area without data stays transparent.
      const transparent = layer.coverageKm !== null && far > layer.coverageKm
      const key = `${layer.id}/${level}/${col}/${row}`
      result.push({ layer, level, col, row, bounds, key, url: wmsUrl(layer, bounds, transparent) })
    }
  }
  const distance = (t: Tile) => Math.hypot((t.bounds.minX + t.bounds.maxX) / 2 - cx, (t.bounds.minY + t.bounds.maxY) / 2 - cy)
  return result.sort((a, b) => distance(a) - distance(b))
}

/** Whether the NAC layer covers the given projected point. */
export function insideNac(x: number, y: number) {
  return Math.hypot(x, y) < NAC_EDGE_KM
}

type Entry = { state: 'loading' | 'loaded' | 'failed'; bitmap?: ImageBitmap; controller?: AbortController }

/** Loads tiles with bounded concurrency, nearest the view centre first, and keeps a bounded cache.
 *  Downloads for tiles the view no longer needs are cancelled, so their slots go to the current view. */
export class TileCache {
  private entries = new Map<string, Entry>()
  private queue: Tile[] = []
  private active = 0
  failures = 0
  loaded = 0
  cancelled = 0

  constructor(private onChange: () => void, private maxActive = 6, private maxEntries = 600) {}

  get(key: string) {
    const entry = this.entries.get(key)
    return entry?.state === 'loaded' ? entry.bitmap : undefined
  }

  /** Make these the only tiles wanted: cancel other downloads, queue the missing ones, start loading. */
  request(tiles: Tile[]) {
    const wanted = new Set(tiles.map(tile => tile.key))
    for (const [key, entry] of this.entries) {
      if (entry.state === 'loading' && !wanted.has(key)) {
        entry.controller?.abort()   // the abort handler frees the slot and forgets the entry
      }
    }
    this.queue = tiles.filter(tile => !this.entries.has(tile.key))
    this.pump()
  }

  private pump() {
    while (this.active < this.maxActive && this.queue.length) {
      const tile = this.queue.shift()!
      if (this.entries.has(tile.key)) continue
      const controller = new AbortController()
      const entry: Entry = { state: 'loading', controller }
      this.entries.set(tile.key, entry)
      this.active++
      fetch(tile.url, { signal: controller.signal })
        .then(reply => { if (!reply.ok) throw new Error(`HTTP ${reply.status}`); return reply.blob() })
        .then(blob => createImageBitmap(blob))
        .then(bitmap => { entry.state = 'loaded'; entry.bitmap = bitmap; this.loaded++ })
        .catch(() => {
          if (controller.signal.aborted) { this.entries.delete(tile.key); this.cancelled++ }   // may be requested again later
          else { entry.state = 'failed'; this.failures++ }   // stays failed (no retry loop); coarser layers still show
        })
        .finally(() => {
          entry.controller = undefined
          this.active--
          this.trim()
          if (!controller.signal.aborted) this.onChange()
          this.pump()
        })
    }
  }

  private trim() {
    for (const [key, entry] of this.entries) {
      if (this.entries.size <= this.maxEntries) break
      if (entry.state === 'loading') continue
      entry.bitmap?.close()
      this.entries.delete(key)
    }
  }
}
