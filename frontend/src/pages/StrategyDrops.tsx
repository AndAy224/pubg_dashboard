import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router'
import { get } from '../api/client'
import type { DropRow, Gazetteer, MapInfo, TileInfo } from '../api/types'
import { DropMap, fullLabel, placeClass } from '../components/DropMap'
import { Place, Skeleton } from '../components/ui'
import { clusterDrops, labelCluster, summariseCluster } from '../lib/drops'
import { dateTime, duration, num } from '../lib/format'

/**
 * Where we drop, and whether it worked.
 *
 * The heatmaps have shown *where* landings happen since they were built. What
 * nobody could ask was whether landing there was a good idea — and every input
 * for it has been in Postgres since parser v7.
 *
 * Names come from PUBG's own `Character.zone`, harvested into a gazetteer by
 * `scripts/build_gazetteer.py`. They are not invented and not hand-curated.
 * Where no name is near, the spot says so and gives a bearing to the nearest
 * one rather than borrowing its name.
 */
export function StrategyDrops({
  maps,
  map,
  mode,
}: {
  maps: MapInfo[] | undefined
  /** The page filter's map, or `''` for "every map". */
  map: string
  mode: string
}) {
  // **This panel cannot honour "every map"**, and that is not a limitation to
  // work around — clustering pools coordinates, so two maps in one set puts
  // Miramar drops inside Erangel towns. When the page filter names no map this
  // keeps its own picker and says so; when it does, it follows it and the
  // local picker disappears rather than sitting there disagreeing.
  const [fallback, setFallback] = useState<string>('Baltic_Main')
  const mapName = map || fallback
  const [selected, setSelected] = useState<string | null>(null)

  const drops = useQuery({
    queryKey: ['drops', mapName, mode],
    queryFn: () =>
      get<DropRow[]>('/strategy/drops', { map: mapName, ...(mode ? { gameMode: mode } : {}) }),
    staleTime: 5 * 60_000,
  })

  const places = useQuery({
    queryKey: ['places', mapName],
    // A map with no gazetteer is a normal state, not an error: it needs raw
    // telemetry under data/ and a script run. Resolve to null so the page
    // renders unnamed spots instead of an error banner.
    queryFn: () => get<Gazetteer>(`/maps/${mapName}/places`).catch(() => null),
    staleTime: 60 * 60_000,
  })

  const manifest = useQuery({
    queryKey: ['tiles', 'manifest'],
    queryFn: () => get<Record<string, TileInfo>>('/tiles/manifest.json'),
    staleTime: Infinity,
  })

  const rows = drops.data ?? []
  const clusters = useMemo(() => clusterDrops(rows), [rows])
  const info = manifest.data?.[mapName]
  const worldSize = maps?.find((m) => m.mapName === mapName)?.worldSize ?? 816_000

  const summaries = useMemo(
    () =>
      clusters.map((c) => ({
        cluster: c,
        summary: summariseCluster(c),
        label: labelCluster(c, places.data ?? null),
      })),
    [clusters, places.data],
  )

  const played = maps?.filter((m) => m.mapName !== undefined) ?? []

  return (
    <section className="card drops">
      <div className="row" style={{ marginBottom: 8 }}>
        <h3>Where we drop</h3>
        <span className="spacer" />
        {/* Only when the page filter has not already chosen. Two pickers for
            one value is how they end up disagreeing. */}
        {!map && played.length > 1 && (
          <select value={mapName} onChange={(e) => setFallback(e.target.value)}>
            {played.map((m) => (
              <option key={m.mapName} value={m.mapName}>
                {m.display}
              </option>
            ))}
          </select>
        )}
        <span className="faint small">
          {rows.length} squad drops · {clusters.length} spots
        </span>
      </div>

      <p className="note">
        One row per squad landing, not per player — the three of you are always
        on the same roster, so counting participants would treble every spot.
        Names are PUBG’s own, from <code>Character.zone</code>. Sorted by how
        often you drop there, <strong>not</strong> by placement: with single
        digits at most spots, ranking by outcome would read as a recommendation
        the sample cannot support.
      </p>

      {drops.isPending || manifest.isPending ? (
        <Skeleton h={320} />
      ) : rows.length === 0 ? (
        <div className="empty">no landings recorded on this map yet</div>
      ) : (
        <>
          {info ? (
            <DropMap
              drops={rows}
              gazetteer={places.data ?? null}
              info={info}
              worldSize={worldSize}
              size={900}
              selected={selected}
              onSelect={setSelected}
            />
          ) : (
            <div className="empty">
              no map tiles for {mapName} — run scripts/fetch_map_assets.py
            </div>
          )}

          <div className="drop-legend faint">
            <span>
              <i className="drop-sw good" />
              median top 10
            </span>
            <span>
              <i className="drop-sw mid" />
              11–25
            </span>
            <span>
              <i className="drop-sw poor" />
              26+
            </span>
            <span>marker area ∝ drops</span>
          </div>

          <table className="drops-table">
            <thead>
              <tr>
                <th>Spot</th>
                <th className="r">Drops</th>
                <th className="r">Median</th>
                <th className="r">Best</th>
                <th className="r">Survived</th>
                <th className="r">Kills/drop</th>
                <th className="r">Contested</th>
                <th className="r">1st weapon</th>
              </tr>
            </thead>
            <tbody>
              {summaries.map(({ cluster, summary, label }) => (
                <DropRowView
                  key={cluster.id}
                  id={cluster.id}
                  drops={cluster.drops}
                  summary={summary}
                  labelText={fullLabel(label)}
                  open={selected === cluster.id}
                  onToggle={() => setSelected(selected === cluster.id ? null : cluster.id)}
                />
              ))}
            </tbody>
          </table>
        </>
      )}
    </section>
  )
}

function DropRowView({
  id,
  drops,
  summary,
  labelText,
  open,
  onToggle,
}: {
  id: string
  drops: DropRow[]
  summary: ReturnType<typeof summariseCluster>
  labelText: string
  open: boolean
  onToggle: () => void
}) {
  return (
    <>
      <tr className={`drop-row ${open ? 'open' : ''}`} onClick={onToggle}>
        <td>
          <span className={`drop-sw ${placeClass(summary.medianPlace)}`} />
          <span className="name">{labelText}</span>
          {summary.splitDrops > 0 && (
            <span className="tag" title="landings more than 200 m apart">
              {summary.splitDrops} split
            </span>
          )}
        </td>
        <td className="r num">{summary.n}</td>
        <td className="r">
          <Place place={summary.medianPlace} />
        </td>
        <td className="r">
          <Place place={summary.bestPlace} />
        </td>
        <td className="r num">{duration(summary.meanSurvivalS)}</td>
        <td className="r num">{num(summary.killsPerDrop, 1)}</td>
        <td className="r num">
          {/* Both halves travel: "72% (of 25)" and "100% (of 1)" are very
              different claims and a bare percentage hides which one you are
              reading. */}
          {summary.contestedRate === null ? (
            <span className="faint">—</span>
          ) : (
            <>
              {Math.round(summary.contestedRate * 100)}%
              <span className="faint"> /{summary.contestedN}</span>
            </>
          )}
        </td>
        <td className="r num">
          {summary.medianFirstWeaponS === null ? (
            <span className="faint">—</span>
          ) : (
            `${num(summary.medianFirstWeaponS, 1)}s`
          )}
        </td>
      </tr>
      {open && (
        <tr className="drop-detail">
          <td colSpan={8}>
            <div className="drop-detail-inner">
              {drops.map((d) => (
                <Link
                  key={`${d.matchId}-${d.teamId}`}
                  to={`/matches/${d.matchId}/replay?t=${Math.max(0, Math.round(d.landedAtS ?? 0))}`}
                  title={`${d.names.join(', ')} — watch the drop`}
                >
                  <Place place={d.winPlace} />
                  <span className="faint">{dateTime(d.playedAt)}</span>
                </Link>
              ))}
            </div>
            <p className="faint small" style={{ marginTop: 6 }}>
              {id} · each link opens the replay at the moment you landed
            </p>
          </td>
        </tr>
      )}
    </>
  )
}
