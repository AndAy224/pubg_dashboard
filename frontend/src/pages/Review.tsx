import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { get } from '../api/client'
import type { RangeBandRow, SessionRow, SquadReview } from '../api/types'
import { Place, Skeleton, Tile } from '../components/ui'
import { dateTime, num } from '../lib/format'
import { rankFindings, rateText, squadFindings } from '../lib/findings'
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

  const findings = useMemo(
    () => (review.data ? rankFindings(squadFindings(review.data)) : []),
    [review.data],
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
