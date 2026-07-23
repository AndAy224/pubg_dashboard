export const nf = new Intl.NumberFormat('en-GB')

export function num(n: number | null | undefined, digits = 0): string {
  if (n === null || n === undefined || Number.isNaN(n)) return '—'
  return n.toLocaleString('en-GB', { minimumFractionDigits: digits, maximumFractionDigits: digits })
}

export function duration(seconds: number | null | undefined): string {
  if (!seconds && seconds !== 0) return '—'
  const s = Math.max(0, Math.round(seconds))
  const m = Math.floor(s / 60)
  // Both trailing units are zero-padded so the strings stay the same width in
  // a `tabular-nums` column — "1h 0m" against "1h 30m" shifts the whole
  // column by a character.
  return m >= 60
    ? `${Math.floor(m / 60)}h ${String(m % 60).padStart(2, '0')}m`
    : `${m}m ${String(s % 60).padStart(2, '0')}s`
}

export function distance(metres: number | null | undefined): string {
  if (metres === null || metres === undefined) return '—'
  return metres >= 1000 ? `${(metres / 1000).toFixed(1)} km` : `${Math.round(metres)} m`
}

export function ago(iso: string | null | undefined): string {
  if (!iso) return 'never'
  const delta = (Date.now() - new Date(iso).getTime()) / 1000
  if (delta < 90) return `${Math.round(delta)}s ago`
  if (delta < 5400) return `${Math.round(delta / 60)}m ago`
  if (delta < 172800) return `${Math.round(delta / 3600)}h ago`
  return `${Math.round(delta / 86400)}d ago`
}

export function dateTime(iso: string): string {
  return new Date(iso).toLocaleString('en-GB', {
    day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit',
  })
}

/**
 * `squad-fpp` -> `Squad FPP`.
 *
 * **Must tolerate an empty or absent mode.** This used to be `p[0]!` over the
 * raw split, and `''.split('-')` is `['']` — so `p[0]` was `undefined` and
 * `.toUpperCase()` threw. The `!` silenced TypeScript at exactly the point
 * where the value really is undefined.
 *
 * The call site was `gameMode(match?.gameMode ?? '')` in the replay's TopBar,
 * which passes `''` for as long as the match query is in flight. The throw
 * happened during render, so React Router's error boundary swallowed the whole
 * **page** — canvas included — and a cold load of any replay showed nothing at
 * all. Every PUBG enum is open, so a formatter must never assume its input's
 * shape.
 */
export function gameMode(mode: string | null | undefined): string {
  if (!mode) return '—'
  return mode
    .split('-')
    .filter(Boolean)
    .map((p) =>
      p === 'fpp' || p === 'tpp' ? p.toUpperCase() : p[0]!.toUpperCase() + p.slice(1),
    )
    .join(' ')
}

/**
 * Strip PUBG's class-name decoration for display.
 * `WeapHK416_C` -> `HK416`, `Item_Weapon_AWM_C` -> `AWM`.
 *
 * Always falls back to the raw id: `api-assets` has been frozen since Oct
 * 2024 and roughly 11% of live ids are missing from its dictionaries, so a
 * lookup miss must never blank the row.
 */
export function weaponName(raw: string | null | undefined): string {
  if (!raw) return '—'
  return raw
    .replace(/^Item_Weapon_/, '')
    .replace(/^Weap/, '')
    .replace(/_C$/, '')
    .replace(/_/g, ' ')
}

export function placement(place: number): string {
  return `#${place}`
}

/** Attachment category prefixes that only repeat what follows them. */
const ATTACH_CATEGORY = /^(Muzzle|Magazine|Stock|Lower|Upper|SideRail)_/

/**
 * Inventory item ids, for the replay loadout.
 *
 * `weaponName` only strips the weapon decorations, so armour and attachments
 * came out as `Item Attach Weapon Muzzle AR MuzzleBrake` and
 * `Item Head F 01 Lv2` — technically the data, practically unreadable.
 *
 * Armour and packs encode a model letter and number that mean nothing to a
 * reader (`Item_Head_F_01_Lv2_C` is "a level 2 helmet"), and the slot label
 * beside them already says which piece it is, so only the tier is kept.
 *
 * Always degrades to something printable: `api-assets` froze in Oct 2024 and
 * ~11% of live ids are absent from it, so an unknown id must render as itself
 * rather than blank the row.
 */
export function itemName(raw: string | null | undefined): string {
  if (!raw) return '—'
  let s = raw.replace(/_C$/, '').replace(/^Item_/, '')

  const tier = /_Lv(\d)$/.exec(s)
  if (tier && /^(Head|Armor|Back)_/.test(s)) return `Lv${tier[1]}`

  s = s
    .replace(/^Attach_Weapon_/, '')
    .replace(/^Weapon_/, '')
    .replace(/^Weap/, '')
    .replace(/^(Ammo|Heal|Boost|Attach)_/, '')
    .replace(ATTACH_CATEGORY, '')

  return s
    .replace(/_/g, ' ')
    // CamelCase to words, so "MuzzleBrake" reads as "Muzzle Brake".
    .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
    .trim()
}
