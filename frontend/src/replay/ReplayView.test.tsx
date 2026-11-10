import { act, fireEvent, render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { createApiClient } from '../api/client.ts'
import {
  API_ORIGIN,
  CLOSED,
  CONNECTING,
  ENTRY,
  fakeApi,
  fakeStreams,
  interval,
  json,
  lap,
  pit,
  position,
  raceControl,
  REPLAY,
  WEATHER,
  type FakeEventStream,
  type Route,
} from '../testing.ts'
import { ReplayView } from './ReplayView.tsx'

const CONTROLS: Record<string, Route> = {
  'POST /api/replays/replay-1/pause': () => json({ ...REPLAY, status: 'paused' }),
  'POST /api/replays/replay-1/resume': () => json(REPLAY),
  'PUT /api/replays/replay-1/speed': async (request) =>
    json({ ...REPLAY, speed: ((await request.json()) as { speed: number }).speed }),
}

function renderView(routes: Record<string, Route> = CONTROLS) {
  const api = fakeApi(routes)
  const streams = fakeStreams()
  const view = render(
    <ReplayView
      client={createApiClient(API_ORIGIN, api.fetchImpl)}
      openStream={streams.open}
      replay={REPLAY}
      entry={ENTRY}
    />,
  )
  const [stream] = streams.streams
  if (stream === undefined) {
    throw new Error('the view opened no stream')
  }
  return { ...view, stream, requests: api.requests }
}

/** Sends the events and waits for the frame that hands them to the view. */
async function emit(
  stream: FakeEventStream,
  ...events: ({ kind: string } & Record<string, unknown>)[]
) {
  await act(async () => {
    for (const event of events) {
      stream.emit(event.kind, event)
    }
    await new Promise(requestAnimationFrame)
  })
}

function towerCells() {
  const rows = within(screen.getByRole('table', { name: 'Timing' }))
    .getAllByRole('row')
    .slice(1)
  return rows.map((row) => Array.from(row.querySelectorAll('th, td'), (cell) => cell.textContent))
}

describe('ReplayView', () => {
  it('shows every driver before any event arrives', () => {
    renderView()

    expect(towerCells()).toEqual([
      ['-', 'VER', '-', '-', '-', '-', '-', '-'],
      ['-', 'LEC', '-', '-', '-', '-', '-', '-'],
    ])
    expect(screen.getByText('Connecting...')).toBeInTheDocument()
    expect(screen.getByText('No reading yet.')).toBeInTheDocument()
    expect(screen.getByText('No messages yet.')).toBeInTheDocument()
  })

  it('folds the events into the tower, the weather and race control', async () => {
    const { stream } = renderView()

    await emit(
      stream,
      position(1, 2),
      position(16, 1),
      interval(1, { gap_to_leader_s: 1.234, interval_s: 1.234 }),
      lap(1, 12, { compound: 'HARD', tyre_age_laps: 0 }),
      pit(1, 11),
      WEATHER,
      raceControl(7, 'DRS ENABLED'),
    )

    expect(towerCells()).toEqual([
      ['1', 'LEC', '-', '-', '-', '-', '-', '-'],
      ['2', 'VER', '+1.234', '+1.234', '1:32.608', '12', 'HARD (0)', 'L11'],
    ])
    expect(screen.getByRole('rowheader', { name: /VER/ })).toHaveAttribute(
      'title',
      'Max VERSTAPPEN, Red Bull Racing',
    )
    expect(screen.getByText('26.1 °C')).toBeInTheDocument()
    expect(screen.getByText('1.2 m/s from 135°')).toBeInTheDocument()
    expect(screen.getByText('No')).toBeInTheDocument()
    expect(screen.getByRole('listitem')).toHaveTextContent('15:03:27 DRS ENABLED')
    expect(screen.getByText(/UTC/)).toHaveTextContent('15:03:27 UTC. Live')
  })

  it('shows a compound without an age, and rain', async () => {
    const { stream } = renderView()

    await emit(stream, lap(16, 3, { tyre_age_laps: null }), { ...WEATHER, rainfall: true })

    expect(towerCells()[1]).toEqual(['-', 'LEC', '-', '-', '1:32.608', '3', 'SOFT', '-'])
    expect(screen.getByText('Yes')).toBeInTheDocument()
  })

  it('pauses, resumes and changes the speed through the API', async () => {
    const { requests } = renderView()

    fireEvent.click(screen.getByRole('button', { name: 'Pause' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Resume' }))
    await screen.findByRole('button', { name: 'Pause' })
    fireEvent.change(screen.getByLabelText('Speed'), { target: { value: '20' } })

    expect(await screen.findByDisplayValue('20x')).toBeInTheDocument()
    expect(requests.map((request) => `${request.method} ${new URL(request.url).pathname}`)).toEqual(
      [
        'POST /api/replays/replay-1/pause',
        'POST /api/replays/replay-1/resume',
        'PUT /api/replays/replay-1/speed',
      ],
    )
  })

  it('disables the controls while a change is on its way', () => {
    renderView({ ...CONTROLS, 'POST /api/replays/replay-1/pause': () => new Promise(() => {}) })

    fireEvent.click(screen.getByRole('button', { name: 'Pause' }))

    expect(screen.getByRole('button', { name: 'Pause' })).toBeDisabled()
    expect(screen.getByLabelText('Speed')).toBeDisabled()
  })

  it('says why a control failed and keeps the playback it had', async () => {
    renderView({
      ...CONTROLS,
      'POST /api/replays/replay-1/pause': () => json({ detail: 'replay replay-1 expired' }, 404),
    })

    fireEvent.click(screen.getByRole('button', { name: 'Pause' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'The replay did not change: replay replay-1 expired',
    )
    expect(screen.getByRole('button', { name: 'Pause' })).toBeEnabled()
  })

  it('clears a control error once a control succeeds', async () => {
    let calls = 0
    renderView({
      ...CONTROLS,
      'POST /api/replays/replay-1/pause': () =>
        ++calls === 1
          ? Promise.reject(new TypeError('down'))
          : json({ ...REPLAY, status: 'paused' }),
    })

    fireEvent.click(screen.getByRole('button', { name: 'Pause' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('the API is unreachable')
    fireEvent.click(await screen.findByRole('button', { name: 'Pause' }))

    expect(await screen.findByRole('button', { name: 'Resume' })).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('reports the link as it drops, ends or fails', async () => {
    const { stream } = renderView()

    act(() => stream.fail(CONNECTING))
    expect(screen.getByText('Reconnecting...')).toBeInTheDocument()
    act(() => stream.fail(CLOSED))
    expect(screen.getByRole('status')).toHaveTextContent('The replay has ended')
    await emit(stream, { kind: 'replay_failed', message: 'boom' })
    expect(screen.getByRole('alert')).toHaveTextContent('The replay failed: boom')
  })

  it('closes the stream when it unmounts', () => {
    const { stream, unmount } = renderView()

    unmount()

    expect(stream.readyState).toBe(CLOSED)
  })
})
