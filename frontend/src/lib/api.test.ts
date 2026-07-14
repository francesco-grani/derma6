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
import { apiCompleteSignup, apiFindProduct, apiGetProfile, buildProductFindStreamRequest } from './api'

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

  describe('apiFindProduct', () => {
    it('GETs with only the "name" query param when brand is omitted', async () => {
      mocks.getSession.mockResolvedValue({ data: { session: fakeSession('tok-abc') } })
      fetchMock.mockResolvedValue(jsonResponse({ listings: [], retail_ok: true, secondhand_ok: true }))

      const result = await apiFindProduct('Foo Cleanser')

      expect(fetchMock).toHaveBeenCalledWith(
        '/api/products/find?name=Foo+Cleanser',
        expect.objectContaining({
          headers: expect.objectContaining({ Authorization: 'Bearer tok-abc' }),
        }),
      )
      expect(result).toEqual({ listings: [], retail_ok: true, secondhand_ok: true })
    })

    it('includes the "brand" query param when brand is a non-empty string', async () => {
      mocks.getSession.mockResolvedValue({ data: { session: fakeSession('tok-abc') } })
      fetchMock.mockResolvedValue(jsonResponse({ listings: [], retail_ok: true, secondhand_ok: true }))

      await apiFindProduct('Foo Cleanser', 'Acme')

      const [url] = fetchMock.mock.calls[0] as [string]
      expect(url).toBe('/api/products/find?name=Foo+Cleanser&brand=Acme')
    })

    it('omits the "brand" query param when brand is an empty string', async () => {
      mocks.getSession.mockResolvedValue({ data: { session: fakeSession('tok-abc') } })
      fetchMock.mockResolvedValue(jsonResponse({ listings: [], retail_ok: true, secondhand_ok: true }))

      await apiFindProduct('Foo Cleanser', '')

      const [url] = fetchMock.mock.calls[0] as [string]
      expect(url).toBe('/api/products/find?name=Foo+Cleanser')
    })

    it('includes the "source" query param when given, for per-source progressive requests', async () => {
      mocks.getSession.mockResolvedValue({ data: { session: fakeSession('tok-abc') } })
      fetchMock.mockResolvedValue(jsonResponse({ listings: [], retail_ok: true, secondhand_ok: true }))

      await apiFindProduct('Foo Cleanser', undefined, 'retail')

      const [url] = fetchMock.mock.calls[0] as [string]
      expect(url).toBe('/api/products/find?name=Foo+Cleanser&source=retail')
    })

    it('returns the full ProductFindResponse shape, including populated listings', async () => {
      mocks.getSession.mockResolvedValue({ data: { session: fakeSession('tok-abc') } })
      const body = {
        listings: [
          {
            type: 'new',
            title: 'Foo Cleanser 200ml',
            price: 12.99,
            currency: 'EUR',
            source: 'dm.de',
            thumbnail_url: 'https://example.com/thumb.jpg',
            listing_url: 'https://example.com/listing/123',
          },
        ],
        retail_ok: true,
        secondhand_ok: false,
      }
      fetchMock.mockResolvedValue(jsonResponse(body))

      const result = await apiFindProduct('Foo Cleanser')

      expect(result).toEqual(body)
    })

    it('propagates a non-ok response as an ApiError', async () => {
      mocks.getSession.mockResolvedValue({ data: { session: fakeSession('tok-abc') } })
      fetchMock.mockResolvedValue(jsonResponse({ detail: 'upstream lookup failed' }, 502))

      await expect(apiFindProduct('Foo Cleanser')).rejects.toThrow('upstream lookup failed')
    })
  })

  describe('buildProductFindStreamRequest', () => {
    it('builds a stream=true URL with only "name" and "stream" when brand/source are omitted', async () => {
      mocks.getSession.mockResolvedValue({ data: { session: fakeSession('tok-abc') } })

      const { url } = await buildProductFindStreamRequest('Foo Cleanser')

      expect(url).toBe('/api/products/find?name=Foo+Cleanser&stream=true')
    })

    it('includes "brand" and "source" query params when given', async () => {
      mocks.getSession.mockResolvedValue({ data: { session: fakeSession('tok-abc') } })

      const { url } = await buildProductFindStreamRequest('Foo Cleanser', 'Acme', 'retail')

      expect(url).toBe('/api/products/find?name=Foo+Cleanser&brand=Acme&source=retail&stream=true')
    })

    it('omits "brand" when null/empty', async () => {
      mocks.getSession.mockResolvedValue({ data: { session: fakeSession('tok-abc') } })

      const { url } = await buildProductFindStreamRequest('Foo Cleanser', null, 'vinted')

      expect(url).toBe('/api/products/find?name=Foo+Cleanser&source=vinted&stream=true')
    })

    it("attaches the Authorization header from getAccessToken()'s resolved token", async () => {
      mocks.getSession.mockResolvedValue({ data: { session: fakeSession('tok-xyz') } })

      const { init } = await buildProductFindStreamRequest('Foo Cleanser')

      expect(mocks.getSession).toHaveBeenCalledTimes(1)
      expect((init.headers as Record<string, string>).Authorization).toBe('Bearer tok-xyz')
    })

    it('omits the Authorization header when there is no active session', async () => {
      mocks.getSession.mockResolvedValue({ data: { session: null } })

      const { init } = await buildProductFindStreamRequest('Foo Cleanser')

      expect((init.headers as Record<string, string>).Authorization).toBeUndefined()
    })
  })
})
