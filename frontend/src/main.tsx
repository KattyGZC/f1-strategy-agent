import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import '@fontsource/jetbrains-mono/500.css'
import '@fontsource/jetbrains-mono/700.css'
import '@fontsource/titillium-web/400.css'
import '@fontsource/titillium-web/600.css'
import '@fontsource/titillium-web/700.css'
import '@fontsource/titillium-web/900.css'

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
