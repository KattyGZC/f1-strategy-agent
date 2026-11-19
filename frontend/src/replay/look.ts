import type { components } from '../api/schema.ts'
import type { Look } from '../look.ts'

type Schemas = components['schemas']

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
