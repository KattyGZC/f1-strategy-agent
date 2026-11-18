import { useEffect, useReducer, useRef, useState } from 'react'

import type { ApiClient } from '../api/client.ts'
import { failureMessage, UNREACHABLE } from '../api/errors.ts'
import type { components } from '../api/schema.ts'
import { MAX_TYRE_AGE_LAPS } from './bounds.ts'
import { benchReducer, newBench, simulationRequest } from './strategies.ts'
import { StrategyForm } from './StrategyForm.tsx'
import { StrategyResults } from './StrategyResults.tsx'

type Schemas = components['schemas']
type Compound = Schemas['CompoundResponse']

export interface Driver {
  driverNumber: number
  name: string
}

type Run =
  | { kind: 'idle' }
  | { kind: 'running' }
  | { kind: 'done'; simulation: Schemas['SimulationResponse'] }
  | { kind: 'failed'; message: string }

const AVERAGE_CAR = ''

interface Props {
  client: ApiClient
  model: Schemas['RaceModelResponse']
  compounds: readonly [Compound, ...Compound[]]
  drivers: Driver[]
}

export function StrategyBench({ client, model, compounds, drivers }: Readonly<Props>) {
  const [bench, dispatch] = useReducer(
    benchReducer,
    newBench(compounds[0].compound, model.race_laps),
  )
  const [driver, setDriver] = useState(AVERAGE_CAR)
  const [run, setRun] = useState<Run>({ kind: 'idle' })
  const inFlight = useRef<AbortController | null>(null)
  useEffect(() => () => inFlight.current?.abort(), [])

  const request = simulationRequest(
    bench,
    model.session_key,
    driver === AVERAGE_CAR ? null : Number(driver),
  )

  const simulate = async (body: Schemas['SimulationRequest']) => {
    const controller = new AbortController()
    inFlight.current = controller
    setRun({ kind: 'running' })
    try {
      const { data, error, response } = await client.POST('/api/simulations', {
        body,
        signal: controller.signal,
      })
      setRun(
        data
          ? { kind: 'done', simulation: data }
          : { kind: 'failed', message: failureMessage(error, response) },
      )
    } catch {
      if (!controller.signal.aborted) {
        setRun({ kind: 'failed', message: UNREACHABLE })
      }
    }
  }

  return (
    <section className="bench" aria-label="Strategies">
      <label className="field">
        <span className="label">Driver</span>
        <select value={driver} onChange={(event) => setDriver(event.target.value)}>
          <option value={AVERAGE_CAR}>The average car of the race</option>
          {drivers.map(({ driverNumber, name }) => (
            <option key={driverNumber} value={driverNumber}>
              {driverNumber} {name}
            </option>
          ))}
        </select>
      </label>
      <StrategyForm
        bench={bench}
        compounds={compounds.map(({ compound }) => compound)}
        dispatch={dispatch}
      />
      <button
        type="button"
        className="primary"
        disabled={request === null || run.kind === 'running'}
        onClick={request === null ? undefined : () => void simulate(request)}
      >
        {run.kind === 'running' ? 'Simulating...' : 'Simulate'}
      </button>
      {request === null ? (
        <p className="muted small">
          Every stint needs its laps, at least 1, and the tyre&apos;s age at its start, 0 to{' '}
          {MAX_TYRE_AGE_LAPS}.
        </p>
      ) : null}
      {run.kind === 'failed' ? (
        <p className="notice" role="alert">
          The simulation failed: {run.message}
        </p>
      ) : null}
      {run.kind === 'done' ? <StrategyResults simulation={run.simulation} /> : null}
    </section>
  )
}
