import type { components } from '../api/schema.ts'

type Schemas = components['schemas']

interface Look {
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

export const FLAG_LOOK: Readonly<Record<Schemas['Flag'], Look>> = {
  GREEN: { label: 'Green', tone: 'green' },
  CLEAR: { label: 'Clear', tone: 'green' },
  YELLOW: { label: 'Yellow', tone: 'yellow' },
  'DOUBLE YELLOW': { label: 'Double yellow', tone: 'yellow' },
  RED: { label: 'Red', tone: 'red' },
  BLUE: { label: 'Blue', tone: 'blue' },
  CHEQUERED: { label: 'Chequered', tone: 'chequered' },
  'BLACK AND WHITE': { label: 'Black and white', tone: 'black-white' },
}

export const CATEGORY_LABEL: Readonly<Record<Schemas['RaceControlCategory'], string>> = {
  Flag: 'Flag',
  Other: 'Notice',
  SessionStatus: 'Session',
  Drs: 'DRS',
  SafetyCar: 'Safety car',
  CarEvent: 'Car event',
}
