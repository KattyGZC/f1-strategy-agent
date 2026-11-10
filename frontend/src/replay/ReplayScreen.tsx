import { useState } from 'react'

import type { ApiClient } from '../api/client.ts'
import type { ReplaySpeed } from '../api/closedSets.ts'
import { failureMessage, UNREACHABLE } from '../api/errors.ts'
import type { components } from '../api/schema.ts'
import { ReplayView } from './ReplayView.tsx'
import { SessionPicker } from './SessionPicker.tsx'
import type { OpenEventStream } from './stream.ts'

type Schemas = components['schemas']

type ScreenState =
  | { kind: 'choosing'; error: string | null }
  | { kind: 'starting' }
  | {
      kind: 'watching'
      replay: Schemas['ReplayResponse']
      entry: Schemas['SessionEntryResponse']
    }

interface Props {
  client: ApiClient
  openStream: OpenEventStream
}

export function ReplayScreen({ client, openStream }: Readonly<Props>) {
  const [screen, setScreen] = useState<ScreenState>({ kind: 'choosing', error: null })

  const start = (sessionKey: number, speed: ReplaySpeed) => {
    setScreen({ kind: 'starting' })
    startReplay(client, sessionKey, speed)
      .then(setScreen)
      .catch(() => setScreen({ kind: 'choosing', error: UNREACHABLE }))
  }

  if (screen.kind === 'watching') {
    return (
      <ReplayView
        key={screen.replay.replay_id}
        client={client}
        openStream={openStream}
        replay={screen.replay}
        entry={screen.entry}
        onLeave={() => setScreen({ kind: 'choosing', error: null })}
      />
    )
  }
  return (
    <>
      <SessionPicker client={client} starting={screen.kind === 'starting'} onStart={start} />
      {screen.kind === 'choosing' && screen.error !== null ? (
        <p className="notice" role="alert">
          The replay did not start: {screen.error}
        </p>
      ) : null}
    </>
  )
}

/** The session's drivers first, so a replay starts only for a session the screen can show. */
async function startReplay(
  client: ApiClient,
  sessionKey: number,
  speed: ReplaySpeed,
): Promise<ScreenState> {
  const read = await client.GET('/api/sessions/{session_key}', {
    params: { path: { session_key: sessionKey } },
  })
  if (!read.data) {
    return { kind: 'choosing', error: failureMessage(read.error, read.response) }
  }
  const started = await client.POST('/api/replays', { body: { session_key: sessionKey, speed } })
  if (!started.data) {
    return { kind: 'choosing', error: failureMessage(started.error, started.response) }
  }
  return { kind: 'watching', replay: started.data, entry: read.data }
}
