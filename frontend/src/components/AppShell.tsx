import { useEffect } from 'react'
import { NavLink, Outlet } from 'react-router'
import { useQuery } from '@tanstack/react-query'
import { get } from '../api/client'
import type { Health, PlayerCard } from '../api/types'
import { ago, num } from '../lib/format'
import { playerColour, registerPlayers, useTrackedPlayers } from '../lib/players'
import './AppShell.css'

const NAV = [
  { to: '/', label: 'Overview', end: true },
  { to: '/matches', label: 'Matches' },
  { to: '/heatmaps', label: 'Heatmaps' },
  { to: '/compare', label: 'Compare' },
  { to: '/review', label: 'Review' },
  { to: '/strategy', label: 'Strategy' },
]

function IngestBadge() {
  const { data } = useQuery({
    queryKey: ['health'],
    queryFn: () => get<Health>('/health'),
    refetchInterval: 30_000,
  })
  if (!data) return null

  // **`alerts` decides, not the lag.** `pollerLagS` is min() of the poll ages
  // with never-polled players excluded, so it reports the freshest player: it
  // read 46 s in a live check while one tracked account was nine hours stale.
  // `pubgd doctor` checks max() and NULLs, and puts what it finds here.
  const alerts = data.alerts ?? []
  const broken = !data.db || !data.storage || alerts.length > 0

  // The watchdog cannot report its own death, so the API reports it instead.
  // null means it has never run, which is a reason to look and not a blank.
  const watchdog = data.watchdogAgeS
  const watchdogStale = watchdog === null || watchdog > 1200

  const title = [
    `${data.matches} matches, ${data.parsed} parsed · parser v${data.parserVersion}`,
    ...alerts.map((a) => `${a.kind}: ${a.detail}`),
    watchdogStale
      ? watchdog === null
        ? 'watchdog has never run — enable pubgd-doctor.timer'
        : `watchdog last ran ${Math.round(watchdog / 60)} min ago`
      : null,
  ]
    .filter(Boolean)
    .join('\n')

  return (
    <div className="badge" title={title}>
      <span className={`dot ${broken ? 'bad' : watchdogStale ? 'warn' : 'ok'}`} />
      <span className="num">{data.parsed}</span>
      <span className="faint">/{data.matches}</span>
      {data.queuePending > 0 && <span className="faint">· {data.queuePending} queued</span>}
      {/* Named, not "check ingest". An alert that does not say what is wrong
          sends the reader to look in the wrong place. */}
      {alerts.length > 0 && <span className="bad">· {alerts[0]!.kind.replace(/_/g, ' ')}</span>}
      {alerts.length === 0 && watchdogStale && <span className="warn">· watchdog</span>}
    </div>
  )
}

/**
 * The squad strip: the tracked players, always one glance away.
 *
 * Three people are the entire point of this dashboard. In the old sidebar
 * they were nav entries; here they are a persistent strip under the command
 * bar, on every page.
 */
function SquadStrip() {
  const { data } = useQuery({
    queryKey: ['players', 'tracked'],
    queryFn: () => get<PlayerCard[]>('/players', { tracked: true }),
    staleTime: 5 * 60_000,
  })

  useEffect(() => {
    if (data) registerPlayers(data.map((p) => p.accountId))
  }, [data])

  if (!data?.length) return null
  return (
    <div className="squadstrip">
      {data.map((p) => (
        <NavLink key={p.accountId} to={`/players/${p.accountId}`} className="sqchip">
          <span className="sq-dot" style={{ background: playerColour(p.accountId) }} />
          <span className="sq-name">{p.name}</span>
          <span className="sq-sub faint num">{num(p.matches)} drops</span>
        </NavLink>
      ))}
      <div className="sq-hint faint" title="last poll of the stalest tracked player">
        {data.some((p) => p.consecutivePollFailures > 0) ? (
          <span className="bad">poll failures</span>
        ) : (
          <>polled {ago(data[0]?.lastPolledAt)}</>
        )}
      </div>
    </div>
  )
}

export function AppShell() {
  /**
   * Subscribed here, above the `<Outlet />`, deliberately.
   *
   * Identity colours are read during render all over the app — the nav, the
   * match feed's kill chips, the scoreboard swatches, the heatmap panels —
   * but the roster is registered from an effect, so the render that first
   * needs a colour always precedes the registration. Re-rendering the shell
   * re-renders the routed page with it, so one subscription fixes every
   * surface rather than each one having to remember.
   */
  useTrackedPlayers()

  return (
    <div className="shell">
      <header className="cmdbar">
        <NavLink to="/" className="brand">
          PUBG<em>DASH</em>
        </NavLink>
        <nav className="cmdnav">
          {NAV.map((n) => (
            <NavLink key={n.to} to={n.to} end={n.end} className="cmdlink">
              {n.label}
            </NavLink>
          ))}
        </nav>
        <span className="spacer" />
        <IngestBadge />
        <NavLink to="/settings" className="cmdgear" title="Settings">
          ⚙
        </NavLink>
      </header>
      <SquadStrip />
      <main className="content">
        <Outlet />
      </main>
    </div>
  )
}
