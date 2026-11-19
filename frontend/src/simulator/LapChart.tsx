import type { components } from '../api/schema.ts'
import { formatLapTime } from '../format.ts'
import { axisOf, position, type Axis } from './chartScale.ts'

type Simulated = components['schemas']['SimulatedResponse']
type Lap = components['schemas']['LapResponse']

/** A simulated strategy and its number among the strategies sent, which names its colour. */
export interface Series {
  readonly number: number
  readonly result: Simulated
}

const WIDTH = 960
const HEIGHT = 320
const LEFT = 64
const RIGHT = WIDTH - 16
const TOP = 16
const BOTTOM = HEIGHT - 36
const LAP_TICKS = 8
const TIME_TICKS = 6

/** Each simulated strategy's lap times, lap by lap; laps outside the calibrated tyre ages are
 * dashed, and each stop is marked on its in-lap. */
export function LapChart({ series }: Readonly<{ series: readonly Series[] }>) {
  const laps = series.map(({ number, result }) => {
    const lapList = result.stints.flatMap((stint) => stint.laps)
    return {
      number,
      laps: lapList,
      inLaps: new Set(result.stops.map((stop) => stop.in_lap)),
      times: new Map(lapList.map((lap) => [lap.lap_number, lap.lap_time_s])),
    }
  })
  const all = laps.flatMap((line) => line.laps)
  const lapAxis = axisOf(
    all.map((lap) => lap.lap_number),
    LAP_TICKS,
  )
  const timeAxis = axisOf(
    all.map((lap) => lap.lap_time_s),
    TIME_TICKS,
  )
  const x = (lapNumber: number) => position(lapAxis, lapNumber, LEFT, RIGHT)
  const y = (lapTimeS: number) => position(timeAxis, lapTimeS, BOTTOM, TOP)

  return (
    <figure className="panel lap-chart">
      <figcaption className="panel-head">
        <span className="label">Lap time, lap by lap</span>
        <span className="muted small">Dashed: a tyre older or newer than any calibrated</span>
      </figcaption>
      <svg
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        role="img"
        aria-label={`The lap times of ${series.length} simulated strategies`}
      >
        <Axes lapAxis={lapAxis} timeAxis={timeAxis} x={x} y={y} />
        {laps.map((line) => (
          <g key={line.number} className={`series--${line.number}`} data-series={line.number}>
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
              .filter((lap) => line.inLaps.has(lap.lap_number))
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
        ))}
      </svg>
      <LapTable laps={laps} />
    </figure>
  )
}

interface AxesProps {
  lapAxis: Axis
  timeAxis: Axis
  x(lapNumber: number): number
  y(lapTimeS: number): number
}

function Axes({ lapAxis, timeAxis, x, y }: Readonly<AxesProps>) {
  return (
    <g className="axes" aria-hidden="true">
      {timeAxis.ticks.map((tick) => (
        <g key={tick}>
          <line className="grid" x1={LEFT} x2={RIGHT} y1={y(tick)} y2={y(tick)} />
          <text x={LEFT - 8} y={y(tick)} textAnchor="end" dominantBaseline="middle">
            {formatLapTime(tick)}
          </text>
        </g>
      ))}
      {lapAxis.ticks.map((tick) => (
        <text key={tick} x={x(tick)} y={BOTTOM + 20} textAnchor="middle">
          {tick}
        </text>
      ))}
      <text x={RIGHT} y={HEIGHT - 2} textAnchor="end">
        Lap
      </text>
    </g>
  )
}

interface TableProps {
  laps: readonly { number: number; laps: readonly Lap[]; times: ReadonlyMap<number, number> }[]
}

/** The chart's values for a screen reader. */
function LapTable({ laps }: Readonly<TableProps>) {
  const lapNumbers = [...new Set(laps.flatMap((line) => [...line.times.keys()]))].toSorted(
    (a, b) => a - b,
  )
  return (
    <div className="visually-hidden">
      <table>
        <caption>Lap times of the simulated strategies</caption>
        <thead>
          <tr>
            <th scope="col">Lap</th>
            {laps.map((line) => (
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
              {laps.map((line) => (
                <td key={line.number}>{formatLapTime(line.times.get(lapNumber) ?? null)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
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
