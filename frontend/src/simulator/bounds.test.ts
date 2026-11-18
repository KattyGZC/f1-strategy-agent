import { describe, expect, it } from 'vitest'

import openapi from '../../openapi.json'
import { MAX_STINTS, MAX_STRATEGIES, MAX_TYRE_AGE_LAPS } from './bounds.ts'

const { SimulationRequest, StintRequest } = openapi.components.schemas

describe('the simulation bounds', () => {
  it('are the ones the API validates', () => {
    expect(MAX_STRATEGIES).toBe(SimulationRequest.properties.strategies.maxItems)
    expect(MAX_STINTS).toBe(SimulationRequest.properties.strategies.items.maxItems)
    expect(MAX_TYRE_AGE_LAPS).toBe(StintRequest.properties.tyre_age_at_start_laps.maximum)
  })
})
