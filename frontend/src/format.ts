export const NOTHING = '-'
const MS_PER_S = 1000
const MS_PER_MINUTE = 60 * MS_PER_S
const MS_PER_HOUR = 60 * MS_PER_MINUTE

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

/** A race's length in seconds with its hours, such as 1:33:08.697. */
export function formatRaceTime(durationS: number): string {
  const durationMs = Math.round(durationS * MS_PER_S)
  const hours = Math.floor(durationMs / MS_PER_HOUR)
  const minutes = String(Math.floor((durationMs % MS_PER_HOUR) / MS_PER_MINUTE)).padStart(2, '0')
  const seconds = ((durationMs % MS_PER_MINUTE) / MS_PER_S).toFixed(3).padStart(6, '0')
  return `${hours}:${minutes}:${seconds}`
}

/** A duration under a minute, such as a sector time: 29.123. */
export function formatSeconds(durationS: number | null): string {
  return durationS === null ? NOTHING : durationS.toFixed(3)
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
