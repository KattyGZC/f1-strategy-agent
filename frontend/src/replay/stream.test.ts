import { describe, expect, it } from 'vitest'

import { CLOSED, CONNECTING, fakeStreams, lap, position, WEATHER } from '../testing.ts'
import type { ReplayEvent } from './fold.ts'
import { watchReplay, type StreamLink } from './stream.ts'

function watched(replayId = 'replay-1') {
  const { open, streams } = fakeStreams()
  const batches: (readonly ReplayEvent[])[] = []
  const links: StreamLink[] = []
  let frames: (() => void)[] = []
  const stop = watchReplay(
    open,
    replayId,
    { onEvents: (events) => batches.push(events), onLink: (link) => links.push(link) },
    (flush) => frames.push(flush),
  )
  const [stream] = streams
  if (stream === undefined) {
    throw new Error('watchReplay opened no stream')
  }
  const nextFrame = () => {
    const due = frames
    frames = []
    for (const flush of due) {
      flush()
    }
  }
  return { stream, batches, links, stop, nextFrame }
}

describe('watchReplay', () => {
  it('opens the events route of the replay', () => {
    expect(watched('a b/c').stream.path).toBe('/api/replays/a%20b%2Fc/events')
  })

  it('hands over the events of a frame together, in the order they arrived', () => {
    const { stream, batches, links, nextFrame } = watched()

    stream.emit('position', position(1, 1))
    stream.emit('lap', lap(1, 1))
    stream.emit('weather', WEATHER)
    const before = [...batches]
    nextFrame()

    expect(before).toEqual([])
    expect(batches).toEqual([[position(1, 1), lap(1, 1), WEATHER]])
    expect(links).toEqual([{ kind: 'live' }])
  })

  it('starts a new batch after each frame, with the same live link', () => {
    const { stream, batches, links, nextFrame } = watched()

    stream.emit('position', position(1, 1))
    nextFrame()
    stream.emit('position', position(1, 2))
    nextFrame()
    nextFrame()

    expect(batches).toEqual([[position(1, 1)], [position(1, 2)]])
    expect(links).toHaveLength(2)
    expect(new Set(links).size).toBe(1)
  })

  it('hands over what arrived before a failure, then stops with its message', () => {
    const { stream, batches, links } = watched()

    stream.emit('position', position(1, 1))
    stream.emit('replay_failed', { kind: 'replay_failed', message: 'boom' })

    expect(stream.readyState).toBe(CLOSED)
    expect(batches).toEqual([[position(1, 1)]])
    expect(links).toEqual([{ kind: 'live' }, { kind: 'failed', message: 'boom' }])
  })

  it('reports a failure alone when nothing is pending', () => {
    const { stream, batches, links } = watched()

    stream.emit('replay_failed', { kind: 'replay_failed', message: 'boom' })

    expect(batches).toEqual([])
    expect(links).toEqual([{ kind: 'failed', message: 'boom' }])
  })

  it('reports a dropped link as reconnecting, and one the browser gave up as ended', () => {
    const { stream, links } = watched()

    stream.fail(CONNECTING)
    stream.fail(CLOSED)

    expect(links).toEqual([{ kind: 'reconnecting' }, { kind: 'ended' }])
  })

  it('closes the stream and drops what is pending when the watch stops', () => {
    const { stream, batches, links, stop, nextFrame } = watched()

    stream.emit('position', position(1, 1))
    stop()
    nextFrame()

    expect(stream.readyState).toBe(CLOSED)
    expect(batches).toEqual([])
    expect(links).toEqual([])
  })

  it.each([
    [
      'of another kind',
      new MessageEvent('lap', { data: JSON.stringify(position(1, 2)) }),
      'holding another kind',
    ],
    ['null', new MessageEvent('lap', { data: 'null' }), 'holding another kind'],
    ['a string', new MessageEvent('lap', { data: '"lap"' }), 'holding another kind'],
    [
      'without a kind',
      new MessageEvent('lap', { data: '{"driver_number":1}' }),
      'holding another kind',
    ],
    ['not JSON', new MessageEvent('lap', { data: '{' }), 'whose data is not JSON'],
    ['without data', new Event('lap'), 'without data'],
    ['with data that is not text', new MessageEvent('lap', { data: 7 }), 'without data'],
  ])('fails the watch on an event %s, after what arrived before it', (_, message, problem) => {
    const { stream, batches, links, nextFrame } = watched()

    stream.emit('position', position(1, 1))
    stream.dispatch(message)
    nextFrame()

    expect(stream.readyState).toBe(CLOSED)
    expect(batches).toEqual([[position(1, 1)]])
    expect(links).toEqual([
      { kind: 'live' },
      { kind: 'failed', message: `the stream sent a lap event ${problem}` },
    ])
  })

  it('reports the link live again once the browser reconnects', () => {
    const { stream, links } = watched()

    stream.fail(CONNECTING)
    stream.dispatch(new Event('open'))

    expect(links).toEqual([{ kind: 'reconnecting' }, { kind: 'live' }])
  })

  it('hands over on the next animation frame by default', async () => {
    const { open, streams } = fakeStreams()
    const batches: (readonly ReplayEvent[])[] = []
    watchReplay(open, 'replay-1', { onEvents: (events) => batches.push(events), onLink: () => {} })

    streams[0]?.emit('position', position(1, 1))
    await new Promise(requestAnimationFrame)

    expect(batches).toEqual([[position(1, 1)]])
  })
})
