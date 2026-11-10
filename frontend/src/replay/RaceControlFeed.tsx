import type { RaceControlEvent } from './fold.ts'
import { formatClock } from './format.ts'

export function RaceControlFeed({ messages }: Readonly<{ messages: readonly RaceControlEvent[] }>) {
  return (
    <section className="race-control" aria-label="Race control">
      <h2>Race control</h2>
      {messages.length === 0 ? (
        <p>No messages yet.</p>
      ) : (
        <ol>
          {messages.map((message) => (
            <li key={message.seq}>
              <time dateTime={message.at}>{formatClock(message.at)}</time> {message.message}
            </li>
          ))}
        </ol>
      )}
    </section>
  )
}
