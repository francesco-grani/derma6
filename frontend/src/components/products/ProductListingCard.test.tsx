import { describe, expect, it } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { ProductListingCard, type ProductListing } from './ProductListingCard'

const BASE_LISTING: ProductListing = {
  type: 'new',
  title: 'Foo Cleanser 200ml',
  price: 12.99,
  currency: 'EUR',
  source: 'dm.de',
  thumbnail_url: 'https://example.com/thumb.jpg',
  listing_url: 'https://example.com/listing/123',
}

describe('ProductListingCard', () => {
  it('renders the price/currency line when price is non-null (Req 5.3)', () => {
    render(<ProductListingCard listing={BASE_LISTING} />)
    expect(screen.getByText(/12\.99/)).toBeInTheDocument()
    expect(screen.getByText(/EUR/)).toBeInTheDocument()
  })

  it('renders a "Price unavailable" fallback when price is null, but still renders source, thumbnail, and link (Req 5.4)', () => {
    const listing: ProductListing = {
      ...BASE_LISTING,
      price: null,
      currency: null,
    }
    render(<ProductListingCard listing={listing} />)

    // The price line always renders, even without a real price.
    expect(screen.getByText('Price unavailable')).toBeInTheDocument()
    expect(screen.queryByText(/EUR/)).not.toBeInTheDocument()

    // Source, thumbnail, and view-listing link are still present.
    expect(screen.getByText('dm.de')).toBeInTheDocument()
    expect(screen.getByRole('img', { name: listing.title })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /view listing/i })).toBeInTheDocument()
  })

  it('renders a placeholder icon (no <img>) when thumbnail_url is absent — no skeleton either, since there is nothing to wait for', () => {
    const listing: ProductListing = { ...BASE_LISTING, thumbnail_url: null }
    const { container } = render(<ProductListingCard listing={listing} />)

    expect(screen.queryByRole('img')).not.toBeInTheDocument()
    expect(
      container.querySelector('[data-slot="product-listing-thumbnail-placeholder"]')
    ).toBeInTheDocument()
    expect(
      container.querySelector('[data-slot="product-listing-thumbnail-skeleton"]')
    ).not.toBeInTheDocument()
    expect(screen.getByText('dm.de')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /view listing/i })).toBeInTheDocument()
  })

  it('shows a skeleton while a present thumbnail_url is still loading, and no placeholder yet', () => {
    const { container } = render(<ProductListingCard listing={BASE_LISTING} />)

    expect(
      container.querySelector('[data-slot="product-listing-thumbnail-skeleton"]')
    ).toBeInTheDocument()
    expect(
      container.querySelector('[data-slot="product-listing-thumbnail-placeholder"]')
    ).not.toBeInTheDocument()
  })

  it('hides the skeleton once the thumbnail image loads', () => {
    const { container } = render(<ProductListingCard listing={BASE_LISTING} />)
    const img = screen.getByRole('img', { name: BASE_LISTING.title })

    fireEvent.load(img)

    expect(
      container.querySelector('[data-slot="product-listing-thumbnail-skeleton"]')
    ).not.toBeInTheDocument()
    expect(
      container.querySelector('[data-slot="product-listing-thumbnail-placeholder"]')
    ).not.toBeInTheDocument()
  })

  it('falls back to the placeholder icon if the thumbnail image fails to load', () => {
    const { container } = render(<ProductListingCard listing={BASE_LISTING} />)
    const img = screen.getByRole('img', { name: BASE_LISTING.title })

    fireEvent.error(img)

    expect(
      container.querySelector('[data-slot="product-listing-thumbnail-placeholder"]')
    ).toBeInTheDocument()
    expect(
      container.querySelector('[data-slot="product-listing-thumbnail-skeleton"]')
    ).not.toBeInTheDocument()
  })

  it('the "view listing" link carries target="_blank" and rel="noopener noreferrer" (Req 5.7)', () => {
    render(<ProductListingCard listing={BASE_LISTING} />)
    const link = screen.getByRole('link', { name: /view listing/i })
    expect(link).toHaveAttribute('href', BASE_LISTING.listing_url)
    expect(link).toHaveAttribute('target', '_blank')
    expect(link).toHaveAttribute('rel', 'noopener noreferrer')
  })

  it('shows the "Lowest price" badge when isLowestPrice is true', () => {
    render(<ProductListingCard listing={BASE_LISTING} isLowestPrice />)
    expect(screen.getByText('Lowest price')).toBeInTheDocument()
  })

  it('does not show the "Lowest price" badge by default', () => {
    render(<ProductListingCard listing={BASE_LISTING} />)
    expect(screen.queryByText('Lowest price')).not.toBeInTheDocument()
  })

  it('renders no purchase/cart affordance anywhere on the card (Req 5.8)', () => {
    render(<ProductListingCard listing={BASE_LISTING} />)

    // No button elements at all (the only interactive element is the
    // "view listing" anchor), and no buy/cart/purchase copy anywhere.
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
    expect(screen.queryByText(/add to cart/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/buy now/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/purchase/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/checkout/i)).not.toBeInTheDocument()
  })
})
