import { useCallback, useEffect, useRef, useState } from 'react'
import { analysisKey, candidateSite, coordinates, defaultSettings, formatUtc, initialSite, readAnalysis,
  requestAnalysis, requestSites, sameSite, settingsKey, type Candidate, type Settings, type Site, type SiteCatalog,
  type Vehicle } from './analysis'
import { EdgeDrawers, MissionFields, VehicleFields, type Drawer } from './Configuration'
import { HorizonView } from './HorizonView'
import { MapView, type Sector } from './MapView'
import { Rankings, SiteAnalysis } from './Results'
import mark from './assets/lunarsight.svg'
import demoAnalysis from './data/demo.json'

type View = 'map' | 'horizon' | 'rankings'
type Records = Record<string, Candidate>
const apiUrl = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.trim()
// The backend accepts independent mast and antenna heights; set 'false' only for a backend that does not.
const independentAntenna = import.meta.env.VITE_INDEPENDENT_ANTENNA !== 'false'
const emptyCatalog: SiteCatalog = { sites: [], toleranceM: 0 }

const fixtures = demoAnalysis.map(readAnalysis)
const demoSites = fixtures.filter(candidate => candidate.vehicle.solar_panel_mast_height_m === 2).map(candidateSite)
const fullSector = { start: 0, width: 360 }

function findDemo(site: Site, settings: Settings) {
  if (settingsKey({ ...settings, vehicle: defaultSettings.vehicle }) !== settingsKey(defaultSettings)
    || settings.vehicle.antenna_height_m !== defaultSettings.vehicle.antenna_height_m) return undefined
  return fixtures.find(candidate => sameSite(candidate.location, site)
    && candidate.vehicle.solar_panel_mast_height_m === settings.vehicle.solar_panel_mast_height_m)
}

const navigation = [
  { view: 'map', label: 'Lunar Map', detail: 'Explore & select' },
  { view: 'horizon', label: 'Horizon Analysis', detail: 'Simulate conditions' },
  { view: 'rankings', label: 'Site Rankings', detail: 'Compare & decide' },
] as const

function NavIcon({ view }: { view: View }) {
  return <svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.65" strokeLinecap="round" strokeLinejoin="round">
    {view === 'map' && <><path d="M19 10c0 5-7 10-7 10S5 15 5 10a7 7 0 1 1 14 0Z"/><circle cx="12" cy="10" r="2.6"/></>}
    {view === 'horizon' && <><path d="m3 18 6-10 4 6 3-4 5 8H3Z"/><path d="m7 12 2 2 2-2"/></>}
    {view === 'rankings' && <><path d="M9 6h12M9 12h12M9 18h12"/><path d="m3 5 1-1v4m-1 3h2l-2 3h2m-2 4h2"/></>}
  </svg>
}

function Header({ view, goTo, demo, toggleDemo }: { view: View; goTo: (view: View) => void; demo: boolean; toggleDemo: () => void }) {
  return <header className="app-header">
    <button className="brand" onClick={() => goTo('map')} aria-label="LunarSight home"><img src={mark} alt=""/><span>LunarSight</span></button>
    <div className="nav-alignment"><nav className="top-nav" aria-label="Main navigation">
      {navigation.map(item => <button key={item.view} aria-current={view === item.view ? 'page' : undefined} onClick={() => goTo(item.view)}>
        <NavIcon view={item.view} /><strong>{item.label}</strong><small>{item.detail}</small>
      </button>)}
    </nav></div>
    <div className="header-actions"><button className="demo-toggle" onClick={toggleDemo}>{demo ? 'Exit demo' : 'Explore demo'}</button></div>
  </header>
}

const emptyDemo = 'Demo data is available for two waypoints over 14 days starting 2030-11-20 12:00 UTC. Use hourly samples, the default constraints, and a 2 m or 6 m mast.'

export function App() {
  const [view, setView] = useState<View>('map')
  const [site, setSite] = useState<Site>(initialSite)
  // Supported sites come from the backend's GET /sites, so their coordinates always match its terrain data.
  const [catalog, setCatalog] = useState<SiteCatalog>(emptyCatalog)
  const [catalogError, setCatalogError] = useState('')
  const configuredSites = catalog.sites
  const [settings, setSettings] = useState(defaultSettings)
  const [demo, setDemo] = useState(false)
  const [detailOpen, setDetailOpen] = useState(false)
  const [drawer, setDrawer] = useState<Drawer | null>(null)
  const [pinned, setPinned] = useState(false)
  const [sector, setSector] = useState<Sector>({ start: 315, width: 45 })
  const [full, setFull] = useState(true)
  const [index, setIndex] = useState(0)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [analyses, setAnalyses] = useState<Records>({})
  const [baselines, setBaselines] = useState<Record<string, string>>({})
  const [imported, setImported] = useState<{ key: string; candidate: Candidate }>()
  const activeOperation = useRef<AbortController | null>(null)
  const savedState = useRef<{ site: Site; settings: Settings; view: View; index: number } | null>(null)

  useEffect(() => () => activeOperation.current?.abort(), [])

  useEffect(() => {
    if (!apiUrl) return
    const controller = new AbortController()
    requestSites(apiUrl, controller.signal).then(loaded => {
      setCatalog(loaded)
      // Start on a real supported site instead of the placeholder waypoint.
      if (loaded.sites.length) setSite(current => sameSite(current, initialSite) ? loaded.sites[0] : current)
    }).catch(error => {
      if (!controller.signal.aborted) {
        setCatalogError(`The supported site list could not be loaded. ${error instanceof Error ? error.message : ''}`.trim())
      }
    })
    return () => controller.abort()
  }, [])

  const sites = demo ? demoSites : configuredSites
  const knownSite = sites.find(item => sameSite(item, site))
  const key = analysisKey(site, settings)
  const importedCandidate = imported?.key === key ? imported.candidate : undefined
  const candidate = demo ? findDemo(site, settings) : importedCandidate ?? analyses[key]
  const baseline = !candidate ? undefined : demo
    ? (settings.vehicle.solar_panel_mast_height_m === 6 ? findDemo(site, { ...settings, vehicle: defaultSettings.vehicle }) : undefined)
    : importedCandidate ? undefined : analyses[baselines[key]]
  const source = candidate ? demo ? 'Demo data' : importedCandidate ? 'Imported analysis' : 'Backend analysis' : undefined
  const showSidebar = view === 'horizon' || (view === 'rankings' && detailOpen)
  const stale = !demo && !candidate && (Object.values(analyses).some(item => sameSite(item.location, site))
    || (imported && sameSite(imported.candidate.location, site)))
  const unsupported = site.latitude_deg < -89.999 ? 'Polar waypoint selected. Terrain analysis and local azimuth are unavailable this close to the pole.'
    : 'Analysis unavailable at this waypoint. Terrain data is missing and visibility is unknown.'
  const availability = demo ? (knownSite ? 'Demo waypoint selected. Open Horizon Analysis to inspect the illustrative scenario.' : 'Demo terrain is available at the two marked waypoints.')
    : candidate ? 'Analysis loaded for the selected waypoint.' : knownSite && apiUrl ? 'Terrain coverage configured. Open Mission to run the analysis.' : unsupported
  const panelMessage = message || (busy ? 'Running terrain analysis…' : demo && !candidate ? emptyDemo
    : stale ? 'Mission settings changed. Run a fresh analysis.' : catalogError || (source === 'Imported analysis'
      ? 'Loaded from a local file. Review its sources and timestamps.' : ''))

  function cancelOperation() {
    activeOperation.current?.abort()
    activeOperation.current = null
    setBusy(false)
  }

  const changeDrawer = useCallback((next: Drawer | null, pin = false) => {
    setDrawer(next)
    setPinned(next !== null && pin)
  }, [])

  function goTo(next: View) {
    if (next === view) return
    setDetailOpen(false)
    setView(next)
    window.scrollTo(0, 0)
  }

  function select(point: Site) {
    const location = sites.find(item => sameSite(item, point)) ?? point
    if (sameSite(location, site)) return
    cancelOperation()
    setSite(location)
    setIndex(0)
    setMessage('')
  }

  function toggleDemo() {
    cancelOperation()
    setMessage('')
    setDetailOpen(false)
    changeDrawer(null)
    if (!demo) {
      savedState.current = { site, settings, view, index }
      setDemo(true)
      setSite(demoSites[0])
      setSettings(defaultSettings)
      setIndex(168)
      setView('horizon')
    } else {
      setDemo(false)
      const previous = savedState.current
      if (previous) {
        setSite(previous.site)
        setSettings(previous.settings)
        setView(previous.view)
        setIndex(previous.index)
      }
    }
    window.scrollTo(0, 0)
  }

  async function run(point: Site, next: Settings, previousVehicle?: Vehicle) {
    cancelOperation()
    const verifiedSite = sites.find(item => sameSite(item, point))
    const selected = verifiedSite ?? point
    setSite(selected)
    setSettings(next)
    if (!sameSite(site, selected) || next.mission.start_utc !== settings.mission.start_utc
      || next.mission.duration_hours !== settings.mission.duration_hours
      || next.mission.sample_step_seconds !== settings.mission.sample_step_seconds) setIndex(0)
    setView('horizon')
    setDetailOpen(false)
    setMessage('')
    if (demo) {
      if (!findDemo(selected, next)) setMessage(emptyDemo)
      return
    }
    if (!verifiedSite || !apiUrl) {
      setMessage(catalogError || (verifiedSite && !apiUrl ? 'The live analysis service is unavailable.'
        : 'Analysis is unavailable for this waypoint. Select a supported site or load an analysis JSON file.'))
      return
    }

    const controller = new AbortController()
    activeOperation.current = controller
    setBusy(true)
    const runKey = analysisKey(verifiedSite, next)
    try {
      let baseKey: string | undefined
      let baseResult: Candidate | undefined
      if (previousVehicle && previousVehicle.antenna_height_m === next.vehicle.antenna_height_m
        && previousVehicle.solar_panel_mast_height_m !== next.vehicle.solar_panel_mast_height_m) {
        const baseSettings = { ...next, vehicle: previousVehicle }
        baseKey = analysisKey(verifiedSite, baseSettings)
        baseResult = analyses[baseKey]
        if (!baseResult) {
          try { baseResult = await requestAnalysis(apiUrl, { site: verifiedSite, ...baseSettings }, controller.signal, catalog.toleranceM) }
          catch { if (controller.signal.aborted) return }
        }
      }
      const result = await requestAnalysis(apiUrl, { site: verifiedSite, ...next }, controller.signal, catalog.toleranceM)
      if (controller.signal.aborted) return
      const additions: Records = { [runKey]: result }
      if (baseResult && baseKey) {
        additions[baseKey] = baseResult
        setBaselines(values => ({ ...values, [runKey]: baseKey }))
      } else if (baseKey) setMessage('Updated analysis loaded. The baseline analysis is unavailable.')
      setAnalyses(values => ({ ...values, ...additions }))
      setImported(values => values?.key === runKey ? undefined : values)
    } catch (error) {
      if (!controller.signal.aborted) setMessage(error instanceof Error ? error.message : 'Analysis failed. Run the analysis again to retry.')
    } finally {
      if (activeOperation.current === controller) { activeOperation.current = null; setBusy(false) }
    }
  }

  async function compareSites() {
    if (!apiUrl || configuredSites.length < 2) return
    cancelOperation()
    const controller = new AbortController()
    activeOperation.current = controller
    setBusy(true)
    setMessage('')
    try {
      const outcomes = await Promise.allSettled(configuredSites.map(async location => {
        const result = await requestAnalysis(apiUrl, { site: location, ...settings }, controller.signal, catalog.toleranceM)
        return [analysisKey(location, settings), result] as const
      }))
      if (controller.signal.aborted) return
      const analysesLoaded = outcomes.flatMap(outcome => outcome.status === 'fulfilled' ? [outcome.value] : [])
      setAnalyses(values => ({ ...values, ...Object.fromEntries(analysesLoaded) }))
      if (analysesLoaded.length < configuredSites.length) {
        const failure = outcomes.find(outcome => outcome.status === 'rejected')
        const reason = failure?.status === 'rejected' && failure.reason instanceof Error ? ` ${failure.reason.message}` : ''
        setMessage(analysesLoaded.length === 0 ? `No comparison results loaded.${reason}`
          : `${analysesLoaded.length} of ${configuredSites.length} sites returned results.${reason}`)
      }
    } finally {
      if (activeOperation.current === controller) { activeOperation.current = null; setBusy(false) }
    }
  }

  async function loadFile(file: File) {
    cancelOperation()
    const operation = new AbortController()
    activeOperation.current = operation
    try {
      const response = readAnalysis(JSON.parse(await file.text()))
      if (operation.signal.aborted) return
      if (response.location.latitude_deg > -80) throw new Error('Choose an analysis within the south-pole map area, from 90°S to 80°S.')
      const importedSite = candidateSite(response)
      const next = { ...(demo ? (savedState.current?.settings ?? defaultSettings) : settings), vehicle: response.vehicle }
      setImported({ key: analysisKey(importedSite, next), candidate: response })
      setSite(importedSite)
      setSettings(next)
      setIndex(0)
      setDemo(false)
      setMessage('')
    } catch (error) {
      if (!operation.signal.aborted) setMessage(error instanceof SyntaxError ? 'Choose a valid analysis JSON file.'
        : error instanceof Error ? error.message : 'The analysis file could not be loaded.')
    } finally {
      if (activeOperation.current === operation) activeOperation.current = null
    }
  }

  const rows = sites.map(location => ({ site: location, candidate: demo ? findDemo(location, settings) : analyses[analysisKey(location, settings)] }))
  const rankingSummary = demo || configuredSites.length ? `${formatUtc(settings.mission.start_utc)} · ${settings.mission.duration_hours / 24} days · ${settings.mission.sample_step_seconds / 3600} h steps · ${settings.vehicle.solar_panel_mast_height_m} m mast`
    : 'Compare candidates under a shared mission window and vehicle configuration.'
  const title = view === 'map' ? 'Lunar Map' : view === 'horizon' ? '360° Lunar Horizon & Mission Analysis' : 'Site Rankings & Comparison'
  const subtitle = view === 'map' ? 'Explore the lunar south pole and select a landing waypoint.' : view === 'horizon'
    ? 'Local terrain skyline and time-dependent Sun and Earth trajectories.' : 'Compare solar access, Earth visibility, and mission constraints.'

  return <div className="app" data-sidebar={showSidebar}>
    <Header view={view} goTo={goTo} demo={demo} toggleDemo={toggleDemo} />
    <div className="workspace">
      <main className="main-panel panel" id="main-content">
        <div className="content-heading">
          <div><h1>{title}</h1><p>{subtitle}</p></div>
          {(view !== 'rankings' || detailOpen) && <div className="waypoint-tag"><strong>{site.name}</strong><span>{coordinates(site)}</span></div>}
        </div>
        {demo && <div className="demo-notice" role="status"><strong>Illustrative demo</strong><span>Terrain profiles, trajectories, and mission results are synthetic.</span></div>}
        <div hidden={view !== 'map'}><MapView site={site} sites={sites} onSelect={select} onInspect={() => goTo('horizon')}
          onCoordinates={() => {
            changeDrawer('mission', true)
            requestAnimationFrame(() => document.getElementById('mission-title')?.focus())
          }} availability={catalogError || availability} /></div>
        {view === 'horizon' && <HorizonView key={`${key}/${source ?? ''}`} candidate={candidate} baseline={baseline} index={index} onSeek={setIndex}
          full={full} onFull={() => setFull(true)} onSector={() => setFull(false)} sector={sector} onSectorLimits={setSector}
          onLoad={loadFile} message={panelMessage} />}
        {view === 'rankings' && <Rankings rows={rows} active={detailOpen ? site : undefined} onSelect={row => {
          select(row.site)
          if (row.candidate && !demo) setImported(values => values?.key === analysisKey(row.site, settings) ? undefined : values)
          setDetailOpen(true)
        }}
          compare={!demo && apiUrl && configuredSites.length >= 2 ? compareSites : undefined} busy={busy}
          summary={rankingSummary} message={panelMessage} />}
      </main>
      {showSidebar && <SiteAnalysis site={site} candidate={view === 'rankings' ? rows.find(row => sameSite(row.site, site))?.candidate : candidate}
        baseline={baseline} sector={full ? fullSector : sector} source={source}
        onClose={view === 'rankings' ? () => setDetailOpen(false) : undefined}
        onInspect={view === 'rankings' ? () => goTo('horizon') : undefined} />}
    </div>
    <EdgeDrawers open={drawer} pinned={pinned} onChange={changeDrawer}
      mission={<MissionFields key={settingsKey(settings)} site={site} sites={sites} settings={settings} busy={busy} onSelect={select} onRun={run} />}
      vehicle={<VehicleFields key={`${settings.vehicle.solar_panel_mast_height_m}/${settings.vehicle.antenna_height_m}`} vehicle={settings.vehicle}
        independentAntenna={!demo && independentAntenna} busy={busy} demo={demo} onApply={vehicle => run(site, { ...settings, vehicle }, settings.vehicle)} />} />
  </div>
}
