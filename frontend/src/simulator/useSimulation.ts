import { useEffect, useRef, useState } from 'react'

import type { ApiClient } from '../api/client.ts'
import { failureMessage, UNREACHABLE } from '../api/errors.ts'
import type { components } from '../api/schema.ts'

type Schemas = components['schemas']
export type SimulationRequest = Schemas['SimulationRequest']

/** Each answer keeps the request it answers, so the screen can tell when the form moved on. */
export type Run =
  | { kind: 'idle' }
  | { kind: 'running'; sent: SimulationRequest }
  | { kind: 'done'; sent: SimulationRequest; simulation: Schemas['SimulationResponse'] }
  | { kind: 'failed'; sent: SimulationRequest; message: string }

/** The last simulation asked for and its answer; leaving the screen drops one still running. */
export function useSimulation(client: ApiClient): [Run, (request: SimulationRequest) => void] {
  const [run, setRun] = useState<Run>({ kind: 'idle' })
  const inFlight = useRef<AbortController | null>(null)
  useEffect(() => () => inFlight.current?.abort(), [])

  const simulate = (sent: SimulationRequest) => {
    const controller = new AbortController()
    inFlight.current = controller
    setRun({ kind: 'running', sent })
    client
      .POST('/api/simulations', { body: sent, signal: controller.signal })
      .then(({ data, error, response }) =>
        setRun(
          data
            ? { kind: 'done', sent, simulation: data }
            : { kind: 'failed', sent, message: failureMessage(error, response) },
        ),
      )
      .catch(() => {
        if (!controller.signal.aborted) {
          setRun({ kind: 'failed', sent, message: UNREACHABLE })
        }
      })
  }

  return [run, simulate]
}
