// 展示层统一口径：英文全称方法名 + 固定方法色（交接 MD 第 5 节）
// 展示层禁止出现 CTA / TSMOM / ERP / BL 等简称。

export const METHOD_META: Record<string, { name: string; color: string; layer: string }> = {
  risk_parity: { name: 'Risk Parity', color: 'var(--method-risk-parity)', layer: 'strategic' },
  tsmom: { name: 'Time Series Momentum', color: 'var(--method-cta)', layer: 'tactical' },
  clock: { name: 'Merrill Lynch Investment Clock', color: 'var(--method-clock)', layer: 'tactical' },
  erp: { name: 'Equity Risk Premium', color: 'var(--method-erp)', layer: 'tactical' },
  black_litterman: { name: 'Black-Litterman Model', color: 'var(--bl)', layer: 'integration' },
}

export const BUCKET_META: Record<string, { label: string; color: string; classId: string }> = {
  cn_equity: { label: '中国股票', color: 'var(--teal)', classId: 'equity' },
  foreign_equity: { label: '外国股票', color: 'var(--cyan)', classId: 'equity' },
  cn_bond: { label: '中国债券', color: 'var(--amber)', classId: 'bond' },
  foreign_bond: { label: '外国债券', color: 'var(--slate)', classId: 'bond' },
  commodity: { label: '商品', color: 'var(--rose)', classId: 'commodity' },
  fx: { label: '外汇', color: 'var(--violet)', classId: 'fx' },
  cash: { label: '现金', color: 'var(--cash)', classId: 'cash' },
}

export const CLASS_META: Record<string, { label: string; color: string }> = {
  equity: { label: '权益', color: 'var(--teal)' },
  bond: { label: '债券', color: 'var(--amber)' },
  commodity: { label: '商品', color: 'var(--rose)' },
  fx: { label: '外汇', color: 'var(--violet)' },
  cash: { label: '现金', color: 'var(--cash)' },
}

export const BUCKET_ORDER = ['cn_equity', 'foreign_equity', 'cn_bond', 'foreign_bond', 'commodity', 'fx', 'cash']
export const CLASS_ORDER = ['equity', 'bond', 'commodity', 'fx', 'cash']

export const LAYER_ZH: Record<string, string> = { strategic: '战略底仓', tactical: '战术偏离', integration: '整合' }
export const VIEW_TYPE_ZH: Record<string, string> = {
  risk_budget: '风险预算', direction: '趋势方向', regime: '宏观象限', percentile: '估值分位', abstain: '弃权',
}

// ECharts 用的实色（与 CSS 变量同值）
export const SOLID: Record<string, string> = {
  teal: '#0b7668', cyan: '#176f9d', amber: '#8a5b06', slate: '#59666f',
  rose: '#a33f64', violet: '#6f63c8', cash: '#4f5964', green: '#247a54', red: '#b84c48',
  methodRiskParity: '#16806b', methodCta: '#247da8', methodClock: '#9f6500',
  methodErp: '#aa4168', bl: '#405d88', muted: '#66706c', line: '#dde4db',
}
export const BUCKET_SOLID: Record<string, string> = {
  cn_equity: '#0b7668', foreign_equity: '#176f9d', cn_bond: '#8a5b06',
  foreign_bond: '#59666f', commodity: '#a33f64', fx: '#6f63c8', cash: '#4f5964',
}
export const METHOD_SOLID: Record<string, string> = {
  risk_parity: '#16806b', tsmom: '#247da8', clock: '#9f6500', erp: '#aa4168', black_litterman: '#405d88',
}

// ECharts 网格线/轴标签的随主题取值：echarts 渲染到 canvas，读不到 CSS 变量，
// 这里镜像 mock.css 的 --line / --muted 双主题 token；改 token 时必须同步。
// 目的：暗色主题不再被写死的亮色网格线（旧 #dde4db）刺穿。
const CHART_THEME = {
  light: { grid: '#dde4db', axisLabel: '#66706c' },
  dark: { grid: '#29323b', axisLabel: '#93a09a' },
} as const

export function chartTheme(theme: Theme): { grid: string; axisLabel: string } {
  return CHART_THEME[theme]
}

import { tf, type Theme } from './prefs'

export const fmtPct = (v: number | null | undefined, digits = 1): string =>
  v === null || v === undefined || Number.isNaN(v) ? '—' : `${(v * 100).toFixed(digits)}%`

export const fmtPp = (v: number, digits = 1): string =>
  `${v >= 0 ? '+' : ''}${(v * 100).toFixed(digits)}${tf('个百分点', 'pp')}`

export const fmtSignedPct = (v: number, digits = 1): string =>
  `${v >= 0 ? '+' : ''}${(v * 100).toFixed(digits)}%`

export const fmtBp = (v: number): string => `${(v * 10000).toFixed(0)}${tf('基点', 'bp')}`

const EN_MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

// dec_YYYYMMDD_xxx → 决策批次 YYYYMMDD / Batch YYYYMMDD
export function fmtDecisionId(id: string): string {
  const m = id.match(/^dec_(\d{4})(\d{2})(\d{2})/)
  return m ? `${tf('决策批次', 'Batch')} ${m[1]}${m[2]}${m[3]}` : id
}

export function fmtAsof(iso: string): string {
  const m = String(iso).match(/^(\d{4})-(\d{2})-(\d{2})(?:T(\d{2}):(\d{2}))?/)
  if (!m) return iso
  const base = tf(
    `${m[1]}年${Number(m[2])}月${Number(m[3])}日`,
    `${EN_MONTHS[Number(m[2]) - 1]} ${Number(m[3])}, ${m[1]}`,
  )
  return m[4] ? `${base} ${m[4]}:${m[5]}` : base
}
