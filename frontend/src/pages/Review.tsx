import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { get } from '../api/client'
import { Link } from 'react-router'
import type {
  RangeBandRow,
  SessionRow,
  SquadDeaths,
  SquadEngagements,
  SquadReview,
} from '../api/types'
import { Place, Skeleton, Tile } from '../components/ui'
import { dateTime, num, weaponName } from '../lib/format'
import { rankFindings, rateText, squadFindings } from '../lib/findings'
import { caveat, engagementFindings } from '../lib/engagements'
import { circleSentence, deathFindings, replayLink, tagsFor } from '../lib/deaths'
import './Review.css'

/**
 * The retrospective: what happened in these games.
 *
 * The split against `/strategy` is deliberate — that page aggregates across
 * the whole archive to answer "what do we do differently when we place well".
 * This one is about specific evenings and specific deaths, and every row that
 * can point at a moment links into the replay at it.
 *
 * Nothing on this page computes a statistic. `/review/squad` returns counts
 * and `lib/findings.ts` turns them into sentences, so the arithmetic and the
 * wording rules are both hermetically testable and neither lives in JSX.
 */
export function Review() {
  const review = useQuery({
    queryKey: ['review', 'squad'],
    queryFn: () => get<SquadReview>('/review/squad'),
  })
  const sessions = useQuery({
    queryKey: ['review', 'sessions'],
    queryFn: () => get<SessionRow[]>('/review/sessions', { limit: 12 }),
  })
  const fights = useQuery({
    queryKey: ['review', 'engagements'],
    queryFn: () => get<SquadEngagements>('/review/engagements'),
  })
  const deaths = useQuery({
    queryKey: ['review', 'deaths'],
    queryFn: () => get<SquadDeaths>('/review/deaths', { limit: 40 }),
  })

  // Fight findings are ranked **beside** the squad ones rather than mixed into
  // them. They are claims about a modelled grouping, and interleaving the two
  // lists would put a sentence whose denominator is a judgement call directly
  // above one whose denominator is a count of deaths, with nothing to tell
  // them apart.
  const findings = useMemo(
    () => (review.data ? rankFindings(squadFindings(review.data)) : []),
    [review.data],
  )
  const fightFindings = useMemo(
    () => (fights.data ? rankFindings(engagementFindings(fights.data)) : []),
    [fights.data],
  )
  const deathList = useMemo(
    () => (deaths.data ? rankFindings(deathFindings(deaths.data)) : []),
    [deaths.data],
  )

  if (review.isError) {
    return (
      <div className="review">
        <h1>Review</h1>
        <div className="notice">
          could not load the squad review: {(review.error as Error).message}
        </div>
      </div>
    )
  }

  return (
    <div className="review">
      <h1>Review</h1>

      {review.isLoading ? (
        <Skeleton h={220} />
      ) : review.data ? (
        <>
          <Findings findings={findings} review={review.data} />
          <Sessions rows={sessions.data} loading={sessions.isLoading} />
          <Deaths review={review.data} />
          <EveryDeath data={deaths.data} findings={deathList} loading={deaths.isLoading} />
          <Fights data={fights.data} findings={fightFindings} loading={fights.isLoading} />
          <Ranges bands={review.data.rangeBands} />
          <FirstDown review={review.data} />
        </>
      ) : null}
    </div>
  )
}

// ---------------------------------------------------------------------------

function Findings({
  findings,
  review,
}: {
  findings: ReturnType<typeof rankFindings>
  review: SquadReview
}) {
  return (
    <section>
      <h2>What the archive says</h2>
      <p className="faint note">
        {review.matches} official matches, {review.deaths} deaths. Ordering is by
        effect size on samples this small, so the order is a browsing aid rather
        than a ranking — read the counts, not the position.
      </p>
      {findings.length === 0 ? (
        <div className="empty">not enough matches yet to say anything</div>
      ) : (
        <ul className="findings">
          {findings.map((f) => (
            <li key={f.id} className={`finding ${f.tone}`}>
              {f.text}
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

// ---------------------------------------------------------------------------

function Sessions({ rows, loading }: { rows: SessionRow[] | undefined; loading: boolean }) {
  if (loading) return <Skeleton h={160} />
  if (!rows || rows.length === 0) return null

  return (
    <section>
      <h2>Sessions</h2>
      <p className="faint note">
        A run of matches less than three hours apart — an evening that crosses
        midnight is one session, not two.
      </p>
      <table className="sessions">
        <thead>
          <tr>
            <th>When</th>
            <th className="r">Matches</th>
            <th className="r">Best</th>
            <th className="r">Top 10</th>
            <th className="r">Kills</th>
            <th className="r">Damage</th>
            <th>Placements</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((s) => (
            <tr key={s.startedAt}>
              <td>{dateTime(s.startedAt)}</td>
              <td className="r num">{s.matches}</td>
              <td className="r">
                <Place place={s.bestPlace} />
              </td>
              <td className="r num">
                {s.top10}
                <span className="faint"> / {s.matches}</span>
              </td>
              <td className="r num">{s.kills}</td>
              <td className="r num">{num(s.damage)}</td>
              <td>
                <div className="places">
                  {s.places.map((p, i) => (
                    // eslint-disable-next-line react/no-array-index-key
                    <Place key={`${s.startedAt}-${i}`} place={p} />
                  ))}
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  )
}

// ---------------------------------------------------------------------------

function Deaths({ review }: { review: SquadReview }) {
  const { deaths, deathCauses, zoneDeaths } = review
  if (deaths === 0) return null

  return (
    <section>
      <h2>How we die</h2>
      <p className="faint note">
        Shares of {deaths} deaths. <strong>These overlap</strong> — a death can
        be third-partied, early, and finished from a knock all at once. Only
        “knocked, then finished” and “killed outright” partition the total.
      </p>
      <div className="tiles">
        {deathCauses.map((c) => (
          <Tile
            key={c.cause}
            label={c.label}
            value={`${Math.round((c.n / deaths) * 100)}%`}
            sub={`${c.n} of ${deaths}`}
          />
        ))}
      </div>
      <p className="faint note">
        Blue zone: {zoneDeaths} of {deaths}. Too few to be a category, so it is
        a count rather than a tile.
      </p>
    </section>
  )
}

// ---------------------------------------------------------------------------

/**
 * Every death, with a link into the replay fifteen seconds before it.
 *
 * This is the first thing in the app to produce `?follow=`. `pages/Replay.tsx`
 * has parsed it since the replay shipped and nothing ever generated one, so
 * the only way to watch a specific player was to open the replay and find them
 * by hand.
 *
 * The circle comparison sits above the list rather than as a column, because
 * it is not a property of any individual death — it is the reason there is no
 * "caught out of position" column at all.
 */
function EveryDeath({
  data,
  findings,
  loading,
}: {
  data: SquadDeaths | undefined
  findings: ReturnType<typeof rankFindings>
  loading: boolean
}) {
  if (loading) return <Skeleton h={240} />
  if (!data || data.deaths === 0) return null

  const circle = circleSentence(data.circle)

  return (
    <section className="every-death">
      <h2>Every death</h2>
      <p className="faint note">
        {data.deaths} deaths, newest first. Each row opens the replay 15 seconds
        before it, following that player. Tags overlap — a death can be
        third-partied, isolated and knocked-first at once.
      </p>

      {findings.length > 0 && (
        <ul className="findings">
          {findings.map((f) => (
            <li key={f.id} className={`finding ${f.tone}`}>
              {f.text}
            </li>
          ))}
        </ul>
      )}

      {circle && (
        <p className={`compare ${circle.different ? 'differs' : ''}`}>
          {circle.text}
        </p>
      )}

      <table className="death-list">
        <thead>
          <tr>
            <th>When</th>
            <th>Who</th>
            <th className="r">At</th>
            <th>Killed by</th>
            <th className="r">Range</th>
            <th className="r">Dealt</th>
            <th className="r">Took</th>
            <th>Tags</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {data.rows.map((r) => {
            const tags = tagsFor(r)
            return (
              <tr key={`${r.matchId}-${r.seq}`}>
                <td>{dateTime(r.playedAt)}</td>
                <td className="name">{r.name}</td>
                <td className="r num">{clock(r.tS)}</td>
                <td className="name">{r.killerName ?? '—'}</td>
                <td className="r num">
                  {/* Null, not zero: -1 is PUBG's "not applicable" sentinel
                      and a melee kill is not a point-blank shot. */}
                  {r.distanceM === null ? '—' : `${Math.round(r.distanceM)} m`}
                </td>
                <td className="r num">
                  {r.damageDealt === null ? '—' : Math.round(r.damageDealt)}
                </td>
                <td className="r num">
                  {r.damageTaken === null ? '—' : Math.round(r.damageTaken)}
                </td>
                <td>
                  <div className="tags">
                    {tags.map((t) => (
                      <span key={t} className="tag">
                        {t}
                      </span>
                    ))}
                    {r.weapon && <span className="tag weapon">{weaponName(r.weapon)}</span>}
                  </div>
                </td>
                <td>
                  <Link className="watch" to={replayLink(r)}>
                    watch
                  </Link>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>

      <p className="faint note">
        Footnotes, both too thin to be categories: {data.inVehicle} deaths in a
        vehicle, {data.outsideAnyFight} with no attributable exchange behind
        them.
      </p>
    </section>
  )
}

/** `mm:ss` from the match clock. */
function clock(t: number): string {
  const s = Math.max(0, Math.round(t))
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}

// ---------------------------------------------------------------------------

/**
 * Fights — the one section on this page built on a modelled quantity.
 *
 * The choice is spelled out **once at the top in its own block**, and carried
 * into each sentence as a short parenthetical by `engagements.ts`. That
 * duplication is deliberate — a reader who scrolls straight to a number still
 * gets told the fight count came from cutting the stream at a silence somebody
 * picked — but the inline form is terse on purpose. The first draft repeated
 * the whole clause five times and buried the findings under the disclaimer,
 * which is its own kind of dishonesty: a caveat nobody finishes reading is not
 * a caveat.
 */
function Fights({
  data,
  findings,
  loading,
}: {
  data: SquadEngagements | undefined
  findings: ReturnType<typeof rankFindings>
  loading: boolean
}) {
  if (loading) return <Skeleton h={220} />
  if (!data || data.fights === 0) return null

  const undecided = data.fights - data.decided

  return (
    <section className="fights">
      <h2>Fights</h2>
      <div className="modelled">
        <strong>These rows are a model, not a measurement.</strong> PUBG records
        hits, knocks and deaths; it does not record fights. Everything here
        comes from grouping cross-team blows that are less than{' '}
        {data.gapSeconds} seconds apart into one exchange — and sweeping that
        threshold from 5 to 120 seconds moves the count smoothly with no natural
        boundary anywhere, so {data.gapSeconds} seconds is a choice. The per-side
        kill and damage figures are exact <em>given</em> that grouping.
      </div>

      <div className="tiles">
        <Tile label="exchanges" value={num(data.fights)} sub={`over ${data.matches} matches`} />
        <Tile
          label="somebody died"
          value={num(data.decided)}
          sub={`${num(undecided)} ended with nobody down`}
        />
        <Tile
          label="you landed the first blow"
          value={rateText(data.firstHitOurs) ?? '—'}
          sub="of the fights someone died in"
        />
        <Tile
          label="a third team was there"
          value={rateText(data.thirdParty) ?? '—'}
          sub={`another fight within ${data.thirdPartyRadiusM} m at the same time`}
        />
      </div>

      {findings.length > 0 && (
        <ul className="findings">
          {findings.map((f) => (
            <li key={f.id} className={`finding ${f.tone}`}>
              {f.text}
            </li>
          ))}
        </ul>
      )}

      <h3>How they end</h3>
      <p className="faint note">
        Labelled by what the kill counts say, not by who won. A fight where you
        killed two and lost three to a third team is not obviously one you lost,
        so nothing here calls it that. Fights are {caveat(data.gapSeconds)}.
      </p>
      <div className="tiles">
        {data.results.map((r) => (
          <Tile
            key={r.key}
            label={r.label}
            value={`${Math.round((r.n / data.fights) * 100)}%`}
            sub={`${r.n} of ${data.fights}`}
          />
        ))}
      </div>

      <h3>Where they open</h3>
      <p className="faint note">
        By the range the <strong>first blow landed</strong> at — not the range
        anyone shot from. A shot that missed has no victim in the telemetry and
        so has no range at all, which is also why the side that landed first is
        not necessarily the side that fired first.
      </p>
      <table className="ranges">
        <thead>
          <tr>
            <th>Opening range</th>
            <th className="r">Fights</th>
            <th className="r">Kills</th>
            <th className="r">Deaths</th>
            <th className="r">Trade</th>
          </tr>
        </thead>
        <tbody>
          {data.rangeBands.map((b) => {
            const total = b.weKilled + b.weDied
            const ratio = total === 0 ? null : b.weKilled / total
            return (
              <tr key={b.loM}>
                <td>{b.hiM === null ? `${b.loM} m +` : `${b.loM}–${b.hiM} m`}</td>
                <td className="r num">{b.fights}</td>
                <td className="r num">{b.weKilled}</td>
                <td className="r num">{b.weDied}</td>
                <td className={`r num ${ratio === null ? '' : ratio >= 0.5 ? 'good' : 'bad'}`}>
                  {ratio === null || total < 8 ? '—' : `${Math.round(ratio * 100)}%`}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>

      {data.players.length > 0 && (
        <>
          <h3>The average fight, per player</h3>
          <p className="faint note">
            Damage taken is not recorded anywhere else in this app — the match
            API reports damage dealt, and a kill row only says who ended up
            dead. Taking more of it is what an entry fragger does on purpose, so
            these are a contrast, not a scoreboard.
          </p>
          <table className="fight-players">
            <thead>
              <tr>
                <th>Player</th>
                <th className="r">Fights</th>
                <th className="r">Damage dealt</th>
                <th className="r">Damage taken</th>
                <th className="r">Went down</th>
                <th className="r">Died</th>
              </tr>
            </thead>
            <tbody>
              {data.players.map((p) => (
                <tr key={p.accountId}>
                  <td className="name">{p.name}</td>
                  <td className="r num">{p.fights}</td>
                  <td className="r num">{Math.round(p.damageDealtAvg)}</td>
                  <td className="r num">{Math.round(p.damageTakenAvg)}</td>
                  <td className="r num">{rateText(p.knocked) ?? '—'}</td>
                  <td className="r num">{rateText(p.died) ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </section>
  )
}

// ---------------------------------------------------------------------------

function bandLabel(b: RangeBandRow): string {
  return b.hiM === null ? `${b.loM} m +` : `${b.loM}–${b.hiM} m`
}

function Ranges({ bands }: { bands: RangeBandRow[] }) {
  const max = Math.max(1, ...bands.map((b) => b.weKilled + b.weDied))
  return (
    <section>
      <h2>Where the fights happen</h2>
      <p className="faint note">
        Kills and deaths by distance. Kills carrying PUBG’s “not applicable”
        distance sentinel are excluded, so these sum to fewer than the raw kill
        count.
      </p>
      <table className="ranges">
        <thead>
          <tr>
            <th>Range</th>
            <th className="r">Kills</th>
            <th className="r">Deaths</th>
            <th className="r">Trade</th>
            <th>Volume</th>
          </tr>
        </thead>
        <tbody>
          {bands.map((b) => {
            const total = b.weKilled + b.weDied
            const ratio = total === 0 ? null : b.weKilled / total
            return (
              <tr key={b.loM}>
                <td>{bandLabel(b)}</td>
                <td className="r num">{b.weKilled}</td>
                <td className="r num">{b.weDied}</td>
                <td className={`r num ${ratio === null ? '' : ratio >= 0.5 ? 'good' : 'bad'}`}>
                  {/* A ratio over four events is noise; the count is the
                      honest answer there, so the percentage is withheld. */}
                  {ratio === null || total < 8 ? '—' : `${Math.round(ratio * 100)}%`}
                </td>
                <td>
                  <div className="vol-track">
                    <div className="vol-fill" style={{ width: `${(total / max) * 100}%` }} />
                    <span className="vol-n num">{total}</span>
                  </div>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </section>
  )
}

// ---------------------------------------------------------------------------

function FirstDown({ review }: { review: SquadReview }) {
  const rows = review.firstDeaths
  if (rows.length === 0) return null

  return (
    <section>
      <h2>Who goes down first</h2>
      <p className="faint note">
        Matches with at least two tracked players on the roster. Shown as a
        share, because the three play different numbers of matches and a raw
        count would just rank whoever plays most.
      </p>
      <table className="first-down">
        <thead>
          <tr>
            <th>Player</th>
            <th className="r">First down</th>
            <th className="r">Shared matches</th>
            <th className="r">Share</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.accountId}>
              <td className="name">{r.name}</td>
              <td className="r num">{r.diedFirst}</td>
              <td className="r num">{r.squadMatches}</td>
              <td className="r num">
                {r.squadMatches === 0
                  ? '—'
                  : (rateText({
                      n: r.diedFirst,
                      total: r.squadMatches,
                      pct: r.diedFirst / r.squadMatches,
                    }) ?? '—')}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  )
}
