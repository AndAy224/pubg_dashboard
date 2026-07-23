import { describe, expect, it } from 'vitest'
import {
  decodeBundle,
  FLAG_ALIVE,
  FLAG_DBNO,
  FLAG_DRIVING,
  FLAG_IN_VEHICLE,
  FLAG_PARACHUTING,
} from './replayBundle'

/**
 * The decoder against **real** bundles.
 *
 * The synthetic tests in `replayBundle.test.ts` pin the alignment behaviour
 * deterministically, but this project's standing rule is that a fixture you
 * wrote yourself is not evidence about a wire format — the `allWeaponStats`
 * bug had a passing unit test the whole time, written from the same invented
 * field names as the code.
 *
 * So these decode bundles the running API actually serves. They mirror the
 * backend's convention exactly (`tests/test_api.py`): reach the service, and
 * **skip cleanly when it is absent**, so a source-only checkout stays green
 * and CI without a deployment costs nothing.
 *
 * Point them elsewhere with `PUBGD_API_BASE`.
 */
// Reached through `globalThis` rather than a bare `process` so the app's
// tsconfig keeps `types: ["vite/client"]` and nothing in `src/` can quietly
// start depending on Node globals that do not exist in the browser.
const BASE =
  (globalThis as { process?: { env?: Record<string, string | undefined> } }).process?.env
    ?.PUBGD_API_BASE ?? 'http://127.0.0.1:8000'
const SAMPLE = 8

async function apiReachable(): Promise<boolean> {
  try {
    const r = await fetch(`${BASE}/api/health`, { signal: AbortSignal.timeout(2000) })
    return r.ok
  } catch {
    return false
  }
}

async function matchIds(limit: number): Promise<string[]> {
  const r = await fetch(`${BASE}/api/matches?limit=${limit}&trackedOnly=false`)
  const rows = (await r.json()) as { matchId: string; hasReplay: boolean }[]
  return rows.filter((m) => m.hasReplay).map((m) => m.matchId)
}

describe('real replay bundles', () => {
  it('decodes every sampled bundle', async ({ skip }) => {
    if (!(await apiReachable())) skip('no API reachable; start pubgd-api or set PUBGD_API_BASE')

    const ids = await matchIds(SAMPLE)
    expect(ids.length, 'no parsed matches with replay bundles').toBeGreaterThan(0)

    for (const id of ids) {
      const r = await fetch(`${BASE}/api/matches/${id}/replay`)
      expect(r.status, id).toBe(200)
      // fetch transparently decodes Content-Encoding: gzip, so this is
      // already MessagePack. Gunzipping again would be wrong.
      const bundle = decodeBundle(await r.arrayBuffer())

      expect(bundle.matchId, id).toBe(id)
      expect(bundle.le, id).toBe(true)
      expect(bundle.tickMs, id).toBeGreaterThan(0)
      expect(bundle.players.length, id).toBeGreaterThan(0)

      // The CSR index must cover the position arrays exactly: one offset per
      // player plus a terminator, ending at the sample count. A short or long
      // offset array silently truncates or over-reads a player's whole track.
      expect(bundle.pos.off.length, id).toBe(bundle.players.length + 1)
      expect(bundle.pos.off[bundle.pos.off.length - 1], id).toBe(bundle.pos.n)
      for (const arr of [bundle.pos.t, bundle.pos.x, bundle.pos.y]) {
        expect(arr.length, id).toBe(bundle.pos.n)
      }
      expect(bundle.pos.hp.length, id).toBe(bundle.pos.n)
    }
  })

  it('produces coordinates inside the world and monotonic per-player time', async ({
    skip,
  }) => {
    if (!(await apiReachable())) skip('no API reachable')

    const [id] = await matchIds(1)
    if (!id) skip('no parsed match')
    const bundle = decodeBundle(await (await fetch(`${BASE}/api/matches/${id}/replay`)).arrayBuffer())

    // Quantised positions fill the Uint16 range by construction; a misread
    // section would still be "in range", so the real signal is the time
    // cursors, which are only monotonic if the bytes were read correctly.
    let regressions = 0
    for (let p = 0; p < bundle.pos.off.length - 1; p++) {
      const start = bundle.pos.off[p]!
      const end = bundle.pos.off[p + 1]!
      for (let i = start + 1; i < end; i++) {
        if (bundle.pos.t[i]! < bundle.pos.t[i - 1]!) regressions++
      }
    }
    expect(regressions, 'per-player tick cursors must never go backwards').toBe(0)

    // Health is a percentage; anything above 100 means the byte stream was
    // read at the wrong offset.
    expect(Math.max(...bundle.pos.hp)).toBeLessThanOrEqual(100)
  })

  /**
   * The three health/liveness invariants the renderer draws from. All of them
   * were violable before parser version 5, and each failed *plausibly*:
   * knocked players simply never appeared, and a naive fix would have left
   * corpses on the map instead.
   */
  it('resolves knocked, alive and dead so the renderer does not have to', async ({
    skip,
  }) => {
    if (!(await apiReachable())) skip('no API reachable')

    const ids = await matchIds(SAMPLE)
    if (ids.length === 0) skip('no parsed matches')

    let knocked = 0
    let partialHealth = 0
    for (const id of ids) {
      const r = await fetch(`${BASE}/api/matches/${id}/replay`)
      const bundle = decodeBundle(await r.arrayBuffer())
      const { flags, hp, n } = bundle.pos

      for (let i = 0; i < n; i++) {
        // A knocked player is still in the match. The inverse — DBNO without
        // ALIVE — is the ghost corpse: 51% of kill victims are flagged
        // `isDBNO` at the instant they die, so any reader combining the bits
        // itself would strand half the lobby on the map permanently.
        if (flags[i]! & FLAG_DBNO) {
          knocked++
          expect(flags[i]! & FLAG_ALIVE, `${id} sample ${i} knocked but not alive`).toBeTruthy()
        }
        if (hp[i]! > 0 && hp[i]! < 100) partialHealth++
      }

      // Everyone the kill feed says died must actually leave the map. Their
      // last sample is the death snapshot, and it must not read as alive.
      for (const e of bundle.events) {
        if (e.k !== 'kill') continue
        const p = e.v as number
        const end = bundle.pos.off[p + 1]
        const start = bundle.pos.off[p]
        if (end === undefined || start === undefined || end === start) continue
        expect(
          flags[end - 1]! & FLAG_ALIVE,
          `${id} player ${p} died but their last sample still reads alive`,
        ).toBeFalsy()
      }
    }

    // Knocks exist at all. They were parsed the whole time and thrown away by
    // the alive test, so "no knocked samples" is the regression to catch.
    expect(knocked, 'knocked samples across the sample of matches').toBeGreaterThan(0)

    // And health is a real gradient, not a dead 0/100 switch — which is what a
    // misread section, or dropping the pre-damage correction, would look like.
    expect(partialHealth, 'samples at partial health').toBeGreaterThan(0)
  })

  /**
   * The whole lobby rides the aircraft at match start, so `FLAG_IN_VEHICLE` is
   * set for everyone at once. If the steering-wheel marker ever keys on it
   * again, this is what catches it.
   */
  it('does not call the match-start aircraft a driven vehicle', async ({ skip }) => {
    if (!(await apiReachable())) skip('no API reachable')

    const ids = await matchIds(SAMPLE)
    if (ids.length === 0) skip('no parsed matches')

    let driving = 0
    let planePhaseInVehicle = 0
    let planePhaseDriving = 0
    for (const id of ids) {
      const r = await fetch(`${BASE}/api/matches/${id}/replay`)
      const { flags, n } = decodeBundle(await r.arrayBuffer()).pos
      for (let i = 0; i < n; i++) {
        const f = flags[i]!
        if (f & FLAG_DRIVING) {
          driving++
          // Driving is a strict subset of being in a vehicle.
          expect(f & FLAG_IN_VEHICLE, `${id} sample ${i} driving but not in a vehicle`).toBeTruthy()
        }
        if (f & FLAG_PARACHUTING) {
          if (f & FLAG_IN_VEHICLE) planePhaseInVehicle++
          if (f & FLAG_DRIVING) planePhaseDriving++
        }
      }
    }

    // Cars do get driven before `isGame` reaches 1 — 17 rides in the corpus —
    // so this is not zero, and asserting zero would be asserting a bug. What
    // must hold is that it stays a rounding error against everyone sitting in
    // the plane.
    expect(planePhaseInVehicle, 'plane-phase in-vehicle samples').toBeGreaterThan(0)
    expect(
      planePhaseDriving / planePhaseInVehicle,
      'share of plane-phase in-vehicle samples flagged as driving',
    ).toBeLessThan(0.05)
    expect(driving, 'driving samples').toBeGreaterThan(0)
  })

  it('agrees with the match API on the kill count', async ({ skip }) => {
    if (!(await apiReachable())) skip('no API reachable')

    const [id] = await matchIds(1)
    if (!id) skip('no parsed match')

    const bundle = decodeBundle(await (await fetch(`${BASE}/api/matches/${id}/replay`)).arrayBuffer())
    const kills = (await (await fetch(`${BASE}/api/matches/${id}/kills`)).json()) as unknown[]

    // The bundle and kill_events are separate outputs of the same parse, so
    // disagreement means one of them is being read wrong.
    expect(bundle.events.filter((e) => e.k === 'kill').length).toBe(kills.length)
  })
})
