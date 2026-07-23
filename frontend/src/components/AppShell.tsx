import { useEffect } from 'react'
import { NavLink, Outlet } from 'react-router'
import { useQuery } from '@tanstack/react-query'
import { get } from '../api/client'
import type { Health, PlayerCard } from '../api/types'
import { ago, num } from '../lib/format'
import { playerColour, registerPlayers } from '../lib/players'
import './AppShell.css'

const NAV = [
  { to: '/', label: 'Overview', icon: '⌂', end: true },
  { to: '/matches', label: 'Matches', icon: '≣' },
  { to: '/heatmaps', label: 'Heatmaps', icon: '▦' },
  { to: '/compare', label: 'Compare', icon: '⇄' },
]

function IngestBadge() {
  const { data } = useQuery({
    queryKey: ['health'],
    queryFn: () => get<Health>('/health'),
    refetchInterval: 30_000,
  })
  if (!data) return null

  // Poller lag is the number that matters: PUBG drops match history after ~14
  // days, so lag creeping up is the early warning for permanent loss.
  const lag = data.pollerLagS
  const stale = lag !== null && lag > 900
  const broken = !data.db || !data.storage || data.queueFailed > 0

  return (
    <div className="badge" title={`${data.matches} matches, ${data.parsed} parsed · parser v${data.parserVersion}`}>
      <span className={`dot ${broken ? 'bad' : stale ? 'warn' : 'ok'}`} />
      <span className="num">{data.parsed}</span>
      <span className="faint">/{data.matches}</span>
      {data.queuePending > 0 && <span className="faint">· {data.queuePending} queued</span>}
      {broken && <span className="bad">· check ingest</span>}
    </div>
  )
}

/**
 * The tracked players, in the nav.
 *
 * Three people are the entire point of this dashboard; reaching their pages
 * previously meant finding them in a table first.
 */
function TrackedNav() {
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
    <>
      <div className="nav-sep" />
      {data.map((p) => (
        <NavLink key={p.accountId} to={`/players/${p.accountId}`} className="navlink player">
          <span className="dot-lg" style={{ background: playerColour(p.accountId) }} />
          <span className="nav-name">{p.name}</span>
          <span className="faint nav-sub">{num(p.matches)}</span>
        </NavLink>
      ))}
      <div className="nav-hint faint" title="last poll of the stalest tracked player">
        {data.some((p) => p.consecutivePollFailures > 0) ? (
          <span className="bad">poll failures</span>
        ) : (
          <>polled {ago(data[0]?.lastPolledAt)}</>
        )}
      </div>
    </>
  )
}

export function AppShell() {
  return (
    <div className="shell">
      <nav className="nav">
        <div className="brand">
          PUBG<span className="faint"> dash</span>
        </div>
        {NAV.map((n) => (
          <NavLink key={n.to} to={n.to} end={n.end} className="navlink">
            <span className="nav-icon">{n.icon}</span>
            <span className="nav-name">{n.label}</span>
          </NavLink>
        ))}

        <TrackedNav />

        <div className="spacer" />
        <NavLink to="/settings" className="navlink">
          <span className="nav-icon">⚙</span>
          <span className="nav-name">Settings</span>
        </NavLink>
        <IngestBadge />
      </nav>
      <main className="content">
        <Outlet />
      </main>
    </div>
  )
}
