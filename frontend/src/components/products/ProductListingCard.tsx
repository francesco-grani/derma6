import { useState } from 'react'
import { ImageOff, Tag } from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { cn } from '@/lib/utils'
import type { ProductListing } from '@/lib/api'

export type { ProductListing }

type ThumbnailState = 'loading' | 'loaded' | 'error'

/**
 * Renders one `ProductListing` inside the product finder popover's results
 * grid (Req 5.1). Lookup-only: no purchase/cart/checkout affordance is
 * rendered anywhere on the card (Req 5.8).
 *
 * No "New"/"Used" badge — the type distinction wasn't earning its keep next
 * to the title (it's already implied by `source`, e.g. "Vinted" vs
 * "dm.de"), and dropping it frees up space for the title to wrap onto two
 * lines instead of truncating. A price line always renders, even when
 * `listing.price` is `None` (Req 5.4 already tolerates a missing price —
 * this just makes that case visible rather than silently omitting the row).
 *
 * `isLowestPrice` renders a "Lowest price" tag over the thumbnail — set by
 * the caller (comparing this listing's price against every other listing
 * currently shown across all sources, not just this one card's own data),
 * since "lowest" is only meaningful relative to the full result set. Uses
 * this app's own gold accent (`#C4933F` — the same color as the popover's
 * own border/glow in `ProductFinderPopover.tsx` and `RoutinesPage.tsx`'s
 * "pick" badge) as a solid fill with a shadow, not the pale
 * `#FFF3DC`/`#A0742A` chip tint that badge uses elsewhere: this tag needs to
 * read at a glance over a busy product photo, where a pale low-contrast
 * chip disappears.
 */
export function ProductListingCard({
  listing,
  isLowestPrice = false,
}: {
  listing: ProductListing
  isLowestPrice?: boolean
}) {
  const [thumbnailState, setThumbnailState] = useState<ThumbnailState>('loading')
  const hasThumbnailUrl = Boolean(listing.thumbnail_url)
  const showPlaceholder = !hasThumbnailUrl || thumbnailState === 'error'
  const showSkeleton = hasThumbnailUrl && thumbnailState === 'loading'

  return (
    <Card size="sm" data-slot="product-listing-card">
      <div
        className="relative aspect-square w-full overflow-hidden bg-muted"
        data-slot="product-listing-thumbnail"
      >
        {hasThumbnailUrl && (
          <img
            src={listing.thumbnail_url ?? undefined}
            alt={listing.title}
            className={cn(
              // `object-contain`, not `object-cover`: a product photo cropped
              // to fill the square can cut off part of the item, which is
              // worse than a bit of letterboxing for a lookup-only card.
              'h-full w-full object-contain transition-opacity duration-200',
              thumbnailState === 'loaded' ? 'opacity-100' : 'opacity-0'
            )}
            onLoad={() => setThumbnailState('loaded')}
            onError={() => setThumbnailState('error')}
          />
        )}
        {showSkeleton && (
          <div
            className="absolute inset-0 animate-pulse bg-muted-foreground/15"
            data-slot="product-listing-thumbnail-skeleton"
          />
        )}
        {showPlaceholder && (
          <div
            className="absolute inset-0 flex items-center justify-center"
            data-slot="product-listing-thumbnail-placeholder"
          >
            <ImageOff className="h-8 w-8 text-muted-foreground" aria-hidden="true" />
          </div>
        )}
        {isLowestPrice && (
          <span
            data-slot="product-listing-lowest-price-badge"
            className="absolute top-1.5 left-1.5 flex items-center gap-1 rounded-full px-2 py-1 text-xs font-bold tracking-wide text-white shadow-[0_2px_6px_rgba(20,15,0,0.35)]"
            style={{ background: '#C4933F' }}
          >
            <Tag className="size-3" aria-hidden="true" />
            Lowest price
          </span>
        )}
      </div>
      <CardContent className="flex flex-col gap-1.5">
        <span className="line-clamp-2 text-sm font-medium">{listing.title}</span>
        <p className="text-sm text-muted-foreground">
          {listing.price !== null
            ? `${listing.price.toFixed(2)}${listing.currency ? ` ${listing.currency}` : ''}`
            : 'Price unavailable'}
        </p>
        <p className="text-xs text-muted-foreground">{listing.source}</p>
        <a
          href={listing.listing_url}
          target="_blank"
          rel="noopener noreferrer"
          className="text-sm text-primary underline-offset-4 hover:underline"
        >
          View listing
        </a>
      </CardContent>
    </Card>
  )
}

