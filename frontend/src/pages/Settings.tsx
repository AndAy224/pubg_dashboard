import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router'
import { get, post } from '../api/client'
import type { Health, IngestStatus, PlayerCard } from '../api/types'
import { Tile } from '../components/ui'
import { ago, dateTime, duration, num } from '../lib/format'
import { playerColour, registerPlayers } from '../lib/players'

export function Settings() {
  const qc = useQueryClient()
  const [note, setNote] = useState<string | null>(null)

  useEffect(() => {
    document.title = 'Settings · PUBG dashboard'
  }, [])

  const health = useQuery({ queryKey: ['health'], queryFn: () => get<Health>('/health') })
  const ingest = useQuery({
    queryKey: ['ingest'],
    queryFn: () => get<IngestStatus>('/ingest/status'),
    refetchInterval: 15_000,
  })
  const players = useQuery({
    queryKey: ['players', 'tracked'],
    queryFn: () => get<PlayerCard[]>('/players', { tracked: true }),
  })
  useEffect(() => {
    if (players.data) registerPlayers(players.data.map((p) => p.accountId))
  }, [players.data])

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['ingest'] })
    qc.invalidateQueries({ queryKey: ['health'] })
  }

  const backfill = useMutation({
    mutationFn: (accountId: string) =>
      post<{ queued: boolean }>(`/ingest/backfill/${accountId}`),
    onSuccess: (r, accountId) => {
      const name = players.data?.find((p) => p.accountId === accountId)?.name ?? accountId
      // `queued: false` means an identical job was already live — the normal
      // result of a double click, not a failure.
      setNote(r.queued ? `queued a history sweep for ${name}` : `${name} already has one queued`)
      refresh()
    },
    onError: (e: Error) => setNote(`backfill failed: ${e.message}`),
  })

  const reparse = useMutation({
    mutationFn: (staleOnly: boolean) =>
      post<{ matched: number; queued: number; parserVersion: number }>('/ingest/reparse', {
        staleOnly,
      }),
    onSuccess: (r) => {
      setNote(`queued ${r.queued} of ${r.matched} matches for parser v${r.parserVersion}`)
      refresh()
    },
    onError: (e: Error) => setNote(`reparse failed: ${e.message}`),
  })

  const pending =
    ingest.data?.queue.filter((q) => q.state === 'pending').reduce((a, b) => a + b.count, 0) ?? 0

  return (
    <div className="grid" style={{ gap: 20 }}>
      <h1>Settings &amp; ingest</h1>

      {note && (
        <div className="notice" onClick={() => setNote(null)} role="status">
          {note} <span className="faint">· click to dismiss</span>
        </div>
      )}

      <section className="tiles wide">
        <Tile label="Matches" value={num(health.data?.matches)} sub={`${num(health.data?.parsed)} parsed`} />
        <Tile label="Queue" value={num(pending)} sub="pending" />
        <Tile label="Failed jobs" value={num(health.data?.queueFailed)} />
        <Tile
          label="Poller lag"
          value={health.data?.pollerLagS != null ? duration(health.data.pollerLagS) : '—'}
          sub="PUBG drops history after 14 days"
        />
        <Tile label="Rate limit" value={`${num(ingest.data?.rateLimitPerMin)}/min`} sub="GET /players only" />
        <Tile label="Parser" value={`v${num(health.data?.parserVersion)}`} />
      </section>

      <section className="card">
        <div className="row" style={{ marginBottom: 10 }}>
          <h3>Tracked players</h3>
          <div className="spacer" />
          <span className="faint small">
            a backfill costs one rate-limit token; the matches it finds are free
          </span>
        </div>
        <table>
          <thead>
            <tr>
              <th>Name</th><th>Shard</th><th className="r">Matches</th>
              <th className="r">Last polled</th><th className="r">Failures</th><th />
            </tr>
          </thead>
          <tbody>
            {players.data?.map((p) => (
              <tr key={p.accountId}>
                <td>
                  <span className="row" style={{ gap: 8 }}>
                    <span className="dot-lg" style={{ background: playerColour(p.accountId) }} />
                    <Link to={`/players/${p.accountId}`}>{p.name}</Link>
                  </span>
                </td>
                <td className="dim">{p.shard}</td>
                <td className="r num">{p.matches}</td>
                <td className="r dim">{ago(p.lastPolledAt)}</td>
                <td className={`r num ${p.consecutivePollFailures ? 'bad' : 'faint'}`}>
                  {p.consecutivePollFailures}
                </td>
                <td className="r">
                  <button
                    onClick={() => backfill.mutate(p.accountId)}
                    disabled={backfill.isPending}
                  >
                    backfill
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="card">
        <div className="row" style={{ marginBottom: 10 }}>
          <h3>Reparse</h3>
          <div className="spacer" />
          <button onClick={() => reparse.mutate(true)} disabled={reparse.isPending}>
            reparse stale
          </button>
          <button onClick={() => reparse.mutate(false)} disabled={reparse.isPending}>
            reparse everything
          </button>
        </div>
        <p className="faint small" style={{ margin: 0 }}>
          Reparsing reads raw telemetry back out of object storage and spends no
          API budget — it is what makes a parser fix apply to the whole archive.
          Each parse records what it contributed to the heatmap and the next one
          subtracts that first, so repeating it is safe.
          {ingest.data?.unparsed ? (
            <>
              {' '}
              <strong>{ingest.data.unparsed}</strong> unparsed, oldest{' '}
              {ingest.data.oldestUnparsed ? dateTime(ingest.data.oldestUnparsed) : '—'}.
            </>
          ) : null}
        </p>
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

      <section className="card">
        <h3 style={{ marginBottom: 10 }}>Notes</h3>
        <p className="faint small" style={{ margin: 0 }}>
          There is no authentication on this API. <code>/api/players</code> and{' '}
          <code>/api/ingest</code> mutate state and spend rate-limit budget, and
          the app is on the LAN by explicit decision.
        </p>
      </section>
    </div>
  )
}
