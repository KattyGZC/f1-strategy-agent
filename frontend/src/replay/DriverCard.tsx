import type { ReactNode } from 'react'

import type { DriverTiming, SessionDriver } from './fold.ts'
import { formatGap, formatLapTime, formatOptional, formatPitLap, formatSeconds } from './format.ts'
import { TyreBadge } from './TyreBadge.tsx'

interface Props {
  driver: SessionDriver
  timing: DriverTiming
}

export function DriverCard({ driver, timing }: Readonly<Props>) {
  const lap = timing.lastLap
  return (
    <article className="panel driver-card" aria-label="Selected driver">
      <header>
        <span className="team team--tall" style={{ backgroundColor: `#${driver.team_colour}` }} />
        <div>
          <span className="label">
            P{formatOptional(timing.position)}, {driver.team_name}, #{driver.driver_number}
          </span>
          <h3>{driver.full_name}</h3>
        </div>
        <span className="label hint">Pick a driver in the timing to follow them</span>
      </header>
      <dl className="stats">
        <Stat name={`Last lap${lap === null ? '' : `, lap ${lap.lap_number}`}`}>
          {formatLapTime(lap?.lap_duration ?? null)}
        </Stat>
        <Stat name="Gap to leader">{formatGap(timing.gapToLeader)}</Stat>
        <Stat name="Tyre">
          <TyreBadge lap={lap} />
        </Stat>
        <Stat name="Last stop">{formatPitLap(timing.lastPitLap)}</Stat>
      </dl>
      <dl className="stats stats--small">
        <Stat name="Sector 1">{formatSeconds(lap?.duration_sector_1 ?? null)}</Stat>
        <Stat name="Sector 2">{formatSeconds(lap?.duration_sector_2 ?? null)}</Stat>
        <Stat name="Sector 3">{formatSeconds(lap?.duration_sector_3 ?? null)}</Stat>
        <Stat name="Speed I1, km/h">{formatOptional(lap?.i1_speed ?? null)}</Stat>
        <Stat name="Speed I2, km/h">{formatOptional(lap?.i2_speed ?? null)}</Stat>
        <Stat name="Speed trap, km/h">{formatOptional(lap?.st_speed ?? null)}</Stat>
      </dl>
    </article>
  )
}

function Stat({ name, children }: Readonly<{ name: string; children: ReactNode }>) {
  return (
    <div>
      <dt className="label">{name}</dt>
      <dd className="mono">{children}</dd>
    </div>
  )
}
