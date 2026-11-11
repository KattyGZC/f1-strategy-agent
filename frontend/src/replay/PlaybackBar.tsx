import type { ReplaySpeed } from '../api/closedSets.ts'
import { GoToLap } from './GoToLap.tsx'
import { SpeedButtons } from './SpeedButtons.tsx'
import type { Playback } from './usePlayback.ts'

interface Props {
  playback: Playback
  busy: boolean
  onPause(): void
  onResume(): void
  onSpeed(speed: ReplaySpeed): void
  /** `null` when the session has no laps to go to. */
  lastLapNumber: number | null
  onSeek(lapNumber: number): void
  onLeave(): void
}

export function PlaybackBar({
  playback,
  busy,
  onPause,
  onResume,
  onSpeed,
  lastLapNumber,
  onSeek,
  onLeave,
}: Readonly<Props>) {
  const playing = playback.status === 'playing'
  return (
    <div className="playback">
      <button
        type="button"
        className="chip play"
        disabled={busy}
        onClick={playing ? onPause : onResume}
      >
        {playing ? 'Pause' : 'Resume'}
      </button>
      <span className="label">Speed</span>
      <SpeedButtons speed={playback.speed} disabled={busy} onSpeed={onSpeed} />
      <span className="muted small">
        {playback.speed === 1
          ? 'Real time'
          : `1 second here is ${playback.speed} seconds of session`}
      </span>
      {lastLapNumber === null ? null : (
        <GoToLap lastLapNumber={lastLapNumber} disabled={busy} onSeek={onSeek} />
      )}
      <button type="button" className="link" onClick={onLeave}>
        Choose another session
      </button>
    </div>
  )
}
