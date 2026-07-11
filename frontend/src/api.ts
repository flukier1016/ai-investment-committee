import type { AllocationConfig, DecisionTraceBundle, Scenario } from './types'

async function get<T>(url: string): Promise<T> {
  const res = await fetch(url)
  if (!res.ok) throw new Error(`${url} → ${res.status} ${await res.text()}`)
  return res.json() as Promise<T>
}

async function post<T>(url: string, body: unknown): Promise<T> {
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(`${url} → ${res.status} ${await res.text()}`)
  return res.json() as Promise<T>
}

const CONFIG_KEY = 'ai_committee_config_v1'
const SCENARIO_KEY = 'ai_committee_scenario_v1'

export function savedConfig(): AllocationConfig | null {
  const raw = localStorage.getItem(CONFIG_KEY)
  return raw ? (JSON.parse(raw) as AllocationConfig) : null
}

export function saveConfig(config: AllocationConfig | null): void {
  if (config === null) localStorage.removeItem(CONFIG_KEY)
  else localStorage.setItem(CONFIG_KEY, JSON.stringify(config))
}

export function savedScenario(): string {
  return localStorage.getItem(SCENARIO_KEY) ?? 'recovery_2026'
}

export function saveScenario(id: string): void {
  localStorage.setItem(SCENARIO_KEY, id)
}

export const api = {
  meta: () => get<{ universe: unknown; scenarios: { default_scenario: string; scenarios: Scenario[] }; methods: { id: string; name: string; layer: string; color: string }[]; data_span: { start: string; end: string } }>('/api/meta'),
  configDefaults: () => get<{ config: AllocationConfig; personality: Record<string, unknown>; note: string }>('/api/config/defaults'),
  runDecision: (scenario_id: string, config?: AllocationConfig | null, asof?: string) =>
    post<DecisionTraceBundle>('/api/decisions/run', { scenario_id, config: config ?? undefined, asof }),
  decisions: () => get<Array<Record<string, unknown>>>('/api/decisions'),
  decision: (id: string) => get<DecisionTraceBundle>(`/api/decisions/${id}`),
  decisionRecord: (id: string) => get<Record<string, unknown>>(`/api/decisions/${id}/record`),
  overview: (scenario: string) => get<Record<string, any>>(`/api/overview?scenario_id=${scenario}`),
  cockpit: (scenario: string) => get<Record<string, any>>(`/api/cockpit?scenario_id=${scenario}`),
  backtest: (config?: AllocationConfig | null) =>
    post<Record<string, any>>('/api/backtest/run', { scenario_id: 'recovery_2026', config: config ?? undefined }),
  daily: (scenario: string) => get<Record<string, any>>(`/api/daily?scenario_id=${scenario}`),
  weekly: (scenario: string) => get<Record<string, any>>(`/api/weekly-report?scenario_id=${scenario}`),
  outcomes: (backfill = false) =>
    get<Record<string, any>>(`/api/outcomes${backfill ? '?backfill=true' : ''}`),
  spreadDesk: (scenario: string) => get<Record<string, any>>(`/api/spread-desk?scenario_id=${scenario}`),
  compare: (base: string, other: string) =>
    get<{ base: DecisionTraceBundle; other: DecisionTraceBundle; bucket_diff: Record<string, number> }>(`/api/scenarios/compare?base=${base}&other=${other}`),
}
