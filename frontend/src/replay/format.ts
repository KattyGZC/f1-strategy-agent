import type { Gap } from './fold.ts'

export const NOTHING = '-'
const MS_PER_S = 1000
const MS_PER_MINUTE = 60 * MS_PER_S

export function formatGap(gap: Gap | null): string {
  if (gap === null) {
    return NOTHING
  }
  if (gap.unit === 'seconds') {
    return `+${gap.value.toFixed(3)}`
  }
  return `+${gap.value} ${gap.value === 1 ? 'LAP' : 'LAPS'}`
}

/** A duration in seconds as the timing screens print it, such as 1:32.608. */
export function formatLapTime(durationS: number | null): string {
  if (durationS === null) {
    return NOTHING
  }
  // Rounded to the millisecond first, so 59.9999 s prints as 1:00.000, not 0:60.000.
  const durationMs = Math.round(durationS * MS_PER_S)
  const minutes = Math.floor(durationMs / MS_PER_MINUTE)
  const seconds = ((durationMs % MS_PER_MINUTE) / MS_PER_S).toFixed(3).padStart(6, '0')
  return `${minutes}:${seconds}`
}

/** A duration under a minute, such as a sector time: 29.123. */
export function formatSeconds(durationS: number | null): string {
  return durationS === null ? NOTHING : durationS.toFixed(3)
}

/** The UTC time of day of an instant the API sent, such as 15:03:27. */
export function formatClock(at: string | null): string {
  return at === null ? NOTHING : new Date(at).toISOString().slice(11, 19)
}

export function formatPitLap(lapNumber: number | null): string {
  return lapNumber === null ? NOTHING : `L${lapNumber}`
}

const DAY_MONTH_YEAR = new Intl.DateTimeFormat('en-GB', {
  day: 'numeric',
  month: 'short',
  year: 'numeric',
  timeZone: 'UTC',
})

/** The UTC date of an instant the API sent, such as 2 Mar 2024. */
export function formatDate(at: string): string {
  return DAY_MONTH_YEAR.format(new Date(at))
}

export function formatOptional(value: number | string | null): string {
  return value === null ? NOTHING : String(value)
}
