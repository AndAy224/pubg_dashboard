import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router'
import { get } from '../api/client'
import type { Health, IngestStatus, PlayerCard } from '../api/types'
import { ago, duration, num } from '../lib/format'

export function Settings() {
  const health = useQuery({ queryKey: ['health'], queryFn: () => get<Health>('/health') })
  const ingest = useQuery({
    queryKey: ['ingest'],
    queryFn: () => get<IngestStatus>('/ingest/status'),
    refetchInterval: 15_000,
  })
  const players = useQuery({
    queryKey: ['players', 'all'],
    queryFn: () => get<PlayerCard[]>('/players', { tracked: true }),
  })

  return (
    <div className="grid" style={{ gap: 20 }}>
      <h1>Settings & ingest</h1>

      <section className="tiles wide">
        <Tile label="Matches" value={num(health.data?.matches)} sub={`${num(health.data?.parsed)} parsed`} />
        <Tile label="Queue" value={num(ingest.data?.queue.filter((q) => q.state === 'pending').reduce((a, b) => a + b.count, 0))} sub="pending" />
        <Tile label="Failed jobs" value={num(health.data?.queueFailed)} />
        <Tile
          label="Poller lag"
          value={health.data?.pollerLagS != null ? duration(health.data.pollerLagS) : '—'}
          sub="PUBG drops history after 14 days"
        />
        <Tile label="Rate limit" value={`${num(ingest.data?.rateLimitPerMin)}/min`} />
        <Tile label="Parser" value={`v${num(health.data?.parserVersion)}`} />
      </section>

      <section className="card">
        <h3 style={{ marginBottom: 10 }}>Tracked players</h3>
        <table>
          <thead>
            <tr><th>Name</th><th>Shard</th><th className="r">Matches</th><th className="r">Last polled</th><th className="r">Failures</th></tr>
          </thead>
          <tbody>
            {players.data?.map((p) => (
              <tr key={p.accountId}>
                <td><Link to={`/players/${p.accountId}`}>{p.name}</Link></td>
                <td className="dim">{p.shard}</td>
                <td className="r num">{p.matches}</td>
                <td className="r dim">{ago(p.lastPolledAt)}</td>
                <td className={`r num ${p.consecutivePollFailures ? 'bad' : 'faint'}`}>
                  {p.consecutivePollFailures}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="card">
        <h3 style={{ marginBottom: 10 }}>Job queue</h3>
        <table>
          <thead><tr><th>Kind</th><th>State</th><th className="r">Count</th></tr></thead>
          <tbody>
            {ingest.data?.queue.map((q) => (
              <tr key={`${q.kind}-${q.state}`}>
                <td>{q.kind}</td>
                <td className={q.state === 'failed' ? 'bad' : 'dim'}>{q.state}</td>
                <td className="r num">{q.count}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {ingest.data?.queue.length === 0 && <div className="empty">queue is empty</div>}
      </section>
    </div>
  )
}

function Tile({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="tile">
      <div className="tile-label">{label}</div>
      <div className="tile-value num">{value}</div>
      {sub && <div className="tile-sub faint">{sub}</div>}
    </div>
  )
}
