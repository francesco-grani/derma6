import { beforeEach, describe, expect, it, vi } from 'vitest'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import SignUpPage from './SignUpPage'

// `Link` requires a live `RouterProvider` context, which isn't set up in
// these component-level tests. Swap it for a plain anchor.
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

// `vi.hoisted()` runs before the `vi.mock()` factories below (themselves
// hoisted above the imports), so these mock functions are safely available
// inside the factories without a TDZ error — same pattern as
// `lib/auth.test.tsx` / `lib/api.test.ts`.
const mocks = vi.hoisted(() => ({
  apiCompleteSignup: vi.fn(),
  signUp: vi.fn(),
}))

vi.mock('@/lib/api', () => ({
  apiCompleteSignup: mocks.apiCompleteSignup,
}))

vi.mock('@/lib/supabaseClient', () => ({
  supabase: {
    auth: {
      signUp: mocks.signUp,
    },
  },
}))

function fillForm({ email, firstName, password }: { email: string; firstName: string; password: string }) {
  fireEvent.change(screen.getByPlaceholderText('Email'), { target: { value: email } })
  fireEvent.change(screen.getByPlaceholderText('First name'), { target: { value: firstName } })
  fireEvent.change(screen.getByPlaceholderText('Password'), { target: { value: password } })
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('SignUpPage', () => {
  it('blocks submit while the first-name field is empty', async () => {
    render(<SignUpPage />)
    fillForm({ email: 'bob@example.com', firstName: '', password: 'MyPass1!' })

    expect(screen.getByRole('button', { name: 'Create account →' })).toBeDisabled()

    // Submitting the form while the button is disabled must not proceed to sign-up.
    fireEvent.submit(screen.getByRole('button', { name: 'Create account →' }).closest('form')!)
    expect(mocks.signUp).not.toHaveBeenCalled()
  })

  it('completes a full sign-up: signUp() → completeSignup() → check-email screen', async () => {
    mocks.signUp.mockResolvedValue({ data: { user: { id: 'uuid-123' }, session: null }, error: null })
    mocks.apiCompleteSignup.mockResolvedValue({ user_id: 'uuid-123', username: 'newuser' })

    render(<SignUpPage />)
    fillForm({ email: 'newuser@example.com', firstName: 'newuser', password: 'MyPass1!' })

    const submitButton = screen.getByRole('button', { name: 'Create account →' })
    expect(submitButton).toBeEnabled()

    await act(async () => {
      fireEvent.click(submitButton)
    })

    await waitFor(() => {
      expect(mocks.signUp).toHaveBeenCalledWith({
        email: 'newuser@example.com',
        password: 'MyPass1!',
        options: { emailRedirectTo: `${window.location.origin}/verify-email-callback` },
      })
    })
    expect(mocks.apiCompleteSignup).toHaveBeenCalledWith('uuid-123', 'newuser@example.com', 'newuser')

    await waitFor(() => {
      expect(screen.getByText('Check your email to verify your account')).toBeInTheDocument()
    })
  })
})
