import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import {
  Popover,
  PopoverPopup,
  PopoverPortal,
  PopoverPositioner,
  PopoverTrigger,
} from './popover'

// Smoke test for the popover.tsx wrapper (design.md's ui/popover.tsx, Req
// 3.1-3.4, 8.1). Unlike dialog.tsx, this wrapper deliberately does not export
// a `PopoverOverlay`/`Backdrop` component, so the page is never dimmed behind
// an open popover (Req 3.2) — this test guards that behavior.
describe('popover.tsx', () => {
  it('renders no backdrop/overlay element when open, and PopoverPopup carries the viewport width cap class', async () => {
    render(
      <Popover open>
        <PopoverTrigger>Find this product</PopoverTrigger>
        <PopoverPortal>
          <PopoverPositioner>
            <PopoverPopup data-testid="popover-popup">Results</PopoverPopup>
          </PopoverPositioner>
        </PopoverPortal>
      </Popover>
    )

    const popup = await screen.findByTestId('popover-popup')
    expect(popup).toBeInTheDocument()

    // Req 3.2: no full-screen dimming layer — this wrapper never renders
    // Base UI's `Popover.Backdrop`, unlike `dialog.tsx`'s `DialogOverlay`.
    expect(document.querySelector('[data-slot="popover-backdrop"]')).toBeNull()
    expect(document.querySelector('[data-slot="popover-overlay"]')).toBeNull()
    expect(document.querySelector('[class*="backdrop"]')).toBeNull()

    // Req 8.1: the popup caps its width so it can't exceed the viewport on
    // small screens.
    expect(popup.className).toContain('max-w-[calc(100vw-2rem)]')
  })
})
