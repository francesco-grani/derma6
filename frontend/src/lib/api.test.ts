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
    sessionStorage.clear()
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

    it('clears sessionStorage handoff keys on a 401 (deepsec-revalidation Task 80)', async () => {
      // The implicit-signout path (any 401) bypasses AuthProvider.logout()
      // entirely — it must clear the same sessionStorage keys itself rather
      // than leaving a stale account's skin-analysis/chat-handoff data
      // readable by whoever signs in next in this tab.
      mocks.getSession.mockResolvedValue({ data: { session: fakeSession('stale-tok') } })
      fetchMock.mockResolvedValue(jsonResponse({ detail: 'Unauthorized' }, 401))
      sessionStorage.setItem('derma6:skin-analysis', JSON.stringify({ result: {}, imageDataUrl: 'x' }))
      sessionStorage.setItem('derma6:initial-message', 'draft message')

      await expect(apiGetProfile()).rejects.toThrow('Session expired')

      expect(sessionStorage.getItem('derma6:skin-analysis')).toBeNull()
      expect(sessionStorage.getItem('derma6:initial-message')).toBeNull()
    })

    it('throws the server-provided detail message on other non-ok responses', async () => {
      mocks.getSession.mockResolvedValue({ data: { session: fakeSession('tok') } })
      fetchMock.mockResolvedValue(jsonResponse({ detail: 'boom' }, 500))

      await expect(apiGetProfile()).rejects.toThrow('boom')
    })
  })

  describe('apiCompleteSignup', () => {
    it('POSTs with no body and attaches the bearer token (security-remediation Req 21.1)', async () => {
      mocks.getSession.mockResolvedValue({ data: { session: fakeSession('tok-abc') } })
      fetchMock.mockResolvedValue(jsonResponse({ user_id: 'uuid-1', username: 'bob' }, 201))

      const result = await apiCompleteSignup()

      expect(fetchMock).toHaveBeenCalledWith(
        '/api/auth/complete-signup',
        expect.objectContaining({
          method: 'POST',
          headers: expect.objectContaining({ Authorization: 'Bearer tok-abc' }),
        }),
      )
      const [, init] = fetchMock.mock.calls[0] as [string, RequestInit]
      expect(init.body).toBeUndefined()
      expect(result).toEqual({ user_id: 'uuid-1', username: 'bob' })
    })

    it('surfaces a 409 "email already registered" error from the backend', async () => {
      mocks.getSession.mockResolvedValue({ data: { session: fakeSession('tok-abc') } })
      fetchMock.mockResolvedValue(jsonResponse({ detail: 'email already registered' }, 409))

      await expect(apiCompleteSignup()).rejects.toThrow('email already registered')
    })
  })
})
