import { useEffect, useReducer, useState } from 'react'

import type { ApiClient } from '../api/client.ts'
import type { components } from '../api/schema.ts'
import { DriverCard } from './DriverCard.tsx'
import { EMPTY_REPLAY, foldBatch, towerRows } from './fold.ts'
import { PlaybackBar } from './PlaybackBar.tsx'
import { RaceHeader } from './RaceHeader.tsx'
import { CircuitCard, RaceControlFeed, StrategyPanel, WeatherPanel } from './SidePanels.tsx'
import { CONNECTING, watchReplay, type OpenEventStream, type StreamLink } from './stream.ts'
import { TimingTower } from './TimingTower.tsx'
import { usePlayback } from './usePlayback.ts'

type Schemas = components['schemas']

interface Props {
  client: ApiClient
  openStream: OpenEventStream
  replay: Schemas['ReplayResponse']
  entry: Schemas['SessionEntryResponse']
  onLeave(): void
}

export function ReplayView({ client, openStream, replay, entry, onLeave }: Readonly<Props>) {
  const [state, dispatch] = useReducer(foldBatch, EMPTY_REPLAY)
  const [link, setLink] = useState<StreamLink>(CONNECTING)
  const [selected, setSelected] = useState<number | null>(null)
  const controls = usePlayback(client, replay)
  const replayId = replay.replay_id

  useEffect(
    () => watchReplay(openStream, replayId, { onBatch: dispatch, onLink: setLink }),
    [openStream, replayId],
  )

  const rows = towerRows(entry.drivers, state.timings)
  const [first] = rows
  const leader = first?.timing.position === 1 ? first : undefined
  const followed = rows.find((row) => row.driver.driver_number === selected) ?? first

  return (
    <section className="replay" aria-label="Replay">
      <RaceHeader
        entry={entry}
        leaderLap={leader?.timing.lastLap?.lap_number ?? null}
        trackFlag={state.trackFlag}
        sessionTime={state.sessionTime}
        link={link}
      />
      {controls.error === null ? null : (
        <p className="notice" role="alert">
          The replay did not change: {controls.error}
        </p>
      )}
      <div className="replay-grid">
        <TimingTower
          drivers={entry.drivers}
          timings={state.timings}
          selected={followed?.driver.driver_number ?? null}
          onSelect={setSelected}
        />
        <div className="replay-centre">
          {followed === undefined ? null : (
            <DriverCard driver={followed.driver} timing={followed.timing} />
          )}
          <StrategyPanel />
        </div>
        <aside className="replay-side">
          <CircuitCard circuit={entry.circuit_short_name} />
          <WeatherPanel weather={state.weather} />
          <RaceControlFeed messages={state.raceControl} />
        </aside>
      </div>
      <PlaybackBar
        playback={controls.playback}
        busy={controls.busy}
        onPause={controls.pause}
        onResume={controls.resume}
        onSpeed={controls.setSpeed}
        lastLapNumber={entry.last_lap_number}
        onSeek={controls.seek}
        onLeave={onLeave}
      />
    </section>
  )
}
