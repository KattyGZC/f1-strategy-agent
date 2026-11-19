import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { createApiClient } from './api/client.ts'
import App from './App.tsx'
import {
  API_ORIGIN,
  ENTRY,
  fakeApi,
  fakeStreams,
  json,
  RACE,
  RACE_MODEL,
  SESSION,
} from './testing.ts'

const API = {
  'GET /api/health': () => json({ status: 'ok' }),
  'GET /api/sessions': () => json([SESSION]),
  'GET /api/races': () => json([RACE]),
  'GET /api/races/9472': () => json(RACE_MODEL),
  'GET /api/sessions/9472': () => json(ENTRY),
}

function renderApp(hash = '') {
  window.location.hash = hash
  const api = fakeApi(API)
  render(
    <App apiClient={createApiClient(API_ORIGIN, api.fetchImpl)} openStream={fakeStreams().open} />,
  )
  return api.requests
}

function count(requests: Request[], path: string) {
  return requests.filter((request) => new URL(request.url).pathname === path).length
}

afterEach(() => {
  window.location.hash = ''
})

describe('App', () => {
  it('renders the title, the API status and the sessions to replay', async () => {
    renderApp()

    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('F1 Strategy Agent')
    expect(await screen.findByText('API status: ok')).toBeInTheDocument()
    expect(await screen.findByRole('button', { name: 'Start replay' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Replay' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByRole('tabpanel', { name: 'Replay' })).toBeVisible()
  })

  it('opens the screen its hash names', async () => {
    renderApp('#/simulator')

    expect(await screen.findByRole('heading', { name: 'Compare race strategies' })).toBeVisible()
    expect(screen.getByRole('tab', { name: 'Simulator' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.queryByRole('tabpanel', { name: 'Replay' })).not.toBeInTheDocument()
  })

  it('opens a tab in the URL, and keeps the screen it leaves as it was', async () => {
    const requests = renderApp()
    await screen.findByRole('button', { name: 'Start replay' })

    fireEvent.click(screen.getByRole('tab', { name: 'Simulator' }))

    expect(await screen.findByRole('heading', { name: 'Compare race strategies' })).toBeVisible()
    expect(window.location.hash).toBe('#/simulator')
    expect(screen.getByRole('button', { name: 'Start replay', hidden: true })).not.toBeVisible()

    fireEvent.click(screen.getByRole('tab', { name: 'Replay' }))

    expect(await screen.findByRole('button', { name: 'Start replay' })).toBeVisible()
    expect(count(requests, '/api/sessions')).toBe(1)
  })

  it('moves between tabs with the arrows, Home and End, and focuses the one it opens', async () => {
    renderApp()
    const replay = screen.getByRole('tab', { name: 'Replay' })
    const simulator = screen.getByRole('tab', { name: 'Simulator' })
    expect(replay).toHaveAttribute('tabindex', '0')
    expect(simulator).toHaveAttribute('tabindex', '-1')

    expect(fireEvent.keyDown(replay, { key: 'ArrowRight' })).toBe(false)
    expect(await screen.findByRole('tab', { name: 'Simulator', selected: true })).toHaveFocus()

    fireEvent.keyDown(simulator, { key: 'Home' })
    expect(await screen.findByRole('tab', { name: 'Replay', selected: true })).toHaveFocus()

    fireEvent.keyDown(replay, { key: 'End' })
    expect(await screen.findByRole('tab', { name: 'Simulator', selected: true })).toHaveFocus()

    fireEvent.keyDown(simulator, { key: 'ArrowLeft' })
    expect(await screen.findByRole('tab', { name: 'Replay', selected: true })).toHaveFocus()

    expect(fireEvent.keyDown(replay, { key: 'a' })).toBe(true)
    expect(replay).toHaveAttribute('aria-selected', 'true')
    expect(window.location.hash).toBe('#/replay')
  })
})
