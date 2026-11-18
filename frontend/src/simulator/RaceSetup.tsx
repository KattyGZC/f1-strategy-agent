import { useEffect, useState } from 'react'

import type { ApiClient } from '../api/client.ts'
import { failureMessage, UNREACHABLE } from '../api/errors.ts'
import type { components } from '../api/schema.ts'
import { COMPOUND_LOOK } from '../replay/look.ts'
import { formatSeconds } from '../replay/format.ts'
import { StrategyBench, type Driver } from './StrategyBench.tsx'

type Schemas = components['schemas']
type Race = Schemas['RaceResponse']
type RaceModel = Schemas['RaceModelResponse']
type Compound = Schemas['CompoundResponse']

type SetupState =
  | { kind: 'loading' }
  | {
      kind: 'loaded'
      model: RaceModel
      compounds: readonly [Compound, ...Compound[]]
      drivers: Driver[]
    }
  | { kind: 'failed'; message: string }

interface Props {
  client: ApiClient
  race: Race
}

/** The race's model, and its drivers by name: the model only numbers them. */
export function RaceSetup({ client, race }: Readonly<Props>) {
  const [setup, setSetup] = useState<SetupState>({ kind: 'loading' })

  useEffect(() => {
    const controller = new AbortController()
    const params = {
      params: { path: { session_key: race.session_key } },
      signal: controller.signal,
    }
    Promise.all([
      client.GET('/api/races/{session_key}', params),
      client.GET('/api/sessions/{session_key}', params),
    ])
      .then(([model, entry]) => {
        if (!model.data) {
          return setSetup({ kind: 'failed', message: failureMessage(model.error, model.response) })
        }
        if (!entry.data) {
          return setSetup({ kind: 'failed', message: failureMessage(entry.error, entry.response) })
        }
        const [first, ...rest] = model.data.compounds
        if (first === undefined) {
          return setSetup({ kind: 'failed', message: 'the race has no calibrated compound' })
        }
        const named = new Map(entry.data.drivers.map((driver) => [driver.driver_number, driver]))
        const drivers = model.data.driver_numbers.map((driverNumber) => ({
          driverNumber,
          name: named.get(driverNumber)?.full_name ?? `Car ${driverNumber}`,
        }))
        return setSetup({ kind: 'loaded', model: model.data, compounds: [first, ...rest], drivers })
      })
      .catch(() => {
        if (!controller.signal.aborted) {
          setSetup({ kind: 'failed', message: UNREACHABLE })
        }
      })
    return () => controller.abort()
  }, [client, race.session_key])

  switch (setup.kind) {
    case 'loading':
      return <p className="notice">Loading the race&apos;s model...</p>
    case 'failed':
      return (
        <p className="notice" role="alert">
          Could not read the race: {setup.message}
        </p>
      )
    case 'loaded':
      return (
        <div className="race-setup">
          <RaceModelPanel race={race} model={setup.model} />
          <StrategyBench
            client={client}
            model={setup.model}
            compounds={setup.compounds}
            drivers={setup.drivers}
          />
        </div>
      )
  }
}

function RaceModelPanel({ race, model }: Readonly<{ race: Race; model: RaceModel }>) {
  const { pit_loss: pitLoss, track_temperature: temperature } = model
  return (
    <aside className="panel race-model" aria-label="The race's model">
      <span className="label">
        {race.country_name}, {race.circuit_short_name}
      </span>
      <h3>{race.meeting_name}</h3>
      <dl className="facts">
        <dt>Laps</dt>
        <dd className="mono">{model.race_laps}</dd>
        <dt>Pit loss</dt>
        <dd className="mono">{pitLossFact(pitLoss)}</dd>
        <dt>Track temperature</dt>
        <dd className="mono">
          {temperature === null
            ? 'not recorded'
            : `${temperature.min_c} to ${temperature.max_c} °C, median ${temperature.median_c}`}
        </dd>
        <dt>Model error</dt>
        <dd className="mono">{formatSeconds(model.residual_rmse_s)} s per lap</dd>
      </dl>
      <span className="label">Calibrated compounds</span>
      <ul className="compounds">
        {model.compounds.map((fit) => (
          <li key={fit.compound}>
            <span className={`tyre tyre--${COMPOUND_LOOK[fit.compound].tone}`} aria-hidden="true" />
            {COMPOUND_LOOK[fit.compound].label}
            <span className="muted small">
              {' '}
              tyres of {fit.min_tyre_age_laps} to {fit.max_tyre_age_laps} laps
            </span>
          </li>
        ))}
      </ul>
    </aside>
  )
}

function pitLossFact(pitLoss: Schemas['PitLossResponse'] | null): string {
  if (pitLoss === null) {
    return 'not measured'
  }
  const measured = `${formatSeconds(pitLoss.pit_loss_s)} s over ${pitLoss.stops} stops`
  return pitLoss.reliable ? measured : `${measured}, not reliable`
}
