import type { ApiClient } from './api/client.ts'
import { HealthStatus } from './HealthStatus.tsx'
import { ReplayScreen } from './replay/ReplayScreen.tsx'
import type { OpenEventStream } from './replay/stream.ts'

interface Props {
  apiClient: ApiClient
  openStream: OpenEventStream
}

export default function App({ apiClient, openStream }: Readonly<Props>) {
  return (
    <div className="app">
      <header className="app-header">
        <span className="brand-mark" aria-hidden="true" />
        <div>
          <h1>F1 Strategy Agent</h1>
          <span className="label">Pit wall for past Grands Prix</span>
        </div>
        <HealthStatus client={apiClient} />
      </header>
      <main>
        <ReplayScreen client={apiClient} openStream={openStream} />
      </main>
      <footer className="app-footer">
        Fan project. Not affiliated with Formula 1 or the FIA. Data from{' '}
        <a href="https://openf1.org">OpenF1</a>.
      </footer>
    </div>
  )
}
