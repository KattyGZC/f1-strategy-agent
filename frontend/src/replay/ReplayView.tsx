import { useEffect, useReducer, useState } from 'react'

import type { ApiClient } from '../api/client.ts'
import type { components } from '../api/schema.ts'
import { EMPTY_REPLAY, foldEvents } from './fold.ts'
import { formatClock } from './format.ts'
import { RaceControlFeed } from './RaceControlFeed.tsx'
import { ReplayControls } from './ReplayControls.tsx'
import { CONNECTING, watchReplay, type OpenEventStream, type StreamLink } from './stream.ts'
import { TimingTower } from './TimingTower.tsx'
import { usePlayback } from './usePlayback.ts'
import { WeatherPanel } from './WeatherPanel.tsx'

type Schemas = components['schemas']

interface Props {
  client: ApiClient
  openStream: OpenEventStream
  replay: Schemas['ReplayResponse']
  entry: Schemas['SessionEntryResponse']
}

export function ReplayView({ client, openStream, replay, entry }: Readonly<Props>) {
  const [state, dispatch] = useReducer(foldEvents, EMPTY_REPLAY)
  const [link, setLink] = useState<StreamLink>(CONNECTING)
  const controls = usePlayback(client, replay)
  const replayId = replay.replay_id

  useEffect(
    () => watchReplay(openStream, replayId, { onEvents: dispatch, onLink: setLink }),
    [openStream, replayId],
  )

  return (
    <section className="replay" aria-label="Replay">
      <header>
        <h2>
          {entry.year} {entry.meeting_name}, {entry.session_name}
        </h2>
        <p>
          <time dateTime={state.sessionTime ?? undefined}>{formatClock(state.sessionTime)}</time>{' '}
          UTC. <LinkStatus link={link} />
        </p>
      </header>
      <ReplayControls
        playback={controls.playback}
        busy={controls.busy}
        onPause={controls.pause}
        onResume={controls.resume}
        onSpeed={controls.setSpeed}
      />
      {controls.error === null ? null : (
        <p role="alert">The replay did not change: {controls.error}</p>
      )}
      <div className="replay-panels">
        <TimingTower drivers={entry.drivers} timings={state.timings} />
        <aside>
          <WeatherPanel weather={state.weather} />
          <RaceControlFeed messages={state.raceControl} />
        </aside>
      </div>
    </section>
  )
}

function LinkStatus({ link }: Readonly<{ link: StreamLink }>) {
  switch (link.kind) {
    case 'connecting':
      return <span>Connecting...</span>
    case 'live':
      return <span>Live</span>
    case 'reconnecting':
      return <span>Reconnecting...</span>
    case 'ended':
      return <span role="status">The replay has ended</span>
    case 'failed':
      return <span role="alert">The replay failed: {link.message}</span>
  }
}
