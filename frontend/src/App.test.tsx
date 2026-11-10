import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { createApiClient } from './api/client.ts'
import App from './App.tsx'
import { API_ORIGIN, fakeApi, fakeStreams, json, SESSION } from './testing.ts'

describe('App', () => {
  it('renders the title, the API status and the sessions to replay', async () => {
    const api = fakeApi({
      'GET /api/health': () => json({ status: 'ok' }),
      'GET /api/sessions': () => json([SESSION]),
    })

    render(
      <App
        apiClient={createApiClient(API_ORIGIN, api.fetchImpl)}
        openStream={fakeStreams().open}
      />,
    )

    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('F1 Strategy Agent')
    expect(await screen.findByText('API status: ok')).toBeInTheDocument()
    expect(await screen.findByRole('button', { name: 'Start replay' })).toBeInTheDocument()
  })
})
