import { useSyncExternalStore } from 'react'

/** The screens of the app, in the order of their tabs; the first opens by default (ADR 0018). */
export const SCREENS = ['replay', 'simulator'] as const
export type Screen = (typeof SCREENS)[number]

export const SCREEN_LABEL: Readonly<Record<Screen, string>> = {
  replay: 'Replay',
  simulator: 'Simulator',
}

const [DEFAULT_SCREEN] = SCREENS

export const tabId = (screen: Screen) => `tab-${screen}`
export const panelId = (screen: Screen) => `screen-${screen}`

export function hashOf(screen: Screen): string {
  return `#/${screen}`
}

/** The screen a hash names; any other hash opens the default one. */
export function screenOf(hash: string): Screen {
  return SCREENS.find((screen) => hashOf(screen) === hash) ?? DEFAULT_SCREEN
}

/** The screen `steps` tabs away, wrapping around at either end. */
export function screenAfter(screen: Screen, steps: number): Screen {
  const count = SCREENS.length
  const index = (((SCREENS.indexOf(screen) + steps) % count) + count) % count
  return SCREENS[index] ?? DEFAULT_SCREEN
}

function subscribe(onChange: () => void): () => void {
  window.addEventListener('hashchange', onChange)
  return () => window.removeEventListener('hashchange', onChange)
}

/** The screen in the URL, and a way to open another one that the back button can undo. */
export function useScreen(): [Screen, (screen: Screen) => void] {
  const screen = useSyncExternalStore(subscribe, () => screenOf(window.location.hash))
  return [
    screen,
    (next) => {
      window.location.hash = hashOf(next)
    },
  ]
}
