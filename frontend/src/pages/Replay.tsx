import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router'
import { ApiError, get, getBytes } from '../api/client'
import type { MatchDetail, PlayerCard, TileInfo } from '../api/types'
import { decodeBundle, dictName, NULL_PLAYER } from '../lib/replayBundle'
import type { ReplayBundle } from '../lib/replayBundle'
import { duration, gameMode, weaponName } from '../lib/format'
import { hex, teamColour, BOT_COLOUR } from '../lib/palette'
import { playerColour, registerPlayers } from '../lib/players'
import { ReplayCanvas } from '../replay/ReplayCanvas'
import { Timeline } from '../replay/Timeline'
import { InventoryPanel } from '../replay/Inventory'
import type { Renderer } from '../replay/engine/Renderer'
import {
  ALIVE,
  KNOCKED,
  getHealthSnapshot,
  getSnapshot,
  subscribe,
  subscribeHealth,
} from '../replay/store'
import './Replay.css'

const SPEEDS = [1, 2, 4, 8, 20]

export function Replay() {
  const { matchId = '' } = useParams()
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const rendererRef = useRef<Renderer | null>(null)
  const [ready, setReady] = useState(false)
  const [follow, setFollow] = useState<number | null>(null)
  const [renderError, setRenderError] = useState<string | null>(null)

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

  const tracked = useMemo(() => {
    const ids = (players.data ?? []).map((p) => p.accountId)
    // Registered during render rather than in an effect. This route mounts
    // outside `AppShell`, which is what registers the palette everywhere else,
    // and child effects run before parent effects — so `ReplayCanvas` would
    // build its dots before the identity colours existed and tint the tracked
    // players neutral grey.
    registerPlayers(ids)
    return new Set(ids)
  }, [players.data])

  const bundle = bundleQuery.data
  const info = bundle ? tiles.data?.[bundle.mapName] : undefined

  // `?t=` seconds and `?follow=` account id, so a kill-feed row on the match
  // page can link straight into the moment it describes.
  const seekTo = params.get('t')
  const followParam = params.get('follow')

  const onReady = useCallback(
    (r: Renderer) => {
      rendererRef.current = r
      if (seekTo) {
        const seconds = Number(seekTo)
        // Land a couple of seconds early: arriving exactly on the kill means
        // arriving after the fight that produced it.
        if (Number.isFinite(seconds)) r.seek(Math.max(0, (seconds - 3) * 1000))
      }
      if (followParam && bundle) {
        const idx = bundle.players.findIndex((p) => p.a === followParam)
        if (idx >= 0) {
          r.followPlayer(idx)
          setFollow(idx)
        }
      }
      setReady(true)
    },
    [seekTo, followParam, bundle],
  )

  const onFollow = useCallback((index: number | null) => {
    setFollow(index)
    rendererRef.current?.followPlayer(index)
  }, [])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.code === 'Escape') navigate(`/matches/${matchId}`)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [navigate, matchId])

  if (bundleQuery.isError) {
    // Distinguish "the server has no bundle" from "we could not read the one
    // it sent". Reporting both as "not parsed yet" hid a decoder bug that
    // broke every replay in the archive: the message named a cause that was
    // provably false, so it read as a known limitation rather than a defect.
    const err = bundleQuery.error
    const missing = err instanceof ApiError && (err.status === 404 || err.status === 409)
    return (
      <div className="replay-error">
        {missing ? (
          <p>No replay bundle for this match — it has not been parsed yet.</p>
        ) : (
          <>
            <p>The replay bundle could not be read.</p>
            <p className="faint small">
              The server returned it, so this is a decoding fault, not missing
              data: {err instanceof Error ? err.message : String(err)}
            </p>
          </>
        )}
        <Link to={`/matches/${matchId}`}>back to the match</Link>
      </div>
    )
  }
  if (!bundle) return <div className="replay-error">loading replay…</div>
  if (!info) {
    // A bundle with no tiles for its map renders as dots on a void, which
    // looks like a broken replay rather than a missing asset.
    return (
      <div className="replay-error">
        <p>No map tiles for {bundle.mapName}.</p>
        <p className="faint small">
          Run <code>uv run scripts/fetch_map_assets.py</code> to build them.
        </p>
        <Link to={`/matches/${matchId}`}>back to the match</Link>
      </div>
    )
  }

  return (
    <div className="replay">
      <div className="stage">
        <ReplayCanvas
          bundle={bundle}
          sourcePx={info.sourcePx}
          tilePx={info.tilePx}
          imageScale={info.imageScale}
          maxZoom={info.maxZoom}
          tracked={tracked}
          onReady={onReady}
          onError={setRenderError}
        />
        <TopBar match={match.data} bundle={bundle} />

        {/* The loadout lives on the canvas, beside the player it describes,
            rather than in the rail. In the rail it pushed the team list down
            the moment you selected anyone — so the one action that makes you
            want to switch players was also the one that made switching hard. */}
        {ready && follow !== null && (
          <LoadoutOverlay
            bundle={bundle}
            playerIndex={follow}
            onClose={() => onFollow(null)}
          />
        )}

        {renderError && (
          <div className="render-error">
            <strong>The map could not be drawn.</strong>
            <span className="faint small">{renderError}</span>
          </div>
        )}

        {ready && (
          <Controls
            renderer={rendererRef}
            bundle={bundle}
            tracked={tracked}
          />
        )}
      </div>
      <aside className="rail">
        {ready && <KillFeed bundle={bundle} renderer={rendererRef} tracked={tracked} />}
        <TeamList bundle={bundle} tracked={tracked} follow={follow} onFollow={onFollow} />
      </aside>
    </div>
  )
}

function useReplayState() {
  return useSyncExternalStore(subscribe, getSnapshot, getSnapshot)
}

/** Notified only when a health value actually changed, not on every tick. */
function useHealth() {
  return useSyncExternalStore(subscribeHealth, getHealthSnapshot, getHealthSnapshot)
}

/**
 * A health bar, matching the ring on the map's three severity stops.
 *
 * Drawn at full health too, unlike the ring: here an absent bar already means
 * the player is out, so hiding it at 100 would make "fine" and "dead" identical.
 */
function Health({ hp, status }: { hp: number; status: number }) {
  if (status === KNOCKED) return <span className="hp hp-knocked">knocked</span>
  if (status !== ALIVE) return null
  const tone = hp > 60 ? 'ok' : hp > 25 ? 'warn' : 'bad'
  return (
    <span className={`hp hp-${tone}`} title={`${hp} health`}>
      <span className="hp-bar">
        <span className="hp-fill" style={{ width: `${hp}%` }} />
      </span>
      <span className="hp-num num">{hp}</span>
    </span>
  )
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

/**
 * The followed player's loadout, as a card on the canvas.
 *
 * Subscribes to the store itself so the playhead does not re-render the whole
 * page at 10 Hz — the same reason every other panel does.
 */
function LoadoutOverlay({
  bundle,
  playerIndex,
  onClose,
}: {
  bundle: ReplayBundle
  playerIndex: number
  onClose: () => void
}) {
  const s = useReplayState()
  const health = useHealth()
  const player = bundle.players[playerIndex]
  return (
    <div className="loadout">
      <div className="loadout-head">
        <span className="dot-team" style={{ background: hex(teamColour(player?.t ?? 0)) }} />
        <strong>{player?.n}</strong>
        <span className="faint small">team {player?.t}</span>
        <Health
          hp={health.hp[playerIndex] ?? 0}
          status={health.status[playerIndex] ?? 0}
        />
        <div className="spacer" />
        <button className="loadout-close" onClick={onClose} title="stop following (Esc)">
          ✕
        </button>
      </div>
      <InventoryPanel bundle={bundle} playerIndex={playerIndex} nowMs={s.nowMs} />
    </div>
  )
}

function Controls({
  renderer,
  bundle,
  tracked,
}: {
  renderer: React.RefObject<Renderer | null>
  bundle: ReplayBundle
  tracked: Set<string>
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
      {/* The match strip: alive-count curve, kill ticks and phase boundaries,
          so the fights are findable instead of hidden in a flat scrubber. */}
      <Timeline
        bundle={bundle}
        nowMs={s.nowMs}
        tracked={tracked}
        onSeek={(ms) => renderer.current?.seek(ms)}
      />
      <div className="control-row">
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
    </div>
  )
}

/**
 * Kills, knocks and revives interleaved.
 *
 * Knocks and revives were already in the bundle and never rendered — in squad
 * modes a knock is most of the story, and a feed that only shows the finishing
 * blow reads as if fights resolve instantly.
 */
function KillFeed({
  bundle,
  renderer,
  tracked,
}: {
  bundle: ReplayBundle
  renderer: React.RefObject<Renderer | null>
  tracked: Set<string>
}) {
  const s = useReplayState()
  const tick = s.nowMs / bundle.tickMs
  const rows = bundle.events
    .filter((e) => (e.k === 'kill' || e.k === 'knock' || e.k === 'revive') && e.t <= tick)
    .slice(-18)
    .reverse()

  return (
    <div className="panel panel-feed">
      <h3>Kill feed</h3>
      <div className="feed scroll">
        {rows.map((e, i) => {
          const victim = bundle.players[e.v as number]
          const killer = (e.p as number) === NULL_PLAYER ? null : bundle.players[e.p as number]
          const ms = e.t * bundle.tickMs
          const involved =
            (killer !== null && killer !== undefined && tracked.has(killer.a)) ||
            (victim !== undefined && tracked.has(victim.a))
          return (
            <button
              className={`feed-row kind-${e.k}${involved ? ' tracked' : ''}`}
              key={`${e.t}-${i}`}
              onClick={() => renderer.current?.seek(Math.max(0, ms - 3000))}
              title="jump here"
            >
              <span className="faint num">{duration(ms / 1000)}</span>
              <span style={{ color: killer ? hex(teamColour(killer.t)) : undefined }}>
                {killer?.n ?? 'zone'}
              </span>
              <span className="faint">
                {e.k === 'knock' ? 'knocked' : e.k === 'revive' ? 'revived' : ''}
                {e.k === 'kill' &&
                  weaponName(dictName(bundle.dicts, 'weapons', e.w as number))}
              </span>
              <span style={{ color: victim?.b ? hex(BOT_COLOUR) : undefined }}>{victim?.n}</span>
            </button>
          )
        })}
        {rows.length === 0 && <div className="faint">nothing yet</div>}
      </div>
    </div>
  )
}

function TeamList({
  bundle,
  tracked,
  follow,
  onFollow,
}: {
  bundle: ReplayBundle
  tracked: Set<string>
  follow: number | null
  onFollow: (index: number | null) => void
}) {
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

  const click = (i: number) => onFollow(follow === i ? null : i)
  // Its own subscription: this is up to a hundred rows, and the main store
  // notifies ten times a second because the playhead always moves.
  const health = useHealth()

  return (
    <div className="panel panel-teams">
      <h3>Teams ({teams.length})</h3>
      {/* Its own scroll container, so the list keeps its position when the
          loadout appears — the loadout is on the canvas now and nothing above
          this can grow. */}
      <div className="team-list scroll">
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
              {/* Same hue as the dot on the map and the chip in the match
                  feed — that is the whole point of a fixed identity colour. */}
              {tracked.has(m.acct) && (
                <span className="dot-id" style={{ background: playerColour(m.acct) }} />
              )}
              <span className="member-name">{m.name}</span>
              <Health hp={health.hp[m.i] ?? 0} status={health.status[m.i] ?? 0} />
            </button>
          ))}
        </div>
      ))}
      </div>
    </div>
  )
}
