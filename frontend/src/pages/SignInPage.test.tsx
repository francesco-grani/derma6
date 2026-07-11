import { beforeEach, describe, expect, it, vi } from 'vitest'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import SignInPage from './SignInPage'

const mocks = vi.hoisted(() => ({
  signInWithPassword: vi.fn(),
  resend: vi.fn(),
  navigate: vi.fn(),
}))

vi.mock('@/lib/supabaseClient', () => ({
  supabase: {
    auth: {
      signInWithPassword: mocks.signInWithPassword,
      resend: mocks.resend,
    },
  },
}))

vi.mock('@tanstack/react-router', async () => {
  const actual = await vi.importActual<typeof import('@tanstack/react-router')>('@tanstack/react-router')
  return {
    ...actual,
    useNavigate: () => mocks.navigate,
    // `Link` requires a live `RouterProvider` context, which isn't set up
    // in these component-level tests. Swap it for a plain anchor.
    Link: ({ to, children, ...props }: { to: string; children: ReactNode }) => (
      <a href={to} {...props}>
        {children}
      </a>
    ),
  }
})

function fillForm({ email, password }: { email: string; password: string }) {
  fireEvent.change(screen.getByPlaceholderText('Email'), { target: { value: email } })
  fireEvent.change(screen.getByPlaceholderText('Password'), { target: { value: password } })
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('SignInPage', () => {
  it('shows a distinguishable unverified-email message with a resend action (Req 5.3)', async () => {
    mocks.signInWithPassword.mockResolvedValue({
      data: { user: null, session: null },
      error: { code: 'email_not_confirmed', message: 'Email not confirmed', name: 'AuthApiError', status: 400 },
    })
    mocks.resend.mockResolvedValue({ data: {}, error: null })

    render(<SignInPage />)
    fillForm({ email: 'unverified@example.com', password: 'MyPass1!' })

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Sign in →' }))
    })

    await waitFor(() => {
      expect(
        screen.getByText("Your email hasn't been verified yet. Check your inbox for the verification link."),
      ).toBeInTheDocument()
    })
    // Should not be shown as a generic/undistinguished error message.
    expect(screen.queryByText('Email not confirmed')).not.toBeInTheDocument()
    expect(mocks.navigate).not.toHaveBeenCalled()

    const resendButton = screen.getByRole('button', { name: 'Resend verification email' })
    await act(async () => {
      fireEvent.click(resendButton)
    })

    await waitFor(() => {
      expect(mocks.resend).toHaveBeenCalledWith({
        type: 'signup',
        email: 'unverified@example.com',
        options: { emailRedirectTo: `${window.location.origin}/verify-email-callback` },
      })
    })
    await waitFor(() => {
      expect(screen.getByText('Verification email resent ✓')).toBeInTheDocument()
    })
  })

  it('signs in successfully and navigates to /chat', async () => {
    mocks.signInWithPassword.mockResolvedValue({
      data: { user: { id: 'uuid-1' }, session: { access_token: 'tok' } },
      error: null,
    })

    render(<SignInPage />)
    fillForm({ email: 'alice@example.com', password: 'MyPass1!' })

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Sign in →' }))
    })

    await waitFor(() => expect(mocks.navigate).toHaveBeenCalledWith({ to: '/chat' }))
  })

  it('shows a generic error for non-unconfirmed-email failures', async () => {
    mocks.signInWithPassword.mockResolvedValue({
      data: { user: null, session: null },
      error: { code: 'invalid_credentials', message: 'Invalid login credentials', name: 'AuthApiError', status: 400 },
    })

    render(<SignInPage />)
    fillForm({ email: 'bob@example.com', password: 'wrong' })

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Sign in →' }))
    })

    await waitFor(() => {
      expect(screen.getByText('Invalid login credentials')).toBeInTheDocument()
    })
    expect(
      screen.queryByText("Your email hasn't been verified yet. Check your inbox for the verification link."),
    ).not.toBeInTheDocument()
  })
})
