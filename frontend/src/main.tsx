import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import {
  createRouter,
  RouterProvider,
  createRoute,
  createRootRoute,
  redirect,
  Outlet,
} from '@tanstack/react-router'
import './index.css'
import { AuthProvider } from './lib/auth'
import Sidebar from './components/layout/Sidebar'
import LoginPage from './pages/LoginPage'
import ChatPage from './pages/ChatPage'
import ProfilePage from './pages/ProfilePage'
import RoutinesPage from './pages/RoutinesPage'
import AdminPage from './pages/AdminPage'
import SkinAnalysisPage from './pages/SkinAnalysisPage'
import { getToken } from './lib/api'

const queryClient = new QueryClient()

// ── Root route ────────────────────────────────────────────────────────────

const rootRoute = createRootRoute({
  component: () => (
    <AuthProvider>
      <QueryClientProvider client={queryClient}>
        <Outlet />
      </QueryClientProvider>
    </AuthProvider>
  ),
})

// ── Login ─────────────────────────────────────────────────────────────────

const loginRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/login',
  beforeLoad: () => {
    if (getToken()) throw redirect({ to: '/chat' })
  },
  component: LoginPage,
})

// ── Protected layout ─────────────────────────────────────────────────────

function AppLayout() {
  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar />
      <main className="flex-1 overflow-hidden">
        <Outlet />
      </main>
    </div>
  )
}

const protectedRoute = createRoute({
  getParentRoute: () => rootRoute,
  id: 'protected',
  beforeLoad: () => {
    if (!getToken()) throw redirect({ to: '/login' })
  },
  component: AppLayout,
})

// ── Protected child routes ────────────────────────────────────────────────

const indexRoute = createRoute({
  getParentRoute: () => protectedRoute,
  path: '/',
  beforeLoad: () => { throw redirect({ to: '/chat' }) },
})

const chatRoute = createRoute({
  getParentRoute: () => protectedRoute,
  path: '/chat',
  component: ChatPage,
})

const profileRoute = createRoute({
  getParentRoute: () => protectedRoute,
  path: '/profile',
  component: ProfilePage,
})

const routinesRoute = createRoute({
  getParentRoute: () => protectedRoute,
  path: '/routines',
  component: RoutinesPage,
})

const adminRoute = createRoute({
  getParentRoute: () => protectedRoute,
  path: '/admin',
  component: AdminPage,
})

const skinAnalysisRoute = createRoute({
  getParentRoute: () => protectedRoute,
  path: '/skin-analysis',
  component: SkinAnalysisPage,
})

// ── Router ────────────────────────────────────────────────────────────────

const routeTree = rootRoute.addChildren([
  loginRoute,
  protectedRoute.addChildren([
    indexRoute,
    chatRoute,
    profileRoute,
    routinesRoute,
    adminRoute,
    skinAnalysisRoute,
  ]),
])

const router = createRouter({ routeTree })

declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router
  }
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <RouterProvider router={router} />
  </StrictMode>,
)
