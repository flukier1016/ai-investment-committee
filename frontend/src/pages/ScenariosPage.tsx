import { useEffect, useMemo, useState } from 'react'
import type { EChartsOption } from 'echarts'
import { api } from '../api'
import type { DecisionTraceBundle, Scenario, TracedSignal } from '../types'
import {
  BUCKET_META, BUCKET_ORDER, CLASS_META, CLASS_ORDER, METHOD_META, SOLID, chartTheme,
  fmtAsof, fmtDecisionId, fmtPct,
} from '../meta'
import { t, tf, usePrefs } from '../prefs'
import Chart from '../components/Chart'

interface CompareResp {
  base: DecisionTraceBundle
  other: DecisionTraceBundle
  bucket_diff: Record<string, number>
}

const selectStyle: React.CSSProperties = {
  font: 'inherit', padding: '6px 10px', border: '1px solid var(--line-strong)',
  borderRadius: 8, background: 'var(--paper)', color: 'var(--ink)',
}

function clockSignal(bundle: DecisionTraceBundle): TracedSignal | undefined {
  return Object.values(bundle.signals_by_id).find((s) => s.method === 'clock')
}

/** 单个情景大卡：信号摘要 + 大类堆叠条 + 桶横条 + 结论 + 风控 */
function ScenarioCard({ bundle, scenarioMeta, role, bucketMax }: {
  bundle: DecisionTraceBundle
  scenarioMeta: Scenario | undefined
  role: string
  bucketMax: number
}) {
  const clock = clockSignal(bundle)
  const regime = clock ? String(clock.values.regime ?? '—') : '—'
  const regimeProb = clock && typeof clock.values.probability === 'number' ? clock.values.probability : null
  const signals = bundle.input_signals
    .map((id) => bundle.signals_by_id[id])
    .filter((s): s is TracedSignal => Boolean(s))
  const triggered = bundle.guardrail_actions.filter((g) => g.triggered)

  return (
    <div className="app-card">
      <h3>
        {t(scenarioMeta?.label ?? bundle.scenario_id)}
        <span className="mono" style={{ marginLeft: 'auto', color: 'var(--muted)' }}>{role}</span>
      </h3>
      <div style={{ fontSize: 12.5, color: 'var(--muted)', marginBottom: 6 }}>
        as-of {fmtAsof(bundle.asof)} · {fmtDecisionId(bundle.decision_id)}
      </div>
      {scenarioMeta?.description && (
        <p style={{ margin: '0 0 10px', fontSize: 12.5, lineHeight: 1.55, color: 'var(--muted)' }}>
          {scenarioMeta.description}
        </p>
      )}

      <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, margin: '8px 0' }}>
        <span className="kpi-label">{t('宏观象限')}</span>
        <span className="kpi-value" style={{ color: 'var(--method-clock)' }}>{t(regime)}</span>
        <span style={{ fontSize: 12.5, color: 'var(--muted)' }}>
          {regimeProb !== null ? `${t('象限概率')} ${fmtPct(regimeProb)}` : t('概率缺失')}
        </span>
      </div>

      <div className="kpi-label" style={{ margin: '10px 0 6px' }}>{t('四方法信号摘要')}</div>
      <div style={{ display: 'grid', gap: 6 }}>
        {signals.map((s) => {
          const meta = METHOD_META[s.method]
          return (
            <div key={s.signal_id} style={{
              borderLeft: `3px solid ${meta?.color ?? 'var(--teal)'}`,
              padding: '4px 8px', background: 'var(--surface-2)', borderRadius: '0 6px 6px 0',
            }}>
              <div style={{ fontSize: 12.5 }}>
                <b>{s.method_name}</b>
                <span style={{ color: 'var(--muted)', marginLeft: 8 }}>{t('置信度')} {fmtPct(s.confidence, 0)}</span>
              </div>
              <div style={{ fontSize: 11.5, color: 'var(--muted)', lineHeight: 1.5 }}>{s.rationale}</div>
            </div>
          )
        })}
      </div>

      <div className="kpi-label" style={{ margin: '12px 0 4px' }}>{t('五大类权重')}</div>
      <div className="target-bar" style={{ margin: '4px 0 6px' }}>
        {CLASS_ORDER.map((cid) => {
          const w = bundle.class_weights[cid] ?? 0
          return (
            <div key={cid} title={`${t(CLASS_META[cid].label)} ${fmtPct(w)}`}
              style={{ width: `${w * 100}%`, background: CLASS_META[cid].color }} />
          )
        })}
      </div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px 12px', fontSize: 11.5, color: 'var(--muted)' }}>
        {CLASS_ORDER.map((cid) => (
          <span key={cid} style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
            <span style={{ width: 8, height: 8, borderRadius: 2, background: CLASS_META[cid].color }} />
            {t(CLASS_META[cid].label)} {fmtPct(bundle.class_weights[cid] ?? 0)}
          </span>
        ))}
      </div>

      <div className="kpi-label" style={{ margin: '12px 0 4px' }}>{t('七桶权重')}</div>
      <div style={{ display: 'grid', gap: 5 }}>
        {BUCKET_ORDER.map((bid) => {
          const w = bundle.bucket_weights[bid] ?? 0
          return (
            <div key={bid} style={{ display: 'grid', gridTemplateColumns: '64px 1fr 52px', gap: 8, alignItems: 'center', fontSize: 12 }}>
              <span>{t(BUCKET_META[bid].label)}</span>
              <div className="bar">
                <span style={{ width: `${bucketMax > 0 ? (w / bucketMax) * 100 : 0}%`, background: BUCKET_META[bid].color }} />
              </div>
              <span className="mono" style={{ textAlign: 'right' }}>{fmtPct(w)}</span>
            </div>
          )
        })}
      </div>

      <div className="kpi-label" style={{ margin: '12px 0 4px' }}>{t('结论')}</div>
      <p style={{ margin: 0, fontSize: 12.5, lineHeight: 1.6 }}>{bundle.conclusion}</p>

      <div className="kpi-label" style={{ margin: '12px 0 4px' }}>{t('触发的风控')}</div>
      {triggered.length === 0 ? (
        <div className="status-ok" style={{ fontSize: 12.5 }}>{t('✓ 无风控规则触发')}</div>
      ) : (
        <div style={{ display: 'grid', gap: 4 }}>
          {triggered.map((g) => (
            <div key={g.rule} style={{ fontSize: 12 }}>
              <span className="status-warn">⚠ {t(g.label)}</span>
              <span style={{ color: 'var(--muted)', marginLeft: 6 }}>{g.detail}</span>
            </div>
          ))}
        </div>
      )}

      <div style={{ marginTop: 12, paddingTop: 8, borderTop: '1px solid var(--line)', fontSize: 11.5, color: 'var(--muted)' }}>
        {t('输入指纹')} <span className="mono">{bundle.input_fingerprint.slice(0, 12)}</span>
      </div>
    </div>
  )
}

export default function ScenariosPage() {
  const { lang, theme } = usePrefs()  // 订阅语言/主题切换以触发重渲染
  const [scenarios, setScenarios] = useState<Scenario[]>([])
  const [baseId, setBaseId] = useState('recovery_2026')
  const [otherId, setOtherId] = useState('stagflation_2022')
  const [data, setData] = useState<CompareResp | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.meta().then((m) => setScenarios(m.scenarios.scenarios)).catch((e: Error) => setError(e.message))
  }, [])

  useEffect(() => {
    let alive = true
    setLoading(true)
    setError(null)
    api.compare(baseId, otherId)
      .then((d) => { if (alive) setData(d) })
      .catch((e: Error) => { if (alive) setError(e.message) })
      .finally(() => { if (alive) setLoading(false) })
    return () => { alive = false }
  }, [baseId, otherId])

  const baseMeta = scenarios.find((s) => s.id === baseId)
  const otherMeta = scenarios.find((s) => s.id === otherId)

  // 两张卡的桶横条共用同一 max 基准，保证长度可比
  const bucketMax = useMemo(() => {
    if (!data) return 0
    return Math.max(
      ...BUCKET_ORDER.map((b) => data.base.bucket_weights[b] ?? 0),
      ...BUCKET_ORDER.map((b) => data.other.bucket_weights[b] ?? 0),
    )
  }, [data])

  const diffOption = useMemo<EChartsOption>(() => {
    if (!data) return {}
    const values = BUCKET_ORDER.map((b) => Number(((data.bucket_diff[b] ?? 0) * 100).toFixed(2)))
    return {
      grid: { left: 76, right: 70, top: 26, bottom: 24 },
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'shadow' },
        valueFormatter: (v) => `${Number(v) >= 0 ? '+' : ''}${Number(v).toFixed(2)}${t('个百分点')}`,
      },
      xAxis: {
        type: 'value',
        name: t('个百分点'),
        axisLabel: { formatter: (v: number) => `${v > 0 ? '+' : ''}${v}` },
        splitLine: { lineStyle: { color: chartTheme(theme).grid } },
      },
      yAxis: {
        type: 'category',
        inverse: true,
        data: BUCKET_ORDER.map((b) => t(BUCKET_META[b].label)),
        axisTick: { show: false },
      },
      series: [{
        type: 'bar',
        name: t('base − other 桶权重差'),
        data: values.map((v) => ({
          value: v,
          itemStyle: { color: v >= 0 ? SOLID.red : SOLID.green },
        })),
        barWidth: 16,
        label: {
          show: true,
          position: 'right',
          fontSize: 11,
          formatter: (p) => `${Number(p.value) >= 0 ? '+' : ''}${Number(p.value).toFixed(1)}`,
        },
      }],
    }
  }, [data, lang, theme])

  return (
    <>
      <div className="page-head">
        <div>
          <h2>{t('情景回放')}</h2>
          <p className="page-sub">{t('选择两个时点情景，用各自 as-of 之前可见的数据重算完整决策链，严防未来数据泄漏')}</p>
        </div>
        <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap' }}>
          <label className="scenario-picker">
            {t('基准情景 base')}
            <select style={selectStyle} value={baseId} onChange={(e) => setBaseId(e.target.value)}>
              {scenarios.map((s) => <option key={s.id} value={s.id}>{t(s.label)}</option>)}
            </select>
          </label>
          <label className="scenario-picker">
            {t('对比情景 other')}
            <select style={selectStyle} value={otherId} onChange={(e) => setOtherId(e.target.value)}>
              {scenarios.map((s) => <option key={s.id} value={s.id}>{t(s.label)}</option>)}
            </select>
          </label>
        </div>
      </div>

      <div className="demo-banner">{t('Demo 演示数据 · 非投资建议 · 两个情景由同一决策引擎重算，仅输入数据的可见时点不同')}</div>

      {error && <div className="error-block">{error}</div>}
      {loading && !error && <div className="loading-block">{t('正在按各自 as-of 时点重算两条决策链…')}</div>}

      {!loading && !error && data && (
        <div className="page-grid">
          <div className="page-grid grid-2">
            <ScenarioCard bundle={data.base} scenarioMeta={baseMeta} role={tf('base 基准', 'base')} bucketMax={bucketMax} />
            <ScenarioCard bundle={data.other} scenarioMeta={otherMeta} role={tf('other 对比', 'other')} bucketMax={bucketMax} />
          </div>

          <div className="app-card">
            <h3>
              {t('桶权重差异（base − other）')}
              <span style={{ marginLeft: 'auto', fontSize: 11.5, fontWeight: 400, color: 'var(--muted)' }}>
                {t('正值＝基准情景权重更高（红），负值＝对比情景权重更高（绿）')}
              </span>
            </h3>
            <Chart option={diffOption} height={260} />
          </div>

          <div className="app-card">
            <h3>{t('同一引擎 · 不同时点数据')}</h3>
            <p style={{ margin: '0 0 10px', fontSize: 12.5, lineHeight: 1.6, color: 'var(--muted)' }}>
              {tf('两个情景使用完全相同的决策引擎与参数（引擎版本 ', 'Both scenarios use the exact same decision engine and parameters (engine version ')}
              <span className="mono">{data.base.code_version}</span>
              {tf('），差异只来自各自 as-of 时点之前可见的输入数据——输入指纹不同即为证明，任何 as-of 之后的数据都不会进入计算。',
                '); the differences come only from inputs visible before each as-of — the differing input fingerprints prove it, and no post-as-of data ever enters the computation.')}
            </p>
            <div className="table-scroll">
              <table className="data-table">
                <thead>
                  <tr><th>{t('情景')}</th><th>as-of</th><th>{t('输入指纹（前 12 位）')}</th><th>{t('宏观象限')}</th></tr>
                </thead>
                <tbody>
                  {[{ b: data.base, m: baseMeta, r: 'base' }, { b: data.other, m: otherMeta, r: 'other' }].map(({ b, m, r }) => {
                    const clk = clockSignal(b)
                    return (
                      <tr key={r}>
                        <td>{t(m?.label ?? b.scenario_id)} <span className="mono" style={{ color: 'var(--muted)' }}>{r}</span></td>
                        <td>{fmtAsof(b.asof)}</td>
                        <td className="mono">{b.input_fingerprint.slice(0, 12)}</td>
                        <td>{clk ? t(String(clk.values.regime ?? '—')) : '—'}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
