import { describe, expect, it } from 'vitest'
import { readFileSync, existsSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

/**
 * The care-package icons are on disk and are real PNGs.
 *
 * Worth a test precisely **because the renderer degrades gracefully**: if these
 * go missing, `loadCrateArt` falls back to the hand-drawn glyphs and the replay
 * keeps working, so nothing would ever fail loudly. The failure mode is that
 * PUBG's art quietly stops shipping and the map goes back to looking
 * home-made — which is exactly the class of silent regression this project
 * exists to catch.
 *
 * Also guards the Git-LFS trap `scripts/fetch_map_assets.py` documents: on
 * `raw.githubusercontent.com`, LFS-tracked files serve a ~130-byte pointer
 * *text* file with a `.png` name. These three are not LFS-tracked, and the
 * magic-number check below is what would notice if someone re-fetched them
 * from the wrong URL.
 */
const here = dirname(fileURLToPath(import.meta.url))
const CRATES = resolve(here, '../../../public/crates')

const PNG_MAGIC = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])

describe('care-package icons', () => {
  for (const [name, minBytes] of [
    ['CarePackage_Flying.png', 4000],
    ['CarePackage_Normal.png', 2000],
    // Not used by the renderer yet — kept because the signal for it exists
    // (`LogItemPickupFromCarepackage`) and wiring it up needs a parser bump.
    ['CarePackage_Open.png', 2000],
  ] as const) {
    it(`${name} is present and is a real PNG`, () => {
      const path = resolve(CRATES, name)
      expect(existsSync(path), `${path} is missing`).toBe(true)

      const bytes = readFileSync(path)
      // A Git-LFS pointer is ~130 bytes of text beginning "version https://..."
      expect(bytes.length).toBeGreaterThan(minBytes)
      expect(bytes.subarray(0, 8).equals(PNG_MAGIC), 'not PNG magic — LFS pointer?').toBe(
        true,
      )
    })
  }

  it('the flying icon is taller than it is wide', () => {
    // The renderer preserves aspect and anchors on the *box*, not the centre,
    // so the parachute hangs above the drop point rather than the crate
    // sitting below it. Both of those assume a portrait canopy image; a square
    // replacement would silently move every falling crate off its position.
    const bytes = readFileSync(resolve(CRATES, 'CarePackage_Flying.png'))
    // IHDR: width and height are big-endian uint32 at offsets 16 and 20.
    const width = bytes.readUInt32BE(16)
    const height = bytes.readUInt32BE(20)
    expect(width).toBe(144)
    expect(height).toBe(200)
    expect(height).toBeGreaterThan(width)
  })
})
