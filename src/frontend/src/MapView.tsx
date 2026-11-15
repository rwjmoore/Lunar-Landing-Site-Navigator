import { useCallback, useEffect, useRef, useState, type PointerEvent } from 'react'
import { coordinates, sameSite, type Site } from './analysis'
import { Canvas } from './canvas'
import { insideNac, layers, levelFor, TileCache, tilesFor, type Bounds, type Tile } from './imagery'
import { fitToMap, groundDistance, localDirection, mapRadius, project, unproject, type Point } from './polar'
import basemapUrl from './assets/lroc-south-pole.webp'

const sourceUrl = 'https://data.lroc.im-ldi.com/lroc/view_rdr/NAC_POLE_SOUTH_CM_AVG'
// Bundled offline base: WAC_ROI_SOUTH_SUMMER_064P crop, ~474 m per pixel. Live tiles draw over it (imagery.ts).
// Projected outer pixel edges of the cropped GeoTIFF, in lunar kilometres.
const raster = { west: -333.438404078, east: 333.675305253, north: 333.438404078, south: -333.675305253 }
const origin = { x: 0, y: 0 }
const defaultZoom = 1
// Deep enough to reach the NAC mosaic's 1 m pixels on a typical map viewport.
const maxZoom = 250
const minZoom = 0.12
// How long the view must stay still before tiles are requested.
const settleMs = 150

function useBasemap() {
  const [image, setImage] = useState<HTMLImageElement | null>(null)
  const [failed, setFailed] = useState(false)
  useEffect(() => {
    const asset = new Image()
    asset.onload = () => setImage(asset)
    asset.onerror = () => setFailed(true)
    asset.src = basemapUrl
    return () => { asset.onload = null; asset.onerror = null }
  }, [])
  return { image, failed }
}

function screenPoint(point: Point, pole: Point, scale: number) {
  return { x: pole.x + point.x * scale, y: pole.y - point.y * scale }
}

function projectedPoint(point: Point, pole: Point, scale: number) {
  return { x: (point.x - pole.x) / scale, y: (pole.y - point.y) / scale }
}

function circle(ctx: CanvasRenderingContext2D, { x, y }: Point, r: number) {
  ctx.beginPath()
  ctx.arc(x, y, r, 0, Math.PI * 2)
}

function paintBase(ctx: CanvasRenderingContext2D, pole: Point, scale: number, image: HTMLImageElement | null,
  paintTiles?: () => void) {
  circle(ctx, pole, mapRadius * scale)
  ctx.clip()
  ctx.fillStyle = '#182028'
  ctx.fill()
  if (image) {
    const topLeft = screenPoint({ x: raster.west, y: raster.north }, pole, scale)
    ctx.drawImage(image, topLeft.x, topLeft.y, (raster.east - raster.west) * scale, (raster.north - raster.south) * scale)
  }
  paintTiles?.()
  if (image || paintTiles) {
    // The graticule and selection stay legible over bright pixels.
    circle(ctx, pole, mapRadius * scale)
    ctx.fillStyle = '#0710183b'
    ctx.fill()
  }
}

/** Which imagery the view centre shows, stated honestly (including when pixels are enlarged past native detail). */
function imageryNote(kmPerDevicePixel: number, centre: Point, nacShown: boolean, liveShown: boolean) {
  if (nacShown && insideNac(centre.x, centre.y)) {
    return kmPerDevicePixel < 0.001 ? 'LROC NAC controlled mosaic · 1 m/px (enlarged beyond native detail)' : 'LROC NAC controlled mosaic · 1 m/px'
  }
  if (liveShown) {
    return kmPerDevicePixel < 0.1 ? 'LROC WAC south-pole mosaic · ~100 m/px (enlarged beyond native detail)' : 'LROC WAC south-pole mosaic · ~100 m/px'
  }
  return kmPerDevicePixel < 0.474 ? 'Standard LROC WAC image · ~474 m/px (enlarged beyond native detail)' : 'Standard LROC WAC image · ~474 m/px'
}

function paintGrid(ctx: CanvasRenderingContext2D, pole: Point, scale: number, width: number, height: number, compact = false) {
  const step = compact ? 1 : ([0.05, 0.1, 0.25, 0.5, 1, 2, 5].find(value => value * 30.3 * scale >= 61) ?? 5)
  ctx.font = `${compact ? 9 : 11}px Inter, system-ui`
  ctx.textAlign = 'center'
  ctx.lineWidth = 1
  for (let offset = step; offset <= 10; offset += step) {
    const radius = project({ latitude_deg: -90 + offset, longitude_deg_east: 0 }).y * scale
    ctx.setLineDash([3, 5])
    ctx.strokeStyle = '#b6c9d472'
    circle(ctx, pole, radius)
    ctx.stroke()
    const tx = pole.x + radius * 0.58
    const ty = pole.y - radius * 0.815
    if (!compact && tx > 40 && tx < width - 50 && ty > 22 && ty < height - 40) {
      const label = `${Number((90 - offset).toFixed(2))}°S`
      ctx.strokeStyle = '#0c121c'
      ctx.lineWidth = 3
      ctx.setLineDash([])
      ctx.strokeText(label, tx, ty)
      ctx.fillStyle = '#eef3f9'
      ctx.fillText(label, tx, ty)
      ctx.lineWidth = 1
    }
  }
  for (let longitude = 0; longitude < 360; longitude += compact ? 90 : 30) {
    const direction = localDirection({ latitude_deg: -89, longitude_deg_east: longitude }, 0)
    const end = screenPoint({ x: mapRadius * direction.x, y: mapRadius * direction.y }, pole, scale)
    const cardinal = longitude % 90 === 0
    ctx.setLineDash(cardinal ? [] : [4, 6])
    ctx.strokeStyle = cardinal ? '#c3daed9c' : '#c3daed50'
    ctx.beginPath()
    ctx.moveTo(pole.x, pole.y)
    ctx.lineTo(end.x, end.y)
    ctx.stroke()
    if (cardinal) {
      const radius = Math.min(mapRadius * scale * 0.9, height * (compact ? 0.43 : 0.39))
      const x = pole.x + radius * direction.x
      const y = pole.y - radius * direction.y
      if (x > 20 && x < width - 20 && y > 14 && y < height - 8) {
        ctx.lineWidth = 3
        ctx.strokeStyle = '#0c121c'
        ctx.strokeText(`${longitude}°E`, x, y + 3)
        ctx.fillStyle = '#f0f6fc'
        ctx.fillText(`${longitude}°E`, x, y + 3)
        ctx.lineWidth = 1
      }
    }
  }
  ctx.setLineDash([])
  circle(ctx, pole, compact ? 2 : 3)
  ctx.fillStyle = '#e6f3ff'
  ctx.fill()
}

function paintSelection(ctx: CanvasRenderingContext2D, pole: Point, scale: number, site: Site, compact = false) {
  const selected = screenPoint(project(site), pole, scale)
  ctx.font = `600 ${compact ? 9 : 11}px Inter, system-ui`
  ctx.textAlign = 'center'
  if (site.latitude_deg > -90) {
    const north = localDirection(site, 0)
    const length = compact ? 18 : 36
    const tip = { x: selected.x + north.x * length, y: selected.y - north.y * length }
    ctx.beginPath()
    ctx.moveTo(selected.x, selected.y)
    ctx.lineTo(tip.x, tip.y)
    ctx.lineWidth = 2
    ctx.strokeStyle = '#a9dcfe'
    ctx.stroke()
    ctx.fillStyle = '#c4eaff'
    ctx.fillText('N', tip.x + north.x * 8, tip.y - north.y * 8 + 3)
    if (!compact) ctx.fillText('S', selected.x - north.x * 16, selected.y + north.y * 16 + 3)
  }
  circle(ctx, selected, compact ? 4 : 7)
  ctx.fillStyle = '#63c1fb'
  ctx.fill()
  ctx.strokeStyle = '#e6f7ff'
  ctx.lineWidth = compact ? 1 : 2
  ctx.stroke()
}

function paintScale(ctx: CanvasRenderingContext2D, at: Point, pole: Point, scale: number, length: number) {
  const start = unproject(projectedPoint(at, pole, scale))
  const distance = (pixels: number) => groundDistance(start, unproject(projectedPoint({ x: at.x + pixels, y: at.y }, pole, scale)))
  const max = distance(length)
  const order = 10 ** Math.floor(Math.log10(max))
  const km = ([5, 2, 1].find(value => value * order <= max) ?? 1) * order
  let left = 0
  let right = length
  for (let i = 0; i < 14; i++) {
    const mid = (left + right) / 2
    if (distance(mid) < km) left = mid
    else right = mid
  }
  const end = at.x + (left + right) / 2
  ctx.beginPath()
  ctx.moveTo(at.x, at.y - 4)
  ctx.lineTo(at.x, at.y + 4)
  ctx.moveTo(at.x, at.y)
  ctx.lineTo(end, at.y)
  ctx.moveTo(end, at.y - 4)
  ctx.lineTo(end, at.y + 4)
  ctx.strokeStyle = '#0a0d13'
  ctx.lineWidth = 4
  ctx.stroke()
  ctx.strokeStyle = '#edf4fb'
  ctx.lineWidth = 2
  ctx.stroke()
  ctx.font = '600 11px Inter, system-ui'
  ctx.textAlign = 'center'
  const label = km < 1 ? `${Math.round(km * 1000)} m` : `${km} km`
  ctx.strokeStyle = '#0a0d13'
  ctx.lineWidth = 3
  ctx.strokeText(label, (end + at.x) / 2, at.y - 8)
  ctx.fillStyle = '#f1f6fc'
  ctx.fillText(label, (end + at.x) / 2, at.y - 8)
}

function viewport(width: number, height: number, center: Point, zoom: number) {
  const scale = Math.min(width, height) / 68 * zoom
  return { scale, pole: { x: width / 2 - center.x * scale, y: height / 2 + center.y * scale } }
}

export function MapView({ site, sites, onSelect, onInspect, onCoordinates, availability, coverageEdgeDeg = null }: {
  site: Site; sites: Site[]; onSelect: (site: Site) => void; onInspect: () => void; onCoordinates: () => void; availability: string
  /** Northern edge of the backend's on-demand terrain coverage, drawn as a ring; null hides it. */
  coverageEdgeDeg?: number | null
}) {
  const { image, failed } = useBasemap()
  const [center, setCenter] = useState<Point>(origin)
  const [zoom, setZoom] = useState(defaultZoom)
  const [tileVersion, setTileVersion] = useState(0)
  const [imagery, setImagery] = useState('')
  // Off by default: the standard single image zooms instantly; high-res LROC tiles load only when switched on.
  const [highRes, setHighRes] = useState(false)
  const viewportElement = useRef<HTMLDivElement>(null)
  // The latest view, for the wheel handler (several wheel events can arrive before a re-render).
  const latest = useRef({ center, zoom })
  latest.current = { center, zoom }
  const tiles = useRef<TileCache | null>(null)
  const pendingTiles = useRef<{ signature: string; tiles: Tile[] }>({ signature: '', tiles: [] })
  const settleTimer = useRef<number | undefined>(undefined)
  useEffect(() => () => { if (settleTimer.current !== undefined) clearTimeout(settleTimer.current) }, [])
  // Switching HD off stops all imagery traffic at once: no settle delay, during which queued tiles could still start.
  useEffect(() => {
    if (highRes) return
    if (settleTimer.current !== undefined) { clearTimeout(settleTimer.current); settleTimer.current = undefined }
    pendingTiles.current = { signature: '', tiles: [] }
    tiles.current?.request([])
  }, [highRes])
  if (!tiles.current) {
    let pending = false
    tiles.current = new TileCache(() => {
      if (pending) return
      pending = true
      requestAnimationFrame(() => { pending = false; setTileVersion(value => value + 1) })
    })
  }
  const [hover, setHover] = useState<string | null>(null)
  const [dragging, setDragging] = useState(false)
  const drag = useRef<{ start: Point; center: Point; moved: boolean } | null>(null)
  useEffect(() => {
    const point = project({ latitude_deg: site.latitude_deg, longitude_deg_east: site.longitude_deg_east })
    setCenter(previous => Math.hypot(point.x - previous.x, point.y - previous.y) > 25 / zoom ? fitToMap(point) : previous)
    // Re-centre selected waypoints when they change, so zooming still follows the current map centre.
  }, [site.latitude_deg, site.longitude_deg_east])
  const draw = useCallback((ctx: CanvasRenderingContext2D, w: number, h: number) => {
    const { pole, scale } = viewport(w, h, center, zoom)
    ctx.fillStyle = '#0b0e12'
    ctx.fillRect(0, 0, w, h)
    ctx.save()
    const cache = tiles.current!
    const dpr = window.devicePixelRatio || 1
    const view: Bounds = { minX: -pole.x / scale, maxX: (w - pole.x) / scale, minY: (pole.y - h) / scale, maxY: pole.y / scale }
    const needed: Tile[] = []
    let nacShown = false
    let liveShown = false
    // High-res off: only the standard single image is drawn, and no tiles are requested (any in flight are cancelled).
    paintBase(ctx, pole, scale, image, !highRes ? undefined : () => {
      const target = levelFor(scale * dpr)
      ctx.imageSmoothingQuality = 'high'
      for (const layer of layers) {
        const top = Math.min(target, layer.maxLevel)
        if (top < layer.minLevel) continue
        // Coarser levels first, so finer tiles replace them as they arrive (no blank gaps while loading).
        for (let level = Math.max(layer.minLevel, top - 4); level <= top; level++) {
          for (const tile of tilesFor(layer, level, view)) {
            const picture = cache.get(tile.key)
            if (level === top) needed.push(tile)
            if (!picture) continue
            if (layer.id === 'nac') nacShown = true
            else liveShown = true
            const a = screenPoint({ x: tile.bounds.minX, y: tile.bounds.maxY }, pole, scale)
            const b = screenPoint({ x: tile.bounds.maxX, y: tile.bounds.minY }, pole, scale)
            // Snap to whole pixels so neighbouring tiles meet without hairline seams.
            ctx.drawImage(picture, Math.floor(a.x), Math.floor(a.y), Math.ceil(b.x) - Math.floor(a.x), Math.ceil(b.y) - Math.floor(a.y))
          }
        }
      }
    })
    // Ask for tiles only once zooming/panning pauses, so levels merely passed through are never downloaded.
    const signature = needed.map(tile => tile.key).join('|')
    if (signature !== pendingTiles.current.signature) {
      pendingTiles.current = { signature, tiles: needed }
      if (settleTimer.current !== undefined) clearTimeout(settleTimer.current)
      settleTimer.current = window.setTimeout(() => {
        settleTimer.current = undefined
        cache.request(pendingTiles.current.tiles)
      }, settleMs)
    }
    setImagery(imageryNote(1 / (scale * dpr), center, nacShown, liveShown))
    paintGrid(ctx, pole, scale, w, h)
    if (coverageEdgeDeg !== null) {
      const radius = project({ latitude_deg: coverageEdgeDeg, longitude_deg_east: 0 }).y * scale
      circle(ctx, pole, radius)
      ctx.setLineDash([10, 6])
      ctx.strokeStyle = '#8fe3b8'
      ctx.lineWidth = 1.6
      ctx.stroke()
      ctx.setLineDash([])
      const label = `Analysis coverage · south of ${Math.abs(coverageEdgeDeg).toFixed(1)}°S`
      const x = pole.x - radius * 0.62
      const y = pole.y + radius * 0.80
      if (x > 80 && x < w - 80 && y > 20 && y < h - 50) {
        ctx.font = '600 11px Inter, system-ui'
        ctx.textAlign = 'center'
        ctx.lineWidth = 3
        ctx.strokeStyle = '#0c121c'
        ctx.strokeText(label, x, y)
        ctx.fillStyle = '#b5f0d0'
        ctx.fillText(label, x, y)
      }
    }
    for (const location of sites) {
      if (sameSite(location, site)) continue
      const point = screenPoint(project(location), pole, scale)
      circle(ctx, point, 5)
      ctx.fillStyle = '#141c26'
      ctx.fill()
      ctx.strokeStyle = '#b7d8ee'
      ctx.lineWidth = 1.5
      ctx.stroke()
    }
    paintSelection(ctx, pole, scale, site)
    ctx.restore()
    paintScale(ctx, { x: 24, y: h - 28 }, pole, scale, Math.min(w * 0.23, 138))
    // tileVersion repaints as tiles arrive.
  }, [center, coverageEdgeDeg, highRes, image, site, sites, zoom, tileVersion])

  function select(point: Point, pole: Point, scale: number) {
    const p = projectedPoint(point, pole, scale)
    if (Math.hypot(p.x, p.y) > mapRadius) return
    const nearest = sites.find(location => {
      const marker = screenPoint(project(location), pole, scale)
      return Math.hypot(point.x - marker.x, point.y - marker.y) <= 7
    })
    onSelect(nearest ?? { name: 'Selected waypoint', ...unproject(p) })
  }

  function move(event: PointerEvent<HTMLCanvasElement>) {
    const rect = event.currentTarget.getBoundingClientRect()
    const point = { x: event.clientX - rect.left, y: event.clientY - rect.top }
    const { pole, scale } = viewport(rect.width, rect.height, center, zoom)
    if (drag.current) {
      const delta = { x: (event.clientX - drag.current.start.x) / scale, y: (event.clientY - drag.current.start.y) / scale }
      if (Math.hypot(delta.x, delta.y) * scale > 4) drag.current.moved = true
      if (drag.current.moved) {
        setDragging(true)
        setCenter(fitToMap({ x: drag.current.center.x - delta.x, y: drag.current.center.y + delta.y }))
        return
      }
    }
    const p = projectedPoint(point, pole, scale)
    setHover(Math.hypot(p.x, p.y) <= mapRadius ? coordinates(unproject(p)) : 'Outside the map area')
  }

  function zoomBy(factor: number) {
    setZoom(value => Math.min(maxZoom, Math.max(minZoom, value * factor)))
  }

  // Mouse-wheel zoom about the cursor (the point under it stays put). Non-passive so the page doesn't scroll.
  useEffect(() => {
    const element = viewportElement.current
    if (!element) return
    function wheel(event: WheelEvent) {
      const canvas = element!.querySelector('canvas')
      if (!canvas || event.target !== canvas) return
      event.preventDefault()
      const rect = canvas.getBoundingClientRect()
      const at = { x: event.clientX - rect.left, y: event.clientY - rect.top }
      const factor = Math.exp(-event.deltaY * (event.deltaMode === 1 ? 0.05 : 0.0015))
      const { center: previous, zoom: current } = latest.current
      const next = Math.min(maxZoom, Math.max(minZoom, current * factor))
      const before = viewport(rect.width, rect.height, previous, current)
      const ground = projectedPoint(at, before.pole, before.scale)
      const after = viewport(rect.width, rect.height, previous, next)
      const moved = projectedPoint(at, after.pole, after.scale)
      const shifted = fitToMap({ x: previous.x + ground.x - moved.x, y: previous.y + ground.y - moved.y })
      latest.current = { center: shifted, zoom: next }
      setZoom(next)
      setCenter(shifted)
    }
    element.addEventListener('wheel', wheel, { passive: false })
    return () => element.removeEventListener('wheel', wheel)
  }, [])

  return <div className="map-content">
    <div className="map-toolbar">
      <p>Click to select a waypoint. Drag to pan; scroll to zoom.</p>
      <div className="map-actions">
        <div className="selected-site" aria-live="polite" aria-label="Selected waypoint">
          <strong>{site.name}</strong><span>{coordinates(site)}</span>
        </div>
        <div className="button-row"><button onClick={onCoordinates}>Enter coordinates</button><button className="primary" onClick={onInspect}>Inspect horizon <span aria-hidden="true">→</span></button></div>
      </div>
    </div>
    <div className="map-viewport" ref={viewportElement}>
      <Canvas paint={draw} className={dragging ? 'is-dragging' : ''} tabIndex={0}
        aria-label="South-polar lunar map. Use the arrow keys to pan and Enter to select the center."
        onPointerDown={event => {
          if (!event.isPrimary || event.button !== 0) return
          drag.current = { start: { x: event.clientX, y: event.clientY }, center, moved: false }
          event.currentTarget.setPointerCapture(event.pointerId)
        }} onPointerMove={move} onPointerUp={event => {
          if (!event.isPrimary) return
          if (drag.current && !drag.current.moved) {
            const r = event.currentTarget.getBoundingClientRect()
            const frame = viewport(r.width, r.height, center, zoom)
            select({ x: event.clientX - r.left, y: event.clientY - r.top }, frame.pole, frame.scale)
          }
          drag.current = null
          setDragging(false)
        }} onPointerCancel={() => { drag.current = null; setDragging(false) }} onPointerLeave={() => setHover(null)}
        onKeyDown={event => {
          const directions: Record<string, Point> = { ArrowUp: { x: 0, y: 1 }, ArrowDown: { x: 0, y: -1 }, ArrowLeft: { x: -1, y: 0 }, ArrowRight: { x: 1, y: 0 } }
          const direction = directions[event.key]
          if (direction) {
            event.preventDefault()
            setCenter(fitToMap({ x: center.x + direction.x * 6 / zoom, y: center.y + direction.y * 6 / zoom }))
          } else if (event.key === 'Enter') {
            event.preventDefault()
            const r = event.currentTarget.getBoundingClientRect()
            const { pole, scale } = viewport(r.width, r.height, center, zoom)
            select({ x: r.width / 2, y: r.height / 2 }, pole, scale)
          }
        }} />
      <div className="map-key inset-label"><strong>South pole · 2D projected map</strong><span>0°E points up · longitude is east-positive</span>
        <span className="imagery-note">Imagery: {imagery}</span></div>
      <div className="map-zoom" aria-label="Map zoom">
        <button aria-label="Zoom in" disabled={zoom >= maxZoom} onClick={() => zoomBy(1.6)}>+</button>
        <button aria-label="Zoom out" disabled={zoom <= minZoom} onClick={() => zoomBy(1 / 1.6)}>−</button>
        <button aria-label="Reset map view" title="Reset map view" onClick={() => { setCenter(origin); setZoom(defaultZoom) }}>⌖</button>
        <button className="hires-toggle" aria-pressed={highRes} title={highRes ? 'High-resolution imagery on (LROC NAC 1 m/px, WAC 100 m/px). Click to use the standard image.'
          : 'Load high-resolution imagery (LROC NAC 1 m/px, WAC 100 m/px) for this view'} onClick={() => setHighRes(value => !value)}>HD</button>
      </div>
      <div className="map-readouts">
        <div className="inset-label cursor-position"><span>Cursor position</span><strong>{hover ?? 'Move over the map'}</strong></div>
      </div>
    </div>
    <div className="map-footer"><p role="status">{availability}</p><a href={sourceUrl} target="_blank" rel="noreferrer">{failed ? 'Offline basemap unavailable · LROC source' : 'NASA/GSFC/ASU · LROC NAC + WAC mosaics'} <span aria-hidden="true">↗</span></a></div>
  </div>
}

export interface Sector { start: number; width: number }

export function PolarLocator({ site, sector }: { site: Site; sector: Sector }) {
  const { image } = useBasemap()
  const draw = useCallback((ctx: CanvasRenderingContext2D, w: number, h: number) => {
    const pole = { x: w / 2, y: h / 2 }
    const sitePoint = project(site)
    const radius = Math.min(w, h) / 2 - 7
    const scale = radius / Math.max(31, Math.hypot(sitePoint.x, sitePoint.y) * 1.23)
    ctx.save()
    circle(ctx, pole, radius)
    ctx.clip()
    paintBase(ctx, pole, scale, image)
    paintGrid(ctx, pole, scale, w, h, true)
    if (sector.width < 360 && site.latitude_deg > -90) {
      const selected = screenPoint(sitePoint, pole, scale)
      const angle = (site.longitude_deg_east + sector.start - 90) * Math.PI / 180
      ctx.beginPath()
      ctx.moveTo(selected.x, selected.y)
      ctx.arc(selected.x, selected.y, radius * 0.63, angle, angle + sector.width * Math.PI / 180)
      ctx.closePath()
      ctx.fillStyle = '#6cbcff65'
      ctx.fill()
      ctx.strokeStyle = '#a6d8ff'
      ctx.lineWidth = 1.25
      ctx.stroke()
    }
    paintSelection(ctx, pole, scale, site, true)
    ctx.restore()
    circle(ctx, pole, radius)
    ctx.lineWidth = 1
    ctx.strokeStyle = '#708090'
    ctx.stroke()
    paintScale(ctx, { x: 12, y: h - 8 }, pole, scale, 56)
  }, [image, sector, site])
  return <div className="locator">
    <h3>South-pole locator</h3>
    <Canvas paint={draw} role="img" aria-label="Selected waypoint on a polar map, with local north and the current viewing sector" />
    <p>{site.latitude_deg === -90 ? 'Local direction unavailable at the pole' : sector.width >= 360 ? 'Full 360° local horizon' : `${sector.start}° → ${(sector.start + sector.width) % 360}° from local north`}</p>
  </div>
}
