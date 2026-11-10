import type { ReplaySpeed } from '../api/closedSets.ts'
import { SpeedSelect } from './SessionPicker.tsx'
import type { Playback } from './usePlayback.ts'

interface Props {
  playback: Playback
  busy: boolean
  onPause(): void
  onResume(): void
  onSpeed(speed: ReplaySpeed): void
}

export function ReplayControls({ playback, busy, onPause, onResume, onSpeed }: Readonly<Props>) {
  return (
    <div className="controls">
      {playback.status === 'playing' ? (
        <button type="button" disabled={busy} onClick={onPause}>
          Pause
        </button>
      ) : (
        <button type="button" disabled={busy} onClick={onResume}>
          Resume
        </button>
      )}
      <SpeedSelect speed={playback.speed} disabled={busy} onSpeed={onSpeed} />
    </div>
  )
}
