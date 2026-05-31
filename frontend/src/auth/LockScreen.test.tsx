import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { LockScreen } from './LockScreen'

describe('LockScreen', () => {
  beforeEach(() => sessionStorage.clear())

  it('renders the password input and unlock button', async () => {
    render(<LockScreen onUnlock={vi.fn()} />)
    // input appears after boot sequence completes (~1.5 s) — wait for it
    await waitFor(
      () => expect(screen.getByPlaceholderText('Enter token to authenticate')).toBeInTheDocument(),
      { timeout: 3000 }
    )
    expect(screen.getByRole('button', { name: /authenticate/i })).toBeInTheDocument()
  })

  it('stores token in sessionStorage and calls onUnlock on submit', async () => {
    const onUnlock = vi.fn()
    render(<LockScreen onUnlock={onUnlock} />)

    // Wait until the input is enabled (boot sequence finished, showInput=true)
    const input = await waitFor(
      () => {
        const el = screen.getByPlaceholderText('Enter token to authenticate')
        expect(el).not.toBeDisabled()
        return el
      },
      { timeout: 3000 }
    )
    await userEvent.type(input, 'my-secret')
    await userEvent.click(screen.getByRole('button', { name: /authenticate/i }))

    expect(sessionStorage.getItem('pa_token')).toBe('my-secret')
    expect(onUnlock).toHaveBeenCalledOnce()
  })

  it('does not call onUnlock when input is empty', async () => {
    const onUnlock = vi.fn()
    render(<LockScreen onUnlock={onUnlock} />)

    await waitFor(
      () => screen.getByRole('button', { name: /authenticate/i }),
      { timeout: 3000 }
    )
    await userEvent.click(screen.getByRole('button', { name: /authenticate/i }))
    expect(onUnlock).not.toHaveBeenCalled()
  })
})
