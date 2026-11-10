import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import { createApiClient } from './api/client.ts'
import App from './App.tsx'
import './App.css'

const root = document.getElementById('root')
if (root === null) {
  throw new Error('index.html has no #root element')
}

createRoot(root).render(
  <StrictMode>
    <App
      apiClient={createApiClient(window.location.origin)}
      openStream={(path) => new EventSource(new URL(path, window.location.origin))}
    />
  </StrictMode>,
)
