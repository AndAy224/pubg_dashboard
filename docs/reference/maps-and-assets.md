# PUBG Maps, Assets & Coordinate System — Implementation Reference

Ground-truth reference for heatmaps and 2D replay rendering.
Everything below was verified against a live fetch on **2026-07-22** unless explicitly tagged ⚠️.

---

## Sources

Every URL actually fetched while writing this document:

**Official API documentation**
- https://documentation.pubg.com/en/telemetry-objects.html
- https://raw.githubusercontent.com/pubg/api-documentation-content/master/rst/telemetry-objects.rst (the reStructuredText source behind the page above — used to confirm exact wording)

**Official asset repo (`pubg/api-assets`, default branch `master`)**
- https://api.github.com/repos/pubg/api-assets/contents/ (root listing)
- https://api.github.com/repos/pubg/api-assets/contents/Assets
- https://api.github.com/repos/pubg/api-assets/contents/Assets/Maps (full file listing + byte sizes)
- https://api.github.com/repos/pubg/api-assets/contents/Assets/MapSelection
- https://api.github.com/repos/pubg/api-assets/contents/Assets/Icons/Map
- https://api.github.com/repos/pubg/api-assets/contents/Assets/Item
- https://api.github.com/repos/pubg/api-assets/contents/Assets/Vehicle
- https://api.github.com/repos/pubg/api-assets/contents/dictionaries
- https://api.github.com/repos/pubg/api-assets/contents/dictionaries/telemetry
- https://api.github.com/repos/pubg/api-assets/contents/dictionaries/telemetry/item
- https://api.github.com/repos/pubg/api-assets/contents/dictionaries/telemetry/vehicle
- https://api.github.com/repos/pubg/api-assets/contents/enums
- https://api.github.com/repos/pubg/api-assets/contents/enums/telemetry
- https://api.github.com/repos/pubg/api-assets/contents/enums/telemetry/item
- https://api.github.com/repos/pubg/api-assets/contents/enums/telemetry/vehicle
- https://api.github.com/repos/pubg/api-assets/commits?per_page=20
- https://raw.githubusercontent.com/pubg/api-assets/master/README.md
- https://raw.githubusercontent.com/pubg/api-assets/master/Assets/Maps/.gitattributes
- https://raw.githubusercontent.com/pubg/api-assets/master/Assets/Maps/Erangel_Main_High_Res.png (confirmed to be an LFS pointer)
- https://raw.githubusercontent.com/pubg/api-assets/master/dictionaries/telemetry/mapName.json
- https://raw.githubusercontent.com/pubg/api-assets/master/dictionaries/telemetry/damageCauserName.json
- https://raw.githubusercontent.com/pubg/api-assets/master/dictionaries/telemetry/damageTypeCategory.json
- https://raw.githubusercontent.com/pubg/api-assets/master/dictionaries/telemetry/item/itemId.json
- https://raw.githubusercontent.com/pubg/api-assets/master/dictionaries/telemetry/vehicle/vehicleId.json
- https://raw.githubusercontent.com/pubg/api-assets/master/dictionaries/gameMode.json
- https://raw.githubusercontent.com/pubg/api-assets/master/enums/telemetry/objectType.json
- https://raw.githubusercontent.com/pubg/api-assets/master/enums/telemetry/item/category.json
- https://raw.githubusercontent.com/pubg/api-assets/master/enums/telemetry/item/subCategory.json
- https://raw.githubusercontent.com/pubg/api-assets/master/enums/telemetry/vehicle/vehicleType.json
- https://media.githubusercontent.com/media/pubg/api-assets/master/Assets/Maps/*.png (LFS media endpoint — HTTP Range requests used to read PNG IHDR headers for all 26 High_Res and all 26 Low_Res files — 52 images, 53 directory entries including `.gitattributes`)

**Independent open-source consumers (cross-check)**
- https://raw.githubusercontent.com/pubgsh/client/master/src/components/MatchPlayer/Map/index.js (pubg.sh — `MAP_SIZES`)
- https://raw.githubusercontent.com/pubgsh/client/master/src/lib/canvas-math.js (pubg.sh — `toScale`, the 8160/8192 correction)
- https://raw.githubusercontent.com/pubgsh/client/master/src/components/MatchPlayer/Map/PlayerDot.js (pubg.sh — no y-flip)
- https://api.github.com/repos/pubgsh/client/git/trees/master?recursive=1
- https://raw.githubusercontent.com/crflynn/chicken-dinner/master/chicken_dinner/constants.py (`map_dimensions` — **stale, see warning**)
- https://raw.githubusercontent.com/crflynn/chicken-dinner/master/chicken_dinner/visual/playback.py (y-axis handling)
- https://chicken-dinner.readthedocs.io/en/latest/assets/assets.html

**Background / map dimensions in km**
- https://www.pcgamesn.com/playerunknowns-battlegrounds/pubg-map (updated 2026-06-02; current map roster)
- https://liquipedia.net/pubg/Vikendi_Reborn
- https://www.krafton.com/en/news/press/vikendi-is-reborn-in-pubg-battlegrounds/

---

## 1. Repository layout: `pubg/api-assets`

Default branch is **`master`** (not `main`). Raw file URL pattern:

```
https://raw.githubusercontent.com/pubg/api-assets/master/<path>
```

Root:

```
api-assets/
├── .gitignore
├── README.md
├── seasons.json
├── survivalTitles.json
├── Assets/
│   ├── Icons/
│   ├── Item/          # Ammunition, Attachment, Equipment, Use, Weapon
│   ├── Logos/
│   ├── MapSelection/
│   ├── Maps/          # <-- the big map images
│   ├── Mastery/
│   ├── Teams/
│   └── Vehicle/
├── dictionaries/
│   ├── gameMode.json
│   ├── telemetry/
│   │   ├── damageCauserName.json
│   │   ├── damageTypeCategory.json
│   │   ├── mapName.json
│   │   ├── item/itemId.json
│   │   └── vehicle/vehicleId.json
│   └── weaponMastery/
└── enums/
    └── telemetry/
        ├── attackType.json
        ├── carryState.json
        ├── damageReason.json
        ├── objectType.json
        ├── objectTypeStatus.json
        ├── regionId.json
        ├── weatherId.json
        ├── item/{category.json, subCategory.json}
        └── vehicle/vehicleType.json
```

> **Repo freshness:** the most recent commit to `pubg/api-assets` is **2024-10-28, "31.2 Map image update (#269)"**. The repo has been dormant for ~21 months as of 2026-07-22. Treat its dictionaries as a *floor*, not a complete list — telemetry will contain IDs that are absent from these files. Always fall back to the raw ID string rather than dropping the record.

### 1.1 `Assets/Maps/` — exact file listing

Verified complete listing (53 entries incl. `.gitattributes`). Sizes are the bytes stored in git.

| File | Bytes in git | Real content |
|---|---:|---|
| `.gitattributes` | 50 | `*High_Res.png filter=lfs diff=lfs merge=lfs -text` |
| `Boardwalk_No_Text_High_Res.png` | 133 | LFS pointer → ⚠️ PNG **4096×4096**, not 8192 |
| `Boardwalk_No_Text_Low_Res.png` | 958,352 | PNG 819×819 |
| `Camp_Jackal_Main_High_Res.png` | 133 | LFS pointer |
| `Camp_Jackal_Main_Low_Res.png` | 1,022,159 | PNG 819×819 |
| `Camp_Jackal_Main_No_Text_High_Res.png` | 133 | LFS pointer |
| `Camp_Jackal_Main_No_Text_Low_Res.png` | 1,010,055 | PNG 819×819 |
| `Deston_Main_High_Res.png` | 133 | LFS pointer |
| `Deston_Main_Low_Res.png` | 1,302,148 | PNG 819×819 |
| `Deston_Main_No_Text_High_Res.png` | 133 | LFS pointer |
| `Deston_Main_No_Text_Low_Res.png` | 1,291,710 | PNG 819×819 |
| `Erangel_Main_High_Res.png` | 133 | LFS pointer → 94,773,167 B |
| `Erangel_Main_Low_Res.png` | 1,150,033 | PNG 819×819 |
| `Erangel_Main_No_Text_High_Res.png` | 133 | LFS pointer |
| `Erangel_Main_No_Text_Low_Res.png` | 1,141,311 | PNG 819×819 |
| `Haven_Main_High_Res.png` | 133 | LFS pointer |
| `Haven_Main_Low_Res.png` | 1,113,915 | PNG 819×819 |
| `Haven_Main_No_Text_High_Res.png` | 133 | LFS pointer |
| `Haven_Main_No_Text_Low_Res.png` | 1,107,716 | PNG 819×819 |
| `Italy_Bomb_No_Text_High_Res.png` | 133 | LFS pointer |
| `Italy_Bomb_No_Text_Low_Res.png` | 677,022 | PNG 819×819 |
| `Karakin_Main_High_Res.png` | 133 | LFS pointer |
| `Karakin_Main_Low_Res.png` | 1,202,169 | PNG 819×819 |
| `Karakin_Main_No_Text_High_Res.png` | 133 | LFS pointer |
| `Karakin_Main_No_Text_Low_Res.png` | 1,197,491 | PNG 819×819 |
| `Miramar_Main_High_Res.png` | 134 | LFS pointer |
| `Miramar_Main_Low_Res.png` | 1,464,459 | PNG 819×819 |
| `Miramar_Main_No_Text_High_Res.png` | 134 | LFS pointer |
| `Miramar_Main_No_Text_Low_Res.png` | 1,452,988 | PNG 819×819 |
| `Paramo_Main_High_Res.png` | 133 | LFS pointer |
| `Paramo_Main_Low_Res.png` | 1,321,649 | PNG 819×819 |
| `Paramo_Main_No_Text_High_Res.png` | 133 | LFS pointer |
| `Paramo_Main_No_Text_Low_Res.png` | 1,330,875 | PNG 819×819 |
| `Rondo_Main_High_Res.png` | 134 | LFS pointer |
| `Rondo_Main_Low_Res.png` | **53,914** | ⚠️ **JPEG** 819×819 (see §5) |
| `Rondo_Main_No_Text_High_Res.png` | 134 | LFS pointer |
| `Rondo_Main_No_Text_Low_Res.png` | 1,675,592 | PNG 819×819 |
| `Sanhok_Main_High_Res.png` | 133 | LFS pointer |
| `Sanhok_Main_Low_Res.png` | 1,069,220 | PNG 819×819 |
| `Sanhok_Main_No_Text_High_Res.png` | 133 | LFS pointer |
| `Sanhok_Main_No_Text_Low_Res.png` | 1,058,508 | PNG 819×819 |
| `Taego_Main_High_Res.png` | 134 | LFS pointer |
| `Taego_Main_Low_Res.png` | 1,368,588 | PNG 819×819 |
| `Taego_Main_No_Text_High_Res.png` | 134 | LFS pointer |
| `Taego_Main_No_Text_Low_Res.png` | 1,361,111 | PNG 819×819 |
| `Training_Main_High_Res.png` | 133 | LFS pointer |
| `Training_Main_Low_Res.png` | 1,022,159 | PNG 819×819 |
| `Training_Main_No_Text_High_Res.png` | 133 | LFS pointer |
| `Training_Main_No_Text_Low_Res.png` | 1,010,055 | PNG 819×819 |
| `Vikendi_Main_High_Res.png` | 134 | LFS pointer |
| `Vikendi_Main_Low_Res.png` | 1,389,189 | PNG 819×819 |
| `Vikendi_Main_No_Text_High_Res.png` | 134 | LFS pointer |
| `Vikendi_Main_No_Text_Low_Res.png` | 1,383,799 | PNG 819×819 |

### 1.2 Naming convention

```
Assets/Maps/{AssetBaseName}[_No_Text]_{High_Res|Low_Res}.png
```

- `{AssetBaseName}` is almost always `<DisplayName>_Main` — **the display name, NOT the telemetry `mapName`**. See §2.2.
- `_No_Text` = same image with place-name labels removed. Use this as the heatmap/replay basemap; the labelled variant is for static "browse the map" views.
- Two entries have **no labelled variant at all** — `Boardwalk` and `Italy_Bomb` exist only as `*_No_Text_*`, and their base name has no `_Main` suffix.

### 1.3 Resolutions (measured, not documented)

Verified by reading PNG `IHDR` / JPEG `SOF0` headers over HTTP Range requests on every file:

Coverage: **26/26 High_Res** and **26/26 Low_Res** files measured individually (52 images total).

| Variant | Dimensions | Format | Storage |
|---|---|---|---|
| `*_High_Res.png` | **8192 × 8192** — 25 of 26 files; ⚠️ **`Boardwalk_No_Text_High_Res.png` is 4096 × 4096** | PNG, bit depth 8; colour type 2 (truecolor) except type 6 (truecolor+alpha) on the Paramo files | **Git LFS** |
| `*_Low_Res.png` | **819 × 819** (all 26) | PNG, bit depth 8; colour type 2 except type 6 on `Paramo_Main_Low_Res.png`, `Paramo_Main_No_Text_Low_Res.png`, `Rondo_Main_No_Text_Low_Res.png`; one file is actually JPEG | plain git blob |

⚠️ **Do not hard-code 8192 for High_Res.** `Boardwalk_No_Text_High_Res.png` is 4096 × 4096 (IHDR bytes 16–23 = `00 00 10 00 00 00 10 00`); anything assuming 8192 mis-scales every Boardwalk overlay by exactly 2×. Read the IHDR per file.

⚠️ **Do not assume 3 bytes/pixel.** IHDR byte 25 (colour type) is `0x02` for most files but `0x06` (truecolor + alpha) for all four Paramo files (`Paramo_Main_High_Res`, `Paramo_Main_Low_Res`, `Paramo_Main_No_Text_High_Res`, `Paramo_Main_No_Text_Low_Res`) and for `Rondo_Main_No_Text_Low_Res.png`. A decoder or buffer assuming RGB will produce a channel-shifted image, and the alpha channel means Paramo tiles may composite with transparency rather than opaquely. Bit depth is uniformly 8.

Aside from the Boardwalk exception there are only these two resolutions. `819` is exactly `floor(8192 / 10)`, so Low_Res is a ~1:10 downscale — it is **not** a power of two and is **not** 1024.

### 1.4 Git LFS — the High_Res trap

`Assets/Maps/.gitattributes` contains exactly one line:

```
*High_Res.png filter=lfs diff=lfs merge=lfs -text
```

So `raw.githubusercontent.com` returns a **133–134 byte text pointer**, not an image:

```
version https://git-lfs.github.com/spec/v1
oid sha256:5dc33eac3af60b375cb0e29b7648132dbaa164c75c0310368e8ae585bcbecc45
size 94773167
```

To fetch actual High_Res bytes use the **LFS media host** (verified working, supports HTTP `Range`):

```
https://media.githubusercontent.com/media/pubg/api-assets/master/Assets/Maps/Erangel_Main_No_Text_High_Res.png
```

| Purpose | Host |
|---|---|
| Low_Res images, all JSON | `raw.githubusercontent.com` |
| High_Res images | `media.githubusercontent.com/media` |

High_Res files are ~50–95 MB **each**. Erangel alone is 94,773,167 bytes. Do not ship them to a browser; downscale/tile them at build time.

### 1.5 Other map-related asset directories

`Assets/MapSelection/` — map-picker thumbnails, bare display names, **inconsistent extensions and a literal space**:

```
Camp_Jackal.png   Erangel.png   Karakin.jpg   Miramar.png
Paramo.png        Sanhok.png    Vikendi.png   Vikendi [deprecated].png
```

`Assets/Icons/Map/` — small icons, and these **do use telemetry `mapName` codes**, unlike `Assets/Maps/`:

```
Desert_Main.png                Desert_Main_Large.png
DihorOtok_Main.png             DihorOtok_Main_Large.png
Erangel_Main.png               Erangel_Main_Large.png
Range_Main.png                 Range_Main_Transparent.png
Savage_Main.png                Savage_Main_Large.png
Summerland_Main.png            Summerland_Main_Large.png
Summerland_Main_Transparent.png Summerland_Main_Transparent_Large.png
```

Note this icon set is badly out of date — no Taego, Deston, Haven, Paramo, Rondo, or Baltic.

---

## 2. Map identity

### 2.1 `dictionaries/telemetry/mapName.json` — verbatim, complete

`https://raw.githubusercontent.com/pubg/api-assets/master/dictionaries/telemetry/mapName.json`

```json
{
  "Baltic_Main": "Erangel (Remastered)",
  "Chimera_Main": "Paramo",
  "Desert_Main": "Miramar",
  "DihorOtok_Main": "Vikendi",
  "Erangel_Main": "Erangel",
  "Heaven_Main": "Haven",
  "Kiki_Main": "Deston",
  "Range_Main": "Camp Jackal",
  "Savage_Main": "Sanhok",
  "Summerland_Main": "Karakin",
  "Tiger_Main": "Taego",
  "Neon_Main": "Rondo"
}
```

Flat `Record<string, string>`. Exactly 12 keys. Note the file is *almost* alphabetical but `Neon_Main` was appended at the end (commit #252, 2023-12-07) — do not rely on key order.

### 2.2 The master mapping table

This is the table to hard-code. `mapName` comes from telemetry (`LogMatchStart.mapName`) and from the match `attributes.mapName`.

| `mapName` (telemetry) | Display name | `Assets/Maps` base name | Size (km) | Telemetry world size (cm) |
|---|---|---|---:|---:|
| `Baltic_Main` | Erangel (Remastered) | `Erangel_Main` | 8×8 | 816000 |
| `Erangel_Main` | Erangel | `Erangel_Main` | 8×8 | 816000 |
| `Desert_Main` | Miramar | `Miramar_Main` | 8×8 | 816000 |
| `Savage_Main` | Sanhok | `Sanhok_Main` | 4×4 | 408000 |
| `DihorOtok_Main` | Vikendi | `Vikendi_Main` | 8×8 ¹ | 816000 ¹ |
| `Summerland_Main` | Karakin | `Karakin_Main` | 2×2 | 204000 |
| `Chimera_Main` | Paramo | `Paramo_Main` | 3×3 | 306000 |
| `Heaven_Main` | Haven | `Haven_Main` | 1×1 | 102000 |
| `Tiger_Main` | Taego | `Taego_Main` | 8×8 | 816000 |
| `Kiki_Main` | Deston | `Deston_Main` | 8×8 | 816000 |
| `Neon_Main` | Rondo | `Rondo_Main` | 8×8 | 816000 ² |
| `Range_Main` | Camp Jackal | `Camp_Jackal_Main` | 2×2 | 204000 |
| ⚠️ *unknown* | Training Range | `Training_Main` | ? | ? |
| ⚠️ *unknown* | Boardwalk (TDM) | `Boardwalk` (No_Text only) | ? | ? |
| ⚠️ *unknown* | Italy / Bomb (TDM) | `Italy_Bomb` (No_Text only) | ? | ? |

¹ **Vikendi is the trap.** Vikendi shipped as a 6×6 km map, but *Vikendi Reborn* (Update 21.1, PC 2022-12-06 / console 2022-12-15) rebuilt it as **8×8 km**. Current telemetry uses **816000**, confirmed by both the official docs sentence and pubg.sh's `MAP_SIZES`. Do **not** use 612000/614400 — that value only applies to pre-21.1 archived telemetry.

² Rondo is absent from the official docs sentence (docs predate it). 816000 comes from pubg.sh's `MAP_SIZES` plus the independently-reported 8×8 km map size.

**`Erangel_Main` is both a `mapName` and an asset base name, and they mean different things.** As a `mapName` it is the *legacy pre-remaster* Erangel; live matches report `Baltic_Main`. As an asset filename it is the *current* Erangel image. Both `mapName`s resolve to the same image file — that is correct behaviour, not a bug.

`Training_Main`, `Boardwalk` and `Italy_Bomb` have images but **no `mapName.json` entry**. Any lookup keyed on `mapName.json` will return `undefined` for those modes.

---

## 3. Coordinate system

### 3.1 Official statement

From `https://documentation.pubg.com/en/telemetry-objects.html`, the `Location` object:

```json
{
  "x": 0,
  "y": 0,
  "z": 0
}
```

| Field | Type | Meaning |
|---|---|---|
| `x` | number (float) | East–west, centimetres, increases **rightward** |
| `y` | number (float) | North–south, centimetres, increases **downward** |
| `z` | number (float) | Altitude, centimetres |

Verbatim from the docs (and from the `.rst` source in `pubg/api-documentation-content`):

> "Location values are measured in centimeters."
> "(0,0) is at the top-left of each map."
> "The range for the X and Y axes is 0 - 816,000 for Erangel, Miramar, Taego, Vikendi and Deston."
> "The range for the X and Y axes is 0 - 408,000 for Sanhok."
> "The range for the X and Y axes is 0 - 306,000 for Paramo."
> "The range for the X and Y axes is 0 - 204,000 for Karakin and Range."
> "The range for the X and Y axes is 0 - 102,000 for Haven."

### 3.2 Is the y axis inverted relative to image space? **No.**

Telemetry origin `(0,0)` is top-left with y increasing downward — **the same convention as an image raster, HTML canvas, CSS, and SVG.** Blit the map image at `(0,0)` and plot `y` directly. No flip.

Three independent confirmations:

1. **Official docs**: "(0,0) is at the top-left of each map."
2. **pubg.sh** (`PlayerDot.js`) applies the identical `toScale(...)` to `location.x` and `location.y` with no negation or `size - y` term — and it renders correctly in production.
3. **chicken-dinner** (`visual/playback.py`) computes `y = mapy - player_y` — but that is *because* it uses matplotlib with `ax.imshow(img, extent=[0, mapx, 0, mapy])`, which puts the origin at the **bottom-left**. The flip is required precisely because telemetry is top-left. This is the exception that proves the rule.

**Rule of thumb:** flip `y` only if your renderer's origin is bottom-left (matplotlib, OpenGL, WebGL NDC, plotly). Do not flip for canvas/SVG/CSS/PIL/img tags.

### 3.3 Telemetry → pixel conversion

The naïve formula (`x / worldSize * imageSize`) is **slightly wrong on 8×8 maps**. The map image is exported at 8192 px but only covers 8160 m of the telemetry world.

From pubg.sh `src/lib/canvas-math.js`. The executable line below is exact; the leading comment is **paraphrased** — the real file opens `/* From pubgsh/client#15:` and quotes an in-game JSON block containing `"InImageSizeX": 8128.0`, `"ImageSizeX": 8192.0`, and `"Bounds": [812775.0, 812775.0]`. (Note `812775` is a third, distinct extent constant — neither 816000 nor 819200.)

```javascript
// (paraphrase) The map images load in-game at 8128x8128 but export at 8192x8192,
// a scaling factor of 0.9921875. For telemetry the ratio is 8160/8192 = 0.99609375.
// Upstream source: pubgsh/client issue #15, which quotes in-game map data
// { "InImageSizeX": 8128.0, "ImageSizeX": 8192.0, "Bounds": [812775.0, 812775.0] }

// verbatim:
export const toScale = (pubgMapSize, mapSize, n) =>
    n / pubgMapSize * mapSize * (pubgMapSize === 816000 ? 0.99609375 : 1)
```

Written out:

```
K       = (worldSize === 816000) ? 0.99609375 : 1      // 0.99609375 === 8160/8192
pixel_x = (loc.x / worldSize) * imageSizePx * K
pixel_y = (loc.y / worldSize) * imageSizePx * K        // no flip
```

**Convenient identity:** for the 816000 maps against the 8192 px High_Res image this collapses exactly to

```
pixel = telemetryUnits / 100          // 1 px === 1 metre === 100 cm
```

because `(x / 816000) * 8192 * (8160/8192) = x / 100`. Against the 819 px Low_Res image it is `x / 1000.24` (≈ 1 px per 10 m).

For every non-816000 map, `K = 1` — the image is treated as an exact fit to the telemetry range. For Sanhok that means `8192 px / 4080 m ≈ 2.008 px per metre`, i.e. **the px-per-metre scale is different on every map**. Never hard-code a single px/metre constant.

### 3.4 Suggested constant table

```javascript
// worldSize in telemetry units (centimetres)
export const MAP_WORLD_SIZE = {
    Baltic_Main:     816000,  // Erangel (Remastered)
    Erangel_Main:    816000,  // legacy Erangel
    Desert_Main:     816000,  // Miramar
    DihorOtok_Main:  816000,  // Vikendi (post-Reborn; was 612000 pre-21.1)
    Tiger_Main:      816000,  // Taego
    Kiki_Main:       816000,  // Deston
    Neon_Main:       816000,  // Rondo
    Savage_Main:     408000,  // Sanhok
    Chimera_Main:    306000,  // Paramo
    Summerland_Main: 204000,  // Karakin
    Range_Main:      204000,  // Camp Jackal
    Heaven_Main:     102000,  // Haven
}

export const MAP_ASSET_BASE = {
    Baltic_Main: 'Erangel_Main',   Erangel_Main:    'Erangel_Main',
    Desert_Main: 'Miramar_Main',   Savage_Main:     'Sanhok_Main',
    DihorOtok_Main: 'Vikendi_Main', Summerland_Main: 'Karakin_Main',
    Chimera_Main: 'Paramo_Main',   Heaven_Main:     'Haven_Main',
    Tiger_Main:  'Taego_Main',     Kiki_Main:       'Deston_Main',
    Neon_Main:   'Rondo_Main',     Range_Main:      'Camp_Jackal_Main',
}
```

### 3.5 Reference values from other projects (for comparison only)

`chicken-dinner/chicken_dinner/constants.py`:

```python
map_dimensions = {
    "Desert_Main":    [819200, 819200],
    "Erangel_Main":   [819200, 819200],
    "Savage_Main":    [409600, 409600],
    "DihorOtok_Main": [614400, 614400],
    "Range_Main":     [204800, 204800],
    "Baltic_Main":    [819200, 819200],
    "Summerland_Main":[204800, 204800],
}
```

⚠️ **Do not use these.** They are round `2^n × 100` approximations (819200 = 8192×100), not the documented telemetry ranges, they predate Vikendi Reborn, and the dict stops at Karakin (no Paramo/Haven/Taego/Deston/Rondo). Included here only so the discrepancy is not rediscovered later.

---

## 4. Dictionaries and enums

### 4.1 Shape rule

| Directory | JSON shape | Purpose |
|---|---|---|
| `dictionaries/**` | **object** — `Record<rawId, humanReadableName>` | translate long telemetry IDs to display strings |
| `enums/**` | **array** — `string[]` | enumerate the legal values of a telemetry field |

Getting these two backwards is the single most common parsing bug against this repo.

### 4.2 `dictionaries/telemetry/item/itemId.json`

Path: `dictionaries/telemetry/item/itemId.json` (9,273 B). Flat object, no nesting.
Keys match `Item.itemId` in telemetry.

```json
{
  "Helmet_Repair_Kit_C": "Helmet Repair Kit",
  "InstantRevivalKit_C": "Critical Response Kit",
  "Item_Ammo_12GuageSlug_C": "12 Gauge Slug",
  "Item_Ammo_12Guage_C": "12 Gauge Ammo",
  "Item_Ammo_300Magnum_C": "300 Magnum Ammo",
  "Item_Ammo_40mm_C": "40mm Smoke Grenade",
  "Item_Ammo_45ACP_C": ".45 ACP Ammo",
  "Item_Ammo_556mm_C": "5.56mm Ammo",
  "Item_Ammo_762mm_C": "7.62mm Ammo",
  "Item_Armor_C_01_Lv3_C": "Military Vest (Level 3)",
  "Item_Armor_D_01_Lv2_C": "Police Vest (Level 2)",
  "Item_Attach_Weapon_Lower_AngledForeGrip_C": "Angled Foregrip",
  "Item_Attach_Weapon_Magazine_ExtendedQuickDraw_Large_C": "Extended QuickDraw Mag (AR, DMR, M249, S12K)"
}
```

Note `Item_Ammo_12Guage_C` — **"Guage" is misspelled in the game data** and the repo preserves it deliberately. The README states the casing and spelling are kept "consistent with the data", typos included.

### 4.3 `dictionaries/telemetry/vehicle/vehicleId.json`

Path: `dictionaries/telemetry/vehicle/vehicleId.json` (3,981 B). Flat object, **104 keys**.
Keys match `Vehicle.vehicleId`.

```json
{
  "AirBoat_V2_C": "Airboat",
  "AquaRail_A_01_C": "Aquarail",
  "AquaRail_A_02_C": "Aquarail",
  "AquaRail_C": "AquaRail",
  "BP_ATV_C": "Quad",
  "BP_BRDM_C": "BRDM-2",
  "BP_Bicycle_C": "Mountain Bike",
  "BP_Blanc_C": "Coupe SUV",
  "BP_DO_Circle_Train_Merged_C": "Train",
  "BP_Dirtbike_C": "Dirt Bike",
  "BP_EmergencyPickupVehicle_C": "Emergency Pickup",
  "BP_KillTruck_C": "Kill Truck",
  "BP_LootTruck_C": "Loot Truck",
  "BP_M_Rony_A_01_C": "Rony",
  "BP_McLarenGT_Lx_Yellow_C": "McLaren GT (Elite Yellow)",
  "BP_Mirado_A_03_Esports_C": "Mirado",
  "BP_Mirado_Open_03_C": "Mirado (open top)"
}
```

Many distinct IDs collapse to one display name (`AquaRail_A_01_C`, `_A_02_C`, `_A_03_C` → "Aquarail"). Aggregate on the **value**, not the key, when counting vehicle usage. Also note `AquaRail_C` → `"AquaRail"` while `AquaRail_A_01_C` → `"Aquarail"` — inconsistent capitalisation *in the values*.

### 4.4 `dictionaries/telemetry/damageCauserName.json`

Path: `dictionaries/telemetry/damageCauserName.json` (7,497 B). Flat object, **209 keys**.
Keys match `damageCauserName` on `LogPlayerTakeDamage` / `LogPlayerKillV2`.

```json
{
  "AIPawn_Base_Female_C": "AI Player",
  "AIPawn_Base_Male_C": "AI Player",
  "AirBoat_V2_C": "Airboat",
  "BP_ATV_C": "Quad",
  "BP_BRDM_C": "BRDM-2",
  "BP_BearV2_C": "Bear",
  "BP_DronePackage_Projectile_C": "Drone",
  "BP_Eragel_CargoShip01_C": "Ferry Damage",
  "BP_FakeLootProj_AmmoBox_C": "Loot Truck",
  "BP_FireEffectController_C": "Molotov Fire",
  "BP_FireEffectController_JerryCan_C": "Jerrycan Fire",
  "BP_Helicopter_C": "Pillar Scout Helicopter",
  "BP_IncendiaryDebuff_C": "Burn"
}
```

`BP_Eragel_CargoShip01_C` — "Eragel", another preserved typo. Match on the literal string.

### 4.5 `dictionaries/telemetry/damageTypeCategory.json` — complete, 43 keys

```json
{
  "Damage_Blizzard": "Blizzard Damage",
  "Damage_BlueZone": "Bluezone Damage",
  "Damage_BlueZoneGrenade": "Bluezone Grenade Damage",
  "Damage_DronePackage": "Drone Damage",
  "Damage_Drown": "Drowning Damage",
  "Damage_Explosion_Aircraft": "Aircraft Explosion Damage",
  "Damage_Explosion_BlackZone": "Blackzone Damage",
  "Damage_Explosion_Breach": "Breach Explosion Damage",
  "Damage_Explosion_C4": "C4 Explosion Damage",
  "Damage_Explosion_GasPump": "Gas Pump Explosion",
  "Damage_Explosion_Grenade": "Grenade Explosion Damage",
  "Damage_Explosion_JerryCan": "Jerrycan Explosion Damage",
  "Damage_Explosion_LootTruck": "Loot Truck Explosion Damage",
  "Damage_Explosion_Mortar": "Mortar Explosion",
  "Damage_Explosion_PanzerFaustBackBlast": "Panzerfaust Backblast Damage",
  "Damage_Explosion_PanzerFaustWarhead": "Panzerfaust Explosion Damage",
  "Damage_Explosion_PanzerFaustWarheadVehicleArmorPenetration": "Panzerfaust Explosion Damage",
  "Damage_Explosion_PropaneTank": "Propane Tank",
  "Damage_Explosion_RedZone": "Redzone Explosion Damage",
  "Damage_Explosion_StickyBomb": "Sticky Bomb Explosion Damage",
  "Damage_Explosion_Vehicle": "Vehicle Explosion Damage",
  "Damage_Groggy": "Bleed out damage",
  "Damage_Gun": "Gun Damage",
  "Damage_Gun_Penetrate_BRDM": "BRDM",
  "Damage_HelicopterHit": "Pillar Scout Helicopter Damage",
  "Damage_Instant_Fall": "Fall Damage",
  "Damage_KillTruckHit": "Kill Truck Hit",
  "Damage_KillTruckTurret": "Kill Truck Turret Damage",
  "Damage_Lava": "Lava Damage",
  "Damage_LootTruckHit": "Loot Truck Damage",
  "Damage_Melee": "Melee Damage",
  "Damage_MeleeThrow": "Melee Throw Damage",
  "Damage_Molotov": "Molotov Damage",
  "Damage_Monster": "Monster Damage",
  "Damage_MotorGlider": "Motor Glider Damage",
  "Damage_None": "No Damage",
  "Damage_Punch": "Punch Damage",
  "Damage_SandStorm": "Sandstorm Damage",
  "Damage_ShipHit": "Ferry Damage",
  "Damage_TrainHit": "Train Damage",
  "Damage_VehicleCrashHit": "Vehicle Crash Damage",
  "Damage_VehicleHit": "Vehicle Damage",
  "SpikeTrap": "Spike Trap damage"
}
```

`SpikeTrap` is the only key without the `Damage_` prefix. A regex like `/^Damage_/` will silently drop it.

### 4.6 `dictionaries/gameMode.json` — 39 keys (sample below)

```json
{
  "solo": "Solo TPP",           "solo-fpp": "Solo FPP",
  "duo": "Duo TPP",             "duo-fpp": "Duo FPP",
  "squad": "Squad TPP",         "squad-fpp": "Squad FPP",
  "normal-solo": "Solo TPP",    "normal-solo-fpp": "Solo FPP",
  "normal-duo": "Duo TPP",      "normal-duo-fpp": "Duo FPP",
  "normal-squad": "Squad TPP",  "normal-squad-fpp": "Squad FPP",
  "conquest-squad": "Conquest Squad TPP",
  "esports-squad": "Esports Squad TPP",
  "war-squad": "Squad TPP",
  "zombie-squad": "Zombie Squad TPP",
  "lab-tpp": "Lab TPP",         "lab-fpp": "Lab FPP",
  "tdm": "Team Deathmatch"
}
```

(Trimmed — the full file has the same solo/duo/squad × tpp/fpp expansion for `conquest-`, `esports-`, `war-`, `zombie-` prefixes.)

Traps: `normal-squad` and `squad` both display as "Squad TPP"; `war-squad` maps to `"Squad TPP"` while `war-squad-fpp` maps to `"War Squad FPP"` — an inconsistency in the source data, not a transcription error. `lab-tpp`/`lab-fpp` and `tdm` break the `<mode>-<size>[-fpp]` naming pattern entirely.

### 4.7 Enums (arrays)

`enums/telemetry/objectType.json` — complete:

```json
[
  "Caraudio", "Door", "DoubleSlidingDoor", "Fence", "FuelPuddle",
  "Hay", "Jerrycan", "JerryCan", "Jukebox", "JukeBox",
  "PropaneTank", "VendingMachine", "Window", "Ascender",
  "GasPump", "LockedDoor", "BulletproofShield", "Cartoplights"
]
```

⚠️ Contains **case-variant duplicates**: `Jerrycan`/`JerryCan` and `Jukebox`/`JukeBox` are both live values. A case-insensitive `Set` will silently collapse them; a case-sensitive `switch` must handle both.

`enums/telemetry/item/category.json`:

```json
["Ammunition", "Attachment", "Equipment", "Event", "Use", "Weapon"]
```

`enums/telemetry/item/subCategory.json`:

```json
[
  "Backpack", "Boost", "Fuel", "Gadget", "Handgun", "Headgear",
  "Heal", "Jacket", "Main", "Melee", "None", "Parachute",
  "Revive", "Sight", "Throwable", "Vest", "Ascender"
]
```

`enums/telemetry/vehicle/vehicleType.json`:

```json
[
  "EmergencyPickup", "FloatingVehicle", "FlyingVehicle",
  "Mortar", "Parachute", "TransportAircraft", "WheeledVehicle"
]
```

Note `category.json` lists `"Event"` but `Assets/Item/` has **no `Event/` folder** — only `Ammunition`, `Attachment`, `Equipment`, `Use`, `Weapon`. Icon lookups for `Event`-category items will 404.

---

## 5. Implementation notes

**Map images**

1. `Assets/Maps/` filenames are keyed by **display name**, `Assets/Icons/Map/` filenames are keyed by **`mapName` code**. Two different conventions inside the same repo. You need the `MAP_ASSET_BASE` translation table for `Assets/Maps/`.
2. `raw.githubusercontent.com` returns a 133-byte LFS pointer for every `*_High_Res.png`. If your image decoder is receiving ~133 bytes of ASCII, this is why. Use `media.githubusercontent.com/media/...`.
3. **`Rondo_Main_Low_Res.png` is a JPEG with a `.png` extension** (magic bytes `FF D8 FF`, 53,914 B, 819×819). Strict PNG decoders and anything trusting the extension will throw on exactly one file in the set. Sniff magic bytes, never trust the extension. `Rondo_Main_No_Text_Low_Res.png` *is* a real PNG — so if you use the No_Text variants throughout (recommended) you dodge this entirely.
4. `Camp_Jackal_Main_Low_Res.png` and `Training_Main_Low_Res.png` are byte-identical in size (1,022,159) — as are their No_Text pairs (1,010,055). They are almost certainly the same image duplicated.
5. Low_Res is **819×819**, an odd, non-power-of-two number. Don't assume 1024 and don't assume the two resolutions are related by a clean factor.
6. `Assets/MapSelection/` mixes `.png` and `.jpg`, and contains `Vikendi [deprecated].png` — a filename with a space and square brackets. URL-encode before requesting.

**Coordinates**

7. `y` is **not** inverted for image/canvas/SVG rendering. Only flip if your renderer's origin is bottom-left (matplotlib, WebGL).
8. Apply the `0.99609375` correction on 816000 maps or your points drift ~0.4% (≈32 m at the far edge of Erangel) — enough to put kills in the ocean.
9. px-per-metre differs per map. Derive it as `imageSizePx * K / worldSize`, never hard-code.
10. Coordinates are **centimetres as floats** and can legitimately exceed the documented range slightly (out-of-bounds/aircraft positions). Clamp before writing into a fixed-size heatmap bin array or you will index out of bounds.
11. `z` is also centimetres and is **not** bounded by the same range. Do not feed it through the x/y scale function.
12. `DihorOtok_Main` telemetry archived from before Update 21.1 (Dec 2022) uses the old 6×6 km world. If you ingest historical matches, gate the world size on match `createdAt`.

**Dictionaries**

13. `dictionaries/**` are objects, `enums/**` are arrays. Different shapes in sibling trees.
14. Typos are intentional and load-bearing: `Item_Ammo_12Guage_C`, `BP_Eragel_CargoShip01_C`. Never "fix" a key.
15. Casing is inconsistent *within* files: `Jerrycan` vs `JerryCan`, `Jukebox` vs `JukeBox`, `AquaRail` vs `Aquarail`. Do exact-match lookups; if you must normalise, do it on the display value only.
16. `SpikeTrap` has no `Damage_` prefix in `damageTypeCategory.json`.
17. Vehicle **asset** filenames use a `_00_` skin placeholder (`BP_Mirado_A_00_C.png`) while **telemetry** IDs carry real variant digits (`BP_Mirado_A_03_C`). To resolve an icon you must rewrite the variant segment to `00`. Some IDs don't map at all — telemetry `AirBoat_V2_C` vs asset `BP_Airboat_C.png`.
18. The repo is frozen at patch 31.2 (Oct 2024). Expect unknown `itemId`/`damageCauserName`/`vehicleId` values from live 2026 telemetry. Always render `dictionary[id] ?? id` — never drop unmapped rows.
19. `mapName.json` has no entry for the training range or the TDM maps, yet images for them exist. Guard the lookup.

---

## 6. ⚠️ Unverified / needs live confirmation

Items I could **not** confirm against an authoritative source. Verify each against a real telemetry file before relying on it.

1. **The `0.99609375` (8160/8192) correction factor is single-sourced.** It comes only from pubg.sh's `canvas-math.js` comment and implementation. It is not in any official PUBG documentation, and I found no second independent project stating it. pubg.sh is a long-running production replay viewer so the value is credible, but **confirm empirically**: take a `LogPlayerPosition` at a recognisable landmark on Erangel and check alignment with and without the factor. The related 8128×8128 in-game figure is **better sourced than "asserted"**: `canvas-math.js` cites upstream `pubgsh/client` issue #15 and quotes in-game map data (`"InImageSizeX": 8128.0`, `"ImageSizeX": 8192.0`, `"Bounds": [812775.0, 812775.0]`). Still worth confirming against a real telemetry file once the API key is wired up, along with what the `Bounds` value 812775 corresponds to.
2. **`Neon_Main` (Rondo) world size = 816000.** Not present in the official docs sentence (which predates Rondo). Sourced from pubg.sh `MAP_SIZES` plus the independently reported 8×8 km size. Very likely correct; not officially documented.
3. **Whether `K = 1` is genuinely correct for the non-816000 maps.** pubg.sh applies the correction *only* when `worldSize === 816000`. I could not find a statement explaining why Sanhok/Karakin/Paramo/Haven would be exact-fit while the 8×8 maps are not. Verify Sanhok alignment separately.
4. **`mapName` values for the training range and TDM maps.** `Training_Main`, `Boardwalk`, `Italy_Bomb` exist as image assets with no `mapName.json` entry. Whether telemetry emits those exact strings as `mapName` is unconfirmed, as are their world sizes.
5. **Whether `Erangel_Main` (legacy) still appears in any live telemetry.** It is in `mapName.json`, but live matches are believed to report `Baltic_Main`. Unconfirmed which value the current API actually emits — check `LogMatchStart.mapName` on a fresh match.
6. **Exact `worldSize` for pre-21.1 Vikendi.** Widely cited as 612000 (docs-style) or 614400 (chicken-dinner). I did not find an authoritative statement, and the current docs only give the post-Reborn 816000.
7. **Any map released after Rondo (Dec 2023).** `mapName.json` ends at `Neon_Main`, the repo's last commit is Oct 2024, and a map roster page updated 2026-06-02 lists nine maps ending at Rondo. But given a ~21-month asset-repo gap I cannot rule out a newer map with an undocumented `mapName`. Handle unknown `mapName` gracefully.
8. **Whether `Camp_Jackal_Main` and `Training_Main` images are truly identical.** Inferred from identical byte counts, not from a hash comparison.
9. **Colour profile / exact geographic registration of the `_No_Text` variants.** GitHub issue #60 in `pubg/api-assets` reports "Text-free asset of Miramar map is outdated". I did not verify whether the No_Text variants are pixel-aligned with, or the same patch version as, their labelled counterparts. If overlays look offset on Miramar, this is the first thing to check.
10. **`weaponMastery/`, `seasons.json`, `survivalTitles.json`, `Assets/Icons`, `Assets/Logos`, `Assets/Mastery`, `Assets/Teams` contents.** Out of scope for this dimension; listed but not enumerated or shape-checked.
