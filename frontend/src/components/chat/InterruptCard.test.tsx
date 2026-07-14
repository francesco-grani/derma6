import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import type { ReactNode } from 'react'

import InterruptCard, { type InterruptPayload, type PreviewRoutineStep } from './InterruptCard'
import { ProductFinderProvider } from '@/components/products/ProductFinderProvider'

function renderWithProvider(ui: ReactNode) {
  return render(<ProductFinderProvider>{ui}</ProductFinderProvider>)
}

function payloadWithRoutineSteps(items: PreviewRoutineStep[]): InterruptPayload {
  return {
    kind: 'routine_diff',
    title: 'Proposed routine change',
    options: [
      { value: 'approve', label: 'Approve' },
      { value: 'reject', label: 'Reject' },
    ],
    preview: { type: 'routine_steps', items },
  }
}

describe('InterruptCard "Find this product" triggers (Req 2)', () => {
  it('renders a trigger button for a non-empty `suggested` field', () => {
    const onResolve = vi.fn()
    const payload = payloadWithRoutineSteps([{ ingredient: 'retinol', suggested: 'Retinol Serum' }])

    renderWithProvider(<InterruptCard payload={payload} onResolve={onResolve} />)

    expect(screen.getAllByRole('button', { name: 'Find this product' })).toHaveLength(1)
  })

  it('renders a trigger button for a non-empty `budget` field', () => {
    const onResolve = vi.fn()
    const payload = payloadWithRoutineSteps([{ ingredient: 'retinol', budget: 'Budget Retinol' }])

    renderWithProvider(<InterruptCard payload={payload} onResolve={onResolve} />)

    expect(screen.getAllByRole('button', { name: 'Find this product' })).toHaveLength(1)
  })

  it('renders no trigger button when neither `suggested` nor `budget` is set', () => {
    const onResolve = vi.fn()
    const payload = payloadWithRoutineSteps([{ ingredient: 'retinol' }])

    renderWithProvider(<InterruptCard payload={payload} onResolve={onResolve} />)

    expect(screen.queryByRole('button', { name: 'Find this product' })).not.toBeInTheDocument()
  })

  it('renders two independent trigger buttons when both `suggested` and `budget` are set', () => {
    const onResolve = vi.fn()
    const payload = payloadWithRoutineSteps([
      { ingredient: 'retinol', suggested: 'Retinol Serum', budget: 'Budget Retinol' },
    ])

    renderWithProvider(<InterruptCard payload={payload} onResolve={onResolve} />)

    expect(screen.getAllByRole('button', { name: 'Find this product' })).toHaveLength(2)
  })

  it('clicking a "Find this product" trigger does not call onResolve or alter the pending approve/reject decision', () => {
    const onResolve = vi.fn()
    const payload = payloadWithRoutineSteps([
      { ingredient: 'retinol', suggested: 'Retinol Serum', budget: 'Budget Retinol' },
    ])

    renderWithProvider(<InterruptCard payload={payload} onResolve={onResolve} />)

    const [findButton] = screen.getAllByRole('button', { name: 'Find this product' })
    fireEvent.click(findButton)

    expect(onResolve).not.toHaveBeenCalled()

    // The submit ("→") button stays disabled — no option got selected as a
    // side effect of opening the product finder popover.
    const submitButton = screen.getByRole('button', { name: '→' })
    expect(submitButton).toBeDisabled()

    fireEvent.click(submitButton)
    expect(onResolve).not.toHaveBeenCalled()
  })

  it('approve/reject selection still works normally alongside the trigger buttons', () => {
    const onResolve = vi.fn()
    const payload = payloadWithRoutineSteps([
      { ingredient: 'retinol', suggested: 'Retinol Serum', budget: 'Budget Retinol' },
    ])

    renderWithProvider(<InterruptCard payload={payload} onResolve={onResolve} />)

    fireEvent.click(screen.getByRole('button', { name: 'Approve' }))
    fireEvent.click(screen.getByRole('button', { name: '→' }))

    expect(onResolve).toHaveBeenCalledWith('approve', '')
  })
})
