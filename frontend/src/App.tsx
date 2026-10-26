import type { ApiClient } from './api/client.ts'
import { HealthStatus } from './HealthStatus.tsx'

export default function App({ apiClient }: Readonly<{ apiClient: ApiClient }>) {
  return (
    <main>
      <h1>F1 Strategy Agent</h1>
      <HealthStatus client={apiClient} />
    </main>
  )
}
