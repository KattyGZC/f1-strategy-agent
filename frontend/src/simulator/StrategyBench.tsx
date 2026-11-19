import { useReducer, useState } from 'react'

import type { ApiClient } from '../api/client.ts'
import type { components } from '../api/schema.ts'
import { MAX_TYRE_AGE_LAPS } from './bounds.ts'
import { benchReducer, newBench, sameRequest, simulationRequest } from './strategies.ts'
import { StrategyForm } from './StrategyForm.tsx'
import { StrategyResults } from './StrategyResults.tsx'
import { useSimulation, type Run } from './useSimulation.ts'

type Schemas = components['schemas']
type Compound = Schemas['CompoundResponse']

export interface Driver {
  driverNumber: number
  name: string
}

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
  const [run, simulate] = useSimulation(client)

  const request = simulationRequest(
    bench,
    model.session_key,
    driver === AVERAGE_CAR ? null : Number(driver),
  )
  const outdated = run.kind === 'done' && !sameRequest(run.sent, request)

  return (
    <section className="bench" aria-label="Strategies">
      <DriverSelect drivers={drivers} value={driver} onChange={setDriver} />
      <StrategyForm
        bench={bench}
        compounds={compounds.map(({ compound }) => compound)}
        dispatch={dispatch}
      />
      <button
        type="button"
        className="primary"
        disabled={request === null || run.kind === 'running'}
        onClick={request === null ? undefined : () => simulate(request)}
      >
        {run.kind === 'running' ? 'Simulating...' : 'Simulate'}
      </button>
      {request === null ? (
        <p className="muted small">
          Every stint needs its laps, at least 1, and the tyre&apos;s age at its start, 0 to{' '}
          {MAX_TYRE_AGE_LAPS}.
        </p>
      ) : null}
      <RunOutcome run={run} outdated={outdated} />
    </section>
  )
}

interface DriverSelectProps {
  drivers: Driver[]
  value: string
  onChange(value: string): void
}

function DriverSelect({ drivers, value, onChange }: Readonly<DriverSelectProps>) {
  return (
    <label className="field">
      <span className="label">Driver</span>
      <select value={value} onChange={(event) => onChange(event.target.value)}>
        <option value={AVERAGE_CAR}>The average car of the race</option>
        {drivers.map(({ driverNumber, name }) => (
          <option key={driverNumber} value={driverNumber}>
            {driverNumber} {name}
          </option>
        ))}
      </select>
    </label>
  )
}

function RunOutcome({ run, outdated }: Readonly<{ run: Run; outdated: boolean }>) {
  switch (run.kind) {
    case 'idle':
    case 'running':
      return null
    case 'failed':
      return (
        <p className="notice" role="alert">
          The simulation failed: {run.message}
        </p>
      )
    case 'done':
      return (
        <>
          {outdated ? (
            <p className="notice" role="status">
              The strategies or the driver changed since these results. Simulate again to update
              them.
            </p>
          ) : null}
          <StrategyResults simulation={run.simulation} outdated={outdated} />
        </>
      )
  }
}
