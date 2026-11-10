import type { components } from './api/schema.ts'
import type { EventStream, OpenEventStream } from './replay/stream.ts'

type Schemas = components['schemas']

export const API_ORIGIN = 'http://api.test'

export function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

export type Route = (request: Request) => Response | Promise<Response>

export function fakeApi(routes: Readonly<Record<string, Route>>) {
  const requests: Request[] = []
  const fetchImpl: typeof fetch = (input) => {
    if (!(input instanceof Request)) {
      throw new TypeError('openapi-fetch is expected to pass a Request')
    }
    requests.push(input)
    const route = routes[`${input.method} ${new URL(input.url).pathname}`]
    return route === undefined
      ? Promise.reject(new TypeError(`no route for ${input.method} ${input.url}`))
      : Promise.resolve(route(input))
  }
  return { fetchImpl, requests }
}

export const CONNECTING = 0
export const CLOSED = 2

/** An EventSource the test drives: it delivers what the test emits, nothing else. */
export class FakeEventStream implements EventStream {
  readyState = CONNECTING
  readonly path: string
  private readonly listeners = new Map<string, ((event: Event) => void)[]>()

  constructor(path: string) {
    this.path = path
  }

  addEventListener(type: string, listener: (event: Event) => void): void {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener])
  }

  close(): void {
    this.readyState = CLOSED
  }

  emit(type: string, data: unknown): void {
    this.dispatch(new MessageEvent(type, { data: JSON.stringify(data) }))
  }

  dispatch(event: Event): void {
    for (const listener of this.listeners.get(event.type) ?? []) {
      listener(event)
    }
  }

  fail(readyState: number): void {
    this.readyState = readyState
    this.dispatch(new Event('error'))
  }
}

export function fakeStreams() {
  const streams: FakeEventStream[] = []
  const open: OpenEventStream = (path) => {
    const stream = new FakeEventStream(path)
    streams.push(stream)
    return stream
  }
  return { open, streams }
}

export const EVENT_AT = '2024-03-02T15:03:27.000Z'

export const SESSION: Schemas['SessionResponse'] = {
  session_key: 9472,
  meeting_key: 1229,
  session_type: 'Race',
  session_name: 'Race',
  date_start: '2024-03-02T15:00:00Z',
  year: 2024,
  meeting_name: 'Bahrain Grand Prix',
  circuit_short_name: 'Sakhir',
  country_name: 'Bahrain',
}

export const VERSTAPPEN: Schemas['DriverResponse'] = {
  driver_number: 1,
  name_acronym: 'VER',
  full_name: 'Max VERSTAPPEN',
  team_name: 'Red Bull Racing',
  team_colour: '3671C6',
}

export const LECLERC: Schemas['DriverResponse'] = {
  driver_number: 16,
  name_acronym: 'LEC',
  full_name: 'Charles LECLERC',
  team_name: 'Ferrari',
  team_colour: 'E8002D',
}

export const ENTRY: Schemas['SessionEntryResponse'] = {
  ...SESSION,
  drivers: [VERSTAPPEN, LECLERC],
}

export const REPLAY: Schemas['ReplayResponse'] = {
  replay_id: 'replay-1',
  session_key: SESSION.session_key,
  status: 'playing',
  speed: 1,
  session_s: 0,
  failure: null,
}

export function position(driverNumber: number, at_position: number): Schemas['PositionEvent'] {
  return { kind: 'position', at: EVENT_AT, driver_number: driverNumber, position: at_position }
}

export function interval(
  driverNumber: number,
  gaps: Partial<Omit<Schemas['IntervalEvent'], 'kind' | 'at' | 'driver_number'>>,
): Schemas['IntervalEvent'] {
  return {
    kind: 'interval',
    at: EVENT_AT,
    driver_number: driverNumber,
    gap_to_leader_s: null,
    gap_to_leader_laps: null,
    interval_s: null,
    interval_laps: null,
    ...gaps,
  }
}

export function lap(
  driverNumber: number,
  lapNumber: number,
  fields: Partial<Schemas['LapEvent']> = {},
): Schemas['LapEvent'] {
  return {
    kind: 'lap',
    at: EVENT_AT,
    driver_number: driverNumber,
    lap_number: lapNumber,
    lap_duration: 92.608,
    duration_sector_1: 29.1,
    duration_sector_2: 39.5,
    duration_sector_3: 24.008,
    i1_speed: 290,
    i2_speed: 250,
    st_speed: 310,
    is_pit_out_lap: false,
    compound: 'SOFT',
    tyre_age_laps: 3,
    ...fields,
  }
}

export function pit(driverNumber: number, lapNumber: number): Schemas['PitEvent'] {
  return {
    kind: 'pit',
    at: EVENT_AT,
    driver_number: driverNumber,
    lap_number: lapNumber,
    lane_duration: 22.4,
    stop_duration: 2.4,
  }
}

export function raceControl(
  seq: number,
  message: string,
  fields: Partial<Schemas['RaceControlEvent']> = {},
): Schemas['RaceControlEvent'] {
  return {
    kind: 'race_control',
    at: EVENT_AT,
    seq,
    category: 'Flag',
    flag: 'GREEN',
    scope: 'Track',
    sector: null,
    driver_number: null,
    lap_number: null,
    qualifying_phase: null,
    message,
    ...fields,
  }
}

export const WEATHER: Schemas['WeatherEvent'] = {
  kind: 'weather',
  at: EVENT_AT,
  air_temperature: 18.4,
  track_temperature: 26.1,
  humidity: 46,
  pressure: 1017.2,
  rainfall: false,
  wind_speed: 1.2,
  wind_direction: 135,
}

export const OVERTAKE: Schemas['OvertakeEvent'] = {
  kind: 'overtake',
  at: EVENT_AT,
  overtaking_driver_number: 16,
  overtaken_driver_number: 1,
  position: 1,
}

export const TEAM_RADIO: Schemas['TeamRadioEvent'] = {
  kind: 'team_radio',
  at: EVENT_AT,
  driver_number: 1,
  recording_url: 'https://livetiming.formula1.com/radio.mp3',
}
