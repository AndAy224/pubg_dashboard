# PUBG Telemetry — World / Game-State Events Reference

**Scope:** everything needed to render zones, vehicles, care packages, the plane, and match
lifecycle on a 2D replay. Player-combat events (`LogPlayerKillV2`, `LogPlayerAttack`,
`LogPlayerTakeDamage`, …) are deliberately out of scope except where they carry world state.

**Status:** compiled 2026-07-22 from the sources below. Every field name in the main body was
confirmed against **at least two independent sources**. Anything confirmed by only one source, or
by none, is tagged **⚠️ UNVERIFIED** inline and repeated in the final section.

---

## Sources

Fetched directly while writing this document:

**Official (KRAFTON/PUBG):**

1. https://documentation.pubg.com/en/telemetry-events.html
2. https://documentation.pubg.com/en/telemetry-objects.html
3. https://documentation.pubg.com/en/changelog/changelog.html
4. https://documentation.pubg.com/en/known-issues.html
5. https://raw.githubusercontent.com/pubg/api-documentation-content/master/rst/telemetry-events.rst — RST source of (1)
6. https://raw.githubusercontent.com/pubg/api-documentation-content/master/rst/telemetry-objects.rst — RST source of (2)
7. https://raw.githubusercontent.com/pubg/api-documentation-content/master/rst/telemetry.rst
8. https://raw.githubusercontent.com/pubg/api-documentation-content/master/rst/changelog/changelog.rst — RST source of (3)
9. https://raw.githubusercontent.com/pubg/api-documentation-content/master/rst/known-issues.rst — RST source of (4)
10. https://github.com/pubg/api-assets/tree/master/enums/telemetry — directory listing
11. https://github.com/pubg/api-assets/tree/master/enums/telemetry/vehicle — directory listing
12. https://github.com/pubg/api-assets/tree/master/dictionaries/telemetry — directory listing
13. https://raw.githubusercontent.com/pubg/api-assets/master/enums/telemetry/vehicle/vehicleType.json
14. https://raw.githubusercontent.com/pubg/api-assets/master/enums/telemetry/objectType.json
15. https://raw.githubusercontent.com/pubg/api-assets/master/enums/telemetry/weatherId.json
16. https://raw.githubusercontent.com/pubg/api-assets/master/enums/telemetry/carryState.json
17. https://raw.githubusercontent.com/pubg/api-assets/master/enums/telemetry/regionId.json
18. https://raw.githubusercontent.com/pubg/api-assets/master/dictionaries/telemetry/vehicle/vehicleId.json
19. https://raw.githubusercontent.com/pubg/api-assets/master/dictionaries/telemetry/mapName.json
20. https://raw.githubusercontent.com/pubg/api-assets/master/dictionaries/telemetry/damageTypeCategory.json

**Independent open-source consumers (used to cross-check and to catch doc errors):**

21. https://raw.githubusercontent.com/pubgsh/client/master/src/models/Telemetry.parser.js — the
    replay parser behind **pubg.sh / chickendinner.gg**. The single most relevant prior art.
22. https://raw.githubusercontent.com/pubgsh/client/master/src/models/Telemetry.js
23. https://raw.githubusercontent.com/ramonsaraiva/pubg-python/master/pubg_python/domain/telemetry/events.py
24. https://raw.githubusercontent.com/ramonsaraiva/pubg-python/master/pubg_python/domain/telemetry/objects.py
25. https://raw.githubusercontent.com/NovikovRoman/pubg/master/telemetry_events.go
26. https://raw.githubusercontent.com/NovikovRoman/pubg/master/telemetry_objects.go
27. https://raw.githubusercontent.com/crflynn/chicken-dinner/master/chicken_dinner/models/telemetry/telemetry.py
28. https://raw.githubusercontent.com/crflynn/chicken-dinner/master/chicken_dinner/models/telemetry/events.py
29. https://chicken-dinner.readthedocs.io/en/latest/models/telemetry.html
30. https://raw.githubusercontent.com/rico0821/pubg_map/master/telemetry.py — flight-path fitting
31. https://gist.github.com/nikicat/b4922c2cdc86e91c3af7b7667640d67d — flattened field-path dump
    from a real telemetry corpus (**old — circa 2018**, treat as historical evidence only)

**Attempted and failed (recorded so nobody repeats them):**

- `https://telemetry-cdn.pubg.com/...` and `https://telemetry-cdn.playbattlegrounds.com/...` for the
  sample URLs published in the docs and in community issues → **HTTP 403** for all three tried.
  Old telemetry blobs are no longer served. **No live 2026-era telemetry file could be fetched**,
  so nothing here is confirmed against a freshly captured match. See the ⚠️ section.
- `grep.app` code search → HTTP 429 on every attempt.

---

## 0. Ground rules before you parse anything

### 0.1 File format

- Telemetry is a **single JSON array of event objects**, ordered by time, served from a public CDN.
  No API key is required to download the telemetry file itself (only to discover its URL via the
  match endpoint). [Source 7]
- It is **gzip-compressed**. Send `Accept-Encoding: gzip`. This became mandatory in **v4.0.0**
  ("Telemetry data will be compressed using gzip"). [Sources 7, 8]
- Files are large (tens of MB uncompressed for a 100-player match). Stream-parse if you can.

### 0.2 The event envelope

Every event carries these keys, which the docs omit from the per-event outlines:

| Key | Type | Meaning |
| --- | --- | --- |
| `_D` | string | Event timestamp, ISO-8601 UTC, e.g. `2026-07-22T18:04:11.523Z`. **This is the only wall-clock time on most events.** |
| `_T` | string | Event type, e.g. `"LogGameStatePeriodic"`. **Discriminator — switch on this.** |
| `common` | object | `{ "isGame": number }` — see below. |
| `_V` | number | Undocumented schema/version marker. Present in real payloads. Confirmed by `chicken-dinner` (which explicitly whitelists `("_D", "_T", "_V")`) [28] and by the 2018 field dump [31]. Not in the official docs. |
| `_U` | ? | Appears in the 2018 field dump [31] only. **⚠️ UNVERIFIED** for modern telemetry — do not depend on it. |

```json
{
  "_D": "2026-07-22T18:04:11.523Z",
  "_T": "LogGameStatePeriodic",
  "_V": 1,
  "common": { "isGame": 2.5 },
  "gameState": { "...": "..." }
}
```

> All JSON blocks in this document use **exact confirmed key casing**; the *values* are
> illustrative unless stated otherwise, because no live telemetry file could be retrieved
> (see Sources → "Attempted and failed").

### 0.3 `common.isGame` — the match-phase clock

Verbatim from the official object docs [2, 6]:

```
isGame = 0   -> Before lift off
isGame = 0.1 -> On airplane
isGame = 0.5 -> When there's no 'zone' on map(before game starts)
isGame = 1.0 -> First safezone and bluezone appear
isGame = 1.5 -> First bluezone shrinks
isGame = 2.0 -> Second bluezone appears
isGame = 2.5 -> Second bluezone shrinks
...
```

| Value | Phase |
| --- | --- |
| `0` | Pre-lift-off (lobby / starting island) |
| `0.1` | **Players are in the plane** — the only reliable plane-phase marker |
| `0.5` | Dropped, no zone drawn yet |
| `1.0` | Zone *n* announced (white circle drawn) |
| `1.5` | Zone *n* closing (blue shrinking) |
| `2.0`, `2.5`, `3.0`, … | continues in `+0.5` steps |

Rule of thumb: `floor(isGame)` = phase number; `.0` = announce, `.5` = shrink.

### 0.4 Coordinate system

Verbatim from the object docs [2, 6]:

- "Location values are measured in **centimeters**."
- "**(0,0) is at the top-left of each map.**" → **`y` grows downward.** Screen-space friendly;
  do NOT flip `y` as if it were a maths plot.

**Not verbatim — inferred:** `z` is up (altitude, cm). The official Location section says nothing
about the `z` axis at all and publishes no `z` range. Very likely true, but unsourced. ⚠️

| Map (`mapName`) | Display name | X/Y range (cm) |
| --- | --- | --- |
| `Baltic_Main` | Erangel (Remastered) | 0 – 816,000 ⚠️ inferred from display name |
| `Erangel_Main` | Erangel | 0 – 816,000 |
| `Desert_Main` | Miramar | 0 – 816,000 |
| `Tiger_Main` | Taego | 0 – 816,000 |
| `DihorOtok_Main` | Vikendi | 0 – 816,000 |
| `Kiki_Main` | Deston | 0 – 816,000 |
| `Neon_Main` | Rondo | ⚠️ UNVERIFIED — not in the docs' range list; 8×8 km map so almost certainly 816,000 |
| `Savage_Main` | Sanhok | 0 – 408,000 |
| `Chimera_Main` | Paramo | 0 – 306,000 |
| `Summerland_Main` | Karakin | 0 – 204,000 |
| `Range_Main` | Camp Jackal | 0 – 204,000 ⚠️ inferred from display name |
| `Heaven_Main` | Haven | 0 – 102,000 |

Range list from [2, 6]; `mapName` keys and display names from the official dictionary [19].

> **Inference disclosure.** The official Location note gives ranges by **display name**, not by
> `mapName` key: *"0 - 816,000 for Erangel, Miramar, Taego, Vikendi and Deston"* and
> *"0 - 204,000 for Karakin and Range"*. `mapName.json` [19] maps `Baltic_Main` → "Erangel
> (Remastered)" (a *different* display name from "Erangel") and `Range_Main` → "Camp Jackal"
> (not "Range"). Both rows are therefore high-confidence inferences, the same class of inference
> flagged for `Neon_Main` — not directly sourced.

> **Scale trap:** an "8×8 km" map is 816,000 cm, i.e. **102,000 cm per nominal km, not 100,000.**
> Normalise by the *table value for that map*, never by a hard-coded 100,000/km.
> `normX = x / range`, `normY = y / range`, then multiply by your map-image pixel size.

---

## 1. `LogGameStatePeriodic` — the zone heartbeat

The only event that carries zone geometry. Emitted periodically for the whole match.

```json
{
  "_D": "2026-07-22T18:12:40.117Z",
  "_T": "LogGameStatePeriodic",
  "common": { "isGame": 3.5 },
  "gameState": {
    "elapsedTime": 742,
    "numAliveTeams": 21,
    "numJoinPlayers": 98,
    "numStartPlayers": 98,
    "numAlivePlayers": 54,
    "safetyZonePosition":       { "x": 402150.5, "y": 318740.2, "z": 0.0 },
    "safetyZoneRadius":         84120.0,
    "poisonGasWarningPosition": { "x": 398320.1, "y": 331002.9, "z": 0.0 },
    "poisonGasWarningRadius":   50472.0,
    "redZonePosition":          { "x": 511200.0, "y": 240880.0, "z": 0.0 },
    "redZoneRadius":            0.0,
    "blackZonePosition":        { "x": 0.0, "y": 0.0, "z": 0.0 },
    "blackZoneRadius":          0.0
  }
}
```

### `GameState` object

| Field | Type | Meaning |
| --- | --- | --- |
| `elapsedTime` | int | Seconds since match start. **Use this as the replay clock**, not `_D`. |
| `numAliveTeams` | int | Teams still alive. |
| `numJoinPlayers` | int | Players who joined the lobby. |
| `numStartPlayers` | int | Players at match start. |
| `numAlivePlayers` | int | Players still alive. |
| `safetyZonePosition` | `{Location}` | **Centre of the CURRENT playable circle — render this as the BLUE zone.** See §1.1. |
| `safetyZoneRadius` | number | Radius, cm. |
| `poisonGasWarningPosition` | `{Location}` | **Centre of the NEXT circle — render this as the WHITE circle.** See §1.1. |
| `poisonGasWarningRadius` | number | Radius, cm. |
| `redZonePosition` | `{Location}` | Red-zone centre. All-zeros / radius 0 when no red zone is active. |
| `redZoneRadius` | number | Radius, cm. |
| `blackZonePosition` | `{Location}` | Black-zone centre (Haven). Added **v16.1.0** (PC) / **v16.2.0** (console). |
| `blackZoneRadius` | number | Radius, cm. |

Confirmed identically by [2], [6], [24] (pubg-python), [26] (Go), [27] (chicken-dinner), [21] (pubg.sh).

### 1.1 ⚠️ THE BIGGEST TRAP IN THE WHOLE API — zone naming is inverted

The field names read backwards from what they render as. **`safetyZone*` is the blue circle.
`poisonGasWarning*` is the white circle.**

Two independent replay renderers agree, verbatim:

`pubg.sh` / `chickendinner.gg` [21]:

```javascript
if (d._T === 'LogGameStatePeriodic') {
    const gs = d.gameState

    curState.bluezone = {
        ...gs.safetyZonePosition,
        radius: gs.safetyZoneRadius,
    }

    curState.safezone = {
        ...gs.poisonGasWarningPosition,
        radius: gs.poisonGasWarningRadius,
    }

    curState.redzone = {
        ...gs.redZonePosition,
        radius: gs.redZoneRadius,
    }
}
```

`chicken-dinner` [27]:

```python
circle_positions["blue"].append((dt, gs.safety_zone_position.x, ..., gs.safety_zone_radius))
circle_positions["red"].append((dt, gs.red_zone_position.x, ..., gs.red_zone_radius))
circle_positions["white"].append((dt, gs.poison_gas_warning_position.x, ..., gs.poison_gas_warning_radius))
```

| Telemetry field | Render as | In-game meaning |
| --- | --- | --- |
| `safetyZonePosition` / `safetyZoneRadius` | **blue circle** (current gas boundary) | The area that is safe *right now*; shrinks toward the white circle |
| `poisonGasWarningPosition` / `poisonGasWarningRadius` | **white circle** (next zone) | Where the blue will end up |
| `redZonePosition` / `redZoneRadius` | red circle | Bombardment area |
| `blackZonePosition` / `blackZoneRadius` | black zone | Haven-only demolition zone |

Mnemonic: *"poison gas **warning** = warning of where the gas will go = white."*

### 1.2 Emission cadence & interpolation

- `LogGameStatePeriodic` cadence is **not documented**. Community consensus and observed data put it
  around every ~5 s while the match runs. **⚠️ UNVERIFIED exact interval.**
- Between samples the blue circle is *continuously* shrinking. If you snap the blue radius to the
  last sample you get a visibly stepping circle. **Lerp `safetyZonePosition`/`safetyZoneRadius`
  between consecutive `LogGameStatePeriodic` events**, keyed on `gameState.elapsedTime`.
- `pubg.sh` snapshots the whole world into **100 ms buckets** and forward-fills, then interpolates
  player positions between pointers [21, 22]. That is a sound architecture to copy:
  ```javascript
  const msSinceEpoch = new Date(d._D).getTime() - epoch
  const currentInterval = Math.floor(msSinceEpoch / 100)
  ```
- The white circle is a **step function** — it jumps at each phase announce and is then constant.
  Do NOT interpolate it; snap it.
- Before the first zone announce, `poisonGasWarning*` / `safetyZone*` may be all-zeros with radius
  0. Guard `radius > 0` before drawing.

---

## 2. Zone lifecycle events

### `LogPhaseChange`

Added **v15.2.0 / v15.3.0** [8].

```json
{
  "_D": "2026-07-22T18:06:02.004Z",
  "_T": "LogPhaseChange",
  "common": { "isGame": 1.0 },
  "phase": 1,
  "elapsedTime": 184.0
}
```

| Field | Type | Meaning |
| --- | --- | --- |
| `phase` | int | Zone phase number |
| `elapsedTime` | number | Seconds since match start |

Confirmed by [1], [5], [23], [25]. Note `pubg-python` [23] only models `phase`, but the RST [5] and
the Go lib [25] both carry `elapsedTime` — use both, defaulting `elapsedTime` from `_D` if absent.

### `LogRedZoneEnded`

```json
{
  "_D": "2026-07-22T18:09:55.310Z",
  "_T": "LogRedZoneEnded",
  "common": { "isGame": 2.0 },
  "drivers": [ { "name": "SomePlayer", "teamId": 12, "health": 100.0,
                 "location": { "x": 0, "y": 0, "z": 0 }, "ranking": 0,
                 "accountId": "account.xxxx", "isInBlueZone": false,
                 "isInRedZone": true, "zone": ["pochinki"] } ]
}
```

| Field | Type | Meaning |
| --- | --- | --- |
| `drivers` | `[{Character}, …]` | Characters associated with the ended red zone |

Field name `drivers` confirmed by [1], [5], [23], [25]. **The semantics of `drivers` are not
documented anywhere — ⚠️ UNVERIFIED.** For rendering purposes this event is only useful as a
"red zone finished, stop drawing it" signal; there is **no `LogRedZoneStart`**, so the red zone's
active window must be derived from `gameState.redZoneRadius > 0` in `LogGameStatePeriodic`.

### `LogBlackZoneEnded`

Added **v16.1.0** (PC) / **v16.2.0** (console) [8]. Haven.

```json
{
  "_D": "2026-07-22T18:10:31.900Z",
  "_T": "LogBlackZoneEnded",
  "common": { "isGame": 2.0 },
  "survivors": [ { "name": "SomePlayer", "teamId": 4, "...": "..." } ]
}
```

| Field | Type | Meaning |
| --- | --- | --- |
| `survivors` | `[{Character}, …]` | Characters who survived the black zone |

Confirmed by the official RST [5] and by the Go wrapper [25]
(`Survivors []telemetryObjectCharacter \`json:"survivors"\``).
**Note:** `pubg-python` [23] declares `LogBlackZoneEnded` but reads the wire key `'characters'`, not
`'survivors'` — almost certainly a bug in that library. Do not treat it as corroboration.

### `LogBlueZoneCustomOptions` — **does not exist**

There is **no** event named `LogBlueZoneCustomOptions`. The blue-zone configuration is a
**stringified JSON array on `LogMatchStart.blueZoneCustomOptions`**. Confirmed by [1], [5], [23],
[25] (the Go lib literally stores it as `BlueZoneCustomOptionsRaw string` and parses it separately).

`BlueZoneCustomOptions` element shape [2, 6, 26]:

```json
[
  {
    "phaseNum": 1,
    "startDelay": 90,
    "warningDuration": 300,
    "releaseDuration": 180,
    "poisonGasDamagePerSecond": 0.4,
    "radiusRate": 0.35,
    "spreadRatio": 0.5,
    "landRatio": 0.75,
    "circleAlgorithm": 1
  }
]
```

| Field | Type | Meaning |
| --- | --- | --- |
| `phaseNum` | int | Phase index (matches `LogPhaseChange.phase`) |
| `startDelay` | int | Seconds before the phase begins |
| `warningDuration` | int | Seconds the white circle is shown before the blue moves |
| `releaseDuration` | int | Seconds the blue takes to shrink |
| `poisonGasDamagePerSecond` | number | Blue-zone DPS |
| `radiusRate` | number | Next radius as a fraction of the current radius |
| `spreadRatio` | number | How far off-centre the next circle may sit |
| `landRatio` | number | Land-bias weighting for circle placement |
| `circleAlgorithm` | int | Circle-placement algorithm selector |

**Parsing:** `JSON.parse(logMatchStart.blueZoneCustomOptions)` — it is a *string*, not an array.
It is the only source of `warningDuration` / `releaseDuration`, which is exactly what you need to
drive a smooth zone animation instead of guessing.

---

## 3. Care packages

Two events, same payload shape.

### `LogCarePackageSpawn` / `LogCarePackageLand`

```json
{
  "_D": "2026-07-22T18:08:14.882Z",
  "_T": "LogCarePackageSpawn",
  "common": { "isGame": 1.5 },
  "itemPackage": {
    "itemPackageId": "CarePackage_Container_C",
    "location": { "x": 407781.0, "y": 288420.5, "z": 31500.0 },
    "items": [
      {
        "itemId": "Item_Weapon_AWM_C",
        "stackCount": 1,
        "category": "Weapon",
        "subCategory": "Main",
        "attachedItems": ["Item_Attach_Weapon_Upper_ScopeSniper_C"]
      },
      { "itemId": "Item_Ammo_300Magnum_C", "stackCount": 20,
        "category": "Ammunition", "subCategory": "None", "attachedItems": [] }
    ]
  }
}
```

### `ItemPackage` object

| Field | Type | Meaning |
| --- | --- | --- |
| `itemPackageId` | string | **Class name of the crate/delivery, NOT a unique instance id.** |
| `location` | `{Location}` | Spawn position (high `z`) or landed position (ground `z`). |
| `items` | `[{Item}, …]` | Contents. |

### `Item` object

| Field | Type | Meaning |
| --- | --- | --- |
| `itemId` | string | e.g. `Item_Weapon_AWM_C` |
| `stackCount` | int | Quantity |
| `category` | string | e.g. `Weapon`, `Ammunition`, `Equipment`, `Use` |
| `subCategory` | string | e.g. `Main`, `Handgun`, `None` |
| `attachedItems` | `[itemId, …]` | Array of **plain itemId strings**, not objects |

### Confirmed `itemPackageId` values

| Value | Meaning | Source |
| --- | --- | --- |
| `Carapackage_RedBox_C` | Normal care-package crate — **note the official misspelling of "Care"** | Official known-issues page [4, 9]; pubg.sh parser [21] |
| `Carapackage_FlareGun_C` | **Flare-gun crate** (red flare) — render it, ideally highlighted | pubg.sh parser [21] |
| `Uaz_Armored_C` | Flare-gun armored UAZ delivery — `pubg.sh` explicitly **excludes** it from care-package rendering (land event only) | pubg.sh parser [21] |

The `pubg.sh` parser carries this comment block above its `LogCarePackageLand` handler [21]:

```javascript
// 'Carapackage_RedBox_C': normal,
// 'Carapackage_FlareGun_C': flaregun,
// 'Uaz_Armored_C': UAZ but landing event only.
```

The full `itemPackageId` enum is **not published** in `api-assets` (there is no
`itemPackageId.json`). Any other value your dashboard sees must be discovered empirically.
**⚠️ UNVERIFIED** — everything beyond the three values above.

### 3.1 Spawn → Land matching (there is no shared id)

`ItemPackage` has **no unique instance id**. `itemPackageId` is a class name, so several crates in
one match share it. The only production-proven approach is `pubg.sh`'s nearest-neighbour match [21]:

```javascript
if (d._T === 'LogCarePackageSpawn') {
    curState.carePackages.push({
        key: i,                          // index in the telemetry array == synthetic id
        location: d.itemPackage.location,
        items: d.itemPackage.items,
        state: 'spawned',
    })
}

if (d._T === 'LogCarePackageLand') {
    if (d.itemPackage.itemPackageId !== 'Uaz_Armored_C') {
        curState.carePackages.push({
            location: d.itemPackage.location,
            items: d.itemPackage.items,
            state: 'landed',
        })
    }
}

// later: pair each landed package to the nearest still-'spawned' package
const cpDistances = activePackages
    .filter(p => p.state === 'spawned')
    .map(p => ({ key: p.key, distance: distance(cp, p) }))
const matchingCp = minBy(cpDistances, 'distance')
```

Notes:
- Match on **XY distance only** — `z` differs enormously between spawn (in the air) and land.
- `LogItemPickupFromCarepackage` *does* carry a `carePackageUniqueId` (number) [1, 5]. Whether that
  id also appears on `ItemPackage` is **⚠️ UNVERIFIED** — it is not in the documented object shape,
  and `pubg.sh` clearly could not use it. **Check a live payload before relying on it; if it exists
  it would replace the whole distance-matching hack.**
- Between spawn and land, animate the crate falling; there are no intermediate events.

---

## 4. Vehicles

### `Vehicle` object (shared by every vehicle event)

```json
{
  "vehicleType": "WheeledVehicle",
  "vehicleId": "BP_Mirado_A_03_C",
  "vehicleUniqueId": 1849302,
  "healthPercent": 0.82,
  "feulPercent": 0.41,
  "altitudeAbs": 15230.0,
  "altitudeRel": 120.5,
  "velocity": 1740.2,
  "seatIndex": 0,
  "isWheelsInAir": false,
  "isInWaterVolume": false,
  "isEngineOn": true
}
```

| Field | Type | Added | Meaning |
| --- | --- | --- | --- |
| `vehicleType` | string | — | Enum, see §4.1 |
| `vehicleId` | string | — | Blueprint class name, see §4.2 |
| `vehicleUniqueId` | int | v14.2.0 (PC) / v15.1.0 (console) | **Stable per-instance id — use this to track a vehicle across events.** |
| `healthPercent` | number | — | 0.0 – 1.0 |
| `feulPercent` | number | — | 0.0 – 1.0. **MISSPELLED — "feul", not "fuel". Officially acknowledged.** |
| `altitudeAbs` | number | v17.2.0 | Absolute altitude (cm) |
| `altitudeRel` | number | v17.2.0 | Altitude relative to ground (cm) |
| `velocity` | number | v17.2.0 | Speed (cm/s) |
| `seatIndex` | int | — | Seat within the vehicle |
| `isWheelsInAir` | bool | v14.2.0 (PC) / v15.1.0 (console) | |
| `isInWaterVolume` | bool | v14.2.0 (PC) / v15.1.0 (console) | |
| `isEngineOn` | bool | v17.2.0 | |

> **`Vehicle.rotationPitch` no longer exists.** Added v14.2.0 (PC) / v15.1.0 (PS4, Xbox) and
> **REMOVED in v17.0.0** (changelog v17.0.0, *"Removed: - Vehicle.rotationPitch"*) [8]. That is why
> it is absent from the current object docs. Do not read it; it has not been emitted for five major
> versions. (See §9.)

`feulPercent` is confirmed as a bug on the official Known Issues page [4, 9]. The actual section
heading there is **`Mispellings`** (itself misspelled, one `s`), followed by *"The following items
are misspelled in the telemetry:"* and the entries `- Vehicle.FeulPercent` and
`- ItemPackage.itemPackageId.Carapackage_RedBox_C`. The wire key is lowercase-initial `feulPercent`
(confirmed by [2], [6], [24], [26]). Defensive read: `v.feulPercent ?? v.fuelPercent`.

### 4.1 `vehicleType` enum — complete, from `api-assets` [13]

```json
["EmergencyPickup","FloatingVehicle","FlyingVehicle","Mortar","Parachute","TransportAircraft","WheeledVehicle"]
```

| Value | Covers |
| --- | --- |
| `WheeledVehicle` | Cars, bikes, trucks, buggies |
| `FloatingVehicle` | Boats, aquarail, PG-117 |
| `FlyingVehicle` | Motor glider |
| `TransportAircraft` | **The drop plane / redeploy helicopters** |
| `Parachute` | Player parachute |
| `EmergencyPickup` | Emergency pickup balloon |
| `Mortar` | Mortar emplacement |

### 4.2 `vehicleId` → display name (official dictionary, complete) [18]

Aircraft / parachute rows matter most for the replay:

| `vehicleId` | Display name |
| --- | --- |
| `DummyTransportAircraft_C` | C-130 |
| `WarModeTransportAircraft_C` | C-130 |
| `TransportAircraft_Tiger_C` | Helicopter |
| `TransportAircraft_Chimera_C` | Helicopter |
| `RedeployAircraft_Tiger_C` | Helicopter |
| `RedeployAircraft_DihorOtok_C` | Helicopter |
| `EmergencyAircraft_Tiger_C` | Emergency Aircraft |
| `ParachutePlayer_C` | Parachute |
| `ParachutePlayer_Warmode_C` | Parachute |
| `BP_Motorglider_C`, `BP_Motorglider_Green_C` | Motor Glider |
| `BP_EmergencyPickupVehicle_C` | Emergency Pickup |
| `MortarPawn_C` | Mortar |

Ground / water (abridged — full list at [18]): `BP_Mirado_A_02_C`/`_A_03_C`/`Open_03_C`… (Mirado),
`Uaz_A_01_C`/`Uaz_B_01_C`/`Uaz_C_01_C`/`Uaz_Armored_C` (UAZ variants), `Dacia_A_0*_v2_C` (Dacia 1300),
`BP_PickupTruck_A_0*_C` / `_B_0*_C` (Pickup closed/open top), `Buggy_A_0*_C`, `BP_ATV_C` (Quad),
`BP_Motorbike_04_C` (+ `_SideCar_`, `_Desert_`), `BP_Niva_0*_C` (Zima), `BP_Van_A_0*_C`,
`BP_Porter_C`, `BP_PonyCoupe_C`, `BP_CoupeRB_C`, `BP_Blanc_C` (Coupe SUV), `BP_Bicycle_C`,
`BP_Dirtbike_C`, `BP_Scooter_0*_A_C`, `BP_Snowbike_0*_C`, `BP_Snowmobile_0*_C`, `BP_TukTukTuk_A_0*_C`
(Tukshai), `BP_M_Rony_A_0*_C` (Rony), `BP_BRDM_C`, `BP_Pillar_Car_C`, `BP_LootTruck_C`,
`BP_KillTruck_C`, `BP_Food_Truck_C`, `BP_McLarenGT_*_C`, `AirBoat_V2_C`, `AquaRail_*_C`,
`Boat_PG117_C` / `PG117_A_01_C`, `BP_DO_*_Train_*_C` (Train).

> **Do not treat `vehicleId` as a small closed set.** New skins/variants (`_Esports_`, `_Solitario_`,
> `_snow_`, McLaren colourways) are added every few patches. Map unknown ids to a generic icon and
> log them rather than throwing.

### `LogVehicleRide`

```json
{
  "_D": "2026-07-22T18:07:44.201Z",
  "_T": "LogVehicleRide",
  "common": { "isGame": 1.0 },
  "character": { "name": "PlayerA", "teamId": 7, "health": 92.0,
                 "location": { "x": 401002.0, "y": 293110.0, "z": 1240.0 },
                 "ranking": 0, "accountId": "account.xxxx",
                 "isInBlueZone": false, "isInRedZone": false, "zone": ["rozhok"] },
  "vehicle": { "vehicleType": "WheeledVehicle", "vehicleId": "BP_Mirado_A_03_C",
               "vehicleUniqueId": 1849302, "healthPercent": 1.0, "feulPercent": 0.88,
               "altitudeAbs": 0.0, "altitudeRel": 0.0, "velocity": 0.0,
               "seatIndex": 0, "isWheelsInAir": false, "isInWaterVolume": false,
               "isEngineOn": false },
  "seatIndex": 0,
  "fellowPassengers": []
}
```

| Field | Type | Meaning |
| --- | --- | --- |
| `character` | `{Character}` | Who boarded |
| `vehicle` | `{Vehicle}` | Vehicle state at boarding |
| `seatIndex` | int | Seat taken. **Duplicated at both top level and inside `vehicle`.** |
| `fellowPassengers` | `[{Character}, …]` | Others already aboard |

### `LogVehicleLeave`

| Field | Type | Meaning |
| --- | --- | --- |
| `character` | `{Character}` | Who exited |
| `vehicle` | `{Vehicle}` | Vehicle state at exit |
| `rideDistance` | number | Distance ridden this stint (cm) |
| `seatIndex` | int | Seat vacated (docs type it `integer` here vs `int` on Ride — same thing) |
| `maxSpeed` | number | Max speed during the stint |
| `fellowPassengers` | `[{Character}, …]` | Remaining/co-riders |

### `LogVehicleDestroy`

```json
{
  "_D": "2026-07-22T18:14:03.775Z",
  "_T": "LogVehicleDestroy",
  "common": { "isGame": 3.0 },
  "attackId": 41772,
  "attacker": { "name": "PlayerB", "teamId": 3, "...": "..." },
  "vehicle": { "vehicleType": "WheeledVehicle", "vehicleId": "BP_Mirado_A_03_C",
               "vehicleUniqueId": 1849302, "healthPercent": 0.0, "...": "..." },
  "damageTypeCategory": "Damage_Gun",
  "damageCauserName": "WeapAK47_C",
  "distance": 8410.5
}
```

| Field | Type | Meaning |
| --- | --- | --- |
| `attackId` **or** `atackId` | int | See the warning below |
| `attacker` | `{Character}` | Destroyer (may be a null-ish object for environmental kills) |
| `vehicle` | `{Vehicle}` | Destroyed vehicle |
| `damageTypeCategory` | string | See §7 |
| `damageCauserName` | string | Weapon/causer class name |
| `distance` | number | cm |

> **⚠️ `atackId` vs `attackId` conflict.** The official docs — both the rendered page [1] and the
> RST source [5] — spell this key **`atackId`** (one `t`) *for `LogVehicleDestroy` only*, while
> `LogVehicleDamage`, `LogWheelDestroy` and `LogArmorDestroy` all use `attackId`. Two independent
> client libraries ([23] pubg-python, [25] Go) declare `attackId` for this event. One of the two is
> wrong and it could not be resolved without live data.
> **Implement defensively: `const attackId = e.attackId ?? e.atackId`.**

### `LogVehicleDamage`

Added **v20.2.0** [8].

| Field | Type |
| --- | --- |
| `attackId` | int |
| `attacker` | `{Character}` |
| `vehicle` | `{Vehicle}` |
| `damageTypeCategory` | string |
| `damageCauserName` | string |
| `damage` | number |
| `distance` | number |

### `LogWheelDestroy`

Added **v1.4.0** [8].

| Field | Type |
| --- | --- |
| `attackId` | int |
| `attacker` | `{Character}` |
| `vehicle` | `{Vehicle}` |
| `damageTypeCategory` | string |
| `damageCauserName` | string |

No `distance`, no wheel index — you cannot tell *which* wheel. Confirmed by [1], [5], [23], [25].

### 4.3 Tracking vehicles for a replay

There is **no periodic vehicle-position event.** Vehicle positions are only observable via:

1. `LogVehicleRide` / `LogVehicleLeave` — `character.location` at board/exit time.
2. `LogPlayerPosition.vehicle` — the ~10 s player heartbeat carries the vehicle the player is in,
   so an occupied vehicle's path == its driver's path.
3. `LogVehicleDamage` / `LogVehicleDestroy` / `LogWheelDestroy` — `attacker.location` is the
   *attacker*, not the vehicle; the vehicle's own position is **not** in these events.

⇒ **An empty vehicle is invisible to telemetry.** Render vehicles as "attached to their occupants",
and drop them at the last known `LogVehicleLeave` position. Key everything on `vehicleUniqueId`.

---

## 5. Other world / environment events

### `LogSwimStart` / `LogSwimEnd`

`LogSwimEnd.swimDistance` added **v1.4.0**; the events themselves were added for PC/Xbox per the
changelog [8].

```json
{ "_D": "…", "_T": "LogSwimStart", "common": { "isGame": 2.0 },
  "character": { "name": "PlayerA", "...": "..." } }
```

```json
{ "_D": "…", "_T": "LogSwimEnd", "common": { "isGame": 2.0 },
  "character": { "name": "PlayerA", "...": "..." },
  "swimDistance": 6120.0,
  "maxSwimDepthOfWater": 480.0 }
```

| Event | Field | Type |
| --- | --- | --- |
| `LogSwimStart` | `character` | `{Character}` |
| `LogSwimEnd` | `character` | `{Character}` |
| | `swimDistance` | number |
| | `maxSwimDepthOfWater` | number |

### `LogObjectDestroy`

Added **v7.8.0** (PC) / **v9.0.0** (console) [8].

```json
{ "_D": "…", "_T": "LogObjectDestroy", "common": { "isGame": 2.0 },
  "character": { "name": "PlayerA", "...": "..." },
  "objectType": "Door",
  "objectLocation": { "x": 402330.0, "y": 291005.0, "z": 1310.0 } }
```

| Field | Type |
| --- | --- |
| `character` | `{Character}` |
| `objectType` | string (enum, §5.1) |
| `objectLocation` | `{Location}` |

### `LogObjectInteraction`

Added **v14.2.0** (PC) / **v15.1.0** (console) [8].

| Field | Type | Note |
| --- | --- | --- |
| `character` | `{Character}` | |
| `objectType` | string | |
| `objectTypeStatus` | string | |
| `objectTypeAdditionalInfo` | string | |
| `objectTypeCount` | ? | **⚠️ Present in `pubg-python` [23] but NOT in the official docs [1, 5].** |

### `LogPlayerDestroyProp` / `LogPlayerDestroyBreachableWall`

| Event | Fields |
| --- | --- |
| `LogPlayerDestroyProp` (v20.5.0) | `attacker` `{Character}`, `objectType` string, `objectLocation` `{Location}` |
| `LogPlayerDestroyBreachableWall` (v16.1.0/v16.2.0) | `attacker` `{Character}`, `weapon` `{Item}` |

Note `LogPlayerDestroyProp` uses **`attacker`** where `LogObjectDestroy` uses **`character`** for the
same concept. Easy parser bug.

### 5.1 `objectType` enum — complete, from `api-assets` [14]

```json
["Caraudio","Door","DoubleSlidingDoor","Fence","FuelPuddle","Hay","Jerrycan","JerryCan",
 "Jukebox","JukeBox","PropaneTank","VendingMachine","Window","Ascender","GasPump",
 "LockedDoor","BulletproofShield","Cartoplights"]
```

> Note the enum itself contains **case-inconsistent duplicates**: `Jerrycan`/`JerryCan` and
> `Jukebox`/`JukeBox`. **Compare `objectType` case-insensitively.**

### `LogEmPickupLiftOff`

Added **v20.4.0** [8]. Emergency pickup balloon.

| Field | Type |
| --- | --- |
| `instigator` | `{Character}` |
| `riders` | `[{Character}, …]` |

### `LogPlayerRedeploy` / `LogPlayerRedeployBRStart`

Added **v21.1.0** [8]. Blue-chip / redeploy-tower re-drops (these produce *new* aircraft flights
mid-match).

| Event | Fields |
| --- | --- |
| `LogPlayerRedeploy` | `character` `{Character}` |
| `LogPlayerRedeployBRStart` | `characters` `[{Character}, …]` |

### `LogPlayerUseFlareGun`

Added **v17.2.0** [8]. Precedes a `LogCarePackageSpawn` (red flare) or an armored-UAZ delivery
(blue flare, `itemPackageId: "Uaz_Armored_C"`).

| Field | Type |
| --- | --- |
| `attackId` | int |
| `fireWeaponStackCount` | int |
| `attacker` | `{Character}` |
| `attackType` | string |
| `weapon` | `{Item}` |

### `LogParachuteLanding`

| Field | Type |
| --- | --- |
| `character` | `{Character}` |
| `distance` | number |

### `LogCharacterCarry`

Added **v21.3.0** [8].

| Field | Type |
| --- | --- |
| `character` | `{Character}` |
| `carryState` | string |

`carryState` enum — complete, from `api-assets` [16]:

```json
["BodyCarry_DBNO_Carrier","BodyCarry_End_Carried","BodyCarry_End_Carrier",
 "BodyCarry_Start_Carried","BodyCarry_Start_Carrier"]
```

---

## 6. Match lifecycle

### `LogMatchDefinition`

Effectively the first event in the file.

```json
{
  "_D": "2026-07-22T18:02:55.000Z",
  "_T": "LogMatchDefinition",
  "common": { "isGame": 0 },
  "MatchId": "match.bro.official.pc-2018-27.steam.squad.na.2026.07.22.18.a1b2c3d4",
  "PingQuality": "",
  "SeasonState": "progress"
}
```

| Field | Type | Meaning |
| --- | --- | --- |
| `MatchId` | string | **PascalCase leading `M`.** |
| `PingQuality` | string | **DEPRECATED in v18.1.0** [8]. Do not use. |
| `SeasonState` | string | e.g. `progress`, `closed`. Full enum **⚠️ UNVERIFIED**. |

> **CASING TRAP:** this is the *only* event whose payload keys are **PascalCase**
> (`MatchId`, `PingQuality`, `SeasonState`). Every other event uses camelCase.
> `MatchId` and `SeasonState` are confirmed identically by [1], [5], [25] (and [23]).
> **`PingQuality` is single-sourced to the official docs [1], [5]** — the Go wrapper's
> `LogMatchDefinition` struct carries only `MatchId` and `SeasonState`, consistent with the v18.1.0
> deprecation. `pubg-python` [23] *corroborates* the trap rather than hiding it: it reads the
> PascalCase **wire** keys directly (`self._data.get('MatchId')`, `.get('PingQuality')`,
> `.get('SeasonState')`); only its exposed Python attribute names are snake_cased.

### `LogMatchStart`

```json
{
  "_D": "2026-07-22T18:03:40.512Z",
  "_T": "LogMatchStart",
  "common": { "isGame": 0 },
  "mapName": "Baltic_Main",
  "weatherId": "Clear",
  "cameraViewBehaviour": "FpsOnly",
  "teamSize": 4,
  "isCustomGame": false,
  "isEventMode": false,
  "blueZoneCustomOptions": "[{\"phaseNum\":1,\"startDelay\":90,\"warningDuration\":300,\"releaseDuration\":180,\"poisonGasDamagePerSecond\":0.4,\"radiusRate\":0.35,\"spreadRatio\":0.5,\"landRatio\":0.75,\"circleAlgorithm\":1}]",
  "characters": [
    {
      "character": {
        "name": "PlayerA", "teamId": 7, "health": 100.0,
        "location": { "x": 0.0, "y": 0.0, "z": 0.0 },
        "ranking": 0, "accountId": "account.xxxx",
        "isInBlueZone": false, "isInRedZone": false, "zone": []
      },
      "primaryWeaponFirst": "",
      "primaryWeaponSecond": "",
      "secondaryWeapon": "",
      "spawnKitIndex": 0
    }
  ]
}
```

| Field | Type | Meaning |
| --- | --- | --- |
| `mapName` | string | See §0.4 table |
| `weatherId` | string | See §6.1 |
| `characters` | `[{CharacterWrapper}, …]` | **Full starting roster.** |
| `cameraViewBehaviour` | string | FPP/TPP restriction. Enum **⚠️ UNVERIFIED** — no `api-assets` file exists for it. |
| `teamSize` | int | 1 / 2 / 4 |
| `isCustomGame` | bool | Added v1.4.0 |
| `isEventMode` | bool | Added v1.4.0 |
| `blueZoneCustomOptions` | string | **Stringified JSON array** — see §2 |

**`CharacterWrapper`** — confirmed by the official RST [6] and the Go wrapper [26] only.
`pubg-python` [24] has **no** `CharacterWrapper` class (its `objects.py` defines only `BaseObject`,
`Object`, `StringifiedObject`, `Common`, `Location`, `Item`, `ItemPackage`, `Character`, `Vehicle`,
`GameState`, `BlueZone`, `BlueZoneCustomOptions`, `Stats`, `GameResult`) and still parses
`LogMatchStart`/`LogMatchEnd` `characters` as **bare `Character` objects** — i.e. it is stale with
respect to the v18.0.0 shape change.

| Field | Type |
| --- | --- |
| `character` | `{Character}` |
| `primaryWeaponFirst` | string |
| `primaryWeaponSecond` | string |
| `secondaryWeapon` | string |
| `spawnKitIndex` | int |

> **Breaking change — mind the platform.** `LogMatchStart` / `LogMatchEnd` `characters[]` changed
> from bare `Character` objects to `CharacterWrapper` objects in **v18.0.0 on [PC]** and in
> **v19.0.0 on [Console]** [8]. Version-gating console ingestion on v18.0.0 will mis-parse console
> matches recorded between v18.0.0 and v19.0.0. If you ingest historical telemetry from either
> platform, handle both shapes: `const ch = entry.character ?? entry`.

`LogMatchStart` is also the correct **replay t=0 anchor**. `pubg.sh` ignores every event before it
[21]:

```javascript
if (!matchStarted && d._T === 'LogMatchStart') { matchStarted = true }
if (!matchStarted) return
```

### `LogMatchEnd`

```json
{
  "_D": "2026-07-22T18:32:07.884Z",
  "_T": "LogMatchEnd",
  "common": { "isGame": 8.0 },
  "characters": [ { "character": { "...": "..." }, "primaryWeaponFirst": "", "...": "..." } ],
  "gameResultOnFinished": {
    "results": [
      {
        "rank": 1,
        "gameResult": "win",
        "teamId": 7,
        "accountId": "account.xxxx",
        "stats": {
          "killCount": 6,
          "distanceOnFoot": 241300.0,
          "distanceOnSwim": 0.0,
          "distanceOnVehicle": 610250.0,
          "distanceOnParachute": 88400.0,
          "distanceOnFreefall": 51200.0
        }
      }
    ]
  }
}
```

| Field | Type | Meaning |
| --- | --- | --- |
| `characters` | `[{CharacterWrapper}, …]` | Final roster with final `ranking` on each `character` |
| `gameResultOnFinished` | `{GameResultOnFinished}` | `{ "results": [{GameResult}, …] }` |

**`GameResult`** [2, 6, 24, 26]:

| Field | Type |
| --- | --- |
| `rank` | int |
| `gameResult` | string |
| `teamId` | int |
| `stats` | `{Stats}` |
| `accountId` | string |

**`Stats`**: `killCount` int, `distanceOnFoot`, `distanceOnSwim`, `distanceOnVehicle`,
`distanceOnParachute`, `distanceOnFreefall` (all number, cm).

> **`results` only contains the WINNING team.** The RST carries the inline comment
> `// Shows winning players only` [6]. For everyone else's rank you must read
> `characters[].character.ranking`, or `LogPlayerKillV2.victimGameResult`.

> The official Known Issues page [4] says distance stats in `GameResult` are **authoritative** over
> `participant.attributes.stats` from the match endpoint when they disagree. That same page refers
> to the path as `LogMatchEnd.results.gameResultOnFinished`, which contradicts the object docs'
> `LogMatchEnd.gameResultOnFinished.results` — **the object-docs ordering is confirmed by
> `telemetry-objects.rst` / `telemetry-events.rst` [5, 6] and by the Go wrapper [25, 26] only
> (`GameResultOnFinished ... json:"gameResultOnFinished"` containing `Results []…`). No other client
> library models the path at all: `pubg-python`'s `LogMatchEnd` models only `characters`, and
> `chicken-dinner` is a schema-agnostic case-insensitive dict wrapper that asserts nothing. Trust the
> object docs, but null-guard both.**

> `LogMatchEnd.rewardDetail`, `PlayTimeRecord` and `RewardDetail` were **removed in v8.0.0** [8].

### 6.1 `weatherId` enum — complete, from `api-assets` [15]

```json
["Clear","Clear_02","Clouds","Cloudy","Christmas","Dark","Halloween","Night","Overcast",
 "Snow","Sunrise","Sunset","Sunset_a","Weather_Clear","Weather_Overcast",
 "Weather_Range_Sunset","Weather_Sunset","Weather_Summerland_01"]
```

Note the two naming generations (`Clear` vs `Weather_Clear`) coexist. Normalise by stripping a
leading `Weather_` before matching.

---

## 7. Shared enums you will hit on world events

### `damageTypeCategory` (official dictionary, complete) [20]

World-relevant subset:

| Value | Display |
| --- | --- |
| `Damage_BlueZone` | Bluezone Damage |
| `Damage_BlueZoneGrenade` | Bluezone Grenade Damage |
| `Damage_Explosion_RedZone` | Redzone Explosion Damage |
| `Damage_Explosion_BlackZone` | Blackzone Damage |
| `Damage_Explosion_Vehicle` | Vehicle Explosion Damage |
| `Damage_Explosion_Aircraft` | Aircraft Explosion Damage |
| `Damage_Explosion_GasPump` | Gas Pump Explosion |
| `Damage_Explosion_JerryCan` | Jerrycan Explosion Damage |
| `Damage_Explosion_PropaneTank` | Propane Tank |
| `Damage_Explosion_LootTruck` | Loot Truck Explosion Damage |
| `Damage_Explosion_Mortar` | Mortar Explosion |
| `Damage_VehicleHit` / `Damage_VehicleCrashHit` | Vehicle Damage / Vehicle Crash Damage |
| `Damage_LootTruckHit` / `Damage_KillTruckHit` / `Damage_KillTruckTurret` | Truck damage variants |
| `Damage_TrainHit` / `Damage_ShipHit` / `Damage_HelicopterHit` | Train / Ferry / Pillar Scout Helicopter |
| `Damage_Drown` | Drowning Damage |
| `Damage_Instant_Fall` | Fall Damage |
| `Damage_Blizzard` / `Damage_SandStorm` / `Damage_Lava` | Weather / terrain hazards |
| `Damage_MotorGlider` | Motor Glider Damage |
| `Damage_Monster` | Monster Damage |
| `Damage_None` | No Damage |
| `SpikeTrap` | Spike Trap damage — **note: no `Damage_` prefix. Breaks prefix-based parsing.** |

Full list at [20]: **43 entries — 42 with the `Damage_` prefix, plus the single unprefixed
`SpikeTrap`** (verified by parsing `damageTypeCategory.json`).

### `Character` object

| Field | Type | Note |
| --- | --- | --- |
| `name` | string | |
| `teamId` | int | |
| `health` | number | 0–100 |
| `location` | `{Location}` | cm |
| `ranking` | int | 0 until placement is known |
| `accountId` | string | `account.<hex>` |
| `isInBlueZone` | bool | Added v7.8.0 (PC) / v9.0.0 (console) |
| `isInRedZone` | bool | Added v7.8.0 / v9.0.0 |
| `zone` | `[regionId, …]` | Named regions, e.g. `["pochinki"]`. Added v7.8.0 / v9.0.0 |

`regionId` values are per-map lists in `api-assets/enums/telemetry/regionId.json` [17] —
138 entries across `Chimera_Main`, `Desert_Main`, `DihorOtok_Main`, `Erangel_Main`, `Heaven_Main`,
`Savage_Main`, `Summerland_Main`, `Tiger_Main`. **`Baltic_Main`, `Kiki_Main` and `Neon_Main` have no
region list in that file** — expect `zone` to be empty or unmapped on Erangel-Remastered, Deston and
Rondo. **⚠️ Behaviour on those maps UNVERIFIED.**

---

## 8. Deriving the plane flight path

There is **no `LogPlaneFlight` event and no aircraft-position event.** The path must be inferred.

### Method A — regression over in-plane player positions (verified prior art, recommended)

While `common.isGame == 0.1` (officially: *"On airplane"* [2, 6]) every living player's
`character.location` **is** the plane's location. `LogPlayerPosition` fires roughly every 10 s [29],
which over a ~60–90 s flight gives many collinear samples.

`rico0821/pubg_map` implements exactly this [30]:

```python
def getFlightFit(self):
    loc = self.getPlayerXY()                       # from _T == 'LogPlayerPosition'
    early_loc = [data for data in loc if data['time'] < 5]   # uses elapsedTime
    x = np.array([data['x'] for data in early_loc])
    y = np.array([data['y'] for data in early_loc])
    A = np.vstack([x, np.ones(len(x))]).T
    m, c = np.linalg.lstsq(A, y, rcond=None)[0]
    return m, c
```

Recommended refinement over that implementation:

1. Filter `_T === "LogPlayerPosition" && common.isGame === 0.1` — this is more precise than
   `elapsedTime < 5` and is officially defined, whereas the `< 5` cutoff is a magic number.
2. Collect `(character.location.x, character.location.y, _D)` from those events.
3. **Total-least-squares / PCA fit**, not ordinary least squares on `y = mx + c` — an OLS fit
   explodes for a near-vertical (north–south) flight path. Take the first principal component of
   the centred XY point cloud as the direction vector.
4. Determine **direction of travel** by ordering points by `_D`: earliest → latest.
5. Extend the line to the map bounds (§0.4) to get entry/exit points for rendering.

### Method B — jump-out points (higher fidelity if the events exist)

`vehicleType` includes `TransportAircraft`, and `vehicleId` includes `DummyTransportAircraft_C`
(C-130) and `ParachutePlayer_C` (Parachute) [13, 18] — strongly implying that boarding/exiting the
plane and deploying the chute surface as `LogVehicleRide` / `LogVehicleLeave`. If so:

- `LogVehicleLeave` where `vehicle.vehicleType === "TransportAircraft"` gives one exact
  **(x, y, z, t)** point per player, at the moment they jumped → the tightest possible flight line,
  plus a free per-player jump-time visualisation.
- `LogVehicleRide` where `vehicle.vehicleId === "ParachutePlayer_C"` marks chute deployment;
  `LogParachuteLanding` marks touchdown.

> **⚠️ UNVERIFIED.** No source consulted demonstrates `LogVehicleRide`/`LogVehicleLeave` actually
> firing for `TransportAircraft`. `pubg.sh` [21] does not handle it. Confirm against a live
> telemetry file before building on it; **ship Method A and use Method B as an enhancement.**

### Method C — first/last parachute landings (crude fallback)

`LogParachuteLanding.character.location` sorted by `_D` roughly traces the drop order along the
path, but hot-drop clustering and glide distance make it noisy. Use only if Method A yields
fewer than ~3 distinct points.

### Related derived quantity

`LogParachuteLanding.distance` is the parachute distance; `Stats.distanceOnFreefall` and
`Stats.distanceOnParachute` (in `GameResult`) give the per-player totals at match end.

---

## 9. Fields that changed across patches (verified from the official changelog [3, 8])

| Version | Change | Impact on a replay dashboard |
| --- | --- | --- |
| v22.1.0 | `ClanID` added to player object; Clans endpoint | Non-telemetry |
| v22.0.3 | **Tournaments endpoint and matches REMOVED** | Esports ingestion is dead |
| v21.3.0 | `LogCharacterCarry` added | New event to switch on |
| v21.2.0 | `LogItemPutToVehicleTrunk`, `LogItemPickupFromVehicleTrunk`; `matchType` enums `airoyale`, `seasonal` | New vehicle-adjacent events |
| **v21.0.0** | **`LogPlayerKill` REMOVED** (existing matches unaffected; tournament matches excluded) | **Must use `LogPlayerKillV2`** |
| v20.5.0 | `LogPlayerDestroyProp`; `LogPlayerKillV2.assists_AccountId`, `.teamKillers_AccountId` | |
| v20.4.0 | `LogEmPickupLiftOff` | |
| v20.3.0 | `LogPlayerKillV2` introduced | |
| v20.2.0 | `LogItemPickupFromCustomPackage`, **`LogVehicleDamage`** | New vehicle event |
| **v19.0.0** | Console: `"VehicleEngineOff"` added to `damageCauserAdditionalInfo`; **[Console] `LogMatchStart`/`LogMatchEnd` `characters[]` → `CharacterWrapper`** | Console shape change — this, not v18.0.0, is the console cutoff |
| **v18.1.0** | **`LogMatchDefinition.PingQuality` DEPRECATED** | Stop reading it |
| **v18.0.0** | **[PC] `LogMatchStart`/`LogMatchEnd` `characters[]` → `CharacterWrapper`** | Shape change — handle both |
| v17.2.0 | **`Vehicle.velocity`, `.altitudeAbs`, `.altitudeRel`, `.isEngineOn`**; `LogPlayerUseFlareGun` | Absent on older telemetry |
| v16.2.0 | Console: `LogBlackZoneEnded`, `GameState.blackZonePosition`, `GameState.blackZoneRadius`, `LogPlayerDestroyBreachableWall` | |
| v16.1.0 | PC: same as above | **`blackZone*` absent before v16.1.0 — null-guard** |
| v15.3.0 / v15.2.0 | `LogPhaseChange`, `LogPlayerUseThrowable` | Absent on older telemetry |
| **v17.0.0** | **`Vehicle.rotationPitch` REMOVED** | Field no longer emitted on any platform |
| v15.1.0 | **Console (PS4, Xbox):** `LogObjectInteraction`, `Vehicle.vehicleUniqueId`, `Vehicle.rotationPitch`, `Vehicle.isWheelsInAir`, `Vehicle.isInWaterVolume` | Console cutoff for `vehicleUniqueId` |
| **v14.2.0** | **PC:** `LogObjectInteraction`, **`Vehicle.vehicleUniqueId`**, `Vehicle.rotationPitch`, `Vehicle.isWheelsInAir`, `Vehicle.isInWaterVolume` | **No `vehicleUniqueId` before this on PC — vehicle tracking impossible on older PC data** |
| v13.0.0 | `participant.attributes.stats.deathType` = `"byzone"` for zone deaths | |
| v9.0.0 | Console: `Character.isInBlueZone`, `.isInRedZone`, `.zone`, `GameResult`, `LogHeal`, `LogItemPickupFromCarepackage`, `LogRedZoneEnded`, `LogObjectDestroy` | |
| **v8.0.0** | **`LogMatchEnd.rewardDetail`, `PlayTimeRecord`, `RewardDetail` REMOVED** | |
| v7.8.0 | PC: `LogHeal`, `LogItemPickupFromCarepackage`, `LogObjectDestroy`, `LogRedZoneEnded`, `LogVaultStart`, `LogWeaponFireCount`, `Character.isInBlueZone/.isInRedZone/.zone` | |
| v4.0.0 | Telemetry compressed with gzip | Must send `Accept-Encoding: gzip` |
| v1.4.0 | `LogPlayerMakeGroggy`, `LogPlayerRevive`, **`LogWheelDestroy`**, `LogSwimEnd.swimDistance`, `LogMatchStart.isCustomGame`, `.isEventMode` | |

**Latest changelog entry as of writing: v22.1.0.** No telemetry-schema changes are listed in the
v22.x line — the world-event surface has been stable since v21.3.0.

---

## 10. Complete telemetry event list (official, 53 events)

`LogArmorDestroy`, `LogBlackZoneEnded`, `LogCarePackageLand`, `LogCarePackageSpawn`,
`LogCharacterCarry`, `LogEmPickupLiftOff`, `LogGameStatePeriodic`, `LogHeal`, `LogItemAttach`,
`LogItemDetach`, `LogItemDrop`, `LogItemEquip`, `LogItemPickup`, `LogItemPickupFromCarepackage`,
`LogItemPickupFromCustomPackage`, `LogItemPickupFromLootbox`, `LogItemPickupFromVehicleTrunk`,
`LogItemPutToVehicleTrunk`, `LogItemUnequip`, `LogItemUse`, `LogMatchDefinition`, `LogMatchEnd`,
`LogMatchStart`, `LogObjectDestroy`, `LogObjectInteraction`, `LogParachuteLanding`,
`LogPhaseChange`, `LogPlayerAttack`, `LogPlayerCreate`, `LogPlayerDestroyBreachableWall`,
`LogPlayerDestroyProp`, `LogPlayerKill`, `LogPlayerKillV2`, `LogPlayerLogin`, `LogPlayerLogout`,
`LogPlayerMakeGroggy`, `LogPlayerPosition`, `LogPlayerRedeploy`, `LogPlayerRedeployBRStart`,
`LogPlayerRevive`, `LogPlayerTakeDamage`, `LogPlayerUseFlareGun`, `LogPlayerUseThrowable`,
`LogRedZoneEnded`, `LogSwimEnd`, `LogSwimStart`, `LogVaultStart`, `LogVehicleDamage`,
`LogVehicleDestroy`, `LogVehicleLeave`, `LogVehicleRide`, `LogWeaponFireCount`, `LogWheelDestroy`

Source: [1] / [5]. `LogPlayerKill` is still listed — its official section heading is literally
**`LogPlayerKill (tournament matches)`** [5] — and it was **removed in v21.0.0** [8] with two
explicit qualifiers: *"LogPlayerKill events will not be removed from matches that finished before
this update. This update does not effect tournament matches."* So it still appears in pre-v21.0.0
matches and in tournament matches, but not in modern public matches. (Moot for tournaments in
practice: the Tournaments endpoint and its matches were removed in v22.0.3.)

**`LogPlayerPosition`** (needed by the flight-path derivation and by everything else):

| Field | Type |
| --- | --- |
| `character` | `{Character}` |
| `vehicle` | `{Vehicle}` |
| `elapsedTime` | number |
| `numAlivePlayers` | int |

---

## 11. Implementation notes — things that will silently break a parser

1. **Zone naming is inverted.** `safetyZone*` → blue circle; `poisonGasWarning*` → white circle.
   Getting this backwards produces a replay that looks *almost* right and is completely wrong.
   (§1.1)

2. **`feulPercent`, not `fuelPercent`.** Officially acknowledged under the known-issues heading
   `Mispellings` → *"The following items are misspelled in the telemetry:"* → `- Vehicle.FeulPercent`
   [4, 9]. A
   `vehicle.fuelPercent` read returns `undefined` forever and your fuel gauge silently reads 0.

3. **`atackId` vs `attackId` on `LogVehicleDestroy`.** Docs say `atackId`; two client libraries say
   `attackId`. Read both. (§4)

4. **`LogMatchDefinition` is PascalCase.** `MatchId`, `PingQuality`, `SeasonState`. Every other
   event is camelCase. A generic camelCase-only mapper drops all three.

5. **`Carapackage_RedBox_C`** — the care-package class name itself is misspelled [4]. Do not
   "correct" it in a lookup table.

6. **`objectType` has case-duplicate enum members** (`Jerrycan`/`JerryCan`, `Jukebox`/`JukeBox`)
   [14]. Compare case-insensitively.

7. **`SpikeTrap` has no `Damage_` prefix** in `damageTypeCategory` [20] — it is the only one of the
   dictionary's 43 values without it (42 prefixed + `SpikeTrap`). Prefix-stripping logic must not
   assume the prefix.

8. **`y` grows downward; origin is top-left** [2, 6]. Do not flip.

9. **Map scale is 102,000 cm per nominal km, not 100,000.** Always normalise against the per-map
   range table in §0.4.

10. **Care packages have no unique id.** `itemPackageId` is a class name. Match spawn→land by
    nearest XY distance, as `pubg.sh` does [21]. Do NOT match by `itemPackageId`.

11. **Exclude `itemPackageId === "Uaz_Armored_C"`** from care-package rendering — it is a flare-gun
    vehicle delivery, not a crate [21].

12. **Empty vehicles are invisible.** No periodic vehicle-position event exists. Track by
    `vehicleUniqueId` and attach to occupants. (§4.3)

13. **`vehicleUniqueId` doesn't exist before v14.2.0 on PC** (v15.1.0 on PS4/Xbox). Any
    historical-telemetry code path needs a fallback keyed on `vehicleId` + proximity.

14. **`blackZonePosition` / `blackZoneRadius` don't exist before v16.1.0**, and are all-zeros on
    non-Haven maps. Guard `radius > 0` before drawing any zone.

15. **`blueZoneCustomOptions` is a JSON *string*, not an array.** `JSON.parse` it. It may be `""`
    for non-custom matches. Wrap in try/catch.

16. **Anchor the replay clock on `LogMatchStart`**, and use `gameState.elapsedTime` /
    `LogPlayerPosition.elapsedTime` for positioning, not raw `_D` deltas. `_D` is only reliable for
    ordering and for 100 ms bucketing [21].

17. **Interpolate the blue circle, snap the white circle.** (§1.2)

18. **`characters[]` shape changed in v18.0.0 on PC and v19.0.0 on console.** Handle
    `entry.character ?? entry`, and do not gate console ingestion on v18.0.0.

19. **`LogObjectDestroy` uses `character`; `LogPlayerDestroyProp` uses `attacker`** for the same
    role. Two events, two names.

20. **`GameResultOnFinished.results` contains only the winning team** ("Shows winning players
    only" [6]). Never build a full scoreboard from it — use `LogMatchEnd.characters[].character.ranking`.

21. **`LogPlayerKill` is gone from modern public matches (v21.0.0).** Use `LogPlayerKillV2`. It does
    still appear in matches that finished before v21.0.0 and in tournament matches (whose endpoint
    was itself removed in v22.0.3); the official section heading is
    `LogPlayerKill (tournament matches)`.

22. **Unknown enum values are normal.** New `vehicleId`s, `weatherId`s and `itemPackageId`s ship
    every few patches. Log-and-degrade; never throw on an unrecognised class name.

23. **`seatIndex` appears twice** on `LogVehicleRide`/`LogVehicleLeave` (top level and inside
    `vehicle`). They should agree; prefer the top-level one, which is what the docs define as the
    event's own field.

24. **Send `Accept-Encoding: gzip`** and stream-parse. Telemetry files are large.

25. **`attachedItems` is an array of raw `itemId` strings**, not `Item` objects.

26. **`chicken-dinner` warns that key casing differs between PC and Xbox telemetry** [29] — it
    normalises everything to snake_case for that reason. If you will ever ingest console telemetry,
    do a case-insensitive key lookup at the parser boundary. ⚠️ The *specific* keys that differ
    were not enumerated by any source.

---

## 12. ⚠️ Unverified / needs live confirmation

Everything below could **not** be confirmed against two independent sources. No live 2026-era
telemetry file could be retrieved (all CDN sample URLs returned HTTP 403), so **the single highest-
value follow-up is to pull one real telemetry file and diff it against this document.**

1. **No radiation-zone fields exist in PC telemetry.** Searched specifically for `isRadiationZone`,
   `radiationZone`, and radiation-related `GameState` members across the official docs, the RST
   sources, `api-assets`, and four client libraries — **zero hits**. `GameState` has exactly four
   zone families: `safetyZone*`, `poisonGasWarning*`, `redZone*`, `blackZone*`. Radiation zones
   appear to be a **PUBG Mobile / Metro Royale** concept with no PC-telemetry counterpart. Treat any
   radiation field as non-existent until a live payload proves otherwise.

2. **`atackId` vs `attackId` on `LogVehicleDestroy`** — official docs and client libraries disagree.
   Read both keys.

3. *(resolved — `Vehicle.rotationPitch` was added v14.2.0/v15.1.0 and **removed in v17.0.0**; see §4
   and §9. No longer an open question.)*

4. **`_U` event key** — present only in a 2018-era field dump [31]. Not in any current source.
   (`_V` **is** confirmed by two sources and is safe to expect.)

5. **`LogObjectInteraction.objectTypeCount`** — modelled by `pubg-python` [23], absent from the
   official docs.

6. **The full `itemPackageId` enum.** Only three values are source-confirmed:
   `Carapackage_RedBox_C` [4, 21], `Carapackage_FlareGun_C` [21] and `Uaz_Armored_C` [21].
   No `itemPackageId.json` exists in `api-assets`; anything else must be discovered from a live file.

7. **Whether `ItemPackage` carries a `carePackageUniqueId`.** `LogItemPickupFromCarepackage` has
   one, but the `ItemPackage` object definition does not list it — and `pubg.sh` had to fall back to
   distance matching, suggesting it is absent. If present it would obsolete §3.1.

8. **Whether `LogVehicleRide` / `LogVehicleLeave` fire for `vehicleType === "TransportAircraft"`**
   (the drop plane) and for `ParachutePlayer_C`. The enums strongly imply yes; no consumer
   demonstrates it. This determines whether flight-path Method B is available. (§8)

9. **`cameraViewBehaviour` enum values.** No `api-assets` enum file; no source lists the values.
   (`"FpsOnly"` in the §6 example is a *placeholder*, not a confirmed value.)

10. **`SeasonState` enum values.** `"progress"` and `"closed"` are widely used in the community but
    were not confirmable from an authoritative source in this pass.

11. **`LogGameStatePeriodic` emission interval.** Not documented. Community estimate ~5 s.
    (`LogPlayerPosition` ≈ every 10 s **is** documented by `chicken-dinner` [29] but not by KRAFTON.)

12. **Semantics of `LogRedZoneEnded.drivers`.** The field name is confirmed; what the array actually
    contains is documented nowhere.

13. **Map-range rows that are inferences, not quotes.** The official range list is keyed by
    *display name*, not by `mapName`. Confirm against a real telemetry file / observed coordinate
    extremes once one can be pulled:
    - **Rondo (`Neon_Main`)** — absent from the docs' list entirely; 816,000 is a strong inference
      (8×8 km).
    - **`Baltic_Main`** — docs say "Erangel"; the dictionary calls this key "Erangel (Remastered)".
    - **`Range_Main`** — docs say "Range"; the dictionary calls this key "Camp Jackal".

14. **`regionId` coverage for `Baltic_Main`, `Kiki_Main`, `Neon_Main`.** These maps have no region
    list in `regionId.json` [17]; whether `Character.zone` is populated on them is unknown.

15. **Which specific keys differ in casing between PC and console telemetry.** `chicken-dinner`
    documents that they differ [29] but does not enumerate them.

16. **The exact path `LogMatchEnd.gameResultOnFinished.results` vs `LogMatchEnd.results.gameResultOnFinished`.**
    The object/event docs [5, 6] and the Go wrapper [25, 26] say the former; the Known Issues page
    [4] says the latter. No other client library models the path (`pubg-python`'s `LogMatchEnd`
    models only `characters`; `chicken-dinner` is schema-agnostic), so the earlier
    "three client libraries" claim was unsupported. Null-guard both.

17. **`z`-axis semantics and range.** The official Location section defines units, origin and per-map
    X/Y ranges only — it says nothing about the `z` axis, and publishes no `z` range. "`z` is up,
    in cm" is an inference. Confirm against a live telemetry file (compare in-plane altitudes with
    ground-level values).

18. **All JSON values in this document are illustrative.** Only the *key names and casing* are
    verified. Radii, ids, timestamps and enum value strings in the examples are synthetic.
