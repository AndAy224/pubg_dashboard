import { beforeEach, describe, expect, it } from 'vitest'
import { isTracked, placeGrade, playerColour, playerColourHex, registerPlayers } from './players'

const ANDAY = 'account.662de5f2cecc4998886b83be6582ed12'
const SIERIUS = 'account.a92d4e1700f54ccab0c6a0e5928cbdb7'
const GAINZ = 'account.beb5faf7d57d4968bfa187e3cf81cc40'

describe('identity colours', () => {
  beforeEach(() => registerPlayers([ANDAY, SIERIUS, GAINZ]))

  it('assigns a colour per tracked player', () => {
    const colours = [ANDAY, SIERIUS, GAINZ].map(playerColour)
    expect(new Set(colours).size).toBe(3)
  })

  /**
   * The whole reason colours are keyed on sorted account id rather than on the
   * order the API returned. A colour that shifts under you is worse than no
   * colour, because you have already learned to read it.
   */
  it('is stable regardless of registration order', () => {
    const before = [ANDAY, SIERIUS, GAINZ].map(playerColour)
    registerPlayers([GAINZ, ANDAY, SIERIUS])
    expect([ANDAY, SIERIUS, GAINZ].map(playerColour)).toEqual(before)
    registerPlayers([SIERIUS, GAINZ, ANDAY])
    expect([ANDAY, SIERIUS, GAINZ].map(playerColour)).toEqual(before)
  })

  it('does not recolour the existing three when a fourth is added', () => {
    const before = [ANDAY, SIERIUS, GAINZ].map(playerColour)
    // 'account.f...' sorts last, so it takes the free slot.
    registerPlayers([ANDAY, SIERIUS, GAINZ, 'account.fff'])
    expect([ANDAY, SIERIUS, GAINZ].map(playerColour)).toEqual(before)
  })

  it('gives an untracked opponent the neutral treatment', () => {
    // Never borrow a tracked player's colour: the dot is what says "this is
    // one of us" on a scoreboard of a hundred names.
    expect(playerColour('account.stranger')).toBe('var(--text-dim)')
    expect(playerColourHex('account.stranger')).toBe('#97a3b4')
    expect(isTracked('account.stranger')).toBe(false)
    expect(isTracked(ANDAY)).toBe(true)
  })

  it('keeps hex and CSS-variable forms in step', () => {
    // Canvas and Pixi cannot resolve `var()`, so the two lists must stay
    // parallel — a mismatch shows as a replay dot in a different colour from
    // the same player's nav entry.
    const slots = ['var(--p-1)', 'var(--p-2)', 'var(--p-3)']
    const hexes = ['#f0b429', '#4cc9f0', '#b388ff']
    for (const id of [ANDAY, SIERIUS, GAINZ]) {
      expect(hexes[slots.indexOf(playerColour(id))]).toBe(playerColourHex(id))
    }
  })
})

describe('placement grading', () => {
  it('grades the boundaries exactly', () => {
    expect(placeGrade(1)).toBe('win')
    expect(placeGrade(2)).toBe('top5')
    expect(placeGrade(5)).toBe('top5')
    expect(placeGrade(6)).toBe('top10')
    expect(placeGrade(10)).toBe('top10')
    expect(placeGrade(11)).toBe('rest')
  })

  it('handles placements above 100', () => {
    // `winPlace` ranks *participants*, not teams, and has been observed at
    // 107 in the corpus. Nothing may assume an upper bound.
    expect(placeGrade(107)).toBe('rest')
    expect(placeGrade(999)).toBe('rest')
  })

  it('treats a missing placement as ungraded rather than as a win', () => {
    // A feed row with no tracked participant has a null placement; grading it
    // as anything but 'rest' would paint a gold chip on a match nobody played.
    expect(placeGrade(null)).toBe('rest')
    expect(placeGrade(undefined)).toBe('rest')
  })
})
