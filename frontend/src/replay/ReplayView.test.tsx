import { act, fireEvent, render, screen, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

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
  replayReset,
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
  'POST /api/replays/replay-1/seek': () => json({ ...REPLAY, session_s: 5_400 }),
}

function renderView(routes: Record<string, Route> = CONTROLS, onLeave = () => {}, entry = ENTRY) {
  const api = fakeApi(routes)
  const streams = fakeStreams()
  const view = render(
    <ReplayView
      client={createApiClient(API_ORIGIN, api.fetchImpl)}
      openStream={streams.open}
      replay={REPLAY}
      entry={entry}
      onLeave={onLeave}
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

function region(name: string) {
  return within(screen.getByRole('region', { name }))
}

function towerRowsShown() {
  return within(screen.getByRole('table')).getAllByRole('row').slice(1)
}

function towerCells() {
  return towerRowsShown().map((row) =>
    Array.from(row.querySelectorAll('th, td'), (cell) => cell.textContent),
  )
}

/** The value printed right after a label. */
function valueOf(scope: ReturnType<typeof within>, label: string) {
  return scope.getByText(label).nextElementSibling?.textContent
}

describe('ReplayView', () => {
  it('shows every driver, and says what has not arrived yet', () => {
    renderView()

    expect(towerCells()).toEqual([
      ['-', 'VER', '-', '-', '-', '-'],
      ['-', 'LEC', '-', '-', '-', '-'],
    ])
    expect(screen.getByText('Connecting...')).toBeInTheDocument()
    expect(screen.getByText('None yet')).toBeInTheDocument()
    expect(region('Weather').getByText('No reading yet.')).toBeInTheDocument()
    expect(region('Race control').getByText('No messages yet.')).toBeInTheDocument()
    expect(
      region('Circuit').getByText('The circuit map comes in a later version.'),
    ).toBeInTheDocument()
  })

  it('folds the events into the header, the tower, the weather and race control', async () => {
    const { stream } = renderView()

    await emit(
      stream,
      position(1, 2),
      position(16, 1),
      interval(1, { gap_to_leader_s: 1.5, interval_s: 1.234 }),
      lap(1, 12, { compound: 'HARD', tyre_age_laps: 0 }),
      lap(16, 12),
      pit(1, 11),
      WEATHER,
      raceControl(7, 'GREEN LIGHT - PIT EXIT OPEN'),
    )

    expect(towerCells()).toEqual([
      ['1', 'LEC', '-', '1:32.608', '3', '-'],
      ['2', 'VER', '+1.234', '1:32.608', '0', 'L11'],
    ])
    expect(within(towerRowsShown()[1] as HTMLElement).getByRole('img')).toHaveAccessibleName('Hard')
    const header = within(document.body)
    expect(valueOf(header, 'Leader lap')).toBe('12')
    expect(valueOf(header, 'Track flag')).toBe('Green')
    expect(screen.getByText('Session time, UTC').previousElementSibling).toHaveTextContent(
      '15:03:27',
    )
    expect(screen.getByText('Live replay')).toBeInTheDocument()
    const weather = region('Weather')
    expect(valueOf(weather, 'Track')).toBe('26.1 °C')
    expect(valueOf(weather, 'Wind')).toBe('1.2 m/s from 135°')
    expect(valueOf(weather, 'Rain')).toBe('Dry')
    expect(region('Race control').getByRole('listitem')).toHaveTextContent(
      '15:03:27 FlagGREEN LIGHT - PIT EXIT OPEN',
    )
  })

  it('shows the gap to the leader on demand', async () => {
    const { stream } = renderView()
    await emit(stream, interval(1, { gap_to_leader_laps: 1, interval_s: 0.4 }))

    fireEvent.click(screen.getByRole('button', { name: 'Gap to leader' }))

    expect(screen.getByRole('columnheader', { name: 'Gap' })).toBeInTheDocument()
    expect(towerCells()[0]?.[2]).toBe('+1 LAP')
    expect(screen.getByRole('button', { name: 'Gap to leader' })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
    fireEvent.click(screen.getByRole('button', { name: 'Interval' }))
    expect(towerCells()[0]?.[2]).toBe('+0.400')
  })

  it('shows a tyre without its age, and a message without a flag', async () => {
    const { stream } = renderView()

    await emit(
      stream,
      lap(1, 3, { tyre_age_laps: null }),
      raceControl(8, 'DRS DISABLED', { category: 'Drs', flag: null, scope: null }),
    )

    expect(towerCells()[0]?.[4]).toBe('')
    expect(within(towerRowsShown()[0] as HTMLElement).getByRole('img')).toHaveAccessibleName('Soft')
    expect(region('Race control').getByRole('listitem')).toHaveTextContent('DRSDRS DISABLED')
  })

  it('shows no driver card for a session without drivers', () => {
    const api = fakeApi(CONTROLS)
    render(
      <ReplayView
        client={createApiClient(API_ORIGIN, api.fetchImpl)}
        openStream={fakeStreams().open}
        replay={REPLAY}
        entry={{ ...ENTRY, drivers: [] }}
        onLeave={() => {}}
      />,
    )

    expect(screen.queryByRole('article', { name: 'Selected driver' })).not.toBeInTheDocument()
    expect(towerRowsShown()).toEqual([])
  })

  it('follows the first driver until another one is picked', async () => {
    const { stream } = renderView()
    await emit(stream, position(16, 1), position(1, 2), lap(1, 12))

    expect(
      within(screen.getByRole('article', { name: 'Selected driver' })).getByRole('heading'),
    ).toHaveTextContent('Charles LECLERC')
    fireEvent.click(screen.getByRole('button', { name: /VER/ }))

    const card = within(screen.getByRole('article', { name: 'Selected driver' }))
    expect(card.getByRole('heading')).toHaveTextContent('Max VERSTAPPEN')
    expect(card.getByText('P2, Red Bull Racing, #1')).toBeInTheDocument()
    expect(valueOf(card, 'Last lap, lap 12')).toBe('1:32.608')
    expect(valueOf(card, 'Sector 1')).toBe('29.100')
    expect(valueOf(card, 'Sector 3')).toBe('24.008')
    expect(valueOf(card, 'Speed trap, km/h')).toBe('310')
    expect(card.getByRole('img', { name: 'Soft' })).toBeInTheDocument()
    expect(screen.getByRole('row', { selected: true })).toHaveTextContent('VER')
  })

  it('shows rain', async () => {
    const { stream } = renderView()

    await emit(stream, { ...WEATHER, rainfall: true })

    expect(valueOf(region('Weather'), 'Rain')).toBe('Raining')
  })

  it('keeps the strategy tools visible but off until they exist', () => {
    renderView()

    const strategy = region('Strategy, coming soon')
    expect(strategy.getByRole('button', { name: 'What if...' })).toBeDisabled()
    expect(strategy.getByRole('button', { name: 'Ask the strategist' })).toBeDisabled()
    expect(strategy.getByRole('textbox')).toBeDisabled()
  })

  it('pauses, resumes and changes the speed through the API', async () => {
    const { requests } = renderView()

    fireEvent.click(screen.getByRole('button', { name: 'Pause' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Resume' }))
    await screen.findByRole('button', { name: 'Pause' })
    fireEvent.click(screen.getByRole('button', { name: '20x' }))

    await vi.waitFor(() =>
      expect(screen.getByRole('button', { name: '20x' })).toHaveAttribute('aria-pressed', 'true'),
    )
    expect(screen.getByText('1 second here is 20 seconds of session')).toBeInTheDocument()
    expect(requests.map((request) => `${request.method} ${new URL(request.url).pathname}`)).toEqual(
      [
        'POST /api/replays/replay-1/pause',
        'POST /api/replays/replay-1/resume',
        'PUT /api/replays/replay-1/speed',
      ],
    )
  })

  it('says real time at 1x', () => {
    renderView()

    expect(screen.getByText('Real time')).toBeInTheDocument()
  })

  it('disables the controls while a change is on its way', () => {
    renderView({ ...CONTROLS, 'POST /api/replays/replay-1/pause': () => new Promise(() => {}) })

    fireEvent.click(screen.getByRole('button', { name: 'Pause' }))

    expect(screen.getByRole('button', { name: 'Pause' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '60x' })).toBeDisabled()
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

  it('goes back to the sessions on request', () => {
    const onLeave = vi.fn()
    renderView(CONTROLS, onLeave)

    fireEvent.click(screen.getByRole('button', { name: 'Choose another session' }))

    expect(onLeave).toHaveBeenCalledOnce()
  })

  it('closes the stream when it unmounts', () => {
    const { stream, unmount } = renderView()

    unmount()

    expect(stream.readyState).toBe(CLOSED)
  })

  it('goes to a lap through the API and rebuilds the screen from the reset', async () => {
    const { stream, requests } = renderView()
    await emit(stream, position(1, 2), position(16, 1))

    fireEvent.change(screen.getByLabelText('Lap'), { target: { value: '30' } })
    fireEvent.click(screen.getByRole('button', { name: 'Go to lap' }))
    await vi.waitFor(() => expect(requests).toHaveLength(1))
    await emit(stream, replayReset(30, 5_400), position(1, 1))

    const [request] = requests
    expect(`${request?.method} ${new URL(request?.url ?? '').pathname}`).toBe(
      'POST /api/replays/replay-1/seek',
    )
    expect(await request?.json()).toEqual({ lap_number: 30 })
    expect(towerCells()).toEqual([
      ['1', 'VER', '-', '-', '-', '-'],
      ['-', 'LEC', '-', '-', '-', '-'],
    ])
  })

  it.each(['', '0', '58', '2.5', '-3'])('offers no lap for %j', (typed) => {
    renderView()

    fireEvent.change(screen.getByLabelText('Lap'), { target: { value: typed } })

    expect(screen.getByRole('button', { name: 'Go to lap' })).toBeDisabled()
  })

  it('offers the first and the last lap of the session', () => {
    renderView()
    const lapField = screen.getByLabelText('Lap')

    fireEvent.change(lapField, { target: { value: '1' } })
    const first = screen.getByRole('button', { name: 'Go to lap' })
    expect(first).toBeEnabled()
    fireEvent.change(lapField, { target: { value: '57' } })

    expect(screen.getByRole('button', { name: 'Go to lap' })).toBeEnabled()
    expect(lapField).toHaveAttribute('max', '57')
  })

  it('sends a lap on Enter, and nothing for a lap out of range', async () => {
    const { requests } = renderView()
    const lapField = screen.getByLabelText('Lap')

    fireEvent.change(lapField, { target: { value: '99' } })
    fireEvent.submit(lapField)
    fireEvent.change(lapField, { target: { value: '12' } })
    fireEvent.submit(lapField)

    await vi.waitFor(() => expect(requests).toHaveLength(1))
    expect(await requests[0]?.json()).toEqual({ lap_number: 12 })
  })

  it('shows no lap to go to in a session without laps', () => {
    renderView(CONTROLS, () => {}, { ...ENTRY, last_lap_number: null })

    expect(screen.queryByLabelText('Lap')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Go to lap' })).not.toBeInTheDocument()
  })

  it('says why a seek failed', async () => {
    renderView({
      ...CONTROLS,
      'POST /api/replays/replay-1/seek': () =>
        json({ detail: 'session 9472 has no start for lap 30' }, 404),
    })

    fireEvent.change(screen.getByLabelText('Lap'), { target: { value: '30' } })
    fireEvent.click(screen.getByRole('button', { name: 'Go to lap' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'The replay did not change: session 9472 has no start for lap 30',
    )
  })
})
