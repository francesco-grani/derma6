import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react'
import { Link } from '@tanstack/react-router'
import { AlertTriangle, Loader2, MapPin, SearchX, X } from 'lucide-react'

import {
  Popover,
  PopoverPopup,
  PopoverPortal,
  PopoverPositioner,
} from '@/components/ui/popover'
import { ProductListingCard } from '@/components/products/ProductListingCard'
import { useProductFinderTarget } from '@/components/products/ProductFinderProvider'
import {
  dedupeStagePhrases,
  STAGE_PHRASE_FADE_MS,
  STAGE_PHRASE_ROTATE_MS,
} from '@/components/products/stagePhrases'
import { useProductFind } from '@/hooks/useProductFinder'
import { useProfile } from '@/hooks/useProfile'
import { cn } from '@/lib/utils'
import type { ProductFindResponse } from '@/lib/api'

/**
 * The single globally-mounted product finder popover instance (design.md's
 * "one instance with dynamic anchor" decision — see Task 16/19 rationale).
 * Reads `ProductFinderProvider`'s context instead of rendering a co-located
 * `PopoverTrigger`: `PopoverPositioner`'s `anchor` prop is pointed directly
 * at the context's `anchorEl`, which Base UI's `useAnchorPositioning`
 * accepts as `Element | null | VirtualElement | RefObject | (() => ...)`
 * (see `@base-ui/react`'s `utils/useAnchorPositioning.d.ts`) — so a plain
 * externally-owned `HTMLElement | null` works directly, with no virtual
 * element or ref wrapper needed. Every `FindProductButton` across the app
 * just calls `openFinder(el, query)`, which repoints this single popover's
 * anchor and query (Req 3.5) rather than mounting its own `Popover.Root`.
 *
 * Visual treatment (chosen over the base `PopoverPopup` styling alone,
 * which read as flat against the routine page's own dark surface): a
 * branded header bar repeating the product name plus an explicit close
 * affordance, and a soft gold glow-ring border/shadow using the app's own
 * `#C4933F` accent (the same color as the "pick" badge elsewhere in the
 * app — see `RoutinesPage.tsx`'s `borderLeft: '4px solid #C4933F'` — no
 * new color introduced) so the panel reads as lifted off the page.
 * Fires one request per source (retail/Vinted/Kleinanzeigen) rather than
 * the combined endpoint, so results render as each source lands instead of
 * the whole popover waiting on the slowest one — see
 * `ProductFinderPopoverContent`'s merge logic below.
 *
 * Two deliberate deviations from Base UI's default popover behavior: it's
 * draggable (via `useDragOffset` below, dragging the header bar) so it can
 * be moved off whatever it's covering, and it does NOT close on an
 * outside click — only Escape or the header's close button dismiss it, so
 * an accidental click on the routine page behind it doesn't lose the
 * results mid-comparison.
 */
export function ProductFinderPopover() {
  const { isOpen, anchorEl, query, closeFinder } = useProductFinderTarget()

  // The backend's agentic source-discovery step (product-source-agent)
  // deliberately does nothing for a profile with no `location` set (it
  // treats that the same as an unrecognized location, never silently
  // defaulting to another country's sources) — every lookup would just come
  // back `retail_ok=false`/`secondhand_ok=false`. Checking this client-side
  // first avoids three guaranteed-empty network round trips and lets us
  // show an actionable "set your location" message instead of the generic
  // unavailable state.
  const profileQuery = useProfile()
  const hasLocation = Boolean(profileQuery.data?.location?.trim())
  const canSearch = isOpen && !profileQuery.isPending && hasLocation

  // `enabled: isOpen` (which Task 15's hook further ANDs with `!!name`) is
  // the only wiring needed for Req 7.2 ("discard in-memory state on close,
  // fresh lookup on reopen"): closing sets `isOpen` false, which disables
  // the query; reopening (even for the same product) flips `enabled` back
  // to true, and `useProductFind`'s `staleTime: 0` + `refetchOnMount:
  // 'always'` make TanStack Query treat the re-enabled query as stale, so it
  // refetches rather than silently serving a cached render. No extra
  // cleanup on close is required beyond this. `canSearch` further withholds
  // the query until the profile has loaded and has a location (above).
  const retailQuery = useProductFind(query, null, canSearch, 'retail')
  const vintedQuery = useProductFind(query, null, canSearch, 'vinted')
  const kleinanzeigenQuery = useProductFind(query, null, canSearch, 'kleinanzeigen')
  const drag = useDragOffset(isOpen)

  // The three per-source queries, merged once here so both the scrollable
  // results body and the pinned "searching more sources" overlay share the
  // exact same signal. The overlay lives OUTSIDE the scroll container (a
  // sibling of it, below), so it stays fixed on the popover's bottom edge —
  // and semi-transparent over the results — while the grid scrolls under it,
  // instead of the old trailing indicator that scrolled away with the content.
  const queries = [
    { label: 'Retail', ...retailQuery },
    { label: 'Vinted', ...vintedQuery },
    { label: 'Kleinanzeigen', ...kleinanzeigenQuery },
  ]
  const anyPending = queries.some((q) => q.isPending)
  const listingCount = queries.reduce((n, q) => n + (q.data?.listings?.length ?? 0), 0)
  // Show the overlay only once results are actually on screen (listingCount > 0
  // guarantees the content renders its grid, never a loading/empty/unavailable
  // state) AND another source is still in flight — the same condition the
  // trailing indicator used before it was lifted out of the scroll flow.
  const showMoreLoading =
    hasLocation && !profileQuery.isPending && listingCount > 0 && anyPending

  return (
    <Popover
      open={isOpen}
      onOpenChange={(open, eventDetails) => {
        // Base UI's Popover already handles outside-click and Escape
        // dismissal (Req 7.1, 7.2), but an accidental click on the routine
        // page behind this popover shouldn't lose the comparison results —
        // so only Escape/the header close button (any reason other than
        // "outside-press") actually closes it. Since this Popover is
        // controlled via `open={isOpen}`, simply not calling `closeFinder()`
        // is enough to keep it open — there's no internal state to revert.
        if (!open && eventDetails.reason === 'outside-press') {
          eventDetails.cancel()
          return
        }
        if (!open) {
          closeFinder()
        }
      }}
    >
      <PopoverPortal>
        <PopoverPositioner anchor={anchorEl} sideOffset={8}>
          {/* `PopoverPopup` itself stays visually transparent/frameless and
              only carries floating-ui's anchored position plus the
              open/close scale+fade animation. All the visible "frame" chrome
              (border, shadow, background, rounded corners, overflow clip)
              lives on this inner wrapper instead, which also carries the
              drag offset — so the whole card moves together as one piece
              when dragged, rather than the frame staying put while only the
              content slides underneath it. */}
          <PopoverPopup className="bg-transparent p-0 ring-0">
            <div
              data-testid="product-finder-drag-wrapper"
              className="relative overflow-hidden rounded-xl border border-[#C4933F]/50 bg-popover shadow-[0_0_0_5px_rgba(196,147,63,0.16),0_24px_50px_-14px_rgba(20,15,0,0.45)]"
              style={{ transform: `translate(${drag.offset.x}px, ${drag.offset.y}px)` }}
            >
              <PopoverHeader
                query={query}
                onClose={closeFinder}
                isDragging={drag.isDragging}
                dragHandlers={drag.handlers}
              />
              <div className="max-h-[min(420px,70vh)] overflow-y-auto p-3">
                <ProductFinderPopoverContent
                  queries={queries}
                  name={query}
                  profilePending={profileQuery.isPending}
                  hasLocation={hasLocation}
                  onNavigateToProfile={closeFinder}
                />
              </div>
              {/* Pinned "searching more sources" bar: a frosted-glass overlay
                  fixed to the popover's bottom edge, sitting outside the scroll
                  container above so it stays put — and semi-transparent over the
                  grid — while results scroll underneath it. */}
              {showMoreLoading && (
                <div
                  data-testid="product-finder-more-loading"
                  role="status"
                  aria-live="polite"
                  className="pointer-events-none absolute inset-x-0 bottom-0 flex items-center justify-center gap-1.5 border-t border-[#C4933F]/30 bg-popover/70 py-2 text-xs text-muted-foreground supports-backdrop-filter:backdrop-blur-sm"
                >
                  <Loader2 className="size-3 animate-spin" aria-hidden="true" />
                  <span>Searching more sources...</span>
                </div>
              )}
            </div>
          </PopoverPopup>
        </PopoverPositioner>
      </PopoverPortal>
    </Popover>
  )
}

/** Tracks a pixel offset applied on top of the popover's floating-ui
 * anchored position, driven by pointer-drag on the header bar. Lives on an
 * inner wrapper `div` rather than on `PopoverPopup` itself so it never
 * fights `PopoverPopup`'s own open/close animation transform. Resets to
 * `{0, 0}` whenever the popover closes, so it re-anchors cleanly on the
 * next open rather than reopening wherever it was last dragged to. */
function useDragOffset(isOpen: boolean) {
  const [offset, setOffset] = useState({ x: 0, y: 0 })
  const [isDragging, setIsDragging] = useState(false)
  // Resets `offset` when `isOpen` flips closed, following React's "adjusting
  // state when a prop changes" pattern (computed during render, not a
  // `useEffect`) — see https://react.dev/learn/you-might-not-need-an-effect.
  const [prevIsOpen, setPrevIsOpen] = useState(isOpen)
  const dragStart = useRef<{
    pointerX: number
    pointerY: number
    originX: number
    originY: number
  } | null>(null)

  if (isOpen !== prevIsOpen) {
    setPrevIsOpen(isOpen)
    if (!isOpen) {
      setOffset({ x: 0, y: 0 })
    }
  }

  const onPointerDown = (event: ReactPointerEvent<HTMLDivElement>) => {
    event.currentTarget.setPointerCapture?.(event.pointerId)
    dragStart.current = {
      pointerX: event.clientX,
      pointerY: event.clientY,
      originX: offset.x,
      originY: offset.y,
    }
    setIsDragging(true)
  }

  const onPointerMove = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (!dragStart.current) return
    setOffset({
      x: dragStart.current.originX + (event.clientX - dragStart.current.pointerX),
      y: dragStart.current.originY + (event.clientY - dragStart.current.pointerY),
    })
  }

  const onPointerUp = (event: ReactPointerEvent<HTMLDivElement>) => {
    dragStart.current = null
    setIsDragging(false)
    event.currentTarget.releasePointerCapture?.(event.pointerId)
  }

  return { offset, isDragging, handlers: { onPointerDown, onPointerMove, onPointerUp } }
}

/** Branded header bar: repeats the product name being searched (so the
 * popover still reads correctly if the routine list scrolls underneath
 * it) plus an explicit close button, on top of an outside-click/Escape
 * dismissal that Base UI's Popover already provides. Reuses the app's own
 * dark-green surface color (`#2E3D2F`, matching e.g. `Sidebar.tsx` and
 * every `Card` treatment across the app) rather than a new token. Also
 * doubles as the drag handle (`useDragOffset`'s pointer handlers) — the
 * close button stops pointerdown propagation so grabbing it doesn't also
 * start a drag.
 */
function PopoverHeader({
  query,
  onClose,
  isDragging,
  dragHandlers,
}: {
  query: string | null
  onClose: () => void
  isDragging: boolean
  dragHandlers: {
    onPointerDown: (event: ReactPointerEvent<HTMLDivElement>) => void
    onPointerMove: (event: ReactPointerEvent<HTMLDivElement>) => void
    onPointerUp: (event: ReactPointerEvent<HTMLDivElement>) => void
  }
}) {
  return (
    <div
      className={cn(
        'flex touch-none items-center gap-2 px-3.5 py-3 select-none',
        isDragging ? 'cursor-grabbing' : 'cursor-grab'
      )}
      style={{ background: '#2E3D2F', color: '#E0E8E0' }}
      data-testid="product-finder-header"
      {...dragHandlers}
    >
      <span className="truncate text-sm font-semibold">{query ?? 'Find this product'}</span>
      <button
        type="button"
        onClick={onClose}
        onPointerDown={(event) => event.stopPropagation()}
        aria-label="Close"
        className="ml-auto flex size-5 shrink-0 cursor-pointer items-center justify-center rounded-full bg-white/10 text-current hover:bg-white/20"
      >
        <X className="size-3" aria-hidden="true" />
      </button>
    </div>
  )
}

/** Ranks one listing for the combined results grid — mirrors the backend's
 * `_sort_by_relevance_and_completeness`/`_rank_listing`
 * (backend/tools/product_finder.py) exactly: name match, then brand match,
 * then thumbnail presence, then price presence, each ranking higher, then
 * (only once all four are tied) a numeric price-ascending tiebreaker — two
 * listings with identical relevance/completeness still need to resolve
 * deterministically by price, or the cheaper one has no reason to sort
 * first (verified live: two same-brand listings with identical scores
 * otherwise just kept their arbitrary per-source arrival order). "Match"
 * means the query name/brand appears verbatim (case-insensitive) in the
 * listing's title, not that the whole title equals the query — real
 * listing titles are full retailer page titles, so whole-string equality
 * would essentially never match anything. Brand is always `null` from this
 * component today (see the three `useProductFind` calls above), so that
 * component never penalizes any listing; kept as a parameter (rather than
 * hardcoded) so this stays a direct mirror of the backend function if a
 * brand ever gets threaded through here later. */
function rankListing(
  listing: { title: string; thumbnail_url: string | null; price: number | null },
  name: string | null,
  brand: string | null
): readonly [boolean, boolean, boolean, boolean, number] {
  const titleLower = listing.title.toLowerCase()
  const nameMatch = name === null || titleLower.includes(name.toLowerCase())
  const brandMatch = brand === null || titleLower.includes(brand.toLowerCase())
  const hasPrice = listing.price !== null
  // Negated so a *lower* price yields a *larger* rank value, consistent
  // with the boolean components above (a `true`/higher value ranks first).
  // Inert when there's no price: `hasPrice` already separates priced from
  // unpriced listings before this component is ever compared between them.
  const priceRank = listing.price !== null ? -listing.price : 0
  return [nameMatch, brandMatch, listing.thumbnail_url !== null, hasPrice, priceRank]
}

/** Sorts the *combined* cross-source listings so the most relevant and
 * complete results surface first. The backend's own sort only orders
 * listings within one source's response (each of the three streamed
 * per-source requests is sorted internally before it's returned), but the
 * three responses are otherwise just concatenated (Retail, then Vinted,
 * then Kleinanzeigen) here — this is what makes "most relevant + complete
 * on top" hold across all three sources together rather than only within
 * each one. `Array.prototype.sort` is stable per spec, so listings tied on
 * every ranked component keep their prior relative order. Recomputed on
 * every render (called from `listings.map`'s call site below, not memoized)
 * so the order keeps updating correctly as more sources stream in, rather
 * than freezing whatever partial order existed when the first source
 * landed. */
function sortByRelevanceAndCompleteness<
  T extends { title: string; thumbnail_url: string | null; price: number | null },
>(listings: T[], name: string | null, brand: string | null): T[] {
  return [...listings].sort((a, b) => {
    const scoreA = rankListing(a, name, brand)
    const scoreB = rankListing(b, name, brand)
    for (let i = 0; i < scoreA.length; i++) {
      if (scoreA[i] !== scoreB[i]) return scoreA[i] > scoreB[i] ? -1 : 1
    }
    return 0
  })
}

interface ProductFinderQueryState {
  isPending: boolean
  isError: boolean
  isSuccess: boolean
  data: ProductFindResponse | undefined
  /** Req 7.5, 10.1 — the in-flight request's most recently received stage
   * phrase, or `null` before the first one arrives or once the request has
   * reached its terminal event. */
  stagePhrase: string | null
}

/** Merges the three independent per-source queries into the idle -> loading
 * -> results/empty/unavailable state machine from design.md (Req 4, 5, 6),
 * rendering already-arrived listings immediately rather than waiting for
 * every source to settle. `allSettled`/`anyPending` are exact complements
 * over the same three queries, so together they cover every case: nothing
 * yet + still waiting -> full loading state; everything settled + nothing
 * found -> empty or unavailable (Req 6.5); anything found -> the grid,
 * with a small trailing indicator if other sources are still in flight.
 *
 * Gated ahead of all of that by the profile's `location`: while the profile
 * is still loading, show the same loading state; once loaded, a missing
 * location short-circuits straight to `NoLocationState` instead of ever
 * touching `queries` (the three requests are disabled in that case, per
 * `ProductFinderPopover`'s `canSearch`, so they'd sit pending forever). */
function ProductFinderPopoverContent({
  queries,
  name,
  profilePending,
  hasLocation,
  onNavigateToProfile,
}: {
  queries: (ProductFinderQueryState & { label: string })[]
  name: string | null
  profilePending: boolean
  hasLocation: boolean
  onNavigateToProfile: () => void
}) {
  if (profilePending) {
    return <LoadingState />
  }

  if (!hasLocation) {
    return <NoLocationState onNavigateToProfile={onNavigateToProfile} />
  }

  const anyPending = queries.some((q) => q.isPending)
  const allSettled = !anyPending
  const listings = sortByRelevanceAndCompleteness(
    queries.flatMap((q) => q.data?.listings ?? []),
    name,
    null
  )
  const anySourceOk = queries.some(
    (q) => q.isSuccess && q.data && (q.data.retail_ok || q.data.secondhand_ok)
  )
  // "Lowest price" is only meaningful relative to what's currently shown
  // across all three sources combined, not per-source — recomputed on every
  // render so a cheaper listing arriving from a still-streaming source
  // correctly moves the badge, no separate effect/memo needed.
  const pricedListings = listings.map((l) => l.price).filter((p): p is number => p !== null)
  const lowestPrice = pricedListings.length > 0 ? Math.min(...pricedListings) : null

  if (listings.length === 0 && anyPending) {
    // Req 10.2/10.3: only still-pending sources contribute a stage phrase — a
    // source whose stream already reached its terminal event (even with an
    // empty/failed result) drops out independent of the other two, since it's
    // no longer "in flight". Deduplicated by text (see `dedupeStagePhrases`) so
    // two sources reporting the same phrase collapse to one entry —
    // `LoadingState` then rotates through these one at a time.
    const phrases = dedupeStagePhrases(queries.filter((q) => q.isPending).map((q) => q.stagePhrase))
    return <LoadingState phrases={phrases} />
  }

  if (allSettled && listings.length === 0) {
    return anySourceOk ? <EmptyState /> : <UnavailableState />
  }

  // The "searching more sources" indicator for this results-with-pending case
  // is rendered by `ProductFinderPopover` as a frosted overlay pinned to the
  // popover's bottom edge — outside this scroll container — so it stays visible
  // while the grid scrolls. It intentionally lives there, not here.
  return (
    <div className="grid grid-cols-2 gap-2" data-testid="product-finder-results">
      {listings.map((listing) => (
        <ProductListingCard
          key={listing.listing_url}
          listing={listing}
          isLowestPrice={lowestPrice !== null && listing.price === lowestPrice}
        />
      ))}
    </div>
  )
}

/** Req 10.1/10.2: the still-pending sources' stage phrases, already
 * deduplicated by the caller. Rather than stacking every phrase at once (which
 * crowded the small popover when several sources were mid-flight), it shows one
 * at a time and rotates through them — see `RotatingStagePhrase`. When
 * `phrases` is omitted (the profile-still-loading gate, before any per-source
 * query has even started), falls back to a single generic message. Req 10.4:
 * the phrase is exposed to assistive technology via `role="status"
 * aria-live="polite"` (on the rotating node / the fallback). */
function LoadingState({ phrases }: { phrases?: string[] }) {
  return (
    <div
      className="flex flex-col items-center gap-2 py-6 text-muted-foreground"
      data-testid="product-finder-loading"
    >
      <Loader2 className="size-5 animate-spin" aria-hidden="true" />
      {phrases && phrases.length > 0 ? (
        <RotatingStagePhrase phrases={phrases} />
      ) : (
        <p role="status" aria-live="polite" className="text-sm">
          Searching...
        </p>
      )}
    </div>
  )
}

/** Shows one deduped stage phrase at a time so a small popover mid-search reads
 * as a single calm status line instead of a stack of competing ones. When
 * there's more than one phrase it rotates through them on a fixed interval, and
 * the same short opacity fade plays on EVERY change to the shown phrase — both
 * a rotation AND a phrase leaving the set (its source settled) — so an event
 * disappearing fades out rather than snapping. `displayed` is kept distinct
 * from the derived `desired` phrase precisely so the outgoing one can fade out
 * before the incoming one is painted; the fade is a straight fade-out →
 * swap-while-invisible → fade-in on one persistent node (no cross-fade
 * flicker), and `prefers-reduced-motion` collapses it to an instant swap.
 * Exported for direct unit testing. */
export function RotatingStagePhrase({
  phrases,
  rotateMs = STAGE_PHRASE_ROTATE_MS,
  fadeMs = STAGE_PHRASE_FADE_MS,
}: {
  phrases: string[]
  rotateMs?: number
  fadeMs?: number
}) {
  const [rotIndex, setRotIndex] = useState(0)
  // Wrap the index back into range if the list shrank past it (a source
  // settled and dropped out) — computed during render, no effect needed.
  const safeIndex = phrases.length > 0 ? rotIndex % phrases.length : 0
  const desired = phrases[safeIndex] ?? 'Searching...'

  const [displayed, setDisplayed] = useState(desired)
  const [visible, setVisible] = useState(true)
  const [swapping, setSwapping] = useState(false)

  // Begin the fade the instant the phrase that should be on screen changes —
  // whether from rotation or from the shown phrase's source finishing. This is
  // React's supported "adjust state when a derived value changes during render"
  // pattern (setState during render, guarded so it runs at most once per
  // change), which — unlike doing it in an effect — fades out without an
  // intermediate painted frame at the old opacity.
  if (desired !== displayed && visible && !swapping) {
    setVisible(false)
    setSwapping(true)
  }

  // Rotate the index on a fixed interval when there's more than one phrase.
  useEffect(() => {
    if (phrases.length <= 1) return
    const id = setInterval(() => setRotIndex((i) => i + 1), rotateMs + fadeMs)
    return () => clearInterval(id)
  }, [phrases.length, rotateMs, fadeMs])

  // Once the fade-out has run for `fadeMs`, swap in the (latest) desired phrase
  // and fade it back in.
  useEffect(() => {
    if (!swapping) return
    const id = setTimeout(() => {
      setDisplayed(desired)
      setVisible(true)
      setSwapping(false)
    }, fadeMs)
    return () => clearTimeout(id)
  }, [swapping, desired, fadeMs])

  return (
    <p
      role="status"
      aria-live="polite"
      className="text-center text-sm transition-opacity motion-reduce:transition-none"
      style={{ opacity: visible ? 1 : 0, transitionDuration: `${fadeMs}ms` }}
    >
      {displayed}
    </p>
  )
}

function NoLocationState({ onNavigateToProfile }: { onNavigateToProfile: () => void }) {
  return (
    <div
      className="flex flex-col items-center gap-2 py-6 text-center text-muted-foreground"
      data-testid="product-finder-no-location"
    >
      <MapPin className="size-5" aria-hidden="true" />
      <p className="text-sm font-medium text-foreground">Location missing</p>
      <p className="text-xs">
        Go to your{' '}
        <Link
          to="/profile"
          onClick={onNavigateToProfile}
          className="text-primary underline-offset-4 hover:underline"
        >
          profile page
        </Link>{' '}
        and set a location so we can find retailers and marketplaces near you.
      </p>
    </div>
  )
}

function EmptyState() {
  return (
    <div
      className="flex flex-col items-center gap-2 py-6 text-center text-muted-foreground"
      data-testid="product-finder-empty"
    >
      <SearchX className="size-5" aria-hidden="true" />
      <p className="text-sm font-medium text-foreground">No listings found</p>
      <p className="text-xs">We didn't find any retail or secondhand listings for this product.</p>
    </div>
  )
}

function UnavailableState() {
  return (
    <div
      className="flex flex-col items-center gap-2 py-6 text-center text-destructive"
      data-testid="product-finder-unavailable"
    >
      <AlertTriangle className="size-5" aria-hidden="true" />
      <p className="text-sm font-medium">Search temporarily unavailable</p>
      <p className="text-xs text-muted-foreground">
        We couldn't reach any product sources right now. Please try again shortly.
      </p>
    </div>
  )
}
