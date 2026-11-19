import { useEffect, useState } from 'react'

import type { ApiClient } from '../api/client.ts'
import { failureMessage, UNREACHABLE } from '../api/errors.ts'
import type { components } from '../api/schema.ts'
import { formatDate } from '../format.ts'
import { RaceSetup } from './RaceSetup.tsx'

type Race = components['schemas']['RaceResponse']

type ListState =
  { kind: 'loading' } | { kind: 'loaded'; races: Race[] } | { kind: 'failed'; message: string }

interface Props {
  client: ApiClient
}

export function SimulatorScreen({ client }: Readonly<Props>) {
  const [list, setList] = useState<ListState>({ kind: 'loading' })

  useEffect(() => {
    const controller = new AbortController()
    client
      .GET('/api/races', { signal: controller.signal })
      .then(({ data, error, response }) =>
        setList(
          data
            ? { kind: 'loaded', races: data }
            : { kind: 'failed', message: failureMessage(error, response) },
        ),
      )
      .catch(() => {
        if (!controller.signal.aborted) {
          setList({ kind: 'failed', message: UNREACHABLE })
        }
      })
    return () => controller.abort()
  }, [client])

  switch (list.kind) {
    case 'loading':
      return <p className="notice">Loading the calibrated races...</p>
    case 'failed':
      return (
        <p className="notice" role="alert">
          Could not list the races: {list.message}
        </p>
      )
    case 'loaded': {
      const [first, ...rest] = list.races
      return first === undefined ? (
        <p className="notice">No race is calibrated yet. Run make calibrate first.</p>
      ) : (
        <Simulator client={client} races={[first, ...rest]} />
      )
    }
  }
}

interface SimulatorProps {
  client: ApiClient
  races: readonly [Race, ...Race[]]
}

function Simulator({ client, races }: Readonly<SimulatorProps>) {
  const [chosen, setChosen] = useState<Race>(races[0])

  return (
    <div className="simulator">
      <section className="simulator-intro">
        <h2 className="hero">Compare race strategies</h2>
        <p className="muted">
          Pick a race the model was calibrated on and up to four strategies. Every lap time is the
          model&apos;s prediction for that race, and every stop costs its measured pit loss.
        </p>
        <label className="field">
          <span className="label">Race</span>
          <select
            value={chosen.session_key}
            onChange={(event) =>
              setChosen(
                races.find((race) => race.session_key === Number(event.target.value)) ?? chosen,
              )
            }
          >
            {races.map((race) => (
              <option key={race.session_key} value={race.session_key}>
                {race.year} {race.meeting_name}, {formatDate(race.date_start)}
              </option>
            ))}
          </select>
        </label>
      </section>
      <RaceSetup key={chosen.session_key} client={client} race={chosen} />
    </div>
  )
}
