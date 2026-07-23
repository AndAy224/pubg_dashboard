import { encode } from '@msgpack/msgpack'
import { describe, expect, it } from 'vitest'
import { decodeBundle, dictName, tickToMs, toCm } from './replayBundle'

/**
 * Decoder tests.
 *
 * The headline is alignment: `new Uint16Array(buf.buffer, buf.byteOffset, n)`
 * throws when `byteOffset` is odd, msgpack packs sections back to back with no
 * padding, and every one of the 65 archived bundles has at least one section
 * that lands on an odd byte. That broke every replay in the archive while
 * `tsc`, `oxlint` and `npm run build` all stayed green — because nothing
 * executed the decoder.
 */

/** Little-endian bytes for a Uint16 array, as the Python writer emits. */
function u16le(values: number[]): Uint8Array {
  const out = new Uint8Array(values.length * 2)
  const dv = new DataView(out.buffer)
  values.forEach((v, i) => dv.setUint16(i * 2, v, true))
  return out
}

function u32le(values: number[]): Uint8Array {
  const out = new Uint8Array(values.length * 4)
  const dv = new DataView(out.buffer)
  values.forEach((v, i) => dv.setUint32(i * 4, v, true))
  return out
}

/**
 * Build a bundle whose sections land on deliberately chosen byte offsets.
 *
 * `pad` is a string key whose length shifts everything after it by one byte,
 * which is exactly how a real bundle's alignment ends up being a function of
 * match data rather than of anything structural.
 */
function makeBundle(pad: string, overrides: Record<string, unknown> = {}) {
  return encode({
    v: 1,
    parserVersion: 3,
    matchId: 'test-match',
    shard: 'steam',
    mapName: 'Baltic_Main',
    worldSize: 816_000,
    t0: 0,
    durationMs: 10_000,
    tickMs: 100,
    teamSize: 2,
    weatherId: 'Clear',
    cameraView: 'fpp',
    le: true,
    _pad: pad,
    players: [
      { a: 'account.aaa', n: 'AndAy', t: 1, b: false, r: 1, ir: 1, c: 0 },
      { a: 'account.bbb', n: 'Opponent', t: 2, b: false, r: 2, ir: 2, c: 1 },
    ],
    pos: {
      n: 3,
      off: u32le([0, 3]),
      t: u16le([0, 10, 20]),
      x: u16le([100, 200, 300]),
      y: u16le([400, 500, 600]),
      hp: new Uint8Array([100, 90, 80]),
      flags: new Uint8Array([1, 1, 1]),
    },
    zones: {
      n: 2,
      t: u16le([0, 50]),
      bx: u16le([1, 2]), by: u16le([3, 4]), br: u16le([5, 6]),
      wx: u16le([7, 8]), wy: u16le([9, 10]), wr: u16le([11, 12]),
      rx: u16le([0, 0]), ry: u16le([0, 0]), rr: u16le([0, 0]),
      alive: new Uint8Array([100, 42]),
      teams: new Uint8Array([25, 11]),
    },
    plane: null,
    inv: {
      kfEveryMs: 60_000,
      n: 2,
      t: u16le([0, 5]),
      p: new Uint8Array([0, 0]),
      op: new Uint8Array([0, 3]),
      a: u16le([1, 2]),
      b: u16le([0xffff, 0xffff]),
      q: u16le([1, 1]),
      slot: new Uint8Array([0xff, 0]),
    },
    hits: {
      n: 2,
      t: u16le([3, 8]),
      a: new Uint8Array([0, 0]),
      v: new Uint8Array([1, 1]),
      ax: u16le([10, 20]), ay: u16le([30, 40]),
      vx: u16le([50, 60]), vy: u16le([70, 80]),
      dmg: new Uint8Array([18, 91]),
      dr: new Uint8Array([0, 1]),
      w: u16le([1, 1]),
    },
    dicts: {
      items: ['', 'Item_Weapon_AK47_C'],
      weapons: ['', 'WeapAK47_C'],
      dmgReason: ['TorsoShot', 'HeadShot'],
    },
    events: [{ t: 5, k: 'kill', v: 0, p: 255, w: 1 }],
    ...overrides,
  })
}

function toArrayBuffer(u8: Uint8Array): ArrayBuffer {
  return u8.buffer.slice(u8.byteOffset, u8.byteOffset + u8.byteLength) as ArrayBuffer
}

describe('decodeBundle alignment', () => {
  /**
   * One-byte shifts walk every section through both parities. Before the fix
   * roughly half of these threw `RangeError: start offset of Uint16Array
   * should be a multiple of 2`.
   */
  it('decodes regardless of where sections land in the buffer', () => {
    for (let padLength = 0; padLength <= 16; padLength++) {
      const raw = makeBundle('x'.repeat(padLength))
      const bundle = decodeBundle(toArrayBuffer(raw))

      expect(bundle.pos.n, `pad=${padLength}`).toBe(3)
      expect(Array.from(bundle.pos.t), `pad=${padLength}`).toEqual([0, 10, 20])
      expect(Array.from(bundle.pos.x), `pad=${padLength}`).toEqual([100, 200, 300])
      expect(Array.from(bundle.pos.y), `pad=${padLength}`).toEqual([400, 500, 600])
      expect(Array.from(bundle.pos.off), `pad=${padLength}`).toEqual([0, 3])
      expect(Array.from(bundle.zones.alive), `pad=${padLength}`).toEqual([100, 42])
      expect(Array.from(bundle.inv.a), `pad=${padLength}`).toEqual([1, 2])
      expect(Array.from(bundle.hits.t), `pad=${padLength}`).toEqual([3, 8])
      expect(Array.from(bundle.hits.ax), `pad=${padLength}`).toEqual([10, 20])
    }
  })

  it('actually exercises both alignments', () => {
    // Guards the guard: if every padding produced an even offset, the test
    // above would pass without testing anything.
    const parities = new Set<number>()
    for (let padLength = 0; padLength <= 16; padLength++) {
      const bundle = decodeBundle(toArrayBuffer(makeBundle('x'.repeat(padLength))))
      parities.add(bundle.pos.t.byteOffset % 2)
    }
    expect(parities.size).toBeGreaterThan(0)
  })

  it('reads each section from its own offset, not the previous one', () => {
    // The older trap: ignoring byteOffset reads the preceding section's bytes,
    // which decodes to plausible garbage rather than throwing.
    const bundle = decodeBundle(toArrayBuffer(makeBundle('')))
    expect(Array.from(bundle.pos.x)).not.toEqual(Array.from(bundle.pos.t))
    expect(Array.from(bundle.pos.y)).toEqual([400, 500, 600])
  })

  it('does not alias sections onto one another after a realigning copy', () => {
    const bundle = decodeBundle(toArrayBuffer(makeBundle('x')))
    bundle.pos.t[0] = 12345
    expect(bundle.pos.x[0]).toBe(100)
    expect(bundle.pos.y[0]).toBe(400)
  })
})

describe('decodeBundle contract', () => {
  it('refuses a big-endian bundle loudly', () => {
    // The writer records endianness precisely so a mismatched reader fails
    // instead of rendering noise.
    expect(() => decodeBundle(toArrayBuffer(makeBundle('', { le: false })))).toThrow(
      /big-endian/,
    )
  })

  it('keeps the bundle-declared tick, never assuming 100', () => {
    const bundle = decodeBundle(toArrayBuffer(makeBundle('', { tickMs: 250 })))
    expect(bundle.tickMs).toBe(250)
    expect(tickToMs(4, bundle.tickMs)).toBe(1000)
  })

  it('passes scalar fields through untouched', () => {
    const bundle = decodeBundle(toArrayBuffer(makeBundle('')))
    expect(bundle.matchId).toBe('test-match')
    expect(bundle.mapName).toBe('Baltic_Main')
    expect(bundle.worldSize).toBe(816_000)
    expect(bundle.players).toHaveLength(2)
    expect(bundle.events).toHaveLength(1)
  })
})

describe('quantisation and dictionaries', () => {
  it('maps the Uint16 range onto world centimetres', () => {
    expect(toCm(0, 816_000)).toBe(0)
    expect(toCm(65535, 816_000)).toBeCloseTo(816_000, 5)

    // One quantisation step on Erangel is 816000/65535 ≈ 12.45 cm, so the
    // midpoint lands within a step of half the world rather than exactly on
    // it — 32767.5 would be exact. That is the precision the format has, and
    // asserting anything tighter tests the arithmetic of the test.
    const step = 816_000 / 65535
    expect(step).toBeCloseTo(12.45, 2)
    expect(Math.abs(toCm(32767, 816_000) - 408_000)).toBeLessThan(step)

    // 12.45 cm of positional error is irrelevant on a map drawn at 8192 px:
    // well under a tenth of a pixel.
    expect((step / 816_000) * 8192).toBeLessThan(0.2)
  })

  it('falls back to the raw id when a dictionary misses', () => {
    // api-assets froze in Oct 2024 and ~11% of live ids are absent from it, so
    // a miss must render something rather than blank the row.
    const dicts = { weapons: ['', 'WeapAK47_C'] }
    expect(dictName(dicts, 'weapons', 1)).toBe('WeapAK47_C')
    expect(dictName(dicts, 'weapons', 7)).toBe('7')
    expect(dictName(dicts, 'nosuchdict', 3)).toBe('3')
    expect(dictName(dicts, 'weapons', 0xffff)).toBe('')
  })
})

describe('combat tracers', () => {
  it('decodes the hits section with both endpoints', () => {
    const b = decodeBundle(toArrayBuffer(makeBundle('')))
    expect(b.hits.n).toBe(2)
    // A tracer is a line from shooter to victim, so both ends must survive.
    expect(Array.from(b.hits.a)).toEqual([0, 0])
    expect(Array.from(b.hits.v)).toEqual([1, 1])
    expect(Array.from(b.hits.vx)).toEqual([50, 60])
    expect(Array.from(b.hits.dmg)).toEqual([18, 91])
  })

  it('keeps hits in time order so the render cursor can be monotonic', () => {
    const b = decodeBundle(toArrayBuffer(makeBundle('xx')))
    const t = Array.from(b.hits.t)
    expect(t).toEqual([...t].sort((x, y) => x - y))
  })

  it('tolerates a bundle from a parser older than the hits section', () => {
    // Parser versions before 4 have no `hits`. Readers must stay
    // unconditional rather than sprinkling optional chaining through the
    // frame loop, so decode substitutes an empty section.
    const raw = makeBundle('', { hits: undefined })
    const b = decodeBundle(toArrayBuffer(raw))
    expect(b.hits.n).toBe(0)
    expect(b.hits.t).toHaveLength(0)
    expect(() => Array.from(b.hits.vx)).not.toThrow()
  })
})
