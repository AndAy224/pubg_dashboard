/** Team colours for the replay and the scoreboard.
 *
 * Chosen for separability against the map's greens and blues at small dot
 * sizes, not for prettiness — 100 dots on Erangel is the hard case. */
export const TEAM_COLOURS = [
  0xf0b429, 0x58a6ff, 0x3fb950, 0xf85149, 0xbc8cff, 0x39c5cf,
  0xff8c69, 0xffd700, 0x7ee787, 0xff7b72, 0xa5d6ff, 0xd2a8ff,
  0xffab70, 0x85e89d, 0xf692ce, 0x79c0ff, 0xffa657, 0x56d364,
  0xffbedd, 0x6cb6ff, 0xfaa356, 0x6bc46d, 0xdbb7ff, 0xec8e2c,
] as const

export function teamColour(index: number): number {
  return TEAM_COLOURS[index % TEAM_COLOURS.length]!
}

export function hex(colour: number): string {
  return `#${colour.toString(16).padStart(6, '0')}`
}

/** Dimmed rendering for bots — they are up to 93% of a TPP squad lobby. */
export const BOT_COLOUR = 0x6e7681
/** The tracked players, so they stand out in a 100-dot crowd. */
export const TRACKED_COLOUR = 0xffffff
