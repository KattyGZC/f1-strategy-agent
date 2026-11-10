import type { LapEvent } from './fold.ts'
import { NOTHING } from './format.ts'
import { COMPOUND_LOOK } from './look.ts'

/** The compound of the lap's stint as a coloured ring, and the tyre's age in laps. */
export function TyreBadge({ lap }: Readonly<{ lap: LapEvent | null }>) {
  if (lap === null || lap.compound === null) {
    return <span className="muted">{NOTHING}</span>
  }
  const look = COMPOUND_LOOK[lap.compound]
  return (
    <span className="tyre-badge" title={look.label}>
      <span className={`tyre tyre--${look.tone}`} aria-label={look.label} role="img" />
      {lap.tyre_age_laps === null ? null : <span className="mono muted">{lap.tyre_age_laps}</span>}
    </span>
  )
}
