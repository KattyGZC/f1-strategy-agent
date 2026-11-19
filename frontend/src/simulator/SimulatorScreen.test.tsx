import { fireEvent, render, screen, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { createApiClient } from '../api/client.ts'
import {
  API_ORIGIN,
  ENTRY,
  fakeApi,
  json,
  RACE,
  RACE_MODEL,
  SIMULATION,
  TWO_STOPS,
  abortable,
  type Route,
} from '../testing.ts'
import { SimulatorScreen } from './SimulatorScreen.tsx'

const JEDDAH = {
  ...RACE,
  session_key: 9480,
  date_start: '2024-03-09T17:00:00Z',
  meeting_name: 'Saudi Arabian Grand Prix',
  circuit_short_name: 'Jeddah',
  country_name: 'Saudi Arabia',
  race_laps: 50,
} as const

const API: Record<string, Route> = {
  'GET /api/races': () => json([RACE, JEDDAH]),
  'GET /api/races/9472': () => json(RACE_MODEL),
  'GET /api/sessions/9472': () => json(ENTRY),
  'GET /api/races/9480': () =>
    json({
      ...RACE_MODEL,
      session_key: 9480,
      race_laps: 50,
      compounds: [RACE_MODEL.compounds[1]],
      driver_numbers: [16, 99],
      pit_loss: { pit_loss_s: 21.1, stops: 3, reliable: false },
      track_temperature: null,
    }),
  'GET /api/sessions/9480': () => json({ ...ENTRY, session_key: 9480 }),
  'POST /api/simulations': () => json(SIMULATION),
}

function renderScreen(routes: Record<string, Route> = API) {
  const api = fakeApi(routes)
  const view = render(<SimulatorScreen client={createApiClient(API_ORIGIN, api.fetchImpl)} />)
  return { requests: api.requests, unmount: view.unmount }
}

function paths(requests: Request[]) {
  return requests.map((request) => `${request.method} ${new URL(request.url).pathname}`)
}

async function strategy(number: number) {
  return within(await screen.findByRole('group', { name: `Strategy ${number}` }))
}

function stint(group: ReturnType<typeof within>, number: number) {
  return within(group.getByRole('group', { name: `Stint ${number}` }))
}

async function sentBody(requests: Request[]) {
  const posted = requests.find((request) => request.method === 'POST')
  return posted?.json()
}

describe('SimulatorScreen', () => {
  it('opens on the first calibrated race with its model', async () => {
    renderScreen()

    const model = within(await screen.findByRole('complementary', { name: "The race's model" }))

    expect(screen.getByRole('combobox', { name: 'Race' })).toHaveValue('9472')
    expect(model.getByRole('heading')).toHaveTextContent('Bahrain Grand Prix')
    expect(model.getByText('24.343 s over 42 stops')).toBeInTheDocument()
    expect(model.getByText('21.9 to 23.8 °C, median 22.8')).toBeInTheDocument()
    expect(model.getByText('0.454 s per lap')).toBeInTheDocument()
    expect(model.getAllByRole('listitem').map((item) => item.textContent)).toEqual([
      'Soft tyres of 1 to 20 laps',
      'Hard tyres of 1 to 29 laps',
    ])
  })

  it('says when no stop of the race could be measured', async () => {
    renderScreen({ ...API, 'GET /api/races/9472': () => json({ ...RACE_MODEL, pit_loss: null }) })

    const model = within(await screen.findByRole('complementary', { name: "The race's model" }))

    expect(model.getByText('not measured')).toBeInTheDocument()
  })

  it('keeps the race and the compound when a choice names neither', async () => {
    const { requests } = renderScreen()
    const first = await strategy(1)

    fireEvent.change(screen.getByRole('combobox', { name: 'Race' }), { target: { value: '1' } })
    fireEvent.change(stint(first, 1).getByLabelText('Compound'), { target: { value: 'WET' } })
    fireEvent.click(screen.getByRole('button', { name: 'Simulate' }))

    await screen.findByRole('region', { name: 'Results' })
    expect(await sentBody(requests)).toMatchObject({
      session_key: 9472,
      strategies: [[{ compound: 'SOFT' }]],
    })
  })

  it('offers the average car and the calibrated drivers by name', async () => {
    renderScreen()

    const driver = await screen.findByRole('combobox', { name: 'Driver' })

    expect(
      within(driver)
        .getAllByRole('option')
        .map((option) => option.textContent),
    ).toEqual(['The average car of the race', '1 Max VERSTAPPEN', '16 Charles LECLERC'])
  })

  it('reads another race when it is chosen, and names a driver the session does not', async () => {
    const { requests } = renderScreen()
    await screen.findByRole('complementary', { name: "The race's model" })

    fireEvent.change(screen.getByRole('combobox', { name: 'Race' }), {
      target: { value: '9480' },
    })

    const model = within(await screen.findByRole('complementary', { name: "The race's model" }))
    expect(model.getByRole('heading')).toHaveTextContent('Saudi Arabian Grand Prix')
    expect(model.getByText('21.100 s over 3 stops, not reliable')).toBeInTheDocument()
    expect(model.getByText('not recorded')).toBeInTheDocument()
    expect(await screen.findByRole('option', { name: '99 Car 99' })).toBeInTheDocument()
    expect(paths(requests)).toContain('GET /api/races/9480')
    expect((await strategy(1)).getByText('50 / 50 laps')).toBeInTheDocument()
  })

  it('simulates the strategies it was given, for the average car', async () => {
    const { requests } = renderScreen()
    const first = await strategy(1)
    fireEvent.click(first.getByRole('button', { name: 'Add a stint' }))
    fireEvent.change(stint(first, 1).getByLabelText('Laps'), { target: { value: '18' } })
    fireEvent.change(stint(first, 2).getByLabelText('Compound'), { target: { value: 'HARD' } })
    fireEvent.change(stint(first, 2).getByLabelText('Laps'), { target: { value: '39' } })
    fireEvent.change(stint(first, 2).getByLabelText('Tyre age at start'), {
      target: { value: '2' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Add a strategy' }))

    expect(first.getByText('57 / 57 laps')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Simulate' }))

    expect(await screen.findByRole('region', { name: 'Results' })).toBeInTheDocument()
    expect(await sentBody(requests)).toEqual({
      session_key: 9472,
      strategies: [
        [
          { compound: 'SOFT', laps: 18, tyre_age_at_start_laps: 0 },
          { compound: 'HARD', laps: 39, tyre_age_at_start_laps: 2 },
        ],
        [{ compound: 'SOFT', laps: 57, tyre_age_at_start_laps: 0 }],
      ],
    })
  })

  it('simulates for the chosen driver', async () => {
    const { requests } = renderScreen()

    fireEvent.change(await screen.findByRole('combobox', { name: 'Driver' }), {
      target: { value: '16' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Simulate' }))

    await screen.findByRole('region', { name: 'Results' })
    expect(await sentBody(requests)).toMatchObject({ driver_number: 16 })
  })

  it('shows each strategy simulated or rejected, and what the model leaves out', async () => {
    renderScreen()
    await strategy(1)

    fireEvent.click(screen.getByRole('button', { name: 'Simulate' }))

    const results = within(await screen.findByRole('region', { name: 'Results' }))
    const oneStop = within(results.getByRole('article', { name: 'Strategy 1' }))
    expect(oneStop.getByText('1:33:08.697')).toBeInTheDocument()
    expect(oneStop.getByText('+17.135')).toBeInTheDocument()
    expect(oneStop.getByText('Stop on lap 2, 24.343 s')).toBeInTheDocument()
    expect(oneStop.getByRole('listitem')).toHaveTextContent(
      'Some laps run a tyre older or newer than any the race calibrated',
    )
    const twoStops = results.getByRole('article', { name: 'Strategy 2' })
    expect(twoStops).toHaveAttribute('aria-current', 'true')
    expect(within(twoStops).getByText('Fastest')).toBeInTheDocument()
    expect(
      within(twoStops).getByText('Stop on lap 1, 24.343 s; Stop on lap 2, 24.343 s'),
    ).toBeInTheDocument()
    expect(
      within(results.getByRole('article', { name: 'Strategy 3' })).getByText(
        'The race did not calibrate this compound (stint 1).',
      ),
    ).toBeInTheDocument()
    expect(
      within(results.getByRole('article', { name: 'Strategy 4' })).getByText(
        "Its laps do not add up to the race's.",
      ),
    ).toBeInTheDocument()
    const left = within(results.getByRole('complementary', { name: 'Not modelled' }))
    expect(left.getAllByRole('listitem')[0]).toHaveTextContent(
      'The standing start: lap 1 is predicted as a racing lap',
    )
  })

  it('names every caveat the API gives a strategy', async () => {
    renderScreen({
      ...API,
      'POST /api/simulations': () =>
        json({
          ...SIMULATION,
          results: [
            {
              ...TWO_STOPS,
              caveats: ['pit_loss_not_reliable', 'extrapolated_tyre_age', 'one_dry_compound'],
            },
          ],
        }),
    })
    await strategy(1)

    fireEvent.click(screen.getByRole('button', { name: 'Simulate' }))

    const result = within(await screen.findByRole('article', { name: 'Strategy 1' }))
    expect(result.getAllByRole('listitem').map((item) => item.textContent)).toEqual([
      'Its pit loss was measured on fewer than 5 stops',
      'Some laps run a tyre older or newer than any the race calibrated',
      'Every stint runs the same dry compound',
    ])
  })

  it('says a strategy that stops nowhere has no stop', async () => {
    renderScreen({
      ...API,
      'POST /api/simulations': () =>
        json({ ...SIMULATION, results: [{ ...TWO_STOPS, stops: [], caveats: [] }] }),
    })
    await strategy(1)

    fireEvent.click(screen.getByRole('button', { name: 'Simulate' }))

    const result = within(await screen.findByRole('article', { name: 'Strategy 1' }))
    expect(result.getByText('No stop')).toBeInTheDocument()
    expect(result.queryByRole('list')).not.toBeInTheDocument()
  })

  it('shows the simulation as pending until the API answers', async () => {
    renderScreen({ ...API, 'POST /api/simulations': () => new Promise(() => {}) })
    await strategy(1)

    fireEvent.click(screen.getByRole('button', { name: 'Simulate' }))

    expect(screen.getByRole('button', { name: 'Simulating...' })).toBeDisabled()
  })

  it('keeps the strategies within the schema bounds', async () => {
    renderScreen()
    const first = await strategy(1)
    const addStrategy = screen.getByRole('button', { name: 'Add a strategy' })

    for (const _ of [1, 2, 3]) {
      fireEvent.click(addStrategy)
    }
    for (const _ of [1, 2, 3, 4, 5]) {
      fireEvent.click(first.getByRole('button', { name: 'Add a stint' }))
    }

    expect(addStrategy).toBeDisabled()
    expect(first.getByRole('button', { name: 'Add a stint' })).toBeDisabled()
    expect(first.getAllByRole('group')).toHaveLength(6)
    expect(screen.getByRole('button', { name: 'Simulate' })).toBeDisabled()
    expect(screen.getByText(/Every stint needs its laps/)).toBeInTheDocument()
  })

  it('removes a strategy and a stint the viewer added', async () => {
    renderScreen()
    const first = await strategy(1)
    fireEvent.click(first.getByRole('button', { name: 'Add a stint' }))
    fireEvent.click(screen.getByRole('button', { name: 'Add a strategy' }))

    fireEvent.click(first.getByRole('button', { name: 'Remove stint 2' }))
    fireEvent.click(screen.getByRole('button', { name: 'Remove strategy 2' }))

    expect(screen.queryByRole('group', { name: 'Strategy 2' })).not.toBeInTheDocument()
    expect(first.queryByRole('group', { name: 'Stint 2' })).not.toBeInTheDocument()
    expect(first.queryByRole('button', { name: /Remove/ })).not.toBeInTheDocument()
  })

  it('says why the simulation failed, with the request id', async () => {
    renderScreen({
      ...API,
      'POST /api/simulations': () =>
        new Response(JSON.stringify({ detail: 'race 9472 has no calibration' }), {
          status: 404,
          headers: { 'Content-Type': 'application/json', 'X-Request-ID': 'req-7' },
        }),
    })
    await strategy(1)

    fireEvent.click(screen.getByRole('button', { name: 'Simulate' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'The simulation failed: race 9472 has no calibration (request req-7)',
    )
    expect(screen.getByRole('button', { name: 'Simulate' })).toBeEnabled()
  })

  it('says the API is unreachable when the simulation does not reach it', async () => {
    renderScreen({ ...API, 'POST /api/simulations': () => Promise.reject(new TypeError('down')) })
    await strategy(1)

    fireEvent.click(screen.getByRole('button', { name: 'Simulate' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'The simulation failed: the API is unreachable',
    )
  })

  it('drops a simulation still running when the screen goes away', async () => {
    const { requests, unmount } = renderScreen({ ...API, 'POST /api/simulations': abortable })
    await strategy(1)
    fireEvent.click(screen.getByRole('button', { name: 'Simulate' }))

    unmount()

    await vi.waitFor(() =>
      expect(requests.find((request) => request.method === 'POST')?.signal.aborted).toBe(true),
    )
  })

  it.each([
    [
      'the list',
      { 'GET /api/races': () => json({ detail: 'down' }, 500) },
      'Could not list the races: down',
    ],
    [
      'the list, unreachable',
      { 'GET /api/races': () => Promise.reject(new TypeError('down')) },
      'Could not list the races: the API is unreachable',
    ],
    [
      'the model',
      { 'GET /api/races/9472': () => json({ detail: 'no calibration' }, 404) },
      'Could not read the race: no calibration',
    ],
    [
      'the drivers',
      { 'GET /api/sessions/9472': () => json({ detail: 'not loaded' }, 404) },
      'Could not read the race: not loaded',
    ],
    [
      'the race, unreachable',
      { 'GET /api/races/9472': () => Promise.reject(new TypeError('down')) },
      'Could not read the race: the API is unreachable',
    ],
    [
      'a race without compounds',
      { 'GET /api/races/9472': () => json({ ...RACE_MODEL, compounds: [] }) },
      'Could not read the race: the race has no calibrated compound',
    ],
  ] as const)('says when %s cannot be read', async (_, routes, message) => {
    renderScreen({ ...API, ...routes })

    expect(await screen.findByRole('alert')).toHaveTextContent(message)
  })

  it('says how to calibrate when no race is calibrated', async () => {
    renderScreen({ ...API, 'GET /api/races': () => json([]) })

    expect(
      await screen.findByText('No race is calibrated yet. Run make calibrate first.'),
    ).toBeInTheDocument()
  })

  it('stops reading the races when the screen goes away', async () => {
    const { requests, unmount } = renderScreen({ ...API, 'GET /api/races': abortable })

    unmount()

    await vi.waitFor(() => expect(requests[0]?.signal.aborted).toBe(true))
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('stops reading a race still loading when the screen goes away', async () => {
    const { requests, unmount } = renderScreen({ ...API, 'GET /api/races/9472': abortable })
    await vi.waitFor(() => expect(paths(requests)).toContain('GET /api/races/9472'))

    unmount()

    const model = requests.find(({ url }) => new URL(url).pathname === '/api/races/9472')
    await vi.waitFor(() => expect(model?.signal.aborted).toBe(true))
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('stops reading the race it leaves when another is chosen', async () => {
    const { requests } = renderScreen({ ...API, 'GET /api/races/9472': abortable })
    await vi.waitFor(() => expect(paths(requests)).toContain('GET /api/races/9472'))

    fireEvent.change(await screen.findByRole('combobox', { name: 'Race' }), {
      target: { value: '9480' },
    })

    const model = within(await screen.findByRole('complementary', { name: "The race's model" }))
    expect(model.getByRole('heading')).toHaveTextContent('Saudi Arabian Grand Prix')
    const left = requests.find(({ url }) => new URL(url).pathname === '/api/races/9472')
    expect(left?.signal.aborted).toBe(true)
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('marks the results as outdated once the strategies change, until they are simulated again', async () => {
    renderScreen()
    const first = await strategy(1)
    fireEvent.click(screen.getByRole('button', { name: 'Simulate' }))
    await screen.findByRole('region', { name: 'Results' })
    expect(screen.queryByRole('status')).not.toBeInTheDocument()

    fireEvent.change(stint(first, 1).getByLabelText('Tyre age at start'), {
      target: { value: '3' },
    })

    expect(screen.getByRole('status')).toHaveTextContent('Simulate again to update them')
    expect(screen.getByRole('region', { name: 'Results' })).toHaveClass('results--outdated')

    fireEvent.click(screen.getByRole('button', { name: 'Simulate' }))

    expect(await screen.findByRole('region', { name: 'Results' })).not.toHaveClass(
      'results--outdated',
    )
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })

  it('marks the results as outdated once the driver changes', async () => {
    renderScreen()
    await strategy(1)
    fireEvent.click(screen.getByRole('button', { name: 'Simulate' }))
    await screen.findByRole('region', { name: 'Results' })

    fireEvent.change(screen.getByRole('combobox', { name: 'Driver' }), { target: { value: '16' } })

    expect(screen.getByRole('status')).toHaveTextContent('The strategies or the driver changed')
  })

  it('marks an answer as outdated when the strategies changed while it was on its way', async () => {
    const answers: ((response: Response) => void)[] = []
    renderScreen({
      ...API,
      'POST /api/simulations': () => new Promise<Response>((resolve) => answers.push(resolve)),
    })
    const first = await strategy(1)
    fireEvent.click(screen.getByRole('button', { name: 'Simulate' }))

    fireEvent.change(stint(first, 1).getByLabelText('Laps'), { target: { value: '50' } })
    answers[0]?.(json(SIMULATION))

    expect(await screen.findByRole('region', { name: 'Results' })).toHaveClass('results--outdated')
    expect(screen.getByRole('status')).toBeInTheDocument()
  })
})
