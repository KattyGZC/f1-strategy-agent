import { describe, expect, it } from 'vitest'

import {
  EVENT_AT,
  interval,
  lap,
  LECLERC,
  OVERTAKE,
  pit,
  position,
  raceControl,
  TEAM_RADIO,
  VERSTAPPEN,
  WEATHER,
} from '../testing.ts'
import {
  EMPTY_REPLAY,
  foldBatch,
  foldEvent,
  NO_TIMING,
  towerRows,
  type DriverTiming,
  type ReplayEvent,
} from './fold.ts'

function fold(...events: ReplayEvent[]) {
  return events.reduce(foldEvent, EMPTY_REPLAY)
}

function timingOf(events: ReplayEvent[], driverNumber: number): DriverTiming | undefined {
  return fold(...events).timings.get(driverNumber)
}

describe('foldEvent', () => {
  it('keeps the instant of the latest event', () => {
    const state = fold(position(1, 1), { ...OVERTAKE, at: '2024-03-02T15:04:00.000Z' })

    expect(state.sessionTime).toBe('2024-03-02T15:04:00.000Z')
  })

  it('keeps the last position of each driver', () => {
    const state = fold(position(1, 2), position(16, 1), position(1, 1))

    expect(state.timings.get(1)).toEqual({ ...NO_TIMING, position: 1 })
    expect(state.timings.get(16)).toEqual({ ...NO_TIMING, position: 1 })
  })

  it('keeps a gap in seconds', () => {
    const timing = timingOf([interval(16, { gap_to_leader_s: 1.5, interval_s: 0.4 })], 16)

    expect(timing).toEqual({
      ...NO_TIMING,
      gapToLeader: { unit: 'seconds', value: 1.5 },
      interval: { unit: 'seconds', value: 0.4 },
    })
  })

  it('keeps a gap in laps when the seconds are missing', () => {
    const timing = timingOf([interval(16, { gap_to_leader_laps: 1, interval_laps: 2 })], 16)

    expect(timing).toEqual({
      ...NO_TIMING,
      gapToLeader: { unit: 'laps', value: 1 },
      interval: { unit: 'laps', value: 2 },
    })
  })

  it('clears a gap the latest interval does not carry, as for the leader', () => {
    const timing = timingOf(
      [interval(1, { gap_to_leader_s: 2, interval_s: 2 }), interval(1, {})],
      1,
    )

    expect(timing).toEqual(NO_TIMING)
  })

  it('keeps the whole last lap, and the position it already had', () => {
    const last = lap(1, 5, { lap_duration: 91.2, compound: null, tyre_age_laps: null })

    expect(timingOf([position(1, 3), lap(1, 4), last], 1)).toEqual({
      ...NO_TIMING,
      position: 3,
      lastLap: last,
    })
  })

  it('keeps the lap of the last pit stop', () => {
    expect(timingOf([pit(1, 12), pit(1, 31)], 1)).toEqual({ ...NO_TIMING, lastPitLap: 31 })
  })

  it('puts the latest race control message first', () => {
    const first = raceControl(1, 'GREEN LIGHT - PIT EXIT OPEN')
    const second = raceControl(2, 'DRS ENABLED')

    expect(fold(first, second).raceControl).toEqual([second, first])
  })

  it('keeps the flag of the latest message about the whole track', () => {
    const state = fold(
      raceControl(1, 'GREEN LIGHT - PIT EXIT OPEN'),
      raceControl(2, 'RED FLAG', { flag: 'RED' }),
      raceControl(3, 'YELLOW IN TRACK SECTOR 4', { flag: 'YELLOW', scope: 'Sector', sector: 4 }),
      raceControl(4, 'DRS DISABLED', { category: 'Drs', flag: null, scope: null }),
    )

    expect(state.trackFlag).toBe('RED')
  })

  it('has no track flag before a message about the whole track', () => {
    const state = fold(raceControl(1, 'BLUE FLAG FOR CAR 2', { flag: 'BLUE', scope: 'Driver' }))

    expect(state.trackFlag).toBeNull()
  })

  it('keeps the latest weather reading', () => {
    const later = { ...WEATHER, track_temperature: 27 }

    expect(fold(WEATHER, later).weather).toEqual(later)
  })

  it('leaves the timing alone on an overtake or a team radio', () => {
    const state = fold(OVERTAKE, TEAM_RADIO)

    expect(state).toEqual({ ...EMPTY_REPLAY, sessionTime: EVENT_AT })
  })

  it('does not change the state it was given', () => {
    const before = fold(position(1, 2))

    foldEvent(before, position(1, 1))

    expect(before.timings.get(1)).toEqual({ ...NO_TIMING, position: 2 })
  })
})

describe('towerRows', () => {
  it('orders the drivers by their last position', () => {
    const { timings } = fold(position(1, 2), position(16, 1))

    expect(towerRows([VERSTAPPEN, LECLERC], timings).map((row) => row.driver)).toEqual([
      LECLERC,
      VERSTAPPEN,
    ])
  })

  it('puts a driver without a position last, by driver number among them', () => {
    const third = { ...VERSTAPPEN, driver_number: 44, name_acronym: 'HAM' }
    const { timings } = fold(position(44, 1))

    expect(towerRows([LECLERC, VERSTAPPEN, third], timings)).toEqual([
      { driver: third, timing: { ...NO_TIMING, position: 1 } },
      { driver: VERSTAPPEN, timing: NO_TIMING },
      { driver: LECLERC, timing: NO_TIMING },
    ])
  })
})

describe('foldBatch', () => {
  it('folds a plain batch onto what was built', () => {
    const built = fold(position(1, 1))

    const state = foldBatch(built, { reset: false, events: [position(16, 2)] })

    expect(state).toEqual(fold(position(1, 1), position(16, 2)))
  })

  it('rebuilds from nothing after a reset', () => {
    const built = fold(
      position(1, 1),
      WEATHER,
      raceControl(1, 'YELLOW IN TRACK', { scope: 'Track', flag: 'YELLOW' }),
    )

    const state = foldBatch(built, { reset: true, events: [position(16, 2)] })

    expect(state).toEqual(fold(position(16, 2)))
  })

  it('leaves nothing after a reset alone', () => {
    expect(foldBatch(fold(position(1, 1)), { reset: true, events: [] })).toBe(EMPTY_REPLAY)
  })
})
