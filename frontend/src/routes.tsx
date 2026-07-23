import { lazy, Suspense } from 'react'
import type { RouteObject } from 'react-router'
import { AppShell } from './components/AppShell'
import { Home } from './pages/Home'
import { Match } from './pages/Match'
import { Matches } from './pages/Matches'
import { Heatmaps } from './pages/Heatmaps'
import { Settings } from './pages/Settings'

// Pixi is ~400 KB and only this route needs it.
const Replay = lazy(() => import('./pages/Replay').then((m) => ({ default: m.Replay })))

// Recharts is ~415 KB and only these two routes use it. Static imports here
// would put it behind the Overview page's first paint, which draws its
// sparklines with a hand-rolled SVG precisely so it does not need a library.
const Player = lazy(() => import('./pages/Player').then((m) => ({ default: m.Player })))
const Compare = lazy(() => import('./pages/Compare').then((m) => ({ default: m.Compare })))

// No heavy dependency — its charts are hand-rolled SVG — but lazy anyway: the
// analysis page is a destination, not part of anyone's first paint.
const Strategy = lazy(() => import('./pages/Strategy').then((m) => ({ default: m.Strategy })))

function Loading() {
  return <div className="empty">loading…</div>
}

function lazyRoute(element: React.ReactNode) {
  return <Suspense fallback={<Loading />}>{element}</Suspense>
}

export const routes: RouteObject[] = [
  {
    path: '/',
    element: <AppShell />,
    children: [
      { index: true, element: <Home /> },
      { path: 'players/:accountId', element: lazyRoute(<Player />) },
      { path: 'matches', element: <Matches /> },
      { path: 'matches/:matchId', element: <Match /> },
      { path: 'heatmaps', element: <Heatmaps /> },
      { path: 'compare', element: lazyRoute(<Compare />) },
      { path: 'strategy', element: lazyRoute(<Strategy />) },
      { path: 'settings', element: <Settings /> },
      { path: '*', element: <div className="empty">no such page</div> },
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
