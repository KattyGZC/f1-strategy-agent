import { towerRows, type DriverTiming, type SessionDriver } from './fold.ts'
import { formatGap, formatLapTime, formatOptional, formatPitLap, NOTHING } from './format.ts'

interface Props {
  drivers: readonly SessionDriver[]
  timings: ReadonlyMap<number, DriverTiming>
}

export function TimingTower({ drivers, timings }: Readonly<Props>) {
  return (
    <table className="tower">
      <caption>Timing</caption>
      <thead>
        <tr>
          <th scope="col">Pos</th>
          <th scope="col">Driver</th>
          <th scope="col">Gap</th>
          <th scope="col">Interval</th>
          <th scope="col">Last lap</th>
          <th scope="col">Lap</th>
          <th scope="col">Tyre</th>
          <th scope="col">Pit</th>
        </tr>
      </thead>
      <tbody>
        {towerRows(drivers, timings).map(({ driver, timing }) => (
          <tr key={driver.driver_number}>
            <td>{formatOptional(timing.position)}</td>
            <th scope="row" title={`${driver.full_name}, ${driver.team_name}`}>
              <span className="team" style={{ backgroundColor: `#${driver.team_colour}` }} />
              {driver.name_acronym}
            </th>
            <td>{formatGap(timing.gapToLeader)}</td>
            <td>{formatGap(timing.interval)}</td>
            <td>{formatLapTime(timing.lastLap?.durationS ?? null)}</td>
            <td>{formatOptional(timing.lastLap?.lapNumber ?? null)}</td>
            <td>{tyre(timing)}</td>
            <td>{formatPitLap(timing.lastPitLap)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function tyre({ compound, tyreAgeLaps }: DriverTiming): string {
  if (compound === null) {
    return NOTHING
  }
  return tyreAgeLaps === null ? compound : `${compound} (${tyreAgeLaps})`
}
