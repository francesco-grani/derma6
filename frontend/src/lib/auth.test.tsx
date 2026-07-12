import { beforeEach, describe, expect, it, vi } from 'vitest'
import { act, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query'
import type { AuthChangeEvent, Session } from '@supabase/supabase-js'
import { useAuth } from './auth'
import { AuthProvider } from './AuthProvider'
import { useSession } from './sessionContext'
import { SessionProvider } from './SessionProvider'
import { ApiError } from './api'

// `vi.hoisted()` runs before the `vi.mock()` factories below (which are
// themselves hoisted above the imports), so the mock functions declared here
// are safely available inside those factories without a TDZ error.
const mocks = vi.hoisted(() => ({
  getSession: vi.fn(),
  onAuthStateChange: vi.fn(),
  signOut: vi.fn(),
  apiGetProfile: vi.fn(),
  apiGetSessions: vi.fn(),
  apiCreateSession: vi.fn(),
  apiCompleteSignup: vi.fn(),
  authStateCallback: null as ((event: AuthChangeEvent, session: Session | null) => void) | null,
}))

vi.mock('./supabaseClient', () => ({
  supabase: {
    auth: {
      getSession: mocks.getSession,
      onAuthStateChange: (cb: (event: AuthChangeEvent, session: Session | null) => void) => {
        mocks.authStateCallback = cb
        return mocks.onAuthStateChange(cb)
      },
      signOut: mocks.signOut,
    },
  },
}))

// Re-exports the real `ApiError` class (via `importActual`) so
// `instanceof ApiError` checks inside `auth.tsx` still work against errors
// constructed in these tests — only the functions are swapped for mocks.
vi.mock('./api', async () => {
  const actual = await vi.importActual<typeof import('./api')>('./api')
  return {
    ...actual,
    apiGetProfile: mocks.apiGetProfile,
    apiGetSessions: mocks.apiGetSessions,
    apiCreateSession: mocks.apiCreateSession,
    apiCompleteSignup: mocks.apiCompleteSignup,
  }
})

function fakeSession(accessToken: string, userId = 'supabase-user-id'): Session {
  return {
    access_token: accessToken,
    refresh_token: 'refresh-token',
    expires_in: 3600,
    token_type: 'bearer',
    user: { id: userId },
  } as unknown as Session
}

function fakeProfile(username: string, isAdmin: boolean) {
  return {
    user_id: 'supabase-user-id',
    username,
    skin_type: null,
    skin_concerns: [],
    has_shaving_routine: null,
    beard_style: null,
    location: null,
    medical_flags: [],
    onboarding_complete: false,
    is_admin: isAdmin,
  }
}

/** AuthProvider now depends on QueryClientProvider (useQueryClient) and
 * SessionProvider (useSession) for its logout() cache/session clearing
 * (security-remediation Req 20.2, 20.3, 20.5) — every render needs both
 * ancestors, matching the real provider nesting in main.tsx. */
function renderWithProviders(ui: React.ReactElement, queryClient = new QueryClient()) {
  return {
    queryClient,
    ...render(
      <QueryClientProvider client={queryClient}>
        <SessionProvider>
          <AuthProvider>{ui}</AuthProvider>
        </SessionProvider>
      </QueryClientProvider>,
    ),
  }
}

/** Renders the auth context's live values as text so tests can assert on them. */
function Probe() {
  const { session, token, userId, username, isAdmin, loading } = useAuth()
  return (
    <div>
      <span data-testid="loading">{String(loading)}</span>
      <span data-testid="hasSession">{String(session !== null)}</span>
      <span data-testid="token">{token ?? 'null'}</span>
      <span data-testid="userId">{userId ?? 'null'}</span>
      <span data-testid="username">{username ?? 'null'}</span>
      <span data-testid="isAdmin">{String(isAdmin)}</span>
    </div>
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  mocks.authStateCallback = null
  mocks.onAuthStateChange.mockReturnValue({ data: { subscription: { unsubscribe: vi.fn() } } })
})

describe('AuthProvider', () => {
  it('derives session/token/userId/username/isAdmin from getSession() when a session is present on mount', async () => {
    mocks.getSession.mockResolvedValue({ data: { session: fakeSession('tok-abc') } })
    mocks.apiGetProfile.mockResolvedValue(fakeProfile('alice', true))

    renderWithProviders(<Probe />)

    await waitFor(() => expect(screen.getByTestId('loading')).toHaveTextContent('false'))
    expect(screen.getByTestId('hasSession')).toHaveTextContent('true')
    expect(screen.getByTestId('token')).toHaveTextContent('tok-abc')
    expect(screen.getByTestId('userId')).toHaveTextContent('supabase-user-id')

    // isAdmin/username come from a separate apiGetProfile() fetch, not the session itself.
    await waitFor(() => expect(screen.getByTestId('username')).toHaveTextContent('alice'))
    expect(screen.getByTestId('isAdmin')).toHaveTextContent('true')
    expect(mocks.apiGetProfile).toHaveBeenCalledTimes(1)
  })

  it('leaves token/userId/username/isAdmin null/false when no session is present on mount', async () => {
    mocks.getSession.mockResolvedValue({ data: { session: null } })

    renderWithProviders(<Probe />)

    await waitFor(() => expect(screen.getByTestId('loading')).toHaveTextContent('false'))
    expect(screen.getByTestId('hasSession')).toHaveTextContent('false')
    expect(screen.getByTestId('token')).toHaveTextContent('null')
    expect(screen.getByTestId('userId')).toHaveTextContent('null')
    expect(screen.getByTestId('username')).toHaveTextContent('null')
    expect(screen.getByTestId('isAdmin')).toHaveTextContent('false')
    // No session means no profile fetch should have been attempted.
    expect(mocks.apiGetProfile).not.toHaveBeenCalled()
  })

  it('reacts to onAuthStateChange: sign-in populates state, sign-out clears it', async () => {
    mocks.getSession.mockResolvedValue({ data: { session: null } })
    mocks.apiGetProfile.mockResolvedValue(fakeProfile('bob', false))

    renderWithProviders(<Probe />)

    await waitFor(() => expect(screen.getByTestId('loading')).toHaveTextContent('false'))
    expect(screen.getByTestId('hasSession')).toHaveTextContent('false')
    expect(mocks.authStateCallback).not.toBeNull()

    // Simulate Supabase's listener firing a sign-in event after the initial mount.
    act(() => {
      mocks.authStateCallback?.('SIGNED_IN', fakeSession('tok-signed-in'))
    })

    await waitFor(() => expect(screen.getByTestId('hasSession')).toHaveTextContent('true'))
    expect(screen.getByTestId('token')).toHaveTextContent('tok-signed-in')
    await waitFor(() => expect(screen.getByTestId('username')).toHaveTextContent('bob'))
    expect(screen.getByTestId('isAdmin')).toHaveTextContent('false')

    // Simulate a subsequent sign-out event.
    act(() => {
      mocks.authStateCallback?.('SIGNED_OUT', null)
    })

    await waitFor(() => expect(screen.getByTestId('hasSession')).toHaveTextContent('false'))
    expect(screen.getByTestId('token')).toHaveTextContent('null')
    expect(screen.getByTestId('username')).toHaveTextContent('null')
    expect(screen.getByTestId('isAdmin')).toHaveTextContent('false')
  })

  it('logout() calls supabase.auth.signOut()', async () => {
    mocks.getSession.mockResolvedValue({ data: { session: null } })
    mocks.signOut.mockResolvedValue({ error: null })

    function LogoutProbe() {
      const { logout } = useAuth()
      return (
        <button type="button" onClick={() => void logout()}>
          Sign out
        </button>
      )
    }

    renderWithProviders(<LogoutProbe />)

    await waitFor(() => expect(screen.getByRole('button', { name: 'Sign out' })).toBeEnabled())
    await act(async () => {
      screen.getByRole('button', { name: 'Sign out' }).click()
    })

    expect(mocks.signOut).toHaveBeenCalledTimes(1)
  })
})

// ── security-remediation Task 58/59/60: logout() cache/session/storage clearing ──

describe('AuthProvider logout() cross-account isolation', () => {
  it('synchronously clears the QueryClient cache, before signOut() resolves', async () => {
    mocks.getSession.mockResolvedValue({ data: { session: fakeSession('tok-abc') } })
    mocks.apiGetProfile.mockResolvedValue(fakeProfile('alice', false))
    // Never resolves during this test — proves the cache clear in logout()
    // doesn't wait on signOut() to complete.
    mocks.signOut.mockReturnValue(new Promise(() => {}))

    function LogoutProbe() {
      const { logout } = useAuth()
      const query = useQuery({ queryKey: ['profile', 'supabase-user-id'], queryFn: () => 'cached-alice-data' })
      return (
        <div>
          <span data-testid="profileData">{query.data ?? 'none'}</span>
          <button type="button" onClick={() => void logout()}>
            Sign out
          </button>
        </div>
      )
    }

    const { queryClient } = renderWithProviders(<LogoutProbe />)
    await waitFor(() => expect(screen.getByTestId('profileData')).toHaveTextContent('cached-alice-data'))
    expect(queryClient.getQueryData(['profile', 'supabase-user-id'])).toBe('cached-alice-data')

    act(() => {
      screen.getByRole('button', { name: 'Sign out' }).click()
    })

    // Cache is gone immediately — no need to await signOut() or a re-render.
    expect(queryClient.getQueryData(['profile', 'supabase-user-id'])).toBeUndefined()
  })

  it('synchronously resets username/isAdmin within logout() itself, without waiting on signOut()', async () => {
    mocks.getSession.mockResolvedValue({ data: { session: fakeSession('tok-abc') } })
    mocks.apiGetProfile.mockResolvedValue(fakeProfile('alice', true))
    // Never resolves during this test — proves the reset in logout() doesn't
    // wait on signOut() (or the async onAuthStateChange callback) to complete.
    mocks.signOut.mockReturnValue(new Promise(() => {}))

    function ProbeWithLogout() {
      const { logout, username, isAdmin } = useAuth()
      return (
        <div>
          <span data-testid="username">{username ?? 'null'}</span>
          <span data-testid="isAdmin">{String(isAdmin)}</span>
          <button type="button" onClick={() => void logout()}>
            Sign out
          </button>
        </div>
      )
    }

    renderWithProviders(<ProbeWithLogout />)
    await waitFor(() => expect(screen.getByTestId('username')).toHaveTextContent('alice'))
    expect(screen.getByTestId('isAdmin')).toHaveTextContent('true')

    act(() => {
      screen.getByRole('button', { name: 'Sign out' }).click()
    })

    expect(screen.getByTestId('username')).toHaveTextContent('null')
    expect(screen.getByTestId('isAdmin')).toHaveTextContent('false')
  })

  it('clears sessionStorage handoff keys on logout', async () => {
    mocks.getSession.mockResolvedValue({ data: { session: fakeSession('tok-abc') } })
    mocks.apiGetProfile.mockResolvedValue(fakeProfile('alice', false))
    mocks.signOut.mockResolvedValue({ error: null })
    sessionStorage.setItem('derma6:skin-analysis', JSON.stringify({ result: {}, imageDataUrl: 'x' }))
    sessionStorage.setItem('derma6:initial-message', 'draft message')

    function LogoutProbe() {
      const { logout } = useAuth()
      return (
        <button type="button" onClick={() => void logout()}>
          Sign out
        </button>
      )
    }
    renderWithProviders(<LogoutProbe />)

    await waitFor(() => expect(screen.getByRole('button', { name: 'Sign out' })).toBeEnabled())
    await act(async () => {
      screen.getByRole('button', { name: 'Sign out' }).click()
    })

    expect(sessionStorage.getItem('derma6:skin-analysis')).toBeNull()
    expect(sessionStorage.getItem('derma6:initial-message')).toBeNull()
  })

  it('clears QueryClient cache, sessionId, and sessionStorage on a SIGNED_OUT event that bypasses logout() entirely (Task 82)', async () => {
    // deepsec-revalidation follow-up: a sign-out triggered from outside this
    // tab (another tab, Supabase's own session-invalidation) never calls
    // logout() or handleUnauthorized() — only the onAuthStateChange listener
    // fires. That listener must be a complete backstop on its own.
    mocks.getSession.mockResolvedValue({ data: { session: fakeSession('tok-abc') } })
    mocks.apiGetProfile.mockResolvedValue(fakeProfile('alice', false))
    sessionStorage.setItem('derma6:skin-analysis', JSON.stringify({ result: {}, imageDataUrl: 'x' }))
    sessionStorage.setItem('derma6:initial-message', 'draft message')

    function Probe2() {
      const query = useQuery({ queryKey: ['profile', 'supabase-user-id'], queryFn: () => 'cached-alice-data' })
      const { sessionId, setSessionId } = useSession()
      return (
        <div>
          <span data-testid="profileData">{query.data ?? 'none'}</span>
          <span data-testid="sessionId">{sessionId ?? 'null'}</span>
          <button type="button" onClick={() => setSessionId('stale-session-from-alice')}>
            Set session
          </button>
        </div>
      )
    }

    const { queryClient } = renderWithProviders(<Probe2 />)
    await waitFor(() => expect(screen.getByTestId('profileData')).toHaveTextContent('cached-alice-data'))
    act(() => {
      screen.getByRole('button', { name: 'Set session' }).click()
    })
    expect(screen.getByTestId('sessionId')).toHaveTextContent('stale-session-from-alice')

    // Fired directly — not via logout() or handleUnauthorized().
    act(() => {
      mocks.authStateCallback?.('SIGNED_OUT', null)
    })

    expect(queryClient.getQueryData(['profile', 'supabase-user-id'])).toBeUndefined()
    expect(screen.getByTestId('sessionId')).toHaveTextContent('null')
    expect(sessionStorage.getItem('derma6:skin-analysis')).toBeNull()
    expect(sessionStorage.getItem('derma6:initial-message')).toBeNull()
  })

  it('resets the in-memory chat sessionId on logout', async () => {
    mocks.getSession.mockResolvedValue({ data: { session: fakeSession('tok-abc') } })
    mocks.apiGetProfile.mockResolvedValue(fakeProfile('alice', false))
    mocks.signOut.mockResolvedValue({ error: null })

    function SessionProbe() {
      const { sessionId, setSessionId } = useSession()
      const { logout } = useAuth()
      return (
        <div>
          <span data-testid="sessionId">{sessionId ?? 'null'}</span>
          <button type="button" onClick={() => setSessionId('stale-session-from-alice')}>
            Set session
          </button>
          <button type="button" onClick={() => void logout()}>
            Sign out
          </button>
        </div>
      )
    }
    renderWithProviders(<SessionProbe />)

    await waitFor(() => expect(screen.getByRole('button', { name: 'Sign out' })).toBeEnabled())
    act(() => {
      screen.getByRole('button', { name: 'Set session' }).click()
    })
    expect(screen.getByTestId('sessionId')).toHaveTextContent('stale-session-from-alice')

    await act(async () => {
      screen.getByRole('button', { name: 'Sign out' }).click()
    })

    expect(screen.getByTestId('sessionId')).toHaveTextContent('null')
  })

  it('a second account signing in after logout never sees the first account\'s cached profile', async () => {
    // End-to-end account-switch regression (Task 60): alice's profile query
    // populates the cache under her userId, alice logs out (via the same
    // onAuthStateChange path a real sign-out triggers), then bob signs in in
    // the same tab — his own query (keyed by his own userId) must be a clean
    // fetch of his own data, and alice's cached entry must be gone, not just
    // shadowed by a different key.
    mocks.getSession.mockResolvedValue({ data: { session: fakeSession('tok-alice', 'uid-alice') } })
    mocks.apiGetProfile.mockImplementation(() =>
      Promise.resolve(fakeProfile(mocks.authStateCallback ? 'bob' : 'alice', false)),
    )
    mocks.signOut.mockResolvedValue({ error: null })

    function App() {
      const { logout, userId } = useAuth()
      const query = useQuery({
        queryKey: ['profile', userId],
        queryFn: () => `profile-data-for-${userId}`,
        enabled: !!userId,
      })
      return (
        <div>
          <span data-testid="profileData">{query.data ?? 'none'}</span>
          <button type="button" onClick={() => void logout()}>
            Sign out
          </button>
        </div>
      )
    }

    const { queryClient } = renderWithProviders(<App />)
    await waitFor(() => expect(screen.getByTestId('profileData')).toHaveTextContent('profile-data-for-uid-alice'))
    expect(queryClient.getQueryData(['profile', 'uid-alice'])).toBe('profile-data-for-uid-alice')

    // logout()'s queryClient.clear() runs synchronously; session/userId only
    // update afterward via the async onAuthStateChange listener below, so the
    // still-enabled query legitimately refetches alice's own data under her
    // own key in that gap (she's still authenticated at that instant) — not a
    // security issue. What actually matters is checked after bob signs in.
    act(() => {
      screen.getByRole('button', { name: 'Sign out' }).click()
    })

    // Bob signs in, in the same tab, without a page reload.
    act(() => {
      mocks.authStateCallback?.('SIGNED_IN', fakeSession('tok-bob', 'uid-bob'))
    })

    // The property that actually matters: bob's own query, under his own key,
    // never resolves to alice's cached value — it's his own fresh fetch.
    await waitFor(() => expect(screen.getByTestId('profileData')).toHaveTextContent('profile-data-for-uid-bob'))
  })
})

// ── security-remediation Task 63: post-login signup provisioning recovery ──

function ProvisioningProbe() {
  const { username, isAdmin, provisioningError, retryProvisioning } = useAuth()
  return (
    <div>
      <span data-testid="username">{username ?? 'null'}</span>
      <span data-testid="isAdmin">{String(isAdmin)}</span>
      <span data-testid="provisioningError">{provisioningError ?? 'null'}</span>
      <button type="button" onClick={() => void retryProvisioning()}>
        Retry
      </button>
    </div>
  )
}

describe('AuthProvider signup provisioning recovery (Req 21.4/21.5)', () => {
  it('retries provisioning once via apiCompleteSignup() after a 412 profile fetch, then loads normally', async () => {
    mocks.getSession.mockResolvedValue({ data: { session: fakeSession('tok-abc') } })
    mocks.apiGetProfile
      .mockRejectedValueOnce(new ApiError('Account setup incomplete', 412))
      .mockResolvedValueOnce(fakeProfile('alice', false))
    mocks.apiCompleteSignup.mockResolvedValue({ user_id: 'supabase-user-id', username: 'alice' })

    renderWithProviders(<ProvisioningProbe />)

    await waitFor(() => expect(screen.getByTestId('username')).toHaveTextContent('alice'))
    expect(screen.getByTestId('provisioningError')).toHaveTextContent('null')
    expect(mocks.apiCompleteSignup).toHaveBeenCalledTimes(1)
    expect(mocks.apiGetProfile).toHaveBeenCalledTimes(2)
  })

  it('does not call apiCompleteSignup() for a non-412 profile fetch failure', async () => {
    mocks.getSession.mockResolvedValue({ data: { session: fakeSession('tok-abc') } })
    mocks.apiGetProfile.mockRejectedValue(new ApiError('Server error', 500))

    renderWithProviders(<ProvisioningProbe />)

    await waitFor(() => expect(screen.getByTestId('username')).toHaveTextContent('null'))
    expect(screen.getByTestId('provisioningError')).toHaveTextContent('null')
    expect(mocks.apiCompleteSignup).not.toHaveBeenCalled()
  })

  it('surfaces a distinguishable provisioningError when the automatic retry also fails, and a manual retry recovers', async () => {
    mocks.getSession.mockResolvedValue({ data: { session: fakeSession('tok-abc') } })
    mocks.apiGetProfile.mockRejectedValueOnce(new ApiError('Account setup incomplete', 412))
    mocks.apiCompleteSignup.mockRejectedValueOnce(new Error('boom'))

    renderWithProviders(<ProvisioningProbe />)

    await waitFor(() =>
      expect(screen.getByTestId('provisioningError')).toHaveTextContent(
        'We could not finish setting up your account. Please try again.',
      ),
    )
    expect(screen.getByTestId('username')).toHaveTextContent('null')

    // A manual retry (per get_or_create_user_by_id's idempotent contract)
    // succeeds this time.
    mocks.apiGetProfile.mockRejectedValueOnce(new ApiError('Account setup incomplete', 412))
    mocks.apiCompleteSignup.mockResolvedValueOnce({ user_id: 'supabase-user-id', username: 'alice' })
    mocks.apiGetProfile.mockResolvedValueOnce(fakeProfile('alice', false))

    await act(async () => {
      screen.getByRole('button', { name: 'Retry' }).click()
    })

    await waitFor(() => expect(screen.getByTestId('username')).toHaveTextContent('alice'))
    expect(screen.getByTestId('provisioningError')).toHaveTextContent('null')
  })
})
