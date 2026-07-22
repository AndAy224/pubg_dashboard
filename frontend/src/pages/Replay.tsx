import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link, useParams } from 'react-router'
import { get, getBytes } from '../api/client'
import type { MatchDetail, PlayerCard, TileInfo } from '../api/types'
import { decodeBundle, dictName, NULL_PLAYER } from '../lib/replayBundle'
import type { ReplayBundle } from '../lib/replayBundle'
import { duration, gameMode, weaponName } from '../lib/format'
import { hex, teamColour, BOT_COLOUR } from '../lib/palette'
import { ReplayCanvas } from '../replay/ReplayCanvas'
import type { Renderer } from '../replay/engine/Renderer'
import { getSnapshot, subscribe } from '../replay/store'
import './Replay.css'

const SPEEDS = [1, 2, 4, 8, 20]

export function Replay() {
  const { matchId = '' } = useParams()
  const rendererRef = useRef<Renderer | null>(null)
  const [ready, setReady] = useState(false)

  const match = useQuery({
    queryKey: ['match', matchId],
    queryFn: () => get<MatchDetail>(`/matches/${matchId}`),
  })
  const tiles = useQuery({ queryKey: ['tiles'], queryFn: () => get<Record<string, TileInfo>>('/tiles/manifest.json') })
  const players = useQuery({ queryKey: ['players', 'tracked'], queryFn: () => get<PlayerCard[]>('/players', { tracked: true }) })

  const bundleQuery = useQuery({
    queryKey: ['replay', matchId],
    queryFn: async () => decodeBundle(await getBytes(`/matches/${matchId}/replay`)),
    staleTime: Infinity, // immutable for a given parser version
  })

  const tracked = useMemo(
    () => new Set((players.data ?? []).map((p) => p.accountId)),
    [players.data],
  )

  const onReady = useCallback((r: Renderer) => {
    rendererRef.current = r
    setReady(true)
  }, [])

  const bundle = bundleQuery.data
  const info = bundle ? tiles.data?.[bundle.mapName] : undefined

  if (bundleQuery.isError) {
    return (
      <div className="replay-error">
        <p>No replay bundle for this match — it has not been parsed yet.</p>
        <Link to={`/matches/${matchId}`}>back to the match</Link>
      </div>
    )
  }
  if (!bundle || !info) return <div className="replay-error">loading replay…</div>

  return (
    <div className="replay">
      <div className="stage">
        <ReplayCanvas
          bundle={bundle}
          sourcePx={info.sourcePx}
          imageScale={info.imageScale}
          maxZoom={info.maxZoom}
          tracked={tracked}
          onReady={onReady}
        />
        <TopBar match={match.data} bundle={bundle} />
        {ready && <Controls renderer={rendererRef} bundle={bundle} />}
      </div>
      <aside className="rail">
        {ready && <KillFeed bundle={bundle} />}
        <TeamList bundle={bundle} tracked={tracked} renderer={rendererRef} />
      </aside>
    </div>
  )
}

function useReplayState() {
  return useSyncExternalStore(subscribe, getSnapshot, getSnapshot)
}

function TopBar({ match, bundle }: { match?: MatchDetail; bundle: ReplayBundle }) {
  const s = useReplayState()
  return (
    <div className="topbar">
      <Link to={`/matches/${bundle.matchId}`} className="back">
        ‹ back
      </Link>
      <strong>{match?.mapDisplay ?? bundle.mapName}</strong>
      <span className="faint">{gameMode(match?.gameMode ?? '')}</span>
      <div className="spacer" />
      <span className="num">{s.alive} alive</span>
      <span className="faint num">
        {duration(s.nowMs / 1000)} / {duration(bundle.durationMs / 1000)}
      </span>
    </div>
  )
}

function Controls({
  renderer,
  bundle,
}: {
  renderer: React.RefObject<Renderer | null>
  bundle: ReplayBundle
}) {
  const s = useReplayState()
  const [, force] = useState(0)

  const setSpeed = (v: number) => {
    if (renderer.current) renderer.current.speed = v
    force((n) => n + 1)
  }
  const toggle = useCallback(() => {
    const r = renderer.current
    if (!r) return
    r.playing = !r.playing
    force((n) => n + 1)
  }, [renderer])

  const seekBy = useCallback(
    (deltaMs: number) => renderer.current?.seek((renderer.current?.nowMs ?? 0) + deltaMs),
    [renderer],
  )

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.code === 'Space') { e.preventDefault(); toggle() }
      else if (e.code === 'ArrowLeft') seekBy(-10_000)
      else if (e.code === 'ArrowRight') seekBy(10_000)
      else if (e.code === 'KeyF') renderer.current?.fit()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [toggle, seekBy, renderer])

  return (
    <div className="controls">
      <button onClick={toggle}>{s.playing ? '❚❚' : '▶'}</button>
      <button onClick={() => seekBy(-10_000)} title="back 10s (←)">-10s</button>
      <button onClick={() => seekBy(10_000)} title="forward 10s (→)">+10s</button>
      <input
        className="scrub"
        type="range"
        min={0}
        max={bundle.durationMs}
        step={100}
        value={s.nowMs}
        onChange={(e) => renderer.current?.seek(Number(e.target.value))}
      />
      {SPEEDS.map((v) => (
        <button key={v} className={s.speed === v ? 'on' : ''} onClick={() => setSpeed(v)}>
          {v}×
        </button>
      ))}
      <button onClick={() => renderer.current?.fit()} title="fit (F)">⤢</button>
    </div>
  )
}

function KillFeed({ bundle }: { bundle: ReplayBundle }) {
  const s = useReplayState()
  const tick = s.nowMs / bundle.tickMs
  const rows = bundle.events
    .filter((e) => e.k === 'kill' && e.t <= tick)
    .slice(-14)
    .reverse()

  return (
    <div className="panel">
      <h3>Kill feed</h3>
      <div className="feed">
        {rows.map((e, i) => {
          const victim = bundle.players[e.v as number]
          const killer = (e.p as number) === NULL_PLAYER ? null : bundle.players[e.p as number]
          return (
            <div className="feed-row" key={`${e.t}-${i}`}>
              <span className="faint num">{duration((e.t * bundle.tickMs) / 1000)}</span>
              <span style={{ color: killer ? hex(teamColour(killer.t)) : undefined }}>
                {killer?.n ?? 'zone'}
              </span>
              <span className="faint">{weaponName(dictName(bundle.dicts, 'weapons', e.w as number))}</span>
              <span style={{ color: victim?.b ? hex(BOT_COLOUR) : undefined }}>{victim?.n}</span>
            </div>
          )
        })}
        {rows.length === 0 && <div className="faint">no kills yet</div>}
      </div>
    </div>
  )
}

function TeamList({
  bundle,
  tracked,
  renderer,
}: {
  bundle: ReplayBundle
  tracked: Set<string>
  renderer: React.RefObject<Renderer | null>
}) {
  const [follow, setFollow] = useState<number | null>(null)
  const teams = useMemo(() => {
    const byTeam = new Map<number, { i: number; name: string; bot: boolean; acct: string }[]>()
    bundle.players.forEach((p, i) => {
      const list = byTeam.get(p.t) ?? []
      list.push({ i, name: p.n, bot: p.b, acct: p.a })
      byTeam.set(p.t, list)
    })
    return [...byTeam.entries()].sort((a, b) => {
      // Teams containing a tracked player first — that is who you came to watch.
      const at = a[1].some((m) => tracked.has(m.acct)) ? 0 : 1
      const bt = b[1].some((m) => tracked.has(m.acct)) ? 0 : 1
      return at - bt || a[0] - b[0]
    })
  }, [bundle.players, tracked])

  const click = (i: number) => {
    const next = follow === i ? null : i
    setFollow(next)
    renderer.current?.followPlayer(next)
  }

  return (
    <div className="panel scroll">
      <h3>Teams ({teams.length})</h3>
      {teams.map(([teamId, members]) => (
        <div key={teamId} className="team">
          <div className="team-head">
            <span className="swatch" style={{ background: hex(teamColour(teamId)) }} />
            team {teamId}
          </div>
          {members.map((m) => (
            <button
              key={m.i}
              className={`member ${follow === m.i ? 'on' : ''} ${m.bot ? 'isbot' : ''}`}
              onClick={() => click(m.i)}
              title="follow"
            >
              {m.name}
              {tracked.has(m.acct) && <span className="tag" style={{ marginLeft: 6 }}>tracked</span>}
            </button>
          ))}
        </div>
      ))}
    </div>
  )
}
