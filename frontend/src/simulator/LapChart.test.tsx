import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { components } from '../api/schema.ts'
import { ONE_STOP, REJECTED, SIMULATION, TWO_STOPS } from '../testing.ts'
import { LapChart } from './LapChart.tsx'
import { StrategyResults } from './StrategyResults.tsx'

type Simulated = components['schemas']['SimulatedResponse']

function lap(lapNumber: number, lapTimeS: number, extrapolated = false) {
  return { lap_number: lapNumber, tyre_age_laps: lapNumber - 1, lap_time_s: lapTimeS, extrapolated }
}

function seriesOf(container: HTMLElement, number: number) {
  const group = container.querySelector(`[data-series="${number}"]`)
  if (group === null) {
    throw new Error(`no series ${number} on the chart`)
  }
  return group
}

describe('LapChart', () => {
  it('draws one line per strategy, joining its laps, with a mark on each in-lap', () => {
    const { container } = render(
      <LapChart
        series={[
          { number: 1, result: ONE_STOP },
          { number: 2, result: TWO_STOPS },
        ]}
      />,
    )

    expect(screen.getByRole('img')).toHaveAccessibleName('The lap times of 2 simulated strategies')
    expect(seriesOf(container, 1).querySelectorAll('line.trace')).toHaveLength(3)
    expect(seriesOf(container, 1).querySelectorAll('circle.stop')).toHaveLength(1)
    expect(seriesOf(container, 2).querySelectorAll('circle.stop')).toHaveLength(2)
    expect(seriesOf(container, 2)).toHaveClass('series--2')
  })

  it('dashes the segments that reach a lap outside the calibrated tyre ages', () => {
    const extrapolated: Simulated = {
      ...ONE_STOP,
      stints: [{ compound: 'SOFT', laps: [lap(1, 90, true), lap(2, 90.1), lap(3, 90.2)] }],
      stops: [],
    }

    const { container } = render(<LapChart series={[{ number: 1, result: extrapolated }]} />)

    const traces = Array.from(seriesOf(container, 1).querySelectorAll('line.trace'))
    expect(traces.map((trace) => trace.classList.contains('trace--dashed'))).toEqual([true, false])
  })

  it('labels the time axis as lap times and the lap axis by lap', () => {
    render(<LapChart series={[{ number: 1, result: ONE_STOP }]} />)

    const svg = screen.getByRole('img')
    expect(within(svg).getByText('1:38.000')).toBeInTheDocument()
    expect(within(svg).getByText('Lap')).toBeInTheDocument()
  })

  it('gives a screen reader every lap time, and a dash where a strategy has none', () => {
    const shorter: Simulated = {
      ...TWO_STOPS,
      stints: [{ compound: 'HARD', laps: [lap(1, 98.7), lap(2, 98.6)] }],
      stops: [],
    }

    render(
      <LapChart
        series={[
          { number: 1, result: ONE_STOP },
          { number: 3, result: shorter },
        ]}
      />,
    )

    const table = screen.getByRole('table', { name: 'Lap times of the simulated strategies' })
    const rows = within(table).getAllByRole('row')
    expect(rows.map((row) => row.textContent)).toEqual([
      'LapStrategy 1Strategy 3',
      '11:37.8001:38.700',
      '21:37.9001:38.600',
      '31:38.600-',
      '41:38.500-',
    ])
  })
})

describe('StrategyResults', () => {
  it('charts the simulated strategies under the numbers they were sent with', () => {
    const { container } = render(
      <StrategyResults
        simulation={{ ...SIMULATION, results: [REJECTED, ONE_STOP, REJECTED, TWO_STOPS] }}
        outdated={false}
      />,
    )

    const numbers = Array.from(container.querySelectorAll('[data-series]')).map((group) =>
      group.getAttribute('data-series'),
    )
    expect(numbers).toEqual(['2', '4'])
  })

  it('draws no chart when no strategy was simulated', () => {
    render(<StrategyResults simulation={{ ...SIMULATION, results: [REJECTED] }} outdated={false} />)

    expect(screen.queryByRole('img')).not.toBeInTheDocument()
  })
})
