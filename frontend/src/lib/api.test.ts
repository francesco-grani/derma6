import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

// `vi.hoisted()` runs before the `vi.mock()` factory below (itself hoisted
// above the imports), so these mock functions are safely available inside
// the factory without a TDZ error — same pattern as `lib/auth.test.tsx`.
const mocks = vi.hoisted(() => ({
  getSession: vi.fn(),
  signOut: vi.fn(),
}))

vi.mock('./supabaseClient', () => ({
  supabase: {
    auth: {
      getSession: mocks.getSession,
      signOut: mocks.signOut,
    },
  },
}))

// Imported after the mock so `api.ts` picks up the mocked `./supabaseClient`.
import { apiCompleteSignup, apiGetProfile } from './api'

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: 'error',
    json: async () => body,
  } as Response
}

function fakeSession(accessToken: string) {
  return { access_token: accessToken }
}

describe('api.ts', () => {
  let fetchMock: ReturnType<typeof vi.fn>
  let replaceMock: ReturnType<typeof vi.fn>

  beforeEach(() => {
    vi.clearAllMocks()
    fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)

    // jsdom's real `window.location.replace` throws "not implemented"; stub
    // it so `authedFetch`'s 401 handler can be exercised without crashing.
    replaceMock = vi.fn()
    Object.defineProperty(window, 'location', {
      value: { ...window.location, replace: replaceMock },
      writable: true,
      configurable: true,
    })

    mocks.signOut.mockResolvedValue({ error: null })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  describe('authedFetch token attachment (via apiGetProfile)', () => {
    it('attaches the current Supabase session access token as a Bearer header', async () => {
      mocks.getSession.mockResolvedValue({ data: { session: fakeSession('tok-abc') } })
      fetchMock.mockResolvedValue(jsonResponse({ username: 'alice' }))

      await apiGetProfile()

      expect(mocks.getSession).toHaveBeenCalledTimes(1)
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/me/profile',
        expect.objectContaining({
          headers: expect.objectContaining({ Authorization: 'Bearer tok-abc' }),
        }),
      )
    })

    it('omits the Authorization header when there is no active session', async () => {
      mocks.getSession.mockResolvedValue({ data: { session: null } })
      fetchMock.mockResolvedValue(jsonResponse({ username: 'alice' }))

      await apiGetProfile()

      const [, init] = fetchMock.mock.calls[0] as [string, RequestInit]
      expect((init.headers as Record<string, string>).Authorization).toBeUndefined()
    })

    it('signs out and redirects to /login on a 401, then throws', async () => {
      mocks.getSession.mockResolvedValue({ data: { session: fakeSession('stale-tok') } })
      fetchMock.mockResolvedValue(jsonResponse({ detail: 'Unauthorized' }, 401))

      await expect(apiGetProfile()).rejects.toThrow('Session expired')

      expect(mocks.signOut).toHaveBeenCalledTimes(1)
      expect(replaceMock).toHaveBeenCalledWith('/login')
    })

    it('throws the server-provided detail message on other non-ok responses', async () => {
      mocks.getSession.mockResolvedValue({ data: { session: fakeSession('tok') } })
      fetchMock.mockResolvedValue(jsonResponse({ detail: 'boom' }, 500))

      await expect(apiGetProfile()).rejects.toThrow('boom')
    })
  })

  describe('apiCompleteSignup', () => {
    it('POSTs the supabase_user_id/email/username and returns the provisioned user', async () => {
      fetchMock.mockResolvedValue(jsonResponse({ user_id: 'uuid-1', username: 'bob' }, 201))

      const result = await apiCompleteSignup('uuid-1', 'bob@example.com', 'bob')

      expect(fetchMock).toHaveBeenCalledWith(
        '/api/auth/complete-signup',
        expect.objectContaining({
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ supabase_user_id: 'uuid-1', email: 'bob@example.com', username: 'bob' }),
        }),
      )
      expect(result).toEqual({ user_id: 'uuid-1', username: 'bob' })
    })

    it('does not attach a bearer token (public endpoint)', async () => {
      fetchMock.mockResolvedValue(jsonResponse({ user_id: 'uuid-1', username: 'bob' }, 201))

      await apiCompleteSignup('uuid-1', 'bob@example.com', 'bob')

      expect(mocks.getSession).not.toHaveBeenCalled()
    })

    it('surfaces a 409 "email already registered" error from the backend', async () => {
      fetchMock.mockResolvedValue(jsonResponse({ detail: 'email already registered' }, 409))

      await expect(apiCompleteSignup('uuid-1', 'bob@example.com', 'bob')).rejects.toThrow(
        'email already registered',
      )
    })
  })
})
