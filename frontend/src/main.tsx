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
import { AuthProvider } from './lib/AuthProvider'
import { SessionProvider } from './lib/SessionProvider'
import { supabase } from './lib/supabaseClient'
import AppLayout from './components/layout/AppLayout'
import SignUpPage from './pages/SignUpPage'
import SignInPage from './pages/SignInPage'
import VerifyEmailCallback from './pages/VerifyEmailCallback'
import ChatPage from './pages/ChatPage'
import ProfilePage from './pages/ProfilePage'
import RoutinesPage from './pages/RoutinesPage'
import AdminPage from './pages/AdminPage'
import SkinAnalysisPage from './pages/SkinAnalysisPage'
import { apiGetProfile } from './lib/api'

const queryClient = new QueryClient()

// ── Root route ────────────────────────────────────────────────────────────

const rootRoute = createRootRoute({
  // security-remediation Req 20.2, 20.3, 20.5: AuthProvider is innermost so its
  // logout() can synchronously reach both the QueryClient (to clear cached
  // per-user data) and SessionContext (to reset the in-memory chat sessionId)
  // via useQueryClient()/useSession() — previously AuthProvider wrapped both
  // and couldn't reach either.
  component: () => (
    <QueryClientProvider client={queryClient}>
      <SessionProvider>
        <AuthProvider>
          <Outlet />
        </AuthProvider>
      </SessionProvider>
    </QueryClientProvider>
  ),
})

// ── Auth (public) ─────────────────────────────────────────────────────────
//
// Route guards run in TanStack Router's `beforeLoad` — outside the React
// tree, so they can't read `useAuth()`'s reactive state. `supabase.auth
// .getSession()` is async but resolves from supabase-js's in-memory/
// localStorage-cached session (no network round-trip in the common case),
// so it's cheap enough to call directly here (TanStack Router's `beforeLoad`
// supports async loaders).

const signupRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/signup',
  beforeLoad: async () => {
    const { data } = await supabase.auth.getSession()
    if (data.session) throw redirect({ to: '/chat' })
  },
  component: SignUpPage,
})

const loginRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/login',
  beforeLoad: async () => {
    const { data } = await supabase.auth.getSession()
    if (data.session) throw redirect({ to: '/chat' })
  },
  component: SignInPage,
})

const verifyEmailCallbackRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/verify-email-callback',
  component: VerifyEmailCallback,
})

const protectedRoute = createRoute({
  getParentRoute: () => rootRoute,
  id: 'protected',
  beforeLoad: async () => {
    const { data } = await supabase.auth.getSession()
    if (!data.session) throw redirect({ to: '/login' })
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
  beforeLoad: async () => {
    // `protectedRoute`'s `beforeLoad` (parent) has already confirmed a
    // session exists by the time this runs. `is_admin` isn't part of the
    // Supabase session/JWT (Req 8.2), so it's fetched from the backend
    // profile here; any failure (e.g. not-yet-provisioned account) is
    // treated as non-admin rather than blocking navigation. A 401 here is
    // separately handled by `authedFetch()`'s own sign-out/redirect.
    let isAdmin = false
    try {
      isAdmin = (await apiGetProfile()).is_admin
    } catch {
      // Non-admin fallback: see comment above.
    }
    if (!isAdmin) throw redirect({ to: '/chat' })
  },
  component: AdminPage,
})

const skinAnalysisRoute = createRoute({
  getParentRoute: () => protectedRoute,
  path: '/skin-analysis',
  component: SkinAnalysisPage,
})

// ── Router ────────────────────────────────────────────────────────────────

const routeTree = rootRoute.addChildren([
  signupRoute,
  loginRoute,
  verifyEmailCallbackRoute,
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
