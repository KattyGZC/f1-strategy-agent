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
  | { kind: 'choosing'; alert: string | null }
  | { kind: 'starting' }
  | {
      kind: 'watching'
      replay: Schemas['ReplayResponse']
      entry: Schemas['SessionEntryResponse']
    }

const CHOOSING: ScreenState = { kind: 'choosing', alert: null }
const HTTP_NOT_FOUND = 404

interface Props {
  client: ApiClient
  openStream: OpenEventStream
}

export function ReplayScreen({ client, openStream }: Readonly<Props>) {
  const [screen, setScreen] = useState<ScreenState>(CHOOSING)

  const start = (sessionKey: number, speed: ReplaySpeed) => {
    setScreen({ kind: 'starting' })
    startReplay(client, sessionKey, speed)
      .then(setScreen)
      .catch(() => setScreen(notStarted(UNREACHABLE)))
  }

  const leave = (replayId: string) => {
    setScreen(CHOOSING)
    void stopReplay(client, replayId).then((problem) => {
      if (problem !== null) {
        setScreen((now) => (now.kind === 'choosing' ? notStopped(problem) : now))
      }
    })
  }

  if (screen.kind === 'watching') {
    return (
      <ReplayView
        key={screen.replay.replay_id}
        client={client}
        openStream={openStream}
        replay={screen.replay}
        entry={screen.entry}
        onLeave={() => leave(screen.replay.replay_id)}
      />
    )
  }
  return (
    <>
      <SessionPicker client={client} starting={screen.kind === 'starting'} onStart={start} />
      {screen.kind === 'choosing' && screen.alert !== null ? (
        <p className="notice" role="alert">
          {screen.alert}
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
    return notStarted(failureMessage(read.error, read.response))
  }
  const started = await client.POST('/api/replays', { body: { session_key: sessionKey, speed } })
  if (!started.data) {
    return notStarted(failureMessage(started.error, started.response))
  }
  return { kind: 'watching', replay: started.data, entry: read.data }
}

/** Why the replay could not be stopped, or null once it is gone, already gone included. */
async function stopReplay(client: ApiClient, replayId: string): Promise<string | null> {
  try {
    const { error, response } = await client.DELETE('/api/replays/{replay_id}', {
      params: { path: { replay_id: replayId } },
    })
    return response.ok || response.status === HTTP_NOT_FOUND
      ? null
      : failureMessage(error, response)
  } catch {
    return UNREACHABLE
  }
}

function notStarted(reason: string): ScreenState {
  return { kind: 'choosing', alert: `The replay did not start: ${reason}` }
}

function notStopped(reason: string): ScreenState {
  return {
    kind: 'choosing',
    alert: `The last replay could not be stopped (${reason}); it ends on its own after a few idle minutes.`,
  }
}
