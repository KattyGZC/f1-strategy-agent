import { useState } from 'react'

import type { ApiClient } from '../api/client.ts'
import { failureMessage, UNREACHABLE } from '../api/errors.ts'
import type { ReplaySpeed } from '../api/closedSets.ts'
import type { components } from '../api/schema.ts'

type ReplayResponse = components['schemas']['ReplayResponse']

export interface Playback {
  status: components['schemas']['PlaybackStatus']
  speed: ReplaySpeed
}
type ControlCall = () => Promise<{ data?: ReplayResponse; error?: unknown; response: Response }>

/** The replay's playback as the API last returned it, and the controls that change it. */
export function usePlayback(client: ApiClient, replay: ReplayResponse) {
  const [playback, setPlayback] = useState<Playback>(replay)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const control = (call: ControlCall) => {
    setBusy(true)
    call()
      .then(({ data, error: failed, response }) => {
        if (data) {
          setPlayback(data)
          setError(null)
        } else {
          setError(failureMessage(failed, response))
        }
      })
      .catch(() => setError(UNREACHABLE))
      .finally(() => setBusy(false))
  }
  const path = { params: { path: { replay_id: replay.replay_id } } }

  return {
    playback,
    busy,
    error,
    pause: () => control(() => client.POST('/api/replays/{replay_id}/pause', path)),
    resume: () => control(() => client.POST('/api/replays/{replay_id}/resume', path)),
    setSpeed: (speed: ReplaySpeed) =>
      control(() => client.PUT('/api/replays/{replay_id}/speed', { ...path, body: { speed } })),
  }
}
