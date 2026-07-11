import { useEffect, useState } from 'react'
import { api } from '../api'
import { ScenarioPicker } from '../components/Layout'
import { useScenario } from '../scenario'
import {
  BUCKET_META, CLASS_META, METHOD_META, BUCKET_ORDER, CLASS_ORDER, LAYER_ZH,
  fmtAsof, fmtDecisionId, fmtPct, fmtPp, fmtSignedPct,
} from '../meta'
import { t, tf, usePrefs } from '../prefs'

// ---- 本页局部类型（字段以 docs/api_samples/weekly.json 为准） ----

interface WeeklySignal {
  method: string
  method_name: string
  layer: string
  confidence: number
  rationale: string
  abstain: string[]
  signal_id: string
}

interface WeightChange {
  bucket: string
  label: string
  prev: number
  now: number
  delta: number
}

interface RiskEvent {
  rule: string
  label: string
  triggered: boolean
  detail: string
}

interface WeeklyChecks {
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

interface WeeklyData {
  week_of: string
  prev_ref: string
  decision_id: string
  scenario_id: string
  market_summary: Record<string, number>
  signals: WeeklySignal[]
  strategic_base: Record<string, number>
  tactical_tilts: Record<string, number>
  target_classes: Record<string, number>
  target_buckets: Record<string, number>
  weight_changes: WeightChange[]
  risk_events: RiskEvent[]
  guardrail_summary: { total: number; triggered: number }
  checks: WeeklyChecks
  conclusion: string
  data_note: string
  markdown: string
}

// ---- 小型展示组件（仅本页使用） ----

function HBar({ value, max, color }: { value: number; max: number; color: string }) {
  const w = max > 0 ? Math.min(100, (Math.abs(value) / max) * 100) : 0
  return (
    <div style={{ flex: 1, minWidth: 40, height: 8, background: 'var(--bg)', border: '1px solid var(--line)', borderRadius: 4, overflow: 'hidden' }}>
      <div style={{ width: `${w}%`, height: '100%', background: color }} />
    </div>
  )
}

const check = (ok: boolean) => (ok ? '✓' : '✗')

export default function WeeklyPage() {
  usePrefs()  // 订阅语言/主题切换以触发重渲染
  const { scenarioId } = useScenario()
  const [data, setData] = useState<WeeklyData | null>(null)
  const [err, setErr] = useState<Error | null>(null)

  useEffect(() => {
    let alive = true
    setData(null)
    setErr(null)
    api.weekly(scenarioId)
      .then((d) => { if (alive) setData(d as WeeklyData) })
      .catch((e) => { if (alive) setErr(e as Error) })
    return () => { alive = false }
  }, [scenarioId])

  const exportMarkdown = () => {
    if (!data) return
    const blob = new Blob([data.markdown], { type: 'text/markdown;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `weekly_${data.week_of}.md`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  }

  // 同类比例条统一 max 基准
  const chgMax = data ? Math.max(...Object.values(data.market_summary).map((v) => Math.abs(v)), 0) : 0
  const baseMax = data ? Math.max(...Object.values(data.strategic_base), 0) : 0

  return (
    <div>
      <div className="page-head">
        <div>
          <h2>{t('周度纪要')}</h2>
          <p className="page-sub">{t('由本周 Decision Record 结构化生成 · 数字不经 LLM')}</p>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 14, flexWrap: 'wrap' }}>
          <button
            onClick={exportMarkdown}
            disabled={!data}
            style={{
              padding: '6px 14px', border: '1px solid var(--line-strong)', borderRadius: 8,
              background: 'var(--paper)', color: 'var(--ink)', fontSize: 12.5,
              cursor: data ? 'pointer' : 'not-allowed', opacity: data ? 1 : 0.55,
            }}
          >
            {t('导出 Markdown')}
          </button>
          <ScenarioPicker />
        </div>
      </div>

      <div className="demo-banner">
        {t('Demo 演示数据 · 非投资建议')}{data ? ` · ${data.data_note}` : ''}
      </div>

      {err ? (
        <div className="error-block">{err.message}</div>
      ) : !data ? (
        <div className="loading-block">{t('周度纪要加载中…')}</div>
      ) : (
        <div className="page-grid">
          {/* a. 摘要行 */}
          <div className="app-card" style={{ display: 'flex', flexWrap: 'wrap', gap: '10px 36px' }}>
            <div>
              <div className="kpi-label">{t('周报周次')}</div>
              <div style={{ fontWeight: 700, fontSize: 14.5 }}>{fmtAsof(data.week_of)}</div>
            </div>
            <div>
              <div className="kpi-label">{t('决策批次')}</div>
              <div style={{ fontWeight: 700, fontSize: 14.5 }} title={data.decision_id}>{fmtDecisionId(data.decision_id)}</div>
              <div className="mono" style={{ color: 'var(--muted)' }}>{data.decision_id}</div>
            </div>
            <div>
              <div className="kpi-label">{t('对比基准日')}</div>
              <div style={{ fontWeight: 700, fontSize: 14.5 }}>{fmtAsof(data.prev_ref)}</div>
            </div>
          </div>

          {/* b. 本周市场速览 */}
          <div className="app-card">
            <h3>{t('本周市场速览')}</h3>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(230px, 1fr))', gap: '4px 22px' }}>
              {BUCKET_ORDER.filter((b) => data.market_summary[b] !== undefined).map((b) => {
                const v = data.market_summary[b]
                return (
                  <div key={b} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '5px 0' }}>
                    <span style={{ width: 62, fontSize: 12.5, flexShrink: 0 }}>{t(BUCKET_META[b]?.label ?? b)}</span>
                    <HBar value={v} max={chgMax} color={v >= 0 ? 'var(--red)' : 'var(--green)'} />
                    <b className={`mono ${v >= 0 ? 'pos' : 'neg'}`} style={{ width: 58, textAlign: 'right', flexShrink: 0 }}>
                      {fmtSignedPct(v, 2)}
                    </b>
                  </div>
                )
              })}
            </div>
            <div className="kpi-label" style={{ marginTop: 8 }}>{t('周涨跌 · 红涨绿跌 · 相对')} {fmtAsof(data.prev_ref)}</div>
          </div>

          {/* c. 四方法信号 */}
          <div className="app-card">
            <h3>{t('四方法信号')}</h3>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(230px, 1fr))', gap: 10 }}>
              {data.signals.map((s) => {
                const color = METHOD_META[s.method]?.color ?? 'var(--teal)'
                return (
                  <div
                    key={s.signal_id}
                    title={s.signal_id}
                    style={{ border: '1px solid var(--line)', borderTop: `3px solid ${color}`, borderRadius: 8, padding: '9px 11px', minWidth: 0 }}
                  >
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '2px 8px', alignItems: 'baseline' }}>
                      <b style={{ color, fontSize: 13 }}>{s.method_name}</b>
                      <span className="kpi-label">{t(LAYER_ZH[s.layer] ?? s.layer)} · {t('置信度')} {fmtPct(s.confidence, 0)}</span>
                    </div>
                    <p style={{ margin: '6px 0 0', fontSize: 12, color: 'var(--muted)', lineHeight: 1.6 }}>{s.rationale}</p>
                    {s.abstain.length > 0 && (
                      <div className="chip abstain" style={{ display: 'inline-block', marginTop: 7 }}>
                        {t('弃权')}{tf('：', ': ')}{s.abstain.map((b) => t(BUCKET_META[b]?.label ?? b)).join(tf('、', ', '))}
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          </div>

          {/* d / e / f */}
          <div className="page-grid grid-3">
            {/* d. 战略底仓 */}
            <div className="app-card">
              <h3>{t('战略底仓（Risk Parity）')}</h3>
              {BUCKET_ORDER.filter((b) => data.strategic_base[b] !== undefined).map((b) => {
                const v = data.strategic_base[b]
                return (
                  <div key={b} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '5px 0' }}>
                    <span style={{ width: 62, fontSize: 12.5, flexShrink: 0 }}>{t(BUCKET_META[b]?.label ?? b)}</span>
                    <HBar value={v} max={baseMax} color={BUCKET_META[b]?.color ?? 'var(--teal)'} />
                    <b className="mono" style={{ width: 48, textAlign: 'right', flexShrink: 0 }}>{fmtPct(v, 1)}</b>
                  </div>
                )
              })}
              <div className="kpi-label" style={{ marginTop: 8 }}>{t('7 桶战略权重 · 桶间等风险贡献')}</div>
            </div>

            {/* e. 战术偏离 */}
            <div className="app-card">
              <h3>{t('战术偏离（Black-Litterman Model 融合）')}</h3>
              {BUCKET_ORDER.filter((b) => data.tactical_tilts[b] !== undefined).length === 0 ? (
                <p style={{ fontSize: 12.5, color: 'var(--muted)' }}>{t('本周无战术偏离')}</p>
              ) : (
                BUCKET_ORDER.filter((b) => data.tactical_tilts[b] !== undefined).map((b) => {
                  const v = data.tactical_tilts[b]
                  return (
                    <div key={b} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, padding: '7px 0', borderBottom: '1px solid var(--line)' }}>
                      <span style={{ fontSize: 12.5 }}>
                        <span style={{ display: 'inline-block', width: 8, height: 8, borderRadius: '50%', background: BUCKET_META[b]?.color ?? 'var(--teal)', marginRight: 7 }} />
                        {t(BUCKET_META[b]?.label ?? b)}
                      </span>
                      <b className={`mono ${v >= 0 ? 'pos' : 'neg'}`}>{fmtPp(v)}</b>
                    </div>
                  )
                })
              )}
              <div className="kpi-label" style={{ marginTop: 8 }}>{t('相对战略底仓的偏离 · 红正绿负')}</div>
            </div>

            {/* f. 目标权重与变化 */}
            <div className="app-card">
              <h3>{t('目标权重与变化')}</h3>
              <div style={{ display: 'flex', height: 16, borderRadius: 8, overflow: 'hidden', border: '1px solid var(--line)' }}>
                {CLASS_ORDER.map((c) => (
                  <div
                    key={c}
                    title={`${t(CLASS_META[c]?.label ?? c)} ${fmtPct(data.target_classes[c] ?? 0, 1)}`}
                    style={{ width: `${(data.target_classes[c] ?? 0) * 100}%`, background: CLASS_META[c]?.color ?? 'var(--teal)' }}
                  />
                ))}
              </div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px 14px', marginTop: 8 }}>
                {CLASS_ORDER.filter((c) => data.target_classes[c] !== undefined).map((c) => (
                  <span key={c} style={{ fontSize: 12, color: 'var(--muted)' }}>
                    <span style={{ display: 'inline-block', width: 8, height: 8, borderRadius: '50%', background: CLASS_META[c]?.color ?? 'var(--teal)', marginRight: 5 }} />
                    {t(CLASS_META[c]?.label ?? c)} <b className="mono" style={{ color: 'var(--ink)' }}>{fmtPct(data.target_classes[c], 1)}</b>
                  </span>
                ))}
              </div>
              <div className="kpi-label" style={{ margin: '12px 0 4px' }}>{t('与上周相比的主要变化')}</div>
              {data.weight_changes.length === 0 ? (
                <p style={{ fontSize: 12.5, color: 'var(--muted)', margin: 0 }}>{t('本周目标权重基本稳定')}</p>
              ) : (
                data.weight_changes.map((c) => (
                  <div key={c.bucket} style={{ display: 'flex', justifyContent: 'space-between', gap: 8, padding: '6px 0', borderTop: '1px solid var(--line)', fontSize: 12.5 }}>
                    <span>{t(c.label)}</span>
                    <span className="mono">
                      {fmtPct(c.prev, 1)} → {fmtPct(c.now, 1)}{tf('（', ' (')}<b className={c.delta >= 0 ? 'pos' : 'neg'}>{fmtPp(c.delta)}</b>{tf('）', ')')}
                    </span>
                  </div>
                ))
              )}
            </div>
          </div>

          {/* g / h */}
          <div className="page-grid grid-2">
            {/* g. 风险事件与风控状态 */}
            <div className="app-card">
              <h3>{t('风险事件与风控状态')}</h3>
              <div style={{ fontSize: 12.5, marginBottom: 6 }}>
                {tf('风控规则', 'Guardrail rules')} <b className="mono">{data.guardrail_summary.total}</b> {tf('条 / 触发', '· triggered')}{' '}
                <b className={`mono ${data.guardrail_summary.triggered > 0 ? 'status-warn' : 'status-ok'}`}>{data.guardrail_summary.triggered}</b>{tf(' 条', '')}
              </div>
              {data.risk_events.length === 0 ? (
                <p style={{ fontSize: 12.5, color: 'var(--muted)' }}>{t('本周无触发的风险事件')}</p>
              ) : (
                data.risk_events.map((e) => (
                  <div key={e.rule} style={{ padding: '7px 0', borderTop: '1px solid var(--line)' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, alignItems: 'baseline' }}>
                      <b style={{ fontSize: 12.5 }}>{t(e.label)}</b>
                      <span className={e.triggered ? 'status-warn' : 'status-ok'} style={{ fontSize: 12, whiteSpace: 'nowrap' }}>
                        {e.triggered ? t('⚠ 触发') : t('✓ 通过')}
                      </span>
                    </div>
                    <div style={{ fontSize: 12, color: 'var(--muted)', marginTop: 2 }}>{e.detail}</div>
                  </div>
                ))
              )}
            </div>

            {/* h. 结论 */}
            <div className="app-card">
              <h3>{t('结论与调仓建议')}</h3>
              <p style={{ margin: 0, fontSize: 13, lineHeight: 1.7 }}>{data.conclusion}</p>
              <div className="mono" style={{ marginTop: 12, color: 'var(--muted)', lineHeight: 1.7 }}>
                {tf('校验闭合：权重和 资产', 'Closure checks: weight sums — assets')} {data.checks.weight_sum_assets.toFixed(4)} {tf('/ 桶', '/ buckets')} {data.checks.weight_sum_buckets.toFixed(4)} {tf('/ 大类', '/ classes')} {data.checks.weight_sum_classes.toFixed(4)}
                {' · '}{tf('归因闭合', 'attribution closure')} {check(data.checks.attribution_closure)}
                {' · '}{tf('观点溯源', 'view lineage')} {check(data.checks.views_have_sources)}
                {' · '}{tf('Ω 正定', 'Ω positive-definite')} {check(data.checks.omega_positive)}
                {' · '}{tf('组合事前波动', 'ex-ante portfolio vol')} {fmtPct(data.checks.portfolio_vol, 2)}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
