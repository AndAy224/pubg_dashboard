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
 *
 * **And the offset is very often unusable.** A typed-array view must begin on
 * a multiple of its element size, or the constructor throws
 * `RangeError: start offset of Uint16Array should be a multiple of 2`.
 * msgpack packs sections back to back with no padding, so where a section
 * lands depends on the byte length of everything before it — which is match
 * data. Measured across the archive: **every bundle has at least one
 * misaligned section**, and which ones differ per match. This threw on the
 * first `Uint16Array` for all 65 matches, and because it threw inside the
 * react-query `queryFn`, the replay page reported "no replay bundle for this
 * match — it has not been parsed yet". The bundles were fine; nothing could
 * read them.
 *
 * So the zero-copy path is now conditional, with a copy as the fallback. The
 * copy is once per bundle load and the largest section is ~28 KB, which is
 * not worth padding the format to avoid.
 */

/**
 * Still in the match — **including knocked**. Resolved server-side against
 * each account's final death, not from `hp > 0`.
 *
 * Do not try to recover "knocked but not dead" as `FLAG_DBNO && !FLAG_ALIVE`
 * from an older bundle: at the moment of death 51% of victims are still
 * flagged `isDBNO`, so that test leaves half the corpses on the map forever.
 * Parser version 5 is what makes these two bits independent and correct.
 */
export const FLAG_ALIVE = 1 << 0
/** Knocked and not yet finished off. Implies `FLAG_ALIVE`. */
export const FLAG_DBNO = 1 << 1
/**
 * In *any* vehicle, straight from `character.isInVehicle`.
 *
 * **Not the flag to draw a vehicle marker from.** The match-start aircraft is
 * a vehicle, so this is true for the entire lobby for the first minute and a
 * half, and 43% of in-vehicle samples are aircraft, pickup balloons or a
 * mounted mortar. Use `FLAG_DRIVING`.
 */
export const FLAG_IN_VEHICLE = 1 << 2
export const FLAG_BLUE_ZONE = 1 << 3
export const FLAG_RED_ZONE = 1 << 4
export const FLAG_PARACHUTING = 1 << 5
/**
 * In a vehicle that is driven around the map — car, boat or glider. Implies
 * `FLAG_IN_VEHICLE`. Passengers included. Requires parser version 6.
 */
export const FLAG_DRIVING = 1 << 6

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
    /**
     * Health, 0..100, already corrected to the value *after* the event that
     * produced the sample. **Step it, never interpolate it** — health jumps on
     * a hit, and a smooth ramp would show a player at 60 while they are at 10.
     */
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
  /**
   * Attributed hits — the combat tracers. **Both** endpoints, because a tracer
   * is a line from shooter to victim, and `LogPlayerTakeDamage` is the only
   * event carrying the two positions together.
   *
   * Sorted by `t`, so the renderer can walk it with a cursor like `pos`.
   * Absent on bundles from parser versions before 4.
   */
  hits: {
    n: number
    t: Uint16Array
    /** Player indices. */
    a: Uint8Array
    v: Uint8Array
    /** Quantised positions, same scale as `pos`. */
    ax: Uint16Array
    ay: Uint16Array
    vx: Uint16Array
    vy: Uint16Array
    /** Clamped into a byte; real damage caps at 100. */
    dmg: Uint8Array
    /** Index into `dicts.dmgReason` — HeadShot, TorsoShot, … */
    dr: Uint8Array
    w: Uint16Array
  }
  dicts: Record<string, string[]>
}

/**
 * Copy a section into its own buffer, so a view can start at offset 0.
 *
 * `ArrayBuffer.prototype.slice` is used rather than `TypedArray.slice`
 * because under Node — where msgpack yields a `Buffer` rather than a plain
 * `Uint8Array` — `Buffer.prototype.slice` returns a *view*, not a copy, and
 * would hand back the original misaligned buffer. `ArrayBuffer.slice` copies
 * in every runtime.
 */
function realign(b: Uint8Array): ArrayBuffer {
  return b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength) as ArrayBuffer
}

function u8(v: unknown): Uint8Array {
  const b = v as Uint8Array
  // Always safe: a one-byte element has no alignment requirement.
  return new Uint8Array(b.buffer, b.byteOffset, b.byteLength)
}

function u16(v: unknown): Uint16Array {
  const b = v as Uint8Array
  // byteOffset is load-bearing, and must be even — see the module docstring.
  if (b.byteOffset % 2 !== 0) return new Uint16Array(realign(b))
  return new Uint16Array(b.buffer, b.byteOffset, b.byteLength / 2)
}

function u32(v: unknown): Uint32Array {
  const b = v as Uint8Array
  if (b.byteOffset % 4 !== 0) return new Uint32Array(realign(b))
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
    // Parser versions before 4 have no `hits`. An empty section keeps every
    // reader unconditional rather than sprinkling `?.` through the hot loop.
    hits: d.hits
      ? {
          n: d.hits.n,
          t: u16(d.hits.t),
          a: u8(d.hits.a),
          v: u8(d.hits.v),
          ax: u16(d.hits.ax),
          ay: u16(d.hits.ay),
          vx: u16(d.hits.vx),
          vy: u16(d.hits.vy),
          dmg: u8(d.hits.dmg),
          dr: u8(d.hits.dr),
          w: u16(d.hits.w),
        }
      : EMPTY_HITS,
  } as ReplayBundle
}

const EMPTY_HITS = {
  n: 0,
  t: new Uint16Array(0),
  a: new Uint8Array(0),
  v: new Uint8Array(0),
  ax: new Uint16Array(0),
  ay: new Uint16Array(0),
  vx: new Uint16Array(0),
  vy: new Uint16Array(0),
  dmg: new Uint8Array(0),
  dr: new Uint8Array(0),
  w: new Uint16Array(0),
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
