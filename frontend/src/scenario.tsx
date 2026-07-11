import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import { api, savedScenario, saveScenario } from './api'
import type { Scenario } from './types'

interface ScenarioCtx {
  scenarioId: string
  setScenarioId: (id: string) => void
  scenarios: Scenario[]
  scenario: Scenario | undefined
}

const Ctx = createContext<ScenarioCtx>({
  scenarioId: 'recovery_2026',
  setScenarioId: () => {},
  scenarios: [],
  scenario: undefined,
})

export function ScenarioProvider({ children }: { children: ReactNode }) {
  const [scenarioId, setId] = useState(savedScenario())
  const [scenarios, setScenarios] = useState<Scenario[]>([])

  useEffect(() => {
    api.meta().then((m) => setScenarios(m.scenarios.scenarios)).catch(() => {})
  }, [])

  const setScenarioId = (id: string) => {
    setId(id)
    saveScenario(id)
  }

  return (
    <Ctx.Provider value={{ scenarioId, setScenarioId, scenarios, scenario: scenarios.find((s) => s.id === scenarioId) }}>
      {children}
    </Ctx.Provider>
  )
}

export const useScenario = () => useContext(Ctx)
