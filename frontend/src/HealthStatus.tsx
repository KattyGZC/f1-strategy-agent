import { useEffect, useState } from 'react'

import type { ApiClient } from './api/client.ts'
import type { components } from './api/schema.ts'

type HealthState =
  | { kind: 'loading' }
  | { kind: 'loaded'; health: components['schemas']['HealthResponse'] }
  | { kind: 'failed'; httpStatus: number | null }

export function HealthStatus({ client }: Readonly<{ client: ApiClient }>) {
  const [state, setState] = useState<HealthState>({ kind: 'loading' })

  useEffect(() => {
    const controller = new AbortController()
    client
      .GET('/api/health', { signal: controller.signal })
      .then(({ data, response }) =>
        setState(
          data ? { kind: 'loaded', health: data } : { kind: 'failed', httpStatus: response.status },
        ),
      )
      .catch(() => {
        if (!controller.signal.aborted) {
          setState({ kind: 'failed', httpStatus: null })
        }
      })
    return () => controller.abort()
  }, [client])

  switch (state.kind) {
    case 'loading':
      return <p>Checking the API...</p>
    case 'loaded':
      return <p>API status: {state.health.status}</p>
    case 'failed':
      return (
        <p role="alert">
          API unreachable{state.httpStatus === null ? '' : ` (HTTP ${state.httpStatus})`}
        </p>
      )
  }
}
