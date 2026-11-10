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
    <main>
      <h1>F1 Strategy Agent</h1>
      <HealthStatus client={apiClient} />
      <ReplayScreen client={apiClient} openStream={openStream} />
    </main>
  )
}
