import { describe, expect, it } from 'vitest'

import { axisOf, position } from './chartScale.ts'

describe('a chart axis', () => {
  it('rounds its bounds out to a round step that holds every value', () => {
    expect(axisOf([97.83, 99.2, 101.46], 5)).toEqual({
      min: 97,
      max: 102,
      ticks: [97, 98, 99, 100, 101, 102],
    })
    expect(axisOf([0, 12], 5)).toEqual({ min: 0, max: 15, ticks: [0, 5, 10, 15] })
  })

  it('counts laps in round steps', () => {
    expect(axisOf([1, 57], 6)).toEqual({ min: 0, max: 60, ticks: [0, 20, 40, 60] })
  })

  it('gives a single value room on each side', () => {
    expect(axisOf([91, 91], 3)).toEqual({ min: 90, max: 92, ticks: [90, 91, 92] })
  })

  it('keeps ticks of a decimal step free of floating-point drift', () => {
    expect(axisOf([0.1, 0.3], 3)).toEqual({ min: 0.1, max: 0.3, ticks: [0.1, 0.2, 0.3] })
  })

  it('places a value between the pixels the axis is drawn over, either way round', () => {
    const axis = axisOf([0, 10], 3)

    expect(position(axis, 5, 40, 240)).toBe(140)
    expect(position(axis, 10, 300, 20)).toBe(20)
  })
})
