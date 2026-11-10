import type { ReplaySpeed } from '../api/closedSets.ts'
import { SpeedButtons } from './SpeedButtons.tsx'
import type { Playback } from './usePlayback.ts'

interface Props {
  playback: Playback
  busy: boolean
  onPause(): void
  onResume(): void
  onSpeed(speed: ReplaySpeed): void
  onLeave(): void
}

export function PlaybackBar({
  playback,
  busy,
  onPause,
  onResume,
  onSpeed,
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
      <button type="button" className="link" onClick={onLeave}>
        Choose another session
      </button>
    </div>
  )
}
