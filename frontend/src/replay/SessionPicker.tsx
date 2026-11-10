import { useEffect, useState } from 'react'

import type { ApiClient } from '../api/client.ts'
import { REPLAY_SPEEDS, type ReplaySpeed } from '../api/closedSets.ts'
import { failureMessage, UNREACHABLE } from '../api/errors.ts'
import type { components } from '../api/schema.ts'

type Schemas = components['schemas']

type ListState =
  | { kind: 'loading' }
  | { kind: 'loaded'; sessions: Schemas['SessionResponse'][] }
  | { kind: 'failed'; message: string }

interface Props {
  client: ApiClient
  starting: boolean
  onStart(sessionKey: number, speed: ReplaySpeed): void
}

export function SessionPicker({ client, starting, onStart }: Readonly<Props>) {
  const [list, setList] = useState<ListState>({ kind: 'loading' })

  useEffect(() => {
    const controller = new AbortController()
    client
      .GET('/api/sessions', { signal: controller.signal })
      .then(({ data, error, response }) =>
        setList(
          data
            ? { kind: 'loaded', sessions: data }
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
      return <p>Loading the sessions...</p>
    case 'failed':
      return <p role="alert">Could not list the sessions: {list.message}</p>
    case 'loaded': {
      const [latest, ...older] = list.sessions
      return latest === undefined ? (
        <p>No session is loaded yet. Run make ingest and make transform first.</p>
      ) : (
        <StartForm sessions={[latest, ...older]} starting={starting} onStart={onStart} />
      )
    }
  }
}

interface FormProps {
  sessions: readonly [Schemas['SessionResponse'], ...Schemas['SessionResponse'][]]
  starting: boolean
  onStart(sessionKey: number, speed: ReplaySpeed): void
}

function StartForm({ sessions, starting, onStart }: Readonly<FormProps>) {
  const [sessionKey, setSessionKey] = useState(sessions[0].session_key)
  const [speed, setSpeed] = useState<ReplaySpeed>(REPLAY_SPEEDS[0])

  return (
    <form
      className="start-form"
      onSubmit={(submitted) => {
        submitted.preventDefault()
        onStart(sessionKey, speed)
      }}
    >
      <label>
        Session
        <select
          value={sessionKey}
          onChange={(changed) => setSessionKey(Number(changed.target.value))}
        >
          {sessions.map((session) => (
            <option key={session.session_key} value={session.session_key}>
              {session.year} {session.meeting_name}, {session.session_name}
            </option>
          ))}
        </select>
      </label>
      <SpeedSelect speed={speed} disabled={starting} onSpeed={setSpeed} />
      <button type="submit" disabled={starting}>
        {starting ? 'Starting...' : 'Start replay'}
      </button>
    </form>
  )
}

interface SpeedProps {
  speed: ReplaySpeed
  disabled: boolean
  onSpeed(speed: ReplaySpeed): void
}

export function SpeedSelect({ speed, disabled, onSpeed }: Readonly<SpeedProps>) {
  return (
    <label>
      Speed
      <select
        value={speed}
        disabled={disabled}
        onChange={(changed) => {
          const chosen = REPLAY_SPEEDS.find((value) => String(value) === changed.target.value)
          if (chosen !== undefined) {
            onSpeed(chosen)
          }
        }}
      >
        {REPLAY_SPEEDS.map((value) => (
          <option key={value} value={value}>
            {value}x
          </option>
        ))}
      </select>
    </label>
  )
}
