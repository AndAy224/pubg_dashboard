import { decode } from '@msgpack/msgpack'

/**
 * Decoding the processed replay bundle.
 *
 * The point of MessagePack here is the `bin` type: the server writes raw
 * little-endian typed-array buffers and we wrap them **in place** with
 * `new Uint16Array(buf.buffer, buf.byteOffset, n)`. No copy, no parse. JSON
 * would mean parsing ~200k numbers into boxed values on the main thread every
 * time the user scrubs.
 *
 * `byteOffset` is not optional. msgpack hands back `Uint8Array` views onto one
 * larger buffer, so ignoring the offset silently reads the *previous*
 * section's bytes — which decodes to plausible-looking garbage rather than
 * throwing.
 */

export const FLAG_ALIVE = 1 << 0
export const FLAG_DBNO = 1 << 1
export const FLAG_IN_VEHICLE = 1 << 2
export const FLAG_BLUE_ZONE = 1 << 3
export const FLAG_RED_ZONE = 1 << 4
export const FLAG_PARACHUTING = 1 << 5

/** No player index 255 exists in a <=100-player lobby. */
export const NULL_PLAYER = 255

export interface BundlePlayer {
  /** accountId — `account.<hex>` or `ai.<n>`. */
  a: string
  /** name at match time */
  n: string
  /** teamId */
  t: number
  /** isBot */
  b: boolean
  /** final team ranking */
  r: number
  /** final individual ranking */
  ir: number
  /** palette colour index */
  c: number
}

export interface BundleEvent {
  t: number
  k: string
  [key: string]: unknown
}

export interface ReplayBundle {
  v: number
  parserVersion: number
  matchId: string
  shard: string
  mapName: string
  worldSize: number
  t0: number
  durationMs: number
  /** Time quantum for every `t` array in the file. **Never assume 100.** */
  tickMs: number
  teamSize: number
  weatherId: string
  cameraView: string
  le: boolean
  players: BundlePlayer[]
  pos: {
    n: number
    /** CSR offsets: player p occupies [off[p], off[p+1]) in every array. */
    off: Uint32Array
    t: Uint16Array
    x: Uint16Array
    y: Uint16Array
    hp: Uint8Array
    flags: Uint8Array
  }
  events: BundleEvent[]
  zones: {
    n: number
    t: Uint16Array
    /** blue == safetyZone* — the current damaging circle. INTERPOLATE. */
    bx: Uint16Array
    by: Uint16Array
    br: Uint16Array
    /** white == poisonGasWarning* — the next circle. SNAP; it is a step fn. */
    wx: Uint16Array
    wy: Uint16Array
    wr: Uint16Array
    rx: Uint16Array
    ry: Uint16Array
    rr: Uint16Array
    alive: Uint8Array
    teams: Uint8Array
  }
  plane: { x0: number; y0: number; x1: number; y1: number } | null
  inv: {
    kfEveryMs: number
    n: number
    t: Uint16Array
    p: Uint8Array
    op: Uint8Array
    a: Uint16Array
    b: Uint16Array
    q: Uint16Array
    slot: Uint8Array
  }
  dicts: Record<string, string[]>
}

function u8(v: unknown): Uint8Array {
  const b = v as Uint8Array
  return new Uint8Array(b.buffer, b.byteOffset, b.byteLength)
}

function u16(v: unknown): Uint16Array {
  const b = v as Uint8Array
  // byteOffset is load-bearing — see the module docstring.
  return new Uint16Array(b.buffer, b.byteOffset, b.byteLength / 2)
}

function u32(v: unknown): Uint32Array {
  const b = v as Uint8Array
  return new Uint32Array(b.buffer, b.byteOffset, b.byteLength / 4)
}

export function decodeBundle(raw: ArrayBuffer): ReplayBundle {
  const d = decode(new Uint8Array(raw)) as Record<string, any>

  if (d.le === false) {
    // The writer records endianness precisely so a big-endian reader fails
    // loudly instead of rendering noise.
    throw new Error('replay bundle is big-endian; this reader assumes little-endian')
  }

  const pos = d.pos
  const zones = d.zones
  const inv = d.inv

  return {
    ...d,
    pos: {
      n: pos.n,
      off: u32(pos.off),
      t: u16(pos.t),
      x: u16(pos.x),
      y: u16(pos.y),
      hp: u8(pos.hp),
      flags: u8(pos.flags),
    },
    zones: {
      n: zones.n,
      t: u16(zones.t),
      bx: u16(zones.bx), by: u16(zones.by), br: u16(zones.br),
      wx: u16(zones.wx), wy: u16(zones.wy), wr: u16(zones.wr),
      rx: u16(zones.rx), ry: u16(zones.ry), rr: u16(zones.rr),
      alive: u8(zones.alive),
      teams: u8(zones.teams),
    },
    inv: {
      kfEveryMs: inv.kfEveryMs,
      n: inv.n,
      t: u16(inv.t),
      p: u8(inv.p),
      op: u8(inv.op),
      a: u16(inv.a),
      b: u16(inv.b),
      q: u16(inv.q),
      slot: u8(inv.slot),
    },
  } as ReplayBundle
}

/** Quantised Uint16 back to centimetres. */
export function toCm(q: number, worldSize: number): number {
  return (q / 65535) * worldSize
}

/** Ticks since t0 -> milliseconds. Uses the bundle's own tickMs. */
export function tickToMs(tick: number, tickMs: number): number {
  return tick * tickMs
}

/** Look up a dictionary entry, always falling back to the raw id.
 *
 * `api-assets` froze in Oct 2024 and ~11% of live ids are absent from it, so
 * a miss must render the id rather than blank the row. */
export function dictName(dicts: Record<string, string[]>, name: string, index: number): string {
  if (index === 0xffff) return ''
  return dicts[name]?.[index] ?? String(index)
}
