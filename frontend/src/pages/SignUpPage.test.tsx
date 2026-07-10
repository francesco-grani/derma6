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
  apiCheckUsername: vi.fn(),
  apiCompleteSignup: vi.fn(),
  signUp: vi.fn(),
}))

vi.mock('@/lib/api', () => ({
  apiCheckUsername: mocks.apiCheckUsername,
  apiCompleteSignup: mocks.apiCompleteSignup,
}))

vi.mock('@/lib/supabaseClient', () => ({
  supabase: {
    auth: {
      signUp: mocks.signUp,
    },
  },
}))

function fillForm({ email, username, password }: { email: string; username: string; password: string }) {
  fireEvent.change(screen.getByPlaceholderText('Email'), { target: { value: email } })
  fireEvent.change(screen.getByPlaceholderText('Username'), { target: { value: username } })
  fireEvent.change(screen.getByPlaceholderText('Password'), { target: { value: password } })
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('SignUpPage', () => {
  it('blocks submit while the chosen username is taken (Req 4.2, 4.3)', async () => {
    mocks.apiCheckUsername.mockResolvedValue(false)

    render(<SignUpPage />)
    fillForm({ email: 'bob@example.com', username: 'bob', password: 'MyPass1!' })

    // Debounced availability check (Req 4.2) resolves against the real
    // (non-fake) timer used by the component.
    await waitFor(() => expect(mocks.apiCheckUsername).toHaveBeenCalledWith('bob'))
    await waitFor(() => expect(screen.getByText('Username already taken')).toBeInTheDocument())
    expect(screen.getByRole('button', { name: 'Create account →' })).toBeDisabled()

    // Submitting the form while the button is disabled must not proceed to sign-up.
    fireEvent.submit(screen.getByRole('button', { name: 'Create account →' }).closest('form')!)
    expect(mocks.signUp).not.toHaveBeenCalled()
  })

  it('completes a full sign-up: availability confirmed → signUp() → completeSignup() → check-email screen', async () => {
    mocks.apiCheckUsername.mockResolvedValue(true)
    mocks.signUp.mockResolvedValue({ data: { user: { id: 'uuid-123' }, session: null }, error: null })
    mocks.apiCompleteSignup.mockResolvedValue({ user_id: 'uuid-123', username: 'newuser' })

    render(<SignUpPage />)
    fillForm({ email: 'newuser@example.com', username: 'newuser', password: 'MyPass1!' })

    await waitFor(() => expect(screen.getByText('Username available ✓')).toBeInTheDocument())
    const submitButton = screen.getByRole('button', { name: 'Create account →' })
    expect(submitButton).toBeEnabled()

    await act(async () => {
      fireEvent.click(submitButton)
    })

    await waitFor(() => {
      expect(mocks.signUp).toHaveBeenCalledWith({ email: 'newuser@example.com', password: 'MyPass1!' })
    })
    expect(mocks.apiCompleteSignup).toHaveBeenCalledWith('uuid-123', 'newuser@example.com', 'newuser')

    await waitFor(() => {
      expect(screen.getByText('Check your email to verify your account')).toBeInTheDocument()
    })
  })
})
