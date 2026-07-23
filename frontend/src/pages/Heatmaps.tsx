import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { get } from '../api/client'
import type { Heatmap, PlayerCard, TileInfo } from '../api/types'
import { HeatmapCanvas } from '../components/HeatmapCanvas'
import { MapView } from '../components/MapView'
import { num } from '../lib/format'
import { playerColour, registerPlayers } from '../lib/players'

const KINDS = [
  { key: 'landing', label: 'landings' },
  { key: 'movement', label: 'movement' },
  { key: 'kill', label: 'kills' },
  { key: 'death', label: 'deaths' },
  { key: 'knock', label: 'knocks' },
  { key: 'care_package', label: 'care pkgs' },
  { key: 'vehicle_destroy', label: 'vehicles' },
]
const MODES = ['squad-fpp', 'duo-fpp', 'solo-fpp', 'squad', 'duo', 'solo']
const SIZE = 660

/**
 * "The tracked players, together" — the three of them summed, and nobody else.
 *
 * Distinct from `''`, which is the precomputed everyone-row and includes the
 * other ~97 people in every lobby. A sentinel rather than an empty value
 * because the query-string builder drops empty parameters, and a dropped
 * filter here would quietly answer with the whole server.
 */
const TRACKED_ALL = 'tracked'

export function Heatmaps() {
  const [kind, setKind] = useState('landing')
  const [mapName, setMapName] = useState('Baltic_Main')
  const [gameMode, setGameMode] = useState('')
  const [matchType, setMatchType] = useState('official')
  const [split, setSplit] = useState(false)

  useEffect(() => {
    document.title = 'Heatmaps · PUBG dashboard'
  }, [])

  const tiles = useQuery({
    queryKey: ['tiles'],
    queryFn: () => get<Record<string, TileInfo>>('/tiles/manifest.json'),
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

  const [accountId, setAccountId] = useState('')
  const info = tiles.data?.[mapName]

  const trackedIds = (players.data ?? []).map((p) => p.accountId)

  // The tracked-players-combined view needs the roster before it can ask for
  // anything. Until the query resolves, `trackedIds` is empty — and an empty
  // account list means "everyone" to both the query builder and the API, so
  // firing early would render the whole server's heat under a label claiming
  // it was three people. Hold the request instead.
  const ready = accountId !== TRACKED_ALL || trackedIds.length > 0

  // Compare mode draws one panel per tracked player with identical filters,
  // which is the only way to answer "where do we each drop" — a single
  // blended map cannot separate three people.
  const panels = split
    ? (players.data ?? []).map((p) => ({
        key: p.accountId,
        accountIds: [p.accountId],
        accountId: p.accountId,
        label: p.name,
      }))
    : [
        {
          key: accountId || 'all',
          accountIds:
            accountId === TRACKED_ALL ? trackedIds : accountId ? [accountId] : [],
          // No identity dot for the combined view — it is three colours, and
          // borrowing one of them would read as that player alone.
          accountId: accountId === TRACKED_ALL ? '' : accountId,
          label:
            accountId === TRACKED_ALL
              ? `tracked players (${trackedIds.length})`
              : accountId
                ? (players.data?.find((p) => p.accountId === accountId)?.name ?? '')
                : 'everyone',
        },
      ]

  return (
    <div className="grid" style={{ gap: 14 }}>
      <h1>Heatmaps</h1>

      <div className="filters">
        <select value={mapName} onChange={(e) => setMapName(e.target.value)}>
          {Object.values(tiles.data ?? {}).map((t) => (
            <option key={t.mapName} value={t.mapName}>{t.display ?? t.mapName}</option>
          ))}
        </select>

        {/* "all" is the API's sentinel for every type — an empty string would
            be dropped by the query-string builder and silently fall back to
            official while this control claimed otherwise. */}
        <select value={matchType} onChange={(e) => setMatchType(e.target.value)}>
          <option value="official">official only</option>
          <option value="all">all match types</option>
          <option value="airoyale">airoyale</option>
          <option value="tutorialatoz">tutorial</option>
        </select>

        <select value={gameMode} onChange={(e) => setGameMode(e.target.value)}>
          <option value="">all modes</option>
          {MODES.map((m) => <option key={m} value={m}>{m}</option>)}
        </select>

        {!split && (
          <select value={accountId} onChange={(e) => setAccountId(e.target.value)}>
            <option value="">everyone</option>
            {/* Only worth offering once there is a roster to sum. With none
                loaded it would resolve to an empty filter, which the API reads
                as "everyone" — the one answer this option must never give. */}
            {trackedIds.length > 0 && (
              <option value={TRACKED_ALL}>tracked players (combined)</option>
            )}
            {players.data?.map((p) => (
              <option key={p.accountId} value={p.accountId}>{p.name}</option>
            ))}
          </select>
        )}

        <button className={split ? 'on' : ''} onClick={() => setSplit((v) => !v)}>
          ⇄ compare players
        </button>
      </div>

      <div className="seg">
        {KINDS.map((k) => (
          <button key={k.key} className={k.key === kind ? 'on' : ''} onClick={() => setKind(k.key)}>
            {k.label}
          </button>
        ))}
      </div>

      <p className="faint small" style={{ margin: 0 }}>
        {matchType === 'official'
          ? 'Official matches only — the same set career stats count.'
          : 'All match types, including airoyale and tutorial.'}{' '}
        Kill and death bins include bots, which career K/D excludes by default.
      </p>

      {!info ? (
        <div className="card empty">
          no tiles for {mapName} — run <code>scripts/fetch_map_assets.py</code>
        </div>
      ) : (
        <div className="heatgrid" style={{ gridTemplateColumns: `repeat(${panels.length}, minmax(0, 1fr))` }}>
          {panels.map((p) => (
            <HeatPanel
              key={p.key}
              info={info}
              mapName={mapName}
              kind={kind}
              accountIds={p.accountIds}
              accountId={p.accountId}
              label={p.label}
              gameMode={gameMode}
              matchType={matchType}
              enabled={ready}
              size={split ? Math.min(SIZE, 1180 / panels.length) : SIZE}
            />
          ))}
        </div>
      )}
    </div>
  )
}

function HeatPanel({
  info,
  mapName,
  kind,
  accountIds,
  accountId,
  label,
  gameMode,
  matchType,
  enabled,
  size,
}: {
  info: TileInfo
  mapName: string
  kind: string
  /** Accounts to sum. Empty means the precomputed everyone row. */
  accountIds: string[]
  /** Whose identity colour to show, if exactly one player is in view. */
  accountId: string
  label: string
  gameMode: string
  matchType: string
  enabled: boolean
  size: number
}) {
  const heat = useQuery({
    // The ids are part of the key, not just `accountId` — otherwise the
    // combined view and a single player could share a cache entry.
    queryKey: ['heatmap', mapName, kind, accountIds.join(','), gameMode, matchType],
    queryFn: () =>
      get<Heatmap>('/heatmap', {
        map: mapName,
        kind,
        // Repeated `accountId=` params; `undefined` when empty, which is the
        // everyone row.
        accountId: accountIds.length > 0 ? accountIds : undefined,
        gameMode: gameMode || undefined,
        matchType,
      }),
    enabled,
  })

  return (
    <div className="grid" style={{ gap: 6 }}>
      <div className="row">
        {accountId && <span className="dot-lg" style={{ background: playerColour(accountId) }} />}
        <strong>{label}</strong>
        <div className="spacer" />
        <span className="faint small">
          {heat.data ? `${num(heat.data.total)} events · peak ${num(heat.data.max)}` : '…'}
        </span>
      </div>
      {/* The heat field goes in the transformed layer: it *is* the terrain,
          so it has to stay glued to the tiles at every zoom. */}
      <MapView info={info} size={size} world={heat.data ? <HeatmapCanvas heatmap={heat.data} /> : null} />
    </div>
  )
}
