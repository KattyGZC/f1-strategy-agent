import { useState, type ReactNode } from 'react'

import type { ApiClient } from './api/client.ts'
import { HealthStatus } from './HealthStatus.tsx'
import { ReplayScreen } from './replay/ReplayScreen.tsx'
import type { OpenEventStream } from './replay/stream.ts'
import { panelId, SCREENS, tabId, useScreen, type Screen } from './screens.ts'
import { ScreenTabs } from './ScreenTabs.tsx'
import { SimulatorScreen } from './simulator/SimulatorScreen.tsx'

interface Props {
  apiClient: ApiClient
  openStream: OpenEventStream
}

export default function App({ apiClient, openStream }: Readonly<Props>) {
  const [screen, openScreen] = useScreen()
  // Every panel exists, so each tab controls one; a screen mounts when first opened and stays,
  // so a replay keeps playing while the simulator is open.
  const [opened, setOpened] = useState<ReadonlySet<Screen>>(() => new Set([screen]))
  if (!opened.has(screen)) {
    setOpened(new Set([...opened, screen]))
  }

  const content: Record<Screen, ReactNode> = {
    replay: <ReplayScreen client={apiClient} openStream={openStream} />,
    simulator: <SimulatorScreen client={apiClient} />,
  }

  return (
    <div className="app">
      <header className="app-header">
        <span className="brand-mark" aria-hidden="true" />
        <div>
          <h1>F1 Strategy Agent</h1>
          <span className="label">Pit wall for past Grands Prix</span>
        </div>
        <ScreenTabs screen={screen} onSelect={openScreen} />
        <HealthStatus client={apiClient} />
      </header>
      <main>
        {SCREENS.map((each) => (
          <section
            key={each}
            role="tabpanel"
            id={panelId(each)}
            aria-labelledby={tabId(each)}
            hidden={each !== screen}
          >
            {opened.has(each) ? content[each] : null}
          </section>
        ))}
      </main>
      <footer className="app-footer">
        Fan project. Not affiliated with Formula 1 or the FIA. Data from{' '}
        <a href="https://openf1.org">OpenF1</a>.
      </footer>
    </div>
  )
}
