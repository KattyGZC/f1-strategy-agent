import type { components } from '../api/schema.ts'
import type { Flag } from './fold.ts'
import { formatClock, formatDate, formatOptional } from './format.ts'
import { FLAG_LOOK } from './look.ts'
import type { StreamLink } from './stream.ts'

interface Props {
  entry: components['schemas']['SessionEntryResponse']
  leaderLap: number | null
  trackFlag: Flag | null
  sessionTime: string | null
  link: StreamLink
}

export function RaceHeader({ entry, leaderLap, trackFlag, sessionTime, link }: Readonly<Props>) {
  const flag = trackFlag === null ? null : FLAG_LOOK[trackFlag]
  return (
    <header className="race-header">
      <div>
        <h2>{entry.meeting_name}</h2>
        <span className="label">
          {entry.session_name}, {entry.circuit_short_name}, {formatDate(entry.date_start)}
        </span>
      </div>
      <div className="panel tile">
        <span className="label">Leader lap</span>
        <span className="mono big">{formatOptional(leaderLap)}</span>
      </div>
      <div className={`panel tile tile--${flag === null ? 'none' : flag.tone}`}>
        <span className="label">Track flag</span>
        <span className="big">{flag === null ? 'None yet' : flag.label}</span>
      </div>
      <div className="clock">
        <time className="mono big" dateTime={sessionTime ?? undefined}>
          {formatClock(sessionTime)}
        </time>
        <span className="label">Session time, UTC</span>
      </div>
      <LinkStatus link={link} />
    </header>
  )
}

function LinkStatus({ link }: Readonly<{ link: StreamLink }>) {
  switch (link.kind) {
    case 'connecting':
      return <span className="link-status">Connecting...</span>
    case 'live':
      return <span className="link-status link-status--live">Live replay</span>
    case 'reconnecting':
      return <span className="link-status">Reconnecting...</span>
    case 'ended':
      return (
        <span className="link-status" role="status">
          The replay has ended
        </span>
      )
    case 'failed':
      return (
        <span className="link-status link-status--failed" role="alert">
          The replay failed: {link.message}
        </span>
      )
  }
}
