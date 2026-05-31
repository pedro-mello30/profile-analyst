import { describe, it, expect } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AskPanel } from './AskPanel'

function wrapper({ children }: { children: React.ReactNode }) {
  return <QueryClientProvider client={new QueryClient()}>{children}</QueryClientProvider>
}

describe('AskPanel', () => {
  it('renders handle input, question input, and submit button', () => {
    render(<AskPanel />, { wrapper })
    expect(screen.getByPlaceholderText('instagram_handle')).toBeInTheDocument()
    expect(screen.getByPlaceholderText(/ask anything/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /execute query/i })).toBeInTheDocument()
  })

  it('renders answer and cypher block after successful query', async () => {
    render(<AskPanel />, { wrapper })
    await userEvent.type(screen.getByPlaceholderText('instagram_handle'), 'sample')
    await userEvent.type(screen.getByPlaceholderText(/ask anything/i), 'list creators')
    await userEvent.click(screen.getByRole('button', { name: /execute query/i }))

    await waitFor(() => expect(screen.getByText('mock answer')).toBeInTheDocument())
    expect(screen.getByText(/MATCH/)).toBeInTheDocument()
    expect(screen.getByText(/1 ROW RETURNED/i)).toBeInTheDocument()
  })

  it('does not submit when question is empty', async () => {
    render(<AskPanel />, { wrapper })
    const btn = screen.getByRole('button', { name: /execute query/i })
    expect(btn).toBeDisabled()
  })
})
