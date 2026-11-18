import { describe, expect, it } from 'vitest'

import { MAX_STINTS, MAX_STRATEGIES } from './bounds.ts'
import {
  benchReducer,
  lapsTyped,
  newBench,
  simulationRequest,
  type Bench,
  type BenchAction,
} from './strategies.ts'

const SESSION_KEY = 9472

function apply(bench: Bench, ...actions: BenchAction[]): Bench {
  return actions.reduce(benchReducer, bench)
}

function firstStrategy(bench: Bench) {
  return bench.strategies[0]
}

describe('the strategy bench', () => {
  it('starts with one strategy that runs the whole race on one compound', () => {
    const bench = newBench('SOFT', 57)

    expect(simulationRequest(bench, SESSION_KEY, null)).toEqual({
      session_key: SESSION_KEY,
      strategies: [[{ compound: 'SOFT', laps: 57, tyre_age_at_start_laps: 0 }]],
    })
  })

  it('sends the driver only when one is chosen', () => {
    expect(simulationRequest(newBench('SOFT', 57), SESSION_KEY, 16)).toEqual({
      session_key: SESSION_KEY,
      driver_number: 16,
      strategies: [[{ compound: 'SOFT', laps: 57, tyre_age_at_start_laps: 0 }]],
    })
  })

  it('adds strategies up to the schema bound, each its own', () => {
    const full = apply(
      newBench('HARD', 50),
      ...Array.from({ length: MAX_STRATEGIES + 1 }, () => ({ type: 'add_strategy' }) as const),
    )

    expect(full.strategies).toHaveLength(MAX_STRATEGIES)
    expect(new Set(full.strategies.map(({ id }) => id)).size).toBe(MAX_STRATEGIES)
    expect(simulationRequest(full, SESSION_KEY, null)?.strategies[3]).toEqual([
      { compound: 'HARD', laps: 50, tyre_age_at_start_laps: 0 },
    ])
  })

  it('removes a strategy but never the last one', () => {
    const two = apply(newBench('SOFT', 57), { type: 'add_strategy' })
    const [first, second] = two.strategies

    const one = apply(two, { type: 'remove_strategy', strategyId: first.id })

    expect(one.strategies).toEqual([second])
    expect(apply(one, { type: 'remove_strategy', strategyId: second?.id ?? -1 })).toEqual(one)
  })

  it('adds stints up to the schema bound, empty until the viewer types their laps', () => {
    const bench = newBench('SOFT', 57)
    const strategyId = firstStrategy(bench).id

    const full = apply(
      bench,
      ...Array.from({ length: MAX_STINTS }, () => ({ type: 'add_stint', strategyId }) as const),
    )

    expect(firstStrategy(full).stints).toHaveLength(MAX_STINTS)
    expect(firstStrategy(full).stints[1]).toMatchObject({
      compound: 'SOFT',
      laps: '',
      tyreAge: '0',
    })
    expect(simulationRequest(full, SESSION_KEY, null)).toBeNull()
  })

  it('edits and removes one stint, but never the last one', () => {
    const bench = newBench('SOFT', 57)
    const strategyId = firstStrategy(bench).id
    const withStint = apply(bench, { type: 'add_stint', strategyId })
    const [first, second] = firstStrategy(withStint).stints
    const stintId = second?.id ?? -1

    const edited = apply(
      withStint,
      { type: 'edit_stint', strategyId, stintId: first.id, field: { laps: '20' } },
      { type: 'edit_stint', strategyId, stintId, field: { compound: 'HARD', laps: '37' } },
      { type: 'edit_stint', strategyId, stintId, field: { tyreAge: '3' } },
    )

    expect(simulationRequest(edited, SESSION_KEY, null)?.strategies).toEqual([
      [
        { compound: 'SOFT', laps: 20, tyre_age_at_start_laps: 0 },
        { compound: 'HARD', laps: 37, tyre_age_at_start_laps: 3 },
      ],
    ])
    const removed = apply(edited, { type: 'remove_stint', strategyId, stintId: first.id })
    expect(firstStrategy(removed).stints.map(({ id }) => id)).toEqual([stintId])
    expect(apply(removed, { type: 'remove_stint', strategyId, stintId })).toEqual(removed)
  })

  it('leaves the other strategies alone', () => {
    const two = apply(newBench('SOFT', 57), { type: 'add_strategy' })
    const [first, second] = two.strategies

    const edited = apply(two, {
      type: 'edit_stint',
      strategyId: first.id,
      stintId: first.stints[0].id,
      field: { laps: '1' },
    })

    expect(edited.strategies[1]).toBe(second)
  })

  it.each([
    ['', '0'],
    ['0', '0'],
    ['2.5', '0'],
    ['-1', '0'],
    ['57', ''],
    ['57', '100'],
    ['57', '1e1'],
  ])('builds no request while a stint has laps %j and tyre age %j', (laps, tyreAge) => {
    const bench = newBench('SOFT', 57)
    const strategyId = firstStrategy(bench).id
    const stintId = firstStrategy(bench).stints[0].id

    const edited = apply(bench, {
      type: 'edit_stint',
      strategyId,
      stintId,
      field: { laps, tyreAge },
    })

    expect(simulationRequest(edited, SESSION_KEY, null)).toBeNull()
  })

  it('counts the laps typed so far, ignoring the ones not yet valid', () => {
    const bench = newBench('SOFT', 57)
    const strategyId = firstStrategy(bench).id
    const withStints = apply(
      bench,
      { type: 'add_stint', strategyId },
      { type: 'add_stint', strategyId },
    )
    const [first, second, third] = firstStrategy(withStints).stints

    const typed = apply(
      withStints,
      { type: 'edit_stint', strategyId, stintId: first.id, field: { laps: '20' } },
      { type: 'edit_stint', strategyId, stintId: second?.id ?? -1, field: { laps: '30' } },
      { type: 'edit_stint', strategyId, stintId: third?.id ?? -1, field: { laps: 'x' } },
    )

    expect(lapsTyped(firstStrategy(typed))).toBe(50)
  })
})
