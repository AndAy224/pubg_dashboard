import { useEffect, useState } from 'react'
import { useInfiniteQuery, useQuery } from '@tanstack/react-query'
import { get } from '../api/client'
import type { MapInfo, MatchFeedRow, PlayerCard } from '../api/types'
import { MatchFeed } from '../components/MatchFeed'
import { Skeleton } from '../components/ui'
import { gameMode, num } from '../lib/format'
import { registerPlayers } from '../lib/players'

const PAGE = 25
const MODES = ['squad-fpp', 'duo-fpp', 'solo-fpp', 'squad', 'duo', 'solo']
const TYPES = ['official', 'airoyale', 'tutorialatoz']

/**
 * The full archive.
 *
 * Pagination is keyset on `playedAt` rather than OFFSET — the poller adds
 * matches at the head continuously, and an offset page would repeat or skip
 * rows as it does.
 */
export function Matches() {
  const [mapName, setMapName] = useState('')
  const [mode, setMode] = useState('')
  const [type, setType] = useState('')
  const [accountId, setAccountId] = useState('')
  const [replayOnly, setReplayOnly] = useState(false)

  useEffect(() => {
    document.title = 'Matches · PUBG dashboard'
  }, [])

  const maps = useQuery({
    queryKey: ['maps', 'played'],
    queryFn: () => get<MapInfo[]>('/maps/played'),
    staleTime: 10 * 60_000,
  })
  const players = useQuery({
    queryKey: ['players', 'tracked'],
    queryFn: () => get<PlayerCard[]>('/players', { tracked: true }),
    staleTime: 5 * 60_000,
  })
  useEffect(() => {
    if (players.data) registerPlayers(players.data.map((p) => p.accountId))
  }, [players.data])

  const filters = {
    map: mapName || undefined,
    gameMode: mode || undefined,
    matchType: type || undefined,
    accountId: accountId || undefined,
    hasReplay: replayOnly ? true : undefined,
    // With a player filter the tracked-only semantics would be redundant, but
    // it stays true so the archive never turns into a list of strangers'
    // matches.
    trackedOnly: true,
  }

  const q = useInfiniteQuery({
    queryKey: ['matches', 'browse', filters],
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam }) =>
      get<MatchFeedRow[]>('/matches', { ...filters, limit: PAGE, before: pageParam }),
    // The cursor is the oldest row on the page; a short page means the end.
    getNextPageParam: (last) =>
      last.length < PAGE ? undefined : last[last.length - 1]!.playedAt,
  })

  const rows = q.data?.pages.flat() ?? []

  return (
    <div className="grid" style={{ gap: 16 }}>
      <div className="row">
        <h1>Matches</h1>
        <div className="spacer" />
        <span className="faint small">{num(rows.length)} shown</span>
      </div>

      <div className="filters">
        <label>Map</label>
        <select value={mapName} onChange={(e) => setMapName(e.target.value)}>
          <option value="">all</option>
          {maps.data?.map((m) => (
            <option key={m.mapName} value={m.mapName}>{m.display}</option>
          ))}
        </select>

        <label>Mode</label>
        <select value={mode} onChange={(e) => setMode(e.target.value)}>
          <option value="">all</option>
          {MODES.map((m) => <option key={m} value={m}>{gameMode(m)}</option>)}
        </select>

        <label>Type</label>
        <select value={type} onChange={(e) => setType(e.target.value)}>
          <option value="">all</option>
          {TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
        </select>

        <label>Player</label>
        <select value={accountId} onChange={(e) => setAccountId(e.target.value)}>
          <option value="">anyone tracked</option>
          {players.data?.map((p) => (
            <option key={p.accountId} value={p.accountId}>{p.name}</option>
          ))}
        </select>

        <button className={replayOnly ? 'on' : ''} onClick={() => setReplayOnly((v) => !v)}>
          ▶ replay only
        </button>
      </div>

      <section className="card" style={{ padding: 0 }}>
        {q.isLoading ? (
          <div style={{ padding: 12 }}>
            <Skeleton h={62} /><div style={{ height: 6 }} />
            <Skeleton h={62} /><div style={{ height: 6 }} />
            <Skeleton h={62} />
          </div>
        ) : (
          <MatchFeed rows={rows} emptyLabel="no matches match these filters" />
        )}
      </section>

      {q.hasNextPage && (
        <button onClick={() => q.fetchNextPage()} disabled={q.isFetchingNextPage}>
          {q.isFetchingNextPage ? 'loading…' : 'load more'}
        </button>
      )}
    </div>
  )
}
