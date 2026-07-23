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
  /** Set only for players tracking was deliberately turned off for. */
  untrackedAt?: string | null
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

  /**
   * Σhits/Σshots — but **`shotsFired === 0` means "not reported", not
   * "fired nothing"**. PUBG populates `allWeaponStats` for a median of 2
   * accounts per match and for a tracked player in only 3 of 65 archived
   * matches, so this is almost always absent. Render it only when
   * `shotsFired > 0`; a headline 0% reads as a bug and is missing data.
   */
  accuracy: number
  shotsFired: number
  shotsHit: number
  /** Headshot kills over *raw* kills — both count bots, so the ratio is
   *  self-consistent. Always available. */
  headshotRate: number
  knocksHuman: number
  roadKills: number
  vehicleDestroys: number
  teamKills: number
  avgSurvivedS: number
  /** Numerically lowest placement, i.e. the best. */
  bestPlace: number
}

export interface PlacementBucket {
  label: string
  lo: number
  hi: number | null
  matches: number
}

export interface Nemesis {
  accountId: string
  name: string
  killedBy: number
  killed: number
  lastSeen: string | null
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
  knocks: number
  headshotKills: number
  /** Resolved through `participants` — bots kill often and have no player row. */
  killedBy: string | null
  killedByIsBot: boolean | null
  deathWeapon: string | null
  shotsFired: number | null
  shotsHit: number | null
  /** Lobby size, for rendering "#8 / 25" rather than a bare rank. */
  numStartTeams: number | null
}

/** One tracked player's result in a match — the feed's payload. */
export interface TrackedResult {
  accountId: string
  name: string
  teamId: number
  winPlace: number
  kills: number
  killsHuman: number | null
  knocks: number
  assists: number
  damageDealt: number
  timeSurvived: number
  deathType: string
  headshotKills: number
  shotsFired: number | null
  shotsHit: number | null
  killedBy: string | null
  killedByIsBot: boolean | null
  deathWeapon: string | null
}

/**
 * A match plus what the tracked players did in it.
 *
 * They are always on the same roster when they play together (verified across
 * the archive, 0 counterexamples), so one `winPlace` describes the row.
 */
export interface MatchFeedRow {
  matchId: string
  playedAt: string
  telemetryT0: string | null
  mapName: string
  mapDisplay: string
  gameMode: string
  matchType: string
  durationS: number
  hasReplay: boolean
  parsed: boolean
  weatherId: string | null
  botCount: number | null
  numStartPlayers: number | null
  numStartTeams: number | null
  teamSize: number | null
  winPlace: number | null
  won: boolean
  results: TrackedResult[]
}

/** One day's aggregate of a single metric. */
export interface TimeseriesPoint {
  /** ISO date, `YYYY-MM-DD`. */
  day: string
  matches: number
  value: number
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
  shotsFired: number | null
  shotsHit: number | null
  knocksHuman: number | null
  /** CENTIMETRES, origin top-left, y growing downward. **No y flip.** */
  landingX: number | null
  landingY: number | null
  deathX: number | null
  deathY: number | null
  diedAtS: number | null
  killerAccountId: string | null
  deathWeapon: string | null
  weaponsAcquired: number
  killStreaks: number
  roadKills: number
  vehicleDestroys: number
  teamKills: number
  swimDistance: number
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
  numStartPlayers: number | null
  numStartTeams: number | null
  cameraView: string | null
  rosters: RosterRow[]
}

export interface KillRow {
  seq: number
  tS: number
  victimAccountId: string
  victimName: string | null
  victimIsBot: boolean
  victimTeamId: number
  killerAccountId: string | null
  killerName: string | null
  killerIsBot: boolean | null
  killerTeamId: number | null
  weapon: string | null
  damageReason: string | null
  /** Null when the source was the -1 "not applicable" sentinel. */
  distanceM: number | null
  isSuicide: boolean
  isTeamKill: boolean
  /** CENTIMETRES. Killer coords are null for zone/fall/drown deaths. */
  victimX: number
  victimY: number
  killerX: number | null
  killerY: number | null
  /** Already-resolved display names. */
  assists: string[]
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

// ---------------------------------------------------------------------------
// overview — one request for the whole home page
// ---------------------------------------------------------------------------
export interface FormEntry {
  matchId: string
  playedAt: string
  winPlace: number
  numStartTeams: number | null
  kills: number
  mapDisplay: string
  gameMode: string
}

export interface PlayerSummary {
  card: PlayerCard
  /** Null when the player has no `official` matches — normal, not an error. */
  stats: PlayerStats | null
  /** Oldest first, so the strip reads left to right. */
  form: FormEntry[]
  /** The two trailing windows the trend arrows compare. Either may be null. */
  recent: PlayerStats | null
  previous: PlayerStats | null
}

export interface SessionSummary {
  matches: number
  startedAt: string
  endedAt: string
  bestPlace: number
  wins: number
  killsHuman: number
  damage: number
  spanS: number
}

export interface Overview {
  players: PlayerSummary[]
  matches: MatchFeedRow[]
  health: Health
  session: SessionSummary | null
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

// ---------------------------------------------------------------------------
// strategy
// ---------------------------------------------------------------------------

/**
 * Telemetry-derived behavior for one player in one match.
 *
 * Every metric is nullable, and null means "not measurable" (no landing, no
 * teammates, no fights, no circle) — it must never be treated as zero.
 */
export interface StrategyMetrics {
  blueS: number | null
  blueDamage: number | null
  rotateLagS: number | null
  teammateDistAvgCm: number | null
  teammateNearPct: number | null
  hotDropN: number | null
  firstEngageS: number | null
  dmgDealtEarly: number | null
  dmgTakenEarly: number | null
  firstWeaponS: number | null
  earlyPickupsN: number | null
}

export interface StrategyMatchRow extends StrategyMetrics {
  matchId: string
  playedAt: string
  mapName: string
  gameMode: string
  teamSize: number | null
  winPlace: number
  timeSurvived: number
  kills: number
  damageDealt: number
  rideDistance: number
  walkDistance: number
}

export interface SquadPlayerCohesion extends StrategyMetrics {
  accountId: string
  name: string
}

export interface SquadMatchRow {
  matchId: string
  playedAt: string
  mapName: string
  gameMode: string
  winPlace: number
  players: SquadPlayerCohesion[]
}

export interface MatchStrategyRow extends StrategyMetrics {
  accountId: string
  name: string
}
