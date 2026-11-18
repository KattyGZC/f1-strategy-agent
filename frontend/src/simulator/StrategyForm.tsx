import type { Dispatch } from 'react'

import { COMPOUND_LOOK } from '../replay/look.ts'
import { MAX_STINTS, MAX_STRATEGIES, MAX_TYRE_AGE_LAPS } from './bounds.ts'
import {
  lapsTyped,
  type Bench,
  type BenchAction,
  type Compound,
  type StintDraft,
  type StintField,
  type StrategyDraft,
} from './strategies.ts'

interface Props {
  bench: Bench
  compounds: Compound[]
  dispatch: Dispatch<BenchAction>
}

/** Each strategy's stints in order: the first starts on lap 1, the next on the lap after. */
export function StrategyForm({ bench, compounds, dispatch }: Readonly<Props>) {
  return (
    <div className="strategy-form">
      {bench.strategies.map((strategy, index) => (
        <StrategyFields
          key={strategy.id}
          number={index + 1}
          strategy={strategy}
          raceLaps={bench.raceLaps}
          compounds={compounds}
          removable={bench.strategies.length > 1}
          dispatch={dispatch}
        />
      ))}
      <button
        type="button"
        className="chip"
        disabled={bench.strategies.length >= MAX_STRATEGIES}
        onClick={() => dispatch({ type: 'add_strategy' })}
      >
        Add a strategy
      </button>
    </div>
  )
}

interface StrategyProps {
  number: number
  strategy: StrategyDraft
  raceLaps: number
  compounds: Compound[]
  removable: boolean
  dispatch: Dispatch<BenchAction>
}

function StrategyFields({
  number,
  strategy,
  raceLaps,
  compounds,
  removable,
  dispatch,
}: Readonly<StrategyProps>) {
  const strategyId = strategy.id
  return (
    <fieldset className={`panel strategy-fields series--${number}`}>
      <legend>Strategy {number}</legend>
      <div className="panel-head">
        <span className="mono small">
          {lapsTyped(strategy)} / {raceLaps} laps
        </span>
        {removable ? (
          <button
            type="button"
            className="link"
            onClick={() => dispatch({ type: 'remove_strategy', strategyId })}
          >
            Remove strategy {number}
          </button>
        ) : null}
      </div>
      {strategy.stints.map((stint, index) => (
        <StintFields
          key={stint.id}
          number={index + 1}
          stint={stint}
          compounds={compounds}
          removable={strategy.stints.length > 1}
          onEdit={(field) => dispatch({ type: 'edit_stint', strategyId, stintId: stint.id, field })}
          onRemove={() => dispatch({ type: 'remove_stint', strategyId, stintId: stint.id })}
        />
      ))}
      <button
        type="button"
        className="chip"
        disabled={strategy.stints.length >= MAX_STINTS}
        onClick={() => dispatch({ type: 'add_stint', strategyId })}
      >
        Add a stint
      </button>
    </fieldset>
  )
}

interface StintProps {
  number: number
  stint: StintDraft
  compounds: Compound[]
  removable: boolean
  onEdit(field: StintField): void
  onRemove(): void
}

function StintFields({
  number,
  stint,
  compounds,
  removable,
  onEdit,
  onRemove,
}: Readonly<StintProps>) {
  return (
    <fieldset className="stint-fields">
      <legend className="label">Stint {number}</legend>
      <span className={`tyre tyre--${COMPOUND_LOOK[stint.compound].tone}`} aria-hidden="true" />
      <label className="field">
        <span className="label">Compound</span>
        <select
          value={stint.compound}
          onChange={(event) => {
            const compound = compounds.find((calibrated) => calibrated === event.target.value)
            if (compound !== undefined) {
              onEdit({ compound })
            }
          }}
        >
          {compounds.map((compound) => (
            <option key={compound} value={compound}>
              {COMPOUND_LOOK[compound].label}
            </option>
          ))}
        </select>
      </label>
      <label className="field">
        <span className="label">Laps</span>
        <input
          type="number"
          inputMode="numeric"
          min={1}
          step={1}
          value={stint.laps}
          onChange={(event) => onEdit({ laps: event.target.value })}
        />
      </label>
      <label className="field">
        <span className="label">Tyre age at start</span>
        <input
          type="number"
          inputMode="numeric"
          min={0}
          max={MAX_TYRE_AGE_LAPS}
          step={1}
          value={stint.tyreAge}
          onChange={(event) => onEdit({ tyreAge: event.target.value })}
        />
      </label>
      {removable ? (
        <button type="button" className="link" onClick={onRemove}>
          Remove stint {number}
        </button>
      ) : null}
    </fieldset>
  )
}
