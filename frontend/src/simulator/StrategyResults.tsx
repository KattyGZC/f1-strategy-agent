import type { components } from '../api/schema.ts'
import { formatRaceTime, formatSeconds } from '../format.ts'
import { CAVEAT_LABEL, NOT_MODELLED_LABEL, REJECTION_LABEL } from './labels.ts'
import { LapChart, type Series } from './LapChart.tsx'

type Schemas = components['schemas']
type Simulated = Schemas['SimulatedResponse']
type Rejected = Schemas['RejectedResponse']

interface Props {
  simulation: Schemas['SimulationResponse']
  /** The form no longer asks for what these results answer. */
  outdated: boolean
}

/** Each strategy as the API answered it, in the order it was sent. */
export function StrategyResults({ simulation, outdated }: Readonly<Props>) {
  const series: Series[] = simulation.results.flatMap((result, index) =>
    result.outcome === 'simulated' ? [{ number: index + 1, result }] : [],
  )
  return (
    <section className={outdated ? 'results results--outdated' : 'results'} aria-label="Results">
      {series.length === 0 ? null : <LapChart series={series} />}
      <div className="result-cards">
        {simulation.results.map((result, index) =>
          result.outcome === 'simulated' ? (
            <SimulatedCard key={index} number={index + 1} result={result} />
          ) : (
            <RejectedCard key={index} number={index + 1} result={result} />
          ),
        )}
      </div>
      <aside className="not-modelled" aria-label="Not modelled">
        <span className="label">What this simulation leaves out</span>
        <ul>
          {simulation.not_modelled.map((member) => (
            <li key={member}>{NOT_MODELLED_LABEL[member]}</li>
          ))}
        </ul>
        <p className="muted small">
          They count the same for every strategy of the race: compare the strategies, not their
          totals with the race&apos;s result.
        </p>
      </aside>
    </section>
  )
}

function SimulatedCard({ number, result }: Readonly<{ number: number; result: Simulated }>) {
  const fastest = result.gap_to_fastest_s === 0
  return (
    <article
      className={`panel result series--${number}${fastest ? ' result--fastest' : ''}`}
      aria-label={`Strategy ${number}`}
    >
      <div className="panel-head">
        <h3>Strategy {number}</h3>
        <span className="label">
          {fastest ? 'Fastest' : `+${formatSeconds(result.gap_to_fastest_s)}`}
        </span>
      </div>
      <p className="big mono">{formatRaceTime(result.total_s)}</p>
      <p className="muted small">
        {result.stops.length === 0
          ? 'No stop'
          : result.stops
              .map((stop) => `Stop on lap ${stop.in_lap}, ${formatSeconds(stop.pit_loss_s)} s`)
              .join('; ')}
      </p>
      {result.caveats.length === 0 ? null : (
        <ul className="caveats">
          {result.caveats.map((caveat) => (
            <li key={caveat}>{CAVEAT_LABEL[caveat]}</li>
          ))}
        </ul>
      )}
    </article>
  )
}

function RejectedCard({ number, result }: Readonly<{ number: number; result: Rejected }>) {
  return (
    <article
      className={`panel result result--rejected series--${number}`}
      aria-label={`Strategy ${number}`}
    >
      <div className="panel-head">
        <h3>Strategy {number}</h3>
        <span className="label">Not simulated</span>
      </div>
      <p>
        {REJECTION_LABEL[result.reason]}
        {result.stint_number === null ? '.' : ` (stint ${result.stint_number}).`}
      </p>
    </article>
  )
}
