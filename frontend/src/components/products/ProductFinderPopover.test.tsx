import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import { ProductFinderPopover, RotatingStagePhrase } from './ProductFinderPopover'
import { dedupeStagePhrases } from './stagePhrases'
import { ProductFinderProvider, useProductFinderTarget } from './ProductFinderProvider'
import type { ProductFindResponse, ProductFindSource, UserProfile } from '@/lib/api'

// `vi.hoisted()` runs before the `vi.mock()` factory below (itself hoisted
// above the imports), so this mock is safely available inside the factory
// without a TDZ error — same pattern as `useProductFinder.test.tsx` /
// `RoutinesPage.test.tsx`. `useProductFind` (Task 11) no longer calls
// `apiFindProduct` — it builds its own `fetch()` from
// `buildProductFindStreamRequest`'s pieces and reads a streamed response
// body, so these tests drive it by mocking `buildProductFindStreamRequest`
// (to control the request URL) and the global `fetch` (to control the
// streamed SSE response), the same approach `useProductFinder.test.tsx`
// takes.
const mocks = vi.hoisted(() => ({
  buildProductFindStreamRequest: vi.fn(),
  apiGetProfile: vi.fn(),
}))

vi.mock('@/lib/api', () => ({
  buildProductFindStreamRequest: mocks.buildProductFindStreamRequest,
  apiGetProfile: mocks.apiGetProfile,
}))

vi.mock('@/lib/auth', () => ({
  useAuth: () => ({ token: 'tok-abc', userId: 'uid-alice' }),
}))

vi.mock('@tanstack/react-router', async () => {
  const actual = await vi.importActual<typeof import('@tanstack/react-router')>(
    '@tanstack/react-router'
  )
  return {
    ...actual,
    // `Link` requires a live `RouterProvider` context, which isn't set up in
    // these component-level tests — swap it for a plain anchor, same
    // workaround as `SignInPage.test.tsx`.
    Link: ({ to, children, ...props }: { to: string; children: ReactNode }) => (
      <a href={to} {...props}>
        {children}
      </a>
    ),
  }
})

const PROFILE_WITH_LOCATION: UserProfile = {
  user_id: 'uid-alice',
  username: 'alice',
  skin_type: null,
  skin_concerns: [],
  has_shaving_routine: null,
  beard_style: null,
  location: 'Germany',
  medical_flags: [],
  onboarding_complete: true,
  is_admin: false,
}

// Stand-in for `FindProductButton` (Task 18) that opens/closes the shared
// global target directly, so these tests can drive `ProductFinderPopover`
// (Task 19) without depending on Task 18's own rendering rules.
function Controls({ query }: { query: string }) {
  const { openFinder, closeFinder } = useProductFinderTarget()
  return (
    <>
      <button
        onClick={(event) => openFinder(event.currentTarget, query)}
      >
        open
      </button>
      <button onClick={() => closeFinder()}>close</button>
    </>
  )
}

function renderPopover(query = 'Cleanser') {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <ProductFinderProvider>
        <Controls query={query} />
        <ProductFinderPopover />
      </ProductFinderProvider>
    </QueryClientProvider>
  )
}

const RETAIL_ONLY: ProductFindResponse = {
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
  secondhand_ok: false,
}

const VINTED_ONLY: ProductFindResponse = {
  listings: [
    {
      type: 'used',
      title: 'Cleanser 200ml (used)',
      price: null,
      currency: null,
      source: 'Vinted',
      thumbnail_url: null,
      listing_url: 'https://vinted.de/cleanser',
    },
  ],
  retail_ok: false,
  secondhand_ok: true,
}

const VINTED_CHEAPER: ProductFindResponse = {
  listings: [
    {
      type: 'used',
      title: 'Cleanser 200ml (used)',
      price: 5.0,
      currency: 'EUR',
      source: 'Vinted',
      thumbnail_url: null,
      listing_url: 'https://vinted.de/cleanser',
    },
  ],
  retail_ok: false,
  secondhand_ok: true,
}

const EMPTY_OK: ProductFindResponse = { listings: [], retail_ok: true, secondhand_ok: false }
const EMPTY_NOT_OK: ProductFindResponse = { listings: [], retail_ok: false, secondhand_ok: false }

/** A manually-driven fake `ReadableStream` reader (mirrors
 * `useProductFinder.test.tsx`'s `FakeStream`): lets a test `push()` SSE
 * frame text incrementally and `close()` when the stream ends, so tests can
 * assert the popover's mid-stream `stagePhrase` display, not just the
 * settled end state. */
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
    if (waiter) waiter(result)
    else this.queue.push(result)
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

function stageFrame(message: string) {
  return `data: ${JSON.stringify({ type: 'stage', stage: 'domain_check', message })}\n\n`
}

function resultFrame(result: ProductFindResponse) {
  return `data: ${JSON.stringify({ type: 'result', result })}\n\n`
}

const DONE_FRAME = 'data: [DONE]\n\n'

function sourceFromUrl(url: string): ProductFindSource | undefined {
  const match = /source=([a-z]+)/.exec(url)
  return match ? (match[1] as ProductFindSource) : undefined
}

function immediateStream(result: ProductFindResponse) {
  return {
    getReader: () => {
      const frames = [resultFrame(result), DONE_FRAME]
      let i = 0
      return {
        read: async () => {
          if (i < frames.length) {
            return { done: false, value: new TextEncoder().encode(frames[i++]) }
          }
          return { done: true, value: undefined }
        },
      }
    },
  }
}

type SourceOutcome = ProductFindResponse | 'pending' | Error

/** Configures the global `fetch` mock's per-source dispatch: since
 * `ProductFinderPopover` fires one independent streamed request per source
 * (retail/vinted/kleinanzeigen), tests need to control each source's
 * response separately rather than a blanket `mockResolvedValue`. `'pending'`
 * (or an omitted source) leaves that source's request unresolved, for
 * exercising the loading/progressive-arrival states. */
function mockPerSource(bySource: Partial<Record<ProductFindSource, SourceOutcome>>) {
  fetchMockRef.mockImplementation((url: string) => {
    const source = sourceFromUrl(url)
    const outcome = (source && bySource[source]) ?? 'pending'
    if (outcome === 'pending') {
      return new Promise<Response>(() => {})
    }
    if (outcome instanceof Error) {
      return Promise.reject(outcome)
    }
    return Promise.resolve({ ok: true, status: 200, body: immediateStream(outcome) } as unknown as Response)
  })
}

/** Like `mockPerSource`, but backs each given source with a caller-driven
 * `FakeStream` instead of an immediately-resolved one, so a test can push
 * `stage` frames and observe the popover's live `stagePhrase` display before
 * ending the stream. */
function mockPerSourceStreams(streams: Partial<Record<ProductFindSource, FakeStream>>) {
  fetchMockRef.mockImplementation((url: string) => {
    const source = sourceFromUrl(url)
    const stream = source && streams[source]
    if (!stream) return new Promise<Response>(() => {})
    return Promise.resolve({ ok: true, status: 200, body: stream } as unknown as Response)
  })
}

let fetchMockRef: ReturnType<typeof vi.fn>

beforeEach(() => {
  vi.clearAllMocks()
  fetchMockRef = vi.fn()
  vi.stubGlobal('fetch', fetchMockRef)
  mocks.buildProductFindStreamRequest.mockImplementation(
    async (name: string, brand?: string | null, source?: ProductFindSource) =>
      ({
        url: `/api/products/find?name=${encodeURIComponent(name)}${brand ? `&brand=${brand}` : ''}${source ? `&source=${source}` : ''}&stream=true`,
        init: {},
      })
  )
  // Default: a profile with a location set, so every pre-existing test in
  // this file (written before the location gate existed) keeps exercising
  // the actual search flow unchanged. Tests for the no-location/
  // profile-pending states override this per-test.
  mocks.apiGetProfile.mockResolvedValue(PROFILE_WITH_LOCATION)
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('ProductFinderPopover', () => {
  it('renders nothing when anchorEl is null (no trigger clicked yet)', () => {
    renderPopover()

    expect(screen.queryByTestId('product-finder-loading')).toBeNull()
    expect(screen.queryByTestId('product-finder-results')).toBeNull()
    expect(screen.queryByTestId('product-finder-empty')).toBeNull()
    expect(screen.queryByTestId('product-finder-unavailable')).toBeNull()
    expect(fetchMockRef).not.toHaveBeenCalled()
  })

  it('shows a single loading line while every source is still in flight (all three fall back to "Searching...", deduped)', async () => {
    mockPerSource({}) // all three left pending, none has emitted a stage event

    renderPopover()

    fireEvent.click(screen.getByText('open'))

    expect(await screen.findByTestId('product-finder-loading')).toBeInTheDocument()
    // Three pending sources with no stage event yet all read "Searching...";
    // deduped to one line, and only one phrase is shown at a time.
    await waitFor(() => expect(screen.getAllByText('Searching...')).toHaveLength(1))
  })

  it('renders a results grid combining listings from all three sources on success', async () => {
    mockPerSource({ retail: RETAIL_ONLY, vinted: VINTED_ONLY, kleinanzeigen: EMPTY_OK })
    renderPopover()

    fireEvent.click(screen.getByText('open'))

    const grid = await screen.findByTestId('product-finder-results')
    expect(grid).toBeInTheDocument()
    expect(screen.getByText('Cleanser 200ml')).toBeInTheDocument()
    expect(screen.getByText('Cleanser 200ml (used)')).toBeInTheDocument()
  })

  it('sorts the combined grid by relevance across sources, not just within each source', async () => {
    // Retail's own listing is off-topic; Kleinanzeigen's (concatenated last)
    // is on-topic. The backend only sorts each source's response internally
    // — the popover must re-sort the combined list, or the off-topic retail
    // listing would stay first purely because Retail is concatenated first.
    const RETAIL_OFF_TOPIC: ProductFindResponse = {
      listings: [
        {
          type: 'new',
          title: 'Unrelated Skincare Guide',
          price: 5.0,
          currency: 'EUR',
          source: 'dm.de',
          thumbnail_url: null,
          listing_url: 'https://dm.de/guide',
        },
      ],
      retail_ok: true,
      secondhand_ok: false,
    }
    const KLEINANZEIGEN_ON_TOPIC: ProductFindResponse = {
      listings: [
        {
          type: 'used',
          title: 'Cleanser 200ml, kaum benutzt',
          price: 3.0,
          currency: 'EUR',
          source: 'Kleinanzeigen',
          thumbnail_url: null,
          listing_url: 'https://kleinanzeigen.de/cleanser',
        },
      ],
      retail_ok: false,
      secondhand_ok: true,
    }
    mockPerSource({ retail: RETAIL_OFF_TOPIC, vinted: EMPTY_OK, kleinanzeigen: KLEINANZEIGEN_ON_TOPIC })
    renderPopover('Cleanser')

    fireEvent.click(screen.getByText('open'))

    const grid = await screen.findByTestId('product-finder-results')
    const titles = within(grid).getAllByText(/Unrelated Skincare Guide|Cleanser 200ml, kaum benutzt/)
    expect(titles.map((el) => el.textContent)).toEqual([
      'Cleanser 200ml, kaum benutzt',
      'Unrelated Skincare Guide',
    ])
  })

  it('breaks a relevance/completeness tie by price, cheapest first', async () => {
    // Neither title contains the full query verbatim, both have a
    // thumbnail and a price - tied on every boolean component, so price
    // magnitude must decide the order.
    const RETAIL_EXPENSIVE: ProductFindResponse = {
      listings: [
        {
          type: 'new',
          title: 'Balea Cream for Very Dry Feet',
          price: 13.69,
          currency: 'EUR',
          source: 'amazon.it',
          thumbnail_url: 'https://x/expensive.jpg',
          listing_url: 'https://amazon.it/expensive',
        },
      ],
      retail_ok: true,
      secondhand_ok: false,
    }
    const KLEINANZEIGEN_CHEAP: ProductFindResponse = {
      listings: [
        {
          type: 'used',
          title: 'Balea Moisturizing Day Cream SPF 15',
          price: 8.49,
          currency: 'EUR',
          source: 'Kleinanzeigen',
          thumbnail_url: 'https://x/cheap.jpg',
          listing_url: 'https://kleinanzeigen.de/cheap',
        },
      ],
      retail_ok: false,
      secondhand_ok: true,
    }
    mockPerSource({ retail: RETAIL_EXPENSIVE, vinted: EMPTY_OK, kleinanzeigen: KLEINANZEIGEN_CHEAP })
    renderPopover('Balea Hydrating Cream')

    fireEvent.click(screen.getByText('open'))

    const grid = await screen.findByTestId('product-finder-results')
    const titles = within(grid).getAllByText(
      /Balea Cream for Very Dry Feet|Balea Moisturizing Day Cream SPF 15/
    )
    expect(titles.map((el) => el.textContent)).toEqual([
      'Balea Moisturizing Day Cream SPF 15',
      'Balea Cream for Very Dry Feet',
    ])
    // The cheaper (first-position) listing should also carry the badge.
    const badge = screen.getByText('Lowest price')
    const card = badge.closest('[data-slot="product-listing-card"]')
    expect(card).toHaveTextContent('Balea Moisturizing Day Cream SPF 15')
  })

  it('shows the "Lowest price" badge only on the cheapest listing across all sources combined', async () => {
    // Retail is 12.50, Vinted is 5.00 - the badge must land on the Vinted
    // card, not (incorrectly) be decided per-source.
    mockPerSource({ retail: RETAIL_ONLY, vinted: VINTED_CHEAPER, kleinanzeigen: EMPTY_OK })
    renderPopover()

    fireEvent.click(screen.getByText('open'))

    await screen.findByTestId('product-finder-results')
    const badges = screen.getAllByText('Lowest price')
    expect(badges).toHaveLength(1)
    const card = badges[0].closest('[data-slot="product-listing-card"]')
    expect(card).toHaveTextContent('Cleanser 200ml (used)')
  })

  it('shows no "Lowest price" badge when no listing across any source has a price', async () => {
    mockPerSource({ retail: EMPTY_OK, vinted: VINTED_ONLY, kleinanzeigen: EMPTY_OK })
    renderPopover()

    fireEvent.click(screen.getByText('open'))

    await screen.findByTestId('product-finder-results')
    expect(screen.queryByText('Lowest price')).not.toBeInTheDocument()
  })

  it('shows already-arrived listings immediately, before the other sources have settled', async () => {
    mockPerSource({ retail: RETAIL_ONLY }) // vinted/kleinanzeigen left pending
    renderPopover()

    fireEvent.click(screen.getByText('open'))

    expect(await screen.findByTestId('product-finder-results')).toBeInTheDocument()
    expect(screen.getByText('Cleanser 200ml')).toBeInTheDocument()
    expect(screen.queryByText('Cleanser 200ml (used)')).not.toBeInTheDocument()
    // Still waiting on the other two sources.
    expect(screen.getByTestId('product-finder-more-loading')).toBeInTheDocument()
  })

  it('appends more listings as additional sources resolve, and drops the trailing indicator once all have settled', async () => {
    const vintedStream = new FakeStream()
    fetchMockRef.mockImplementation((url: string) => {
      const source = sourceFromUrl(url)
      if (source === 'retail') {
        return Promise.resolve({ ok: true, status: 200, body: immediateStream(RETAIL_ONLY) } as unknown as Response)
      }
      if (source === 'vinted') {
        return Promise.resolve({ ok: true, status: 200, body: vintedStream } as unknown as Response)
      }
      return Promise.resolve({ ok: true, status: 200, body: immediateStream(EMPTY_OK) } as unknown as Response) // kleinanzeigen
    })
    renderPopover()

    fireEvent.click(screen.getByText('open'))

    expect(await screen.findByText('Cleanser 200ml')).toBeInTheDocument()
    expect(screen.getByTestId('product-finder-more-loading')).toBeInTheDocument()

    vintedStream.push(resultFrame(VINTED_ONLY))
    vintedStream.push(DONE_FRAME)
    vintedStream.close()

    expect(await screen.findByText('Cleanser 200ml (used)')).toBeInTheDocument()
    await waitFor(() =>
      expect(screen.queryByTestId('product-finder-more-loading')).not.toBeInTheDocument()
    )
  })

  it('shows the empty state, distinct from unavailable, when listings are empty but a source succeeded', async () => {
    mockPerSource({ retail: EMPTY_OK, vinted: EMPTY_NOT_OK, kleinanzeigen: EMPTY_NOT_OK })
    renderPopover()

    fireEvent.click(screen.getByText('open'))

    expect(await screen.findByTestId('product-finder-empty')).toBeInTheDocument()
    expect(screen.getByText('No listings found')).toBeInTheDocument()
    expect(screen.queryByTestId('product-finder-unavailable')).toBeNull()
    expect(screen.queryByText('Search temporarily unavailable')).toBeNull()
  })

  it('shows the unavailable state, distinct from empty, when every source failed', async () => {
    mockPerSource({ retail: EMPTY_NOT_OK, vinted: EMPTY_NOT_OK, kleinanzeigen: EMPTY_NOT_OK })
    renderPopover()

    fireEvent.click(screen.getByText('open'))

    expect(await screen.findByTestId('product-finder-unavailable')).toBeInTheDocument()
    expect(screen.getByText('Search temporarily unavailable')).toBeInTheDocument()
    expect(screen.queryByTestId('product-finder-empty')).toBeNull()
    expect(screen.queryByText('No listings found')).toBeNull()
  })

  it('shows the unavailable state when every source request itself errors', async () => {
    const err = new Error('network down')
    mockPerSource({ retail: err, vinted: err, kleinanzeigen: err })
    renderPopover()

    fireEvent.click(screen.getByText('open'))

    expect(await screen.findByTestId('product-finder-unavailable')).toBeInTheDocument()
  })

  it('closes the popover when closeFinder is invoked', async () => {
    mockPerSource({ retail: RETAIL_ONLY, vinted: VINTED_ONLY, kleinanzeigen: EMPTY_OK })
    renderPopover()

    fireEvent.click(screen.getByText('open'))
    expect(await screen.findByTestId('product-finder-results')).toBeInTheDocument()

    fireEvent.click(screen.getByText('close'))

    await waitFor(() => expect(screen.queryByTestId('product-finder-results')).toBeNull())
  })

  it('the header repeats the exact product name being searched', async () => {
    mockPerSource({ retail: RETAIL_ONLY, vinted: VINTED_ONLY, kleinanzeigen: EMPTY_OK })
    renderPopover('Vichy Mineral 89 Serum')

    fireEvent.click(screen.getByText('open'))

    expect(await screen.findByText('Vichy Mineral 89 Serum')).toBeInTheDocument()
  })

  it('closes the popover when the header close button is clicked', async () => {
    mockPerSource({ retail: RETAIL_ONLY, vinted: VINTED_ONLY, kleinanzeigen: EMPTY_OK })
    renderPopover()

    fireEvent.click(screen.getByText('open'))
    expect(await screen.findByTestId('product-finder-results')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Close' }))

    await waitFor(() => expect(screen.queryByTestId('product-finder-results')).toBeNull())
  })

  it('the header close button has a pointer cursor', async () => {
    mockPerSource({ retail: RETAIL_ONLY, vinted: VINTED_ONLY, kleinanzeigen: EMPTY_OK })
    renderPopover()

    fireEvent.click(screen.getByText('open'))

    const closeButton = await screen.findByRole('button', { name: 'Close' })
    expect(closeButton.className).toContain('cursor-pointer')
  })

  it('does not close when clicking outside the popover', async () => {
    mockPerSource({ retail: RETAIL_ONLY, vinted: VINTED_ONLY, kleinanzeigen: EMPTY_OK })
    renderPopover()

    fireEvent.click(screen.getByText('open'))
    expect(await screen.findByTestId('product-finder-results')).toBeInTheDocument()

    fireEvent.click(document.body)

    // Give any (incorrect) close handling a chance to run before asserting
    // the popover is still open.
    await new Promise((resolve) => setTimeout(resolve, 10))
    expect(screen.getByTestId('product-finder-results')).toBeInTheDocument()
  })

  it('drags the popover by pointer-dragging the header, offsetting it from its anchored position', async () => {
    mockPerSource({ retail: RETAIL_ONLY, vinted: VINTED_ONLY, kleinanzeigen: EMPTY_OK })
    renderPopover()

    fireEvent.click(screen.getByText('open'))
    await screen.findByTestId('product-finder-results')

    const header = screen.getByTestId('product-finder-header')
    const wrapper = screen.getByTestId('product-finder-drag-wrapper')
    expect(wrapper).toHaveStyle({ transform: 'translate(0px, 0px)' })

    fireEvent.pointerDown(header, { clientX: 100, clientY: 100 })
    fireEvent.pointerMove(header, { clientX: 140, clientY: 130 })
    fireEvent.pointerUp(header, { clientX: 140, clientY: 130 })

    expect(wrapper).toHaveStyle({ transform: 'translate(40px, 30px)' })
  })

  describe('location gate', () => {
    it('shows the loading state while the profile is still loading, without firing any product-finder request', async () => {
      mocks.apiGetProfile.mockReturnValue(new Promise<UserProfile>(() => {}))
      renderPopover()

      fireEvent.click(screen.getByText('open'))

      expect(await screen.findByTestId('product-finder-loading')).toBeInTheDocument()
      expect(fetchMockRef).not.toHaveBeenCalled()
    })

    it('shows a "set your location" prompt, without firing any product-finder request, when the profile has no location', async () => {
      mocks.apiGetProfile.mockResolvedValue({ ...PROFILE_WITH_LOCATION, location: null })
      renderPopover()

      fireEvent.click(screen.getByText('open'))

      expect(await screen.findByTestId('product-finder-no-location')).toBeInTheDocument()
      expect(screen.getByText('Location missing')).toBeInTheDocument()
      expect(screen.getByRole('link', { name: 'profile page' })).toHaveAttribute('href', '/profile')
      expect(fetchMockRef).not.toHaveBeenCalled()
    })

    it('treats a blank/whitespace-only location the same as no location', async () => {
      mocks.apiGetProfile.mockResolvedValue({ ...PROFILE_WITH_LOCATION, location: '   ' })
      renderPopover()

      fireEvent.click(screen.getByText('open'))

      expect(await screen.findByTestId('product-finder-no-location')).toBeInTheDocument()
    })

    it('closes the popover when the "profile page" link is clicked', async () => {
      mocks.apiGetProfile.mockResolvedValue({ ...PROFILE_WITH_LOCATION, location: null })
      renderPopover()

      fireEvent.click(screen.getByText('open'))
      await screen.findByTestId('product-finder-no-location')

      fireEvent.click(screen.getByRole('link', { name: 'profile page' }))

      await waitFor(() => expect(screen.queryByTestId('product-finder-no-location')).toBeNull())
    })

    it('proceeds with the normal search flow once the profile has a location', async () => {
      mockPerSource({ retail: RETAIL_ONLY, vinted: VINTED_ONLY, kleinanzeigen: EMPTY_OK })
      renderPopover()

      fireEvent.click(screen.getByText('open'))

      expect(await screen.findByTestId('product-finder-results')).toBeInTheDocument()
      expect(screen.queryByTestId('product-finder-no-location')).toBeNull()
    })
  })

  describe('live stage-phrase display (Req 10)', () => {
    it('shows only one stage phrase at a time — the first pending source\'s — not every source stacked', async () => {
      const retailStream = new FakeStream()
      const vintedStream = new FakeStream()
      const kleinanzeigenStream = new FakeStream() // never gets a stage event -> fallback
      mockPerSourceStreams({
        retail: retailStream,
        vinted: vintedStream,
        kleinanzeigen: kleinanzeigenStream,
      })
      renderPopover()

      fireEvent.click(screen.getByText('open'))
      await screen.findByTestId('product-finder-loading')

      retailStream.push(stageFrame('Checking dm.de...'))
      vintedStream.push(stageFrame('Checking vinted.de...'))

      // Retail is the first source, so its phrase leads the rotation; the
      // others are in the rotation set but not on screen simultaneously.
      await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Checking dm.de...'))
      expect(screen.queryByText('Checking vinted.de...')).toBeNull()
      expect(screen.queryByText('Searching...')).toBeNull()
    })

    it('rotates the status region to the next distinct phrase after the interval', async () => {
      const retailStream = new FakeStream()
      const vintedStream = new FakeStream()
      mockPerSourceStreams({ retail: retailStream, vinted: vintedStream })
      renderPopover()

      fireEvent.click(screen.getByText('open'))
      await screen.findByTestId('product-finder-loading')

      retailStream.push(stageFrame('Checking dm.de...'))
      vintedStream.push(stageFrame('Checking vinted.de...'))
      await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Checking dm.de...'))

      // After a full rotate+fade cycle the line advances to the next source's
      // phrase (kleinanzeigen is pending with the deduped "Searching..." too).
      await waitFor(
        () => expect(screen.getByRole('status')).toHaveTextContent('Checking vinted.de...'),
        { timeout: 5000 }
      )
    }, 7000)

    it('renders the phrase in a role="status" aria-live="polite" region', async () => {
      mockPerSource({}) // all three pending, no stage events pushed
      renderPopover()

      fireEvent.click(screen.getByText('open'))

      const status = await screen.findByRole('status')
      expect(status).toHaveAttribute('aria-live', 'polite')
    })

    it("a terminal event for one source drops its phrase from the rotation, leaving the others pending", async () => {
      const retailStream = new FakeStream()
      const vintedStream = new FakeStream()
      const kleinanzeigenStream = new FakeStream()
      mockPerSourceStreams({
        retail: retailStream,
        vinted: vintedStream,
        kleinanzeigen: kleinanzeigenStream,
      })
      renderPopover()

      fireEvent.click(screen.getByText('open'))
      await screen.findByTestId('product-finder-loading')

      retailStream.push(stageFrame('Checking dm.de...'))
      vintedStream.push(stageFrame('Checking vinted.de...'))
      await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Checking dm.de...'))

      // Retail reaches its terminal event with no listings; its phrase should
      // leave the rotation set even though the other two are still in flight.
      retailStream.push(resultFrame(EMPTY_NOT_OK))
      retailStream.push(DONE_FRAME)
      retailStream.close()

      // dm.de is gone from the rotation; the leading phrase is now vinted's,
      // and the loading state persists (results not yet shown).
      await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Checking vinted.de...'))
      expect(screen.queryByText('Checking dm.de...')).toBeNull()
      expect(screen.getByTestId('product-finder-loading')).toBeInTheDocument()
      expect(screen.queryByTestId('product-finder-results')).toBeNull()
    })
  })

  describe('dedupeStagePhrases', () => {
    it('drops duplicate phrases, preserving first-seen order', () => {
      expect(dedupeStagePhrases(['Checking dm.de...', 'Checking dm.de...', 'Assessing retailers']))
        .toEqual(['Checking dm.de...', 'Assessing retailers'])
    })

    it('maps a null (no stage event yet) to the "Searching..." fallback and dedupes those too', () => {
      expect(dedupeStagePhrases([null, null])).toEqual(['Searching...'])
      expect(dedupeStagePhrases(['Checking dm.de...', null])).toEqual([
        'Checking dm.de...',
        'Searching...',
      ])
    })
  })

  describe('RotatingStagePhrase', () => {
    beforeEach(() => vi.useFakeTimers())
    afterEach(() => vi.useRealTimers())

    it('shows a single phrase with no rotation, even after time passes', () => {
      render(<RotatingStagePhrase phrases={['Only one']} rotateMs={100} fadeMs={20} />)
      const status = screen.getByRole('status')
      expect(status).toHaveTextContent('Only one')
      expect(status.style.opacity).toBe('1')
      act(() => vi.advanceTimersByTime(1000))
      expect(status).toHaveTextContent('Only one')
    })

    it('rotates through phrases, fading the old one out before swapping the next in', () => {
      // interval = rotateMs + fadeMs = 120.
      render(<RotatingStagePhrase phrases={['A', 'B', 'C']} rotateMs={100} fadeMs={20} />)
      const status = screen.getByRole('status')
      expect(status).toHaveTextContent('A')
      expect(status.style.opacity).toBe('1')

      // Interval fires -> the OLD phrase fades out (opacity 0, text still 'A').
      act(() => vi.advanceTimersByTime(120))
      expect(status).toHaveTextContent('A')
      expect(status.style.opacity).toBe('0')

      // Fade-out done -> swap in 'B' and fade it back in.
      act(() => vi.advanceTimersByTime(20))
      expect(status).toHaveTextContent('B')
      expect(status.style.opacity).toBe('1')

      // Next interval: 'B' fades out, then 'C' fades in.
      act(() => vi.advanceTimersByTime(100))
      expect(status).toHaveTextContent('B')
      expect(status.style.opacity).toBe('0')
      act(() => vi.advanceTimersByTime(20))
      expect(status).toHaveTextContent('C')
      expect(status.style.opacity).toBe('1')
    })

    it('fades the shown phrase out when its source settles and it leaves the set, instead of snapping', () => {
      // A large rotate interval keeps rotation from interfering — this exercises
      // the disappear path specifically.
      const { rerender } = render(
        <RotatingStagePhrase phrases={['A', 'B']} rotateMs={100000} fadeMs={20} />
      )
      const status = screen.getByRole('status')
      expect(status).toHaveTextContent('A')
      expect(status.style.opacity).toBe('1')

      // 'A''s source finishes -> the set shrinks to just 'B'. The outgoing 'A'
      // fades out (opacity 0, text still 'A') rather than being replaced instantly.
      rerender(<RotatingStagePhrase phrases={['B']} rotateMs={100000} fadeMs={20} />)
      expect(status).toHaveTextContent('A')
      expect(status.style.opacity).toBe('0')

      act(() => vi.advanceTimersByTime(20))
      expect(status).toHaveTextContent('B')
      expect(status.style.opacity).toBe('1')
    })

    it('wraps the index into range (and fades) when the list shrinks below the current index', () => {
      const { rerender } = render(
        <RotatingStagePhrase phrases={['A', 'B', 'C']} rotateMs={100} fadeMs={20} />
      )
      const status = screen.getByRole('status')
      // Rotate to 'C' (index 2): each interval+fade advanced one step.
      act(() => vi.advanceTimersByTime(120))
      act(() => vi.advanceTimersByTime(20)) // -> 'B'
      act(() => vi.advanceTimersByTime(100))
      act(() => vi.advanceTimersByTime(20)) // -> 'C' (index 2)
      expect(status).toHaveTextContent('C')

      // Shrink to a single phrase while the index is past the new end: it must
      // wrap (2 % 1 = 0) and, after the fade, settle on the remaining phrase.
      rerender(<RotatingStagePhrase phrases={['Z']} rotateMs={100} fadeMs={20} />)
      act(() => vi.advanceTimersByTime(20))
      expect(status).toHaveTextContent('Z')
      expect(status.style.opacity).toBe('1')
    })
  })
})
