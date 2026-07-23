import { useMemo } from 'react'
import type { ReplayBundle } from '../lib/replayBundle'
import { dictName } from '../lib/replayBundle'
import { weaponName } from '../lib/format'

/** Opcodes, mirroring `telemetry/inventory.py`. */
const OP_ADD_LOOSE = 0
const OP_REMOVE_LOOSE = 1
const OP_SET_LOOSE = 2
const OP_EQUIP = 3
const OP_UNEQUIP = 4
const OP_ATTACH = 5
const OP_DETACH = 6
const OP_CLEAR = 7
const OP_ARMOR_DESTROY = 8
// OP_PROVENANCE (9) records where an item came from; it changes no state.

const SLOT_NAMES = [
  'Primary',
  'Secondary',
  'Sidearm',
  'Melee',
  'Throwable',
  'Helmet',
  'Vest',
  'Backpack',
]
const SLOT_LOOSE = 0xff

interface Resolved {
  slots: Map<number, { item: string; attachments: string[] }>
  loose: Map<string, number>
}

/**
 * What one player is carrying at time `t`.
 *
 * The bundle ships the delta track but **not** the keyframes the parser
 * builds, so this folds deltas from zero. BUILD-SPEC §5.3 warns against that,
 * and it is right about the case it means — resolving every player every
 * frame. This resolves **one** player at **10 Hz**, and a whole match is a few
 * thousand deltas of which one player owns a fraction, so the fold is
 * microseconds. Memoised per (player, whole second) so scrubbing does not
 * repeat it.
 */
function resolve(bundle: ReplayBundle, playerIndex: number, tickLimit: number): Resolved {
  const inv = bundle.inv
  const slots = new Map<number, { item: string; attachments: string[] }>()
  const loose = new Map<string, number>()

  for (let i = 0; i < inv.n; i++) {
    if (inv.t[i]! > tickLimit) break
    if (inv.p[i]! !== playerIndex) continue

    const op = inv.op[i]!
    const item = dictName(bundle.dicts, 'items', inv.a[i]!)
    const other = inv.b[i]! === 0xffff ? '' : dictName(bundle.dicts, 'items', inv.b[i]!)
    const qty = inv.q[i]!
    const slot = inv.slot[i]!

    switch (op) {
      case OP_ADD_LOOSE:
        loose.set(item, (loose.get(item) ?? 0) + qty)
        break
      case OP_REMOVE_LOOSE: {
        const left = (loose.get(item) ?? 0) - qty
        if (left > 0) loose.set(item, left)
        else loose.delete(item)
        break
      }
      case OP_SET_LOOSE:
        if (qty > 0) loose.set(item, qty)
        else loose.delete(item)
        break
      case OP_EQUIP:
        if (slot !== SLOT_LOOSE) slots.set(slot, { item, attachments: [] })
        break
      case OP_UNEQUIP:
      case OP_ARMOR_DESTROY:
        if (slot !== SLOT_LOOSE) slots.delete(slot)
        break
      case OP_ATTACH: {
        // `a` is the host weapon, `b` the attachment.
        for (const entry of slots.values()) {
          if (entry.item === item && other) entry.attachments.push(other)
        }
        break
      }
      case OP_DETACH: {
        for (const entry of slots.values()) {
          if (entry.item === item && other) {
            const at = entry.attachments.indexOf(other)
            if (at >= 0) entry.attachments.splice(at, 1)
          }
        }
        break
      }
      case OP_CLEAR:
        slots.clear()
        loose.clear()
        break
      default:
        // Every PUBG enum is open and this one is ours, but a parser bump can
        // still add an opcode. Ignoring it leaves the panel slightly stale
        // rather than throwing mid-replay.
        break
    }
  }
  return { slots, loose }
}

export function InventoryPanel({
  bundle,
  playerIndex,
  nowMs,
}: {
  bundle: ReplayBundle
  playerIndex: number | null
  nowMs: number
}) {
  // Bucketed to whole seconds: the store ticks at 10 Hz and the inventory
  // does not change ten times a second.
  const second = Math.floor(nowMs / 1000)
  const state = useMemo(() => {
    if (playerIndex === null) return null
    return resolve(bundle, playerIndex, (second * 1000) / bundle.tickMs)
  }, [bundle, playerIndex, second])

  // Body only — the caller owns the heading and the surrounding card, because
  // this renders inside the loadout overlay on the canvas rather than as a
  // rail panel of its own.
  if (playerIndex === null) {
    return <div className="faint small">select a player to follow</div>
  }

  const heals = state
    ? [...state.loose.entries()].filter(([k]) => /heal|med|bandage|boost|painkiller|drink|syringe|adrenaline/i.test(k))
    : []
  const ammo = state
    ? [...state.loose.entries()].filter(([k]) => /ammo/i.test(k))
    : []

  return (
    <>
      {!state || (state.slots.size === 0 && state.loose.size === 0) ? (
        <div className="faint small">nothing carried yet</div>
      ) : (
        <div className="inv">
          {SLOT_NAMES.map((name, slot) => {
            const entry = state.slots.get(slot)
            if (!entry) return null
            return (
              <div className="inv-slot" key={slot}>
                <span className="inv-slot-name faint">{name}</span>
                <span className="inv-item">{weaponName(entry.item)}</span>
                {entry.attachments.length > 0 && (
                  <span className="inv-attach faint">
                    {entry.attachments.map((a) => weaponName(a)).join(' · ')}
                  </span>
                )}
              </div>
            )
          })}

          {heals.length > 0 && (
            <div className="inv-group">
              <span className="inv-slot-name faint">Heals</span>
              {heals.map(([k, v]) => (
                <span className="inv-pill" key={k}>
                  {weaponName(k)} <b className="num">{v}</b>
                </span>
              ))}
            </div>
          )}
          {ammo.length > 0 && (
            <div className="inv-group">
              <span className="inv-slot-name faint">Ammo</span>
              {ammo.map(([k, v]) => (
                <span className="inv-pill" key={k}>
                  {weaponName(k)} <b className="num">{v}</b>
                </span>
              ))}
            </div>
          )}
        </div>
      )}
    </>
  )
}
