import { REPLAY_SPEEDS, type ReplaySpeed } from '../api/closedSets.ts'

interface Props {
  speed: ReplaySpeed
  disabled: boolean
  onSpeed(speed: ReplaySpeed): void
}

export function SpeedButtons({ speed, disabled, onSpeed }: Readonly<Props>) {
  return (
    <fieldset className="segmented">
      <legend className="visually-hidden">Speed</legend>
      {REPLAY_SPEEDS.map((value) => (
        <button
          key={value}
          type="button"
          className="chip"
          aria-pressed={value === speed}
          disabled={disabled}
          onClick={() => onSpeed(value)}
        >
          {value}x
        </button>
      ))}
    </fieldset>
  )
}
