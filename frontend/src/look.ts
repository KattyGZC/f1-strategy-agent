import type { components } from './api/schema.ts'

type Schemas = components['schemas']

export interface Look {
  readonly label: string
  /** The modifier of the CSS class that colours it, such as `tyre--soft`. */
  readonly tone: string
}

export const COMPOUND_LOOK: Readonly<Record<Schemas['Compound'], Look>> = {
  SOFT: { label: 'Soft', tone: 'soft' },
  MEDIUM: { label: 'Medium', tone: 'medium' },
  HARD: { label: 'Hard', tone: 'hard' },
  INTERMEDIATE: { label: 'Intermediate', tone: 'intermediate' },
  WET: { label: 'Wet', tone: 'wet' },
  UNKNOWN: { label: 'Unknown', tone: 'unknown' },
}
