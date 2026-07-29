import '@testing-library/jest-dom/vitest'
import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'
import App from './App'

describe('App', () => {
  beforeEach(() => {
    Object.defineProperty(window, 'desktopApi', {
      configurable: true,
      value: {
        platform: 'win32',
        versions: { chrome: '1.0.0', electron: '43.2.0', node: '24.6.0' }
      }
    })
  })

  it('renders the secure desktop shell and runtime information', () => {
    render(<App />)

    expect(screen.getByTestId('desktop-root')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '桌面端基础框架已就绪' })).toBeInTheDocument()
    expect(screen.getByText('43.2.0')).toBeInTheDocument()
    expect(screen.getByText('win32')).toBeInTheDocument()
  })
})
