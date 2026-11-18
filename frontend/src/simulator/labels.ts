import type { components } from '../api/schema.ts'

type Schemas = components['schemas']

export const CAVEAT_LABEL: Readonly<Record<Schemas['Caveat'], string>> = {
  pit_loss_not_reliable: 'Its pit loss was measured on fewer than 5 stops',
  extrapolated_tyre_age: 'Some laps run a tyre older or newer than any the race calibrated',
  one_dry_compound: 'Every stint runs the same dry compound',
}

export const REJECTION_LABEL: Readonly<Record<Schemas['StrategyRejection'], string>> = {
  no_stints: 'It has no stint',
  zero_laps: 'A stint has no lap',
  negative_tyre_age: 'A stint starts on a negative tyre age',
  compound_not_calibrated: 'The race did not calibrate this compound',
  laps_do_not_add_up: "Its laps do not add up to the race's",
  no_pit_loss: 'It stops, and no stop of this race could be measured',
}

export const NOT_MODELLED_LABEL: Readonly<Record<Schemas['NotModelled'], string>> = {
  standing_start: 'The standing start: lap 1 is predicted as a racing lap',
  starting_fuel: 'Starting fuel',
  wind: 'Wind',
  driver_aggressiveness: 'Driver aggressiveness',
  track_temperature: 'The effect of track temperature',
  rain_on_slicks: 'Rain on slick tyres',
}
