import { act, fireEvent, render, screen, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

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
const ABU_DHABI = {
  ...SESSION,
  session_key: 9662,
  meeting_key: 1252,
  date_start: '2024-12-08T13:00:00Z',
  meeting_name: 'Abu Dhabi Grand Prix',
  circuit_short_name: 'Yas Marina Circuit',
  country_name: 'United Arab Emirates',
} as const

const API: Record<string, Route> = {
  'GET /api/sessions': () => json([ABU_DHABI, SESSION, QUALIFYING]),
  'GET /api/sessions/9662': () => json({ ...ENTRY, ...ABU_DHABI }),
  'GET /api/sessions/9472': () => json(ENTRY),
  'GET /api/sessions/9468': () => json({ ...ENTRY, ...QUALIFYING }),
  'POST /api/replays': () => json(REPLAY, 201),
  'DELETE /api/replays/replay-1': () => new Response(null, { status: 204 }),
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
  it('groups the loaded sessions by Grand Prix, the latest first', async () => {
    renderScreen()

    const cards = await screen.findAllByRole('article')

    expect(cards.map((card) => within(card).getByRole('heading').textContent)).toEqual([
      'Abu Dhabi Grand Prix',
      'Bahrain Grand Prix',
    ])
    expect(
      within(cards[1] as HTMLElement)
        .getAllByRole('button')
        .map((button) => button.textContent),
    ).toEqual(['Race', 'Qualifying'])
  })

  it('is ready to start the latest session at real time', async () => {
    renderScreen()

    const ready = within(await screen.findByRole('complementary', { name: 'Ready to start' }))

    expect(ready.getByRole('heading')).toHaveTextContent('Abu Dhabi Grand Prix')
    expect(ready.getByText('Race, Yas Marina Circuit, 8 Dec 2024')).toBeInTheDocument()
    expect(ready.getByRole('button', { name: '1x' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getAllByRole('article')[0]).toHaveAttribute('aria-current', 'true')
  })

  it('starts the chosen session at the chosen speed and watches it', async () => {
    const { requests, streams } = renderScreen()
    const bahrain = within((await screen.findAllByRole('article'))[1] as HTMLElement)

    fireEvent.click(bahrain.getByRole('button', { name: 'Qualifying' }))
    fireEvent.click(screen.getByRole('button', { name: '60x' }))
    const ready = within(screen.getByRole('complementary', { name: 'Ready to start' }))
    expect(ready.getByText('Qualifying, Sakhir, 2 Mar 2024')).toBeInTheDocument()
    await startReplay()

    expect(await screen.findByRole('heading', { name: 'Bahrain Grand Prix' })).toBeInTheDocument()
    const started = requests.find((request) => request.method === 'POST')
    expect(await started?.json()).toEqual({ session_key: 9468, speed: 60 })
    expect(streams.map((stream) => stream.path)).toEqual(['/api/replays/replay-1/events'])
  })

  it('shows the start as pending until the API answers', async () => {
    renderScreen({ ...API, 'GET /api/sessions/9662': () => new Promise(() => {}) })

    await startReplay()

    expect(screen.getByRole('button', { name: 'Starting...' })).toBeDisabled()
  })

  it('stops the replay it leaves and goes back to the sessions', async () => {
    const { requests } = renderScreen()
    await startReplay()

    fireEvent.click(await screen.findByRole('button', { name: 'Choose another session' }))

    expect(await screen.findByRole('button', { name: 'Start replay' })).toBeEnabled()
    expect(screen.queryByRole('region', { name: 'Replay' })).not.toBeInTheDocument()
    await vi.waitFor(() =>
      expect(
        requests.map((request) => `${request.method} ${new URL(request.url).pathname}`),
      ).toContain('DELETE /api/replays/replay-1'),
    )
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('says nothing when the replay it leaves was already gone', async () => {
    renderScreen({
      ...API,
      'DELETE /api/replays/replay-1': () =>
        json({ detail: 'replay replay-1 does not exist or has expired' }, 404),
    })
    await startReplay()

    fireEvent.click(await screen.findByRole('button', { name: 'Choose another session' }))
    await screen.findByRole('button', { name: 'Start replay' })
    await new Promise((resolve) => setTimeout(resolve, 0))

    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('keeps watching a new replay when the old one fails to stop late', async () => {
    const answers: ((response: Response) => void)[] = []
    renderScreen({
      ...API,
      'DELETE /api/replays/replay-1': () =>
        new Promise<Response>((resolve) => answers.push(resolve)),
    })
    await startReplay()
    fireEvent.click(await screen.findByRole('button', { name: 'Choose another session' }))
    await startReplay()
    await screen.findByRole('region', { name: 'Replay' })

    await act(async () => answers[0]?.(json({ detail: 'redis down' }, 500)))

    expect(screen.getByRole('region', { name: 'Replay' })).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it.each([
    [
      'the API refuses',
      () => json({ detail: 'redis down' }, 500),
      'The last replay could not be stopped (redis down); it ends on its own after a few idle minutes.',
    ],
    [
      'the API is unreachable',
      () => Promise.reject(new TypeError('down')),
      'The last replay could not be stopped (the API is unreachable); it ends on its own after a few idle minutes.',
    ],
  ])('says when %s to stop the replay it leaves', async (_, stop: Route, message) => {
    renderScreen({ ...API, 'DELETE /api/replays/replay-1': stop })
    await startReplay()

    fireEvent.click(await screen.findByRole('button', { name: 'Choose another session' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(message)
    expect(screen.getByRole('button', { name: 'Start replay' })).toBeEnabled()
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
      'GET /api/sessions/9662': () =>
        json({ detail: 'session 9662 is not in the clean model' }, 404),
    })

    await startReplay()

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'The replay did not start: session 9662 is not in the clean model',
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
