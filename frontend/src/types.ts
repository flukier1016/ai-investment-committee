// 与后端 schemas 对齐的前端类型（前端只渲染，不重算）

export interface AssetInfo {
  id: string
  name: string
  short_name: string
  code: string
  bucket: string
  prior: number
  target: number
}

export interface DisplayBucket {
  id: string
  label: string
  asset_class: string
  color: string
  note: string
}

export type BucketStance = '显著超配' | '超配' | '中性' | '低配' | '显著低配'

export interface AssetClass {
  id: string
  label: string
  color: string
  bucket_ids: string[]
}

export interface DataInput {
  data_id: string
  source: string
  asof: string
  hash: string
}

export interface TracedSignal {
  signal_id: string
  method: 'risk_parity' | 'tsmom' | 'clock' | 'erp'
  method_name: string
  layer: 'strategic' | 'tactical'
  view_type: string
  asof: string
  values: Record<string, number | string>
  strength: Record<string, number>
  confidence: number
  horizon_days: number
  rationale: string
  abstain: string[]
  agent_id: string
  agent_version: string
  code_version: string
  params: Record<string, unknown>
  inputs: DataInput[]
  derivation: string
  source_refs: string[]
}

export interface BLView {
  view_id: string
  label: string
  source_signal_ids: string[]
  P: Record<string, number>
  P_derivation: string
  Q: number
  Q_derivation: string
  confidence: number
  view_variance: number
  Omega: number
  lambda: number
  lambda_raw: number
  derivation: string
}

export interface GuardrailAction {
  rule: string
  label: string
  triggered: boolean
  detail: string
}

export interface DecisionChecks {
  portfolio_vol: number
  weight_sum_assets: number
  weight_sum_buckets: number
  weight_sum_classes: number
  attribution_closure: boolean
  views_have_sources: boolean
  omega_positive: boolean
  p_q_omega_rows: number
  macro_staleness_days: number | null
}

export interface CommitteeChallenge {
  id: string
  kind: string
  text: string
  refs: Record<string, unknown>
  response: { text: string; refs: Record<string, unknown> }
}

export type RiskPerspectiveAssessment =
  | 'capacity_remaining' | 'at_budget' | 'over_budget'
  | 'headroom' | 'binding' | 'breach'
  | 'no_turnover' | 'fully_explained' | 'partly_explained'
  | 'intra_bucket_only' | 'inconsistent'

interface RiskPerspectiveBase {
  id: string
  persona: string
  value: number
  assessment: RiskPerspectiveAssessment
  text: string
  refs: Record<string, string>
}

export interface AggressiveRiskPerspective extends RiskPerspectiveBase {
  role: 'aggressive'
  metric: 'vol_budget_utilization'
  metrics: {
    portfolio_vol: number
    target_vol: number
    utilization: number
    remaining_vol: number
    remaining_budget_share: number
  }
}

export interface ConservativeRiskPerspective extends RiskPerspectiveBase {
  role: 'conservative'
  metric: 'cap_headroom'
  metrics: {
    subject: string
    current: number
    limit: number
    headroom: number
  }
}

export interface NeutralRiskPerspective extends RiskPerspectiveBase {
  role: 'neutral'
  metric: 'turnover_proportionality'
  metrics: {
    asset_turnover_proxy: number
    bucket_shift: number
    explainable_share: number
    intra_bucket_churn: number
  }
}

export type CommitteeRiskPerspective =
  | AggressiveRiskPerspective
  | ConservativeRiskPerspective
  | NeutralRiskPerspective

export interface CommitteeReview {
  risk_perspectives: CommitteeRiskPerspective[]
  challenges: CommitteeChallenge[]
  verdict: { result: string; text: string; score: Record<string, number | boolean> }
  note: string
}

export interface DecisionTraceBundle {
  decision_id: string
  asof: string
  scenario_id: string
  mode: string
  conclusion: string
  display_buckets: DisplayBucket[]
  asset_classes: AssetClass[]
  assets: AssetInfo[]
  input_signals: string[]
  signals_by_id: Record<string, TracedSignal>
  prior: {
    w_strategic: Record<string, number>
    pi: Record<string, number>
    delta: number
    tau: number
    bucket_weights: Record<string, number>
    class_weights: Record<string, number>
    pi_buckets: Record<string, number>
  }
  bl_inputs: { asset_order: string[]; views: BLView[] }
  posterior_ER: Record<string, number>
  target_weights: Record<string, number>
  bucket_weights: Record<string, number>
  bucket_stances: Record<string, BucketStance>
  class_weights: Record<string, number>
  attribution: Record<string, Record<string, number>>
  guardrail_actions: GuardrailAction[]
  degraded_inputs: Array<{ input: string; reason: string; action: string }>
  committee_review: CommitteeReview
  checks: DecisionChecks
  config: Record<string, unknown>
  input_fingerprint: string
  engine_runtime_ms: number
  code_version: string
  created_at: string
}

export interface Scenario {
  id: string
  label: string
  asof: string
  description: string
  tags: string[]
}

export interface AllocationConfig {
  principal: number
  currency: string
  target_vol: number
  max_drawdown_tolerance: number
  single_asset_cap: number
  cn_equity_cap: number
  equity_class_cap: number
  bond_floor: number
  cash_floor: number
  rebalance: string
  no_trade_band: number
  cost_bps_per_side: number
  risk_aversion: number
  tau: number
  max_view_tilt: number
  cov_window_days: number
  shrinkage: number
  risk_caps_wan: Record<string, number>
}
