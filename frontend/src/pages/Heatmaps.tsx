import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { get } from '../api/client'
import type { Heatmap, PlayerCard, TileInfo } from '../api/types'
import { HeatmapCanvas } from '../components/HeatmapCanvas'
import { MapTiles } from '../components/MapTiles'
import { num } from '../lib/format'

const KINDS = ['movement', 'kill', 'death', 'knock', 'landing', 'care_package', 'vehicle_destroy']
const SIZE = 720

export function Heatmaps() {
  const [kind, setKind] = useState('landing')
  const [mapName, setMapName] = useState('Baltic_Main')
  const [accountId, setAccountId] = useState('')

  const tiles = useQuery({
    queryKey: ['tiles'],
    queryFn: () => get<Record<string, TileInfo>>('/tiles/manifest.json'),
  })
  const players = useQuery({
    queryKey: ['players', 'tracked'],
    queryFn: () => get<PlayerCard[]>('/players', { tracked: true }),
  })
  const heat = useQuery({
    queryKey: ['heatmap', mapName, kind, accountId],
    queryFn: () => get<Heatmap>('/heatmap', { map: mapName, kind, accountId: accountId || undefined }),
  })

  const info = tiles.data?.[mapName]

  return (
    <div className="grid" style={{ gap: 16 }}>
      <h1>Heatmaps</h1>

      <div className="row wrap">
        <select value={mapName} onChange={(e) => setMapName(e.target.value)}>
          {Object.values(tiles.data ?? {}).map((t) => (
            <option key={t.mapName} value={t.mapName}>{t.display ?? t.mapName}</option>
          ))}
        </select>
        <select value={accountId} onChange={(e) => setAccountId(e.target.value)}>
          <option value="">everyone</option>
          {players.data?.map((p) => <option key={p.accountId} value={p.accountId}>{p.name}</option>)}
        </select>
        <div className="row" style={{ gap: 4 }}>
          {KINDS.map((k) => (
            <button key={k} className={k === kind ? 'on' : ''} onClick={() => setKind(k)}>
              {k.replace('_', ' ')}
            </button>
          ))}
        </div>
      </div>

      <div className="faint small">
        {heat.data && (
          <>
            {num(heat.data.total)} events binned · peak cell {num(heat.data.max)} ·{' '}
            {heat.data.grid}×{heat.data.grid} grid
            {' · '}
            {/* Stated plainly rather than hidden: bins have no match_type
                dimension, so these include airoyale and tutorial matches
                while career stats do not. */}
            <span title="heatmap_bins has no match_type column">all match types</span>
          </>
        )}
      </div>

      <div className="mapwrap" style={{ width: SIZE, height: SIZE }}>
        {info ? (
          <>
            <MapTiles info={info} size={SIZE} zoom={2} />
            {heat.data && <HeatmapCanvas heatmap={heat.data} size={SIZE} />}
          </>
        ) : (
          <div className="empty">
            no tiles for {mapName} — run <code>scripts/fetch_map_assets.py</code>
          </div>
        )}
      </div>
    </div>
  )
}
