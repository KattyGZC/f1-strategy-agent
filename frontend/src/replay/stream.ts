import { EVENT_KINDS } from '../api/closedSets.ts'
import type { components, paths } from '../api/schema.ts'
import type { ReplayEvent } from './fold.ts'

type ReplayFailedEvent = components['schemas']['ReplayFailedEvent']
type StreamEvent = ReplayEvent | ReplayFailedEvent
type Received = { kind: 'event'; event: StreamEvent } | { kind: 'invalid'; reason: string }

const EVENTS_PATH = '/api/replays/{replay_id}/events' satisfies keyof paths
const REPLAY_FAILED: ReplayFailedEvent['kind'] = 'replay_failed'
/** `EventSource.CLOSED`, which jsdom does not define: the browser gave up reconnecting. */
const CLOSED = 2

/** What the screen needs of an `EventSource`, so tests can drive one by hand. */
export interface EventStream {
  addEventListener(type: string, listener: (event: Event) => void): void
  close(): void
  readonly readyState: number
}

export type OpenEventStream = (path: string) => EventStream

export type StreamLink =
  | { kind: 'connecting' }
  | { kind: 'live' }
  | { kind: 'reconnecting' }
  | { kind: 'ended' }
  | { kind: 'failed'; message: string }

export const CONNECTING: StreamLink = { kind: 'connecting' }
// One object for every batch, so a state setter given it again does not render again.
const LIVE: StreamLink = { kind: 'live' }

export interface StreamHandlers {
  /** The events that arrived since the last call, in the order they arrived. */
  onEvents(events: readonly ReplayEvent[]): void
  onLink(link: StreamLink): void
}

export type ScheduleFlush = (flush: () => void) => void

// At 60x the 2024 Bahrain race sends about 345 events a second while it runs (1,727 in 5 s,
// measured in the browser 2026-11-05); the view renders once per frame, not once per event.
const nextFrame: ScheduleFlush = (flush) => {
  requestAnimationFrame(flush)
}

/** Watches a replay's events until the returned function is called. The browser reconnects
 * on its own and resumes after the last event it received (ADR 0009). */
export function watchReplay(
  open: OpenEventStream,
  replayId: string,
  handlers: StreamHandlers,
  schedule: ScheduleFlush = nextFrame,
): () => void {
  const stream = open(EVENTS_PATH.replace('{replay_id}', encodeURIComponent(replayId)))
  let pending: ReplayEvent[] = []
  let watching = true
  const flush = () => {
    if (watching && pending.length > 0) {
      const batch = pending
      pending = []
      handlers.onLink(LIVE)
      handlers.onEvents(batch)
    }
  }
  const fail = (message: string) => {
    stream.close()
    flush()
    handlers.onLink({ kind: 'failed', message })
  }
  const receive = (message: Event) => {
    const received = parse(message)
    if (received.kind === 'invalid') {
      fail(received.reason)
      return
    }
    const { event } = received
    if (event.kind === REPLAY_FAILED) {
      fail(event.message)
      return
    }
    pending.push(event)
    if (pending.length === 1) {
      schedule(flush)
    }
  }
  for (const kind of [...EVENT_KINDS, REPLAY_FAILED]) {
    stream.addEventListener(kind, receive)
  }
  stream.addEventListener('open', () => handlers.onLink(LIVE))
  stream.addEventListener('error', () => {
    handlers.onLink({ kind: stream.readyState === CLOSED ? 'ended' : 'reconnecting' })
  })
  return () => {
    watching = false
    stream.close()
  }
}

/** The event's data, checked to be of the kind its SSE name says; the listener is only
 * registered for the stream's kinds. Its fields are not checked again: the API emits them
 * from the schema this client is generated from. */
function parse(message: Event): Received {
  if (!(message instanceof MessageEvent) || typeof message.data !== 'string') {
    return invalid(message, 'without data')
  }
  let data: unknown
  try {
    data = JSON.parse(message.data)
  } catch {
    return invalid(message, 'whose data is not JSON')
  }
  if (
    typeof data !== 'object' ||
    data === null ||
    !('kind' in data) ||
    data.kind !== message.type
  ) {
    return invalid(message, 'holding another kind')
  }
  return { kind: 'event', event: data as StreamEvent }
}

function invalid(message: Event, problem: string): Received {
  return { kind: 'invalid', reason: `the stream sent a ${message.type} event ${problem}` }
}
