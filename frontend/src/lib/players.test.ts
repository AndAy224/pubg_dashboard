import { beforeEach, describe, expect, it } from 'vitest'
import {
  getPlayerOrder,
  isTracked,
  placeGrade,
  playerColour,
  playerColourHex,
  registerPlayers,
  subscribeToPlayers,
} from './players'

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
    expect(playerColourHex('account.stranger')).toBe('#a4a28c')
    expect(isTracked('account.stranger')).toBe(false)
    expect(isTracked(ANDAY)).toBe(true)
  })

  it('keeps hex and CSS-variable forms in step', () => {
    // Canvas and Pixi cannot resolve `var()`, so the two lists must stay
    // parallel — a mismatch shows as a replay dot in a different colour from
    // the same player's nav entry.
    const slots = ['var(--p-1)', 'var(--p-2)', 'var(--p-3)']
    const hexes = ['#1e9fd2', '#d84378', '#8a72e8']
    for (const id of [ANDAY, SIERIUS, GAINZ]) {
      expect(hexes[slots.indexOf(playerColour(id))]).toBe(playerColourHex(id))
    }
  })
})

/**
 * The subscription is the whole reason the nav's player dots were grey.
 *
 * `order` is read during render but written from an effect, so the first
 * render after the roster arrives always saw an empty roster and rendered the
 * neutral fallback. Nothing told React to look again, so the nav stayed grey
 * for the life of the page while other surfaces got their colours only when
 * some unrelated re-render happened along.
 *
 * These test the store contract directly rather than through a component:
 * there is no jsdom here, and the bug was never in the markup.
 */
describe('roster subscription', () => {
  beforeEach(() => registerPlayers([]))

  it('notifies subscribers when the roster arrives', () => {
    let calls = 0
    const stop = subscribeToPlayers(() => calls++)
    // Precisely the sequence that was broken: read first, register second.
    expect(playerColour(ANDAY)).toBe('var(--text-dim)')
    registerPlayers([ANDAY, SIERIUS, GAINZ])
    expect(calls).toBe(1)
    expect(playerColour(ANDAY)).not.toBe('var(--text-dim)')
    stop()
  })

  it('stays silent when the roster has not actually changed', () => {
    // `useSyncExternalStore` re-reads on every notification, so a store that
    // cries wolf turns one registration per page into a render storm.
    registerPlayers([ANDAY, SIERIUS, GAINZ])
    let calls = 0
    const stop = subscribeToPlayers(() => calls++)
    registerPlayers([ANDAY, SIERIUS, GAINZ])
    registerPlayers([GAINZ, SIERIUS, ANDAY])
    expect(calls).toBe(0)
    stop()
  })

  it('hands out a snapshot whose identity is stable until it changes', () => {
    // If `getSnapshot` returned a fresh array each call, React would see a new
    // value on every render and loop forever.
    registerPlayers([ANDAY, SIERIUS])
    const first = getPlayerOrder()
    expect(getPlayerOrder()).toBe(first)
    registerPlayers([ANDAY, SIERIUS, GAINZ])
    expect(getPlayerOrder()).not.toBe(first)
  })

  it('stops notifying after unsubscribe', () => {
    let calls = 0
    subscribeToPlayers(() => calls++)()
    registerPlayers([ANDAY])
    expect(calls).toBe(0)
  })

  it('notifies every subscriber even if one detaches another mid-notification', () => {
    // React unsubscribes on unmount, and it is this very notification that
    // triggers the re-render doing the unmounting — so a listener really can
    // remove a later one while the store is still iterating. Over a live Set
    // that later listener is skipped and its component keeps the stale
    // colours, which is the original bug wearing a different hat.
    const seen: string[] = []
    const stopA = subscribeToPlayers(() => {
      seen.push('a')
      stopC()
    })
    const stopB = subscribeToPlayers(() => seen.push('b'))
    const stopC = subscribeToPlayers(() => seen.push('c'))

    registerPlayers([ANDAY, SIERIUS])
    expect(seen).toEqual(['a', 'b', 'c'])

    // And it really is detached for the next round.
    seen.length = 0
    registerPlayers([ANDAY])
    expect(seen).toEqual(['a', 'b'])
    stopA()
    stopB()
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
