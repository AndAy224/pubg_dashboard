import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { RouterProvider, createBrowserRouter } from 'react-router'
import { routes } from './routes'
import './styles/base.css'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // The archive only changes when the poller finds a match, which is at
      // most every POLL_INTERVAL_SECONDS. Refetching on every window focus
      // just burns database round trips.
      staleTime: 60_000,
      refetchOnWindowFocus: false,
      retry: 1,
    },
  },
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={createBrowserRouter(routes)} />
    </QueryClientProvider>
  </StrictMode>,
)
