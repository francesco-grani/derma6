import { beforeEach, describe, expect, it, vi } from 'vitest'
import { act, render, screen, waitFor } from '@testing-library/react'
import type { AuthChangeEvent, Session } from '@supabase/supabase-js'
import { AuthProvider, useAuth } from './auth'

// `vi.hoisted()` runs before the `vi.mock()` factories below (which are
// themselves hoisted above the imports), so the mock functions declared here
// are safely available inside those factories without a TDZ error.
const mocks = vi.hoisted(() => ({
  getSession: vi.fn(),
  onAuthStateChange: vi.fn(),
  signOut: vi.fn(),
  apiGetProfile: vi.fn(),
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

vi.mock('./api', () => ({
  apiGetProfile: mocks.apiGetProfile,
}))

function fakeSession(accessToken: string): Session {
  return {
    access_token: accessToken,
    refresh_token: 'refresh-token',
    expires_in: 3600,
    token_type: 'bearer',
    user: { id: 'supabase-user-id' },
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

/** Renders the auth context's live values as text so tests can assert on them. */
function Probe() {
  const { session, token, username, isAdmin, loading } = useAuth()
  return (
    <div>
      <span data-testid="loading">{String(loading)}</span>
      <span data-testid="hasSession">{String(session !== null)}</span>
      <span data-testid="token">{token ?? 'null'}</span>
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
  it('derives session/token/username/isAdmin from getSession() when a session is present on mount', async () => {
    mocks.getSession.mockResolvedValue({ data: { session: fakeSession('tok-abc') } })
    mocks.apiGetProfile.mockResolvedValue(fakeProfile('alice', true))

    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    )

    await waitFor(() => expect(screen.getByTestId('loading')).toHaveTextContent('false'))
    expect(screen.getByTestId('hasSession')).toHaveTextContent('true')
    expect(screen.getByTestId('token')).toHaveTextContent('tok-abc')

    // isAdmin/username come from a separate apiGetProfile() fetch, not the session itself.
    await waitFor(() => expect(screen.getByTestId('username')).toHaveTextContent('alice'))
    expect(screen.getByTestId('isAdmin')).toHaveTextContent('true')
    expect(mocks.apiGetProfile).toHaveBeenCalledTimes(1)
  })

  it('leaves token/username/isAdmin null/false when no session is present on mount', async () => {
    mocks.getSession.mockResolvedValue({ data: { session: null } })

    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    )

    await waitFor(() => expect(screen.getByTestId('loading')).toHaveTextContent('false'))
    expect(screen.getByTestId('hasSession')).toHaveTextContent('false')
    expect(screen.getByTestId('token')).toHaveTextContent('null')
    expect(screen.getByTestId('username')).toHaveTextContent('null')
    expect(screen.getByTestId('isAdmin')).toHaveTextContent('false')
    // No session means no profile fetch should have been attempted.
    expect(mocks.apiGetProfile).not.toHaveBeenCalled()
  })

  it('reacts to onAuthStateChange: sign-in populates state, sign-out clears it', async () => {
    mocks.getSession.mockResolvedValue({ data: { session: null } })
    mocks.apiGetProfile.mockResolvedValue(fakeProfile('bob', false))

    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    )

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

    render(
      <AuthProvider>
        <LogoutProbe />
      </AuthProvider>,
    )

    await waitFor(() => expect(screen.getByRole('button', { name: 'Sign out' })).toBeEnabled())
    await act(async () => {
      screen.getByRole('button', { name: 'Sign out' }).click()
    })

    expect(mocks.signOut).toHaveBeenCalledTimes(1)
  })
})
