import type { components } from '../api/schema.ts'
import { formatLapTime } from '../format.ts'
import { axisOf, position } from './chartScale.ts'

type Simulated = components['schemas']['SimulatedResponse']
type Lap = components['schemas']['LapResponse']

/** A simulated strategy and its number among the strategies sent, which names its colour. */
export interface Series {
  readonly number: number
  readonly result: Simulated
}

interface Line {
  readonly number: number
  readonly laps: readonly Lap[]
  readonly inLaps: readonly number[]
  readonly times: ReadonlyMap<number, number>
}

// The plot has no viewBox: its laps sit at percentages of its width and its times at pixels of
// its height, so no screen width scales the text.
const HEIGHT_PX = 296
const TOP_PX = 12
// Room under the plot for the lap numbers, then for the axis title below them.
const BOTTOM_PX = HEIGHT_PX - 48
const LAP_NUMBERS_PX = BOTTOM_PX + 20
const LAP_TICKS = 8
const TIME_TICKS = 6
const LIST = new Intl.ListFormat('en', { type: 'conjunction' })

/** Each simulated strategy's lap times, lap by lap; laps outside the calibrated tyre ages are
 * dashed, and each stop is marked on its in-lap. */
export function LapChart({ series }: Readonly<{ series: readonly Series[] }>) {
  const lines = series.map(lineOf)
  return (
    <figure className="panel lap-chart">
      <figcaption className="panel-head">
        <span className="label">Lap time, lap by lap</span>
        <Legend lines={lines} />
      </figcaption>
      <Plot lines={lines} />
      <LapTable lines={lines} />
    </figure>
  )
}

function Legend({ lines }: Readonly<{ lines: readonly Line[] }>) {
  return (
    <ul className="legend">
      {lines.map((line) => (
        <li key={line.number} className={`series--${line.number}`}>
          <span className="swatch" aria-hidden="true" />
          Strategy {line.number}
        </li>
      ))}
      <li className="muted">
        <span className="swatch swatch--dashed" aria-hidden="true" />A tyre older or newer than any
        calibrated
      </li>
    </ul>
  )
}

function Plot({ lines }: Readonly<{ lines: readonly Line[] }>) {
  const laps = lines.flatMap((line) => line.laps)
  const lapAxis = axisOf(
    laps.map((lap) => lap.lap_number),
    LAP_TICKS,
  )
  const timeAxis = axisOf(
    laps.map((lap) => lap.lap_time_s),
    TIME_TICKS,
  )
  const x = (lapNumber: number) => `${position(lapAxis, lapNumber, 0, 100)}%`
  const y = (lapTimeS: number) => position(timeAxis, lapTimeS, BOTTOM_PX, TOP_PX)

  return (
    <div className="lap-chart-plot" role="img" aria-label={summaryOf(lines)}>
      <TimeAxis ticks={timeAxis.ticks} y={y} />
      <svg className="plot" height={HEIGHT_PX} aria-hidden="true">
        {timeAxis.ticks.map((tick) => (
          <line key={tick} className="grid" x1="0" x2="100%" y1={y(tick)} y2={y(tick)} />
        ))}
        {lapAxis.ticks.map((tick) => (
          <text key={tick} x={x(tick)} y={LAP_NUMBERS_PX} textAnchor="middle">
            {tick}
          </text>
        ))}
        <text x="100%" y={HEIGHT_PX - 2} textAnchor="end">
          Lap
        </text>
        {lines.map((line) => (
          <SeriesLine key={line.number} line={line} x={x} y={y} />
        ))}
      </svg>
    </div>
  )
}

interface TimeAxisProps {
  ticks: readonly number[]
  y(lapTimeS: number): number
}

/** Its own column of fixed width, so the plot's percentages start where the labels end. */
function TimeAxis({ ticks, y }: Readonly<TimeAxisProps>) {
  return (
    <svg className="time-axis" height={HEIGHT_PX} aria-hidden="true">
      {ticks.map((tick) => (
        <text key={tick} x="100%" dx={-8} y={y(tick)} textAnchor="end" dominantBaseline="middle">
          {formatLapTime(tick)}
        </text>
      ))}
    </svg>
  )
}

interface SeriesLineProps {
  line: Line
  x(lapNumber: number): string
  y(lapTimeS: number): number
}

function SeriesLine({ line, x, y }: Readonly<SeriesLineProps>) {
  return (
    <g className={`series--${line.number}`} data-series={line.number}>
      {segments(line.laps).map(([from, to]) => (
        <line
          key={to.lap_number}
          className={from.extrapolated || to.extrapolated ? 'trace trace--dashed' : 'trace'}
          x1={x(from.lap_number)}
          y1={y(from.lap_time_s)}
          x2={x(to.lap_number)}
          y2={y(to.lap_time_s)}
        />
      ))}
      {line.laps
        .filter((lap) => line.inLaps.includes(lap.lap_number))
        .map((lap) => (
          <circle
            key={lap.lap_number}
            className="stop"
            cx={x(lap.lap_number)}
            cy={y(lap.lap_time_s)}
            r={4}
          />
        ))}
    </g>
  )
}

/** The chart's values for a screen reader. */
function LapTable({ lines }: Readonly<{ lines: readonly Line[] }>) {
  const lapNumbers = [...new Set(lines.flatMap((line) => [...line.times.keys()]))].toSorted(
    (a, b) => a - b,
  )
  return (
    <div className="visually-hidden">
      <table>
        <caption>Lap times of the simulated strategies</caption>
        <thead>
          <tr>
            <th scope="col">Lap</th>
            {lines.map((line) => (
              <th key={line.number} scope="col">
                Strategy {line.number}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {lapNumbers.map((lapNumber) => (
            <tr key={lapNumber}>
              <th scope="row">{lapNumber}</th>
              {lines.map((line) => (
                <td key={line.number}>{formatLapTime(line.times.get(lapNumber) ?? null)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function lineOf({ number, result }: Series): Line {
  const laps = result.stints.flatMap((stint) => stint.laps)
  return {
    number,
    laps,
    inLaps: result.stops.map((stop) => stop.in_lap),
    times: new Map(laps.map((lap) => [lap.lap_number, lap.lap_time_s])),
  }
}

/** What the chart shows, in words: the laps, the range of lap times and each strategy's stops,
 * all as the API sent them. */
function summaryOf(lines: readonly Line[]): string {
  const laps = lines.flatMap((line) => line.laps)
  const lapNumbers = laps.map((lap) => lap.lap_number)
  const times = laps.map((lap) => lap.lap_time_s)
  const names = LIST.format(lines.map((line) => `strategy ${line.number}`))
  const stops = lines.map((line) => `strategy ${line.number} ${stopsOf(line.inLaps)}`).join('; ')
  return (
    `Lap times of ${names}, laps ${Math.min(...lapNumbers)} to ${Math.max(...lapNumbers)}, ` +
    `from ${formatLapTime(Math.min(...times))} to ${formatLapTime(Math.max(...times))}. ` +
    `${stops.charAt(0).toUpperCase()}${stops.slice(1)}.`
  )
}

function stopsOf(inLaps: readonly number[]): string {
  if (inLaps.length === 0) {
    return 'does not stop'
  }
  return `stops on ${inLaps.length === 1 ? 'lap' : 'laps'} ${LIST.format(inLaps.map(String))}`
}

/** Each lap with the one before it, so a line joins them. */
function segments(laps: readonly Lap[]): [Lap, Lap][] {
  const pairs: [Lap, Lap][] = []
  let previous: Lap | undefined
  for (const lap of laps) {
    if (previous !== undefined) {
      pairs.push([previous, lap])
    }
    previous = lap
  }
  return pairs
}
