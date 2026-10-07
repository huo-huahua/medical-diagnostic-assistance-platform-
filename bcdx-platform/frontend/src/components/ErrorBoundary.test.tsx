import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import ErrorBoundary from '@/components/ErrorBoundary'

/**
 * The boundary is the difference between "one property read was wrong" and
 * "the entire application is a white screen". It earns its keep precisely when
 * nobody is watching, so it is the last thing that should go untested.
 */
const Boom = ({ fail }: { fail: boolean }) => {
  if (fail) throw new Error('boom: cannot read properties of undefined')
  return <p>the page rendered fine</p>
}

const renderBoundary = (fail: boolean, onReset?: () => void) =>
  render(
    <MemoryRouter>
      <ErrorBoundary label="测试区域" onReset={onReset}>
        <Boom fail={fail} />
      </ErrorBoundary>
    </MemoryRouter>,
  )

describe('ErrorBoundary', () => {
  it('renders children untouched when nothing throws', () => {
    renderBoundary(false)
    expect(screen.getByText('the page rendered fine')).toBeInTheDocument()
  })

  it('shows a recoverable panel instead of unmounting the tree', () => {
    // React logs the caught error; without silencing it the test output looks
    // like a failure when it is actually the thing under test.
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {})
    renderBoundary(true)

    expect(screen.getByText('这一部分未能正常显示')).toBeInTheDocument()
    expect(screen.getByText('测试区域', { exact: false })).toBeInTheDocument()
    spy.mockRestore()
  })

  it('names the crashed region so the report says where it happened', () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {})
    renderBoundary(true)
    expect(screen.getByText(/出错区域：测试区域/)).toBeInTheDocument()
    spy.mockRestore()
  })

  it('recovers once the underlying cause is gone, and calls onReset first', async () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {})
    const calls: string[] = []
    const onReset = vi.fn(() => calls.push('reset'))

    const view = (fail: boolean) => (
      <MemoryRouter>
        <ErrorBoundary label="测试区域" onReset={onReset}>
          <Boom fail={fail} />
        </ErrorBoundary>
      </MemoryRouter>
    )

    const { rerender } = render(view(true))
    expect(screen.getByText('这一部分未能正常显示')).toBeInTheDocument()

    // Fix the cause first, then retry. onReset runs before the error is
    // cleared, which is the whole point: clearing first would re-render
    // against the same bad data and throw again.
    rerender(view(false))
    await userEvent.click(screen.getByRole('button', { name: /重试/ }))

    expect(calls).toContain('reset')
    expect(screen.getByText('the page rendered fine')).toBeInTheDocument()
    spy.mockRestore()
  })

  it('keeps the panel up when a retry hits the same crash — it must not look like it worked', async () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {})
    renderBoundary(true)

    await userEvent.click(screen.getByRole('button', { name: /重试/ }))

    // The child still throws, so the boundary catches again. Claiming success
    // here would be the worse outcome: a user would think the retry fixed it.
    expect(screen.getByText('这一部分未能正常显示')).toBeInTheDocument()
    expect(screen.queryByText('the page rendered fine')).toBeNull()
    spy.mockRestore()
  })

  it('offers the error text for copying, since the panel is what a user can send', () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {})
    renderBoundary(true)
    // Read the <pre> directly: its text is split across several nodes, so a
    // text-query helper would not match even though the content is there.
    const details = document.querySelector('pre')
    expect(details?.textContent).toContain('boom: cannot read properties of undefined')
    expect(details?.textContent).toContain('组件调用栈')
    spy.mockRestore()
  })
})
