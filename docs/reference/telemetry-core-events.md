# PUBG Telemetry — Core Player Events Reference

**Status:** verified against a 2019 telemetry file **and four 2026 telemetry files** + official docs
+ independent implementations, then adversarially fact-checked.
**Last researched:** 2026-07-22.

> ⚠️ **Era labelling.** Several shapes changed between 2019 and today. Anything marked
> **2019-only** is gone from current telemetry; anything marked **modern** is what a live
> dashboard will actually receive. When in doubt, follow the *modern* column.

This document is the single source of truth for parsing PUBG telemetry in this project.
Every field name below is reproduced with **exact casing**. Where the official documentation
and real payloads disagree, the disagreement is called out explicitly — the docs are wrong
in several places and following them will silently break a parser.

---

## Sources

Official documentation (rendered):

- https://documentation.pubg.com/en/telemetry.html — how telemetry is fetched
- https://documentation.pubg.com/en/telemetry-events.html — event catalogue
- https://documentation.pubg.com/en/telemetry-objects.html — shared object catalogue
- https://documentation.pubg.com/en/telemetry-objects.html#common — `Common` / `Character` / `Location` detail
- https://documentation.pubg.com/en/telemetry-events.html#logheal — `LogHeal` field casing check

Official documentation (raw reStructuredText source — authoritative over the rendered HTML):

- https://raw.githubusercontent.com/pubg/api-documentation-content/master/rst/telemetry.rst
- https://raw.githubusercontent.com/pubg/api-documentation-content/master/rst/telemetry-events.rst
- https://raw.githubusercontent.com/pubg/api-documentation-content/master/rst/telemetry-objects.rst
- https://raw.githubusercontent.com/pubg/api-documentation-content/master/rst/changelog/changelog.rst

Official asset dictionaries:

- https://api.github.com/repos/pubg/api-assets/contents/dictionaries/telemetry — directory listing
- https://raw.githubusercontent.com/pubg/api-assets/master/dictionaries/telemetry/damageTypeCategory.json
- https://raw.githubusercontent.com/pubg/api-assets/master/dictionaries/telemetry/damageCauserName.json
- https://raw.githubusercontent.com/pubg/api-assets/master/dictionaries/telemetry/mapName.json

**Real telemetry payload (primary ground truth, downloaded and parsed locally):**

- https://raw.githubusercontent.com/ramonsaraiva/pubg-python/master/tests/telemetry_response.json
  — 20,185,531 bytes, 39,284 events, PC `steam` `squad-fpp` EU match recorded 2019-10-23.
  Match id `match.bro.official.pc-2018-04.steam.squad-fpp.eu.2019.10.23.00.db8f8222-4300-4683-9483-db85602ff756`.
  **Claims marked "2019 sample" in this document were produced by parsing this file directly.**

**Modern telemetry payloads (secondary ground truth, 2026-05-03):**

- 4 × PC `steam` matches captured 2026-05-03 (`steam_11ca6321…`, `588fc1a8…`, `5d13f824…`, `abca7f1c….json.gz`),
  52,714–56,188 events each, 37.7–39.4 MB uncompressed / 2.38–2.73 MiB gzipped.
  **Claims marked "modern" were produced by parsing these four files.** Where the 2019 sample and the
  modern payloads disagree, the modern shape is authoritative for a current dashboard and the 2019
  shape is labelled **2019-only**.

Independent third-party implementations (used for cross-checking casing):

- https://raw.githubusercontent.com/NovikovRoman/pubg/master/telemetry_events.go — Go wrapper
- https://raw.githubusercontent.com/martinsileno/pubg-typescript-api/master/src/interfaces/telemetry.ts — TypeScript interfaces (case-sensitive, so good evidence)
- https://raw.githubusercontent.com/martinsileno/pubg-typescript-api/master/src/entities/telemetry/objects/character.ts
- https://api.github.com/repos/martinsileno/pubg-typescript-api/git/trees/master?recursive=1
- https://api.github.com/repos/ramonsaraiva/pubg-python/git/trees/master?recursive=1
- https://chicken-dinner.readthedocs.io/en/latest/models/telemetry.html — Python `chicken_dinner` telemetry model notes

---

## 1. Fetching telemetry

Telemetry is **not** returned inline with a match. It is a two-step fetch.

### Step 1 — get the match, find the telemetry asset

```
GET https://api.pubg.com/shards/{platform}/matches/{matchId}
Accept: application/vnd.api+json
Authorization: Bearer {api-key}
```

The response is JSON:API. `data.relationships.assets.data[]` gives asset ids; resolve each id
against the top-level `included[]` array. The asset object of `"type": "asset"` carries the
telemetry file URL in `attributes.URL`.

> ⚠️ **Casing trap:** the attribute is `URL` — **all caps**, not `url`. This is the single most
> commonly mis-typed field in the whole API.

### Step 2 — download the telemetry file from the CDN

```
GET {that URL}
Accept: application/vnd.api+json
Accept-Encoding: gzip
```

- **No API key is required** for the CDN download. The docs state this explicitly.
- Telemetry files are served **gzip-compressed**. The docs instruct clients to send
  `Accept-Encoding: gzip`. With `curl` this is `curl --compressed`.
- Host is `telemetry-cdn.pubg.com` (historically `telemetry-cdn.playbattlegrounds.com`).
  Path shape observed in docs: `/{shard-or-bucket}/{YYYY}/{MM}/{DD}/{HH}/{mm}/{uuid}-telemetry.json`.
  **Never construct this URL yourself — always use the `URL` attribute verbatim.**
- Telemetry files are **eventually purged**; the retention window is undocumented.
  ⚠️ *Correction:* `telemetry.rst` contains exactly **one** example URL (`pc-krjp/…`, repeated
  twice) and explicitly labels it *"the URL is only an example and will not work"*. The second URL
  previously cited here (`bluehole-pubg/steam/…`) is **not** in the official docs at all — it comes
  from the `pubg-python` / `pubg-typescript-api` test fixtures. Both do return HTTP 403 when
  fetched, but since neither was ever a live URL, **no inference about "403 = expired" is
  supported.** The sound rule stands: **never construct this URL yourself — always use the `URL`
  attribute verbatim.**

### Sizes and counts (observed)

| Metric | Observed value |
|---|---|
| File size (uncompressed), 2019 sample | 20,185,531 bytes ≈ 19.3 MiB for one 99-player squad match |
| Event count, 2019 sample | 39,284 |
| Whitespace | **none** — the entire file is a single line |
| Gzipped size, 2019 sample | **1,691,484 bytes = 1.61 MiB (11.9×)** — measured, `gzip level 9` |
| File size (uncompressed), modern | **37.7 – 39.4 MB** per match |
| Event count, modern | **52,714 – 56,188** |
| Gzipped size, modern | **2.38 – 2.73 MiB** |

Budget **~40–60 MB** of RAM per **modern** match if you `JSON.parse` the whole file (the older
~20–30 MB figure reflects the 2019 sample and is roughly half of current reality). A 100-player
match is the worst case; smaller modes produce proportionally fewer events.

---

## 2. Top-level file structure

The file is a **flat JSON array of heterogeneous event objects**. There is no envelope, no
`data` wrapper, no pagination.

```json
[
  {"MatchId":"match.bro.official.pc-2018-04.steam.squad-fpp.eu.2019.10.23.00.db8f8222-4300-4683-9483-db85602ff756","PingQuality":"low","SeasonState":"closed","_D":"2019-10-23T00:18:48.7334511Z","_T":"LogMatchDefinition"},
  {"accountId":"account.16c7103a56b64806b491844ffc73b400","common":{"isGame":0},"_D":"2019-10-23T00:17:24.526Z","_T":"LogPlayerLogin"},
  {"character":{"name":"Sl4y3r__","teamId":15,"health":100,"location":{"x":796378.6875,"y":19669.08984375,"z":547.231201171875},"ranking":0,"accountId":"account.16c7103a56b64806b491844ffc73b400","isInBlueZone":false,"isInRedZone":false,"zone":[]},"common":{"isGame":0},"_D":"2019-10-23T00:17:24.547Z","_T":"LogPlayerCreate"}
]
```

### The three universal fields

| Field | Type | Meaning |
|---|---|---|
| `_T` | string | Event type discriminator, e.g. `"LogPlayerKillV2"`. Always present. |
| `_D` | string | Event timestamp, ISO-8601 UTC, always ends `Z`. Always present. |
| `common` | object | `{ "isGame": number }`. Present on **every event except `LogMatchDefinition`**. |

**Observed key order.** ⚠️ This **differs between eras** — do not rely on it for parsing:

- **Modern (2026) payloads:** `_T` is the **first** key, then the event-specific fields, then
  `common`, then `_D` **last**.
- **2019 sample:** event-specific fields first, then `common`, then `_D`, then `_T`.

The JSON examples in this document are reproduced in 2019-sample order.

### `_D` timestamp format — two different precisions

This is a real parser trap. Observed in one single file:

| Fractional digits | Count | Example | Which events |
|---|---|---|---|
| 3 | 39,283 | `2019-10-23T00:17:24.526Z` | everything else |
| 7 | 1 | `2019-10-23T00:18:48.7334511Z` | `LogMatchDefinition` only |

All values end in `Z`. Seven-digit fractional seconds is .NET "round-trip" (`O`) format and is
**not** parseable by naive `strptime("%Y-%m-%dT%H:%M:%S.%fZ")` in Python (Python's `%f` accepts at
most 6 digits) and is lossy in JavaScript `Date.parse` (truncates to ms — acceptable).
Use a tolerant ISO-8601 parser, or regex-truncate the fraction to 3 digits before parsing.

### `common.isGame` — match phase

Documented meaning:

| `isGame` | Meaning |
|---|---|
| `0` | Before lift off |
| `0.1` | On the airplane |
| `0.5` | Landed, no zone on map yet |
| `1.0` | First safezone and bluezone appear |
| `1.5` | First bluezone starts shrinking |
| `2.0` | Second bluezone appears |
| `2.5` | Second bluezone shrinks |
| `n.0` / `n.5` | …pattern repeats |

Values actually observed in the sample match, **with counts**:

| Value | Event count |
|---|---|
| `0` | 1,474 |
| `0.10000000149011612` | 3,444 |
| `1` | 10,717 |
| `1.5` | 7,583 |
| `2` | 6,005 |
| `2.5` | 2,561 |
| `3` | 2,323 |
| `3.5` | 1,545 |
| `4` | 1,409 |
| `4.5` | 354 |
| `5` | 550 |
| `5.5` | 275 |
| `6` | 554 |
| `6.5` | 122 |
| `7` | 367 |

> ⚠️ **`isGame` 0.1 is literally `0.10000000149011612`.** The server serialises a 32-bit float
> into a 64-bit JSON number. `isGame === 0.1` is **always false**. Compare with a tolerance
> (`Math.abs(v - 0.1) < 1e-6`) or, better, `Math.round(v * 2) / 2` to snap to the half-step grid
> — but note that snapping maps `0.1` onto `0`, so special-case the airplane phase first.
>
> `0.5` was **not** observed in this match; do not assume every documented step occurs.

---

## 3. Event ordering guarantees

Measured over all 39,283 adjacent pairs in the sample file:

- **2 pairs out of 39,283 were out of `_D` order.** The array is *almost* but **not** strictly
  sorted ascending by `_D`.
- Violation #1 — **structural and always present**: `LogMatchDefinition` is the **first element of
  the array** but carries a timestamp ~84 seconds *later* than the second element.
  ```
  idx 0  LogMatchDefinition   2019-10-23T00:18:48.7334511Z
  idx 1  LogPlayerLogin       2019-10-23T00:17:24.526Z
  ```
- Violation #2 — a 1 ms inversion between two genuinely simultaneous events:
  ```
  idx 9677  LogPlayerUseThrowable  2019-10-23T00:22:26.265Z
  idx 9678  LogPlayerAttack        2019-10-23T00:22:26.264Z
  ```

**Practical rules:**

1. Treat array order as the primary ordering for causally-related events; it is more reliable
   than `_D` at millisecond granularity.
2. If you sort by `_D`, use a **stable** sort so ties preserve file order.
3. Special-case `LogMatchDefinition` — do not let it define the match start time.
4. The **last** event is not `LogMatchEnd`. Observed last event was `LogItemUnequip`
   at `00:47:54.129Z`, while `LogMatchEnd` occurred earlier at `00:47:02.254Z`. Never assume
   the terminal element is the match end.

---

## 4. Shared objects

### `Character`

Present as `character`, `attacker`, `victim`, `killer`, `reviver`, `assistant`, `dBNOMaker`,
`finisher`, and inside the `characters[]`, `drivers[]`, `fellowPassengers[]`, `survivors[]` arrays.

```json
{
  "name": "soFENDI",
  "teamId": 20,
  "health": 86.18868255615234,
  "location": { "x": 541025.9375, "y": 235078.671875, "z": 184.67999267578125 },
  "ranking": 0,
  "accountId": "account.82d973a786fb4ee6a607eeb81f67d70c",
  "isInBlueZone": true,
  "isInRedZone": false,
  "zone": ["yasnayapolyana"]
}
```

⚠️ **The modern `Character` has 14 fields, not 9.** Five of them are absent from the official
object docs entirely. Full modern key set:

`name`, `teamId`, `health`, `location`, `ranking`, `individualRanking`, `accountId`,
`isInBlueZone`, `isInRedZone`, `inSpecialZone`, `isInVehicle`, `zone`, `type`, `isDBNO`.

| Field | Type | Notes |
|---|---|---|
| `name` | string | In-game nickname at match time. Not stable across renames. |
| `teamId` | int | Per-match team number. `1`–`30` for real players (verified from the 99 `LogPlayerCreate` events), contiguous, 30 distinct teams for 99 players in squads. Unique **within a match only**. ⚠️ **`teamId: 0` also occurs** — see sentinel note below. |
| `health` | number | 0–100 float. `0` means knocked or dead. |
| `location` | `Location` | See below. |
| `ranking` | int | **Team placement.** Usually `0`, but **not always** — it becomes non-zero once a player's placement is locked in (i.e. after death) and then appears non-zero on ordinary mid-match events. Reliable only in `LogMatchEnd`. Treat as *"unreliable / mostly zero before match end"*, **not** *"always zero"*. |
| `individualRanking` | int | ⚠️ **Modern, undocumented.** Individual (not team) placement; observed `1`–`96`. |
| `accountId` | string | Stable player id, `"account."` prefix. **Use this as the join key, never `name`.** |
| `isInBlueZone` | bool | |
| `isInRedZone` | bool | |
| `inSpecialZone` | bool | ⚠️ Modern, undocumented. |
| `isInVehicle` | bool | ⚠️ Modern, undocumented. |
| `zone` | string[] | Named POI regions the player is inside; `[]` when in open terrain. |
| `type` | string | ⚠️ Modern, undocumented. Observed `"user"`. |
| `isDBNO` | bool | ⚠️ Modern, undocumented — **directly useful**: knocked state without deriving it from `LogPlayerMakeGroggy`/`LogPlayerRevive` pairing. |

> ⚠️ **Sentinel `Character` with `teamId: 0`.** The single `attackType: "RedZone"` `LogPlayerAttack`
> in the 2019 sample carries an `attacker` with `name: ""`, `accountId: ""`, `teamId: 0` — a
> synthetic non-player actor. Any roster join keyed on `accountId` will silently miss or
> mis-attribute it. **Guard for empty `accountId` before joining.**

**Non-zero `ranking` outside `LogMatchEnd`** — re-parse of the 2019 sample found **998** such
occurrences: `LogItemUnequip.character` 416/1,272, `LogItemDetach.character` 141/887,
`LogPlayerTakeDamage.victim` 107/8,666, `LogPlayerAttack.attacker` 105/4,996,
`LogPlayerPosition.character` 80/7,495, `LogPlayerKill.victim` 27/95. (A previously stated
"32,989 of 33,320" figure did not reproduce under any slot definition and has been removed;
the file contains 24,890 top-level `character` objects and 41,432 `Character`-shaped objects.)

Observed `zone` values (Erangel, 18 distinct, all **lowercase, no separators**):
`yasnayapolyana`, `school`, `pochinki`, `rozhok`, `georgopol`, `severny`, `gatka`,
`sosnovkamilitarybase`, `stalber`, `quarry`, `hospital`, `mansion`, `mylta`, `shelter`,
`ferrypier`, `primorsk`, `myltapower`, `lipovka`.

### `Location`

```json
{ "x": 541025.9375, "y": 235078.671875, "z": 184.67999267578125 }
```

- Units are **centimetres**. Divide by 100 for metres.
- Origin `(0,0)` is the **top-left** of the map image; `y` increases **downward**.
  For a standard screen-space render you use `x` and `y` directly — do **not** flip `y`.
- `z` is altitude. Observed range in the sample: **`-2191.560546875`** … `150088` (the aircraft).
  (The minimum occurs at `LogVehicleLeave.character`; the previously stated `-2151` did not
  reproduce under any subset.)
- `x` can be **slightly negative** (observed min `-11623.21875`) — clamp, don't assume `>= 0`.
- Documented per-map coordinate ranges:

| Range (cm) | Maps |
|---|---|
| 0 – 816,000 | Erangel, Miramar, Taego, Vikendi, Deston |
| 0 – 408,000 | Sanhok |
| 0 – 306,000 | Paramo |
| 0 – 204,000 | Karakin, Range (Camp Jackal) |
| 0 – 102,000 | Haven |

To convert to a fraction of the map image: `u = x / mapExtent`, `v = y / mapExtent`.

### `Item`

```json
{
  "itemId": "Item_Weapon_BerylM762_C",
  "stackCount": 1,
  "category": "Weapon",
  "subCategory": "Main",
  "attachedItems": [
    "Item_Attach_Weapon_Magazine_ExtendedQuickDraw_Large_C",
    "Item_Attach_Weapon_Lower_Foregrip_C",
    "Item_Attach_Weapon_Upper_DotSight_01_C",
    "Item_Attach_Weapon_Muzzle_Compensator_Large_C"
  ]
}
```

| Field | Type | Notes |
|---|---|---|
| `itemId` | string | e.g. `Item_Weapon_BerylM762_C`. Dictionary: `dictionaries/telemetry/item/itemId.json`. |
| `stackCount` | int | |
| `category` | string | |
| `subCategory` | string | |
| `attachedItems` | string[] | Array of **itemId strings**, not objects. |

Observed `category` / `subCategory` pairs:

| category | subCategory |
|---|---|
| `Ammunition` | `None` |
| `Attachment` | `None` |
| `Equipment` | `Backpack`, `Headgear`, `Throwable`, `Vest` |
| `Use` | `Boost`, `Fuel`, `Heal` |
| `Weapon` | `Handgun`, `Main`, `Melee` |

### `Vehicle`

Observed shape (2019 payload):

```json
{
  "vehicleType": "WheeledVehicle",
  "vehicleId": "Buggy_A_01_C",
  "vehicleUniqueId": 503092,
  "healthPercent": 95.28163146972656,
  "feulPercent": 74.62688446044922,
  "rotationPitch": 7.509047985076904,
  "seatIndex": 0,
  "isWheelsInAir": false,
  "isInWaterVolume": false
}
```

| Field | Type | Notes |
|---|---|---|
| `vehicleType` | string | Observed: `WheeledVehicle`, `FloatingVehicle`, `TransportAircraft`. |
| `vehicleId` | string | Blueprint name, e.g. `Dacia_A_01_v2_C`, `BP_BRDM_C`, `DummyTransportAircraft_C`. |
| `vehicleUniqueId` | int | ⚠️ **2019-ONLY — REMOVED.** Absent from all modern payloads and from the official `telemetry-objects.rst` `Vehicle` block. **There is no per-instance vehicle id in current telemetry** — you cannot track an individual vehicle by key. Reading it on a modern event yields `undefined` with no error (silent-empty-data trap). |
| `healthPercent` | number | 0–100. |
| `feulPercent` | number | ⚠️ **Misspelled in the actual wire format.** Not `fuelPercent`. |
| `rotationPitch` | number | ⚠️ **2019-ONLY — removed in v17.0.0** (`changelog.rst`: *"Removed: Vehicle.rotationPitch"*). It *was* documented — added v14.2.0 \[PC\] / v15.1.0 \[PS4, Xbox\]. Absent from all modern payloads. |
| `seatIndex` | int | |
| `isWheelsInAir` | bool | |
| `isInWaterVolume` | bool | |
| `altitudeAbs` | number | Documented; added in **v17.2.0** — absent from the 2019 sample, **present in modern payloads**. |
| `altitudeRel` | number | Documented; added in **v17.2.0**. Present in modern payloads. |
| `velocity` | number | Documented; added in **v17.2.0**. Present in modern payloads. |
| `isEngineOn` | bool | Documented; added in **v17.2.0**. Present in modern payloads. |
| `location` | `Location` | Present in modern payloads. |

**Modern `Vehicle` key set is exactly:** `vehicleType`, `vehicleId`, `seatIndex`, `healthPercent`,
`feulPercent`, `altitudeAbs`, `altitudeRel`, `velocity`, `isWheelsInAir`, `isInWaterVolume`,
`isEngineOn`, `location`.

Observed `vehicleType` → `vehicleId` pairs in the sample:
`TransportAircraft|DummyTransportAircraft_C`, `WheeledVehicle|{Dacia_A_01_v2_C, Dacia_A_02_v2_C,
Dacia_A_03_v2_C, Uaz_A_01_C, Uaz_B_01_C, Uaz_C_01_C, Buggy_A_01_C, Buggy_A_02_C, Buggy_A_03_C,
BP_Motorbike_04_C, BP_Motorbike_04_SideCar_C, BP_BRDM_C}`, `FloatingVehicle|Boat_PG117_C`.

The `TransportAircraft` entry is how you detect a player still on the plane.

### `GameState`

Observed shape (2019 payload — no black zone fields):

```json
{
  "elapsedTime": 838,
  "numAliveTeams": 10,
  "numJoinPlayers": 95,
  "numStartPlayers": 98,
  "numAlivePlayers": 32,
  "safetyZonePosition": { "x": 508659.375, "y": 572304.625, "z": 0 },
  "safetyZoneRadius": 202901.53125,
  "poisonGasWarningPosition": { "x": 516141.46875, "y": 600652.625, "z": 0 },
  "poisonGasWarningRadius": 121740.921875,
  "redZonePosition": { "x": 251287.046875, "y": 300256.53125, "z": 0 },
  "redZoneRadius": 50000
}
```

⚠️ **Modern `GameState` carries three further fields, absent from both the 2019 sample and the
official docs:** `numStartTeams`, `numParticipatedTeams`, `numParticipatedPlayers`.
Full modern key set: `elapsedTime`, `numStartTeams`, `numAliveTeams`, `numParticipatedTeams`,
`numJoinPlayers`, `numStartPlayers`, `numAlivePlayers`, `numParticipatedPlayers`,
`safetyZonePosition`, `safetyZoneRadius`, `poisonGasWarningPosition`, `poisonGasWarningRadius`,
`redZonePosition`, `redZoneRadius`, `blackZonePosition`, `blackZoneRadius`.

| Field | Type | Notes |
|---|---|---|
| `elapsedTime` | int | Seconds since match start. Observed `10` … `1666`. |
| `numStartTeams` | int | ⚠️ Modern, undocumented. |
| `numAliveTeams` | int | |
| `numParticipatedTeams` | int | ⚠️ Modern, undocumented. |
| `numParticipatedPlayers` | int | ⚠️ Modern, undocumented. |
| `numJoinPlayers` | int | |
| `numStartPlayers` | int | |
| `numAlivePlayers` | int | |
| `safetyZonePosition` | `Location` | The **current** white circle centre. `z` is always `0`. |
| `safetyZoneRadius` | number | Centimetres. |
| `poisonGasWarningPosition` | `Location` | The **next** (target) circle centre — this is what you draw as the incoming white circle. |
| `poisonGasWarningRadius` | number | Centimetres. |
| `redZonePosition` | `Location` | All-zero `{x:0,y:0,z:0}` when no red zone is active. |
| `redZoneRadius` | number | `0` when inactive; observed `50000` when active. |
| `blackZonePosition` | `Location` | Documented; added **v16.1.0–v16.2.0**. Absent from the 2019 sample. |
| `blackZoneRadius` | number | Documented; added **v16.1.0–v16.2.0**. |

**Naming trap:** the blue zone (the damaging wall) is the *current* `safetyZone*` boundary, and
the *upcoming* circle is `poisonGasWarning*`. There is no field literally called "blueZone".

### `Common`

```json
{ "isGame": 1.5 }
```

Only one field, `isGame`, was observed on PC — in the 2019 sample **and confirmed in all four
modern PC payloads**. Some third-party Go wrappers also model `matchId` and `mapName` inside
`common`; **neither appears in any sampled PC file, 2019 or modern**. Treat them as absent on PC
(possibly console-only or stale wrapper modelling).

### `DamageInfo`

Used only by `LogPlayerKillV2`. Not present in the 2019 sample file, but **confirmed in the modern
payloads** (1,266 instances) with `additionalInfo` and `isThroughPenetrableWall` exactly as
documented:

```json
{
  "damageReason": "TorsoShot",
  "damageTypeCategory": "Damage_Gun",
  "damageCauserName": "WeapHK416_C",
  "additionalInfo": ["Item_Attach_Weapon_Upper_DotSight_01_C"],
  "distance": 5423.19,
  "isThroughPenetrableWall": false
}
```

Note the attachment array here is `additionalInfo` — **not** `damageCauserAdditionalInfo` as in
the V1 events.

### `GameResult` and `Stats`

Observed inside `LogPlayerKill.victimGameResult`:

```json
{
  "rank": 0,
  "gameResult": "",
  "teamId": 27,
  "stats": {
    "killCount": 0,
    "distanceOnFoot": 1056.1524658203125,
    "distanceOnSwim": 0,
    "distanceOnVehicle": 0,
    "distanceOnParachute": 370.0971984863281,
    "distanceOnFreefall": 1731.5845947265625
  },
  "accountId": "account.c8ddf25d8d614b4b89d3a836eb7d32ce"
}
```

Observed inside `LogMatchEnd.gameResultOnFinished.results[]` — note the **extra fields**:

```json
{
  "rank": 1,
  "gameResult": "",
  "teamId": 18,
  "stats": {
    "killCount": 5,
    "score": 517,
    "xp": 280,
    "distanceOnFoot": 4168.8037109375,
    "distanceOnSwim": 304.90435791015625,
    "distanceOnVehicle": 1301.11083984375,
    "distanceOnParachute": 362.0933837890625,
    "distanceOnFreefall": 1232.1220703125
  },
  "isBpGrinder": false,
  "isXpGrinder": false,
  "accountId": "account.3a796212bb13494f8558e9f04365cf5a"
}
```

> ⚠️ **`Stats.score`, `Stats.xp`, `GameResult.isBpGrinder` and `GameResult.isXpGrinder` are
> 2019-ONLY.** They are real but undocumented, appear **only** in the `LogMatchEnd` variant, and
> are **absent from all four modern payloads**. In modern telemetry:
> - `GameResult` has **`isRewardAbuse`** instead of `isBpGrinder`/`isXpGrinder`.
> - `Stats` has **no `score` / `xp`**, but adds `bpRewardDetail`, `arcadeRewardDetail`,
>   `statTrakDataPairs`, `headshotStatTrakDataPairs`.
>
> Model all of the above as optional and era-dependent.
>
> ⚠️ `gameResult` was the **empty string** in all **99** observed instances (95 in
> `victimGameResult`, 4 in `LogMatchEnd`), including the four rank-1 winners. Do not rely on it to
> determine a win. Use `rank`.
>
> ⚠️ `rank` is `0` inside `victimGameResult` on kill events (it is not yet known); it is only
> meaningful in `LogMatchEnd`.

All `distanceOn*` values are in **centimetres**.

### `ItemPackage`

```json
{
  "itemPackageId": "...",
  "location": { "x": 0, "y": 0, "z": 0 },
  "items": [ { "itemId": "...", "stackCount": 1, "category": "...", "subCategory": "...", "attachedItems": [] } ]
}
```

### `CharacterWrapper`

**The element type of `LogMatchStart.characters[]` and `LogMatchEnd.characters[]` in modern
telemetry** — documented, and confirmed present in all four 2026 payloads:

```json
{
  "character": { },
  "primaryWeaponFirst": "string",
  "primaryWeaponSecond": "string",
  "secondaryWeapon": "string",
  "spawnKitIndex": 0
}
```

> ⚠️ **Era conflict — the docs are right for modern matches.** All four 2026 payloads use
> `CharacterWrapper` in **both** `LogMatchStart` and `LogMatchEnd`; the modern element key set is
> exactly `{character, primaryWeaponFirst, primaryWeaponSecond, secondaryWeapon, spawnKitIndex}`.
> The 2019 sample instead contained **plain `Character` objects** with no `character` key.
>
> **Write your parser to accept both shapes** — this is mandatory, not a footnote: if the element
> has a `character` key, unwrap it; otherwise treat the element as the `Character` itself.
> Reading `characters[].ranking` directly on modern data raises `KeyError: 'ranking'`.
>
> Final placements on modern data live at **`LogMatchEnd.characters[].character.ranking`** (team
> rank, observed `1`–`27`) and **`.character.individualRanking`** (observed `1`–`96`).

---

## 5. Core player events

Every example below is a **verbatim, unmodified event** from the real telemetry file (arrays in
`LogMatchStart`/`LogMatchEnd` trimmed, which is marked inline).

### `LogPlayerLogin`

```json
{
  "accountId": "account.05a865a404564c11a6e8a1715261865b",
  "common": { "isGame": 0 },
  "_D": "2019-10-23T00:17:30.004Z",
  "_T": "LogPlayerLogin"
}
```

| Field | Type |
|---|---|
| `accountId` | string |

Carries **no** `Character` — you cannot get a name or team from this event alone. Observed 99 occurrences (one per player).

### `LogPlayerLogout`

```json
{
  "accountId": "account.94f91a1bc4d0454ba61487c276cb1507",
  "common": { "isGame": 1.5 },
  "_D": "2019-10-23T00:30:06.389Z",
  "_T": "LogPlayerLogout"
}
```

| Field | Type |
|---|---|
| `accountId` | string |

Observed 99 occurrences. **A logout does not mean a death** — it fires when the client disconnects, which for most players is after they die and leave, but the two are independent.

### `LogPlayerCreate`

```json
{
  "character": {
    "name": "Clex-",
    "teamId": 18,
    "health": 100,
    "location": { "x": 797566.8125, "y": 18388.900390625, "z": 547.231201171875 },
    "ranking": 0,
    "accountId": "account.05a865a404564c11a6e8a1715261865b",
    "isInBlueZone": false,
    "isInRedZone": false,
    "zone": []
  },
  "common": { "isGame": 0 },
  "_D": "2019-10-23T00:17:30.014Z",
  "_T": "LogPlayerCreate"
}
```

| Field | Type |
|---|---|
| `character` | `Character` |

**This is your roster-building event.** It is the earliest event that maps `accountId → name` and
`accountId → teamId`. The `location` here is the pre-match lobby spawn, **not** a map position —
do not plot it.

### `LogPlayerPosition`

```json
{
  "character": {
    "name": "CARFF",
    "teamId": 8,
    "health": 99.76122283935547,
    "location": { "x": 293226.3125, "y": 506317.09375, "z": 1013.0713500976562 },
    "ranking": 0,
    "accountId": "account.1d46afd6dd55469687003fb2d2cc6816",
    "isInBlueZone": false,
    "isInRedZone": false,
    "zone": []
  },
  "vehicle": {
    "vehicleType": "WheeledVehicle",
    "vehicleId": "Buggy_A_01_C",
    "vehicleUniqueId": 503092,
    "healthPercent": 95.28163146972656,
    "feulPercent": 74.62688446044922,
    "rotationPitch": 7.509047985076904,
    "seatIndex": 0,
    "isWheelsInAir": false,
    "isInWaterVolume": false
  },
  "elapsedTime": 567,
  "numAlivePlayers": 50,
  "common": { "isGame": 1.5 },
  "_D": "2019-10-23T00:28:25.693Z",
  "_T": "LogPlayerPosition"
}
```

| Field | Type | Notes |
|---|---|---|
| `character` | `Character` | |
| `vehicle` | `Vehicle` \| **`null`** | `null` when on foot. Observed non-null 1,230 / 7,495. |
| `elapsedTime` | number | Seconds since match start. Observed `0` … `1669`. |
| `numAlivePlayers` | int | |

**Sampling cadence (measured per-player):** median **10.003 s**, p25 9.989 s, p75 10.011 s,
p95 10.025 s, min 9.713 s, max 10.985 s over 7,396 intervals across 99 players.

> ⚠️ **This is the single most important limitation for a replay dashboard.** Positions are
> logged only ~every 10 seconds per player. You **must** interpolate between samples to render
> smooth movement, and a player can travel hundreds of metres between two consecutive points.
> Higher-fidelity positions for a specific moment can sometimes be recovered from the
> `Character` embedded in `LogPlayerAttack` / `LogPlayerTakeDamage` / `LogPlayerPosition`
> events, which fire at their own (event-driven) times.

Observed 7,495 events — the second most common event type.

### `LogParachuteLanding`

```json
{
  "character": {
    "name": "XpertX",
    "teamId": 23,
    "health": 100,
    "location": { "x": 389319.53125, "y": 278269.96875, "z": 3320.2822265625 },
    "ranking": 0,
    "accountId": "account.1acec499b8db42b2bd2deeddd97b78ad",
    "isInBlueZone": false,
    "isInRedZone": false,
    "zone": ["rozhok"]
  },
  "distance": 296.4188232421875,
  "common": { "isGame": 0.10000000149011612 },
  "_D": "2019-10-23T00:20:09.895Z",
  "_T": "LogParachuteLanding"
}
```

| Field | Type | Notes |
|---|---|---|
| `character` | `Character` | |
| `distance` | number | Centimetres travelled **under parachute** (not total drop distance). |

Observed 98 events (one per player who landed). Excellent for computing landing spots / hot-drop heat maps.

### `LogPlayerAttack`

```json
{
  "attackId": 956302055,
  "fireWeaponStackCount": 37,
  "attacker": {
    "name": "soFENDI",
    "teamId": 20,
    "health": 86.18868255615234,
    "location": { "x": 541025.9375, "y": 235078.671875, "z": 184.67999267578125 },
    "ranking": 0,
    "accountId": "account.82d973a786fb4ee6a607eeb81f67d70c",
    "isInBlueZone": true,
    "isInRedZone": false,
    "zone": ["yasnayapolyana"]
  },
  "attackType": "Weapon",
  "weapon": {
    "itemId": "Item_Weapon_BerylM762_C",
    "stackCount": 1,
    "category": "Weapon",
    "subCategory": "Main",
    "attachedItems": [
      "Item_Attach_Weapon_Magazine_ExtendedQuickDraw_Large_C",
      "Item_Attach_Weapon_Lower_Foregrip_C",
      "Item_Attach_Weapon_Upper_DotSight_01_C",
      "Item_Attach_Weapon_Muzzle_Compensator_Large_C"
    ]
  },
  "vehicle": null,
  "common": { "isGame": 2 },
  "_D": "2019-10-23T00:31:10.986Z",
  "_T": "LogPlayerAttack"
}
```

| Field | Type | Notes |
|---|---|---|
| `attackId` | int | **Unique within the match** — 4,996 distinct across 4,996 events. Join key to `LogPlayerTakeDamage`. |
| `fireWeaponStackCount` | int | Rounds remaining in the magazine. |
| `attacker` | `Character` | |
| `attackType` | string | **Within `LogPlayerAttack`:** `"Weapon"` 4,995, `"RedZone"` 1. (A previously stated 5,092 was an aggregate across `LogPlayerAttack` + `LogPlayerUseThrowable`; the other 97 `Weapon` values come from `LogPlayerUseThrowable`.) |
| `weapon` | `Item` | |
| `vehicle` | `Vehicle` \| `null` | Observed `null` in all 4,996 sample events. |

This is **one event per shot fired** (or melee swing). It does **not** mean a hit landed.

### `LogPlayerTakeDamage`

```json
{
  "attackId": 1375731771,
  "attacker": {
    "name": "Zzenk",
    "teamId": 26,
    "health": 12.432504653930664,
    "location": { "x": 437009.4375, "y": 332152.5625, "z": 634.989990234375 },
    "ranking": 0,
    "accountId": "account.f9553a3b81ce485fa2425cacddadccbe",
    "isInBlueZone": false,
    "isInRedZone": false,
    "zone": ["school"]
  },
  "victim": {
    "name": "beSzian",
    "teamId": 6,
    "health": 30.719999313354492,
    "location": { "x": 437555.46875, "y": 332221.6875, "z": 606.989990234375 },
    "ranking": 0,
    "accountId": "account.ceaea48c9fa64bf3aecff7b4204eb516",
    "isInBlueZone": false,
    "isInRedZone": false,
    "zone": ["school"]
  },
  "damageTypeCategory": "Damage_Gun",
  "damageReason": "TorsoShot",
  "damage": 23.369998931884766,
  "damageCauserName": "WeapHK416_C",
  "common": { "isGame": 1 },
  "_D": "2019-10-23T00:24:56.605Z",
  "_T": "LogPlayerTakeDamage"
}
```

| Field | Type | Notes |
|---|---|---|
| `attackId` | int | **`-1` for environmental damage.** 7,909 of 8,666 events had `attackId <= 0`. |
| `attacker` | `Character` \| **`null`** | `null` for blue-zone/environment damage — observed `null` 6,820 / 8,666. |
| `victim` | `Character` | |
| `damageTypeCategory` | string | See enum table. |
| `damageReason` | string | See enum table. |
| `damage` | number | HP removed. **`victim.health` is the health *before* this damage is applied.** |
| `damageCauserName` | string | See `damageCauserName.json` dictionary (**209 entries**). |
| `isThroughPenetrableWall` | bool | Added **v16.1.0 \[PC\] / v16.2.0 \[PS4, Xbox\]** (alongside `LogBlackZoneEnded` and `GameState.blackZone*`). **Absent** from the 2019 sample; **present on all 35,982 modern `LogPlayerTakeDamage` events.** |

Most common event type — 8,666 occurrences, of which the large majority is blue-zone tick damage.
**Filter out `attacker === null` before computing player-vs-player damage stats.**

`attackId` only joins back to a `LogPlayerAttack` for genuine weapon fire: only
**757 of 8,666** damage events had an `attackId` matching a `LogPlayerAttack`.

### `LogPlayerMakeGroggy`

Fired when a player is knocked down (DBNO) in a team mode.

```json
{
  "attackId": 788529240,
  "attacker": {
    "name": "Sh1sHH",
    "teamId": 18,
    "health": 75,
    "location": { "x": 382452.03125, "y": 474205.78125, "z": 2293.929931640625 },
    "ranking": 0,
    "accountId": "account.3a796212bb13494f8558e9f04365cf5a",
    "isInBlueZone": false,
    "isInRedZone": false,
    "zone": []
  },
  "victim": {
    "name": "CARFF",
    "teamId": 8,
    "health": 0,
    "location": { "x": 382234.625, "y": 473653, "z": 2321.77001953125 },
    "ranking": 0,
    "accountId": "account.1d46afd6dd55469687003fb2d2cc6816",
    "isInBlueZone": false,
    "isInRedZone": false,
    "zone": []
  },
  "damageReason": "TorsoShot",
  "damageTypeCategory": "Damage_Gun",
  "damageCauserName": "WeapSCAR-L_C",
  "damageCauserAdditionalInfo": [
    "Item_Attach_Weapon_Muzzle_Compensator_Large_C",
    "Item_Attach_Weapon_Magazine_ExtendedQuickDraw_Large_C",
    "Item_Attach_Weapon_Upper_DotSight_01_C",
    "Item_Attach_Weapon_Lower_LightweightForeGrip_C"
  ],
  "distance": 594.649169921875,
  "isAttackerInVehicle": false,
  "dBNOId": 385875968,
  "victimWeapon": "WeapBerylM762_C_12",
  "victimWeaponAdditionalInfo": [
    "Item_Attach_Weapon_Muzzle_Compensator_Large_C",
    "Item_Attach_Weapon_Upper_DotSight_01_C",
    "Item_Attach_Weapon_Magazine_ExtendedQuickDraw_Large_C"
  ],
  "common": { "isGame": 1.5 },
  "_D": "2019-10-23T00:30:17.259Z",
  "_T": "LogPlayerMakeGroggy"
}
```

| Field | Type | Notes |
|---|---|---|
| `attackId` | int | |
| `attacker` | `Character` | |
| `victim` | `Character` | `health` is `0` at knock. |
| `damageReason` | string | |
| `damageTypeCategory` | string | |
| `damageCauserName` | string | |
| `damageCauserAdditionalInfo` | string[] | Attacker's weapon attachments. |
| `distance` | number | **Centimetres.** `594.649` above is 5.9 m, not 594 m. |
| `isAttackerInVehicle` | bool | |
| `dBNOId` | int | Knock-down id. Join key to `LogPlayerKillV2` / `LogPlayerRevive`. |
| `victimWeapon` | string | ⚠️ **Observed lowercase `v` on PC.** Docs say `VictimWeapon`. See casing note below. |
| `victimWeaponAdditionalInfo` | string[] | ⚠️ Same casing issue. |
| `isThroughPenetrableWall` | bool | Added **v16.1.0 \[PC\] / v16.2.0 \[PS4, Xbox\]**. **Absent** from the 2019 sample; **present on all 432 modern `LogPlayerMakeGroggy` events.** |

Observed 81 events, all with **distinct** `dBNOId`.

> ⚠️ Note `victimWeapon` values here carry a numeric suffix (`WeapBerylM762_C_12`) that the
> `damageCauserName` values do not (`WeapSCAR-L_C`). Strip a trailing `_\d+` before dictionary lookup.

### `LogPlayerRevive`

```json
{
  "reviver": {
    "name": "Sl4y3r__",
    "teamId": 15,
    "health": 46.78505325317383,
    "location": { "x": 414111.34375, "y": 314012.21875, "z": 1069.47998046875 },
    "ranking": 0,
    "accountId": "account.16c7103a56b64806b491844ffc73b400",
    "isInBlueZone": true,
    "isInRedZone": false,
    "zone": ["school"]
  },
  "victim": {
    "name": "SirNicolas21",
    "teamId": 15,
    "health": 10,
    "location": { "x": 414094.0625, "y": 314090.4375, "z": 1078.5499267578125 },
    "ranking": 0,
    "accountId": "account.7a3a5201a1764a759d232c5ab3ddac88",
    "isInBlueZone": true,
    "isInRedZone": false,
    "zone": ["school"]
  },
  "dBNOId": 419430400,
  "common": { "isGame": 2 },
  "_D": "2019-10-23T00:31:17.478Z",
  "_T": "LogPlayerRevive"
}
```

| Field | Type | Notes |
|---|---|---|
| `reviver` | `Character` | |
| `victim` | `Character` | `health` is `10` post-revive. |
| `dBNOId` | int | Matches the originating `LogPlayerMakeGroggy`. |

Observed 16 events; **all 16** `dBNOId`s matched a preceding `LogPlayerMakeGroggy` — this join is reliable.

### `LogPlayerKillV2`

**This event does not exist in the sampled 2019 file** (which predates it), but it is **confirmed
real** against 422 `LogPlayerKillV2` events across the four modern payloads. The table below is the
official documented shape **plus two real undocumented fields** found only in the payloads.
Everything else in this table — `dBNOMaker`, `finishDamageInfo` (not `finisher…`),
`assists_AccountId`, no `assistant`, no top-level `damageCauserName` — is **confirmed correct
against real data**. `victimWeapon` / `victimWeaponAdditionalInfo` are **lowercase** on modern
payloads (the docs' PascalCase is simply wrong, on this event *and* on `LogPlayerMakeGroggy`).

Version history (from the official changelog):

| Version | Change |
|---|---|
| v20.3.0 | `LogPlayerKillV2` **added** |
| v20.5.0 | `assists_AccountId` and `teamKillers_AccountId` added |
| v21.0.0 | `LogPlayerKill` (V1) **removed** — "will not be removed from matches that finished before this update" |

So: **matches after v21.0.0 contain only `LogPlayerKillV2`; matches before v20.3.0 contain only
`LogPlayerKill`; matches in between may contain both.** Handle all three cases.

> ⚠️ **Tournament exception.** The v21.0.0 changelog entry ends *"This update does not effect
> tournament matches"*, and `telemetry-events.rst` still titles the V1 section
> **"LogPlayerKill (tournament matches)"**. **V1 survives in tournament telemetry post-v21** — so
> the rule is really four cases: never drop the `LogPlayerKill` fallback path.

Documented shape:

```json
{
  "attackId": 0,
  "dBNOId": 0,
  "victimGameResult": { },
  "victim": { },
  "victimWeapon": "string",
  "victimWeaponAdditionalInfo": ["string"],
  "dBNOMaker": { },
  "dBNODamageInfo": { },
  "finisher": { },
  "finishDamageInfo": { },
  "killer": { },
  "killerDamageInfo": { },
  "assists_AccountId": ["string"],
  "teamKillers_AccountId": ["string"],
  "isSuicide": false,
  "victimVehicle": { },
  "killerVehicle": { },
  "common": { "isGame": 0 },
  "_D": "…Z",
  "_T": "LogPlayerKillV2"
}
```

| Field | Type | Meaning |
|---|---|---|
| `attackId` | int | Links to the `LogPlayerAttack` that produced the killing blow. |
| `dBNOId` | int | Links to the `LogPlayerMakeGroggy` knock, if the victim was knocked first. |
| `victimGameResult` | `GameResult` | Victim's placement + stats snapshot. |
| `victim` | `Character` | |
| `victimWeapon` | string | Weapon the **victim** was holding. ⚠️ casing — see below. |
| `victimWeaponAdditionalInfo` | string[] | Victim's attachments. ⚠️ casing. |
| `dBNOMaker` | `Character` | Who **knocked** the victim. ⚠️ Note the casing: lowercase `d`, uppercase `BNO`, uppercase `M`. |
| `dBNODamageInfo` | `DamageInfo` | Damage details of the knock. |
| `finisher` | `Character` | Who dealt the **final blow** to a knocked player. |
| `finishDamageInfo` | `DamageInfo` | ⚠️ `finish`, **not** `finisher` — the prefix differs from the `finisher` field. |
| `killer` | `Character` | Who is **credited** with the kill. |
| `killerDamageInfo` | `DamageInfo` | |
| `assists_AccountId` | string[] | ⚠️ Snake/Pascal hybrid: `assists_AccountId`. Array of **account id strings**, not `Character`s. |
| `teamKillers_AccountId` | string[] | ⚠️ Same hybrid casing. |
| `isSuicide` | bool | |
| `victimVehicle` | `Vehicle` | ⚠️ **Real but undocumented** — present on all 422 modern `LogPlayerKillV2` events. **Not `null` when on foot**: it is a zeroed sentinel object with `vehicleType: ""` and `seatIndex: -1`. Check `vehicleType !== ""`, not `!= null`. |
| `killerVehicle` | `Vehicle` | ⚠️ Same — real, undocumented, zeroed-sentinel when on foot. |

> ⚠️ **Three corrections to common assumptions about `LogPlayerKillV2`:**
>
> 1. There is **no `assistant` field**. `assistant` is a `LogPlayerKill` (V1) field. V2 replaces it
>    with `assists_AccountId`, an **array of strings**.
> 2. There are **no top-level `damageCauserName`, `damageReason`, or `distance` fields**. Those
>    live *inside* the three `DamageInfo` sub-objects (`dBNODamageInfo`, `finishDamageInfo`,
>    `killerDamageInfo`). Reading `event.damageCauserName` on a V2 event yields `undefined`.
> 3. `killer`, `dBNOMaker` and `finisher` are **three different people** in the general case.
>    For a kill feed you almost always want `killer`. For "who knocked me", use `dBNOMaker`.

### `LogPlayerKill` (V1 — legacy, removed in v21.0.0)

Observed shape, still relevant for historical matches:

```json
{
  "attackId": 989856479,
  "killer": { "name": "volldampf", "teamId": 20, "health": 90.19000244140625, "location": { "x": 536812.6875, "y": 242027.921875, "z": 227.2899932861328 }, "ranking": 0, "accountId": "account.af1312d1a03e4726bb5919538f924d12", "isInBlueZone": false, "isInRedZone": false, "zone": ["yasnayapolyana"] },
  "victim": { "name": "Lidija_Bachich", "teamId": 27, "health": 0, "location": { "x": 537620.875, "y": 241746.46875, "z": 196.72999572753906 }, "ranking": 0, "accountId": "account.c8ddf25d8d614b4b89d3a836eb7d32ce", "isInBlueZone": false, "isInRedZone": false, "zone": ["yasnayapolyana"] },
  "assistant": { "name": "soFENDI", "teamId": 20, "health": 98.59998321533203, "location": { "x": 537554.4375, "y": 241745.96875, "z": 197.34999084472656 }, "ranking": 0, "accountId": "account.82d973a786fb4ee6a607eeb81f67d70c", "isInBlueZone": true, "isInRedZone": false, "zone": ["yasnayapolyana"] },
  "dBNOId": 1409286144,
  "damageReason": "TorsoShot",
  "damageTypeCategory": "Damage_Punch",
  "damageCauserName": "PlayerFemale_A_C",
  "damageCauserAdditionalInfo": [],
  "distance": 856.3392333984375,
  "victimGameResult": { "rank": 0, "gameResult": "", "teamId": 27, "stats": { "killCount": 0, "distanceOnFoot": 1056.1524658203125, "distanceOnSwim": 0, "distanceOnVehicle": 0, "distanceOnParachute": 370.0971984863281, "distanceOnFreefall": 1731.5845947265625 }, "accountId": "account.c8ddf25d8d614b4b89d3a836eb7d32ce" },
  "victimWeapon": "WeapSCAR-L_C_12",
  "victimWeaponAdditionalInfo": ["Item_Attach_Weapon_Upper_Holosight_C", "Item_Attach_Weapon_SideRail_DotSight_RMR_C"],
  "common": { "isGame": 1.5 },
  "_D": "2019-10-23T00:29:19.682Z",
  "_T": "LogPlayerKill"
}
```

Observed top-level keys, in payload order: `attackId`, `killer`, `victim`, `assistant`, `dBNOId`,
`damageReason`, `damageTypeCategory`, `damageCauserName`, `damageCauserAdditionalInfo`, `distance`,
`victimGameResult`, `victimWeapon`, `victimWeaponAdditionalInfo`, `common`, `_D`, `_T`.

Observed 95 events. `killer` and `assistant` were **never `null`** in this sample, and `dBNOId` was
never `0`; 65 of 95 `dBNOId`s matched a `LogPlayerMakeGroggy` (the other 30 were kills without a
prior knock — solo-mode-style instant kills or self-inflicted).

> ⚠️ `victimWeapon` and `victimWeaponAdditionalInfo` are **lowercase-`v`** in this real PC payload,
> which contradicts the official docs' `VictimWeapon` for `LogPlayerMakeGroggy`.

### `LogArmorDestroy`

```json
{
  "attackId": 989856481,
  "attacker": {
    "name": "volldampf", "teamId": 20, "health": 90.19000244140625,
    "location": { "x": 536791, "y": 242004.15625, "z": 227.5699920654297 },
    "ranking": 0, "accountId": "account.af1312d1a03e4726bb5919538f924d12",
    "isInBlueZone": false, "isInRedZone": false, "zone": ["yasnayapolyana"]
  },
  "victim": {
    "name": "Lidija_Bachich", "teamId": 27, "health": 0,
    "location": { "x": 537625.25, "y": 241731.53125, "z": 196.72999572753906 },
    "ranking": 0, "accountId": "account.c8ddf25d8d614b4b89d3a836eb7d32ce",
    "isInBlueZone": false, "isInRedZone": false, "zone": ["yasnayapolyana"]
  },
  "damageTypeCategory": "Damage_Gun",
  "damageReason": "HeadShot",
  "damageCauserName": "WeapDP28_C",
  "item": {
    "itemId": "Item_Head_F_02_Lv2_C",
    "stackCount": 1,
    "category": "Equipment",
    "subCategory": "Headgear",
    "attachedItems": []
  },
  "distance": 878.2075805664062,
  "common": { "isGame": 1.5 },
  "_D": "2019-10-23T00:29:03.557Z",
  "_T": "LogArmorDestroy"
}
```

| Field | Type | Notes |
|---|---|---|
| `attackId` | int | |
| `attacker` | `Character` | |
| `victim` | `Character` | |
| `damageTypeCategory` | string | |
| `damageReason` | string | |
| `damageCauserName` | string | |
| `item` | `Item` | The **destroyed armour piece** (helmet or vest). |
| `distance` | number | Centimetres. |

Observed 32 events.

### `LogHeal`

```json
{
  "character": {
    "name": "HDZedSlaya", "teamId": 24, "health": 45.644126892089844,
    "location": { "x": 541399.25, "y": 234579.109375, "z": 184.69000244140625 },
    "ranking": 0, "accountId": "account.cb48db6af5a3457ea534fbc8e5d606e3",
    "isInBlueZone": true, "isInRedZone": false, "zone": ["yasnayapolyana"]
  },
  "item": {
    "itemId": "",
    "stackCount": 1540649104,
    "category": "",
    "subCategory": "",
    "attachedItems": []
  },
  "healAmount": 2,
  "common": { "isGame": 2 },
  "_D": "2019-10-23T00:32:29.247Z",
  "_T": "LogHeal"
}
```

| Field | Type | Notes |
|---|---|---|
| `character` | `Character` | `health` is the value **before** the heal is applied. |
| `item` | `Item` | ⚠️ **Usually garbage — see below.** |
| `healAmount` | number | ⚠️ **`healAmount`, camelCase.** The official docs say `healamount` (all-lowercase `a`). **The docs are wrong.** |

> ⚠️ **`LogHeal.item` is almost always empty and contains uninitialised memory.**
> In the sample: **3,245 of 3,253** `LogHeal` events had `item.itemId === ""`, `category === ""`,
> `subCategory === ""` — and a **garbage `stackCount`** (e.g. `1540649104`). Only 8 events had a
> real `itemId` (`Item_Heal_MedKit_C`).
> **Never** display `LogHeal.item`, and never trust `stackCount` on this event. To know *what* the
> player used, correlate with the preceding `LogItemUse` event for the same `accountId`.

`LogHeal` fires **per healing tick**, not per item consumed — hence 3,253 events. Observed
`healAmount` values: `2` (1,435×), `0` (713×), `3` (517×), `15` (183×), `4` (147×), `1` (119×),
`5` (10×), plus fractional values. **`healAmount` of `0` occurs 713 times** — filter these out.

### `LogPlayerUseThrowable`

```json
{
  "attackId": 324,
  "fireWeaponStackCount": 4,
  "attacker": {
    "name": "Sh1sHH", "teamId": 18, "health": 62.53199768066406,
    "location": { "x": 506056.59375, "y": 554735.875, "z": 1047.169921875 },
    "ranking": 0, "accountId": "account.3a796212bb13494f8558e9f04365cf5a",
    "isInBlueZone": false, "isInRedZone": false, "zone": []
  },
  "attackType": "Weapon",
  "weapon": {
    "itemId": "Item_Weapon_Grenade_C",
    "stackCount": 1,
    "category": "Equipment",
    "subCategory": "Throwable",
    "attachedItems": []
  },
  "common": { "isGame": 3.5 },
  "_D": "2019-10-23T00:37:48.475Z",
  "_T": "LogPlayerUseThrowable"
}
```

| Field | Type | Notes |
|---|---|---|
| `attackId` | int | Shares the `LogPlayerAttack` id space: **all 97** throwable `attackId`s (range `200`–`420`) also appeared as a `LogPlayerAttack` `attackId`. Each throw emits **both** a `LogPlayerAttack` and a `LogPlayerUseThrowable` — de-duplicate by `attackId` or you will double-count shots. |
| `fireWeaponStackCount` | int | Throwables remaining. |
| `attacker` | `Character` | |
| `attackType` | string | Observed `"Weapon"`. |
| `weapon` | `Item` | `category` is `Equipment`, `subCategory` is `Throwable`. |

Observed 97 events. Note this event has **no `vehicle` field**, unlike `LogPlayerAttack`.

---

## 6. Supporting events (observed shapes)

These are not "core player events" but you will need them to build a replay.

### `LogMatchDefinition`

```json
{
  "MatchId": "match.bro.official.pc-2018-04.steam.squad-fpp.eu.2019.10.23.00.db8f8222-4300-4683-9483-db85602ff756",
  "PingQuality": "low",
  "SeasonState": "closed",
  "_D": "2019-10-23T00:18:48.7334511Z",
  "_T": "LogMatchDefinition"
}
```

⚠️ **Modern shape has only TWO fields — `SeasonState` is gone.** Modern key set is exactly
`['_T', 'MatchId', 'PingQuality', '_D']`. `SeasonState` is **2019-only**, and `PingQuality` is
marked `// Deprecated` in `telemetry-events.rst`.

> ⚠️ **The single most anomalous event in the whole format:**
> - Its fields are **PascalCase** (`MatchId`, `PingQuality`, and 2019-only `SeasonState`) while
>   every other event uses camelCase.
> - It is the **only event with no `common` object**.
> - Its `_D` has **7 fractional digits** instead of 3.
> - It is **first in the array** but its timestamp is **later** than the events that follow it.

### `LogMatchStart`

```json
{
  "mapName": "Baltic_Main",
  "weatherId": "Clear",
  "characters": [ { "name": "Sl4y3r__", "teamId": 15, "health": 100, "location": { "x": -11623.21875, "y": 800809.375, "z": 150088 }, "ranking": 0, "accountId": "account.16c7103a56b64806b491844ffc73b400", "isInBlueZone": false, "isInRedZone": false, "zone": [] }, "…97 more…" ],
  "cameraViewBehaviour": "FpsOnly",
  "teamSize": 4,
  "isCustomGame": false,
  "isEventMode": false,
  "blueZoneCustomOptions": "[]",
  "common": { "isGame": 0.10000000149011612 },
  "_D": "2019-10-23T00:18:48.728Z",
  "_T": "LogMatchStart"
}
```

| Field | Type | Notes |
|---|---|---|
| `mapName` | string | Internal name — see mapName table. |
| `weatherId` | string | Observed `"Clear"`. |
| `characters` | **`CharacterWrapper[]`** (modern) / `Character[]` (2019) | ⚠️ **Accept both shapes.** All four 2026 payloads use `CharacterWrapper`; the 2019 sample used plain `Character`. The `z` of `150088` is the aircraft altitude. |
| `cameraViewBehaviour` | string | Observed `"FpsOnly"` (i.e. FPP). |
| `teamSize` | int | `4` for squads. |
| `isCustomGame` | bool | |
| `isEventMode` | bool | |
| `blueZoneCustomOptions` | string | ⚠️ **A JSON-encoded string, not an object.** Observed literal `"[]"`. You must `JSON.parse` it a second time. Documented element fields: `phaseNum`, `startDelay`, `warningDuration`, `releaseDuration`, `poisonGasDamagePerSecond`, `radiusRate`, `spreadRatio`, `landRatio`, `circleAlgorithm`. |

**Use `LogMatchStart._D` as your replay t=0**, not `LogMatchDefinition._D`.

### `LogMatchEnd`

```json
{
  "characters": [ { "name": "Sl4y3r__", "teamId": 15, "health": 0, "location": { "x": 0, "y": 0, "z": 0 }, "ranking": 8, "accountId": "account.16c7103a56b64806b491844ffc73b400", "isInBlueZone": false, "isInRedZone": false, "zone": [] }, "…97 more…" ],
  "rewardDetail": [],
  "gameResultOnFinished": { "results": [ { "rank": 1, "gameResult": "", "teamId": 18, "stats": { "killCount": 5, "score": 517, "xp": 280, "distanceOnFoot": 4168.8037109375, "distanceOnSwim": 304.90435791015625, "distanceOnVehicle": 1301.11083984375, "distanceOnParachute": 362.0933837890625, "distanceOnFreefall": 1232.1220703125 }, "isBpGrinder": false, "isXpGrinder": false, "accountId": "account.3a796212bb13494f8558e9f04365cf5a" }, "…3 more, all rank 1, all teamId 18…" ] },
  "common": { "isGame": 7 },
  "_D": "2019-10-23T00:47:02.254Z",
  "_T": "LogMatchEnd"
}
```

| Field | Type | Notes |
|---|---|---|
| `characters` | **`CharacterWrapper[]`** (modern) / `Character[]` (2019) | **This is where `ranking` is finally populated.** ⚠️ On modern data read **`characters[].character.ranking`** (team rank, `1`–`27` observed) and `characters[].character.individualRanking` (`1`–`96`); reading `characters[].ranking` raises `KeyError`. In the 2019 sample the elements were plain `Character`s: 98 entries, `ranking` `1`–`29`, never `0`. **Accept both shapes.** |
| `allWeaponStats` | object | ⚠️ **Real, undocumented, modern — present on every modern `LogMatchEnd`, and arguably the single most valuable object in the file for a stats dashboard.** Per-account arrays of `{weapon, damage, dBNODamage, shots, hits, dBNOHits, holdingTime, hitDetails[{bodyPart, kills, dBNOs, hits}]}`. |
| `gameResultOnFinished` | object | `{ "results": [GameResult] }`. ⚠️ **Winning team only** — see below. |
| `rewardDetail` | array | ⚠️ **2019-ONLY.** Observed empty `[]` in the 2019 sample; the key is **absent entirely** from modern `LogMatchEnd`. |

**Modern `LogMatchEnd` key set is exactly:** `_T`, `characters`, `gameResultOnFinished`,
`allWeaponStats`, `common`, `_D`.

> ⚠️ **`gameResultOnFinished.results[]` contains only the winning team.** Observed **4** entries
> for a 98-player match, all with `rank: 1` and all `teamId: 18`. The official docs confirm this
> ("showing winning players only"). **Do not use it as a scoreboard.** For full placements you must
> use `LogMatchEnd.characters[].ranking`, which covers all 98 players.
>
> ⚠️ **`LogMatchEnd.characters[].location` is zeroed for the dead, but not for the living.**
> Observed: **95 of 98** characters had `{x:0,y:0,z:0}`; the 3 non-zero ones were surviving winners
> at their real final positions. So neither "always zero" nor "always real" is safe — check before plotting.
>
> ⚠️ `LogPlayerCreate` fired for **99** distinct `accountId`s but `LogMatchEnd.characters[]` had
> **98**, and `GameState.numStartPlayers` was `98`. Players can be created and then never start.
> Build your roster from `LogPlayerCreate` but reconcile against `LogMatchEnd`.

### `LogGameStatePeriodic`

```json
{
  "gameState": { "elapsedTime": 838, "numAliveTeams": 10, "numJoinPlayers": 95, "numStartPlayers": 98, "numAlivePlayers": 32, "safetyZonePosition": { "x": 508659.375, "y": 572304.625, "z": 0 }, "safetyZoneRadius": 202901.53125, "poisonGasWarningPosition": { "x": 516141.46875, "y": 600652.625, "z": 0 }, "poisonGasWarningRadius": 121740.921875, "redZonePosition": { "x": 251287.046875, "y": 300256.53125, "z": 0 }, "redZoneRadius": 50000 },
  "common": { "isGame": 2 },
  "_D": "2019-10-23T00:32:59.411Z",
  "_T": "LogGameStatePeriodic"
}
```

Observed 169 events at a **median 10.002 s** interval — the same cadence as `LogPlayerPosition`.
This is your circle-animation keyframe source; interpolate radius and centre between events.

### `LogPhaseChange`

```json
{ "phase": 4, "elapsedTime": 0, "common": { "isGame": 4 }, "_D": "2019-10-23T00:38:59.967Z", "_T": "LogPhaseChange" }
```

| Field | Type | Notes |
|---|---|---|
| `phase` | int | Observed `1`–`7`. |
| `elapsedTime` | number | ⚠️ Observed `0` — appears unpopulated on this event. Do not rely on it. |

Observed 13 events: phases 1–6 fired **twice each** (once for the warning, once for the shrink),
phase 7 once. `phase` is an integer; `common.isGame` carries the half-steps.

### Other observed events (full type inventory from the sample file)

| `_T` | Count | Top-level keys observed |
|---|---|---|
| `LogPlayerTakeDamage` | 8,666 | see above |
| `LogPlayerPosition` | 7,495 | see above |
| `LogPlayerAttack` | 4,996 | see above |
| `LogItemPickup` | 4,178 | `character`, `item` |
| `LogHeal` | 3,253 | see above |
| `LogObjectInteraction` | 1,347 | `character`, `objectType`, `objectTypeStatus`, `objectTypeAdditionalInfo`, `objectTypeCount` ⚠️ **`objectTypeCount` is 2019-only** — the modern shape (2,483 events) matches the official docs exactly and has no `objectTypeCount`. |
| `LogItemEquip` | 1,272 | `character`, `item` |
| `LogItemUnequip` | 1,272 | `character`, `item` |
| `LogItemDrop` | 964 | `character`, `item` |
| `LogItemAttach` | 943 | `character`, `parentItem`, `childItem` |
| `LogItemDetach` | 887 | `character`, `parentItem`, `childItem` |
| `LogItemPickupFromLootBox` | 583 | `character`, `item`, `ownerTeamId`, `creatorAccountId` |
| `LogVaultStart` | 547 | `character` ⚠️ **2019-only shape.** Modern (2,701 events): `character`, `isLedgeGrab` (documented), `isVaultOnVehicle` (**undocumented**). |
| `LogItemUse` | 422 | `character`, `item` |
| `LogWeaponFireCount` | 406 | `character`, `weaponId`, `fireCount` |
| `LogObjectDestroy` | 380 | `character`, `objectType`, `objectLocation` |
| `LogVehicleRide` | 341 | `character`, `vehicle`, `seatIndex`, `fellowPassengers` |
| `LogVehicleLeave` | 341 | `character`, `vehicle`, `rideDistance`, `seatIndex`, `maxSpeed`, `fellowPassengers` |
| `LogGameStatePeriodic` | 169 | `gameState` |
| `LogPlayerLogin` | 99 | `accountId` |
| `LogPlayerCreate` | 99 | `character` |
| `LogPlayerLogout` | 99 | `accountId` |
| `LogParachuteLanding` | 98 | `character`, `distance` |
| `LogPlayerUseThrowable` | 97 | see above |
| `LogPlayerKill` | 95 | see above |
| `LogPlayerMakeGroggy` | 81 | see above |
| `LogArmorDestroy` | 32 | see above |
| `LogItemPickupFromCarepackage` | 27 | `character`, `item`, `carePackageUniqueId` |
| `LogSwimStart` | 20 | `character` |
| `LogPlayerRevive` | 16 | see above |
| `LogSwimEnd` | 15 | `character`, `swimDistance`, `maxSwimDepthOfWater` |
| `LogPhaseChange` | 13 | `phase`, `elapsedTime` |
| `LogWheelDestroy` | 13 | `attackId`, `attacker`, `vehicle`, `damageTypeCategory`, `damageCauserName` |
| `LogCarePackageLand` | 5 | `itemPackage` |
| `LogCarePackageSpawn` | 4 | `itemPackage` |
| `LogRedZoneEnded` | 3 | `drivers` |
| `LogVehicleDestroy` | 3 | `attackId`, `attacker`, `vehicle`, `damageTypeCategory`, `damageCauserName`, `distance` |
| `LogMatchDefinition` | 1 | see above |
| `LogMatchStart` | 1 | see above |
| `LogMatchEnd` | 1 | see above |

> ⚠️ **`LogItemPickupFromLootBox` — capital `B`.** The official docs spell this
> `LogItemPickupFromLootbox` (lowercase `b`). The real payload uses `LogItemPickupFromLootBox`.
> Match this event type case-insensitively or you will silently drop 583 events per match.

Documented event types **not** present in the 2019 sample (newer or mode-specific): `LogBlackZoneEnded`,
`LogCharacterCarry`, `LogEmPickupLiftOff`, `LogItemPickupFromCustomPackage`, `LogItemPickupFromVehicleTrunk`,
`LogItemPutToVehicleTrunk`, `LogPlayerDestroyBreachableWall`, `LogPlayerDestroyProp`, `LogPlayerKillV2`,
`LogPlayerRedeploy`, `LogPlayerRedeployBRStart`, `LogPlayerUseFlareGun`, **`LogVehicleDamage`**
(documented in `telemetry-events.rst`, added in changelog v20.2.0, present in modern payloads).

⚠️ **Fully undocumented modern event type: `LogSpecialZoneInCharacters`** — 231 events in the
modern payloads, keys `zoneInfo`, `charactersInZone`. It appears in **neither** the official event
catalogue nor any third-party wrapper found. Do not let an exhaustive `_T` switch throw on it.

> ⚠️ **`LogItemPickupFromLootBox` (capital `B`) is confirmed in all four modern payloads**, not
> just the 2019 sample. The docs' lowercase-`b` spelling is wrong in both eras.

---

## 7. Enum reference

### `damageTypeCategory`

Observed in the sample (9 distinct, with counts):

| Value | Count |
|---|---|
| `Damage_BlueZone` | 6,820 |
| `Damage_Groggy` | 1,025 |
| `Damage_Gun` | 897 |
| `Damage_Instant_Fall` | 35 |
| `Damage_Explosion_Grenade` | 34 |
| `Damage_Molotov` | 33 |
| `Damage_VehicleCrashHit` | 23 |
| `Damage_Punch` | 16 |
| `Damage_Explosion_Vehicle` | 7 |

Full official set (43 values) from `dictionaries/telemetry/damageTypeCategory.json`:

| Value | Display name |
|---|---|
| `Damage_Blizzard` | Blizzard Damage |
| `Damage_BlueZone` | Bluezone Damage |
| `Damage_BlueZoneGrenade` | Bluezone Grenade Damage |
| `Damage_DronePackage` | Drone Damage |
| `Damage_Drown` | Drowning Damage |
| `Damage_Explosion_Aircraft` | Aircraft Explosion Damage |
| `Damage_Explosion_BlackZone` | Blackzone Damage |
| `Damage_Explosion_Breach` | Breach Explosion Damage |
| `Damage_Explosion_C4` | C4 Explosion Damage |
| `Damage_Explosion_GasPump` | Gas Pump Explosion |
| `Damage_Explosion_Grenade` | Grenade Explosion Damage |
| `Damage_Explosion_JerryCan` | Jerrycan Explosion Damage |
| `Damage_Explosion_LootTruck` | Loot Truck Explosion Damage |
| `Damage_Explosion_Mortar` | Mortar Explosion |
| `Damage_Explosion_PanzerFaustBackBlast` | Panzerfaust Backblast Damage |
| `Damage_Explosion_PanzerFaustWarhead` | Panzerfaust Explosion Damage |
| `Damage_Explosion_PanzerFaustWarheadVehicleArmorPenetration` | Panzerfaust Explosion Damage |
| `Damage_Explosion_PropaneTank` | Propane Tank |
| `Damage_Explosion_RedZone` | Redzone Explosion Damage |
| `Damage_Explosion_StickyBomb` | Sticky Bomb Explosion Damage |
| `Damage_Explosion_Vehicle` | Vehicle Explosion Damage |
| `Damage_Groggy` | Bleed out damage |
| `Damage_Gun` | Gun Damage |
| `Damage_Gun_Penetrate_BRDM` | BRDM |
| `Damage_HelicopterHit` | Pillar Scout Helicopter Damage |
| `Damage_Instant_Fall` | Fall Damage |
| `Damage_KillTruckHit` | Kill Truck Hit |
| `Damage_KillTruckTurret` | Kill Truck Turret Damage |
| `Damage_Lava` | Lava Damage |
| `Damage_LootTruckHit` | Loot Truck Damage |
| `Damage_Melee` | Melee Damage |
| `Damage_MeleeThrow` | Melee Throw Damage |
| `Damage_Molotov` | Molotov Damage |
| `Damage_Monster` | Monster Damage |
| `Damage_MotorGlider` | Motor Glider Damage |
| `Damage_None` | No Damage |
| `Damage_Punch` | Punch Damage |
| `Damage_SandStorm` | Sandstorm Damage |
| `Damage_ShipHit` | Ferry Damage |
| `Damage_TrainHit` | Train Damage |
| `Damage_VehicleCrashHit` | Vehicle Crash Damage |
| `Damage_VehicleHit` | Vehicle Damage |
| `SpikeTrap` | Spike Trap damage |

⚠️ Note `SpikeTrap` breaks the `Damage_` prefix convention. Do not assume all values start with `Damage_`.

### `damageReason`

There is **no official dictionary file** for `damageReason` (confirmed: the `dictionaries/telemetry/`
directory contains only `damageCauserName.json`, `damageTypeCategory.json`, `mapName.json`, plus
`item/` and `vehicle/` subdirectories). Values observed in the sample:

| Value | Count | Meaning |
|---|---|---|
| `NonSpecific` | 6,952 | Environmental / no hit location (blue zone, fall, explosion) |
| `None` | 1,025 | Paired with `Damage_Groggy` (bleed-out ticks) |
| `TorsoShot` | 455 | |
| `HeadShot` | 171 | |
| `LegShot` | 116 | |
| `ArmShot` | 89 | |
| `PelvisShot` | 66 | |

⚠️ Both `NonSpecific` **and** `None` exist and mean different things. Headshot-rate calculations
must filter to `damageTypeCategory === "Damage_Gun"` first, otherwise blue-zone ticks pollute the denominator.

### `attackType`

| Value | Count observed | Where |
|---|---|---|
| `Weapon` | 4,995 | `LogPlayerAttack` |
| `RedZone` | 1 | `LogPlayerAttack` |
| `Weapon` | 97 | `LogPlayerUseThrowable` |

(The previously stated single figure of 5,092 was the aggregate across both event types.)

⚠️ Only two values appeared in one match; more certainly exist. Treat as an open string.

### `objectType` (`LogObjectInteraction` / `LogObjectDestroy`)

| Value | Count |
|---|---|
| `Door` | 1,361 |
| `Window` | 247 |
| `Fence` | 118 |
| `Jerrycan` | 1 |

### `mapName` → display name

From `dictionaries/telemetry/mapName.json`:

| `mapName` | Display name |
|---|---|
| `Baltic_Main` | Erangel (Remastered) |
| `Chimera_Main` | Paramo |
| `Desert_Main` | Miramar |
| `DihorOtok_Main` | Vikendi |
| `Erangel_Main` | Erangel |
| `Heaven_Main` | Haven |
| `Kiki_Main` | Deston |
| `Neon_Main` | Rondo |
| `Range_Main` | Camp Jackal |
| `Savage_Main` | Sanhok |
| `Summerland_Main` | Karakin |
| `Tiger_Main` | Taego |

⚠️ **`Baltic_Main` is Erangel**, not "Baltic". Both `Baltic_Main` and `Erangel_Main` map to Erangel —
you must handle both keys or modern matches will show an unknown map.

### `damageCauserName`

**209 entries** in `dictionaries/telemetry/damageCauserName.json` (209 unique keys, no duplicates,
7,497 bytes — counted from the raw file). Mixed naming conventions in one file:
`BP_*_C` (vehicles/props), `Weap*_C` (weapons), `Player*_C` (melee/punch), `AIPawn_*_C`.
Fetch and embed the dictionary at build time rather than hardcoding.

⚠️ Values arriving in `victimWeapon` may carry a trailing numeric suffix (`WeapSCAR-L_C_12`) that is
**not** in the dictionary. Strip `_\d+$` before lookup.

---

## 8. Implementation notes

### Casing traps — the complete list

| Trap | Correct form | Wrong form you'll instinctively write |
|---|---|---|
| Telemetry asset attribute | `URL` | `url` |
| Timestamp | `_D` | `_d`, `D`, `timestamp` |
| Type discriminator | `_T` | `_t`, `T`, `type` |
| Vehicle fuel | `feulPercent` | `fuelPercent` |
| Heal amount | `healAmount` | `healamount` (**what the official docs say**) |
| Knock id | `dBNOId` | `dbnoId`, `DBNOId`, `dBNOID` |
| Knocker | `dBNOMaker` | `dbnoMaker`, `DBNOMaker` |
| Knock damage | `dBNODamageInfo` | `dBNOdamageInfo` |
| Finish damage | `finishDamageInfo` | `finisherDamageInfo` |
| Kill assists | `assists_AccountId` | `assistsAccountId`, `assists_accountId` |
| Team kills | `teamKillers_AccountId` | `teamKillersAccountId` |
| Match definition fields | `MatchId`, `PingQuality` (+ 2019-only `SeasonState`) | `matchId`, `pingQuality`, `seasonState` |
| Loot box pickup | `LogItemPickupFromLootBox` | `LogItemPickupFromLootbox` (**what the docs say**) |
| Care package pickup | `LogItemPickupFromCarepackage` | `LogItemPickupFromCarePackage` |
| Victim weapon | `victimWeapon` — **lowercase, confirmed on 2019 *and* modern PC payloads, on `LogPlayerKill`, `LogPlayerKillV2` *and* `LogPlayerMakeGroggy`** | `VictimWeapon` (**what the docs say for MakeGroggy — simply wrong**) |

**Recommended defence:** normalise every key to lowercase at parse time and look fields up
case-insensitively. The `chicken_dinner` Python library does exactly this and documents the reason:
*"The key casing in responses are different between PC and XBox platforms."* The official changelog
corroborates: **v1.1.0** \[Xbox\] — *"keys in the telemetry data are now lowercase."* (Not v1.1.1,
which contains only two unrelated bug fixes.) If you support
console shards at all, case-insensitive access is **mandatory**, not optional.

### Things that will silently break a parser

1. **`isGame === 0.1` is never true.** The value is `0.10000000149011612`.
2. **`_D` has 7 fractional digits on `LogMatchDefinition`.** Python's `%f` accepts at most 6 and will
   raise. Use a tolerant ISO-8601 parser.
3. **`LogMatchDefinition` has no `common` key.** `event.common.isGame` throws on it.
4. **`attacker` is `null`** on `LogPlayerTakeDamage` for environmental damage (6,820 / 8,666 events).
   `vehicle` is `null` on `LogPlayerPosition` and `LogPlayerAttack`. These are explicit JSON `null`s,
   not missing keys — an "is the key present" check will not save you.
5. **`attackId` is `-1`**, not `0` and not absent, for environmental damage.
6. **`LogHeal.item` is uninitialised garbage** in ~99.75% of events, including a nonsense
   `stackCount` in the hundreds of millions.
7. **The array is not strictly time-sorted**, and `LogMatchDefinition` is deliberately out of order.
8. **The last array element is not `LogMatchEnd`.**
9. **`blueZoneCustomOptions` is a JSON string requiring a second parse**, not an object.
10. **`character.ranking` is *mostly* `0` before match end — but not always.** It becomes non-zero
    once a player's placement is locked in (after death) and shows up non-zero on ordinary
    mid-match events (998 such occurrences in the 2019 sample). Never use a non-zero `ranking`
    mid-match as a signal, and never assume zero.
10b. **`LogMatchStart`/`LogMatchEnd` `characters[]` elements are `CharacterWrapper`s in modern
    matches.** `characters[].ranking` raises `KeyError`; use `characters[].character.ranking`.
10c. **`Vehicle.vehicleUniqueId` and `Vehicle.rotationPitch` no longer exist** (removed by
    v17.0.0). Reading them returns `undefined` silently — there is no per-instance vehicle id.
10d. **`victimVehicle` / `killerVehicle` on `LogPlayerKillV2` are zeroed sentinel objects, not
    `null`, when the player was on foot.** Test `vehicleType !== ""`.
11. **`gameResult` is an empty string** even for the winner. Use `rank`.
12. **`LogMatchEnd.characters[].location` is `{0,0,0}` for dead players but real for survivors**
    (95 of 98 zeroed in the sample).
13. **`LogMatchEnd.gameResultOnFinished.results[]` holds the winning team only** (4 of 98 players).
    Using it as a scoreboard silently drops 96% of the lobby.
14. **Distances are centimetres.** A `distance` of `856` is 8.56 m. Kill-distance leaderboards divide by 100.
15. **Every throwable emits both `LogPlayerAttack` and `LogPlayerUseThrowable`** with the same
    `attackId` — naive shot counting double-counts grenades.
16. **All-caps `URL`** in the match asset attributes.
17. **Telemetry files are eventually purged** — never construct or cache-construct a CDN URL;
    always use the asset's `URL` attribute verbatim. (Earlier drafts claimed "403 means expired";
    that inference is withdrawn — see §1.)
18. **A sentinel `Character` with `teamId: 0` and empty `name`/`accountId`** appears on
    `attackType: "RedZone"` attacks and will break a roster join keyed on `accountId`.

### Recommended parse strategy for a replay dashboard

1. Stream or `JSON.parse` the whole array (≈20 MB, acceptable).
2. First pass: build `accountId → {name, teamId}` from `LogPlayerCreate`, and read
   `LogMatchStart` for `mapName` / `teamSize` / `_D` (t=0).
3. Second pass: bucket events by `_T`.
4. Build the position track from `LogPlayerPosition` (10 s cadence) and enrich with the `Character`
   snapshots embedded in `LogPlayerAttack` / `LogPlayerTakeDamage` / `LogPlayerMakeGroggy` /
   `LogPlayerKillV2` for sub-10 s fidelity around fights.
5. Build the circle track from `LogGameStatePeriodic` (10 s cadence); interpolate
   `safetyZone*` and `poisonGasWarning*`.
6. Build the kill feed from `LogPlayerKillV2` (falling back to `LogPlayerKill` for old matches),
   joining `dBNOId` back to `LogPlayerMakeGroggy` for "knocked by / finished by" attribution.
7. Compute per-player damage from `LogPlayerTakeDamage` **filtered to `attacker !== null`**.
8. Take final placements from `LogMatchEnd.characters[]` (all players), **unwrapping the
   `CharacterWrapper` first**:

   ```js
   const el = matchEnd.characters[i];
   const ch = el.character ?? el;          // modern: wrapper; 2019: plain Character
   const teamRank = ch.ranking;            // 1..27 observed
   const soloRank = ch.individualRanking;  // 1..96 observed (modern only)
   ```

   Running `characters[i].ranking` directly on modern data raises `KeyError: 'ranking'`.
   Use `LogMatchEnd.gameResultOnFinished.results[]` only for the winning team.
9. Pull per-weapon accuracy/damage from **`LogMatchEnd.allWeaponStats`** (modern only) rather than
   re-deriving it from `LogPlayerAttack` / `LogPlayerTakeDamage`.

### Version-gating cheat sheet

| Field / event | Introduced | Implication |
|---|---|---|
| `Character.isInBlueZone` / `isInRedZone` / `zone` | **v7.8.0 (PC)**, v9.0.0 (PS4/Xbox) | Present in the 2019 PC sample. |
| `LogHeal`, `LogParachuteLanding`, `LogItemPickupFromCarepackage`, `LogPlayerRevive.dBNOId` | **v7.8.0 (PC)**, v9.0.0 (PS4/Xbox) | Present in the sample. ⚠️ v9.0.0 is the **console-only** rollout; this doc targets PC, where these landed at v7.8.0. |
| `LogPlayerKill.VictimWeapon` / `LogPlayerMakeGroggy.VictimWeapon` | **v14.0.0 (PC)**, **v14.1.0 (PS4/Xbox)** | Present in the sample (as lowercase `victimWeapon`). Platforms were previously listed inverted here. |
| `Vehicle.rotationPitch` | added v14.2.0 (PC) / v15.1.0 (PS4, Xbox); **removed v17.0.0** | 2019-only. **Absent from modern payloads.** |
| `LogPhaseChange`, `LogPlayerUseThrowable` | v15.2.0 (PC), v15.3.0 (console) | Present in the sample. |
| `GameState.blackZonePosition` / `blackZoneRadius`, `LogBlackZoneEnded`, `*.isThroughPenetrableWall` | **v16.1.0 (PC)**, v16.2.0 (PS4/Xbox) | **Absent** from the 2019 sample; **present in modern payloads.** |
| `Vehicle.vehicleUniqueId` | **removed by v17.x** | 2019-only; absent from modern payloads and from the official `Vehicle` docs. No replacement. |
| `Vehicle.velocity` / `altitudeAbs` / `altitudeRel` / `isEngineOn` | v17.2.0 | **Absent** from the sample; **present in modern payloads.** |
| `LogVehicleDamage` | v20.2.0 | Absent from the sample; present in modern payloads. |
| `LogPlayerKillV2` | v20.3.0 | Absent from the sample; **confirmed in modern payloads (422 events).** |
| `LogPlayerKillV2.assists_AccountId` / `teamKillers_AccountId` | v20.5.0 | |
| `LogPlayerKill` (V1) | **removed** v21.0.0 — **except tournament matches** | Modern non-tournament matches have V2 only; historical **and tournament** matches keep V1. |
| `LogMatchDefinition.SeasonState` | **removed** (absent from modern payloads) | 2019-only. `PingQuality` is documented as deprecated. |
| `Stats.score` / `Stats.xp` / `GameResult.isBpGrinder` / `isXpGrinder` / `LogMatchEnd.rewardDetail` | **removed** (absent from modern payloads) | 2019-only. Modern equivalents: `GameResult.isRewardAbuse`, `Stats.bpRewardDetail` / `arcadeRewardDetail` / `statTrakDataPairs` / `headshotStatTrakDataPairs`. |
| `LogObjectInteraction.objectTypeCount` | **removed** (absent from modern payloads) | 2019-only. |

---

## ⚠️ Unverified / needs live confirmation

Everything below could **not** be confirmed. Items 1–8 of an earlier draft have been **resolved**
against four modern (2026-05-03) PC payloads and moved out — see the resolved list at the end.

1. **Full enum domains** for `attackType`, `damageReason`, `weatherId`, `cameraViewBehaviour`,
   `objectType`, `objectTypeStatus`, `gameResult`, `PingQuality`, `SeasonState`. Only the values
   present in one squad-FPP Erangel match were observed; no official dictionary exists for any of them.
2. **Event ordering guarantees are empirical, not contractual.** PUBG publishes no ordering
   guarantee. The 2-violation-in-39,283 result is from a single match.
3. **Per-match event counts vary by mode.** All 2019 counts here are from one 99-player
   squad-FPP match. Solo/duo/smaller maps will differ substantially.
4. **Element shapes of the modern undocumented reward/stat-trak structures** —
   `Stats.bpRewardDetail`, `arcadeRewardDetail`, `statTrakDataPairs`, `headshotStatTrakDataPairs`,
   and `GameResult.isRewardAbuse` semantics. Observed as keys only; populated element shapes not
   characterised. *Confirmation: dump a modern match where the account earned rewards and inspect.*
   (The 2019-only `LogMatchEnd.rewardDetail` was always `[]`; its populated shape will now never be
   observable, since the key no longer exists.)
5. **`Vehicle.rotationPitch` units** (degrees vs radians) — never determined, and now unresolvable
   from live data since the field was removed in v17.0.0. Relevant only for archival 2019 matches.
6. **Semantics of the modern undocumented fields** `Character.inSpecialZone` / `type`,
   `LogVaultStart.isVaultOnVehicle`, `GameState.numStartTeams` vs `numParticipatedTeams`, and
   `LogSpecialZoneInCharacters.zoneInfo`. Key names and presence are confirmed; **meanings are
   inferred from the names only.** *Confirmation: correlate against a match with a known special
   zone / known team-count churn.*
7. **Telemetry retention window.** Not documented anywhere found, and the 403s previously cited as
   evidence turned out to be on URLs that were never live (see §1). *Confirmation: record the
   `URL` of a fresh match and re-fetch it on a schedule until it starts failing.*
8. **Whether `common` carries `matchId` / `mapName` on console shards.** Confirmed absent on PC in
   both eras; the Go wrappers that model them may be reflecting Xbox/PS4 payloads.
   *Confirmation: fetch one console-shard telemetry file.*
9. **Casing on console shards generally.** Changelog v1.1.0 \[Xbox\] says Xbox keys were lowercased;
   no console payload was ever inspected here. *Confirmation: as above.* Keep case-insensitive
   access mandatory until then.

### ✅ Resolved by the modern (2026) payloads

Previously listed as unverified; now confirmed and folded into the body of this document:

| Was unverified | Resolution |
|---|---|
| `LogPlayerKillV2` never observed | **Confirmed real** — 422 events across 4 matches. |
| `victimWeapon` vs `VictimWeapon` casing | **Lowercase** on modern `LogPlayerKillV2` *and* `LogPlayerMakeGroggy`. The docs' PascalCase is wrong on both. |
| Does `common` carry `matchId` / `mapName`? | **No** — modern PC `common` carries only `isGame`. (Console still open, see #8 above.) |
| Gzipped file size | **Measured**: 2019 sample 1,691,484 B = 1.61 MiB (11.9×); modern 2.38–2.73 MiB. |
| `CharacterWrapper` never observed | **Confirmed present** in both `LogMatchStart` and `LogMatchEnd` on all 4 modern payloads. |
| `isThroughPenetrableWall` introduction version | **v16.1.0 \[PC\] / v16.2.0 \[PS4, Xbox\]**; present on all modern damage/groggy events. |
| `DamageInfo` never observed | **Confirmed** (1,266 instances) with `additionalInfo` and `isThroughPenetrableWall` exactly as documented. |
| `LogItemPickupFromLootBox` capital `B` in modern payloads | **Confirmed** capital `B` in all 4 modern payloads. |
