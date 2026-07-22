import { NavLink, Outlet } from 'react-router'
import { useQuery } from '@tanstack/react-query'
import { get } from '../api/client'
import type { Health } from '../api/types'
import './AppShell.css'

const NAV = [
  { to: '/', label: 'Overview', end: true },
  { to: '/heatmaps', label: 'Heatmaps' },
  { to: '/settings', label: 'Settings' },
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
    <div className="badge" title={`${data.matches} matches, ${data.parsed} parsed`}>
      <span className={`dot ${broken ? 'bad' : stale ? 'warn' : 'ok'}`} />
      <span className="num">{data.parsed}</span>
      <span className="faint">/{data.matches}</span>
      {data.queuePending > 0 && <span className="faint">· {data.queuePending} queued</span>}
      {broken && <span className="bad">· check ingest</span>}
    </div>
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
            {n.label}
          </NavLink>
        ))}
        <div className="spacer" />
        <IngestBadge />
      </nav>
      <main className="content">
        <Outlet />
      </main>
    </div>
  )
}
