// Elevation / slope overlay (docs/elevation_overlay.md). Tiles are built offline from the same LOLA terrain the
// physics uses (pipeline/build_elevation_tiles.py) and served by the API at /tiles/elevation/. They store heights,
// not colours, so the browser can recolour them for the current view, derive slope and read the height under the
// cursor. Display only: analyses never use these tiles.
import { ROOT_KM, tileBounds, type Bounds, type Fetchable } from './imagery'

export type OverlayMode = 'off' | 'elevation' | 'slope'
type Box = [number, number, number, number]   // min x, min y, max x, max y, metres

export interface Manifest {
  tile_px: number
  root_m: number
  encoding: { offset_m: number; step_m: number }
  region: { levels: [number, number]; bounds_m: Box; source_pixel_m: number }
  sites: { id: string; levels: [number, number]; bounds_m: Box }[]
  height_range_m: [number, number]
}

export interface ElevationTile extends Fetchable { level: number; col: number; row: number; bounds: Bounds }

/** Decoded heights of one tile (metres above the 1,737.4 km sphere; NaN = no data), row 0 = north edge. */
export interface HeightTile { heights: Float32Array; size: number; slope?: Float32Array }

/** Reads the tile set's manifest; null if the server has no elevation tiles. */
export async function loadManifest(base: string, signal: AbortSignal): Promise<Manifest | null> {
  try {
    const reply = await fetch(`${base}/manifest.json`, { signal })
    if (!reply.ok) return null
    const manifest = await reply.json() as Manifest
    // The overlay shares the imagery's tile grid; refuse a tile set built on a different one.
    return manifest.root_m === ROOT_KM * 1000 && manifest.encoding?.step_m > 0 ? manifest : null
  } catch { return null }
}

const box = (b: Box): Bounds => ({ minX: b[0] / 1000, minY: b[1] / 1000, maxX: b[2] / 1000, maxY: b[3] / 1000 })
const overlaps = (a: Bounds, b: Bounds) => a.minX < b.maxX && b.minX < a.maxX && a.minY < b.maxY && b.minY < a.maxY

/** Where tiles exist at a level: the regional map for coarse levels, the four site maps for fine ones. */
export function coverageAt(manifest: Manifest, level: number): Bounds[] {
  const [r0, r1] = manifest.region.levels
  if (level >= r0 && level <= r1) return [box(manifest.region.bounds_m)]
  return manifest.sites.filter(site => level >= site.levels[0] && level <= site.levels[1]).map(site => box(site.bounds_m))
}

export function finestLevel(manifest: Manifest) {
  return Math.max(manifest.region.levels[1], ...manifest.sites.map(site => site.levels[1]))
}

/** Tiles at one level overlapping both the view and the data, nearest the view centre first. */
export function elevationTiles(base: string, manifest: Manifest, level: number, view: Bounds): ElevationTile[] {
  const areas = coverageAt(manifest, level).filter(area => overlaps(area, view))
  if (!areas.length) return []
  const span = ROOT_KM / 2 ** level
  const count = 2 ** level
  const clamp = (v: number) => Math.max(0, Math.min(count - 1, v))
  const min = -ROOT_KM / 2
  const cx = (view.minX + view.maxX) / 2
  const cy = (view.minY + view.maxY) / 2
  const result: ElevationTile[] = []
  for (let col = clamp(Math.floor((view.minX - min) / span)); col <= clamp(Math.floor((view.maxX - min) / span)); col++) {
    for (let row = clamp(Math.floor((view.minY - min) / span)); row <= clamp(Math.floor((view.maxY - min) / span)); row++) {
      const bounds = tileBounds(level, col, row)
      if (!areas.some(area => overlaps(area, bounds))) continue
      result.push({ level, col, row, bounds, key: `elevation/${level}/${col}/${row}`, url: `${base}/${level}/${col}/${row}.png` })
    }
  }
  const distance = (t: ElevationTile) => Math.hypot((t.bounds.minX + t.bounds.maxX) / 2 - cx, (t.bounds.minY + t.bounds.maxY) / 2 - cy)
  return result.sort((a, b) => distance(a) - distance(b))
}

/** PNG -> heights, exactly as encoded by app/terrain/elevation_tiles.py (no colour management, no premultiplication). */
export async function decodeTile(blob: Blob, manifest: Manifest): Promise<HeightTile> {
  const bitmap = await createImageBitmap(blob, { premultiplyAlpha: 'none', colorSpaceConversion: 'none' })
  const size = bitmap.width
  const canvas = new OffscreenCanvas(size, size)
  const context = canvas.getContext('2d', { willReadFrequently: true })!
  context.drawImage(bitmap, 0, 0)
  bitmap.close()
  const rgba = context.getImageData(0, 0, size, size).data
  const heights = new Float32Array(size * size)
  const { offset_m, step_m } = manifest.encoding
  for (let i = 0, p = 0; i < heights.length; i++, p += 4) {
    heights[i] = rgba[p + 3] === 0 ? NaN : (rgba[p] * 256 + rgba[p + 1]) * step_m - offset_m
  }
  return { heights, size }
}

/** Surface slope in degrees from central differences (one-sided at tile edges); NaN next to missing data. */
export function slopeOf(tile: HeightTile, pixelM: number): Float32Array {
  if (tile.slope) return tile.slope
  const { heights: h, size: n } = tile
  const slope = new Float32Array(n * n)
  for (let r = 0; r < n; r++) {
    const up = r > 0 ? r - 1 : r
    const down = r < n - 1 ? r + 1 : r
    for (let c = 0; c < n; c++) {
      const left = c > 0 ? c - 1 : c
      const right = c < n - 1 ? c + 1 : c
      const dzdx = (h[r * n + right] - h[r * n + left]) / ((right - left) * pixelM)
      const dzdy = (h[up * n + c] - h[down * n + c]) / ((down - up) * pixelM)
      slope[r * n + c] = Math.atan(Math.hypot(dzdx, dzdy)) * 180 / Math.PI
    }
  }
  tile.slope = slope
  return slope
}

// Perceptually uniform, colour-blind-safe scales: viridis for height, inferno for slope.
export const scales = {
  elevation: ['#440154', '#482878', '#3e4a89', '#31688e', '#26828e', '#1f9e89', '#35b779', '#6ece58', '#b5de2b', '#fde725'],
  slope: ['#000004', '#1b0c41', '#4a0c6b', '#781c6d', '#a52c60', '#cf4446', '#ed6925', '#fb9b06', '#f7d13d', '#fcffa4'],
}
export const SLOPE_RANGE: [number, number] = [0, 40]

function lut(stops: string[]) {
  const rgb = stops.map(hex => [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16)))
  const table = new Uint8ClampedArray(256 * 3)
  for (let i = 0; i < 256; i++) {
    const t = i / 255 * (rgb.length - 1)
    const k = Math.min(rgb.length - 2, Math.floor(t))
    const f = t - k
    for (let j = 0; j < 3; j++) table[i * 3 + j] = rgb[k][j] * (1 - f) + rgb[k + 1][j] * f
  }
  return table
}
const tables = { elevation: lut(scales.elevation), slope: lut(scales.slope) }

/** Colours values onto a canvas (NaN stays transparent). */
export function colourise(values: Float32Array, size: number, mode: 'elevation' | 'slope', [lo, hi]: [number, number]) {
  const table = tables[mode]
  const image = new ImageData(size, size)
  const out = image.data
  const scale = 255 / Math.max(hi - lo, 1e-6)
  for (let i = 0, p = 0; i < values.length; i++, p += 4) {
    const v = values[i]
    if (Number.isNaN(v)) continue
    const k = Math.max(0, Math.min(255, Math.round((v - lo) * scale))) * 3
    out[p] = table[k]; out[p + 1] = table[k + 1]; out[p + 2] = table[k + 2]; out[p + 3] = 255
  }
  const canvas = new OffscreenCanvas(size, size)
  canvas.getContext('2d')!.putImageData(image, 0, 0)
  return canvas
}

/** Height range of the view (2nd-98th percentile of sampled pixels), rounded outward to a tidy step. */
export function viewRange(samples: number[]): [number, number] | null {
  if (samples.length < 16) return null
  samples.sort((a, b) => a - b)
  let lo = samples[Math.floor(samples.length * 0.02)]
  let hi = samples[Math.ceil(samples.length * 0.98) - 1]
  const step = hi - lo > 2000 ? 100 : hi - lo > 300 ? 25 : 5
  lo = Math.floor(lo / step) * step
  hi = Math.max(lo + step, Math.ceil(hi / step) * step)
  return [lo, hi]
}

/** Pixel of a tile containing a map point (km), or -1 if outside. */
export function pixelIndex(bounds: Bounds, size: number, x: number, y: number) {
  const span = bounds.maxX - bounds.minX
  const col = Math.floor((x - bounds.minX) / span * size)
  const row = Math.floor((bounds.maxY - y) / span * size)
  return col < 0 || row < 0 || col >= size || row >= size ? -1 : row * size + col
}
