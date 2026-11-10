import { act, fireEvent, render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { createApiClient } from '../api/client.ts'
import {
  API_ORIGIN,
  ENTRY,
  fakeApi,
  fakeStreams,
  json,
  REPLAY,
  SESSION,
  type Route,
} from '../testing.ts'
import { ReplayScreen } from './ReplayScreen.tsx'

const QUALIFYING = { ...SESSION, session_key: 9468, session_name: 'Qualifying' } as const

const API: Record<string, Route> = {
  'GET /api/sessions': () => json([SESSION, QUALIFYING]),
  'GET /api/sessions/9472': () => json(ENTRY),
  'GET /api/sessions/9468': () => json({ ...ENTRY, ...QUALIFYING }),
  'POST /api/replays': () => json(REPLAY, 201),
}

/** Rejects as fetch does when its request is aborted. */
const abortable: Route = (request) =>
  new Promise((_, reject) =>
    request.signal.addEventListener('abort', () => reject(new DOMException('', 'AbortError'))),
  )

function renderScreen(routes: Record<string, Route> = API) {
  const api = fakeApi(routes)
  const streams = fakeStreams()
  render(
    <ReplayScreen client={createApiClient(API_ORIGIN, api.fetchImpl)} openStream={streams.open} />,
  )
  return { requests: api.requests, streams: streams.streams }
}

async function startReplay() {
  fireEvent.click(await screen.findByRole('button', { name: 'Start replay' }))
}

describe('ReplayScreen', () => {
  it('lists the loaded sessions, the latest first', async () => {
    renderScreen()

    const options = within(await screen.findByLabelText('Session')).getAllByRole('option')

    expect(options.map((option) => option.textContent)).toEqual([
      '2024 Bahrain Grand Prix, Race',
      '2024 Bahrain Grand Prix, Qualifying',
    ])
  })

  it('starts the chosen session at the chosen speed and watches it', async () => {
    const { requests, streams } = renderScreen()

    fireEvent.change(await screen.findByLabelText('Session'), { target: { value: '9468' } })
    fireEvent.change(screen.getByLabelText('Speed'), { target: { value: '60' } })
    await startReplay()

    expect(await screen.findByRole('heading', { name: /Qualifying/ })).toBeInTheDocument()
    const started = requests.find((request) => request.method === 'POST')
    expect(await started?.json()).toEqual({ session_key: 9468, speed: 60 })
    expect(streams.map((stream) => stream.path)).toEqual(['/api/replays/replay-1/events'])
  })

  it('ignores a speed that is not one of the replay speeds', async () => {
    const { requests } = renderScreen()

    fireEvent.change(await screen.findByLabelText('Speed'), { target: { value: '3' } })
    await startReplay()

    await screen.findByRole('region', { name: 'Replay' })
    const started = requests.find((request) => request.method === 'POST')
    expect(await started?.json()).toEqual({ session_key: 9472, speed: 1 })
  })

  it('shows the start as pending until the API answers', async () => {
    renderScreen({ ...API, 'GET /api/sessions/9472': () => new Promise(() => {}) })

    await startReplay()

    expect(screen.getByRole('button', { name: 'Starting...' })).toBeDisabled()
  })

  it('goes back to the sessions from a replay', async () => {
    renderScreen()
    await startReplay()

    fireEvent.click(await screen.findByRole('button', { name: 'Choose another session' }))

    expect(await screen.findByRole('button', { name: 'Start replay' })).toBeEnabled()
    expect(screen.queryByRole('region', { name: 'Replay' })).not.toBeInTheDocument()
  })

  it('says why a replay over the limit did not start', async () => {
    const { requests } = renderScreen({
      ...API,
      'POST /api/replays': () => json({ detail: 'too many active replays' }, 503),
    })

    await startReplay()

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'The replay did not start: too many active replays',
    )
    expect(requests.filter((request) => request.method === 'POST')).toHaveLength(1)
  })

  it('does not start a replay of a session it cannot read', async () => {
    const { requests } = renderScreen({
      ...API,
      'GET /api/sessions/9472': () =>
        json({ detail: 'session 9472 is not in the clean model' }, 404),
    })

    await startReplay()

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'The replay did not start: session 9472 is not in the clean model',
    )
    expect(requests.filter((request) => request.method === 'POST')).toEqual([])
  })

  it('names the HTTP status when the API sends no detail', async () => {
    renderScreen({ ...API, 'POST /api/replays': () => new Response('', { status: 502 }) })

    await startReplay()

    expect(await screen.findByRole('alert')).toHaveTextContent('the API answered HTTP 502')
  })

  it('reports an unreachable API on start', async () => {
    renderScreen({ ...API, 'POST /api/replays': () => Promise.reject(new TypeError('down')) })

    await startReplay()

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'The replay did not start: the API is unreachable',
    )
  })

  it('says when no session is loaded yet', async () => {
    renderScreen({ ...API, 'GET /api/sessions': () => json([]) })

    expect(await screen.findByText(/No session is loaded yet/)).toBeInTheDocument()
  })

  it('says why the sessions could not be listed', async () => {
    renderScreen({ ...API, 'GET /api/sessions': () => json({ detail: 'database down' }, 500) })

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Could not list the sessions: database down',
    )
  })

  it('reports an unreachable API while listing', async () => {
    renderScreen({ ...API, 'GET /api/sessions': () => Promise.reject(new TypeError('down')) })

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Could not list the sessions: the API is unreachable',
    )
  })

  it('stops listing when it unmounts', async () => {
    const api = fakeApi({ 'GET /api/sessions': abortable })
    const { unmount } = render(
      <ReplayScreen
        client={createApiClient(API_ORIGIN, api.fetchImpl)}
        openStream={fakeStreams().open}
      />,
    )
    expect(screen.getByText('Loading the sessions...')).toBeInTheDocument()

    await act(async () => unmount())

    expect(api.requests.map((request) => request.signal.aborted)).toEqual([true])
  })
})
