/** An axis over the values a chart shows: round bounds that hold them all, and round ticks. */
export interface Axis {
  readonly min: number
  readonly max: number
  readonly ticks: readonly number[]
}

/** The axis of `values`, with about `tickCount` ticks; one value is given room on each side. */
export function axisOf(values: readonly number[], tickCount: number): Axis {
  const low = Math.min(...values)
  const high = Math.max(...values)
  const [from, to] = low === high ? [low - 1, high + 1] : [low, high]
  const step = roundStep((to - from) / (tickCount - 1))
  // Multiples of a decimal step drift in floating point (3 * 0.1); rounding to its decimals does not.
  const round = (value: number) => Number(value.toFixed(decimalsOf(step)))
  const min = round(Math.floor(from / step) * step)
  const max = round(Math.ceil(to / step) * step)
  const ticks = Array.from({ length: Math.round((max - min) / step) + 1 }, (_, index) =>
    round(min + index * step),
  )
  return { min, max, ticks }
}

/** Where `value` of the axis falls between `start` and `end`, the pixels it is drawn over. */
export function position(axis: Axis, value: number, start: number, end: number): number {
  return start + ((value - axis.min) / (axis.max - axis.min)) * (end - start)
}

/** The smallest of 1, 2, 5 or 10 times a power of ten that is at least `rough`. */
function roundStep(rough: number): number {
  const magnitude = 10 ** Math.floor(Math.log10(rough))
  if (rough <= magnitude) {
    return magnitude
  }
  if (rough <= 2 * magnitude) {
    return 2 * magnitude
  }
  return rough <= 5 * magnitude ? 5 * magnitude : 10 * magnitude
}

function decimalsOf(step: number): number {
  return Math.max(0, -Math.floor(Math.log10(step)))
}
