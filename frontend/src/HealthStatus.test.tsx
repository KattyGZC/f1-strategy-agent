import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { createApiClient } from './api/client.ts'
import { HealthStatus } from './HealthStatus.tsx'

const API_ORIGIN = 'http://api.test'

function respondWith(body: unknown, status: number): typeof fetch {
  return () =>
    Promise.resolve(
      new Response(JSON.stringify(body), {
        status,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
}

describe('HealthStatus', () => {
  it('shows the status the API returns', async () => {
    render(
      <HealthStatus client={createApiClient(API_ORIGIN, respondWith({ status: 'ok' }, 200))} />,
    )

    expect(await screen.findByText('API status: ok')).toBeInTheDocument()
  })

  it('shows the HTTP status when the API answers with an error', async () => {
    render(
      <HealthStatus client={createApiClient(API_ORIGIN, respondWith({ detail: 'down' }, 503))} />,
    )

    expect(await screen.findByRole('alert')).toHaveTextContent('API unreachable (HTTP 503)')
    expect(screen.queryByText(/API status/)).not.toBeInTheDocument()
  })

  it('reports the API as unreachable when the request fails', async () => {
    const failingFetch: typeof fetch = () => Promise.reject(new TypeError('network down'))

    render(<HealthStatus client={createApiClient(API_ORIGIN, failingFetch)} />)

    expect(await screen.findByRole('alert')).toHaveTextContent(/^API unreachable$/)
  })

  it('cancels the request when the component unmounts', () => {
    const requests: Request[] = []
    const pendingFetch: typeof fetch = (input) => {
      if (!(input instanceof Request)) {
        throw new TypeError('openapi-fetch is expected to pass a Request')
      }
      requests.push(input)
      return new Promise(() => {})
    }

    const { unmount } = render(<HealthStatus client={createApiClient(API_ORIGIN, pendingFetch)} />)
    unmount()

    expect(requests.map((request) => request.signal.aborted)).toEqual([true])
  })

  it('shows a loading message before the API answers', () => {
    const pendingFetch: typeof fetch = () => new Promise(() => {})

    render(<HealthStatus client={createApiClient(API_ORIGIN, pendingFetch)} />)

    expect(screen.getByText('Checking the API...')).toBeInTheDocument()
  })
})
