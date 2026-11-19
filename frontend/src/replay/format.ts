import { NOTHING } from '../format.ts'
import type { Gap } from './fold.ts'

export function formatGap(gap: Gap | null): string {
  if (gap === null) {
    return NOTHING
  }
  if (gap.unit === 'seconds') {
    return `+${gap.value.toFixed(3)}`
  }
  return `+${gap.value} ${gap.value === 1 ? 'LAP' : 'LAPS'}`
}

/** The UTC time of day of an instant the API sent, such as 15:03:27. */
export function formatClock(at: string | null): string {
  return at === null ? NOTHING : new Date(at).toISOString().slice(11, 19)
}

export function formatPitLap(lapNumber: number | null): string {
  return lapNumber === null ? NOTHING : `L${lapNumber}`
}

export function formatOptional(value: number | string | null): string {
  return value === null ? NOTHING : String(value)
}
