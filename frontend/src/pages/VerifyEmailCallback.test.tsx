import { afterEach, describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import type { ReactNode } from 'react'
import VerifyEmailCallback from './VerifyEmailCallback'

// `Link` requires a live `RouterProvider` context to resolve route info,
// which isn't set up in these component-level tests. Swap it for a plain
// anchor so `to`/`children` still render and are assertable, matching the
// same partial-mock approach used by `SignInPage.test.tsx`/`SignUpPage.test.tsx`.
vi.mock('@tanstack/react-router', async () => {
  const actual = await vi.importActual<typeof import('@tanstack/react-router')>('@tanstack/react-router')
  return {
    ...actual,
    Link: ({ to, children, ...props }: { to: string; children: ReactNode }) => (
      <a href={to} {...props}>
        {children}
      </a>
    ),
  }
})

afterEach(() => {
  // Reset the URL between tests since the component reads
  // `window.location.hash`/`search` on mount.
  window.history.pushState({}, '', '/verify-email-callback')
})

describe('VerifyEmailCallback', () => {
  it('renders a confirmed/verified state when no error params are present (Req 5.2)', () => {
    window.history.pushState({}, '', '/verify-email-callback')

    render(<VerifyEmailCallback />)

    expect(screen.getByTestId('verify-status')).toHaveTextContent('Email verified')
    expect(screen.getByText('Email verified — you can sign in.')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Continue to sign in' })).toHaveAttribute('href', '/login')
  })

  it('renders a distinguishable error state when Supabase appends an error param', () => {
    window.history.pushState(
      {},
      '',
      '/verify-email-callback#error=access_denied&error_description=Email+link+is+invalid+or+has+expired',
    )

    render(<VerifyEmailCallback />)

    expect(screen.getByTestId('verify-status')).toHaveTextContent('Verification failed')
    expect(screen.getByText('Email link is invalid or has expired')).toBeInTheDocument()
  })
})
