import { describe, expect, it } from 'vitest'

import { formatClock, formatGap, formatLapTime, formatOptional } from './format.ts'

describe('format', () => {
  it.each([
    [null, '-'],
    [{ unit: 'seconds', value: 1.5 } as const, '+1.500'],
    [{ unit: 'seconds', value: 0 } as const, '+0.000'],
    [{ unit: 'laps', value: 1 } as const, '+1 LAP'],
    [{ unit: 'laps', value: 2 } as const, '+2 LAPS'],
  ])('prints the gap %j as %s', (gap, printed) => {
    expect(formatGap(gap)).toBe(printed)
  })

  it.each([
    [null, '-'],
    [92.608, '1:32.608'],
    [65.05, '1:05.050'],
    [59.9999, '1:00.000'],
    [7.2, '0:07.200'],
  ])('prints the lap time %s as %s', (durationS, printed) => {
    expect(formatLapTime(durationS)).toBe(printed)
  })

  it('prints the UTC time of day of an instant', () => {
    expect(formatClock('2024-03-02T18:03:27.512+03:00')).toBe('15:03:27')
    expect(formatClock(null)).toBe('-')
  })

  it('prints an optional value or a dash', () => {
    expect(formatOptional(0)).toBe('0')
    expect(formatOptional('SOFT')).toBe('SOFT')
    expect(formatOptional(null)).toBe('-')
  })
})
