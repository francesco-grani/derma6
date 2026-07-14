import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react'

export interface ProductFinderTargetValue {
  /** True whenever a trigger has an open target — derived from `anchorEl`
   * being non-null, not tracked as separate state, so it can never drift
   * out of sync with `anchorEl`/`query`. */
  isOpen: boolean
  /** The trigger button `ProductFinderPopover` should anchor to, or `null`
   * when no finder is open. */
  anchorEl: HTMLElement | null
  /** The product name/search query for the open target, or `null` when no
   * finder is open. */
  query: string | null
  /** Opens (or re-anchors) the single global popover at `anchorEl` for
   * `query`. Always replaces any existing `anchorEl`/`query` rather than
   * stacking, so a new trigger click supersedes whatever target was
   * previously open (Req 3.5). */
  openFinder: (anchorEl: HTMLElement, query: string) => void
  /** Closes the popover and clears the open target. */
  closeFinder: () => void
}

const ProductFinderContext = createContext<ProductFinderTargetValue | null>(null)

/**
 * Holds the single, global "which trigger opened the product finder popover"
 * state. Intended to be mounted once, high in the tree (see AppLayout.tsx),
 * alongside the single globally-mounted `ProductFinderPopover` — every
 * `FindProductButton` across the app shares this one target via
 * `useProductFinderTarget()` instead of owning its own open/anchor state.
 */
export function ProductFinderProvider({ children }: { children: ReactNode }) {
  const [anchorEl, setAnchorEl] = useState<HTMLElement | null>(null)
  const [query, setQuery] = useState<string | null>(null)

  const openFinder = useCallback((nextAnchorEl: HTMLElement, nextQuery: string) => {
    // Replace, never stack: whatever target was previously open (if any) is
    // superseded by this one, satisfying Req 3.5 for the single global
    // popover instance.
    setAnchorEl(nextAnchorEl)
    setQuery(nextQuery)
  }, [])

  const closeFinder = useCallback(() => {
    setAnchorEl(null)
    setQuery(null)
  }, [])

  const value = useMemo<ProductFinderTargetValue>(
    () => ({
      isOpen: anchorEl !== null,
      anchorEl,
      query,
      openFinder,
      closeFinder,
    }),
    [anchorEl, query, openFinder, closeFinder]
  )

  return <ProductFinderContext.Provider value={value}>{children}</ProductFinderContext.Provider>
}

// The design (per design.md's Components and Interfaces table) pins the
// provider and its paired `useProductFinderTarget()` hook to this single
// file; splitting the hook into its own module purely to satisfy
// fast-refresh's single-export convention would contradict that explicit
// file layout for a dev-only hot-reload nicety.
// eslint-disable-next-line react-refresh/only-export-components
export function useProductFinderTarget(): ProductFinderTargetValue {
  const ctx = useContext(ProductFinderContext)
  if (!ctx) {
    throw new Error('useProductFinderTarget must be used inside ProductFinderProvider')
  }
  return ctx
}
