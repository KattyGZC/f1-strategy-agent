import type { WeatherEvent } from './fold.ts'

export function WeatherPanel({ weather }: Readonly<{ weather: WeatherEvent | null }>) {
  return (
    <section className="weather" aria-label="Weather">
      <h2>Weather</h2>
      {weather === null ? (
        <p>No reading yet.</p>
      ) : (
        <dl>
          <dt>Air</dt>
          <dd>{weather.air_temperature} °C</dd>
          <dt>Track</dt>
          <dd>{weather.track_temperature} °C</dd>
          <dt>Humidity</dt>
          <dd>{weather.humidity} %</dd>
          <dt>Wind</dt>
          <dd>
            {weather.wind_speed} m/s from {weather.wind_direction}°
          </dd>
          <dt>Rain</dt>
          <dd>{weather.rainfall ? 'Yes' : 'No'}</dd>
        </dl>
      )}
    </section>
  )
}
