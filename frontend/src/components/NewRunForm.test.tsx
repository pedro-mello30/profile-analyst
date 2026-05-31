import { describe, it, expect, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { NewRunForm } from './NewRunForm'

function wrapper({ children }: { children: React.ReactNode }) {
  return <QueryClientProvider client={new QueryClient()}>{children}</QueryClientProvider>
}

describe('NewRunForm', () => {
  it('renders handle input and stage radio options', () => {
    render(<NewRunForm onRunCreated={vi.fn()} />, { wrapper })
    expect(screen.getByPlaceholderText('instagram_handle')).toBeInTheDocument()
    expect(screen.getByLabelText(/all stages/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /run pipeline/i })).toBeInTheDocument()
  })

  it('calls onRunCreated with run data after successful submit', async () => {
    const onRunCreated = vi.fn()
    render(<NewRunForm onRunCreated={onRunCreated} />, { wrapper })

    await userEvent.type(screen.getByPlaceholderText('instagram_handle'), 'sample')
    await userEvent.click(screen.getByRole('button', { name: /run pipeline/i }))

    await waitFor(() => expect(onRunCreated).toHaveBeenCalledOnce())
    expect(onRunCreated).toHaveBeenCalledWith(
      expect.objectContaining({ run_id: 'abc123', handle: 'sample', status: 'queued' })
    )
  })

  it('does not submit when handle is empty', async () => {
    const onRunCreated = vi.fn()
    render(<NewRunForm onRunCreated={onRunCreated} />, { wrapper })
    await userEvent.click(screen.getByRole('button', { name: /run pipeline/i }))
    expect(onRunCreated).not.toHaveBeenCalled()
  })

  it('shows custom stages input when Custom is selected', async () => {
    render(<NewRunForm onRunCreated={vi.fn()} />, { wrapper })
    await userEvent.click(screen.getByLabelText(/custom/i))
    expect(screen.getByPlaceholderText(/e\.g\. 1,2,3,7/i)).toBeInTheDocument()
  })
})
