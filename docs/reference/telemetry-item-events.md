# PUBG Telemetry — Item / Inventory Events (ground truth)

**Purpose:** everything needed to build an inventory state machine that can answer
"what was player X carrying at timestamp T?" from a PUBG match telemetry file.

**Status of this document:** every field name below was verified against **real telemetry
payloads**, not just the official docs. Where the official docs disagree with reality, the
docs are wrong and this document says so explicitly. Anything that could not be confirmed
is tagged `⚠️ UNVERIFIED` and repeated in the final section.

**Evidence base**

| Sample | What | Events | Notes |
|---|---|---|---|
| `7236f71d-5a53-11e8-...-telemetry.json` | Real Erangel duo-fpp match, 2018-05-18 | 23,433 | `_V: 2` era. Used for historical casing comparison. |
| 4 × `steam_*_telemetry.json.gz` | Real Erangel squad matches, **2026-05-03** | 218,917 | Current schema. All schema claims below come from these unless stated. |

> **Scope of figures.** Most counts below are corpus-wide over all four matches, but some
> are **single-match** and are labelled inline where they appear (§7.1's `4 / 1285`, §7.2's
> whole death-timing table, §9.2's `1378 : 0`). Two of those do **not** generalise to the
> other three matches — see the ⚠️ notes in §9.2 and §3.11. Per-match totals for reference:
> `LogItemAttach` 1471/1377/1301/1313 (5462 total), `LogItemDrop` 1285/1216/2472/1262
> (6235 total), Equip→Pickup 1378/1267/2586/1255.

---

## Sources

Fetched and read in full:

- https://documentation.pubg.com/en/telemetry-events.html
- https://documentation.pubg.com/en/telemetry-objects.html
- https://documentation.pubg.com/en/telemetry.html
- https://raw.githubusercontent.com/pubg/api-documentation-content/master/rst/telemetry-events.rst (reStructuredText source of the events page)
- https://raw.githubusercontent.com/pubg/api-documentation-content/master/rst/telemetry-objects.rst (source of the objects page)
- https://raw.githubusercontent.com/pubg/api-documentation-content/master/rst/telemetry.rst
- https://api.github.com/repos/pubg/api-assets/git/trees/master?recursive=1 (full authoritative file listing of `pubg/api-assets`)
- https://raw.githubusercontent.com/pubg/api-assets/master/README.md
- https://raw.githubusercontent.com/pubg/api-assets/master/dictionaries/telemetry/item/itemId.json
- https://raw.githubusercontent.com/pubg/api-assets/master/enums/telemetry/item/category.json
- https://raw.githubusercontent.com/pubg/api-assets/master/enums/telemetry/item/subCategory.json
- https://raw.githubusercontent.com/pubg/api-assets/master/enums/telemetry/carryState.json
- https://raw.githubusercontent.com/pubg/api-assets/master/enums/telemetry/objectType.json
- https://raw.githubusercontent.com/pubg/api-assets/master/enums/telemetry/objectTypeStatus.json
- https://raw.githubusercontent.com/pubg/api-assets/master/enums/telemetry/attackType.json
- https://raw.githubusercontent.com/ramonsaraiva/pubg-python/master/pubg_python/domain/telemetry/events.py
- https://raw.githubusercontent.com/ramonsaraiva/pubg-python/master/pubg_python/domain/telemetry/objects.py
- https://raw.githubusercontent.com/NovikovRoman/pubg/master/telemetry_events.go
- https://raw.githubusercontent.com/martinsileno/pubg-typescript-api/master/src/interfaces/telemetry.ts
- https://raw.githubusercontent.com/martinsileno/pubg-typescript-api/master/src/entities/telemetry/objects/item.ts
- https://raw.githubusercontent.com/pubgsh/client/master/src/models/Telemetry.parser.js (pubg.sh replay state machine)
- https://raw.githubusercontent.com/pubgsh/client/master/util/7236f71d-5a53-11e8-b364-0a58647f9b0f-telemetry.json (**real 2018 telemetry**)
- https://github.com/denyschepelyuk/PUBG_Erangel_telemetry — `data/raw/steam_*_telemetry.json.gz` (**real 2026 telemetry**, ~180 matches)
- https://gist.github.com/nikicat/b4922c2cdc86e91c3af7b7667640d67d (field dump from real 2018 telemetry)
- https://chicken-dinner.readthedocs.io/en/latest/models/telemetry.html

---

## 0. Read this first — the six things that will silently break your parser

| # | Trap | Reality |
|---|---|---|
| 1 | Event name casing | It is **`LogItemPickupFromLootBox`** — capital **B**. The official docs say `LogItemPickupFromLootbox`, which appears **0 times** in 219k real events. |
| 2 | Duplicate pickups | **100 %** of `LogItemPickupFromLootBox` (1976/1976) and `LogItemPickupFromCarepackage` (177/177) events are *also* emitted as a plain `LogItemPickup` **within 50 ms** (§9.3). It is *not* the same millisecond: exact `_D` equality only matches 1550/1976 LootBox, 140/177 Carepackage, 45/65 VehicleTrunk. **Never de-duplicate on timestamp equality** — you would double-count ~22 %. Summing both double-counts. |
| 3 | `subCategory` for backpacks | Real data says **`"BackPack"`** (capital P). The official `enums/telemetry/item/subCategory.json` says `"Backpack"`. The 2018 data said `"Backpack"`; **the casing changed**. Never string-compare without normalising. |
| 4 | Equip precedes pickup | For auto-equipped loot, `LogItemEquip` is usually emitted **before** `LogItemPickup` (per-match Equip→Pickup 1378 / 1267 / 2586 / 1255). It is **not** guaranteed: one of the four matches also has 44 Pickup→Equip pairs. Do not assume you own an item before you can equip it — tolerate either order. |
| 5 | Death | `LogItemDrop` **does not** fire on death. The victim emits a burst of `LogItemDetach` within 1 s, then `LogItemUnequip` for every equipped item **exactly ~60 s later**. |
| 6 | `LogHeal.healAmount` | Real data: `healAmount` (camelCase). Official docs: `healamount`. The docs are wrong. |

---

## 1. Event envelope

Every telemetry event is an object in a top-level JSON array. Envelope fields
(present on every event, omitted from the per-event tables below):

```json
{
  "_T": "LogItemPickup",
  "_D": "2026-05-03T04:21:24.216Z",
  "common": { "isGame": 0.10000000149011612 }
}
```

| Field | Type | Meaning |
|---|---|---|
| `_T` | string | Event type. **Exact, case-sensitive.** |
| `_D` | string | ISO-8601 UTC timestamp. Precision varies (see §9.1). |
| `common` | object | See below. |

### `common`

| Field | Type | Present | Meaning |
|---|---|---|---|
| `isGame` | number | always | Match phase. `0` pre-liftoff, `0.1` on plane, `0.5` no zone yet, `1.0` first safe/blue zone, `1.5` first shrink, `2.0` second zone, … |

**Field drift:** in 2018 telemetry `common` also carried `mapName` and `matchId`
(23,432/23,433 events). In 2026 telemetry `common` contains **only `isGame`**
(218,913/218,917 objects). Get `mapName` from `LogMatchStart` and the match ID from the
API, not from `common`.

**`_V` / `_U`:** the 2018 file has `"_V": 2` on every event. The 2026 files have
**no `_V` and no `_U` at all**. Treat both as optional; do not key off them.

---

## 2. The `Item` object

This is the single most important shape. It is embedded as `item`, `weapon`,
`parentItem`, `childItem`, and inside `itemPackage.items[]`.

```json
{
  "itemId": "Item_Weapon_AK47_C",
  "stackCount": 1,
  "category": "Weapon",
  "subCategory": "Main",
  "attachedItems": [
    "Item_Attach_Weapon_Upper_Holosight_C",
    "Item_Attach_Weapon_Magazine_ExtendedQuickDraw_Large_C"
  ]
}
```

| Field | Type | Meaning |
|---|---|---|
| `itemId` | string | Unreal class name, e.g. `Item_Weapon_AK47_C`. Key into the itemId dictionary (§6). May be `""` — see below. |
| `stackCount` | int | **Quantity involved in this event**, not the total held. Semantics vary per event — see §5. Can be `0`. |
| `category` | string | See §4.1. May be `""`. |
| `subCategory` | string | See §4.2. May be `""`. |
| `attachedItems` | string[] | Array of **itemId strings** (not Item objects). Non-empty only for `Weapon/Main` and `Weapon/Handgun`. |

**Verified exhaustively:** across **137,337** item objects in the 2026 samples, the key set
is *exactly* these five. Every single one had all five.

> ⚠️ **There is no `ownerTeamId` on the `Item` object.** `ownerTeamId` is a **top-level
> field on `LogItemPickupFromLootBox` only** (1976/1976 of those events; nowhere else).
> Confirmed by the official `telemetry-objects.rst` Item schema, which lists exactly five
> fields, and by 137k real item objects carrying exactly that key set.
> (An earlier revision claimed three client libraries "agree". They do not: `pubg-python`,
> `pubg-typescript-api` and `NovikovRoman/pubg` contain **zero** references to
> `ownerTeamId` / `owner_team_id` — they simply do not model the field, which is not
> evidence either way. The separate §3.2 claim about capital-B `LogItemPickupFromLootBox`
> in `pubg-python` / `NovikovRoman/pubg` **is** confirmed and stands.)

**Empty-item sentinel.** `LogHeal` frequently carries a fully-blank item
(`{"itemId":"","stackCount":0,"category":"","subCategory":"","attachedItems":[]}`) —
17,445 of 21,563 `LogHeal` events. `LogPlayerAttack.weapon` is also blank for melee/fists.
Your parser must not crash on `itemId === ""` and must not create an inventory entry for it.

### `ItemPackage` (care packages)

```json
{
  "itemPackageId": "Carapackage_RedBox_C",
  "location": { "x": 272041.46875, "y": 563085.75, "z": 1872.6552734375 },
  "items": [ { …Item… }, … ]
}
```

Observed `itemPackageId` values (note the misspelling "Carapackage" — it is in the data):
`Carapackage_SmallPackage_C`, `Carapackage_RedBox_C`, `Carapackage_FlareGun_C`,
`Carapackage_SmallPackage_NoParachute_C`, `BP_BRDM_C`.

### `Character` (as embedded in item events)

Docs list 9 fields. **Real 2026 data has 14** — the extra ones are undocumented but
present on 100 % of 137,468 character objects.

```json
{
  "name": "sounddevice",
  "teamId": 1,
  "health": 100,
  "location": { "x": -73178.9375, "y": 726425.5, "z": 150208 },
  "ranking": 0,
  "individualRanking": 0,
  "accountId": "account.aaac9fb7f08347fdba1727035954e340",
  "isInBlueZone": false,
  "isInRedZone": false,
  "inSpecialZone": "None",
  "isInVehicle": true,
  "zone": [],
  "type": "user",
  "isDBNO": false
}
```

| Field | Type | Documented? | Notes |
|---|---|---|---|
| `name` | string | yes | Display name. **Not** a stable key — use `accountId`. |
| `teamId` | int | yes | |
| `health` | number | yes | |
| `location` | Location | yes | cm, origin top-left of map |
| `ranking` | int | yes | Team placement |
| `individualRanking` | int | **no** | |
| `accountId` | string | yes | `account.<32 hex>`. The stable identity key. |
| `isInBlueZone` / `isInRedZone` | bool | yes | |
| `inSpecialZone` | string | **no** | Observed: `None`, `RedZone`, `EMP`, `SandStorm` |
| `isInVehicle` | bool | **no** | |
| `zone` | string[] | yes | Named POI regions, e.g. `["school"]` |
| `type` | string | **no** | Observed: `user`, **`user_ai`** (bots — 1388 of 137,468) |
| `isDBNO` | bool | **no** | Knocked-down state at event time |

### `Vehicle` (as embedded in trunk events)

```json
{
  "vehicleType": "WheeledVehicle",
  "vehicleId": "Dacia_A_03_v2_Esports_C",
  "seatIndex": -1,
  "healthPercent": 100,
  "feulPercent": 100,
  "altitudeAbs": 0,
  "altitudeRel": 0,
  "velocity": 0,
  "isWheelsInAir": false,
  "isInWaterVolume": false,
  "isEngineOn": false,
  "location": { "x": 316684.03125, "y": 659586.0625, "z": 2669.20361328125 }
}
```

- `feulPercent` — **yes, that typo is real and is in the data.** Not `fuelPercent`.
- `location` is present on the vehicle object but is **not documented**.
- `vehicleUniqueId` (documented) was **absent** on all 200 trunk-event vehicle objects
  in the samples. You cannot use it to key a trunk. See §7.3.
- `seatIndex` on trunk events is `-1` in only **74 / 200** samples; the other 126 carry seat
  values `0`–`3` (the player was seated in the vehicle while accessing the trunk).
  Breakdown: `LogItemPickupFromVehicleTrunk` (n=65) `{3:16, 0:15, 1:13, -1:11, 2:10}`;
  `LogItemPutToVehicleTrunk` (n=135) `{-1:63, 2:22, 1:18, 0:17, 3:15}`.
  **Never use `seatIndex == -1` as a trunk-event discriminator** — it would drop 83 % of
  trunk pickups. It only reflects whether the character happened to be seated.

---

## 3. Event catalogue

All 12 item events, with a real trimmed payload for each. `character` and `common` are
elided in most examples for brevity — assume the envelope from §1 and a character object
from §2.

### 3.1 `LogItemPickup`

Fires whenever an item enters a player's inventory from anywhere: ground loot, a death
crate, a care package, a vehicle trunk. **It is the superset event.**

```json
{
  "_T": "LogItemPickup",
  "character": { "name": "sounddevice", "accountId": "account.aaac…", "teamId": 1, "…": "…" },
  "item": {
    "itemId": "Item_Back_B_01_StartParachutePack_C",
    "stackCount": 1,
    "category": "Equipment",
    "subCategory": "BackPack",
    "attachedItems": []
  },
  "common": { "isGame": 0.10000000149011612 },
  "_D": "2026-05-03T04:21:24.216Z"
}
```

| Field | Type |
|---|---|
| `character` | Character |
| `item` | Item |

`stackCount` = **quantity acquired by this action**, not the resulting total. Verified:
a player picking 30-round 9 mm stacks logs `30, 30, 30, 30` — not `30, 60, 90, 120`.

### 3.2 `LogItemPickupFromLootBox`

Looting a **player death crate**. Note the capital **B**.

```json
{
  "_T": "LogItemPickupFromLootBox",
  "character": { "name": "n9i99mgae85", "teamId": 14, "accountId": "account.da9e…", "…": "…" },
  "item": {
    "itemId": "Item_Ammo_556mm_C",
    "stackCount": 30,
    "category": "Ammunition",
    "subCategory": "None",
    "attachedItems": []
  },
  "ownerTeamId": 4,
  "creatorAccountId": "account.52df6a6ae0a44c7dba3a7dfbd1230e5e",
  "common": { "isGame": 1 },
  "_D": "2026-05-03T04:23:08.205Z"
}
```

| Field | Type | Meaning |
|---|---|---|
| `character` | Character | Who is looting |
| `item` | Item | |
| `ownerTeamId` | int | `teamId` of the **dead player who created the crate** |
| `creatorAccountId` | string | `accountId` of the dead player who created the crate |

This is the **only** way to attribute looted gear to its previous owner. In the samples,
60/1976 pickups had `character.accountId === creatorAccountId` — a revived player
recovering their own crate.

> ⚠️ Casing: the official docs and `documentation.pubg.com` both spell this
> `LogItemPickupFromLootbox`. That string occurs **0 times** in 219k real events;
> `LogItemPickupFromLootBox` occurs 1976 times. Two third-party libraries
> (`pubg-python`, `NovikovRoman/pubg`) also use the capital-B form. **Match on capital B**,
> and defensively accept both.

### 3.3 `LogItemPickupFromCarepackage`

```json
{
  "_T": "LogItemPickupFromCarepackage",
  "character": { "name": "lusan_-", "teamId": 19, "…": "…" },
  "item": {
    "itemId": "Item_Heal_MedKit_C",
    "stackCount": 1,
    "category": "Use",
    "subCategory": "Heal",
    "attachedItems": []
  },
  "carePackageUniqueId": 0,
  "carePackageName": "Carapackage_SmallPackage_C",
  "common": { "isGame": 1.5 },
  "_D": "2026-05-03T04:27:22.992Z"
}
```

| Field | Type | Meaning |
|---|---|---|
| `character` | Character | |
| `item` | Item | |
| `carePackageUniqueId` | number | Documented. A small **per-match ordinal** — observed values `0`–`3` across n=177 (`{0:82, 1:51, 2:36, 3:8}`). Combined with `carePackageName` it **does** distinguish individual crates within a match (e.g. `steam_abca7f1c` has `(0,RedBox) (1,RedBox) (2,RedBox) (3,RedBox)` = four distinct red boxes). Not globally unique, and `0` is the most common value, but usable — do not discard it. |
| `carePackageName` | string | **Undocumented but always present.** Matches `itemPackage.itemPackageId` values from `LogCarePackageLand`. |

Note the event name uses **`Carepackage`** (lowercase `p`), unlike `LogCarePackageLand` /
`LogCarePackageSpawn` which use **`CarePackage`** (capital `P`). Both spellings are real
and both appear in the same file.

### 3.4 `LogItemPickupFromVehicleTrunk`

```json
{
  "_T": "LogItemPickupFromVehicleTrunk",
  "character": { "name": "LLLL-SHouSHuai", "teamId": 20, "…": "…" },
  "vehicle": { "vehicleType": "WheeledVehicle", "vehicleId": "Dacia_A_03_v2_Esports_C", "seatIndex": -1, "…": "…" },
  "item": {
    "itemId": "Item_Weapon_FlashBang_C",
    "stackCount": 0,
    "category": "Equipment",
    "subCategory": "Throwable",
    "attachedItems": []
  },
  "common": { "isGame": 1 },
  "_D": "2026-05-03T04:25:46.328Z"
}
```

| Field | Type |
|---|---|
| `character` | Character |
| `vehicle` | Vehicle |
| `item` | Item |

Note the `stackCount: 0` in this genuine payload — see §9.4.

### 3.5 `LogItemPutToVehicleTrunk`

Same shape as 3.4, opposite direction (item leaves the player's inventory).

| Field | Type |
|---|---|
| `character` | Character |
| `vehicle` | Vehicle |
| `item` | Item |

### 3.6 `LogItemPickupFromCustomPackage`

| Field | Type |
|---|---|
| `character` | Character |
| `item` | Item |

> ⚠️ **UNVERIFIED.** Zero occurrences across 219k real events (4 normal Erangel squad
> matches). Field list is from the official docs only. Presumably fires in event/arcade
> modes with custom supply drops. Handle it, but you will not see it in normal matches.

### 3.7 `LogItemDrop`

```json
{
  "_T": "LogItemDrop",
  "character": { "name": "lusan_-", "teamId": 19, "…": "…" },
  "item": {
    "itemId": "Item_Back_C_02_Lv3_C",
    "stackCount": 1,
    "category": "Equipment",
    "subCategory": "BackPack",
    "attachedItems": []
  },
  "common": { "isGame": 0.10000000149011612 },
  "_D": "2026-05-03T04:22:36.398Z"
}
```

| Field | Type |
|---|---|
| `character` | Character |
| `item` | Item |

`stackCount` = **quantity dropped**, which may be a partial stack. Observed drops of the
same itemId with counts `5, 10, 20, 30, 60, 90, 100, 140, 180`.

**`LogItemDrop` does NOT fire on death.** See §7.1 — this is measured, not assumed.

### 3.8 `LogItemUse`

```json
{
  "_T": "LogItemUse",
  "character": { "name": "jeng_ie", "teamId": 1, "…": "…" },
  "item": {
    "itemId": "Item_Ammo_762mm_C",
    "stackCount": 30,
    "category": "Ammunition",
    "subCategory": "None",
    "attachedItems": []
  },
  "common": { "isGame": 0.10000000149011612 },
  "_D": "2026-05-03T04:22:32.883Z"
}
```

| Field | Type |
|---|---|
| `character` | Character |
| `item` | Item |

**Not just consumables.** Observed `(category, subCategory)` on `LogItemUse` across 6,773
events:

| category / subCategory | count | What it means |
|---|---|---|
| `Ammunition` / `None` | 4,339 | **Reload** — see §8 |
| `Use` / `Boost` | 1,282 | Energy drink, painkiller, adrenaline |
| `Use` / `Heal` | 1,016 | Bandage, first aid, medkit |
| `Use` / `None` | 47 | Blue chip, `Item_Neon_Key_C`, `Item_Tiger_Key_C` |
| `Use` / `Gadget` | 17 | Bulletproof shield, emergency pickup, mountain bike |
| `Use` / `Fuel` | 9 | Jerry can, spare tire |
| `Equipment` / `Parachute` | 63 | Backup parachute deploy |

`stackCount` on `LogItemUse` is the **count held before this use is deducted**. Strongly
supported by the 2018 sample: four players' consecutive `Item_Heal_Bandage_C` uses log
exactly `5, 4, 3, 2, 1`.

> ⚠️ **But the sequence is not always monotonically decreasing by 1.** `LogItemUse` also
> fires for uses that are subsequently **cancelled/interrupted**, producing repeated and
> even increasing values. Counterexamples in the same 2018 file: `Opeyone` /
> `Item_Heal_Bandage_C` → `[5, 5, 4, 3]`; `Balagat` / `Item_Heal_FirstAid_C` →
> `[2, 2, 3, 3, 2, 1, 4]`. A reducer doing `set(stackCount - 1)` unconditionally will
> silently delete an item the player still holds. **Set the count to `stackCount` on
> receipt, and only decrement when a completion signal (e.g. a following `LogHeal`)
> confirms the use.**

### 3.9 `LogItemEquip`

| Field | Type |
|---|---|
| `character` | Character |
| `item` | Item |

Item moved into a loadout slot. `(category, subCategory)` observed on 9,282 equips:

`Equipment/BackPack` 1661, `Equipment/Parachute` 436, `Equipment/Ascender` 436,
`Equipment/Bluechip` 436, `Weapon/Main` 1727, `Equipment/Throwable` 2095,
`Equipment/Headgear` 1061, `Equipment/Vest` 940, `Weapon/Melee` 321,
`Weapon/Handgun` 149, `Use/Fuel` 20.

The `Parachute` / `Ascender` / `Bluechip` equips are exactly one per player at match
start (436 = one per player across 4 matches) — spawn kit, not loot.

### 3.10 `LogItemUnequip`

| Field | Type |
|---|---|
| `character` | Character |
| `item` | Item |

**Equip/unequip is perfectly balanced per player over a whole match** — verified 0/98
players unbalanced in the 2018 sample. That balance is achieved by the phantom
death-time unequip burst described in §7.2, *not* by real gameplay.

### 3.11 `LogItemAttach`

```json
{
  "_T": "LogItemAttach",
  "character": { "name": "Asinbcosctan", "teamId": 13, "…": "…" },
  "parentItem": {
    "itemId": "Item_Weapon_Kar98k_C",
    "stackCount": 1,
    "category": "Weapon",
    "subCategory": "Main",
    "attachedItems": []
  },
  "childItem": {
    "itemId": "Item_Attach_Weapon_Upper_Scope6x_C",
    "stackCount": 1,
    "category": "Attachment",
    "subCategory": "None",
    "attachedItems": []
  },
  "common": { "isGame": 0.10000000149011612 },
  "_D": "2026-05-03T04:22:33.376Z"
}
```

| Field | Type | Meaning |
|---|---|---|
| `character` | Character | |
| `parentItem` | Item | The weapon receiving the attachment |
| `childItem` | Item | The attachment |

**`parentItem.attachedItems` is the PRE-mutation state** — it does **not** yet contain
`childItem.itemId`. Verified corpus-wide across all four 2026 matches: **1 contained /
5461 not** (n = 5462; per-match 0/1471, 1/1377, 0/1301, 0/1313), and 0 / 664 (2018).
The rule holds at 99.98 %, not 100 % — so **append defensively**: only add
`childItem.itemId` if it is not already in the list, or de-duplicate afterwards.

`childItem` is always `category: "Attachment"`. `parentItem` is always
`Weapon/Main` (624) or `Weapon/Handgun` (40) in the 2018 sample.

### 3.12 `LogItemDetach`

```json
{
  "_T": "LogItemDetach",
  "character": { "name": "dam7031", "teamId": 1, "…": "…" },
  "parentItem": {
    "itemId": "Item_Weapon_AK47_C",
    "stackCount": 1,
    "category": "Weapon",
    "subCategory": "Main",
    "attachedItems": [ "Item_Attach_Weapon_Upper_Holosight_C" ]
  },
  "childItem": {
    "itemId": "Item_Attach_Weapon_Upper_Holosight_C",
    "stackCount": 1,
    "category": "Attachment",
    "subCategory": "Sight",
    "attachedItems": []
  },
  "common": { "isGame": 0.10000000149011612 },
  "_D": "2026-05-03T04:22:41.134Z"
}
```

Same field set as `LogItemAttach`.

**`parentItem.attachedItems` is also PRE-mutation** — it **still contains**
`childItem.itemId`. Verified corpus-wide: **5300 contained / 0 not** (2026, all four
matches), 617 / 0 (2018). No exceptions.

So both events are symmetrical: `attachedItems` always describes the weapon *before* the
event is applied. Apply the mutation yourself.

### 3.13 Adjacent events you need for a correct inventory

| Event | Item fields | Why it matters |
|---|---|---|
| `LogHeal` | `character`, `item`, **`healAmount`** (number) | Docs say `healamount`; **real data is `healAmount`**, 21,563/21,563. `item` is usually the blank sentinel. |
| `LogArmorDestroy` | `attacker`, `victim`, `item`, `attackId`, `damageTypeCategory`, `damageReason`, `damageCauserName`, `distance` | Helmet/vest broke. `item` is the destroyed armour. **Whether this also emits `LogItemUnequip` is not something you should assume** — see §9.6. |
| `LogPlayerUseThrowable` | `attackId`, `fireWeaponStackCount`, `attacker`, `attackType`, `weapon` | Actual throw. `weapon` is `Equipment/Throwable` (763) or `Weapon/Handgun` (36 — the M79). |
| `LogPlayerUseFlareGun` | same shape as above | |
| `LogPlayerAttack` | `attackId`, `fireWeaponStackCount`, `attacker`, `attackType`, `weapon`, `vehicle` | `weapon` is a full Item (with `attachedItems`) — a cheap way to sample the currently-held weapon. Blank item for fists. |
| `LogCarePackageSpawn` / `LogCarePackageLand` | `itemPackage` | The only place you learn crate contents. |
| `LogWeaponFireCount` | `character`, `weaponId` (string), `fireCount` (int) | Fired-round counter, bucketed in **10s** — but not exclusively: 3209/3217 observed events are multiples of 10, 8 carry residuals (`1`×5, `2`×2, `3`×1), presumably end-of-life flushes. **Do not assert `fireCount % 10 == 0`.** Not per-shot. |
| `LogMatchStart` / `LogMatchEnd` | `characters: [CharacterWrapper]` | See §7.4 — mostly useless for loadout. |

---

## 4. Enums

### 4.1 `category`

Official `enums/telemetry/item/category.json`:

```json
["Ammunition","Attachment","Equipment","Event","Use","Weapon"]
```

Observed in 137,337 real item objects:

| Value | Count | In official enum? |
|---|---|---|
| `Weapon` | 53,579 | yes |
| `Equipment` | 23,793 | yes |
| `Attachment` | 17,327 | yes |
| `Ammunition` | 12,345 | yes |
| `Use` | 12,335 | yes |
| `""` (empty) | 17,958 | **no** — sentinel for "no item" |
| `Event` | 0 | yes, but never observed |

### 4.2 `subCategory`

Official `enums/telemetry/item/subCategory.json`:

```json
["Backpack","Boost","Fuel","Gadget","Handgun","Headgear","Heal","Jacket",
 "Main","Melee","None","Parachute","Revive","Sight","Throwable","Vest","Ascender"]
```

**Observed in real 2026 data** (137,337 objects):

| Value | Count | In official enum? | Note |
|---|---|---|---|
| `Main` | 51,131 | yes | |
| `None` | 27,492 | yes | all Ammunition, most Attachment, some Use |
| `""` | 17,958 | **no** | blank-item sentinel |
| `Throwable` | 8,632 | yes | |
| `Heal` | 7,401 | yes | |
| `BackPack` | 5,947 | **NO — enum says `Backpack`** | ⚠️ casing trap |
| `Boost` | 4,344 | yes | |
| `Headgear` | 4,035 | yes | |
| `Vest` | 3,789 | yes | |
| `Sight` | 2,583 | yes | only 2 itemIds — see below |
| `Melee` | 1,723 | yes | |
| `Handgun` | 725 | yes | |
| `Parachute` | 499 | yes | |
| `Ascender` | 436 | yes | |
| `Bluechip` | 436 | **no** | `Item_Special_Bluechip_C` |
| `Gadget` | 100 | yes | |
| `Fuel` | 85 | yes | |
| `Jacket` | 19 | yes | ghillie suit |
| `CamoNetting` | 2 | **no** | `Item_Weapon_CamoNet_Rondo_C` |
| `Revive` | 0 | yes | never observed |

**The 2018 data spelled it `"Backpack"` (806 occurrences, 0 of `"BackPack"`).**
The 2026 data spells it `"BackPack"` (5947 occurrences, 0 of `"Backpack"`). PUBG changed
the casing. Normalise before comparing, and drive UI slots off a
case-insensitive lookup.

**`Attachment/Sight` is inconsistent and mostly useless.** Only two itemIds ever carry it:

```
Attachment / Sight : Item_Attach_Weapon_Upper_DotSight_01_C, Item_Attach_Weapon_Upper_Holosight_C
Attachment / None  : everything else — including Item_Attach_Weapon_Upper_ACOG_01_C,
                     Item_Attach_Weapon_Upper_Scope3x_C, Item_Attach_Weapon_Upper_Scope6x_C,
                     Item_Attach_Weapon_Upper_CQBSS_C, Item_Attach_Weapon_Upper_PM2_01_C,
                     Item_Attach_Weapon_Upper_Aimpoint_C, Item_Attach_Weapon_Upper_DualOptic_4x1x_C
```

**Do not use `subCategory` to classify attachments.** Parse the itemId instead — the naming
convention `Item_Attach_Weapon_<SLOT>_*` is reliable:

| itemId infix | Attachment slot |
|---|---|
| `_Upper_` | Optic / sight |
| `_Lower_` | Grip / laser |
| `_Muzzle_` | Muzzle |
| `_Magazine_` | Magazine |
| `_Stock_` | Stock |
| `_SideRail_` | Canted sight |

### 4.3 subCategory → UI loadout slot

| UI slot | Selector | Cardinality | Caveats |
|---|---|---|---|
| Primary weapon 1 | `category=Weapon` ∧ `subCategory=Main` | 2 slots share this | **Telemetry does not say which of the two.** Disambiguate by equip order (first equipped = slot 1) and maintain it yourself. |
| Primary weapon 2 | same as above | | |
| Sidearm | `category=Weapon` ∧ `subCategory=Handgun` | 1 | Includes `Item_Weapon_M79_C`, `Item_Weapon_StunGun_C`, `Item_Weapon_Sawnoff_C` |
| Melee | `category=Weapon` ∧ `subCategory=Melee` | 1 | Pan, machete, crowbar, pickaxe, sickle |
| Throwable | `category=Equipment` ∧ `subCategory=Throwable` | 1 *type* at a time | Equipping a different throwable type unequips the previous one. Multiple types are *held* but only one is *equipped*. |
| Helmet | `category=Equipment` ∧ `subCategory=Headgear` | 1 | Level from itemId suffix `_Lv1/_Lv2/_Lv3` |
| Vest | `category=Equipment` ∧ `subCategory=Vest` | 1 | Level from itemId suffix |
| Backpack | `category=Equipment` ∧ `subCategory=BackPack` | 1 | ⚠️ casing |
| (not a slot) | `Equipment/Parachute`, `Equipment/Ascender`, `Equipment/Bluechip` | 1 each | Auto-equipped at spawn. Filter these out of the UI or they will occupy fake slots. |
| Backpack contents | `Ammunition/*`, `Use/*`, `Attachment/*`, un-equipped `Equipment/Throwable` | n | Never `Equip`ped |

**`Weapon/Main` is not "a gun".** It also contains utility items that occupy a primary
slot: `Item_Weapon_Mortar_C`, `Item_Weapon_PanzerFaust100M_C`, `Item_Weapon_Ziplinegun_C`,
`Item_Weapon_TacPack_C`, `Item_Weapon_TraumaBag_C`, `Item_Weapon_IntegratedRepair_C`, and
— surprisingly — `Item_Weapon_FlareGun_C` (which `api-assets` files under `Handgun`).

Full observed `Weapon/Main` set (45 distinct, 2026 Erangel):

```
ACE32, AK47, AUG, AWM, Berreta686, BerylM762, Crossbow, DP12, Dragunov, FAMASG2, FNFal,
FlareGun, Groza, HK416, IntegratedRepair, JS9, K2, Kar98k, L6, M16A4, M249, M24, MG3,
MP5K, Mini14, Mk12, Mk14, Mk47Mutant, Mortar, P90, PanzerFaust100M, QBZ95, SCAR-L, SKS,
Saiga12, TacPack, Thompson, TraumaBag, UMP, UZI, VSS, Vector, Winchester, Ziplinegun,
vz61Skorpion
```

---

## 5. `stackCount` semantics per event

This differs per event and is the #1 source of wrong inventory counts.

| Event | `stackCount` means |
|---|---|
| `LogItemPickup` | Quantity **acquired by this action**. (Verified: 30,30,30,30 for four 9 mm pickups, not a running total.) |
| `LogItemPickupFromLootBox` / `…FromCarepackage` / `…FromVehicleTrunk` | Same — quantity acquired. |
| `LogItemDrop` | Quantity **dropped**, may be a partial stack. |
| `LogItemPutToVehicleTrunk` | Quantity moved into the trunk. |
| `LogItemUse` (Heal/Boost) | **Count held BEFORE the deduction.** Observed `5,4,3,2,1`. A use of the last item logs `1`. ⚠️ Cancelled uses also emit the event, so the series can repeat or increase (§3.8) — treat the value as an absolute resync, not a guaranteed −1 step. |
| `LogItemUse` (Ammunition) | Reserve ammo of that type held at reload time. See §8. |
| `LogItemEquip` / `LogItemUnequip` | Almost always `1`. For `Equipment/Throwable`, `1`. Not a reliable inventory quantity. |
| `LogPlayerAttack.fireWeaponStackCount` | Separate field, not `item.stackCount`. |

---

## 6. `itemId` → human-readable name

**Exact path:**

```
https://raw.githubusercontent.com/pubg/api-assets/master/dictionaries/telemetry/item/itemId.json
repo: pubg/api-assets   path: dictionaries/telemetry/item/itemId.json
```

**Format:** a flat JSON object, `{ "<itemId>": "<Display Name>" }`. 192 entries (~9.3 KB).

```json
{
  "Item_Attach_Weapon_Stock_SniperRifle_CheekPad_C": "Sniper Rifle Cheek Pad",
  "Item_Ammo_556mm_C": "5.56mm Ammo",
  "Item_Armor_C_01_Lv3_C": "Military Vest (Level 3)",
  "InstantRevivalKit_C": "Critical Response Kit"
}
```

**Sibling files in the same repo (all confirmed to exist via the git tree API):**

| Path | Contents |
|---|---|
| `dictionaries/telemetry/item/itemId.json` | itemId → display name (192) |
| `dictionaries/telemetry/vehicle/vehicleId.json` | vehicleId → display name |
| `dictionaries/telemetry/damageCauserName.json` | |
| `dictionaries/telemetry/damageTypeCategory.json` | |
| `dictionaries/telemetry/mapName.json` | e.g. `Erangel_Main` → `Erangel` |
| `dictionaries/gameMode.json` | |
| `enums/telemetry/item/category.json` | array of category values |
| `enums/telemetry/item/subCategory.json` | array of subCategory values |
| `enums/telemetry/attackType.json`, `carryState.json`, `damageReason.json`, `objectType.json`, `objectTypeStatus.json`, `regionId.json`, `weatherId.json`, `vehicle/vehicleType.json` | |
| `seasons.json`, `survivalTitles.json` | |

> The `api-assets` README refers to the enum file as **`subcategory.json`** (lowercase `c`).
> The actual filename is **`subCategory.json`** (capital `C`). The README is wrong; trust
> the git tree.

### Icons

`Assets/Item/$category/$subCategory/$itemId.png`, e.g.
`Assets/Item/Weapon/Main/Item_Weapon_AK47_C.png`.

**Exception:** `Attachment` has **no** subCategory folder — attachments live directly in
`Assets/Item/Attachment/<itemId>.png` (55 files), not `Assets/Item/Attachment/None/`
as the README claims.

Existing folders: `Assets/Item/{Ammunition/None, Attachment, Equipment/{Backpack,
Headgear, Jacket, Throwable, Vest}, Use/{Boost, Fuel, Gadget, Heal},
Weapon/{Handgun, Main, Melee}}`. Note the folder is `Backpack` (lowercase p) while
current telemetry emits `BackPack` — **you cannot build the asset path by string
concatenation from live telemetry values.** Build an explicit map.

Monochrome HUD icons: `Assets/Icons/Item/$category/$subCategory/$itemId.png`, with skinned
items collapsed to a fake skin id `00` (e.g. `Item_Head_E_00_Lv1_C`).

### Dictionary coverage gap — **11 % of live itemIds are missing**

Of 155 distinct itemIds observed in four 2026 Erangel matches, **17 have no dictionary
entry**:

```
Item_Ammo_ZiplinegunHook_C            Item_Special_Bluechip_C
Item_Attach_Weapon_Lower_TiltedGrip_C Item_Weapon_CamoNet_Rondo_C
Item_Attach_Weapon_Muzzle_AR_MuzzleBrake_C
Item_Attach_Weapon_Upper_DualOptic_4x1x_C
Item_Back_BlueBlocker_Lv1             Item_Weapon_CoverStructDropHandFlare_C
Item_Back_BlueBlocker_Lv3             Item_Weapon_FAMASG2_C
Item_Bluechip_C                       Item_Weapon_IntegratedRepair_C
Item_Neon_Key_C                       Item_Weapon_PackageFlare_C
Item_SpareTire_C                      Item_Weapon_Pickaxe_C
                                      Item_Weapon_Ziplinegun_C
```

Some are high-volume (`Item_Weapon_Pickaxe_C` 787, `Item_Weapon_FAMASG2_C` 772,
`Item_Attach_Weapon_Lower_TiltedGrip_C` 706). The dictionary lags live patches, and
`pubg/api-assets` has open issues about exactly this (e.g. issue #278, "Muzzle brake is
missing from the item dictionary").

**You must ship a fallback name generator.** Recommended: strip the `Item_` prefix and
`_C` suffix, split on `_`, drop known noise tokens (`Weapon`, `Attach`, `Ammo`), then
space-separate. Also ship a local override map you can patch without a redeploy.

54 dictionary entries were never observed (other maps, removed items) — that direction is
harmless.

---

## 7. Death, loot transfer, and the things telemetry does not tell you

### 7.1 `LogItemDrop` does **not** fire on death — measured

| Sample | Test | Result |
|---|---|---|
| 2018 | `LogItemDrop` within 0…+3 s of the dropper's own `LogPlayerKill` | **0 / 608** |
| 2026 | `LogItemDrop` within −1…+5 s of the dropper's own `LogPlayerKillV2` | **4 / 1285** (0.3 %, i.e. genuine manual drops that coincide) — **single match only** (match #1). Corpus-wide `LogItemDrop` totals across the four matches are 1285 / 1216 / 2472 / 1262 = 6235; the 4/1285 ratio was not re-measured on the other three. |

A dead player's inventory is transferred to a death crate with **no event describing the
transfer and no event describing the crate's contents**.

### 7.2 What actually happens on death

Measured on **one** 2026 match (`steam_11ca6321`): 103 `LogPlayerKillV2` events for 93
distinct victim `accountId`s (and 93 distinct victim names). The 10 surplus events are
**genuine second deaths** — players who died, came back (Erangel comeback/respawn; gaps of
750–1332 s), and died again. So: **key deaths on `character.accountId` and take the
LATEST (final) `LogPlayerKillV2` per account**, never the earliest. Keying on the earliest
and suppressing afterwards discards 1,586 legitimate item events in this one match alone
(`LogHeal` 492, `LogItemPickup` 426, `LogItemUse` 140, `LogItemEquip` 139,
`LogItemUnequip` 109, `LogItemAttach` 98, `LogItemDetach` 97, `LogItemDrop` 85).

Events emitted **by the victim**, bucketed by time relative to their **final**
`LogPlayerKillV2` (the table below only reproduces under final-death keying; with
earliest-keying you get 571 unequips in the 5–70 s window and a non-empty `> +70 s`
bucket):

| Window | Events |
|---|---|
| −5 … 0 s | `LogHeal` 17, `LogItemUnequip` 16, `LogItemUse` 5, `LogItemEquip` 4, `LogItemPickup` 1 (normal gameplay) |
| **0 … +1 s** | **`LogItemDetach` 587**, `LogItemDrop` 4 |
| +1 … +5 s | *(nothing)* |
| **+5 … +70 s** | **`LogItemUnequip` 563** |
| > +70 s | *(nothing)* |

The post-death `LogItemUnequip` delay distribution: **n = 563, min 60.0 s, median 60.0 s,
max 60.9 s — every single one in the 60 s bucket.** This is the death-crate / pawn
destruction tick, not a gameplay action.

Consequences for your state machine:

0. **A player can have more than one `LogPlayerKillV2` in a match.** Resolve the victim's
   *final* kill event per `accountId` before applying any of the rules below; freezing on
   the first one throws away the player's entire second life.
1. **On the victim's final `LogPlayerKillV2` (or `LogPlayerKill`), snapshot their inventory
   and freeze it.** Everything after that timestamp for that `accountId` is engine
   bookkeeping.
2. The `LogItemDetach` burst at +0…1 s strips every attachment off every weapon the victim
   owned. If you apply it naively, the victim's weapons lose all attachments in your
   reconstruction, and the attachments appear as loose items. **Suppress `LogItemDetach`
   for a character after their death timestamp.**
3. The `LogItemUnequip` burst at +60 s empties the victim's loadout. **Suppress
   `LogItemUnequip` for a character after their death timestamp**, or their gear will
   vanish from the replay 60 s after they die.
4. Item events that arrive for a character **after** their death should be dropped
   wholesale. Exception: a player who is revived (`LogPlayerRevive`) resumes normal
   activity — key the freeze off `LogPlayerKillV2`/`LogPlayerKill` (final death), never off
   `LogPlayerMakeGroggy` (knock).

### 7.3 Reconstructing death-crate contents

There is no crate-contents event. You must derive it:

```
crate(creatorAccountId) contents  ≈  inventory(creatorAccountId) at their death timestamp
```

then decrement it as `LogItemPickupFromLootBox` events arrive with matching
`creatorAccountId`. `ownerTeamId` gives you the crate's team for colouring.

Known imprecision:
- The crate also receives whatever the victim was *holding*, and the engine detaches
  attachments (§7.2), so an attachment that was on a weapon may be looted as a **separate**
  `Attachment` item from the crate. Your crate model needs to account for both forms.
- Multiple deaths in the same spot produce multiple crates keyed by different
  `creatorAccountId`s; they are visually merged in-game but distinct in telemetry.
- Crates from players who died before you started tracking (e.g. partial telemetry) cannot
  be reconstructed.

Trunk contents have the same problem in reverse: `LogItemPutToVehicleTrunk` /
`LogItemPickupFromVehicleTrunk` are the only trunk signals, there is no
"trunk contents" event, and **`vehicleUniqueId` was absent** on all 200 trunk-event
vehicle objects — you must key trunks on `vehicleId` + spatial/temporal proximity, which
is fragile when several identical vehicles are parked together.

### 7.4 `LogMatchStart` / `LogMatchEnd` `CharacterWrapper` is not a loadout source

```json
{
  "character": { "…Character…" },
  "primaryWeaponFirst": "",
  "primaryWeaponSecond": "",
  "secondaryWeapon": "",
  "spawnKitIndex": 0
}
```

Measured across 4 matches:

| Event | Field | empty | non-empty |
|---|---|---|---|
| `LogMatchStart` | `primaryWeaponFirst` | 395 | **0** |
| `LogMatchStart` | `primaryWeaponSecond` | 395 | **0** |
| `LogMatchStart` | `secondaryWeapon` | 395 | **0** |
| `LogMatchEnd` | `primaryWeaponFirst` | 381 | 14 |
| `LogMatchEnd` | `primaryWeaponSecond` | 381 | 14 |
| `LogMatchEnd` | `secondaryWeapon` | 391 | 4 |

Only the surviving winners have non-empty values at match end. **These fields cannot be
used to seed or validate loadout state.** (They are, however, the only official
confirmation that PUBG's own model is *primary-first / primary-second / secondary*.)

`LogMatchEnd` also carries an **undocumented `allWeaponStats`** field.

---

## 8. Ammunition — what you can and cannot know

**There is no per-shot ammo-consumption event.** Confirmed: no telemetry event decrements a
magazine. What you *do* get:

| Signal | Granularity |
|---|---|
| `LogPlayerAttack` | One event per shot fired (with `fireWeaponStackCount`) — this is per-trigger-pull, not ammo bookkeeping |
| `LogWeaponFireCount` | `character`, `weaponId`, `fireCount` — bucketed in **10s**, 3209/3217 events; 8 residuals (`1`,`2`,`3`). Do not assert `fireCount % 10 == 0`. |
| **`LogItemUse` with `category: "Ammunition"`** | **One event per reload** |

The `LogItemUse`-on-ammo signal is the useful one and is widely missed. Real trace
(`jieke033`, 9 mm, one match):

```
04:22:35.026 LogItemPickup 30      04:23:25.686 LogItemPickup 30
04:22:35.306 LogItemPickup 30      04:23:25.974 LogItemPickup 30
04:22:45.111 LogItemPickup 30      04:23:26.226 LogItemPickup 30
04:22:45.409 LogItemPickup 30      04:23:40.465 LogItemUse   180
04:23:03.303 LogItemUse   120      04:24:46.507 LogItemUse   168
                                   04:26:30.247 LogItemUse   133
                                   04:27:02.859 LogItemUse   114
```

Reading: 4 × 30 picked = 120 reserve → reload logs `120` → 30 rounds move to the magazine
→ 90 left → 3 × 30 picked = 180 → reload logs `180`. The arithmetic closes.

**So:** `LogItemUse(Ammunition).stackCount` = **reserve rounds of that type held at the
instant of the reload, before the rounds move into the magazine.** The delta between
consecutive reloads (after accounting for pickups/drops) equals rounds loaded, which
equals rounds fired since the last reload.

> ⚠️ The pre- vs post-deduction reading is inferred from arithmetic across several traces
> and is consistent, but PUBG documents none of this. Treat magazine-level ammo as
> **derived and approximate**; treat reserve ammo at reload timestamps as **exact**.
> Between reloads you can only interpolate.

Ammo pickup/drop are exact: `LogItemPickup` / `LogItemDrop` `stackCount` is the quantity
moved.

---

## 9. Implementation notes

### 9.1 Timestamps

- `_D` is ISO-8601 UTC. **Precision is not stable.** The 2018 file uses 3 fractional
  digits with `Z` (`2018-05-18T03:50:59.094Z`). **All 218,917 2026 `_D` values also end in
  the `Z` UTC designator — none carries a numeric offset such as `+00:00`.** The only
  instability is fractional-digit width: 7 digits on the **first event of each file**
  (`2026-05-03T04:21:24.1248606Z`, 4 of 218,917) and 3 digits on the remaining 218,913.
  `Date.parse` / `datetime.fromisoformat` will choke on 7 fractional digits in some
  runtimes — **truncate the fraction to 6 (or 3) digits before parsing.**
- **Events are in file order, but ties are common.** Many logically-ordered pairs share the
  exact same millisecond. **Never sort by `_D` alone** — that reorders `Equip`/`Pickup`
  pairs. Use a stable sort keyed on `(_D, originalIndex)`, or just trust file order.

### 9.2 Event ordering rules (measured, one 2026 match)

| Pair, within 20 ms, same player + itemId | Count |
|---|---|
| `LogItemEquip` → `LogItemPickup` | **1378** (corpus per-match: 1378 / 1267 / 2586 / 1255) |
| `LogItemPickup` → `LogItemEquip` | **0** in this match — but **44** in match `steam_5d13f824`; 0 in the other two |
| `LogItemPickup` → `LogItemPickupFromLootBox` | 444 |
| `LogItemPickup` → `LogItemPickupFromCarepackage` | 40 |

So: **equip usually fires before pickup**, and **plain pickup fires before the specialised
pickup**. ⚠️ The `1378 : 0` ratio is a property of this one cherry-picked match, **not of
the schema** — the reverse order does occur (44 times in one of the four matches), so do
not assert ordering is guaranteed in one direction. The actionable rule is unchanged:
your reducer must tolerate an `Equip` for an item it has never seen — treat `Equip` as
implicitly creating the item if absent.

`LogItemAttach` can likewise fire **before** the `LogItemPickup` of the attachment (a
player attaching directly from ground loot). Same rule: create on demand.

### 9.3 De-duplicating pickups

```
LogItemPickupFromLootBox      1976/1976 have a matching LogItemPickup within 50 ms
LogItemPickupFromCarepackage   177/177  ditto
LogItemPickupFromVehicleTrunk   58/65   ditto  (89 %)
```

**Recommended:** drive inventory quantity **only** off `LogItemPickup`, and use the
specialised events **only** for provenance/attribution (who owned it, which crate, which
vehicle). This is correct for LootBox and Carepackage. For VehicleTrunk, 7/65 had no
paired `LogItemPickup` — so a pure-`LogItemPickup` model loses ~11 % of trunk pickups.
Handle trunk pickups as: apply if no `LogItemPickup` within 50 ms, otherwise skip.

### 9.4 `stackCount: 0` is real

27 genuine events across 4 matches carry `stackCount: 0` on a non-blank item — e.g.
`LogItemPickupFromVehicleTrunk` of `Item_Weapon_FlashBang_C` with `stackCount: 0`,
`LogItemDrop` of `Item_Ammo_762mm_C` with `stackCount: 0`. Do not `assert(stackCount > 0)`
and do not let a 0 delete an existing stack.

Separately, the blank-item sentinel (§2) always has `stackCount: 0`.

### 9.5 Casing traps, consolidated

| Correct (real data) | Wrong but plausible / found in docs |
|---|---|
| `LogItemPickupFromLootBox` | `LogItemPickupFromLootbox` (official docs), `LogItemPickupFromLootbox` |
| `LogItemPickupFromCarepackage` | `LogItemPickupFromCarePackage` |
| `LogCarePackageLand` / `LogCarePackageSpawn` | `LogCarepackageLand` |
| `LogItemPutToVehicleTrunk` | `LogItemPutToVehicleRunk` (typo in `NovikovRoman/pubg`: `LogItemPickupFromVehicleRunk`) |
| `healAmount` | `healamount` (official docs) |
| `"BackPack"` (2026) | `"Backpack"` (official enum file, and 2018 data) |
| `feulPercent` | `fuelPercent` |
| `subCategory.json` (file) | `subcategory.json` (api-assets README) |
| `Carapackage_*` (itemPackageId) | `Carepackage_*` |
| `dBNOId` | `dbnoId`, `DBNOId` |

Practical defence: build your event dispatch table with **case-insensitive keys** and log
loudly on any `_T` you do not recognise — PUBG adds events without documenting them
(`LogSpecialZoneInCharacters`, 1332 occurrences in the samples, is in **no** official doc).

### 9.6 Attach / detach mutation rules

```
on LogItemAttach:
    # parentItem.attachedItems is PRE-state and does NOT contain childItem
    #   (5461/5462 corpus-wide — 1 exception already contained it, so append defensively)
    weapon = find(parentItem.itemId)  or  create(parentItem)
    weapon.attachedItems = dedupe(parentItem.attachedItems + [childItem.itemId])
    remove childItem.itemId from loose inventory   # may not be there yet — tolerate

on LogItemDetach:
    # parentItem.attachedItems is PRE-state and DOES contain childItem
    weapon.attachedItems = parentItem.attachedItems - [childItem.itemId]
    add childItem to loose inventory
    # ...UNLESS the character is already dead — see §7.2
```

Because `parentItem.attachedItems` is authoritative pre-state, the safest implementation is
to **overwrite** your weapon's attachment list from the event payload rather than
incrementally mutate your own — that self-heals drift.

### 9.7 Identity keys

- Key inventories on **`character.accountId`**, never `character.name`.
- Items have **no unique instance id.** Two identical AK47s on one player are
  indistinguishable. Your inventory must be a multiset keyed on
  `(itemId, sorted(attachedItems))` or an ordered list, not a map keyed on `itemId`.
  `attachedItems` is the only thing that distinguishes two same-model weapons — and it
  changes over time.
- `LogItemUnequip` gives you `itemId` and `attachedItems` but **not which slot**. With two
  `Weapon/Main` items you must match on `attachedItems` and fall back to slot order.

### 9.8 Bots

`character.type === "user_ai"` (1388 / 137,468 character objects). Bots generate full item
event streams. Filter them out of "player" views or your loot statistics will be skewed.

### 9.9 Recommended reducer skeleton

```
state[accountId] = {
  slots: { primary1, primary2, sidearm, melee, throwable, helmet, vest, backpack },
  loose: Multiset<Item>,
  deadAt: timestamp | null
}

for event in file_order(events):
    a = event.character?.accountId
    if a and state[a].deadAt and event._T in ITEM_EVENTS: continue   # §7.2

    switch normalize(event._T):
      LogItemEquip            -> ensure_exists(item); move to slot(item.subCategory)
      LogItemUnequip          -> clear slot; add item to loose
      LogItemPickup           -> loose.add(item, item.stackCount)
      LogItemPickupFromLootBox        -> record provenance(creatorAccountId, ownerTeamId) only
      LogItemPickupFromCarepackage    -> record provenance(carePackageName) only
      LogItemPickupFromVehicleTrunk   -> if no LogItemPickup within 50ms: loose.add(...)
      LogItemDrop             -> loose.remove(item, item.stackCount)
      LogItemPutToVehicleTrunk-> loose.remove(item, item.stackCount)
      LogItemUse              -> loose.set(item, item.stackCount)      # pre-deduction count
                                 # decrement only on a confirming LogHeal — the use may be
                                 # cancelled and re-emit the same/greater count (§3.8)
                                 (Ammunition: record reserve, do not decrement by 1)
      LogItemAttach           -> weapon.attachedItems = dedupe(parent.attachedItems + [child])
      LogItemDetach           -> weapon.attachedItems = parent.attachedItems - [child]
      LogArmorDestroy         -> mark victim's helmet/vest destroyed
      LogPlayerKillV2 / LogPlayerKill -> state[victim].deadAt = _D ; snapshot as crate
                                 # use the LAST such event per accountId — players can die
                                 # twice in a match (§7.2). deadAt must move forward only.
```

Because `LogItemUse` carries the **pre-deduction** count, `loose.set(item, stackCount)`
is more accurate than decrementing your own running total — it resyncs on every use.
Do **not** subtract 1 unconditionally: a cancelled use emits the event without consuming
the item, and the −1 would silently destroy inventory.
Similarly, `LogItemAttach/Detach` payloads resync attachment lists. Prefer
**payload-derived absolute state** over your own accumulator wherever the payload provides
it; PUBG's telemetry has gaps and your accumulator will drift.

---

## 10. Known gaps — things telemetry simply does not contain

| Gap | Impact |
|---|---|
| No per-shot ammo consumption | Magazine contents are unknowable between reloads. Reserve ammo is exact only at reload timestamps (§8). |
| No death-crate contents event | Crate must be derived from the victim's last known inventory (§7.3). |
| No `LogItemDrop` on death | The single biggest reason naive inventory models produce dead players who still "have" everything (§7.1). |
| No item instance IDs | Two identical items are indistinguishable; you cannot follow a specific gun through a match. |
| No slot index on equip/unequip | Primary-1 vs primary-2 must be inferred from order (§4.3). |
| `vehicleUniqueId` missing on trunk events | Cannot key a specific vehicle trunk reliably (§7.3). |
| No healing-item→`LogHeal` linkage | `LogHeal.item` is the blank sentinel 81 % of the time; pair `LogItemUse` with subsequent `LogHeal` by time+player. |
| No inventory snapshot event | There is no "here is the full inventory" event, ever. Everything is deltas from an empty start at `LogPlayerCreate`. |
| Attachment ↔ weapon binding on pickup | Picking up a weapon from a crate gives you its `attachedItems`, but picking up a loose attachment gives no hint which weapon it was on. |

---

## ⚠️ Unverified / needs live confirmation

Everything below could **not** be confirmed against a primary source or real data. Do not
treat any of it as fact.

1. **`LogItemPickupFromCustomPackage`** — 0 occurrences in 219k real events. Its field list
   (`character`, `item`) comes from the official docs only. Its behaviour, whether it is
   also mirrored by `LogItemPickup`, and which modes emit it are unknown.
2. **`category: "Event"`** — present in the official enum, never observed. Meaning unknown.
3. **`subCategory: "Revive"`** — present in the official enum, never observed. Presumably
   `InstantRevivalKit_C` / self-revive items; unconfirmed.
4. **The 60 s post-death `LogItemUnequip` delay** is measured as exactly 60.0–60.9 s across
   563 events in one match on one map. That it is *the death-crate lifetime* is an
   inference. Whether the constant differs on other maps, in ranked, or in esports mode is
   unverified — but the suppression rule in §7.2 is robust regardless of the exact value.
5. **`LogItemUse(Ammunition)` pre- vs post-deduction** — arithmetic across several traces
   is consistent with pre-deduction reserve, but a couple of traces have unexplained
   deltas (possibly weapons picked up with rounds already chambered). Verify against a
   match where you know the ground truth before shipping ammo counters.
6. **Whether `LogArmorDestroy` is accompanied by `LogItemUnequip`** for the destroyed
   helmet/vest. The 2018 sample shows an unequip ~2 s before one death that looks like a
   broken helmet, but this was not measured systematically. Test before relying on it.
7. **Console / mobile shard differences.** All real data analysed is `steam` PC. Xbox/PS
   and PUBG Mobile telemetry may differ in event set or casing.
8. **Non-Erangel maps.** All 2026 samples are Erangel. Map-specific items (Taego's
   Comeback BR, Deston's ascenders/blue chips, Rondo's camo netting, Karakin's sticky
   bombs) will introduce `subCategory` values not in the observed list — `Bluechip` and
   `CamoNetting` already appear and are **not** in the official enum, so expect more.
9. **Whether `_V` will return.** 2018 had `_V: 2`; 2026 has none. A future patch could
   reintroduce it. Do not require its absence.
10. **`spawnKitIndex`** was `0` for all 395 players in all samples. Its non-zero meaning
    (event modes / custom loadouts) is unconfirmed.
11. **`LogSpecialZoneInCharacters`** — 1332 occurrences, appears in no official
    documentation. Observed top-level keys are `_D`, `_T`, `common`, `charactersInZone`,
    `zoneInfo`; the nested shapes were not analysed. Not item-related, but it will hit your
    unknown-event branch.
12. **`LogMatchEnd.allWeaponStats`** — undocumented, shape not analysed here.
13. **Throwable slot semantics.** The model "one throwable *type* equipped at a time,
    switching types emits unequip+equip in the same millisecond" matches the observed
    traces but was not exhaustively proven against every throwable combination.
14. **`Item_Weapon_FlareGun_C` classified as `Weapon/Main`** in 2026 telemetry while
    `api-assets` files its icon under `Weapon/Handgun`. Which is authoritative for UI
    purposes is a judgement call; telemetry says it occupies a primary slot.
