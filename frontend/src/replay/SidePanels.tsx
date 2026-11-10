import type { RaceControlEvent, WeatherEvent } from './fold.ts'
import { formatClock } from './format.ts'
import { CATEGORY_LABEL, FLAG_LOOK } from './look.ts'

export function CircuitCard({ circuit }: Readonly<{ circuit: string }>) {
  return (
    <section className="panel circuit" aria-label="Circuit">
      <div className="panel-head">
        <span className="label">Circuit</span>
        <span className="label muted">{circuit}</span>
      </div>
      <p className="placeholder">The circuit map comes in a later version.</p>
    </section>
  )
}

export function WeatherPanel({ weather }: Readonly<{ weather: WeatherEvent | null }>) {
  return (
    <section className="panel weather" aria-label="Weather">
      <span className="label">Weather</span>
      {weather === null ? (
        <p className="muted">No reading yet.</p>
      ) : (
        <dl>
          <div>
            <dt className="label">Track</dt>
            <dd className="mono big">{weather.track_temperature} °C</dd>
          </div>
          <div>
            <dt className="label">Air</dt>
            <dd className="mono big">{weather.air_temperature} °C</dd>
          </div>
          <div>
            <dt className="label">Humidity</dt>
            <dd className="mono">{weather.humidity} %</dd>
          </div>
          <div>
            <dt className="label">Rain</dt>
            <dd>{weather.rainfall ? 'Raining' : 'Dry'}</dd>
          </div>
          <div className="wide">
            <dt className="label">Wind</dt>
            <dd className="mono">
              {weather.wind_speed} m/s from {weather.wind_direction}°
            </dd>
          </div>
        </dl>
      )}
    </section>
  )
}

export function RaceControlFeed({ messages }: Readonly<{ messages: readonly RaceControlEvent[] }>) {
  return (
    <section className="panel race-control" aria-label="Race control">
      <div className="panel-head">
        <span className="label">Race control</span>
        <span className="label muted">Newest first</span>
      </div>
      {messages.length === 0 ? (
        <p className="muted">No messages yet.</p>
      ) : (
        <ol>
          {messages.map((message) => (
            <li key={message.seq}>
              <span
                className={`flag flag--${message.flag === null ? 'none' : FLAG_LOOK[message.flag].tone}`}
                title={message.flag === null ? undefined : FLAG_LOOK[message.flag].label}
              />
              <div>
                <time className="mono muted" dateTime={message.at}>
                  {formatClock(message.at)}
                </time>{' '}
                <span className="label">{CATEGORY_LABEL[message.category]}</span>
                <p>{message.message}</p>
              </div>
            </li>
          ))}
        </ol>
      )}
    </section>
  )
}

export function StrategyPanel() {
  return (
    <section className="strategy" aria-label="Strategy, coming soon">
      <div className="panel-head">
        <div className="segmented">
          <button type="button" className="chip" disabled>
            What if...
          </button>
          <button type="button" className="chip" disabled>
            Ask the strategist
          </button>
        </div>
        <span className="label">Coming soon</span>
      </div>
      <p className="muted">
        Change the weather, the track temperature, the tyres or the pit plan and see the predicted
        lap times next to what really happened, or ask a question about this race.
      </p>
      <label className="ask">
        <span className="label">Ask about this race</span>
        <input type="text" disabled placeholder="Not available yet" />
      </label>
    </section>
  )
}
