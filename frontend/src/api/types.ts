/** Wire types. These mirror `backend/pubg_dashboard/api/schemas.py`. */

export interface Health {
  db: boolean
  storage: boolean
  matches: number
  parsed: number
  queuePending: number
  queueFailed: number
  /** Seconds since the stalest tracked player was polled, or null if never. */
  pollerLagS: number | null
  parserVersion: number
}

export interface MapInfo {
  mapName: string
  display: string
  worldSize: number
  assetBase: string
  /** 8160/8192 on 816000-cm maps, 1 elsewhere. Never assume either. */
  imageScale: number
}

export interface TileInfo extends MapInfo {
  sourcePx: number
  tilePx: number
  maxZoom: number
  tiles: number
  tileUrl: string
  /** Differs ~4x between maps with identically sized source images. */
  pxPerMetre: number
}

export interface PlayerCard {
  accountId: string
  name: string
  shard: string
  tracked: boolean
  matches: number
  lastSeen: string | null
  lastPolledAt: string | null
  consecutivePollFailures: number
}

export interface PlayerStats {
  accountId: string
  name: string
  matches: number
  wins: number
  top10: number
  /** Raw API kills, bots included. */
  kills: number
  /** Kills against humans only — the default headline. */
  killsHuman: number
  knocks: number
  assists: number
  headshotKills: number
  revives: number
  damageDealt: number
  longestKillM: number
  avgDamage: number
  avgPlace: number
  kd: number
  kdHuman: number
  winRate: number
  timeSurvivedS: number
  walkDistanceM: number
  rideDistanceM: number
  includeBots: boolean
}

export interface MatchSummary {
  matchId: string
  playedAt: string
  mapName: string
  mapDisplay: string
  gameMode: string
  matchType: string
  durationS: number
  teamId: number
  winPlace: number
  rosterWon: boolean
  kills: number
  killsHuman: number | null
  assists: number
  damageDealt: number
  timeSurvived: number
  deathType: string
  hasReplay: boolean
}

export interface WeaponStat {
  weapon: string
  kills: number
  headshots: number
  longestM: number
  avgDistanceM: number
}

export interface ParticipantRow {
  accountId: string
  name: string
  teamId: number
  isBot: boolean
  kills: number
  killsHuman: number | null
  assists: number
  dbnos: number
  damageDealt: number
  headshotKills: number
  heals: number
  boosts: number
  revives: number
  longestKill: number
  timeSurvived: number
  walkDistance: number
  rideDistance: number
  winPlace: number
  deathType: string
  tracked: boolean
}

export interface RosterRow {
  teamId: number
  rank: number
  won: boolean
  participants: ParticipantRow[]
}

export interface MatchDetail {
  matchId: string
  shard: string
  playedAt: string
  /** The real match start. `playedAt` is the API's ingest time. */
  telemetryT0: string | null
  mapName: string
  mapDisplay: string
  worldSize: number
  gameMode: string
  matchType: string
  durationS: number
  teamSize: number | null
  weatherId: string | null
  isCustomMatch: boolean
  parsed: boolean
  hasReplay: boolean
  botCount: number | null
  rosters: RosterRow[]
}

export interface KillRow {
  seq: number
  tS: number
  victimAccountId: string
  victimName: string | null
  victimIsBot: boolean
  killerAccountId: string | null
  killerName: string | null
  weapon: string | null
  damageReason: string | null
  /** Null when the source was the -1 "not applicable" sentinel. */
  distanceM: number | null
  isSuicide: boolean
  isTeamKill: boolean
}

export interface Heatmap {
  mapName: string
  kind: string
  grid: number
  worldSize: number
  max: number
  total: number
  /** base64 little-endian Uint32Array[grid*grid], row-major (y*grid+x). */
  cells: string
}

export interface RecentMatch {
  matchId: string
  playedAt: string
  mapName: string
  mapDisplay: string
  gameMode: string
  matchType: string
  durationS: number
  hasReplay: boolean
}

export interface IngestStatus {
  queue: { kind: string; state: string; count: number }[]
  trackedPlayers: number
  matches: number
  unparsed: number
  oldestUnparsed: string | null
  pollerLagS: number | null
  rateLimitPerMin: number
}
