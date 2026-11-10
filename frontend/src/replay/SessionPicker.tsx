import { useEffect, useState } from 'react'

import type { ApiClient } from '../api/client.ts'
import { REPLAY_SPEEDS, type ReplaySpeed } from '../api/closedSets.ts'
import { failureMessage, UNREACHABLE } from '../api/errors.ts'
import type { components } from '../api/schema.ts'
import { formatDate } from './format.ts'
import { SpeedButtons } from './SpeedButtons.tsx'

type Session = components['schemas']['SessionResponse']
type Sessions = readonly [Session, ...Session[]]

type ListState =
  | { kind: 'loading' }
  | { kind: 'loaded'; sessions: Session[] }
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
      return <p className="notice">Loading the sessions...</p>
    case 'failed':
      return (
        <p className="notice" role="alert">
          Could not list the sessions: {list.message}
        </p>
      )
    case 'loaded': {
      const [latest, ...older] = list.sessions
      return latest === undefined ? (
        <p className="notice">
          No session is loaded yet. Run make ingest and make transform first.
        </p>
      ) : (
        <Picker sessions={[latest, ...older]} starting={starting} onStart={onStart} />
      )
    }
  }
}

interface PickerProps {
  sessions: Sessions
  starting: boolean
  onStart(sessionKey: number, speed: ReplaySpeed): void
}

function Picker({ sessions, starting, onStart }: Readonly<PickerProps>) {
  const [chosen, setChosen] = useState<Session>(sessions[0])

  return (
    <div className="picker">
      <section className="picker-meetings">
        <h2 className="hero">Relive a race as it happened</h2>
        <p className="muted">
          Pick a Grand Prix and a session. The timing, the weather and race control play back in the
          order they happened.
        </p>
        <div className="meetings">
          {byMeeting(sessions).map((meeting) => (
            <MeetingCard
              key={meeting[0].meeting_key}
              sessions={meeting}
              chosen={chosen}
              onChoose={setChosen}
            />
          ))}
        </div>
      </section>
      <ReadyPanel session={chosen} starting={starting} onStart={onStart} />
    </div>
  )
}

interface ReadyProps {
  session: Session
  starting: boolean
  onStart(sessionKey: number, speed: ReplaySpeed): void
}

function ReadyPanel({ session, starting, onStart }: Readonly<ReadyProps>) {
  const [speed, setSpeed] = useState<ReplaySpeed>(REPLAY_SPEEDS[0])
  return (
    <aside className="panel ready" aria-label="Ready to start">
      <span className="label">Ready to start</span>
      <h3>{session.meeting_name}</h3>
      <p className="muted">
        {session.session_name}, {session.circuit_short_name}, {formatDate(session.date_start)}
      </p>
      <span className="label">Playback speed</span>
      <SpeedButtons speed={speed} disabled={starting} onSpeed={setSpeed} />
      <p className="muted small">
        At 60x a two-hour race plays in about two minutes; 1x is real time.
      </p>
      <button
        type="button"
        className="primary"
        disabled={starting}
        onClick={() => onStart(session.session_key, speed)}
      >
        {starting ? 'Starting...' : 'Start replay'}
      </button>
      <p className="muted small">
        A session opens about an hour before the start: the grid, the weather and race control come
        first, and the laps begin at the green light.
      </p>
    </aside>
  )
}

interface CardProps {
  sessions: Sessions
  chosen: Session
  onChoose(session: Session): void
}

function MeetingCard({ sessions, chosen, onChoose }: Readonly<CardProps>) {
  const [meeting] = sessions
  return (
    <article className="panel meeting" aria-current={meeting.meeting_key === chosen.meeting_key}>
      <span className="label">
        {meeting.country_name}, {formatDate(meeting.date_start)}
      </span>
      <h3>{meeting.meeting_name}</h3>
      <p className="muted">{meeting.circuit_short_name}</p>
      <div className="chips">
        {sessions.map((session) => (
          <button
            key={session.session_key}
            type="button"
            className="chip"
            aria-pressed={session.session_key === chosen.session_key}
            onClick={() => onChoose(session)}
          >
            {session.session_name}
          </button>
        ))}
      </div>
    </article>
  )
}

/** The sessions of each meeting, in the order the API listed them. */
function byMeeting(sessions: Sessions): Sessions[] {
  const meetings = new Map<number, Sessions>()
  for (const session of sessions) {
    const meeting = meetings.get(session.meeting_key)
    meetings.set(session.meeting_key, meeting === undefined ? [session] : [...meeting, session])
  }
  return [...meetings.values()]
}
