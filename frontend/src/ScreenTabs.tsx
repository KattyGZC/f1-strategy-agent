import { useRef, type KeyboardEvent } from 'react'

import { panelId, SCREEN_LABEL, SCREENS, screenForKey, tabId, type Screen } from './screens.ts'

interface Props {
  screen: Screen
  onSelect(screen: Screen): void
}

/** The WAI-ARIA tabs pattern: only the open tab is in the tab order; arrows, Home and End move
 * between tabs and open the one they reach. */
export function ScreenTabs({ screen, onSelect }: Readonly<Props>) {
  const tabs = useRef(new Map<Screen, HTMLButtonElement | null>())

  const open = (next: Screen) => {
    onSelect(next)
    tabs.current.get(next)?.focus()
  }

  const onKeyDown = (event: KeyboardEvent) => {
    const next = screenForKey(screen, event.key)
    if (next !== null) {
      event.preventDefault()
      open(next)
    }
  }

  return (
    <div className="screen-tabs" role="tablist" aria-label="Screens">
      {SCREENS.map((each) => (
        <button
          key={each}
          ref={(button) => {
            tabs.current.set(each, button)
            return () => {
              tabs.current.delete(each)
            }
          }}
          type="button"
          role="tab"
          id={tabId(each)}
          aria-controls={panelId(each)}
          aria-selected={each === screen}
          tabIndex={each === screen ? 0 : -1}
          onClick={() => onSelect(each)}
          onKeyDown={onKeyDown}
        >
          {SCREEN_LABEL[each]}
        </button>
      ))}
    </div>
  )
}
