import { useState, type FormEvent } from 'react'

interface Props {
  lastLapNumber: number
  disabled: boolean
  onSeek(lapNumber: number): void
}

/** A lap number from 1 to the session's last lap, sent when the viewer asks for it. */
export function GoToLap({ lastLapNumber, disabled, onSeek }: Readonly<Props>) {
  const [typed, setTyped] = useState('')
  const lapNumber = Number(typed)
  const valid =
    typed !== '' && Number.isInteger(lapNumber) && lapNumber >= 1 && lapNumber <= lastLapNumber

  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (valid) {
      onSeek(lapNumber)
    }
  }

  return (
    <form className="go-to-lap" onSubmit={submit}>
      <label className="label" htmlFor="go-to-lap">
        Lap
      </label>
      <input
        id="go-to-lap"
        type="number"
        inputMode="numeric"
        min={1}
        max={lastLapNumber}
        step={1}
        placeholder={`1-${lastLapNumber}`}
        value={typed}
        onChange={(event) => setTyped(event.target.value)}
      />
      <button type="submit" className="chip" disabled={disabled || !valid}>
        Go to lap
      </button>
    </form>
  )
}
