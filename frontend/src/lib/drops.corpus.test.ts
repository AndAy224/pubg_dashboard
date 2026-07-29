import { beforeAll, describe, expect, it } from 'vitest'
import type { DropRow, Gazetteer } from '../api/types'
import { clusterDrops, labelCluster, summariseCluster } from './drops'

/**
 * Clustering and labelling against the **real** archive.
 *
 * `drops.test.ts` pins the arithmetic hermetically. This file checks the two
 * things a synthetic fixture cannot: that the API's grain is what the
 * clustering assumes, and that PUBG's own place names actually land on the
 * spots the squad drops at.
 *
 * Mirrors the convention in `replayBundle.corpus.test.ts` and the backend's
 * `tests/test_api.py`: reach the service, and **skip cleanly when it is
 * absent**, so a source-only checkout stays green.
 *
 * Point elsewhere with `PUBGD_API_BASE`.
 */
const BASE =
  (globalThis as { process?: { env?: Record<string, string | undefined> } }).process?.env
    ?.PUBGD_API_BASE ?? 'http://127.0.0.1:8000'

const MAP = 'Baltic_Main'

let drops: DropRow[] | null = null
let gaz: Gazetteer | null = null

async function reachable(): Promise<boolean> {
  try {
    const r = await fetch(`${BASE}/api/health`, { signal: AbortSignal.timeout(2000) })
    return r.ok
  } catch {
    return false
  }
}

beforeAll(async () => {
  if (!(await reachable())) return
  drops = (await (await fetch(`${BASE}/api/strategy/drops?map=${MAP}`)).json()) as DropRow[]
  const r = await fetch(`${BASE}/api/maps/${MAP}/places`)
  gaz = r.ok ? ((await r.json()) as Gazetteer) : null
})

describe.skipIf(!(await reachable()))('drops against the live archive', () => {
  it('returns one row per squad landing, not one per player', () => {
    // The counting bug this grain exists to prevent. The tracked players are
    // always on the same roster, so a per-participant endpoint would report
    // up to 3x the drops and every cluster's n would be inflated.
    expect(drops).not.toBeNull()
    const keys = new Set(drops!.map((d) => `${d.matchId}:${d.teamId}`))
    expect(keys.size).toBe(drops!.length)
  })

  it('has drops carrying more than one player', () => {
    // Proves the previous test is not passing trivially on solo matches.
    expect(drops!.some((d) => d.names.length > 1)).toBe(true)
  })

  it('clusters the archive into a sane number of spots', () => {
    // Measured: 83 Erangel squad drops over ~13 spots. A partition that
    // collapses to 1 or explodes to one-per-drop is broken in a way that
    // still renders a plausible-looking page.
    const clusters = clusterDrops(drops!)
    expect(clusters.length).toBeGreaterThan(3)
    expect(clusters.length).toBeLessThan(drops!.length / 2)
    expect(clusters.reduce((s, c) => s + c.drops.length, 0)).toBe(drops!.length)
  })

  it('has a concentrated head — the squad has favourite spots', () => {
    const clusters = clusterDrops(drops!)
    const topFive = clusters.slice(0, 5).reduce((s, c) => s + c.drops.length, 0)
    expect(topFive / drops!.length).toBeGreaterThan(0.5)
  })

  it('is order-independent on real data', () => {
    const forward = clusterDrops(drops!).map((c) => `${c.id}:${c.drops.length}`)
    const reversed = clusterDrops([...drops!].reverse()).map((c) => `${c.id}:${c.drops.length}`)
    expect(forward).toEqual(reversed)
  })

  it('names the biggest spots with PUBG place names', () => {
    if (gaz === null) return // no gazetteer built for this map
    const clusters = clusterDrops(drops!).slice(0, 5)
    const labels = clusters.map((c) => labelCluster(c, gaz))
    // Not every spot is in a town — the squad drops in fields too — but the
    // biggest ones should not all come out unnamed. All-unnamed means the
    // coordinate transform between drops and the gazetteer is wrong, which
    // produces a page of anonymous pins that looks like a design choice.
    expect(labels.filter((l) => l.kind === 'named').length).toBeGreaterThan(0)
    for (const label of labels) {
      expect(label.kind).not.toBe('unknown')
      if (label.kind === 'named') expect(label.name).toBeTruthy()
      else expect(label.nearest).toBeTruthy()
    }
  })

  it('summarises every cluster without inventing a measurement', () => {
    for (const cluster of clusterDrops(drops!)) {
      const s = summariseCluster(cluster)
      expect(s.n).toBe(cluster.drops.length)
      expect(s.contestedN).toBeLessThanOrEqual(s.n)
      expect(s.firstWeaponN).toBeLessThanOrEqual(s.n)
      if (s.contestedRate !== null) {
        expect(s.contestedRate).toBeGreaterThanOrEqual(0)
        expect(s.contestedRate).toBeLessThanOrEqual(1)
      }
      if (s.places.length) {
        expect(s.medianPlace).toBeGreaterThan(0)
        expect(s.bestPlace).toBeLessThanOrEqual(s.medianPlace)
      }
    }
  })

  it('serves a gazetteer whose cells are a minority of the grid', () => {
    if (gaz === null) return
    // Most of Erangel is fields. A gazetteer naming most of the map would
    // label every drop confidently and wrongly.
    expect(gaz.cells.length).toBeGreaterThan(100)
    expect(gaz.cells.length).toBeLessThan(gaz.grid * gaz.grid * 0.3)
    expect(gaz.modalPurity).toBeGreaterThan(0.95)
  })
})
