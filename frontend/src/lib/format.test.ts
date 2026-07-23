import { describe, expect, it } from 'vitest'
import { distance, duration, gameMode, num, placement, weaponName } from './format'

describe('duration', () => {
  it('formats minutes and seconds, and hours past an hour', () => {
    expect(duration(0)).toBe('0m 00s')
    expect(duration(65)).toBe('1m 05s')
    expect(duration(3600)).toBe('1h 00m')
    expect(duration(5430)).toBe('1h 30m')
  })

  it('distinguishes zero from absent', () => {
    // A player who survived 0 s is not a player with no recorded time, and a
    // match strip that renders one as the other is lying about the data.
    expect(duration(0)).toBe('0m 00s')
    expect(duration(null)).toBe('—')
    expect(duration(undefined)).toBe('—')
  })

  it('never renders a negative duration', () => {
    expect(duration(-5)).toBe('0m 00s')
  })
})

describe('num', () => {
  it('groups thousands and honours the requested precision', () => {
    expect(num(1234)).toBe('1,234')
    expect(num(1234.567, 1)).toBe('1,234.6')
    expect(num(0)).toBe('0')
  })

  it('renders absent values as a dash, not as zero', () => {
    expect(num(null)).toBe('—')
    expect(num(undefined)).toBe('—')
    expect(num(NaN)).toBe('—')
  })
})

describe('gameMode', () => {
  it('capitalises words and upper-cases the perspective', () => {
    expect(gameMode('squad-fpp')).toBe('Squad FPP')
    expect(gameMode('duo-fpp')).toBe('Duo FPP')
    expect(gameMode('solo')).toBe('Solo')
  })
})

describe('weaponName', () => {
  it('strips PUBG class-name decoration', () => {
    expect(weaponName('WeapHK416_C')).toBe('HK416')
    expect(weaponName('Item_Weapon_AWM_C')).toBe('AWM')
  })

  it('always renders something for an unknown id', () => {
    // api-assets froze in Oct 2024 and ~11% of live ids are missing from it.
    // A miss must degrade to the raw id, never to an empty cell.
    expect(weaponName('SomethingBrandNew_C')).toBe('SomethingBrandNew')
    expect(weaponName('totally-unknown')).not.toBe('')
  })

  it('renders a dash for a genuinely absent weapon', () => {
    // A zone or fall death has no weapon at all — 2.9% of kills.
    expect(weaponName(null)).toBe('—')
    expect(weaponName(undefined)).toBe('—')
    expect(weaponName('')).toBe('—')
  })
})

describe('distance', () => {
  it('switches to kilometres past 1000 m', () => {
    expect(distance(250)).toBe('250 m')
    expect(distance(999)).toBe('999 m')
    expect(distance(1500)).toBe('1.5 km')
  })

  it('renders absent as a dash but keeps a real zero', () => {
    expect(distance(null)).toBe('—')
    expect(distance(0)).toBe('0 m')
  })
})

describe('placement', () => {
  it('prefixes with a hash', () => {
    expect(placement(1)).toBe('#1')
    expect(placement(107)).toBe('#107')
  })
})
