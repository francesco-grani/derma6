import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { useProductFind } from './useProductFinder'

// `vi.hoisted()` runs before the `vi.mock()` factory below (itself hoisted
// above the imports), so this mock is safely available inside the factory
// without a TDZ error — same pattern as `pages/RoutinesPage.test.tsx`.
const mocks = vi.hoisted(() => ({
  buildProductFindStreamRequest: vi.fn(),
}))

vi.mock('@/lib/api', () => ({
  buildProductFindStreamRequest: mocks.buildProductFindStreamRequest,
}))

/** A manually-driven fake `ReadableStream` reader: tests `push()` SSE frame
 * text as it becomes available and `close()` when the stream ends,
 * mirroring how the real backend emits frames incrementally rather than all
 * at once — this is what lets a test assert the `isPending` -> `stagePhrase`
 * updates -> `isSuccess`/`data` progression instead of only the final
 * state. */
class FakeStream {
  private queue: Array<{ done: boolean; value?: Uint8Array }> = []
  private waiters: Array<(v: { done: boolean; value?: Uint8Array }) => void> = []

  push(text: string) {
    this.emit({ done: false, value: new TextEncoder().encode(text) })
  }

  close() {
    this.emit({ done: true, value: undefined })
  }

  private emit(result: { done: boolean; value?: Uint8Array }) {
    const waiter = this.waiters.shift()
    if (waiter) {
      waiter(result)
    } else {
      this.queue.push(result)
    }
  }

  getReader() {
    return {
      read: (): Promise<{ done: boolean; value?: Uint8Array }> => {
        const next = this.queue.shift()
        if (next) return Promise.resolve(next)
        return new Promise((resolve) => this.waiters.push(resolve))
      },
    }
  }
}

function frame(obj: unknown): string {
  return `data: ${JSON.stringify(obj)}\n\n`
}

const DONE_FRAME = 'data: [DONE]\n\n'

function fakeFetchResolvedWith(stream: FakeStream, status = 200) {
  return Promise.resolve({
    ok: status >= 200 && status < 300,
    status,
    body: stream,
  } as unknown as Response)
}

const RESULT: { listings: unknown[]; retail_ok: boolean; secondhand_ok: boolean } = {
  listings: [
    {
      type: 'new',
      title: 'Cleanser 200ml',
      price: 12.5,
      currency: 'EUR',
      source: 'dm.de',
      thumbnail_url: null,
      listing_url: 'https://dm.de/cleanser',
    },
  ],
  retail_ok: true,
  secondhand_ok: true,
}

describe('useProductFind', () => {
  let fetchMock: ReturnType<typeof vi.fn>

  beforeEach(() => {
    vi.clearAllMocks()
    fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    mocks.buildProductFindStreamRequest.mockImplementation(
      async (name: string, brand?: string | null, source?: string) =>
        ({
          url: `/api/products/find?name=${encodeURIComponent(name)}${brand ? `&brand=${brand}` : ''}${source ? `&source=${source}` : ''}&stream=true`,
          init: { headers: { Authorization: 'Bearer tok' } },
        })
    )
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('does not fetch when disabled', async () => {
    const { result } = renderHook(() => useProductFind('Cleanser', null, false))

    await new Promise((resolve) => setTimeout(resolve, 10))
    expect(fetchMock).not.toHaveBeenCalled()
    expect(result.current).toEqual({
      isPending: false,
      isError: false,
      isSuccess: false,
      data: undefined,
      stagePhrase: null,
    })
  })

  it('does not fetch when there is no query, even if enabled is true', async () => {
    const { result } = renderHook(() => useProductFind(null, null, true))

    await new Promise((resolve) => setTimeout(resolve, 10))
    expect(fetchMock).not.toHaveBeenCalled()
    expect(result.current.isPending).toBe(false)
  })

  it('parses interleaved stage/result frames into state transitions: isPending -> stagePhrase updates -> isSuccess/data', async () => {
    const stream = new FakeStream()
    fetchMock.mockReturnValue(fakeFetchResolvedWith(stream))

    const { result } = renderHook(() => useProductFind('Cleanser', 'BrandX', true, 'retail'))

    await waitFor(() => expect(result.current.isPending).toBe(true))
    expect(result.current.stagePhrase).toBeNull()

    stream.push(frame({ type: 'stage', stage: 'discovery', message: 'Assessing retailers for Germany' }))
    await waitFor(() => expect(result.current.stagePhrase).toBe('Assessing retailers for Germany'))
    expect(result.current.isPending).toBe(true)
    expect(result.current.isSuccess).toBe(false)

    stream.push(frame({ type: 'stage', stage: 'domain_check', message: 'Checking dm.de...' }))
    await waitFor(() => expect(result.current.stagePhrase).toBe('Checking dm.de...'))

    stream.push(frame({ type: 'result', result: RESULT }))
    stream.push(DONE_FRAME)
    stream.close()

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.isPending).toBe(false)
    expect(result.current.isError).toBe(false)
    expect(result.current.data).toEqual(RESULT)
    expect(result.current.stagePhrase).toBeNull()

    expect(mocks.buildProductFindStreamRequest).toHaveBeenCalledWith('Cleanser', 'BrandX', 'retail')
  })

  it('sets isError: true when the stream ends without ever seeing a "result" frame', async () => {
    const stream = new FakeStream()
    fetchMock.mockReturnValue(fakeFetchResolvedWith(stream))

    const { result } = renderHook(() => useProductFind('Cleanser', null, true))

    await waitFor(() => expect(result.current.isPending).toBe(true))

    stream.push(frame({ type: 'stage', stage: 'domain_check', message: 'Checking dm.de...' }))
    await waitFor(() => expect(result.current.stagePhrase).toBe('Checking dm.de...'))

    // Stream ends prematurely (e.g. an unexpected server-side error) with no
    // "result" frame — Req 11.2's "unavailable" outcome.
    stream.push(DONE_FRAME)
    stream.close()

    await waitFor(() => expect(result.current.isError).toBe(true))
    expect(result.current.isPending).toBe(false)
    expect(result.current.isSuccess).toBe(false)
    expect(result.current.data).toBeUndefined()
  })

  it('tolerates a malformed SSE line, ignoring it rather than erroring', async () => {
    const stream = new FakeStream()
    fetchMock.mockReturnValue(fakeFetchResolvedWith(stream))

    const { result } = renderHook(() => useProductFind('Cleanser', null, true))
    await waitFor(() => expect(result.current.isPending).toBe(true))

    stream.push('data: {not valid json\n\n')
    stream.push(frame({ type: 'result', result: RESULT }))
    stream.push(DONE_FRAME)
    stream.close()

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data).toEqual(RESULT)
  })

  it('re-enabling (false -> true) for the same (name, brand, source) issues a brand-new fetch() call', async () => {
    const stream1 = new FakeStream()
    fetchMock.mockReturnValueOnce(fakeFetchResolvedWith(stream1))

    const { result, rerender } = renderHook(
      ({ enabled }: { enabled: boolean }) => useProductFind('Cleanser', null, enabled, 'retail'),
      { initialProps: { enabled: true } }
    )

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1))
    stream1.push(frame({ type: 'result', result: RESULT }))
    stream1.push(DONE_FRAME)
    stream1.close()
    await waitFor(() => expect(result.current.isSuccess).toBe(true))

    rerender({ enabled: false })
    await waitFor(() => expect(result.current.isPending).toBe(false))
    expect(result.current.isSuccess).toBe(false)

    const stream2 = new FakeStream()
    fetchMock.mockReturnValueOnce(fakeFetchResolvedWith(stream2))
    rerender({ enabled: true })

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2))
    stream2.push(frame({ type: 'result', result: RESULT }))
    stream2.push(DONE_FRAME)
    stream2.close()
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
  })

  it('aborts the in-flight fetch on unmount and applies no state update afterward', async () => {
    let capturedInit: RequestInit | undefined
    const stream = new FakeStream()
    fetchMock.mockImplementation((_url: string, init: RequestInit) => {
      capturedInit = init
      return fakeFetchResolvedWith(stream)
    })

    const { result, unmount } = renderHook(() => useProductFind('Cleanser', null, true))
    await waitFor(() => expect(result.current.isPending).toBe(true))

    stream.push(frame({ type: 'stage', stage: 'domain_check', message: 'Checking dm.de...' }))
    await waitFor(() => expect(result.current.stagePhrase).toBe('Checking dm.de...'))

    const stateBeforeUnmount = result.current
    unmount()

    expect((capturedInit?.signal as AbortSignal)?.aborted).toBe(true)

    // Pushing further frames after unmount must not throw or trigger a React
    // state-update-on-unmounted-component warning; the last rendered value
    // stays exactly as it was at unmount time.
    stream.push(frame({ type: 'result', result: RESULT }))
    stream.push(DONE_FRAME)
    stream.close()
    await new Promise((resolve) => setTimeout(resolve, 10))

    expect(result.current).toEqual(stateBeforeUnmount)
  })

  it('aborts the in-flight fetch when disabled mid-stream', async () => {
    let capturedInit: RequestInit | undefined
    const stream = new FakeStream()
    fetchMock.mockImplementation((_url: string, init: RequestInit) => {
      capturedInit = init
      return fakeFetchResolvedWith(stream)
    })

    const { result, rerender } = renderHook(
      ({ enabled }: { enabled: boolean }) => useProductFind('Cleanser', null, enabled),
      { initialProps: { enabled: true } }
    )
    await waitFor(() => expect(result.current.isPending).toBe(true))

    rerender({ enabled: false })

    expect((capturedInit?.signal as AbortSignal)?.aborted).toBe(true)
    await waitFor(() => expect(result.current.isPending).toBe(false))
    expect(result.current.isError).toBe(false)
    expect(result.current.isSuccess).toBe(false)
  })
})
