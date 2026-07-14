import { useRef } from 'react'

import { Button } from '@/components/ui/button'
import { useProductFinderTarget } from '@/components/products/ProductFinderProvider'

export interface FindProductButtonProps {
  /** The product name/search text to look up (e.g. `step.product_name`,
   * `step.budget_product`, `suggested`, or `budget`). Renders nothing when
   * falsy/empty (Req 1.2, 2.3). */
  query: string | null | undefined
}

/**
 * "Find this product" trigger button. Renders nothing when `query` is
 * falsy/empty; otherwise renders a small button that, on click, opens the
 * single global product finder popover anchored to itself with `query` as
 * the search term (Req 1.4, 2.5). Does not touch any surrounding
 * approve/reject or form state (Req 2.6).
 */
export function FindProductButton({ query }: FindProductButtonProps) {
  const buttonRef = useRef<HTMLButtonElement>(null)
  const { openFinder } = useProductFinderTarget()

  if (!query) {
    return null
  }

  return (
    <Button
      ref={buttonRef}
      type="button"
      size="sm"
      variant="outline"
      onClick={() => {
        if (buttonRef.current) {
          openFinder(buttonRef.current, query)
        }
      }}
    >
      Find this product
    </Button>
  )
}
