import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { useScenario } from '../scenario'
import { ScenarioPicker } from '../components/Layout'
import { BUCKET_META, BUCKET_ORDER, CLASS_META, CLASS_ORDER, fmtAsof, fmtDecisionId, fmtPct, fmtPp } from '../meta'
import { t, tf, usePrefs } from '../prefs'
import type { DecisionChecks, GuardrailAction, Scenario } from '../types'

interface OverviewData {
  scenario: Scenario
  decision_id: string
  asof: string
  class_weights: Record<string, number>
  bucket_weights: Record<string, number>
  prior_bucket_weights: Record<string, number>
  conclusion: string
  checks: DecisionChecks
  guardrail_actions: GuardrailAction[]
  risk: { portfolio_vol: number; target_vol: number; vol_budget_use: number }
  rebalance: { last: string; rebalanced_today: boolean; max_drift: number; no_trade_band: number }
  engine_runtime_ms: number
  views_count: number
  history_count: number
}

const QUICK_LINKS = [
  { to: '/trace', label: '决策溯源 · 旗舰', desc: '从数据输入、信号、观点到最终权重的三层全链路溯源' },
  { to: '/backtest', label: '回测分析', desc: '用当前配置在历史区间执行完整策略回测与归因' },
  { to: '/daily', label: '日更驾驶舱', desc: '每日信号变化、权重漂移与调仓建议' },
  { to: '/config', label: '配置', desc: '调整风险参数与约束，重新计算决策' },
]

export default function OverviewPage() {
  usePrefs() // 订阅语言/主题切换
  const { scenarioId } = useScenario()
  const [data, setData] = useState<OverviewData | null>(null)
  const [err, setErr] = useState<Error | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setErr(null)
    api
      .overview(scenarioId)
      .then((d) => {
        if (!cancelled) setData(d as OverviewData)
      })
      .catch((e: Error) => {
        if (!cancelled) setErr(e)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [scenarioId])

  return (
    <>
      <div className="page-head">
        <div>
          <h2>{t('总览')}</h2>
          <p className="page-sub">{t('最新决策批次的关键状态与操作入口 · 全部数字来自决策引擎')}</p>
        </div>
        <ScenarioPicker />
      </div>

      {loading && <div className="loading-block">{t('正在加载总览数据…')}</div>}
      {!loading && err && <div className="error-block">{t('加载失败：')}{err.message}</div>}

      {!loading && !err && data && (
        <div className="page-grid">
          <KpiRow data={data} />
          <WeightsCard data={data} />
          <div className="page-grid grid-2">
            <ConclusionCard data={data} />
            <QuickLinksCard />
          </div>
          <div className="demo-banner">{t('Demo 演示数据 · 非投资建议 · 情景为研究性回放，不构成任何操作依据')}</div>
        </div>
      )}
    </>
  )
}

function KpiRow({ data }: { data: OverviewData }) {
  const { checks, risk, rebalance } = data
  const weightClosed = Math.abs(checks.weight_sum_assets - 1) < 1e-6
  const allClosed = weightClosed && checks.attribution_closure
  const withinBand = rebalance.max_drift < rebalance.no_trade_band

  return (
    <div className="page-grid grid-4">
      <div className="app-card">
        <div className="kpi-label">{t('最新决策批次')}</div>
        <div className="kpi-value" style={{ fontSize: 18 }}>{fmtDecisionId(data.decision_id)}</div>
        <div style={{ fontSize: 11.5, color: 'var(--muted)', marginTop: 4 }}>{tf(`${fmtAsof(data.asof)} 生成`, `Generated ${fmtAsof(data.asof)}`)}</div>
        <div className="mono" style={{ color: 'var(--muted)', marginTop: 2, overflowWrap: 'anywhere' }}>{data.decision_id}</div>
      </div>

      <div className="app-card">
        <div className="kpi-label">{t('风险预算使用率')}</div>
        <div className="kpi-value">{fmtPct(risk.vol_budget_use)}</div>
        <div
          style={{ height: 6, borderRadius: 3, background: 'var(--line)', marginTop: 6, overflow: 'hidden' }}
          title={`${t('风险预算使用率')} ${fmtPct(risk.vol_budget_use)}`}
        >
          <div style={{ width: `${Math.min(risk.vol_budget_use, 1) * 100}%`, height: '100%', background: 'var(--teal)' }} />
        </div>
        <div style={{ fontSize: 11.5, color: 'var(--muted)', marginTop: 6 }}>
          {t('组合事前波动')} {fmtPct(risk.portfolio_vol, 2)} / {t('目标波动')} {fmtPct(risk.target_vol, 2)}
        </div>
      </div>

      <div className="app-card">
        <div className="kpi-label">{t('最近调仓')}</div>
        <div className="kpi-value" style={{ fontSize: 18 }}>{fmtAsof(rebalance.last)}</div>
        <div style={{ fontSize: 11.5, marginTop: 4 }}>
          {rebalance.rebalanced_today ? (
            <span style={{ fontWeight: 600, color: 'var(--teal)' }}>● {t('今日已调仓')}</span>
          ) : (
            <span className="status-ok">✓ {t('今日未调仓')}</span>
          )}
        </div>
        <div style={{ fontSize: 11.5, color: 'var(--muted)', marginTop: 2 }}>
          {t('最大漂移')} {fmtPct(rebalance.max_drift, 2)} {withinBand ? '<' : '≥'} {t('免动带')} {fmtPct(rebalance.no_trade_band, 1)}
          {withinBand ? t('，无需交易') : t('，触发调仓')}
        </div>
      </div>

      <div className="app-card">
        <div className="kpi-label">{t('闭合状态')}</div>
        <div style={{ fontSize: 15, fontWeight: 700, marginTop: 2 }}>
          {allClosed ? (
            <span className="status-ok">✓ {t('权重/归因/风控 已闭合')}</span>
          ) : (
            <span className="status-warn">⚠ {t('存在未闭合校验项')}</span>
          )}
        </div>
        <div style={{ fontSize: 11.5, color: 'var(--muted)', marginTop: 6 }}>
          {t('明细权重加总')} <span className="mono">{checks.weight_sum_assets.toFixed(6)}</span>
          {weightClosed ? ' ✓' : ' ✗'} · {t('归因闭合')} {checks.attribution_closure ? '✓' : '✗'}
        </div>
      </div>
    </div>
  )
}

function WeightsCard({ data }: { data: OverviewData }) {
  const classEntries = CLASS_ORDER.map((id) => ({ id, w: data.class_weights[id] ?? 0, meta: CLASS_META[id] }))
  const bucketMax = Math.max(
    ...BUCKET_ORDER.map((id) => Math.max(data.bucket_weights[id] ?? 0, data.prior_bucket_weights[id] ?? 0)),
    0.0001,
  )

  return (
    <div className="app-card">
      <h3>{t('五大类目标权重')}</h3>
      <div
        style={{ display: 'flex', height: 34, borderRadius: 8, overflow: 'hidden', border: '1px solid var(--line)' }}
      >
        {classEntries.map(({ id, w, meta }) => (
          <div
            key={id}
            title={`${t(meta.label)} ${fmtPct(w)}`}
            style={{
              width: `${w * 100}%`,
              background: meta.color,
              color: '#fff',
              fontSize: 11,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              whiteSpace: 'nowrap',
              overflow: 'hidden',
            }}
          >
            {w >= 0.09 ? `${t(meta.label)} ${fmtPct(w)}` : ''}
          </div>
        ))}
      </div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px 14px', marginTop: 8, fontSize: 11.5, color: 'var(--muted)' }}>
        {classEntries.map(({ id, w, meta }) => (
          <span key={id} style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}>
            <span style={{ width: 8, height: 8, borderRadius: 2, background: meta.color, display: 'inline-block' }} />
            {t(meta.label)} {fmtPct(w)}
          </span>
        ))}
      </div>

      <div style={{ margin: '14px 0 6px', fontSize: 11.5, color: 'var(--muted)' }}>
        {t('七桶明细 · 上粗条为目标权重，下细条为战略底仓（同一长度基准）')}
      </div>
      <div style={{ display: 'grid', gap: 8 }}>
        {BUCKET_ORDER.map((id) => {
          const meta = BUCKET_META[id]
          const w = data.bucket_weights[id] ?? 0
          const prior = data.prior_bucket_weights[id] ?? 0
          const d = w - prior
          const flat = Math.abs(d) < 0.001
          return (
            <div
              key={id}
              style={{ display: 'grid', gridTemplateColumns: '76px minmax(0,1fr) 200px', gap: 10, alignItems: 'center' }}
            >
              <div style={{ fontSize: 12.5 }}>{t(meta.label)}</div>
              <div title={tf(`${meta.label}：战略底仓 ${fmtPct(prior)} → 目标 ${fmtPct(w)}`, `${t(meta.label)}: strategic base ${fmtPct(prior)} → target ${fmtPct(w)}`)}>
                <div style={{ width: `${(w / bucketMax) * 100}%`, height: 10, borderRadius: 3, background: meta.color, marginBottom: 3 }} />
                <div style={{ width: `${(prior / bucketMax) * 100}%`, height: 5, borderRadius: 3, background: meta.color, opacity: 0.35 }} />
              </div>
              <div style={{ fontSize: 11.5, color: 'var(--muted)', fontVariantNumeric: 'tabular-nums' }}>
                {fmtPct(prior)} → <span style={{ color: 'var(--ink)', fontWeight: 600 }}>{fmtPct(w)}</span>{' '}
                {flat ? (
                  <span>{t('≈ 持平')}</span>
                ) : (
                  <span className={d > 0 ? 'pos' : 'neg'}>
                    {d > 0 ? '↑' : '↓'} {fmtPp(d)}
                  </span>
                )}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

function ConclusionCard({ data }: { data: OverviewData }) {
  const triggered = data.guardrail_actions.filter((g) => g.triggered)
  return (
    <div className="app-card">
      <h3>{t('最终结论')}</h3>
      <p style={{ margin: '0 0 10px', fontSize: 13.5, lineHeight: 1.7 }}>{data.conclusion}</p>
      <div style={{ fontSize: 11.5, color: 'var(--muted)', margin: '0 0 6px' }}>{t('风控触发情况')}</div>
      {triggered.length === 0 ? (
        <div className="status-ok" style={{ fontSize: 12.5 }}>✓ {t('风控全部通过')}</div>
      ) : (
        <ul style={{ margin: 0, paddingLeft: 18, fontSize: 12.5, display: 'grid', gap: 4 }}>
          {triggered.map((g) => (
            <li key={g.rule}>
              <span className="status-warn">⚠ {t(g.label)}</span>
              <span style={{ color: 'var(--muted)' }}> — {g.detail}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function QuickLinksCard() {
  return (
    <div className="app-card">
      <h3>{t('快捷入口')}</h3>
      <div style={{ display: 'grid', gap: 8 }}>
        {QUICK_LINKS.map((l) => (
          <Link
            key={l.to}
            to={l.to}
            style={{
              display: 'block',
              padding: '9px 12px',
              border: '1px solid var(--line)',
              borderRadius: 8,
              textDecoration: 'none',
              color: 'var(--ink)',
            }}
          >
            <div style={{ fontSize: 13, fontWeight: 600 }}>
              {t(l.label)} <span style={{ color: 'var(--muted)', fontWeight: 400 }}>→</span>
            </div>
            <div style={{ fontSize: 11.5, color: 'var(--muted)', marginTop: 2 }}>{t(l.desc)}</div>
          </Link>
        ))}
      </div>
    </div>
  )
}
