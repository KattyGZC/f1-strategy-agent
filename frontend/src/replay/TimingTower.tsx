import { useState } from 'react'

import { towerRows, type DriverTiming, type SessionDriver } from './fold.ts'
import { formatGap, formatLapTime, formatOptional, formatPitLap } from './format.ts'
import { TyreBadge } from './TyreBadge.tsx'

type GapMode = 'interval' | 'leader'

interface Props {
  drivers: readonly SessionDriver[]
  timings: ReadonlyMap<number, DriverTiming>
  selected: number | null
  onSelect(driverNumber: number): void
}

export function TimingTower({ drivers, timings, selected, onSelect }: Readonly<Props>) {
  const [mode, setMode] = useState<GapMode>('interval')

  return (
    <section className="panel tower" aria-label="Timing">
      <div className="panel-head">
        <span className="label">Timing</span>
        <GapToggle mode={mode} onMode={setMode} />
      </div>
      <table>
        <thead>
          <tr>
            <th scope="col">Pos</th>
            <th scope="col">Driver</th>
            <th scope="col">{mode === 'interval' ? 'Interval' : 'Gap'}</th>
            <th scope="col">Last lap</th>
            <th scope="col">Tyre</th>
            <th scope="col">Pit</th>
          </tr>
        </thead>
        <tbody>
          {towerRows(drivers, timings).map(({ driver, timing }) => (
            <TowerRow
              key={driver.driver_number}
              driver={driver}
              timing={timing}
              mode={mode}
              selected={driver.driver_number === selected}
              onSelect={onSelect}
            />
          ))}
        </tbody>
      </table>
    </section>
  )
}

function GapToggle({ mode, onMode }: Readonly<{ mode: GapMode; onMode(mode: GapMode): void }>) {
  return (
    <fieldset className="segmented">
      <legend className="visually-hidden">Gap shown</legend>
      <button
        type="button"
        className="chip"
        aria-pressed={mode === 'interval'}
        onClick={() => onMode('interval')}
      >
        Interval
      </button>
      <button
        type="button"
        className="chip"
        aria-pressed={mode === 'leader'}
        onClick={() => onMode('leader')}
      >
        Gap to leader
      </button>
    </fieldset>
  )
}

interface RowProps {
  driver: SessionDriver
  timing: DriverTiming
  mode: GapMode
  selected: boolean
  onSelect(driverNumber: number): void
}

function TowerRow({ driver, timing, mode, selected, onSelect }: Readonly<RowProps>) {
  return (
    <tr aria-selected={selected}>
      <td className="mono muted">{formatOptional(timing.position)}</td>
      <th scope="row">
        <button
          type="button"
          className="driver"
          title={`${driver.full_name}, ${driver.team_name}`}
          onClick={() => onSelect(driver.driver_number)}
        >
          <span className="team" style={{ backgroundColor: `#${driver.team_colour}` }} />
          {driver.name_acronym}
        </button>
      </th>
      <td className="mono">
        {formatGap(mode === 'interval' ? timing.interval : timing.gapToLeader)}
      </td>
      <td className="mono">{formatLapTime(timing.lastLap?.lap_duration ?? null)}</td>
      <td>
        <TyreBadge lap={timing.lastLap} />
      </td>
      <td className="mono muted">{formatPitLap(timing.lastPitLap)}</td>
    </tr>
  )
}
