# PUBG API — Match / Participant / Roster & Player-Stats Schema

**Scope:** everything an implementer needs to build the `matches`, `rosters` and `participants`
tables and the player season / ranked / mastery tables, without re-reading the web.

**Research date:** 2026-07-22.
**API version at time of research:** the official changelog's newest entry is **v22.1.0**.

> **Rule used throughout this document:** no field name appears here unless it was seen in an
> authoritative artifact (official OpenAPI schema, official changelog, official data dictionary,
> or a captured real API response). Everything that could not be confirmed is in
> [§14 Unverified](#14--unverified--needs-live-confirmation) and tagged ⚠️ inline.

---

## Sources

Every URL below was actually fetched during this research pass.

### Official — PUBG OpenAPI source of truth (`pubg/api-documentation-content`)

This repo is what generates <https://documentation.pubg.com>. The rendered HTML pages are
JS-driven and unreadable by fetchers; the raw YAML below is the real content.

| What | URL |
|---|---|
| Repo root listing | `https://api.github.com/repos/pubg/api-documentation-content/contents/` |
| `rst/` listing | `https://api.github.com/repos/pubg/api-documentation-content/contents/rst` |
| `swagger/en/` listing | `https://api.github.com/repos/pubg/api-documentation-content/contents/swagger/en` |
| `swagger/en/schemas/` listing | `https://api.github.com/repos/pubg/api-documentation-content/contents/swagger/en/schemas` |
| `swagger/en/responses/` listing | `https://api.github.com/repos/pubg/api-documentation-content/contents/swagger/en/responses` |
| `swagger/en/paths/` listing | `https://api.github.com/repos/pubg/api-documentation-content/contents/swagger/en/paths` |
| **Match schema** | <https://raw.githubusercontent.com/pubg/api-documentation-content/master/swagger/en/schemas/match.yml> |
| **Participant schema** | <https://raw.githubusercontent.com/pubg/api-documentation-content/master/swagger/en/schemas/participant.yml> |
| **Roster schema** | <https://raw.githubusercontent.com/pubg/api-documentation-content/master/swagger/en/schemas/roster.yml> |
| **Asset schema** | <https://raw.githubusercontent.com/pubg/api-documentation-content/master/swagger/en/schemas/asset.yml> |
| **gameModeStats schema** | <https://raw.githubusercontent.com/pubg/api-documentation-content/master/swagger/en/schemas/gameModeStats.yml> |
| **rankedGameModeStats schema** | <https://raw.githubusercontent.com/pubg/api-documentation-content/master/swagger/en/schemas/rankedGameModeStats.yml> |
| **weaponMastery schema** | <https://raw.githubusercontent.com/pubg/api-documentation-content/master/swagger/en/schemas/weaponMastery.yml> |
| **weaponSummary schema** | <https://raw.githubusercontent.com/pubg/api-documentation-content/master/swagger/en/schemas/weaponSummary.yml> |
| **survivalMastery schema** | <https://raw.githubusercontent.com/pubg/api-documentation-content/master/swagger/en/schemas/survivalMastery.yml> |
| **player schema** | <https://raw.githubusercontent.com/pubg/api-documentation-content/master/swagger/en/schemas/player.yml> |
| matchList schema | <https://raw.githubusercontent.com/pubg/api-documentation-content/master/swagger/en/schemas/matchList.yml> |
| match 200 response | <https://raw.githubusercontent.com/pubg/api-documentation-content/master/swagger/en/responses/match-200.yml> |
| lifetime 200 response | <https://raw.githubusercontent.com/pubg/api-documentation-content/master/swagger/en/responses/lifetime-200.yml> |
| playerSeason 200 response | <https://raw.githubusercontent.com/pubg/api-documentation-content/master/swagger/en/responses/playerSeason-200.yml> |
| rankedstats 200 response | <https://raw.githubusercontent.com/pubg/api-documentation-content/master/swagger/en/responses/rankedstats-200.yml> |
| weaponMastery 200 response | <https://raw.githubusercontent.com/pubg/api-documentation-content/master/swagger/en/responses/weaponMastery-200.yml> |
| survivalMastery 200 response | <https://raw.githubusercontent.com/pubg/api-documentation-content/master/swagger/en/responses/survivalMastery-200.yml> |
| matches.yml (servers/shards) | <https://raw.githubusercontent.com/pubg/api-documentation-content/master/swagger/en/matches.yml> |
| seasons.yml (ranked path) | <https://raw.githubusercontent.com/pubg/api-documentation-content/master/swagger/en/seasons.yml> |
| lifetime.yml | <https://raw.githubusercontent.com/pubg/api-documentation-content/master/swagger/en/lifetime.yml> |
| mastery.yml | <https://raw.githubusercontent.com/pubg/api-documentation-content/master/swagger/en/mastery.yml> |
| players.yml | <https://raw.githubusercontent.com/pubg/api-documentation-content/master/swagger/en/players.yml> |
| paths/match.yml | <https://raw.githubusercontent.com/pubg/api-documentation-content/master/swagger/en/paths/match.yml> |
| paths/rankedstats.yml | <https://raw.githubusercontent.com/pubg/api-documentation-content/master/swagger/en/paths/rankedstats.yml> |
| paths/index.yml, parameters/index.yml | same dir |
| **Changelog (authoritative deprecations/removals)** | <https://raw.githubusercontent.com/pubg/api-documentation-content/master/rst/changelog/changelog.rst> |
| Known issues | <https://raw.githubusercontent.com/pubg/api-documentation-content/master/rst/known-issues.rst> |
| Getting started | <https://raw.githubusercontent.com/pubg/api-documentation-content/master/rst/getting-started.rst> |
| Making requests | <https://raw.githubusercontent.com/pubg/api-documentation-content/master/rst/making-requests.rst> |
| Docs site index | <https://documentation.pubg.com/en/index.html> |

### Official — data dictionaries (`pubg/api-assets`)

| What | URL |
|---|---|
| Repo root listing | `https://api.github.com/repos/pubg/api-assets/contents/` |
| README | <https://raw.githubusercontent.com/pubg/api-assets/master/README.md> |
| **gameMode dictionary** | <https://raw.githubusercontent.com/pubg/api-assets/master/dictionaries/gameMode.json> |
| **mapName dictionary** | <https://raw.githubusercontent.com/pubg/api-assets/master/dictionaries/telemetry/mapName.json> |
| weapon-mastery medal dictionary | <https://raw.githubusercontent.com/pubg/api-assets/master/dictionaries/weaponMastery/medalName.json> |
| item id dictionary (weapon IDs) | <https://raw.githubusercontent.com/pubg/api-assets/master/dictionaries/telemetry/item/itemId.json> |
| survival titles | <https://raw.githubusercontent.com/pubg/api-assets/master/survivalTitles.json> |
| seasons (stale, see notes) | <https://raw.githubusercontent.com/pubg/api-assets/master/seasons.json> |

### Real captured API responses (independent, byte-verified)

| What | URL |
|---|---|
| **Real `/matches/{id}` response, `steam`, 2019-09-08** (post-v12 schema) | <https://github.com/ramonsaraiva/pubg-python/blob/master/tests/match_response.json> |
| **Real `/players/{id}/weapon_mastery` response** | <https://github.com/ramonsaraiva/pubg-python/blob/master/tests/weapon_mastery_response.json> |
| **Real `/players/{id}/seasons/{seasonId}` response** | <https://github.com/ramonsaraiva/pubg-python/blob/master/tests/season_playerid_response.json> |
| Real `/players` response | <https://github.com/ramonsaraiva/pubg-python/blob/master/tests/players_response.json> |
| Real `/leaderboards` response (pre-v20 shape) | <https://github.com/ramonsaraiva/pubg-python/blob/master/tests/leaderboard_response.json> |
| **Real `/matches/{id}` response, `pc-na`, 2018-04-04** (pre-v12 schema, shows the removed fields) | <https://github.com/EpicKitten/PUBG-Resources/blob/master/API/Matches/match.bro.official.2018-04.na.duo-fpp.2018.04.04.ce7c2730-928d-45c3-a8da-76f2ada8a7d0/4e76b5d6-d9cd-4698-97c1-b494b800b64d-match.json> |
| Real match JSON, `pc-eu`, 2018-04-03 | <https://gist.github.com/discordianfish/d7b53b5408f338e1b7cabff37d301521> |
| **Real match attributes showing `matchType: "competitive"`, 2020-11-12, `steam`** | <https://github.com/dataitgirls4/team_5/issues/6> |

### Independent third-party consumers (cross-check for field names / casing)

| What | URL |
|---|---|
| `pubg-python` domain models (Match/Roster/Participant/Stats/WeaponMasterySummary) | <https://raw.githubusercontent.com/ramonsaraiva/pubg-python/master/pubg_python/domain/base.py> |
| `pubg.js` Participant model | <https://raw.githubusercontent.com/ickerio/pubg.js/master/src/matches/Participant.js> |
| `pubg.js` Roster model | <https://raw.githubusercontent.com/ickerio/pubg.js/master/src/matches/Roster.js> |
| Go wrapper `NovikovRoman/pubg` (gameModeStats, rankedGameModeStats, weaponSummary structs) | <https://raw.githubusercontent.com/NovikovRoman/pubg/master/common_structs.go> |
| Go wrapper `moonrailgun/PUBGo` (pre-v12 participant struct) | <https://pkg.go.dev/github.com/moonrailgun/PUBGo/server/config/pubg/schema> |
| **pubg.sh production ingester** (real-world gotchas) | <https://raw.githubusercontent.com/pubgsh/api/master/src/models/Match.js> |
| PUBG-Resources wiki | <https://github.com/EpicKitten/PUBG-Resources/wiki/API-Documentation> |
| Live 404/401 probes against `https://api.pubg.com/shards/steam/matches/...`, `/samples`, `/players` | (executed; results in §1) |

---

## 1. Endpoint basics

```
GET https://api.pubg.com/shards/{platform}/matches/{matchId}
Accept: application/vnd.api+json          # application/json also accepted
Accept-Encoding: gzip                     # optional, server honours it
```

| Fact | Value | Source |
|---|---|---|
| Auth for `/matches/{id}` | **None required.** `matches.yml` has no `security:` block and its description says *"Authorization is not required for the /matches endpoint because it is not rate-limited."* Verified live: an unauthenticated request returns **404** (not 401) for an unknown ID. | `matches.yml`, live probe |
| Auth for everything else | `Authorization: Bearer <api-key>`. Verified live: `/samples` and `/players` return **401** without a key. | `making-requests.rst`, live probe |
| Rate limit | 10 req/min default. Headers: `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset` (UNIX ts). 429 on exceed. `/matches` and telemetry do **not** count. | `rate-limits.rst`, `api-keys.rst` |
| Data retention | **14 days.** Match data older than 14 days is gone. Player match lists go back 14 days; season-stats match lists give up to **32** most recent matches within 14 days (⚠️ whether that cap is 32 per player or 32 per game mode is disputed between official sources — see §14). | `making-requests.rst`, `getting-started.rst` |
| Response media type | `application/vnd.api+json` (JSON:API) | all `*-200.yml` |
| Documented HTTP codes for `/matches/{id}` | 200, 401, 404, 415 (no 429 — not rate limited) | `paths/match.yml` |

**Shard values accepted by `/matches/{id}`** (`matches.yml` `servers.platform.enum`):
`console`, `kakao`, `psn`, `stadia`, `steam`, `tournament`, `xbox` — default `steam`.

Other endpoints (`players.yml`, `lifetime.yml`, `seasons.yml`) accept only
`kakao`, `psn`, `stadia`, `steam`, `xbox`; `mastery.yml` also allows `console`.

Legacy `platform-region` shards (`pc-na`, `pc-eu`, `pc-as`, `pc-jp`, `pc-krjp`, `pc-kakao`,
`pc-oc`, `pc-ru`, `pc-sa`, `pc-sea`, `psn-as`, `psn-eu`, `psn-na`, `psn-oc`,
`xbox-as`, `xbox-eu`, `xbox-na`, `xbox-oc`, `xbox-sa`) are **deprecated for `/matches`**
(changelog v8.0.0) and only remain valid for pre-Survival-Title season stats
(`seasons.yml` second server block).

---

## 2. `/matches/{id}` response envelope

Top-level keys, confirmed identical in the 2018, 2019 and 2020 real payloads:
`data`, `included`, `links`, `meta`.

```json
{
  "data": {
    "type": "match",
    "id": "f80126f4-9520-4c66-9198-57820d04bf00",
    "attributes": { "...": "see §3" },
    "relationships": {
      "rosters": { "data": [ { "type": "roster", "id": "c218f901-c126-4294-9647-f36c4037f957" } ] },
      "assets":  { "data": [ { "type": "asset",  "id": "62a09051-d277-11e9-a33c-0a586469e71b" } ] }
    }
  },
  "included": [
    { "type": "roster", "...": "..." },
    { "type": "participant", "...": "..." },
    { "type": "asset", "...": "..." }
  ],
  "links": { "self": "https://api-origin.playbattlegrounds.com/shards/steam/matches/f80126f4-9520-4c66-9198-57820d04bf00" },
  "meta": {}
}
```

`included` is a **heterogeneous flat array**. In the verified 2019 squad-fpp match it contained
`participant × 91`, `roster × 26`, `asset × 1`. You must filter by `type` and resolve
`relationships.*.data[].id` against it.

`meta` is always `{}` in every captured response.

---

## 3. Match object (`data`)

Source: `schemas/match.yml` + captured payloads.

### 3.1 Real payload (2019-09-08, `steam`, verbatim key order)

```json
{
  "createdAt": "2019-09-08T19:58:52Z",
  "gameMode": "squad-fpp",
  "titleId": "bluehole-pubg",
  "isCustomMatch": false,
  "seasonState": "progress",
  "duration": 1773,
  "stats": null,
  "shardId": "steam",
  "tags": null,
  "mapName": "Baltic_Main",
  "matchType": "official"
}
```

### 3.2 Real payload (2020-11-12, `steam`, ranked match — shows undocumented `matchType`)

```json
{
  "duration": 1492,
  "stats": null,
  "gameMode": "squad-fpp",
  "mapName": "Baltic_Main",
  "isCustomMatch": false,
  "matchType": "competitive",
  "createdAt": "2020-11-12T17:20:20Z",
  "titleId": "bluehole-pubg",
  "shardId": "steam",
  "tags": null,
  "seasonState": "progress"
}
```

### 3.3 Field table

| Field | JSON type | Nullable? | Meaning | Notes |
|---|---|---|---|---|
| `createdAt` | string, ISO-8601 `YYYY-MM-DDTHH:MM:SSZ` | no | *"Time this match object was stored in the API"* | **Not** the match start time. Effectively "match end / ingest time". UTC, always `Z`, no fractional seconds in any observed payload. |
| `duration` | integer | no | Match length in **seconds** | pubg.sh discards matches with `duration > 10000` as corrupt (see §12). |
| `gameMode` | string | no | Game mode played | Enum in §3.4. |
| `mapName` | string | no | Map ID | Enum in §3.5. Absent entirely in very old (2018) payloads. |
| `isCustomMatch` | boolean | no | True for custom matches | Added in v1.3.0. |
| `matchType` | string | no | Match category | Enum in §3.6. Added in v17.1.0 — **absent from matches created before that**. |
| `seasonState` | string | no | Season lifecycle state | Enum in §3.7. Added v6.0.0 (PC) / v9.0.0 (console). |
| `shardId` | string | no | Platform shard of the **match** | e.g. `steam`, `console`, `kakao`, `tournament`. Old matches carry `pc-na`-style values. |
| `titleId` | string | no | Studio+game identifier | Always `"bluehole-pubg"` in every captured payload. |
| `stats` | object | **always `null` in every captured payload** | documented "N/A" | Do not model it. |
| `tags` | object | **always `null` in every captured payload** | documented "N/A" | Do not model it. ⚠️ non-null values for esports/tournament matches unconfirmed. |
| `patchVersion` | string | ⚠️ **not present in 2019/2020 payloads** | documented "N/A" | Present as `""` in the 2018 payload only. Treat as optional/absent. |

### 3.4 `gameMode` enum — 39 values

Both the OpenAPI `match.yml` enum and the official `dictionaries/gameMode.json` list **exactly
the same 39 values** (verified by comparing the two sets).

| Value | Display name (official dictionary) |
|---|---|
| `solo` | Solo TPP |
| `solo-fpp` | Solo FPP |
| `duo` | Duo TPP |
| `duo-fpp` | Duo FPP |
| `squad` | Squad TPP |
| `squad-fpp` | Squad FPP |
| `normal-solo` | Solo TPP |
| `normal-solo-fpp` | Solo FPP |
| `normal-duo` | Duo TPP |
| `normal-duo-fpp` | Duo FPP |
| `normal-squad` | Squad TPP |
| `normal-squad-fpp` | Squad FPP |
| `conquest-solo` | Conquest Solo TPP |
| `conquest-solo-fpp` | Conquest Solo FPP |
| `conquest-duo` | Conquest Duo TPP |
| `conquest-duo-fpp` | Conquest Duo FPP |
| `conquest-squad` | Conquest Squad TPP |
| `conquest-squad-fpp` | Conquest Squad FPP |
| `esports-solo` | Esports Solo TPP |
| `esports-solo-fpp` | Esports Solo FPP |
| `esports-duo` | Esports Duo TPP |
| `esports-duo-fpp` | Esports Duo FPP |
| `esports-squad` | Esports Squad TPP |
| `esports-squad-fpp` | Esports Squad FPP |
| `war-solo` | War Solo TPP |
| `war-solo-fpp` | War Solo FPP |
| `war-duo` | War Duo TPP |
| `war-duo-fpp` | War Duo FPP |
| `war-squad` | Squad TPP *(sic — dictionary says "Squad TPP", not "War Squad TPP")* |
| `war-squad-fpp` | War Squad FPP |
| `zombie-solo` | Zombie Solo TPP |
| `zombie-solo-fpp` | Zombie Solo FPP |
| `zombie-duo` | Zombie Duo TPP |
| `zombie-duo-fpp` | Zombie Duo FPP |
| `zombie-squad` | Zombie Squad TPP |
| `zombie-squad-fpp` | Zombie Squad FPP |
| `lab-tpp` | Lab TPP |
| `lab-fpp` | Lab FPP |
| `tdm` | Team Deathmatch |

Notes:
- `lab-tpp` / `lab-fpp` do **not** follow the `-solo/-duo/-squad` pattern.
- `tdm` has no perspective suffix.
- There is **no** `airoyale-*` game mode; Air Royale is a `matchType`, not a `gameMode`.
- Changelog v11.0.0: the old bare `normal` value was split into
  `normal / war / zombie / conquest / esports` families, each with `-solo/-duo/-squad` and `-fpp`.
- Changelog v5.0.0: squad size + perspective were appended to custom-match modes
  (`normal` → `normal-squad-fpp`).

### 3.5 `mapName` enum

⚠️ **The OpenAPI enum is stale.** `match.yml` lists only 7 values
(`Baltic_Main, Desert_Main, DihorOtok_Main, Erangel_Main, Range_Main, Savage_Main, Summerland_Main`).
The official **data dictionary** `dictionaries/telemetry/mapName.json` is current and lists 12.
**Use the dictionary, and treat `mapName` as an open string in the DB.**

| `mapName` | Map | In OpenAPI enum? |
|---|---|---|
| `Baltic_Main` | Erangel (Remastered) | yes |
| `Chimera_Main` | Paramo | **no** |
| `Desert_Main` | Miramar | yes |
| `DihorOtok_Main` | Vikendi | yes |
| `Erangel_Main` | Erangel | yes — dictionary display string is exactly "Erangel"; this is the *original* map (remaster is `Baltic_Main`) |
| `Heaven_Main` | Haven | **no** |
| `Kiki_Main` | Deston | **no** |
| `Neon_Main` | Rondo | **no** |
| `Range_Main` | Camp Jackal | yes — dictionary display string is exactly "Camp Jackal"; this is the training range |
| `Savage_Main` | Sanhok | yes |
| `Summerland_Main` | Karakin | yes |
| `Tiger_Main` | Taego | **no** |

Changelog v14.0.0: *"[PC] The remastered Erangel map will be called `Baltic_Main` and not
`Erangel_Main`."* Modern PC matches on Erangel report `Baltic_Main`. Both values must be
mapped to "Erangel" in any UI.

### 3.6 `matchType` enum

| Value | Documented? | Meaning |
|---|---|---|
| `official` | yes | Normal public matchmaking |
| `custom` | yes | Custom match |
| `event` | yes | Event mode |
| `training` | yes | Training grounds (`Range_Main`) |
| `arcade` | yes | Arcade modes (TDM, War, etc.) |
| `airoyale` | yes (added v21.2.0) | Air Royale |
| `seasonal` | yes (added v21.2.0) | Seasonal mode |
| **`competitive`** | **NO — undocumented** | **Ranked matches.** Confirmed in a real 2020-11-12 `steam` payload alongside `gameMode: "squad-fpp"`. Corroborated indirectly by `weaponSummaries.*.CompetitiveStatsTotal` existing in the mastery schema. |

**Do not use a DB enum/CHECK constraint for `matchType`.** Store it as text.

### 3.7 `seasonState` enum

`closed`, `prepare`, `progress`. `"progress"` observed in both the 2019 and 2020 real payloads.

### 3.8 `relationships`

| Key | Present in 2018 payload | Present in 2019+ payloads | Shape |
|---|---|---|---|
| `rosters` | yes | **yes** | `{ data: [ { type: "roster", id } ] }` |
| `assets` | yes | **yes** | `{ data: [ { type: "asset", id } ] }` — exactly 1 element in every captured payload |
| `rounds` | yes (`{ "data": [] }`) | **absent** | documented "N/A"; always empty |
| `spectators` | yes (`{ "data": [] }`) | **absent** | documented "N/A"; always empty |

`links.self` on the match object is present. Note the 2019 capture returns an internal hostname
(`api-origin.playbattlegrounds.com`) — **never treat `links.self` as a callable URL.**

---

## 4. Roster object

Source: `schemas/roster.yml` + captured payloads.

### 4.1 Real payload (2019, verbatim)

```json
{
  "type": "roster",
  "id": "86278981-ae3e-4fff-b422-9e080b30913a",
  "attributes": {
    "stats": { "rank": 12, "teamId": 27 },
    "won": "false",
    "shardId": "steam"
  },
  "relationships": {
    "team": { "data": null },
    "participants": {
      "data": [
        { "type": "participant", "id": "2564a25f-cc22-432d-a766-797b49990101" },
        { "type": "participant", "id": "e26d8198-5d98-4318-880e-131ae5086ce6" }
      ]
    }
  }
}
```

### 4.2 Field table

| Path | JSON type | Meaning / notes |
|---|---|---|
| `type` | string | always `"roster"` |
| `id` | string (UUID) | **Randomly generated per response.** Not stable across requests for the same match — do not use as a natural key across refetches. |
| `attributes.shardId` | string | platform shard |
| `attributes.stats.rank` | integer, 1..130 | Team placement in the match (1 = winner) |
| `attributes.stats.teamId` | integer | *"An arbitrary ID assigned to this roster"* — the in-match team number. Not globally meaningful. Observed values are non-contiguous (e.g. 27 in a 26-roster match). |
| `attributes.won` | **string** `"true"` / `"false"` | **YES, it really is a string.** Confirmed in both the 2018 (`pc-na`) and 2019 (`steam`) real payloads, in the OpenAPI schema (`type: string`), and in the `moonrailgun/PUBGo` Go struct (`Won string`). Parse with `won === "true"`. |
| `relationships.participants.data[]` | array of `{type:"participant", id}` | The linkage to participants. **This is the only way to group participants into teams** — participants carry no team id. |
| `relationships.team.data` | always `null` | documented "N/A" |

Changelog v1.3.1: *"Rosters will show highest participant rank."*
Changelog v7.8.0 fixed *"roster.attributes.won was sometimes false for the winning team."*

---

## 5. Participant object — **this defines the `participants` table**

Source: `schemas/participant.yml` + captured payloads + 3 independent wrappers.

### 5.1 Real payload (2019-09-08, `steam`, verbatim — this is the CURRENT shape)

```json
{
  "type": "participant",
  "id": "2a317e98-3feb-454e-b80e-bb45814cca28",
  "attributes": {
    "stats": {
      "DBNOs": 0,
      "assists": 2,
      "boosts": 6,
      "damageDealt": 140.194351,
      "deathType": "byplayer",
      "headshotKills": 1,
      "heals": 19,
      "killPlace": 31,
      "killStreaks": 1,
      "kills": 1,
      "longestKill": 48.2024765,
      "name": "EllasticHeart",
      "playerId": "account.48bea908f26c4957a278c84e099257b6",
      "revives": 0,
      "rideDistance": 2799.167,
      "roadKills": 0,
      "swimDistance": 0,
      "teamKills": 0,
      "timeSurvived": 1294.6,
      "vehicleDestroys": 0,
      "walkDistance": 3281.73315,
      "weaponsAcquired": 4,
      "winPlace": 10
    },
    "actor": "",
    "shardId": "steam"
  }
}
```

**Verification:** the union of `attributes.stats` keys across **all 91 participants** in that real
match is exactly the 23 keys above — no more, no fewer. That set is identical to the current
official `participant.yml` schema and to the `pubg.js` and `pubg-python` models.

### 5.2 Envelope fields

| Path | Type | Notes |
|---|---|---|
| `type` | string | always `"participant"` |
| `id` | string (UUID) | randomly generated per response; only meaningful inside this response |
| `attributes.actor` | string | documented "N/A"; **always `""`** in every captured payload |
| `attributes.shardId` | string | **Per-player** shard. On console cross-play this can differ from the match's `shardId` — changelog v15.0.0: *"Individual players' platforms can be determined from `participant.shardId`."* |

### 5.3 `attributes.stats` — every field (23)

| Field | JSON type | Range (from schema) | Meaning | Gotchas |
|---|---|---|---|---|
| `DBNOs` | integer | ≥ 0 | Number of enemies knocked ("down but not out") | **Casing: capital `DBNO` + lowercase `s`.** The season-stats equivalent is `dBNOs` (lowercase d). |
| `assists` | integer | 0..128 | Enemies this player damaged that a teammate killed | v21.0.0 fixed a mismatch vs. telemetry event counts |
| `boosts` | integer | ≥ 0 | Boost items used | |
| `damageDealt` | number (float) | ≥ 0 | Total damage dealt. **Self-inflicted damage is subtracted.** | Float with many decimals (`140.194351`) |
| `deathType` | string enum | see §5.4 | How the player died, or `alive` | |
| `headshotKills` | integer | 0..129 | Kills via headshot | |
| `heals` | integer | ≥ 0 | Healing items used | |
| `killPlace` | integer | 1..130 | Rank **within the match by kill count** (1 = most kills) | Not a placement. Easy to confuse with `winPlace`. |
| `killStreaks` | integer | ≥ 0 | *"Total number of kill streaks"* | **Was always `0` until changelog v20.3.0.** Also mis-populated before v1.1.1. Any historical analysis crossing those versions is invalid. |
| `kills` | integer | 0..129 | Enemies killed | v13.0.1 fixed "kill steal" miscounts |
| `longestKill` | number (float) | ≥ 0 | Longest kill distance, **metres (inferred** — `participant.yml` description is empty and states no unit; sibling `rideDistance`/`swimDistance`/`walkDistance` are documented "measured in meters"**)** | Was `int` before v2.0.0 — schema is `number`. Use a float column. |
| `name` | string | — | Player IGN at match time | **Snapshot** — a renamed player keeps the old name on old matches. Not a join key. |
| `playerId` | string | — | Account ID, format `account.<32 hex chars>` | **This is the stable join key to the players table.** |
| `revives` | integer | ≥ 0 | Times this player revived teammates | |
| `rideDistance` | number (float) | ≥ 0 | Distance in vehicles, **metres** | See known-issue in §12 |
| `roadKills` | integer | ≥ 0 | Kills while in a vehicle | |
| `swimDistance` | number (float) | ≥ 0 | Distance swum, **metres** | Added v1.2.0/v1.3.0. **Absent from pre-2018-05 payloads.** Was always 0 on Xbox at introduction. |
| `teamKills` | integer | ≥ 0 | Teammates killed | |
| `timeSurvived` | number (float) | ≥ 0 | Seconds survived | Was `int` before v2.0.0. v7.5.0 fixed cases where it was a timestamp instead of seconds. |
| `vehicleDestroys` | integer | ≥ 0 | Vehicles destroyed | |
| `walkDistance` | number (float) | ≥ 0 | Distance on foot, **metres** | |
| `weaponsAcquired` | integer | ≥ 0 | Weapons picked up | Mis-populated before v1.1.1 |
| `winPlace` | integer | 1..130 | **This player's final placement** | Equals their roster's `stats.rank` |

### 5.4 `deathType` enum

| Value | Meaning |
|---|---|
| `alive` | Survived to the end of the match |
| `byplayer` | Killed by another player |
| `byzone` | Killed by the blue or red zone (**only since changelog v13.0.0**; before that these were reported as `byplayer`) |
| `suicide` | Self-inflicted |
| `logout` | Disconnected / left |

Observed in the real 2019 match: `alive`, `byplayer`, `byzone`, `suicide` (all four present in one
match). `logout` is documented but was not present in that particular match.

### 5.5 Fields that **do NOT exist** in the current participant object

This is the most important correction in this document.

| Field | Status | Evidence |
|---|---|---|
| `killPoints` | **Removed** in changelog **v12.0.0**. Deprecated v6.0.0 (PC) / v9.0.0 (console). | Present in 2018 payload (`"killPoints": 1054`), absent from 2019 payload |
| `killPointsDelta` | **Removed** v12.0.0 | Present 2018 (`20.4883461`), absent 2019 |
| `lastKillPoints` | **Removed** v12.0.0 | Present 2018 (`0`), absent 2019 |
| `lastWinPoints` | **Removed** v12.0.0 | Present 2018 (`0`), absent 2019 |
| `mostDamage` | **Removed** v12.0.0 | Present 2018 (always `0` even then), absent 2019 |
| `rankPoints` | **Removed** v12.0.0. Added v6.0.0 (PC), deprecated v7.2.0. | Absent 2019 |
| `winPoints` | **Removed** v12.0.0 | Present 2018 (`1031`), absent 2019 |
| `winPointsDelta` | **Removed** v12.0.0 | Present 2018 (`-6.275014`), absent 2019 |
| `rankPointsTitle` | ⚠️ **Never a participant field at all.** It exists only on `playerSeason.attributes.gameModeStats.{gameMode}` (see §7), where it is deprecated as of v20.0.0. | changelog v7.8.0 / v9.0.0 introduce it under `playerSeason...`; never under `participant...` |
| `killPlacePoints` | ⚠️ **No evidence this field has ever existed in the PUBG API.** Not in any OpenAPI schema, not in the changelog, not in any of the three real payloads, zero hits in a global GitHub issue search. Most likely a conflation with the Kaggle "PUBG Finish Placement Prediction" dataset columns (`killPlace`, `killPoints`, `winPlacePerc`, `winPoints`). | absence across all sources |
| `winPlacePoints` | ⚠️ Same as above — **no evidence it exists.** | absence across all sources |

Because retention is 14 days, **no live match you can fetch today will contain any of the removed
fields.** Do not add columns for them. They are documented here only so you recognise them in old
blog posts, tutorials, and Kaggle notebooks.

### 5.6 Pre-v12 participant payload (for reference only — 2018-04-04, `pc-na`)

```json
{
  "DBNOs": 1, "assists": 1, "boosts": 1, "damageDealt": 134.81,
  "deathType": "byplayer", "headshotKills": 1, "heals": 0,
  "killPlace": 20, "killPoints": 1054, "killPointsDelta": 20.4883461,
  "killStreaks": 0, "kills": 2, "lastKillPoints": 0, "lastWinPoints": 0,
  "longestKill": 14, "mostDamage": 0, "name": "deafinitaly",
  "playerId": "account.b557c02946424c0ba83e5154c3dfc71a",
  "revives": 0, "rideDistance": 0, "roadKills": 0, "teamKills": 0,
  "timeSurvived": 244, "vehicleDestroys": 0, "walkDistance": 240.472885,
  "weaponsAcquired": 0, "winPlace": 34, "winPoints": 1031,
  "winPointsDelta": -6.275014
}
```

Note: no `swimDistance` at all in this vintage.

---

## 6. Asset object (telemetry link)

```json
{
  "type": "asset",
  "id": "62a09051-d277-11e9-a33c-0a586469e71b",
  "attributes": {
    "name": "telemetry",
    "description": "",
    "createdAt": "2019-09-08T20:29:40Z",
    "URL": "https://telemetry-cdn.playbattlegrounds.com/bluehole-pubg/steam/2019/09/08/20/29/62a09051-d277-11e9-a33c-0a586469e71b-telemetry.json"
  }
}
```

| Field | Type | Notes |
|---|---|---|
| `URL` | string | **ALL-CAPS key.** Not `url`, not `Url`. Link to the telemetry JSON. |
| `createdAt` | string ISO-8601 | Time of telemetry creation — typically *later* than `match.attributes.createdAt` |
| `name` | string | `"telemetry"` (lowercase in real payloads, even though the schema description says "Telemetry") |
| `description` | string | always `""` |

Telemetry files are gzip-compressed (changelog v4.0.0); send `Accept-Encoding: gzip`.
Telemetry requests are not rate limited and need no auth.

---

## 7. Season / lifetime stats — `gameModeStats`

```
GET /shards/{platform}/players/{accountId}/seasons/{seasonId}          -> type "playerSeason"
GET /shards/{platform}/players/{accountId}/seasons/lifetime            -> type "lifetime"
GET /shards/{platform}/seasons/{seasonId}/gameMode/{gameMode}/players?filter[playerIds]=...   (batch, ≤10)
GET /shards/{platform}/seasons/lifetime/gameMode/{gameMode}/players?filter[playerIds]=...     (batch, ≤10)
```

### 7.1 Real response shape (verbatim, trimmed to one mode)

```json
{
  "data": {
    "type": "playerSeason",
    "attributes": {
      "bestRankPoint": 3356.1873,
      "gameModeStats": {
        "duo-fpp": {
          "assists": 58,
          "boosts": 230,
          "dBNOs": 265,
          "dailyKills": 4,
          "dailyWins": 0,
          "damageDealt": 52534.945,
          "days": 41,
          "headshotKills": 98,
          "heals": 308,
          "killPoints": 0,
          "kills": 362,
          "longestKill": 368.7044,
          "longestTimeSurvived": 1646.353,
          "losses": 298,
          "maxKillStreaks": 3,
          "mostSurvivalTime": 1646.353,
          "rankPoints": 3356.1873,
          "rankPointsTitle": "4-4",
          "revives": 51,
          "rideDistance": 49538.367,
          "roadKills": 0,
          "roundMostKills": 8,
          "roundsPlayed": 299,
          "suicides": 3,
          "swimDistance": 65.543144,
          "teamKills": 3,
          "timeSurvived": 109465.51,
          "top10s": 23,
          "vehicleDestroys": 2,
          "walkDistance": 131326.12,
          "weaponsAcquired": 849,
          "weeklyKills": 12,
          "weeklyWins": 0,
          "winPoints": 0,
          "wins": 1
        }
      }
    },
    "relationships": {
      "player": { "data": { "type": "player", "id": "account.d1c920088e124f2393455e05c11a8775" } },
      "season": { "data": { "type": "season", "id": "division.bro.official.pc-2018-04" } },
      "matchesSolo":    { "data": [ { "type": "match", "id": "..." } ] },
      "matchesSoloFPP": { "data": [] },
      "matchesDuo":     { "data": [] },
      "matchesDuoFPP":  { "data": [] },
      "matchesSquad":   { "data": [] },
      "matchesSquadFPP":{ "data": [] }
    }
  },
  "links": { "self": "https://api.pubg.com/shards/steam/players/account.d1c9.../seasons/division.bro.official.pc-2018-04" },
  "meta": {}
}
```

### 7.2 `gameModeStats` keys

Exactly **six**, confirmed both in the OpenAPI response schemas and in the real payload:
`solo`, `solo-fpp`, `duo`, `duo-fpp`, `squad`, `squad-fpp`.
Modes the player never played are present with all-zero objects (**not** omitted) — the real
fixture has `"duo": { ...all zeros..., "rankPointsTitle": "0" }`.

### 7.3 `gameModeStats` field table (35 fields)

| Field | Type | Meaning | Deprecated? |
|---|---|---|---|
| `assists` | integer | Enemies damaged that teammates killed | |
| `boosts` | integer | Boost items used | |
| `dBNOs` | integer | Enemies knocked | **note lowercase `d`** |
| `dailyKills` | integer | Kills during the most recent day played | |
| `dailyWins` | integer | Wins during the most recent day played | |
| `damageDealt` | number | Total damage (self-damage subtracted) | |
| `days` | integer | (undocumented description) days played | |
| `headshotKills` | integer | Headshot kills | |
| `heals` | integer | Healing items used | |
| `killPoints` | number | — | **deprecated** (v6.0.0 PC / v9.0.0 console) |
| `kills` | integer | Kills | |
| `longestKill` | number | Longest kill distance (m) | |
| `longestTimeSurvived` | number | Longest single-match survival (s) | |
| `losses` | integer | Matches lost | |
| `maxKillStreaks` | integer | Max kill streak | |
| `mostSurvivalTime` | number | Longest single-match survival (s) — duplicate of `longestTimeSurvived`; equal in the real fixture | |
| `rankPoints` | number | Rank points. Was forced to 0 when `roundsPlayed < 10` between v7.2.0 and v7.8.0 | **deprecated v20.0.0** |
| `rankPointsTitle` | **string** | Survival Title, format `"<titleNumber>-<level>"` (e.g. `"4-4"` = SKILLED level 4). `"0"` when unranked. | **deprecated v20.0.0** |
| `revives` | integer | Teammates revived | |
| `rideDistance` | number | Vehicle distance (m) | |
| `roadKills` | integer | Vehicle kills | |
| `roundMostKills` | integer | Most kills in one match | |
| `roundsPlayed` | integer | Matches played | |
| `suicides` | integer | Self-inflicted deaths | |
| `swimDistance` | number | Swim distance (m) | |
| `teamKills` | integer | Teammates killed | |
| `timeSurvived` | number | Total time survived (s) | |
| `top10s` | integer | Top-10 finishes | |
| `vehicleDestroys` | integer | Vehicles destroyed | |
| `walkDistance` | number | On-foot distance (m) | |
| `weaponsAcquired` | integer | Weapons picked up | |
| `weeklyKills` | integer | Kills in the most recent week played | |
| `weeklyWins` | integer | Wins in the most recent week played | |
| `winPoints` | number | — | **deprecated** |
| `wins` | integer | Matches won | |

`attributes.bestRankPoint` (number) sits **next to** `gameModeStats`, not inside it.
Added v14.0.0, **deprecated v20.0.0**. The per-mode `bestRankPoint` was *removed* in v14.0.0.

### 7.4 Survival Title numbers (for decoding `rankPointsTitle`)

From `survivalTitles.json`:

| Title | `titleNumber` | Levels |
|---|---|---|
| `UNKNOWN` | 0 | 0 |
| `BEGINNER` | 1 | 5,4,3,2,1 |
| `NOVICE` | 2 | 5,4,3,2,1 |
| `EXPERIENCED` | 3 | 5,4,3,2,1 |
| `SKILLED` | 4 | 5,4,3,2,1 |
| `SPECIALIST` | 5 | 5,4,3,2,1 |
| `EXPERT` | 6 | 0 |
| `SURVIVOR` | 7 | 0 |
| `LONE SURVIVOR` | 7 | 0 |

In `survivalTitles.json` these three top titles each carry a single-entry `levels` array with
`"level": 0` (EXPERT `survivalPoints` "5000-5999"; SURVIVOR "6000+", `demotion: false`;
LONE SURVIVOR "6000+", `demotion: true`), so they decode as `"6-0"` and `"7-0"` — a decoder must
not assume the level component is absent.

Note the collision: `SURVIVOR` and `LONE SURVIVOR` share `titleNumber` 7 **and** level 0; they
are distinguished only by `demotion`, so `"7-0"` is genuinely ambiguous between the two.

### 7.5 Season IDs

Format: `division.bro.official.pc-{YYYY}-{NN}` (PC),
`division.bro.official.playstation-{NN}`, `division.bro.official.xbox-{NN}`,
`division.bro.official.console-{NN}`; older seasons use `division.bro.official.{YYYY-MM}`.

First "lifetime" seasons per platform (`getting-started.rst`):
PC `division.bro.official.pc-2018-01`, PSN `division.bro.official.playstation-01`,
Xbox `division.bro.official.xbox-01`, Stadia `division.bro.official.console-07`.

⚠️ `api-assets/seasons.json` is **stale** — its newest entry is `division.bro.official.console-14`
(start 10-14-2021, end `00-00-0000`). Query `/seasons` at runtime instead; the docs ask that you
poll it no more than once a month.

Known issue: *"[PC] Data from seasons prior to `division.bro.official.2018-04` is unavailable."*

---

## 8. Ranked stats

```
GET /shards/{platform}/players/{accountId}/seasons/{seasonId}/ranked
```
Available from Season 7 onward. Requires an API key. **No match ID list is returned by this endpoint.**

### 8.1 Response shape (from the official 200-response schema)

```json
{
  "data": {
    "type": "rankedPlayerStats",
    "attributes": {
      "rankedGameModeStats": {
        "squad": { "...": "see table" },
        "squad-fpp": { "...": "see table" }
      }
    },
    "relationships": {
      "player": { "data": { "type": "player", "id": "account.xxxxxxxx" } },
      "season": { "data": { "type": "season", "id": "division.bro.official.pc-2018-01" } }
    }
  },
  "links": { "self": "https://api.pubg.com/shards/steam/players/.../seasons/.../ranked" },
  "meta": {}
}
```

The official `rankedstats-200.yml` documents **only `squad` and `squad-fpp`** as keys of
`rankedGameModeStats`. The Go wrapper models it as `map[string]rankedGameModeStats`, which is the
safer approach. ⚠️ Whether `solo-fpp` ever appears is unconfirmed — **parse it as a map**.

### 8.2 `rankedGameModeStats` field table

| Field | Type | Meaning | Deprecated (v20.1.0)? |
|---|---|---|---|
| `currentRankPoint` | integer | Current RP | |
| `bestRankPoint` | integer | Highest RP this season | |
| `currentTier` | object `{ tier, subTier }` | Current tier | |
| `bestTier` | object `{ tier, subTier }` | Best tier this season | |
| `roundsPlayed` | integer | Matches played | |
| `avgRank` | number | Average placement | |
| `top10Ratio` | number | Top-10 ratio | |
| `winRatio` | number | Win ratio | |
| `assists` | integer | Assists | |
| `wins` | integer | Wins | |
| `kda` | number | Kill/death/assist ratio | |
| `kills` | integer | Kills | |
| `deaths` | integer | Deaths | |
| `damageDealt` | number | Damage dealt | |
| `dBNOs` | integer | Knocks (**lowercase `d`**) | |
| `kdr` | number | Kill/death ratio | **deprecated** |
| `avgSurvivalTime` | number | Avg survival time | **deprecated** |
| `roundMostKills` | integer | Most kills in a match | **deprecated** |
| `longestKill` | number | Longest kill (m) | **deprecated** |
| `headshotKills` | integer | Headshot kills | **deprecated** |
| `headshotKillRatio` | number | Headshot kill ratio | **deprecated** |
| `reviveRatio` | number | Revive ratio | **deprecated** |
| `revives` | integer | Revives | **deprecated** |
| `heals` | integer | Heals | **deprecated** |
| `boosts` | integer | Boosts | **deprecated** |
| `weaponsAcquired` | integer | Weapons acquired | **deprecated** |
| `teamKills` | integer | Team kills | **deprecated** |
| `playTime` | number | Play time | **deprecated** |
| `killStreak` | integer | Highest kill streak (**singular**, unlike `maxKillStreaks` in season stats) | **deprecated** |

The `deprecated` marks come from the OpenAPI schema and are corroborated one-for-one by the
changelog v20.1.0 deprecation list. The Go wrapper `NovikovRoman/pubg` models only the
**non-deprecated** subset — a useful signal that the deprecated ones are unreliable/zero in practice.

### 8.3 `currentTier` / `bestTier`

```json
"currentTier": { "tier": "Platinum", "subTier": "3" }
```

| Field | Type | Notes |
|---|---|---|
| `tier` | **string** | Official schema: *"Player's current ranked tier"* |
| `subTier` | **string** | Official schema: *"Player's current ranked subtier"*. **A string, not an integer** — both the OpenAPI schema and the Go wrapper type it as `string`. |

⚠️ The **set of `tier` values and the exact casing are NOT documented anywhere official.** The
in-game ladder is Bronze → Silver → Gold → Platinum → Diamond → Master, with five sub-divisions
(V…I) below Master and no sub-divisions at Master. Treat `tier` and `subTier` as opaque strings.
See §14.

---

## 9. Weapon Mastery

```
GET /shards/{platform}/players/{accountId}/weapon_mastery
```

### 9.1 Real response (verbatim, trimmed to one weapon)

```json
{
  "data": {
    "type": "weaponMasterySummary",
    "id": "account.d1c920088e124f2393455e05c11a8775",
    "attributes": {
      "platform": "steam",
      "seasonId": "career",
      "weaponSummaries": {
        "Item_Weapon_AK47_C": {
          "XPTotal": 234845,
          "LevelCurrent": 35,
          "TierCurrent": 4,
          "StatsTotal": {
            "MostDefeatsInAGame": 5,
            "Defeats": 102,
            "MostDamagePlayerInAGame": 473.69485,
            "DamagePlayer": 10317.936,
            "MostHeadShotsInAGame": 3,
            "HeadShots": 51,
            "LongestDefeat": 82.40506,
            "LongRangeDefeats": 0,
            "Kills": 73,
            "MostKillsInAGame": 4,
            "Groggies": 61,
            "MostGroggiesInAGame": 4
          },
          "Medals": [
            { "MedalId": "MedalDoubleKill", "Count": 8 },
            { "MedalId": "MedalDeadeye", "Count": 35 },
            { "MedalId": "MedalAssassin", "Count": 19 }
          ]
        }
      },
      "latestMatchId": "3682bc1a-2bc1-4d14-8e27-fee9be24eb5e"
    }
  },
  "links": { "self": "https://api.pubg.com/shards/steam/players/account.d1c920088e124f2393455e05c11a8775/weapon_mastery" },
  "meta": {}
}
```

### 9.2 Envelope

| Path | Type | Notes |
|---|---|---|
| `data.type` | string | `"weaponMasterySummary"` |
| `data.id` | string | account ID |
| `attributes.platform` | string | e.g. `"steam"` |
| `attributes.seasonId` | string | **⚠️ Undocumented field** — present as `"career"` in the real response; not in `weaponMastery.yml` |
| `attributes.weaponSummaries` | object | **map keyed by weapon item ID** |
| `attributes.latestMatchId` | string | match ID of the last completed match |

### 9.3 `weaponSummaries` keys

Keys are telemetry **item IDs** of the form `Item_Weapon_<Name>_C`. The OpenAPI schema names the
placeholder `$Item_Weapon`; the changelog writes it as
`weaponMasterySummary.weaponSummaries.{Item_Weapon}.…`; the real response uses
`"Item_Weapon_AK47_C"`, `"Item_Weapon_AUG_C"`, etc.

The full item-ID vocabulary lives in
[`dictionaries/telemetry/item/itemId.json`](https://raw.githubusercontent.com/pubg/api-assets/master/dictionaries/telemetry/item/itemId.json)
(81 `Item_Weapon_*` entries at time of research). Samples:

| Key | Display name |
|---|---|
| `Item_Weapon_AK47_C` | AKM |
| `Item_Weapon_HK416_C` | M416 |
| `Item_Weapon_BerylM762_C` | Beryl |
| `Item_Weapon_AUG_C` | AUG A3 |
| `Item_Weapon_AWM_C` | AWM |
| `Item_Weapon_DP12_C` | DBS |
| `Item_Weapon_FNFal_C` | SLR |
| `Item_Weapon_Berreta686_C` | S686 |
| `Item_Weapon_Cowbar_C` | Crowbar *(official known-issue: this is a misspelling of "Crowbar")* |

⚠️ The set of weapons that actually earn mastery is a subset of the item dictionary (throwables,
drones, apples etc. are in `itemId.json` but almost certainly not in `weaponSummaries`).
**Treat `weaponSummaries` as an open map — never hardcode the key list.**

### 9.4 Per-weapon fields

| Field | Type | Notes |
|---|---|---|
| `XPTotal` | integer | Total mastery XP for this weapon |
| `LevelCurrent` | integer | Current mastery level |
| `TierCurrent` | integer | Current mastery tier |
| `StatsTotal` | object | **Legacy** stats. Changelog v22.0.0: contains pre-18.2-patch stats and **is no longer updated.** |
| `OfficialStatsTotal` | object | Stats from **Official** (public) matches, from patch 18.2 onward. Added v22.0.0. |
| `CompetitiveStatsTotal` | object | Stats from **Competitive / Ranked** matches, from patch 18.2 onward. Added v22.0.0. (The schema's description text is a copy-paste error saying "Official mode only".) |
| `Medals` | array of `{ MedalId, Count }` | **Deprecated v22.0.0** |

**All of these keys are PascalCase / SCREAMING-ish**, unlike the rest of the API which is
camelCase. `XPTotal` has an uppercase `XP`.

`StatsTotal` fields (12): `MostDefeatsInAGame`, `Defeats`, `MostDamagePlayerInAGame`,
`DamagePlayer`, `MostHeadShotsInAGame`, `HeadShots`, `LongestDefeat`, `LongRangeDefeats`,
`Kills`, `MostKillsInAGame`, `Groggies`, `MostGroggiesInAGame`.

`OfficialStatsTotal` / `CompetitiveStatsTotal` fields (8): `MostDefeatsInAGame`, `Defeats`,
`DamagePlayer`, `HeadShots`, `Kills`, `MostKillsInAGame`, `Groggies`, **`LongestKill`**.

⚠️ Note the asymmetry: the legacy block has `LongestDefeat`, `LongRangeDefeats`,
`MostDamagePlayerInAGame`, `MostHeadShotsInAGame`, `MostGroggiesInAGame`; the new blocks have
`LongestKill` instead of `LongestDefeat` and drop the other four. This is per the official schema.
The real response predates v22.0.0 so it only contains `StatsTotal` + `Medals` — the new blocks
were **not** observed live. See §14.

### 9.5 `MedalId` vocabulary (deprecated but still returned in the captured response)

From `dictionaries/weaponMastery/medalName.json`:

| `MedalId` | Name | Criterion |
|---|---|---|
| `MedalAnnihilation` | Annihilation | Defeat an entire squad by yourself |
| `MedalAssassin` | Assassin | Headshot kill without taking damage |
| `MedalDeadeye` | Deadeye | Headshot kill |
| `MedalDoubleKill` | Double Kill | 2 kills in rapid succession |
| `MedalFirstBlood` | First Blood | First kill of the match |
| `MedalFrenzy` | Frenzy | 5 kills with one weapon in a match |
| `MedalLastManStanding` | Last Man Standing | Kill the last opponent |
| `MedalLongshot` | Longshot | Kill from ≥ 200 m |
| `MedalPunisher` | Punisher | 300 damage with one weapon in a match |
| `MedalQuadKill` | Quad Kill | 4 kills in rapid succession |
| `MedalRampage` | Rampage | 10 kills with one weapon in a match |
| `MedalTripleKill` | Triple Kill | 3 kills in rapid succession |

---

## 10. Survival Mastery (bonus — same family of endpoints)

```
GET /shards/{platform}/players/{accountId}/survival_mastery
```

`data.type` = `"survivalMasterySummary"`, `data.id` = account ID.

`attributes`: `xp` (int), `tier` (int, added v22.0.2), `level` (int), `totalMatchesPlayed` (int),
`latestMatchId` (string), `stats` (object).

`attributes.stats` is a map of metric → `{ total, average, careerBest, lastMatchValue }`
(all `number`). Metrics:
`airDropsCalled`, `damageDealt`, `damageTaken`, `distanceBySwimming`, `distanceByVehicle`,
`distanceOnFoot`, `distanceTotal`, `healed`, `hotDropLandings` *(only `total`)*,
`enemyCratesLooted`, `position` *(no `total` — only `average`, `careerBest`, `lastMatchValue`)*,
`revived`, `teammatesRevived`, `timeSurvived`, `throwablesThrown`, `top10` *(only `total`)*.

⚠️ The three metrics with reduced sub-field sets (`hotDropLandings`, `position`, `top10`) come
straight from the official schema and were not confirmed against a live response.

---

## 11. Suggested `participants` table

Direct 1:1 mapping of the current 23 stat fields plus linkage. All distances in metres, all times
in seconds.

```sql
CREATE TABLE participants (
  match_id           TEXT    NOT NULL,          -- data.id of the match
  participant_id     TEXT    NOT NULL,          -- included[].id (UUID, response-scoped only)
  roster_id          TEXT    NOT NULL,          -- resolved via roster.relationships.participants
  player_id          TEXT    NOT NULL,          -- stats.playerId  "account.<32hex>"  <-- real key
  player_name        TEXT    NOT NULL,          -- stats.name (snapshot at match time)
  shard_id           TEXT    NOT NULL,          -- attributes.shardId (per-player!)

  dbnos              INTEGER NOT NULL,          -- stats.DBNOs
  assists            INTEGER NOT NULL,
  boosts             INTEGER NOT NULL,
  damage_dealt       DOUBLE PRECISION NOT NULL,
  death_type         TEXT    NOT NULL,          -- alive|byplayer|byzone|suicide|logout
  headshot_kills     INTEGER NOT NULL,
  heals              INTEGER NOT NULL,
  kill_place         INTEGER NOT NULL,
  kill_streaks       INTEGER NOT NULL,
  kills              INTEGER NOT NULL,
  longest_kill       DOUBLE PRECISION NOT NULL,
  revives            INTEGER NOT NULL,
  ride_distance      DOUBLE PRECISION NOT NULL,
  road_kills         INTEGER NOT NULL,
  swim_distance      DOUBLE PRECISION NOT NULL,
  team_kills         INTEGER NOT NULL,
  time_survived      DOUBLE PRECISION NOT NULL,
  vehicle_destroys   INTEGER NOT NULL,
  walk_distance      DOUBLE PRECISION NOT NULL,
  weapons_acquired   INTEGER NOT NULL,
  win_place          INTEGER NOT NULL,

  PRIMARY KEY (match_id, player_id)             -- participant_id is NOT stable across refetches
);
```

Roster-level data worth denormalising onto the row: `roster_rank` (= `winPlace`),
`roster_team_id`, `roster_won` (BOOLEAN, parsed from the string).

---

## 12. Implementation notes — gotchas that will silently break a parser

**Casing traps**

1. `participant.attributes.stats.DBNOs` — capital `DBNO`, lowercase `s`.
   But `gameModeStats.dBNOs` and `rankedGameModeStats.dBNOs` — **lowercase `d`**.
   Same concept, two spellings, two different endpoints. This is the #1 casing trap.
2. `asset.attributes.URL` — **all caps**, not `url`.
3. Weapon-mastery keys are PascalCase (`XPTotal`, `LevelCurrent`, `StatsTotal`, `MedalId`,
   `HeadShots` with a capital `S`) inside an otherwise camelCase API.
4. `matchesSoloFPP` / `matchesDuoFPP` / `matchesSquadFPP` relationship keys use uppercase `FPP`,
   while `gameModeStats` keys use lowercase hyphenated `solo-fpp`.
5. `rankedGameModeStats.killStreak` is **singular**; `gameModeStats.maxKillStreaks` is plural.

**Type traps**

6. **`roster.attributes.won` is the STRING `"true"` / `"false"`, not a boolean.**
   `if (roster.attributes.won)` is always truthy. Compare to `"true"`.
7. `currentTier.subTier` is a **string** (`"3"`), not an integer.
8. `gameModeStats.rankPointsTitle` is a **string** (`"4-4"`, or `"0"` when unranked), not a number.
9. `longestKill` and `timeSurvived` were integers before changelog v2.0.0 and are floats now —
   use float columns.
10. `match.attributes.stats` and `match.attributes.tags` are **`null`**, not `{}`. Naive
    `payload.attributes.stats.foo` access crashes.
11. `roster.relationships.team.data` is **`null`**.

**Shape traps**

12. `included` is a flat heterogeneous array — always filter by `type` before casting.
13. `participant.id` / `roster.id` are *randomly generated per response* (both official schemas say
    so explicitly). Key your rows on `(matchId, playerId)`, never on `participant.id` across
    refetches.
14. Participants carry **no team ID**. The only participant→team linkage is
    `roster.relationships.participants.data[]`. If you drop rosters you lose teams permanently.
15. `match.relationships.rounds` and `.spectators` existed in 2018 payloads (always
    `{"data": []}`) and are **absent** in 2019+ payloads. Don't require them.
16. `match.attributes.patchVersion` is in the OpenAPI schema but **absent** from the 2019 and 2020
    real payloads. Don't require it.
17. `assets.data` had exactly one element in every captured payload, but the schema types it as an
    array. Index defensively.
18. `links.self` on a match points at `api-origin.playbattlegrounds.com` (an internal host) in real
    responses. Never follow it.

**Semantic traps**

19. `killPlace` is a *kill-count rank*, `winPlace` is the *placement*. They are unrelated numbers
    and both are 1..130.
20. `damageDealt` **subtracts self-inflicted damage** — it can be lower than the sum of
    `LogPlayerTakeDamage` telemetry events.
21. `createdAt` on the match is the **API-ingest time**, not the match start. To order matches use
    it anyway (it's all you have), but don't present it as "match start".
22. Official known issue (section heading: *'Inaccurate Values for "swimDistance", "rideDistance",
    and "walkDistance" in the participant object'*): *"Players may sometimes have different values
    for distances in participant.attributes.stats than in the `GameResult` object. In this case,
    `GameResult` should be considered as having the accurate values."* `GameResult` lives in telemetry
    (`LogPlayerKillV2.victimGameResult`, `LogMatchEnd.results.gameResultOnFinished`).
23. `killStreaks` **was always 0** until changelog v20.3.0. Don't build historical comparisons
    across that boundary.
24. `deathType: "byzone"` only exists from v13.0.0; earlier matches report zone deaths as
    `byplayer`.
25. `Range_Main` (Camp Jackal / training) matches should generally be excluded from stats —
    pubg.sh's production ingester does exactly this (`AND m.map_name <> 'Range_Main'`).
26. pubg.sh's production ingester also drops matches with `duration > 10000` seconds as corrupt.
    Worth copying.
27. Both `Erangel_Main` and `Baltic_Main` mean "Erangel". Modern matches use `Baltic_Main`.

**Operational traps**

28. `/matches/{id}` needs **no auth and is not rate limited**, but it **is shard-scoped** — the same
    ID on the wrong shard returns 404, not a redirect. Always carry the shard alongside the match ID.
29. 14-day retention. Backfill is impossible; ingest continuously or lose the data.
30. Season-stats responses cap the returned match ID lists at **32** (⚠️ scope disputed — see
    §14 item 19: `getting-started.rst` says 32 *per player*, the OpenAPI response says the lists are
    "separated by game mode"); `/players` match lists cap at 14 days of history. Custom matches never appear in either list.
31. Console players may need the `console` shard (rather than `psn`/`xbox`) for `/matches`; on
    cross-play matches `participant.attributes.shardId` identifies each player's real platform.
32. Stadia keyboard/mouse vs gamepad stats are separate: use the `console` shard, or the
    `filter[gamepad]=true` filter on the `stadia` shard. Verbatim (`making-requests.rst`,
    `.. _gamepadFilter:`): *"Gamepad stats can be queried for by using the `console` shard, or by
    using the gamepad filter with the `stadia` shard. When querying for these stats, $isGamepad
    should have the value `true`. This filter should be omitted otherwise."* The parameter key is
    `gamepad`; `$isGamepad` is the placeholder for the **value**. `filter[isGamepad]` is
    unrecognised and silently returns keyboard/mouse stats.
33. `matchType` gained `airoyale` and `seasonal` in v21.2.0 and has at least one undocumented value
    (`competitive`). `gameMode` gained whole families in v11.0.0. **Never use a DB enum or a
    `CHECK` constraint on either — store TEXT and map in the app layer.**

---

## 13. Changelog entries that matter for this schema (condensed, verbatim-sourced)

| Version | Change |
|---|---|
| v22.1.0 | Clans endpoint; `ClanID` added to player object |
| v22.0.3 | **Tournaments endpoint and matches removed** |
| v22.0.2 | `tier` added to survival mastery |
| v22.0.1 | ban type added to player object |
| v22.0.0 | `weaponSummaries.{Item_Weapon}.OfficialStatsTotal` and `.CompetitiveStatsTotal` added (from patch 18.2). `StatsTotal` frozen. `Medals` deprecated. |
| v21.2.0 | New `matchType` enums: `airoyale`, `seasonal` |
| v21.0.0 | `LogPlayerKill` removed (telemetry); fixed assist count mismatch vs. participant stats |
| v20.3.0 | **Fixed `participant.attributes.stats.killStreaks` always being 0** |
| v20.1.0 | Bulk deprecation of `rankedGameModeStats` fields (see §8.2) |
| v20.0.0 | Ranked stats endpoint added. Deprecated `gameModeStats.rankPoints`, `.rankPointsTitle`, and `playerSeason.attributes.bestRankPoint` |
| v17.1.0 | **`Match.attributes.matchType` introduced** |
| v15.3.1 | Fixed missing participants / missing matches (not retroactive) |
| v15.0.0 | `console` shard usable at `/matches`; player platform determinable from `participant.shardId` |
| v14.0.0 | Remastered Erangel is `Baltic_Main`; per-mode `bestRankPoint` removed, top-level added |
| v13.0.1 | Fixed "kill steal" inaccuracies in `participant.attributes.stats.kills` |
| v13.0.0 | `deathType` = `byzone` for red/blue-zone deaths (previously `byplayer`) |
| **v12.0.0** | **Removed from participant stats: `killPoints`, `killPointsDelta`, `lastKillPoints`, `lastWinPoints`, `mostDamage`, `rankPoints`, `winPoints`, `winPointsDelta`** |
| v11.0.0 | `gameMode` split `normal` into `normal/war/zombie/conquest/esports` families |
| v8.0.1 / v8.0.2 | Fixed `walkDistance`/`rideDistance`/`swimDistance` all being 0 |
| v7.8.0 | Fixed `roster.attributes.won` sometimes false for the winning team |
| v7.5.0 | Fixed `timeSurvived`/`duration` sometimes being a timestamp instead of seconds |
| v6.0.0 | `match.attributes.seasonState` added (PC) |
| v5.0.0 | Squad size + perspective appended to custom-match `gameMode` |
| v2.0.0 | `timeSurvived` and `longestKill` changed int → number |
| v1.3.0 | `isCustomMatch` added |
| v1.1.1 | `killStreaks` and `weaponsAcquired` populated correctly |

---

## 14. ⚠️ Unverified / needs live confirmation

Everything below could **not** be confirmed against an authoritative source during this pass.
Confirm each with one live API call before relying on it.

1. **`killPlacePoints` and `winPlacePoints` — believed NOT to exist.** No OpenAPI schema, no
   changelog entry, no real payload (2018, 2019, 2020), and zero global GitHub issue-search hits.
   Almost certainly a conflation with the Kaggle dataset. **Do not create columns for them** unless
   a live response proves otherwise.
2. **`rankPointsTitle` on the participant object — believed NOT to exist.** It is only ever
   documented under `playerSeason.attributes.gameModeStats.{gameMode}`.
3. **`matchType: "competitive"`** is confirmed only from a single real 2020-11-12 payload quoted in
   a third-party GitHub issue. It is absent from the official enum. Confirm it still appears on
   today's ranked matches.
4. **Whether the live API still returns exactly the 23 participant stat fields.** The definitive
   real payload used here is from 2019-09-08. No changelog entry between v12.0.0 and v22.1.0 adds
   or removes a participant stat field, so 23 should still be correct — but the newest *captured*
   payload is 6 years old. **Fetch one live match and diff the key set before finalising the DDL.**
5. **`match.attributes.patchVersion`** — in the schema, absent from the 2019 and 2020 payloads.
   Unknown whether it ever returns today.
6. **`match.attributes.tags`** — always `null` in all captured payloads. The schema types it as an
   object. What (if anything) populates it is unknown.
7. **`match.attributes.mapName` enum completeness.** The dictionary lists 12 maps and was current as
   of Rondo (`Neon_Main`). Any map added after that will not be in it. Treat as open text.
8. **`currentTier.tier` / `bestTier.tier` value vocabulary and casing.** No official enum exists. The
   in-game ladder is Bronze/Silver/Gold/Platinum/Diamond/Master, but the exact API strings
   (`"Master"` vs `"MASTER"`, whether an `"Unranked"` sentinel exists for `roundsPlayed < 10`, and
   what `subTier` is for Master) are unconfirmed.
9. **`rankedGameModeStats` key set.** The schema documents only `squad` and `squad-fpp`. Whether
   `solo-fpp` or others appear is unknown. Parse as a map.
10. **`weaponSummaries.{weapon}.OfficialStatsTotal` and `.CompetitiveStatsTotal`** are schema- and
    changelog-confirmed but were **not** present in the captured (pre-v22) real response. Their
    exact field sets (8 fields each, with `LongestKill` replacing `LongestDefeat`) come only from
    the OpenAPI schema.
11. **`weaponMastery.attributes.seasonId`** (value `"career"`) appears in the real response but in
    no schema. Unknown whether other values exist.
12. **The exact set of weapon IDs that appear as `weaponSummaries` keys.** Only a subset of
    `itemId.json` earns mastery.
13. **Survival Mastery metrics with reduced sub-field sets** (`hotDropLandings`, `top10` → `total`
    only; `position` → no `total`). Schema-only; not seen live.
14. **Whether `data.relationships.rounds` / `.spectators` can ever return non-empty.** Never observed.
15. **`meta`** — `{}` in every captured response; documented "N/A".
16. **Console/Kakao/Stadia payload differences.** All captured real match payloads are PC
    (`pc-na`, `pc-eu`, `steam`). Console-specific field presence/absence is unverified.
17. **Tournament shard behaviour.** `tournament` is still listed as a valid `/matches` shard in
    `matches.yml`, but the Tournaments endpoint itself was removed in v22.0.3. Whether tournament
    match IDs still resolve is unknown.
18. **`api-assets/seasons.json` currency** — last entry is from 2021. Use the live `/seasons`
    endpoint.
19. **Scope of the 32-match season-stats cap — official sources disagree.** 32 match IDs *per
    player* per season response (`getting-started.rst` line 122: *"A maximum of 32 match IDs per
    player will be in the response."*; `making-requests.rst` line 270 likewise has no per-mode
    qualifier). But `responses/playerSeason-200.yml` line 38 says *"Lists of up to the 32 most
    recent match IDs that this player played this season (within the last 14 days) separated by
    game mode"*, which leaves open whether the cap is 32 total or 32 per mode. That is a 6×
    difference for ingest sizing (32 vs up to 32 × 6 = 192). **Confirmation:** call
    `/players/{id}/seasons/{seasonId}` for an active multi-mode player and count the IDs in each
    `matchesSolo*`/`matchesDuo*`/`matchesSquad*` list — if more than one list is non-empty and the
    lists sum to well over 32, the cap is per mode.
