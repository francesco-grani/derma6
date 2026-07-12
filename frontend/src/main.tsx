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
import { AuthProvider, useAuth } from './lib/auth'
import { SessionProvider } from './lib/sessionContext'
import { supabase } from './lib/supabaseClient'
import { Button } from './components/ui/button'
import { Card, CardContent, CardHeader } from './components/ui/card'
import Sidebar from './components/layout/Sidebar'
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

// ── Protected layout ─────────────────────────────────────────────────────

function AppLayout() {
  // security-remediation Req 21.4/21.5: a verified session whose local
  // signup provisioning failed even after AuthProvider's automatic retry
  // gets a distinguishable recovery screen here, instead of proceeding into
  // Sidebar/Outlet as if the account were ready.
  const { provisioningError, retryProvisioning } = useAuth()

  if (provisioningError) {
    return (
      <div className="min-h-screen flex items-center justify-center" style={{ background: '#3E4D3F' }}>
        <Card className="w-full max-w-sm shadow-xl" style={{ background: '#2E3D2F', border: '1px solid #4B5A4C' }}>
          <CardHeader className="text-center pb-2">
            <img src="/Derma6_logo.png" alt="Derma6" className="mx-auto mb-2" style={{ height: 120, width: 'auto' }} />
          </CardHeader>
          <CardContent className="text-center flex flex-col gap-3">
            <p style={{ color: '#C4933F', fontWeight: 600 }}>Account setup incomplete</p>
            <p className="text-sm" style={{ color: '#9EAD9E' }}>{provisioningError}</p>
            <Button
              onClick={() => void retryProvisioning()}
              style={{ background: '#7A9B7D', color: '#1C2520', fontWeight: 600 }}
            >
              Retry
            </Button>
          </CardContent>
        </Card>
      </div>
    )
  }

  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar />
      <main className="flex-1 overflow-hidden flex flex-col">
        <Outlet />
      </main>
    </div>
  )
}

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
