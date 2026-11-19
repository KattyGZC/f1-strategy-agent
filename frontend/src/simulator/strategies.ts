import type { components } from '../api/schema.ts'
import { MAX_STINTS, MAX_STRATEGIES, MAX_TYRE_AGE_LAPS } from './bounds.ts'

type Schemas = components['schemas']
export type Compound = Schemas['Compound']
type SimulationRequest = Schemas['SimulationRequest']
type StintRequest = Schemas['StintRequest']
type NonEmpty<T> = readonly [T, ...T[]]

/** A stint as the viewer types it: the numbers stay text until the request is built. */
export interface StintDraft {
  readonly id: number
  readonly compound: Compound
  readonly laps: string
  readonly tyreAge: string
}

export interface StrategyDraft {
  readonly id: number
  readonly stints: NonEmpty<StintDraft>
}

export interface Bench {
  readonly compound: Compound
  readonly raceLaps: number
  readonly nextId: number
  readonly strategies: NonEmpty<StrategyDraft>
}

export type StintField = Partial<Pick<StintDraft, 'compound' | 'laps' | 'tyreAge'>>

export type BenchAction =
  | { type: 'add_strategy' }
  | { type: 'remove_strategy'; strategyId: number }
  | { type: 'add_stint'; strategyId: number }
  | { type: 'remove_stint'; strategyId: number; stintId: number }
  | { type: 'edit_stint'; strategyId: number; stintId: number; field: StintField }

/** One strategy of one stint on `compound` for the whole race, which the API can always run. */
export function newBench(compound: Compound, raceLaps: number): Bench {
  return {
    compound,
    raceLaps,
    nextId: 2,
    strategies: [{ id: 0, stints: [stint(1, compound, String(raceLaps))] }],
  }
}

export function benchReducer(bench: Bench, action: BenchAction): Bench {
  switch (action.type) {
    case 'add_strategy':
      return addStrategy(bench)
    case 'remove_strategy':
      return {
        ...bench,
        strategies: orKept(
          bench.strategies.filter(({ id }) => id !== action.strategyId),
          bench.strategies,
        ),
      }
    case 'add_stint':
      return addStint(bench, action.strategyId)
    case 'remove_stint':
      return editStrategy(bench, action.strategyId, (stints) =>
        orKept(
          stints.filter(({ id }) => id !== action.stintId),
          stints,
        ),
      )
    case 'edit_stint':
      return editStrategy(bench, action.strategyId, (stints) =>
        orKept(
          stints.map((draft) =>
            draft.id === action.stintId ? { ...draft, ...action.field } : draft,
          ),
          stints,
        ),
      )
  }
}

/** A new strategy runs the whole race on the bench's compound, as the first one does. */
function addStrategy(bench: Bench): Bench {
  if (bench.strategies.length >= MAX_STRATEGIES) {
    return bench
  }
  const strategy = {
    id: bench.nextId,
    stints: [stint(bench.nextId + 1, bench.compound, String(bench.raceLaps))] as const,
  }
  return { ...bench, nextId: bench.nextId + 2, strategies: [...bench.strategies, strategy] }
}

/** A new stint waits for the viewer to type its laps. */
function addStint(bench: Bench, strategyId: number): Bench {
  return {
    ...editStrategy(bench, strategyId, (stints) =>
      stints.length >= MAX_STINTS ? stints : [...stints, stint(bench.nextId, bench.compound, '')],
    ),
    nextId: bench.nextId + 1,
  }
}

/** The stint's laps, or null while they are not a whole number of at least 1. */
export function stintLaps(draft: StintDraft): number | null {
  return wholeNumber(draft.laps, 1, Number.MAX_SAFE_INTEGER)
}

/** The tyre's age at the stint's start, or null while it is not 0 to the schema's maximum. */
export function stintTyreAge(draft: StintDraft): number | null {
  return wholeNumber(draft.tyreAge, 0, MAX_TYRE_AGE_LAPS)
}

/** The laps typed so far, for the viewer to compare with the race's; the API decides. */
export function lapsTyped(strategy: StrategyDraft): number {
  return strategy.stints.reduce((total, draft) => total + (stintLaps(draft) ?? 0), 0)
}

/** The request for the bench, or null while a stint has a field the schema would refuse. */
export function simulationRequest(
  bench: Bench,
  sessionKey: number,
  driverNumber: number | null,
): SimulationRequest | null {
  const strategies: StintRequest[][] = []
  for (const strategy of bench.strategies) {
    const stints: StintRequest[] = []
    for (const draft of strategy.stints) {
      const laps = stintLaps(draft)
      const tyreAge = stintTyreAge(draft)
      if (laps === null || tyreAge === null) {
        return null
      }
      stints.push({ compound: draft.compound, laps, tyre_age_at_start_laps: tyreAge })
    }
    strategies.push(stints)
  }
  return {
    session_key: sessionKey,
    strategies,
    ...(driverNumber === null ? {} : { driver_number: driverNumber }),
  }
}

/** Whether two requests ask for the same simulation: `simulationRequest` builds both, so their
 * keys come in one order. */
export function sameRequest(a: SimulationRequest, b: SimulationRequest | null): boolean {
  return JSON.stringify(a) === JSON.stringify(b)
}

function stint(id: number, compound: Compound, laps: string): StintDraft {
  return { id, compound, laps, tyreAge: '0' }
}

function editStrategy(
  bench: Bench,
  strategyId: number,
  change: (stints: StrategyDraft['stints']) => StrategyDraft['stints'],
): Bench {
  return {
    ...bench,
    strategies: orKept(
      bench.strategies.map((strategy) =>
        strategy.id === strategyId ? { ...strategy, stints: change(strategy.stints) } : strategy,
      ),
      bench.strategies,
    ),
  }
}

/** The items, or the ones kept when none is left: a bench never runs out of strategies or a
 * strategy of stints. */
function orKept<T>(items: readonly T[], kept: NonEmpty<T>): NonEmpty<T> {
  const [first, ...rest] = items
  return first === undefined ? kept : [first, ...rest]
}

function wholeNumber(typed: string, min: number, max: number): number | null {
  if (!/^\d+$/.test(typed)) {
    return null
  }
  const value = Number(typed)
  return value >= min && value <= max ? value : null
}
