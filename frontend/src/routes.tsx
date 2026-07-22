import { lazy, Suspense } from 'react'
import type { RouteObject } from 'react-router'
import { AppShell } from './components/AppShell'
import { Home } from './pages/Home'
import { Player } from './pages/Player'
import { Match } from './pages/Match'
import { Heatmaps } from './pages/Heatmaps'
import { Settings } from './pages/Settings'

// Pixi is ~400 KB and only this route needs it.
const Replay = lazy(() => import('./pages/Replay').then((m) => ({ default: m.Replay })))

function Loading() {
  return <div className="empty">loading…</div>
}

export const routes: RouteObject[] = [
  {
    path: '/',
    element: <AppShell />,
    children: [
      { index: true, element: <Home /> },
      { path: 'players/:accountId', element: <Player /> },
      { path: 'matches/:matchId', element: <Match /> },
      { path: 'heatmaps', element: <Heatmaps /> },
      { path: 'settings', element: <Settings /> },
    ],
  },
  {
    // Deliberately outside AppShell: the replay is full-bleed, so it mounts
    // bare rather than inside the nav chrome.
    path: '/matches/:matchId/replay',
    element: (
      <Suspense fallback={<Loading />}>
        <Replay />
      </Suspense>
    ),
  },
]
