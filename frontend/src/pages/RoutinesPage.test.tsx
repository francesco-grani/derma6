import { beforeEach, describe, expect, it, vi } from 'vitest'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import RoutinesPage from './RoutinesPage'
import type { Routine } from '@/lib/api'

// `Link`/`useNavigate` require a live `RouterProvider` context, which isn't
// set up in these component-level tests — same pattern as SignUpPage.test.tsx.
vi.mock('@tanstack/react-router', async () => {
  const actual = await vi.importActual<typeof import('@tanstack/react-router')>('@tanstack/react-router')
  return {
    ...actual,
    useNavigate: () => vi.fn(),
  }
})

// `vi.hoisted()` runs before the `vi.mock()` factories below (themselves
// hoisted above the imports), so these mock functions are safely available
// inside the factories without a TDZ error — same pattern as
// `lib/auth.test.tsx` / `lib/api.test.ts`.
const mocks = vi.hoisted(() => ({
  apiGetRoutines: vi.fn(),
  apiRenameRoutine: vi.fn(),
  apiDeleteRoutine: vi.fn(),
}))

vi.mock('@/lib/api', () => ({
  apiGetRoutines: mocks.apiGetRoutines,
  apiRenameRoutine: mocks.apiRenameRoutine,
  apiDeleteRoutine: mocks.apiDeleteRoutine,
}))

vi.mock('@/lib/auth', () => ({
  useAuth: () => ({ token: 'tok-abc', userId: 'uid-alice' }),
}))

vi.mock('@/lib/sessionContext', () => ({
  useSession: () => ({ startNewSession: vi.fn() }),
}))

const MORNING_ROUTINE: Routine = {
  name: 'Morning',
  steps: [{ position: 1, ingredient: 'cleanser', product_name: 'Foo Cleanser', budget_product: null }],
}

function renderWithProviders(ui: ReactNode) {
  const queryClient = new QueryClient()
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>)
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('RoutinesPage rename collision handling (security-remediation Req 25.3, 25.4)', () => {
  it('surfaces the 409 collision error from the backend instead of failing silently', async () => {
    mocks.apiGetRoutines.mockResolvedValue([MORNING_ROUTINE])
    mocks.apiRenameRoutine.mockRejectedValue(
      new Error("A routine named 'Evening' already exists (names must be unique, case-insensitive)."),
    )

    renderWithProviders(<RoutinesPage />)

    await waitFor(() => expect(screen.getByText('Morning')).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: 'Rename' }))

    const input = await screen.findByDisplayValue('Morning')
    fireEvent.change(input, { target: { value: 'evening' } })

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    })

    await waitFor(() =>
      expect(
        screen.getByText("A routine named 'Evening' already exists (names must be unique, case-insensitive)."),
      ).toBeInTheDocument(),
    )
    // The dialog stays open — this is a recoverable error, not a dead end.
    expect(screen.getByRole('button', { name: 'Save' })).toBeInTheDocument()
  })

  it('renames successfully and clears the dialog when there is no collision', async () => {
    mocks.apiGetRoutines.mockResolvedValue([MORNING_ROUTINE])
    mocks.apiRenameRoutine.mockResolvedValue(undefined)

    renderWithProviders(<RoutinesPage />)

    await waitFor(() => expect(screen.getByText('Morning')).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: 'Rename' }))

    const input = await screen.findByDisplayValue('Morning')
    fireEvent.change(input, { target: { value: 'AM Routine' } })

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    })

    await waitFor(() => expect(screen.queryByDisplayValue('AM Routine')).not.toBeInTheDocument())
    expect(mocks.apiRenameRoutine).toHaveBeenCalledWith('Morning', 'AM Routine')
  })
})
