import { describe, expect, it } from 'vitest'

import { formatLapTime, formatRaceTime } from './format.ts'

describe('format', () => {
  it.each([
    [null, '-'],
    [92.608, '1:32.608'],
    [65.05, '1:05.050'],
    [59.9999, '1:00.000'],
    [7.2, '0:07.200'],
  ])('prints the lap time %s as %s', (durationS, printed) => {
    expect(formatLapTime(durationS)).toBe(printed)
  })

  it.each([
    [5588.697, '1:33:08.697'],
    [3599.9996, '1:00:00.000'],
    [59.5, '0:00:59.500'],
  ])('prints a race of %s s as %s', (durationS, printed) => {
    expect(formatRaceTime(durationS)).toBe(printed)
  })
})
