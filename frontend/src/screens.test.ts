import { describe, expect, it } from 'vitest'

import { hashOf, screenAfter, screenOf } from './screens.ts'

describe('the screens', () => {
  it.each([
    ['#/replay', 'replay'],
    ['#/simulator', 'simulator'],
    ['', 'replay'],
    ['#/assistant', 'replay'],
    ['#simulator', 'replay'],
  ] as const)('open %j as the %s', (hash, screen) => {
    expect(screenOf(hash)).toBe(screen)
  })

  it('name themselves in the hash they are read from', () => {
    expect(screenOf(hashOf('simulator'))).toBe('simulator')
  })

  it.each([
    ['replay', 1, 'simulator'],
    ['simulator', 1, 'replay'],
    ['replay', -1, 'simulator'],
    ['simulator', -3, 'replay'],
  ] as const)('go from the %s %i tabs to the %s', (from, steps, to) => {
    expect(screenAfter(from, steps)).toBe(to)
  })
})
