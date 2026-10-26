import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { createApiClient } from './api/client.ts'
import App from './App.tsx'

describe('App', () => {
  it('renders the title and the API status', async () => {
    const healthyFetch: typeof fetch = () =>
      Promise.resolve(
        new Response(JSON.stringify({ status: 'ok' }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      )

    render(<App apiClient={createApiClient('http://api.test', healthyFetch)} />)

    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('F1 Strategy Agent')
    expect(await screen.findByText('API status: ok')).toBeInTheDocument()
  })
})
