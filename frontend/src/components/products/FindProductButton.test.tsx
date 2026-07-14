import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import type { ReactNode } from 'react'

import { FindProductButton } from './FindProductButton'
import { ProductFinderProvider, useProductFinderTarget } from './ProductFinderProvider'

// Exposes the current global target so assertions can inspect what
// `openFinder` was called with (anchorEl/query), without reaching into
// ProductFinderProvider's internals.
function TargetSpy() {
  const { anchorEl, query } = useProductFinderTarget()
  return (
    <div data-testid="target-spy" data-anchor-tag={anchorEl?.tagName ?? ''} data-query={query ?? ''} />
  )
}

function renderWithProvider(ui: ReactNode) {
  return render(
    <ProductFinderProvider>
      {ui}
      <TargetSpy />
    </ProductFinderProvider>
  )
}

describe('FindProductButton', () => {
  it('renders nothing when query is empty/null/undefined', () => {
    const { container: emptyContainer } = renderWithProvider(<FindProductButton query="" />)
    expect(emptyContainer.querySelector('button')).toBeNull()

    const { container: nullContainer } = renderWithProvider(<FindProductButton query={null} />)
    expect(nullContainer.querySelector('button')).toBeNull()

    const { container: undefinedContainer } = renderWithProvider(
      <FindProductButton query={undefined} />
    )
    expect(undefinedContainer.querySelector('button')).toBeNull()
  })

  it('renders a "Find this product" button when query is non-empty', () => {
    renderWithProvider(<FindProductButton query="Retinol Serum" />)
    expect(screen.getByRole('button', { name: 'Find this product' })).toBeInTheDocument()
  })

  it('clicking the button calls openFinder with the button element and the query', () => {
    renderWithProvider(<FindProductButton query="Retinol Serum" />)

    const button = screen.getByRole('button', { name: 'Find this product' })
    fireEvent.click(button)

    const spy = screen.getByTestId('target-spy')
    expect(spy.dataset.query).toBe('Retinol Serum')
    expect(spy.dataset.anchorTag).toBe('BUTTON')
  })

  it('throws when rendered outside ProductFinderProvider', () => {
    // Suppress React's expected error-boundary console noise for this
    // specific assertion.
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {})
    expect(() => render(<FindProductButton query="Retinol Serum" />)).toThrow(
      'useProductFinderTarget must be used inside ProductFinderProvider'
    )
    consoleError.mockRestore()
  })
})
