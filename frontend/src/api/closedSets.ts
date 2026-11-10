import type { components } from './schema.ts'

type Schemas = components['schemas']
export type ReplaySpeed = Schemas['ReplaySpeed']

/** The values of a closed set the schema only types: leaving a member out fails `tsc`. */
function everyMember<T>() {
  return <const V extends readonly T[]>(
    values: V & ([Exclude<T, V[number]>] extends [never] ? unknown : never),
  ): V => values
}

export const REPLAY_SPEEDS = everyMember<Schemas['ReplaySpeed']>()([1, 2, 5, 10, 20, 60])

export const EVENT_KINDS = everyMember<Schemas['ReplayEvent']['kind']>()([
  'race_control',
  'weather',
  'pit',
  'lap',
  'position',
  'interval',
  'overtake',
  'team_radio',
])
