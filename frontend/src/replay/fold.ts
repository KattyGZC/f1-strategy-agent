import type { components } from '../api/schema.ts'

type Schemas = components['schemas']
export type ReplayEvent = Schemas['ReplayEvent']
export type RaceControlEvent = Schemas['RaceControlEvent']
export type WeatherEvent = Schemas['WeatherEvent']
export type LapEvent = Schemas['LapEvent']
export type Flag = Schemas['Flag']
export type SessionDriver = Schemas['DriverResponse']

/** Events handed over together; after a reset they rebuild the replay from nothing. */
export interface EventBatch {
  readonly reset: boolean
  readonly events: readonly ReplayEvent[]
}

export type Gap = { unit: 'seconds'; value: number } | { unit: 'laps'; value: number }

export interface DriverTiming {
  readonly position: number | null
  readonly gapToLeader: Gap | null
  readonly interval: Gap | null
  /** Its compound and tyre age are those of the stint the lap belongs to. */
  readonly lastLap: LapEvent | null
  readonly lastPitLap: number | null
}

export interface ReplayState {
  readonly timings: ReadonlyMap<number, DriverTiming>
  /** The latest first. */
  readonly raceControl: readonly RaceControlEvent[]
  readonly weather: WeatherEvent | null
  /** The flag of the latest race control message about the whole track. */
  readonly trackFlag: Flag | null
  /** The instant of the latest event, as the API sent it. */
  readonly sessionTime: string | null
}

export interface TowerRow {
  readonly driver: SessionDriver
  readonly timing: DriverTiming
}

export const NO_TIMING: DriverTiming = {
  position: null,
  gapToLeader: null,
  interval: null,
  lastLap: null,
  lastPitLap: null,
}

export const EMPTY_REPLAY: ReplayState = {
  timings: new Map(),
  raceControl: [],
  weather: null,
  trackFlag: null,
  sessionTime: null,
}

/** The state after one more event: each field holds the latest value an event carried. */
export function foldEvent(state: ReplayState, event: ReplayEvent): ReplayState {
  const next = { ...state, sessionTime: event.at }
  switch (event.kind) {
    case 'position':
      return withTiming(next, event.driver_number, { position: event.position })
    case 'interval':
      return withTiming(next, event.driver_number, {
        gapToLeader: gap(event.gap_to_leader_s, event.gap_to_leader_laps),
        interval: gap(event.interval_s, event.interval_laps),
      })
    case 'lap':
      return withTiming(next, event.driver_number, { lastLap: event })
    case 'pit':
      return withTiming(next, event.driver_number, { lastPitLap: event.lap_number })
    case 'race_control':
      return {
        ...next,
        raceControl: [event, ...state.raceControl],
        trackFlag: event.scope === 'Track' && event.flag !== null ? event.flag : state.trackFlag,
      }
    case 'weather':
      return { ...next, weather: event }
    case 'overtake':
    case 'team_radio':
      return next
  }
}

function foldEvents(state: ReplayState, events: readonly ReplayEvent[]): ReplayState {
  return events.reduce(foldEvent, state)
}

export function foldBatch(state: ReplayState, batch: EventBatch): ReplayState {
  return foldEvents(batch.reset ? EMPTY_REPLAY : state, batch.events)
}

/** The session's drivers by the position they last held; a driver with none yet goes last.
 * Ties (no position yet, or two drivers between their position events) go by driver number. */
export function towerRows(
  drivers: readonly SessionDriver[],
  timings: ReadonlyMap<number, DriverTiming>,
): TowerRow[] {
  return drivers
    .map((driver) => ({ driver, timing: timings.get(driver.driver_number) ?? NO_TIMING }))
    .toSorted(
      (a, b) =>
        (a.timing.position ?? Infinity) - (b.timing.position ?? Infinity) ||
        a.driver.driver_number - b.driver.driver_number,
    )
}

function withTiming(
  state: ReplayState,
  driverNumber: number,
  change: Partial<DriverTiming>,
): ReplayState {
  const timings = new Map(state.timings)
  timings.set(driverNumber, { ...(state.timings.get(driverNumber) ?? NO_TIMING), ...change })
  return { ...state, timings }
}

function gap(seconds: number | null, laps: number | null): Gap | null {
  if (seconds !== null) {
    return { unit: 'seconds', value: seconds }
  }
  return laps === null ? null : { unit: 'laps', value: laps }
}
