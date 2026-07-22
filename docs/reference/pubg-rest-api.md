# PUBG REST API — Implementation Reference

Ground-truth reference for the PUBG public REST API, compiled from the official OpenAPI/Swagger source, the official reStructuredText docs, the official `api-assets` dictionaries, and real captured response payloads from open-source consumers.

**Verification standard used here:** every field name and casing below was taken from either (a) the official Swagger schema files, (b) a real captured JSON payload, or (c) both. Anything that could not be confirmed against a primary source is listed in [⚠️ Unverified / needs live confirmation](#️-unverified--needs-live-confirmation) and tagged inline. **No field name in this document was invented.**

---

## Sources

Every URL actually fetched while writing this doc:

**Official documentation — rendered**
- https://documentation.pubg.com/en/making-requests.html
- https://documentation.pubg.com/en/rate-limits.html (via raw source)
- https://chicken-dinner.readthedocs.io/en/latest/pubgapi/core.html

**Official documentation — raw source of truth (`pubg/api-documentation-content`, cloned at `master`)**
- https://github.com/pubg/api-documentation-content
- `rst/making-requests.rst`
- `rst/getting-started.rst`
- `rst/rate-limits.rst`
- `rst/api-keys.rst`
- `rst/known-issues.rst`
- `rst/usage.rst`
- `rst/changelog/changelog.rst`
- `swagger/en/{players,matches,seasons,lifetime,mastery,samples,status,leaderboards,tournaments,clans}.yml`
- `swagger/en/paths/*.yml`
- `swagger/en/parameters/*.yml`
- `swagger/en/schemas/*.yml`
- `swagger/en/responses/*.yml`
- https://github.com/pubg/api-documentation-content/issues/61 (X-RateLimit-Reset unit dispute)

**Official assets (`pubg/api-assets`)**
- https://raw.githubusercontent.com/pubg/api-assets/master/dictionaries/gameMode.json
- https://raw.githubusercontent.com/pubg/api-assets/master/dictionaries/telemetry/mapName.json
- https://raw.githubusercontent.com/pubg/api-assets/master/seasons.json
- https://raw.githubusercontent.com/pubg/api-assets/master/survivalTitles.json

**Real captured payloads (independent cross-check #1 — `ramonsaraiva/pubg-python` test fixtures)**
- https://raw.githubusercontent.com/ramonsaraiva/pubg-python/master/tests/players_response.json
- https://raw.githubusercontent.com/ramonsaraiva/pubg-python/master/tests/player_response.json
- https://raw.githubusercontent.com/ramonsaraiva/pubg-python/master/tests/match_response.json
- https://raw.githubusercontent.com/ramonsaraiva/pubg-python/master/tests/season_response.json
- https://raw.githubusercontent.com/ramonsaraiva/pubg-python/master/tests/season_playerid_response.json
- https://raw.githubusercontent.com/ramonsaraiva/pubg-python/master/tests/weapon_mastery_response.json
- https://raw.githubusercontent.com/ramonsaraiva/pubg-python/master/pubg_python/clients.py
- https://raw.githubusercontent.com/ramonsaraiva/pubg-python/master/pubg_python/exceptions.py
- https://raw.githubusercontent.com/ramonsaraiva/pubg-python/master/pubg_python/domain/base.py

**Independent cross-check #2 — Go client (`NovikovRoman/pubg`)**
- https://raw.githubusercontent.com/NovikovRoman/pubg/master/common_structs.go
- https://raw.githubusercontent.com/NovikovRoman/pubg/master/survival_mastery.go

**Independent cross-check #3 — JS client**
- https://pubg.js.org/Player.js.html

---

## 1. Base URL, shards, headers

### Base URL

```
https://api.pubg.com
```

Confirmed in `pubg_python/clients.py` (`BASE_URL = 'https://api.pubg.com/'`) and in every Swagger `servers:` block.

Most endpoints are sharded:

```
https://api.pubg.com/shards/{shard}/{endpoint}
```

Two endpoints are **not** sharded and sit at the root: `/status` and `/tournaments` (see [§9](#9-status-and-removed-endpoints)).

### Shard names

There are two families of shard. Official wording from `making-requests.rst`:

> **The platform shard should be used at all other endpoints that require a shard. The platform-region shard is deprecated.**

**Platform shards** (`shards/$platform`) — use these:

| Shard | Meaning | Notes |
|---|---|---|
| `steam` | Steam (PC) | The main PC shard |
| `kakao` | Kakao (PC, Korea) | |
| `psn` | PlayStation Network | |
| `xbox` | Xbox | |
| `stadia` | Stadia | ⚠️ Google Stadia shut down Jan 2023; shard still listed in docs |
| `console` | PSN + Xbox combined | Documented as "used for the /matches and /samples endpoints" |
| `tournament` | Tournaments | ⚠️ Changelog v22.0.3 says "Removed: Tournaments endpoint and matches" |

**Platform-region shards** (`shards/$platform-region`) — deprecated, only needed for historical season stats:

`pc-as`, `pc-eu`, `pc-jp`, `pc-kakao`, `pc-krjp`, `pc-na`, `pc-oc`, `pc-ru`, `pc-sa`, `pc-sea`, `pc-tournament`, `psn-as`, `psn-eu`, `psn-na`, `psn-oc`, `xbox-as`, `xbox-eu`, `xbox-na`, `xbox-oc`, `xbox-sa`

**When the platform-region shard is required** (verbatim from `making-requests.rst`):
- PC and PSN season stats for seasons **before and including** `division.bro.official.2018-09`
- Xbox season stats for seasons **before and including** `division.bro.official.2018-08`

For anything modern, use the platform shard.

### Required headers

| Header | Value | Required? |
|---|---|---|
| `Authorization` | `Bearer <api-key>` | Yes, except `/matches` and telemetry |
| `Accept` | `application/vnd.api+json` | Yes (`application/json` also accepted) |
| `Accept-Encoding` | `gzip` | Strongly recommended; **required in practice for telemetry** |

The API key is a JWT issued by the developer portal. From `api-keys.rst`:

> We require that a JSON Web Token JWT be sent along with requests via the `Authorization` header.

The server mirrors the requested format back in `Content-Type`.

```bash
curl -g "https://api.pubg.com/shards/steam/players?filter[playerNames]=chocoTaco" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Accept: application/vnd.api+json" \
  -H "Accept-Encoding: gzip"
```

> **`curl -g` is required.** The `filter[...]` bracket syntax is globbing metacharacter syntax to curl. Every official example that contains a `filter[...]` bracket uses `-g` (all 13 in `rst/getting-started.rst`); examples without brackets (`rst/making-requests.rst`, `rst/telemetry.rst`) do not.

**CORS** is supported (`Access-Control-Allow-Origin: *`), but do not ship your key client-side — `api-keys.rst` explicitly says "your API key should never be stored client side."

---

## 2. Rate limiting

From `rate-limits.rst`, verbatim:

> The default rate limit is 10 requests per minute for testing/development purposes. When you have exceeded the number of available requests you will receive an HTTP 429 error code (too many requests), but you should be able to make requests again within a minute.

| Header | Official description |
|---|---|
| `X-RateLimit-Limit` | *Request limit per day / per minute* |
| `X-RateLimit-Remaining` | *The number of requests left for the time window* |
| `X-RateLimit-Reset` | *The time that the rate limit will be reset, as a UNIX timestamp* |

HTTP headers are case-insensitive; `pubg-python` reads them as `X-Ratelimit-Limit` / `X-Ratelimit-Reset`. Use a case-insensitive lookup.

**Not rate limited** (this is the single most important architectural fact for a replay dashboard):

> Since the /matches and telemetry endpoints are not rate limited, the amount of rate limited requests a typical application needs to make to the API should be directly proportional to the number of users/players using it.
>
> **Any following requests to the /matches or telemetry endpoints will not count against the application's API key rate limit.**

Corroborated structurally: `swagger/en/paths/match.yml` declares only `200/401/404/415` — no `429`. (`paths/status.yml` and `paths/tournamentList.yml` also omit `429`, so absence of a `429` is suggestive rather than unique.) Also, `matches.yml` states "Authorization is not required for the /matches endpoint because it is not rate-limited."

**Practical budget:** each player lookup costs 1 request (`/players`) plus optionally 1 more (`/players/{id}/seasons/{seasonId}`). Fanning out to 100 matches for those players costs **zero** quota.

---

## 3. `GET /shards/{shard}/players`

### Request

```
GET /shards/{shard}/players?filter[playerNames]=name1,name2
GET /shards/{shard}/players?filter[playerIds]=account.xxx,account.yyy
```

| Parameter | Type | Notes |
|---|---|---|
| `filter[playerNames]` | CSV string | **Player names are case sensitive** (verbatim from the Swagger parameter description) |
| `filter[playerIds]` | CSV string | Account IDs, each prefixed `account.` |

**Batching limit: 10.** From `paths/players.yml`: *"Get a collection of up to 10 players."* And from `getting-started.rst`: *"You can search for up to 10 players at a time by separating their account IDs with commas."*

> **The two filters are mutually exclusive.** Verbatim from `paths/players.yml`:
> *"Note: Either filter[playerIds] or filter[playerNames] must be specified, but they cannot be used at the same time."*

There is also a single-player form: `GET /shards/{shard}/players/{accountId}`.

### Real response (trimmed, from `players_response.json`)

```json
{
  "data": [
    {
      "type": "player",
      "id": "account.d1c920088e124f2393455e05c11a8775",
      "attributes": {
        "name": "glmn",
        "stats": null,
        "titleId": "bluehole-pubg",
        "shardId": "steam",
        "createdAt": "2019-09-13T16:19:10Z",
        "updatedAt": "2019-09-13T16:19:10Z",
        "patchVersion": ""
      },
      "relationships": {
        "assets": { "data": [] },
        "matches": {
          "data": [
            { "type": "match", "id": "9675afb2-b8e4-4391-ae06-51410f0b0d01" },
            { "type": "match", "id": "61b1139a-c8cd-4609-b5b1-90e1d9bac474" }
          ]
        }
      },
      "links": {
        "schema": "",
        "self": "https://api.playbattlegrounds.com/shards/steam/players/account.d1c920088e124f2393455e05c11a8775"
      }
    }
  ],
  "links": {
    "self": "https://api.pubg.com/shards/steam/players?filter[playerNames]=chocoTaco,glmn"
  },
  "meta": {}
}
```

### Player object fields

| Field | Type | Meaning |
|---|---|---|
| `type` | string | Always `"player"` |
| `id` | string | Account ID, format `account.<32 hex chars>` |
| `attributes.name` | string | In-game name (IGN). Case sensitive |
| `attributes.shardId` | string | Platform shard |
| `attributes.titleId` | string | e.g. `"bluehole-pubg"` |
| `attributes.patchVersion` | string | Observed empty (`""`) in real payloads |
| `attributes.stats` | object\|null | Documented "N/A"; observed `null` |
| `attributes.createdAt` | string (ISO 8601) | **Deprecated** per Swagger |
| `attributes.updatedAt` | string (ISO 8601) | **Deprecated** per Swagger |
| `attributes.banType` | string | `Innocent`, `TemporaryBan`, `PermanentBan`. Added v22.0.1 — ⚠️ not present in the 2019 fixture |
| `attributes.clanId`(?) | string | ⚠️ **Key name unverified.** `schemas/player.yml` does not contain it; the only evidence is the v22.1.0 changelog prose "Add ClanID to player object". Could be `clanId`, `ClanID`, or `clanID` — probe a live player object |
| `relationships.matches.data[]` | array | `{ "type": "match", "id": "<uuid>" }` |
| `relationships.assets.data` | array | Observed always `[]` |
| `links.self` | string | ⚠️ Points at the legacy `api.playbattlegrounds.com` host |

### Match list ordering and size

- **Retention:** *"Match lists go back 14 days for the players endpoint"* (`making-requests.rst`). ⚠️ Custom-match exclusion is documented only for the **season stats** match list (`getting-started.rst`, section "Getting Player Season Stats": *"Custom matches and matches older than 14 days will not be available."*). Nothing in `rst/` or `swagger/` says custom matches are excluded from `/players` — assumed but not documented.
- **Size:** observed **119** and **300** matches for two players in one real response. The 32-match cap that appears in the docs applies to the **season stats** endpoint, *not* to `/players`. `300` looks like a hard cap. ⚠️ Cap not officially documented.
- **Ordering: newest-first.** ⚠️ **This is not stated anywhere in the official docs.** It is inferred from strong evidence in the real fixtures:
  - The match `f80126f4-…` (`createdAt` = `2019-09-08T19:58:52Z`, from `match_response.json`) sits at **index 20 of 119** in a match list whose player `updatedAt` is `2019-09-13`. Newest-first puts it ~5 days back — consistent. Oldest-first would place index 20/119 near the 14-day boundary (~Aug 31) — inconsistent with its actual `createdAt`.
  - `season_playerid_response.json` (captured later) contains the same ID sequence as `players_response.json` but with 9 additional matches **prepended**, exactly as newest-first ordering predicts.

  **Do not depend on this.** Fetch each match and sort by `data.attributes.createdAt` descending.

---

## 4. `GET /shards/{shard}/matches/{id}`

### Request

```
GET /shards/{shard}/matches/{matchId}
```

- **No `Authorization` required** — *"Authorization is not required for the /matches endpoint because it is not rate-limited."*
- **Not rate limited.** No `429` is declared for this path.
- **14-day retention.** *"The data retention period is 14 days. Match data older than 14 days will not be available."*
- Use the `tournament` shard for tournament matches (⚠️ but see the v22.0.3 removal note).

### Real response (heavily trimmed, from `match_response.json`)

```json
{
  "data": {
    "type": "match",
    "id": "f80126f4-9520-4c66-9198-57820d04bf00",
    "attributes": {
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
    },
    "relationships": {
      "rosters": {
        "data": [
          { "type": "roster", "id": "c218f901-c126-4294-9647-f36c4037f957" }
        ]
      },
      "assets": {
        "data": [
          { "type": "asset", "id": "62a09051-d277-11e9-a33c-0a586469e71b" }
        ]
      }
    },
    "links": {
      "self": "https://api.playbattlegrounds.com/shards/steam/matches/f80126f4-9520-4c66-9198-57820d04bf00",
      "schema": ""
    }
  },
  "included": [
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
    },
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
    },
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
  ],
  "links": {
    "self": "https://api-origin.playbattlegrounds.com/shards/steam/matches/f80126f4-9520-4c66-9198-57820d04bf00"
  },
  "meta": {}
}
```

### Match attributes

| Field | Type | Meaning |
|---|---|---|
| `createdAt` | string (ISO 8601) | Time the match object was stored in the API |
| `duration` | integer | Match length in **seconds** |
| `matchType` | string | See enum below |
| `gameMode` | string | See enum below |
| `mapName` | string | Internal map key, see enum below |
| `isCustomMatch` | boolean | True for custom matches |
| `seasonState` | string | `closed` \| `prepare` \| `progress` |
| `shardId` | string | Platform shard |
| `titleId` | string | e.g. `bluehole-pubg` |
| `patchVersion` | string | Documented "N/A" |
| `stats` | null | Documented "N/A"; observed `null` |
| `tags` | null | Documented "N/A"; observed `null` |

`matchType` enum: `airoyale`, `arcade`, `custom`, `event`, `official`, `seasonal`, `training`

### Finding the telemetry URL

```
data.relationships.assets.data[0].id
  -> find object in included[] where type == "asset" and id matches
  -> included[i].attributes.URL
```

> ### 🔴 Casing trap: the field is `URL`, fully uppercase.
> Not `url`, not `Url`. Confirmed in both `swagger/en/schemas/asset.yml` and the real captured payload.

`asset.attributes.name` is the lowercase string `"telemetry"` in both the official `rst/telemetry.rst` example and real payloads — these agree. (`schemas/asset.yml` declares no value; its `"Telemetry"` is the property's *description* text, not an example or enum.) Match case-insensitively anyway, or just take the sole asset.

The officially documented telemetry host is `telemetry-cdn.pubg.com` (`rst/telemetry.rst` shows both the asset `URL` and the `curl --compressed` download example on that host). `telemetry-cdn.playbattlegrounds.com` — the host in the 2019 fixture above and the only host in `pubg-python`'s hardcoded `TELEMETRY_HOSTS` allowlist — is a **legacy alias**; both currently resolve to the same CloudFront IPs. **Do not allowlist or string-match a fixed host**: take whatever host the asset's `attributes.URL` actually contains. Telemetry is gzip-encoded and requires no `Authorization`.

### Roster object

| Field | Type | Meaning |
|---|---|---|
| `id` | string (uuid) | Random, meaningful only inside this match response |
| `attributes.stats.rank` | integer | Roster placement in the match (1–130) |
| `attributes.stats.teamId` | integer | Arbitrary team ID |
| `attributes.won` | **string** | 🔴 `"true"` / `"false"` as a *string*, not a boolean |
| `attributes.shardId` | string | Platform shard |
| `relationships.participants.data[]` | array | Refs to participants in `included[]` |
| `relationships.team.data` | null | Observed always `null` |

### Participant stats

| Field | Type | Meaning |
|---|---|---|
| `DBNOs` | integer | 🔴 Knocks. All-caps prefix — not `dbnos`/`DBNOS`. In *season* stats the same concept is `dBNOs` |
| `assists` | integer | Enemies damaged that teammates killed |
| `boosts` | integer | Boost items used |
| `damageDealt` | number | Total damage; self-inflicted damage is subtracted |
| `deathType` | string | `alive` \| `byplayer` \| `byzone` \| `suicide` \| `logout` |
| `headshotKills` | integer | |
| `heals` | integer | Healing items used |
| `killPlace` | integer | Rank in match by kills |
| `killStreaks` | integer | |
| `kills` | integer | |
| `longestKill` | number | Metres |
| `name` | string | IGN |
| `playerId` | string | `account.…` |
| `revives` | integer | |
| `rideDistance` | number | Metres. ⚠️ See known-issues note below |
| `roadKills` | integer | |
| `swimDistance` | number | Metres. ⚠️ See known-issues note below |
| `teamKills` | integer | |
| `timeSurvived` | number | Seconds |
| `vehicleDestroys` | integer | |
| `walkDistance` | number | Metres. ⚠️ See known-issues note below |
| `weaponsAcquired` | integer | |
| `winPlace` | integer | Final placement (1–130) |
| `actor` | string | Sits on `attributes`, not `attributes.stats`. Observed `""` |
| `shardId` | string | Sits on `attributes`, not `attributes.stats` |

> **Official known issue:** *"Players may sometimes have different values for distances in participant.attributes.stats than in the GameResult object. In this case, GameResult should be considered as having the accurate values."* `GameResult` lives in telemetry at `LogPlayerKillV2.victimGameResult` and `LogMatchEnd.results.gameResultOnFinished`.

### `included[]` is interleaved

In the real payload of 118 entries (91 participants, 26 rosters, 1 asset) the types are **mixed in arbitrary order**:

```
[participant, participant, roster, participant, roster, participant, …]
```

Always filter by `type`. Never assume grouping, never index positionally. Build an `id -> object` map, then resolve `relationships` refs through it.

---

## 5. Seasons

### `GET /shards/{shard}/seasons`

> *"The list of seasons will only be changing about once every two months when a new season is added. Applications should not be querying for the list of seasons more than once per month."* — cache this aggressively.

```json
{
  "data": [
    {
      "type": "season",
      "id": "division.bro.official.2017-beta",
      "attributes": { "isCurrentSeason": false, "isOffseason": false }
    }
  ],
  "links": { "self": "https://api.pubg.com/shards/steam/seasons" },
  "meta": {}
}
```

Find the live season with `attributes.isCurrentSeason === true`.

**First Survival-Title season per platform** (the earliest season the modern platform shard supports):

| Platform | First season ID |
|---|---|
| PC | `division.bro.official.pc-2018-01` |
| PSN | `division.bro.official.playstation-01` |
| Xbox | `division.bro.official.xbox-01` |
| Stadia | `division.bro.official.console-07` |

### `GET /shards/{shard}/players/{accountId}/seasons/{seasonId}`

Returns `data.type === "playerSeason"`.

```json
{
  "data": {
    "type": "playerSeason",
    "attributes": {
      "bestRankPoint": 3356.1873,
      "gameModeStats": {
        "duo-fpp": {
          "assists": 58, "boosts": 230, "dBNOs": 265,
          "dailyKills": 4, "dailyWins": 0,
          "damageDealt": 52534.945, "days": 41,
          "headshotKills": 98, "heals": 308, "killPoints": 0,
          "kills": 362, "longestKill": 368.7044,
          "longestTimeSurvived": 1646.353, "losses": 298,
          "maxKillStreaks": 3, "mostSurvivalTime": 1646.353,
          "rankPoints": 3356.1873, "rankPointsTitle": "4-4",
          "revives": 51, "rideDistance": 49538.367, "roadKills": 0,
          "roundMostKills": 8, "roundsPlayed": 299, "suicides": 3,
          "swimDistance": 65.543144, "teamKills": 3,
          "timeSurvived": 109465.51, "top10s": 23,
          "vehicleDestroys": 2, "walkDistance": 131326.12,
          "weaponsAcquired": 849, "weeklyKills": 12, "weeklyWins": 0,
          "winPoints": 0, "wins": 1
        }
      }
    },
    "relationships": {
      "matchesSquad":    { "data": [] },
      "matchesSquadFPP": { "data": [ { "type": "match", "id": "efb4a27f-…" } ] },
      "matchesSolo":     { "data": [] },
      "matchesSoloFPP":  { "data": [] },
      "matchesDuo":      { "data": [] },
      "matchesDuoFPP":   { "data": [] },
      "season": { "data": { "type": "season", "id": "…" } },
      "player": { "data": { "type": "player", "id": "account.…" } }
    }
  },
  "links": { "self": "https://api.pubg.com/shards/steam/players/account.…/seasons/division.bro.official.pc-2018-04" },
  "meta": {}
}
```

> 🔴 `data` on `playerSeason` has **no `id` field** (confirmed against the real payload). Only `type`, `attributes`, `relationships`.

> 🔴 Match-list relationship keys are camelCase with **uppercase `FPP`**: `matchesSolo`, `matchesSoloFPP`, `matchesDuo`, `matchesDuoFPP`, `matchesSquad`, `matchesSquadFPP`. These do **not** match the `gameModeStats` keys, which are hyphenated lowercase (`solo`, `solo-fpp`, `duo`, `duo-fpp`, `squad`, `squad-fpp`). You need a mapping table between the two.

> ⚠️ Docs state a maximum of **32 match IDs per player** (`getting-started.rst`; `making-requests.rst` "Data Retention Period"). But the real fixture holds 32 in `matchesSquadFPP` alone plus 27 more across other modes (25 duo-fpp, 2 solo-fpp = 59 total), so the cap appears to be **per game mode** in practice. Documented wording and observed behaviour disagree — do not rely on either number. Empty array if none.

`gameModeStats` fields are documented in `schemas/gameModeStats.yml`. Deprecated members: `killPoints`, `winPoints`, `rankPoints`, `rankPointsTitle`.

### `GET /shards/{shard}/players/{accountId}/seasons/lifetime`

Same shape; `data.type` is `"lifetime"` and the `season` relationship carries `id: "lifetime"`. Lifetime data begins at each platform's first Survival-Title season (table above), **not** at account creation.

### Batch season / lifetime stats (10 players)

```
GET /shards/{shard}/seasons/{seasonId}/gameMode/{gameMode}/players?filter[playerIds]=id1,id2
GET /shards/{shard}/seasons/lifetime/gameMode/{gameMode}/players?filter[playerIds]=id1,id2
```

`{gameMode}` path enum: `solo`, `solo-fpp`, `duo`, `duo-fpp`, `squad`, `squad-fpp`. Only the requested mode is populated; all other mode arrays come back empty.

### `GET /shards/{shard}/players/{accountId}/seasons/{seasonId}/ranked`

Ranked stats exist **from Season 7 onward**. **No match list is returned from this endpoint.**

Documented `data.type` is `rankedPlayerStats`; the changelog writes it `rankedplayerstats`. ⚠️ Casing unconfirmed — compare case-insensitively.

Only `squad` and `squad-fpp` are declared in the response schema.

```json
{
  "data": {
    "type": "rankedPlayerStats",
    "attributes": {
      "rankedGameModeStats": {
        "squad-fpp": {
          "currentRankPoint": 0,
          "bestRankPoint": 0,
          "currentTier": { "tier": "Platinum", "subTier": "4" },
          "bestTier":    { "tier": "Platinum", "subTier": "3" },
          "roundsPlayed": 0,
          "avgRank": 0, "top10Ratio": 0, "winRatio": 0,
          "assists": 0, "wins": 0, "kda": 0,
          "kills": 0, "deaths": 0,
          "damageDealt": 0, "dBNOs": 0
        }
      }
    },
    "relationships": {
      "player": { "data": { "type": "player", "id": "account.…" } },
      "season": { "data": { "type": "season", "id": "…" } }
    }
  }
}
```

⚠️ The `currentTier`/`bestTier` **values** above are illustrative — the exact tier/subTier string vocabulary is unconfirmed (see Unverified).

**Non-deprecated** ranked fields: `currentRankPoint`, `bestRankPoint`, `currentTier{tier,subTier}`, `bestTier{tier,subTier}`, `roundsPlayed`, `avgRank`, `top10Ratio`, `winRatio`, `assists`, `wins`, `kda`, `kills`, `deaths`, `damageDealt`, `dBNOs`.

**Deprecated** (present but do not build on them): `avgSurvivalTime`, `kdr`, `roundMostKills`, `longestKill`, `headshotKills`, `headshotKillRatio`, `reviveRatio`, `revives`, `heals`, `boosts`, `weaponsAcquired`, `teamKills`, `playTime`, `killStreak`.

---

## 6. Mastery endpoints

Platform enum for mastery includes `console` in addition to `kakao`, `psn`, `stadia`, `steam`, `xbox`. Both are rate limited.

### `GET /shards/{shard}/players/{accountId}/weapon_mastery`

Note the **snake_case** path segment.

```json
{
  "data": {
    "type": "weaponMasterySummary",
    "id": "account.d1c920088e124f2393455e05c11a8775",
    "attributes": {
      "platform": "steam",
      "seasonId": "…",
      "latestMatchId": "…",
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
          "Medals": [ { "MedalId": "MedalDoubleKill", "Count": 8 } ]
        }
      }
    }
  },
  "links": { "self": "…" },
  "meta": {}
}
```

> 🔴 `weaponSummaries` inner stat keys are **PascalCase** (`XPTotal`, `LevelCurrent`, `TierCurrent`, `StatsTotal`, `Kills`, `HeadShots`, `Groggies`) — the only place in the whole API that uses this convention. Everything else is camelCase.

> 🔴 `attributes.seasonId` is present in the real payload but **absent from the official Swagger schema**.

Since patch 18.2, three parallel stat blocks exist:

| Block | Meaning |
|---|---|
| `StatsTotal` | Pre-18.2 legacy totals. **Frozen — no longer updated** |
| `OfficialStatsTotal` | Official-mode stats, accumulating since 18.2 |
| `CompetitiveStatsTotal` | Competitive/ranked stats, accumulating since 18.2 |

`OfficialStatsTotal`/`CompetitiveStatsTotal` use `LongestKill` where `StatsTotal` uses `LongestDefeat`, and they omit `MostDamagePlayerInAGame`, `MostHeadShotsInAGame`, `LongRangeDefeats`. `Medals` is deprecated as of v22.0.0.

### `GET /shards/{shard}/players/{accountId}/survival_mastery`

`data.type` is `"survivalMasterySummary"`, `data.id` is the account ID.

```json
{
  "data": {
    "type": "survivalMasterySummary",
    "id": "account.…",
    "attributes": {
      "xp": 0,
      "tier": 0,
      "level": 0,
      "totalMatchesPlayed": 0,
      "latestMatchId": "…",
      "stats": {
        "damageDealt":  { "total": 0, "average": 0, "careerBest": 0, "lastMatchValue": 0 },
        "distanceTotal":{ "total": 0, "average": 0, "careerBest": 0, "lastMatchValue": 0 },
        "top10":        { "total": 0 }
      }
    }
  },
  "links": { "self": "…" },
  "meta": {}
}
```

> 🔴 **The official docs contradict themselves here.** `schemas/survivalMastery.yml` defines `stats` as an **object keyed by stat name**; `responses/survivalMastery-200.yml` defines it as an **array** of `{statid, total, average, careerBest, lastMatchValue}`. The object form is correct — independently confirmed by the Go client `NovikovRoman/pubg` (`survival_mastery.go`), which unmarshals `stats` as a struct with named keys.

Stat keys: `airDropsCalled`, `damageDealt`, `damageTaken`, `distanceBySwimming`, `distanceByVehicle`, `distanceOnFoot`, `distanceTotal`, `healed`, `hotDropLandings`, `enemyCratesLooted`, `position`, `revived`, `teammatesRevived`, `timeSurvived`, `throwablesThrown`, `top10`.

Each carries `total`, `average`, `careerBest`, `lastMatchValue` — **except** `hotDropLandings` and `top10`, which the schema gives **only `total`**, and `position`, which has **no `total`** (only `average`, `careerBest`, `lastMatchValue`). Treat every one of these as optional.

`attributes.tier` was added in v22.0.2.

---

## 7. Error responses

From `making-requests.rst`:

> Each response will contain at least one of the following top-level members:
> - `data` : the response's "primary data"
> - `errors` : an array of error objects

So the envelope is:

```json
{
  "errors": [
    { "title": "Not Found" }
  ]
}
```

Each error member carries `title` and `description`. ⚠️ Neither is declared `required:` in `responses/{notFound,unauthorized,unsupportedMediaType}.yml` — only `description` is annotated "(Optional)" in its own description text; `title` being required is an inference.

> ⚠️ Swagger internally contradicts itself on `title`: its description reads *"The HTTP status code applicable to this problem, expressed as a string value"* while the accompanying `example:` is a reason phrase (`"Not Found"`, `"Unauthorized"`, `"Unsupported media type"`). Treat `title` as **opaque** and switch on the HTTP status code instead.

| Status | Swagger `title` example | Meaning / cause |
|---|---|---|
| `401` | `Unauthorized` | API key invalid or missing |
| `404` | `Not Found` | Player/match/season doesn't exist on that shard, **or** match older than 14 days |
| `415` | `Unsupported media type` | `Accept` header wrong or absent |
| `429` | — | Rate limit exceeded. Swagger declares **no response body** for this case |

`403` is not in the Swagger spec but is used in practice for **expired telemetry** — `pubg-python` maps `403 -> OldTelemetryError`.

⚠️ The exact `{"errors":[…]}` wrapper is inferred from the documented top-level members; the Swagger error files describe only the shape of a *single* error member, not the envelope. Confirm against a live 404.

> **404 vs. empty result:** ⚠️ Swagger declares a `404` on `/players`, but whether a nonexistent name yields a `404` or a `200` with an empty `data` array is **not documented anywhere** (`rst/*.rst` never discusses 404 semantics) and was not tested. See Unverified. Handle both paths.

> If any requested player in a 10-name batch does not exist, ⚠️ it is unconfirmed whether the API returns 404 for the whole batch or silently omits that player. Test this before relying on batching for user-supplied names.

---

## 8. Enum reference

### `gameMode`

Path parameters accept only the six core modes. Match objects can return **any** of the following (from `api-assets/dictionaries/gameMode.json`, which is the authoritative and more current list):

| Value | Display | | Value | Display |
|---|---|---|---|---|
| `solo` | Solo TPP | | `normal-solo` | Solo TPP |
| `solo-fpp` | Solo FPP | | `normal-solo-fpp` | Solo FPP |
| `duo` | Duo TPP | | `normal-duo` | Duo TPP |
| `duo-fpp` | Duo FPP | | `normal-duo-fpp` | Duo FPP |
| `squad` | Squad TPP | | `normal-squad` | Squad TPP |
| `squad-fpp` | Squad FPP | | `normal-squad-fpp` | Squad FPP |
| `conquest-{solo,duo,squad}[-fpp]` | Conquest | | `war-{solo,duo,squad}[-fpp]` | War |
| `esports-{solo,duo,squad}[-fpp]` | Esports | | `zombie-{solo,duo,squad}[-fpp]` | Zombie |
| `lab-tpp` | Lab TPP | | `lab-fpp` | Lab FPP |
| `tdm` | Team Deathmatch | | | |

Treat `normal-*` as aliases of the base modes when aggregating.

### `mapName`

> 🔴 The Swagger `mapName` enum is **stale** — it lists only 7 maps and is missing 5 live ones. Use `api-assets/dictionaries/telemetry/mapName.json`:

| Key | Display name |
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

Map keys are **not** intuitive (`Baltic_Main` = Erangel Remastered, `Kiki_Main` = Deston, `Neon_Main` = Rondo). Always resolve through the dictionary and fail soft on unknown keys — new maps ship before docs update.

### Other enums

- `matchType`: `airoyale`, `arcade`, `custom`, `event`, `official`, `seasonal`, `training`
- `seasonState`: `closed`, `prepare`, `progress`
- `deathType`: `alive`, `byplayer`, `byzone`, `suicide`, `logout`
- `banType`: `Innocent`, `TemporaryBan`, `PermanentBan`

---

## 9. Status and removed endpoints

### `GET /status`

Unsharded, no auth. Returns `data.type = "status"`, `data.id = "pubg-api"`.

### Other sharded endpoints (not core to a replay dashboard)

| Endpoint | Notes |
|---|---|
| `GET /shards/{shard}/samples?filter[createdAt-start]=…` | Random match sample, refreshed every 24h. Shards: `steam`, `console`, `kakao`. Request time must be ≥24h in the past |
| `GET /shards/{platform-region}/leaderboards/{seasonId}/{gameMode}` | Top 500 per mode. Updated every 2h. ⚠️ `page[number]` is **deprecated since v20.0.0** (*"API responses will include the top 500 players for each leaderboard. The page filter is no longer necessary."*) — `paths/leaderboards.yml` declares only `seasonId` and `gameMode` and no longer wires the parameter in; the orphaned `parameters/pageNumber.yml` has `enum: [0, 1]` |
| `GET /shards/{shard}/clans/{clanId}` | Added v22.1.0. Returns `clanName`, `clanTag`, `clanLevel`, `clanMemberCount` |
| `GET /tournaments`, `GET /tournaments/{id}` | ⚠️ Changelog v22.0.3: **"Removed: Tournaments endpoint and matches"** — but the Swagger files and the `tournament` shard listing were never deleted |

---

## 10. Implementation notes — gotchas that will silently break a parser

**Casing traps**
1. **`asset.attributes.URL` is all-uppercase.** The single highest-value field for a replay dashboard, and the one most likely to be typed as `url`.
2. **`DBNOs` in participant stats vs. `dBNOs` in season/ranked stats.** Same concept, two different casings, in the same API. A shared TypeScript interface will silently produce `undefined`.
3. **Weapon mastery uses PascalCase** (`XPTotal`, `StatsTotal`, `Kills`) while the rest of the API is camelCase.
4. **`matchesSquadFPP`** — uppercase `FPP` in relationship keys, but `squad-fpp` (hyphenated lowercase) in `gameModeStats` keys.
5. Asset `attributes.name` is lowercase `"telemetry"` in both the official example and real payloads — the `"Telemetry"` in `schemas/asset.yml` is only the property's description text, not a value. Not a real conflict; still match case-insensitively.

**Type traps**
6. **`roster.attributes.won` is the string `"false"`, not a boolean.** `if (roster.attributes.won)` is always truthy. Compare to `"true"`.
7. `attributes.stats` and `attributes.tags` on match objects are `null`, not `{}`.
8. Survival mastery `stats` is an object keyed by name, despite one official file saying array.
9. `playerSeason` `data` has no `id` — a generic JSON:API deserializer that requires `id` will throw.

**Structural traps**
10. **`included[]` is interleaved, not grouped by type.** Filter by `type`; build an id→object map.
11. Attribute **key order is not stable** — it differed between two player objects in the same real response. Never parse positionally.
12. `links.self` values point at legacy hosts (`api.playbattlegrounds.com`, `api-origin.playbattlegrounds.com`), *not* `api.pubg.com`. Never follow them; construct URLs yourself.
13. Survival mastery stat entries have inconsistent members — `top10`/`hotDropLandings` carry only `total`, `position` has no `total`. Treat all four as optional.

**Behavioural traps**
14. **14-day retention is hard.** Matches and telemetry vanish. Persist anything you want to keep, at ingest time.
15. **`/matches` and telemetry are free** — no auth, no quota. Design your fan-out around this: spend quota only on `/players` and season stats.
16. **`curl -g`** / properly-encoded brackets, or the `filter[...]` params break.
17. **Player names are case sensitive** (documented verbatim in `parameters/filterPlayerNames.yml`). A user typing `chocotaco` will not match `chocoTaco`. Consider caching name→accountId and preferring `filter[playerIds]`.
18. ⚠️ Whether a nonexistent player yields a 404 or a `200` with empty `data` is undocumented and untested — handle both.
19. Batch in tens. Ten names is one request against a 10 req/min budget — the difference between 10 players/min and 100.
20. Cache `/seasons` for weeks; the docs explicitly ask for ≤1 request/month.
21. ⚠️ Custom matches are documented as absent from the **season stats** match list; the same for `/players` is assumed but undocumented.
22. Do not trust the Swagger `mapName` enum, or any enum, as closed. Fail soft on unknown values.
23. Telemetry responses are gzip — send `Accept-Encoding: gzip` and ensure your HTTP client decompresses (most do automatically).

---

## ⚠️ Unverified / needs live confirmation

Everything below could **not** be confirmed against an authoritative source. Verify each with a live API key before depending on it.

1. **Match list ordering is newest-first.** Strongly evidenced by two independent real fixtures (see §3), but **never stated in the official docs**. Mitigation: sort by `match.data.attributes.createdAt` descending yourself.
2. **Maximum match IDs returned by `/players`.** Observed 119 and 300 in real payloads; 300 is likely a cap but is undocumented. (The documented "32 most recent" applies to *season stats*, not `/players`.)
3. **Exact `data.type` casing for ranked stats** — Swagger says `rankedPlayerStats`, the changelog says `rankedplayerstats`. Compare case-insensitively.
4. **The `{"errors":[{"title":…}]}` envelope.** Inferred from the documented top-level `errors` member; the Swagger error files describe only a single error member's shape. No real captured error payload was found.
5. **429 response body.** Swagger declares the 429 response with no content schema at all. Unknown whether a body is returned.
6. **`X-RateLimit-Reset` units.** Current docs say "UNIX timestamp"; an earlier revision said *nanoseconds*, and [issue #61](https://github.com/pubg/api-documentation-content/issues/61) reports the arithmetic only works as *microseconds*. Probe the live header before doing math on it.
7. **Whether `X-RateLimit-Remaining` is actually emitted.** Documented, but `pubg-python` only ever reads `X-Ratelimit-Limit` and `X-Ratelimit-Reset`.
8. **`banType` and the clan-ID field on the player object.** `banType` *is* in `schemas/player.yml` (description "Innocent, TemporaryBan, PermanentBan"); it is only absent from the 2019-era fixture. The clan field is weaker: `schemas/player.yml` has **never** been updated to include it, a repo-wide grep finds `clanId` only as the `/clans/{clanId}` path parameter, and the sole textual evidence is the v22.1.0 changelog prose "Add ClanID to player object". **The exact key name is unverified** — probe a live player object before hardcoding `clanId` vs `ClanID` vs `clanID`.
9. **Ranked `tier` / `subTier` value vocabulary.** Both are typed `string`. Tier names are widely reported as Bronze/Silver/Gold/Platinum/Diamond/Master (+ Survivor historically), but whether `subTier` is `"1"`–`"5"` or `"I"`–`"V"`, and whether Master has a subTier at all, is unconfirmed. The illustrative values in §5 are **not** verified.
10. **Whether the `tournament` shard and `/tournaments` endpoints still function.** Changelog v22.0.3 says removed; the Swagger files and shard list still document them.
11. **Whether the `stadia` shard still functions.** Stadia shut down in January 2023; the shard remains in the docs.
12. **Batch behaviour with a nonexistent player.** Unknown whether one bad name 404s the whole batch or is silently omitted.
13. **Whether modern participant objects carry additional stat fields** beyond the 2019 fixture's set. The Swagger participant schema matches the fixture exactly, so probably not — but the docs lag reality elsewhere.
14. **Whether `/matches` truly requires no `Authorization` in production.** Stated twice in official docs and structurally corroborated, but not tested live here.
15. **Ranked stats game modes.** Only `squad` and `squad-fpp` appear in the response schema; whether solo ranked ever populates is unconfirmed.
16. **Exact `weaponSummaries` weapon-key vocabulary** (`Item_Weapon_*_C`) — sampled only (`Item_Weapon_AK47_C`, `Item_Weapon_AUG_C`, `Item_Weapon_AWM_C`), not enumerated. Note that `api-assets/dictionaries/weaponMastery/` contains **only** `medalName.json` — there is no official weapon-key dictionary there. The closest official list is `api-assets/dictionaries/telemetry/item/`. Enumerate the keys at runtime rather than hardcoding them.
17. **Telemetry host on live asset URLs.** Official docs use `telemetry-cdn.pubg.com`; the 2019 fixtures and `pubg-python`'s hardcoded allowlist use `telemetry-cdn.playbattlegrounds.com`. Both resolve to the same CloudFront IPs today, but which host live `attributes.URL` values carry was not observed here — confirm against a real match response once the API key is wired up. Never allowlist a fixed host regardless.
18. **Custom matches in the `/players` match list.** Documented as excluded only for the season-stats match list (`getting-started.rst`); unconfirmed for `/players`, where `schemas/player.yml` says only "a list of their recent matches (up to 14 days old)".
19. **Nonexistent player: 404 vs. `200` with empty `data`.** `rst/*.rst` never discusses 404 semantics and `responses/notFound.yml` is generic ("The specified resource was not found", declared on nearly every path). Untested for both the single-name and 10-name-batch cases (see also #12).
20. **Season-stats match cap: 32 per player or 32 per game mode.** Docs say per player; `season_playerid_response.json` shows 32 `matchesSquadFPP` + 25 `matchesDuoFPP` + 2 `matchesSoloFPP` = 59. Count a live response before relying on either number.
21. **Whether `title` is required in error members.** Not declared `required:` in any `responses/*.yml`, and its Swagger description ("the HTTP status code ... expressed as a string value") contradicts its own examples ("Not Found", "Unauthorized"). Switch on the HTTP status code, not on `title`.
