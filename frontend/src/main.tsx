import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import './styles/mock.css'
import './styles/app.css'
import App from './App'
import { ScenarioProvider } from './scenario'
import { PrefsProvider } from './prefs'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <PrefsProvider>
        <ScenarioProvider>
          <App />
        </ScenarioProvider>
      </PrefsProvider>
    </BrowserRouter>
  </StrictMode>,
)
