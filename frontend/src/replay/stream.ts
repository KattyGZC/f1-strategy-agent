import { EVENT_KINDS } from '../api/closedSets.ts'
import type { components, paths } from '../api/schema.ts'
import type { EventBatch, ReplayEvent } from './fold.ts'

type ReplayFailedEvent = components['schemas']['ReplayFailedEvent']
type ReplayResetEvent = components['schemas']['ReplayResetEvent']
type StreamEvent = ReplayEvent | ReplayFailedEvent | ReplayResetEvent
type Received = { kind: 'event'; event: StreamEvent } | { kind: 'invalid'; reason: string }

const EVENTS_PATH = '/api/replays/{replay_id}/events' satisfies keyof paths
const REPLAY_FAILED: ReplayFailedEvent['kind'] = 'replay_failed'
const REPLAY_RESET: ReplayResetEvent['kind'] = 'replay_reset'
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
  /** What arrived since the last call: the events in the order they arrived, after a reset
   * when a seek dropped what came before (ADR 0012). */
  onBatch(batch: EventBatch): void
  onLink(link: StreamLink): void
}

export type ScheduleFlush = (flush: () => void) => void

// At 60x the 2024 Bahrain race sends about 345 events a second while it runs (1,727 in 5 s,
// measured in the browser 2026-11-05); the view renders once per frame, not once per event.
const nextFrame: ScheduleFlush = (flush) => {
  requestAnimationFrame(flush)
}

/** Collects what arrives and hands it over once per scheduled flush; a reset drops what is
 * not handed over yet, since a seek replaced it (ADR 0012). */
function frameBatcher(handlers: StreamHandlers, schedule: ScheduleFlush) {
  let pending: ReplayEvent[] = []
  let resetPending = false
  let scheduled = false
  let open = true
  const flush = () => {
    scheduled = false
    if (open && (resetPending || pending.length > 0)) {
      const batch = { reset: resetPending, events: pending }
      pending = []
      resetPending = false
      handlers.onLink(LIVE)
      handlers.onBatch(batch)
    }
  }
  const queue = () => {
    if (!scheduled) {
      scheduled = true
      schedule(flush)
    }
  }
  return {
    push(event: ReplayEvent) {
      pending.push(event)
      queue()
    },
    reset() {
      pending = []
      resetPending = true
      queue()
    },
    flush,
    close() {
      open = false
    },
  }
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
  const batcher = frameBatcher(handlers, schedule)
  const fail = (message: string) => {
    stream.close()
    batcher.flush()
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
    if (event.kind === REPLAY_RESET) {
      batcher.reset()
    } else {
      batcher.push(event)
    }
  }
  for (const kind of [...EVENT_KINDS, REPLAY_FAILED, REPLAY_RESET]) {
    stream.addEventListener(kind, receive)
  }
  stream.addEventListener('open', () => handlers.onLink(LIVE))
  stream.addEventListener('error', () => {
    handlers.onLink({ kind: stream.readyState === CLOSED ? 'ended' : 'reconnecting' })
  })
  return () => {
    batcher.close()
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
