import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { api, savedConfig } from '../api'
import { fmtAsof, fmtBp, fmtDecisionId, fmtPct, fmtPp } from '../meta'
import { useScenario } from '../scenario'
import { t, tf, usePrefs } from '../prefs'
import { ScenarioPicker } from '../components/Layout'
import type {
  BLView, BucketStance, CommitteeRiskPerspective, DecisionTraceBundle,
  RiskPerspectiveAssessment, TracedSignal,
} from '../types'

// ---------- 展示口径（英文全称 + 固定方法色） ----------
const METHOD_INFO: Record<string, { name: string; color: string }> = {
  risk_parity: { name: 'Risk Parity', color: 'var(--method-risk-parity)' },
  tsmom: { name: 'Time Series Momentum', color: 'var(--method-cta)' },
  clock: { name: 'Merrill Lynch Investment Clock', color: 'var(--method-clock)' },
  erp: { name: 'Equity Risk Premium', color: 'var(--method-erp)' },
  black_litterman: { name: 'Black-Litterman Model', color: 'var(--bl)' },
}
const LAYER_LABELS: Record<string, string> = { strategic: '战略底仓', tactical: '战术偏离' }
const VIEW_TYPE_LABELS: Record<string, string> = {
  risk_budget: '风险预算', direction: '方向观点', regime: '宏观象限', percentile: '分位观点', abstain: '弃权',
}
const SIGNAL_VALUE_LABELS: Record<string, string> = {
  regime: '宏观象限', probability: '概率', percentile: '分位', gap: '股债利差',
  cn_equity_vs_cn_bond: '中国股票相对中国债券',
}
const STANCE_TONE: Record<BucketStance, 'positive' | 'flat' | 'negative'> = {
  '显著超配': 'positive', '超配': 'positive', '中性': 'flat',
  '低配': 'negative', '显著低配': 'negative',
}
const RISK_ROLE_INFO: Record<CommitteeRiskPerspective['role'], { label: string; focus: string }> = {
  aggressive: { label: '激进视角', focus: '波动预算利用率' },
  conservative: { label: '保守视角', focus: '距上限余量' },
  neutral: { label: '中性视角', focus: '换手相称性' },
}
const RISK_ASSESSMENT_LABEL: Record<RiskPerspectiveAssessment, string> = {
  capacity_remaining: '预算尚有余量', at_budget: '预算已用满', over_budget: '预算已超限',
  headroom: '上限仍有余量', binding: '上限已贴边', breach: '上限已突破',
  no_turnover: '无理论换手', fully_explained: '桶级完全解释',
  partly_explained: '桶级部分解释', intra_bucket_only: '仅桶内调整',
  inconsistent: '换手口径不一致',
}

interface DrawerState { kind: string; title: string; body: ReactNode }
interface Selection { signalIds: string[]; viewId: string }

export default function TracePage() {
  const { scenarioId } = useScenario()
  usePrefs()  // 订阅主题/语言切换以触发重渲染
  const [bundle, setBundle] = useState<DecisionTraceBundle | null>(null)
  const [error, setError] = useState('')
  const [drawer, setDrawer] = useState<DrawerState | null>(null)
  const [selection, setSelection] = useState<Selection>({ signalIds: [], viewId: '' })
  const [modalOpen, setModalOpen] = useState(false)
  const [modalTab, setModalTab] = useState<'matrix' | 'trace'>('matrix')
  const [focusViewId, setFocusViewId] = useState('')
  const [bucketsExpanded, setBucketsExpanded] = useState(false)
  const [detailExpanded, setDetailExpanded] = useState(false)
  const [committeeExpanded, setCommitteeExpanded] = useState(false)

  useEffect(() => {
    setBundle(null)
    setError('')
    api.runDecision(scenarioId, savedConfig())
      .then(setBundle)
      .catch((e: Error) => setError(e.message))
  }, [scenarioId])

  const closeAll = useCallback(() => {
    setDrawer(null)
    setSelection({ signalIds: [], viewId: '' })
    setModalOpen(false)
  }, [])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') closeAll() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [closeAll])

  const derived = useMemo(() => {
    if (!bundle) return null
    const bucketById = Object.fromEntries(bundle.display_buckets.map((b) => [b.id, b]))
    const assetById = Object.fromEntries(bundle.assets.map((a) => [a.id, a]))
    const target = bundle.bucket_weights
    const prior = bundle.prior.bucket_weights
    const viewMethodId = (view: BLView): string =>
      bundle.signals_by_id[view.source_signal_ids[0]]?.method ?? 'black_litterman'
    const contribution = (bucketId: string, viewId: string): number =>
      bundle.attribution[bucketId]?.[viewId] ?? 0
    const viewBucketIds = (view: BLView): string[] => {
      const affected = new Set(Object.keys(view.P).map((aid) => assetById[aid]?.bucket).filter(Boolean))
      return bundle.display_buckets.filter((b) => affected.has(b.id)).map((b) => b.id)
    }
    const viewById = (id: string) => bundle.bl_inputs.views.find((v) => v.view_id === id)
    const assetOrder = bundle.display_buckets.flatMap((b) => bundle.assets.filter((a) => a.bucket === b.id).map((a) => a.id))
    return { bucketById, assetById, target, prior, viewMethodId, contribution, viewBucketIds, viewById, assetOrder }
  }, [bundle])

  if (error) return <div className="error-block">{tf('决策数据加载失败：', 'Failed to load decision data: ')}{error}</div>
  if (!bundle || !derived) return <div className="loading-block">{tf('正在执行完整计算链路并加载决策追踪数据包…', 'Running the full pipeline and loading the decision trace bundle…')}</div>

  const { bucketById, assetById, target, prior, viewMethodId, contribution, viewBucketIds, viewById, assetOrder } = derived

  // ---------- 交互：正反向追溯 ----------
  const openSignal = (signalId: string) => {
    const signal = bundle.signals_by_id[signalId]
    if (!signal) return
    setSelection({ signalIds: [signalId], viewId: '' })
    setDrawer({ kind: t('信号'), title: METHOD_INFO[signal.method].name, body: <SignalDetails signal={signal} /> })
  }
  const openView = (viewId: string) => {
    const view = viewById(viewId)
    if (!view) return
    setSelection({ signalIds: view.source_signal_ids, viewId })
    setDrawer({
      kind: tf('Black-Litterman Model 观点', 'Black-Litterman View'),
      title: `${METHOD_INFO[viewMethodId(view)].name} · ${view.label}`,
      body: <ViewDetails view={view} bundle={bundle} methodId={viewMethodId(view)} assetById={assetById}
        onOpenTrace={() => { setModalTab('trace'); setFocusViewId(viewId); setModalOpen(true) }} />,
    })
  }
  const openAttribution = (bucketId: string, viewId: string) => {
    const view = viewById(viewId)
    if (!view) return
    const value = contribution(bucketId, viewId)
    setSelection({ signalIds: view.source_signal_ids, viewId })
    setDrawer({
      kind: t('归因'),
      title: `${bucketById[bucketId].label} ${fmtPp(value)}`,
      body: (
        <>
          <MethodBadge methodId={viewMethodId(view)} />
          <Kv k={t('汇总桶')} v={t(bucketById[bucketId].label)} />
          <Kv k={t('观点ID')} v={viewId} />
          <Kv k={t('贡献')} v={fmtPp(value)} />
          <Kv k={t('汇总桶目标')} v={fmtPct(target[bucketId])} />
          <Kv k={t('闭合')} v={`${fmtPct(Object.values(bundle.attribution[bucketId]).reduce((s, x) => s + x, 0))}${tf(' 由先验 + 观点贡献 + 风控段闭合', ' = prior + view contributions + guardrail')}`} />
          <Kv k={t('来源信号')} v={view.source_signal_ids.join(', ')} />
          <div className="codebox">{JSON.stringify({ attribution_for_bucket: bundle.attribution[bucketId], view }, null, 2)}</div>
        </>
      ),
    })
  }

  // ---------- 顶部数据 ----------
  const classTargets = bundle.class_weights
  const classPrior = bundle.prior.class_weights
  const closureOk = Math.abs(bundle.checks.weight_sum_assets - 1) < 1e-6 && Math.abs(bundle.checks.weight_sum_buckets - 1) < 1e-6
  const attributionOk = bundle.checks.attribution_closure
  const triggered = bundle.guardrail_actions.filter((a) => a.triggered)
  const tacticalMethods = ['tsmom', 'clock', 'erp']

  const classBar = (weights: Record<string, number>) => (
    <div className="target-bar labeled">
      {bundle.asset_classes.map((c) => (
        <div key={c.id} className="target-segment" style={{ width: `${weights[c.id] * 100}%`, background: c.color }}
          title={`${t(c.label)} ${fmtPct(weights[c.id])}`}>
          <span className="target-segment-label"><span>{t(c.label)}</span><b>{fmtPct(weights[c.id])}</b></span>
        </div>
      ))}
    </div>
  )

  const classBreakdown = (bucketWeights: Record<string, number>, classWeights: Record<string, number>) => (
    <div className="class-breakdown">
      {bundle.asset_classes.map((c) => (
        <div key={c.id} className="class-row" style={{ ['--asset-color' as string]: c.color }}>
          <div className="class-row-head">
            <span className="class-main"><span className="dot"></span>{t(c.label)}</span>
            <span className="class-total">{fmtPct(classWeights[c.id])}</span>
          </div>
          <div className="class-mini-bar">
            {c.bucket_ids.map((bid) => (
              <span key={bid} style={{ width: `${classWeights[c.id] > 0 ? (bucketWeights[bid] / classWeights[c.id]) * 100 : 0}%`, ['--bucket-color' as string]: bucketById[bid].color }}
                title={`${t(bucketById[bid].label)} ${fmtPct(bucketWeights[bid])}`}></span>
            ))}
          </div>
          <div className={`class-sub ${c.bucket_ids.length === 1 ? 'single' : ''}`}>
            {c.bucket_ids.map((bid) => (
              <div key={bid} className="class-sub-box" style={{ ['--bucket-color' as string]: bucketById[bid].color }}>
                <b title={t(bucketById[bid].label)}>{t(bucketById[bid].label)}</b>
                <span>{fmtPct(bucketWeights[bid])}</span>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  )

  return (
    <div className="trace-page">
      <header className="page-head">
        <div>
          <h2>{t('决策溯源 · 一页式三层看板')}</h2>
          <p className="page-sub">{t('中国投资者视角 · 27 项明细资产 · 五类目标权重与全链路归因 · 研究推演，非投资建议')}</p>
        </div>
        <ScenarioPicker />
      </header>

      <div className="meta" style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 14 }}>
        <span className="badge">{t('时点')} {fmtAsof(bundle.asof)}</span>
        <span className="badge">{fmtDecisionId(bundle.decision_id)}</span>
        <span className="badge">{bundle.mode === 'demo' ? t('演示模式') : bundle.mode}</span>
        <span className="badge">{bundle.assets.length}{tf(' 项明细资产', ' assets')}</span>
        <span className="badge">{bundle.display_buckets.length}{tf(' 个汇总桶', ' buckets')}</span>
        <span className="badge mono" title={`${tf('输入指纹', 'Input fingerprint')} ${bundle.input_fingerprint}`}>{t('指纹')} {bundle.input_fingerprint.slice(0, 10)}</span>
        {bundle.degraded_inputs.length > 0 && (
          <span className="badge" style={{ borderColor: 'var(--amber)', color: 'var(--amber)' }}
            title={bundle.degraded_inputs.map((d) => `${d.input}: ${d.reason}`).join('\n')}>
            ⚠ {t('输入降级')} {bundle.degraded_inputs.length}
          </span>
        )}
      </div>

      {/* ===== 第一整行：最终结果 ===== */}
      <section className="summary">
        <div className="summary-cell final-result">
          <div className="result-head">
            <div>
              <div className="label">{t('最终结果')}</div>
              <h2>{t('合成目标权重')}</h2>
            </div>
            <span className="result-badge">{t('Risk Parity 底仓经 Black-Litterman Model 融合后得到目标')}</span>
          </div>
          <div className="final-grid">
            <div>
              {classBar(classTargets)}
              {classBreakdown(target, classTargets)}
            </div>
            <div className="final-copy">
              <b>{t('最终建议')}</b>
              <p>{bundle.conclusion}</p>
            </div>
          </div>
        </div>

        {/* ===== 权重生成路径 ===== */}
        <div className="summary-cell path-panel">
          <div className="label">{t('权重生成路径')}</div>
          <div className="allocation-stack">
            <div className="allocation-layer strategic">
              <div className="layer-head">
                <span className="layer-title">{t('战略底仓')}</span>
                <span className="layer-index">{t('第一层')}</span>
              </div>
              {classBar(classPrior)}
              {classBreakdown(prior, classPrior)}
              <div className="path-method-line">
                <MethodBadge methodId="risk_parity" />
                <span className="layer-note">{t('唯一战略方法，生成 5 大类与 7 个细分桶的底仓先验。')}</span>
              </div>
            </div>
            <div className="allocation-layer tactical">
              <div className="layer-head">
                <span className="layer-title">{t('战术偏离 + 观点整合')}</span>
                <span className="layer-index">{t('第二层')}</span>
              </div>
              <div className="tactical-methods">
                {tacticalMethods.map((m) => (
                  <div key={m} className="tactical-method" style={{ ['--method-color' as string]: METHOD_INFO[m].color }}>
                    <MethodBadge methodId={m} compact />
                    <b>{bundle.bl_inputs.views.filter((v) => viewMethodId(v) === m).length}{t('条观点')}</b>
                  </div>
                ))}
              </div>
              <div className="tilt-grid">
                {bundle.asset_classes.map((c) => {
                  const delta = classTargets[c.id] - classPrior[c.id]
                  const cls = delta > 0.0001 ? 'positive' : delta < -0.0001 ? 'negative' : 'flat'
                  return <span key={c.id} className={`tilt-chip ${cls}`}><span>{t(c.label)}</span><b>{fmtPp(delta)}</b></span>
                })}
              </div>
              <div className="layer-note">{t('三种战术方法生成方向、收益与置信度观点，经 Black-Litterman Model 融合后，转成相对 Risk Parity 底仓的增减。')}</div>
            </div>
          </div>
        </div>

        <div className="summary-cell status-card">
          <div className="label">{t('权重闭合')}</div>
          <div className={`status-line ${closureOk ? '' : 'warn'}`}><span className="status-dot"></span>{closureOk ? t('已通过') : t('需检查')}</div>
          <div className="small">{t('明细资产与汇总桶都闭合到')}{(bundle.checks.weight_sum_assets * 100).toFixed(4)}%</div>
        </div>
        <div className="summary-cell status-card">
          <div className="label">{t('溯源闭合')}</div>
          <div className={`status-line ${attributionOk ? '' : 'warn'}`}><span className="status-dot"></span>{attributionOk ? t('已通过') : t('需检查')}</div>
          <div className="small">{t('Risk Parity 底仓加 Black-Litterman Model 观点贡献与风控段后，等于汇总目标权重')}</div>
        </div>
        <div className="summary-cell status-card">
          <div className="label">{t('风控闸门')}</div>
          <div className={`status-line ${triggered.length === 0 ? '' : 'warn'}`}><span className="status-dot"></span>{triggered.length === 0 ? t('未触发') : t('已触发')}</div>
          <div className="small">{t('触发规则')} {triggered.length}{tf(' 条', '')}{triggered.length > 0 ? `: ${triggered.map((a) => t(a.label)).join(tf('、', ', '))}` : t('；本批次未发生硬约束裁剪')}</div>
        </div>
      </section>

      {/* ===== 三层步骤导航 ===== */}
      <section className="step-rail">
        {[
          { n: t('第一层'), c: 'var(--method-risk-parity)', h: t('四方法信号'), d: t('Risk Parity 负责战略底仓；其余三种方法形成战术观点。') },
          { n: t('第二层'), c: 'var(--bl)', h: t('观点与 Black-Litterman Model 装配'), d: t('战略先验与战术观点经 Black-Litterman Model 融合为后验收益。') },
          { n: t('第三层'), c: 'var(--rose)', h: t('权重归因'), d: t('先看汇总结论，再追到观点、信号和输入摘要。') },
        ].map((s) => (
          <div key={s.n} className="step" style={{ ['--accent' as string]: s.c }}>
            <div className="num">{s.n}</div>
            <h3>{s.h}</h3>
            <div className="small">{s.d}</div>
          </div>
        ))}
      </section>

      {/* ===== 三层主链路 ===== */}
      <section className="process">
        {/* L1 信号 */}
        <section className="section" data-step={t('第一层')} id="signals">
          <h2>{t('四方法信号')}</h2>
          <p className="section-sub">{t('Risk Parity 独立生成战略底仓；Time Series Momentum、Merrill Lynch Investment Clock、Equity Risk Premium 形成战术观点。')}</p>
          <div>
            {[
              { index: t('战略'), title: t('战略底仓'), note: t('Risk Parity 是唯一战略方法，直接生成组合底仓先验。'), color: 'var(--method-risk-parity)', methods: ['risk_parity'] },
              { index: t('战术'), title: t('战术偏离'), note: t('Time Series Momentum、Merrill Lynch Investment Clock、Equity Risk Premium 生成阶段性 Black-Litterman Model 观点。'), color: 'var(--bl)', methods: ['tsmom', 'clock', 'erp'] },
            ].map((group) => (
              <div key={group.title} className="signal-layer" style={{ ['--layer-color' as string]: group.color }}>
                <div className="signal-layer-head">
                  <span className="layer-index">{group.index}</span>
                  <span className="layer-title">{group.title}</span>
                  <span className="layer-note">{group.note}</span>
                </div>
                <div className="signal-grid">
                  {group.methods.map((m) => {
                    const signal = Object.values(bundle.signals_by_id).find((s) => s.method === m)
                    return signal ? (
                      <SignalCard key={signal.signal_id} signal={signal} bucketById={bucketById}
                        selected={selection.signalIds.includes(signal.signal_id)}
                        onOpen={() => openSignal(signal.signal_id)} />
                    ) : null
                  })}
                </div>
              </div>
            ))}
            {/* 信号去向 */}
            <div className="signal-output">
              <div className="group-title" style={{ margin: 0 }}>{t('信号去向 · 到观点层')}</div>
              {bundle.input_signals.map((signalId) => {
                const signal = bundle.signals_by_id[signalId]
                const views = bundle.bl_inputs.views.filter((v) => v.source_signal_ids.includes(signalId))
                const method = METHOD_INFO[signal.method]
                const isStrategic = signal.layer === 'strategic'
                return (
                  <div key={signalId} className={`signal-flow-row ${selection.signalIds.includes(signalId) ? 'selected' : ''}`}
                    style={{ ['--accent' as string]: method.color }} role="button" tabIndex={0}
                    onClick={() => openSignal(signalId)}
                    onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openSignal(signalId) } }}>
                    <span className="flow-method">{method.name}</span>
                    <span className="flow-path">
                      {isStrategic
                        ? <><b>{t('进入战略底仓')}</b> · {t('直接形成 Risk Parity 先验')}</>
                        : <><b>{views.length} {tf('条 Black-Litterman Model 观点', 'Black-Litterman views')}</b>{views.length > 0 ? <> · {views.slice(0, 2).map((v) => t(v.label)).join(tf('、', ', '))}{views.length > 2 ? tf(' 等', ' …') : ''}</> : <> · {t('本批次弃权或中性')}</>}</>}
                    </span>
                    <span className="flow-impact" style={{ color: isStrategic ? method.color : 'var(--bl)' }}>
                      {isStrategic ? t('底仓') : `${views.length}${tf(' 条', '')}`}
                    </span>
                  </div>
                )
              })}
            </div>
          </div>
        </section>

        {/* L2 BL 装配 */}
        <section className="section" data-step={t('第二层')} id="bl">
          <h2>{t('战术观点与 Black-Litterman Model 装配')}</h2>
          <p className="section-sub">{t('直观看见战略先验与战术观点如何经贝叶斯融合，形成后验收益并推动目标权重。')}</p>
          <div className="row-stack">
            <div>
              <div className="group-title" style={{ marginTop: 0 }}>{t('Black-Litterman Model 如何起作用')}</div>
              <div className="bl-assembly">
                <div className="bl-input-stack">
                  <div className="bl-node prior">
                    <div className="bl-node-kicker">{t('先验 π · 战略底仓')}</div>
                    <MethodBadge methodId="risk_parity" compact />
                    <strong>π = δΣw<sub>RP</sub></strong>
                    <p>{t('Risk Parity 权重结合协方差与风险厌恶系数，反推出先验收益。')}</p>
                  </div>
                  <div className="bl-node views">
                    <div className="bl-node-kicker">{t('观点 · 三专家集议')}</div>
                    <div className="bl-method-row">{tacticalMethods.map((m) => <MethodBadge key={m} methodId={m} compact />)}</div>
                    <strong>P + Q + Ω · {bundle.bl_inputs.views.length}{tf(' 条', '')}</strong>
                    <div className="bl-field-row">
                      <span className="bl-field">{t('P 方向与暴露')}</span>
                      <span className="bl-field">{t('Q 观点收益')}</span>
                      <span className="bl-field">{t('置信度 → Ω')}</span>
                    </div>
                  </div>
                </div>
                <div className="bl-operator" aria-hidden="true">→</div>
                <div className="bl-engine">
                  <div className="engine-name">Black-Litterman Model</div>
                  <strong>{t('贝叶斯观点融合')}</strong>
                  <div className="engine-formula">μ<sub>BL</sub> = Fuse(π, P, Q, Ω)</div>
                  <p>{t('Ω 决定每条观点的可信权重；后验不是简单平均。')}</p>
                  <button className="text-btn bl-tech-btn" onClick={() => { setModalTab('trace'); setFocusViewId(''); setModalOpen(true) }}>{t('查看计算过程')}</button>
                </div>
                <div className="bl-operator" aria-hidden="true">→</div>
                <div className="bl-node output">
                  <div className="bl-node-kicker">{t('后验 · 融合输出')}</div>
                  <strong>{t('后验收益 → 目标权重')}</strong>
                  <p>{t('优化器生成目标，并保留每条观点的可闭合贡献。')}</p>
                </div>
              </div>
            </div>

            <div>
              <div className="group-title">{t('先验明细 · Risk Parity 战略底仓')}</div>
              {bundle.display_buckets.map((b) => (
                <div key={b.id} className="prior-row" style={{ ['--asset-color' as string]: b.color }}>
                  <b style={{ color: b.color }}>{t(b.label)}</b>
                  <div className="bar"><span style={{ width: `${prior[b.id] * 100}%` }}></span></div>
                  <span className="weight-meta">{fmtPct(prior[b.id])}</span>
                </div>
              ))}
            </div>

            <div>
              <div className="group-title">{t('观点明细 · 按资产类别组织')}</div>
              <div className="view-list">
                {bundle.display_buckets.map((bucket, index) => {
                  const bucketViews = bundle.bl_inputs.views
                    .filter((v) => viewBucketIds(v).includes(bucket.id))
                    .sort((a, b2) => Math.abs(contribution(bucket.id, b2.view_id)) - Math.abs(contribution(bucket.id, a.view_id)))
                  const netImpact = bucketViews.reduce((s, v) => s + contribution(bucket.id, v.view_id), 0)
                  return (
                    <details key={`${bucket.id}-${bucketsExpanded}-${index === 0}`} className="view-bucket-group" style={{ ['--asset-color' as string]: bucket.color }}
                      open={bucketsExpanded || index === 0}>
                      <summary>
                        <span className="view-bucket-title">{t(bucket.label)}</span>
                        <span className="view-bucket-meta">{bucketViews.length}{t('条观点')} · {fmtPp(netImpact)}</span>
                      </summary>
                      <div className="view-bucket-list">
                        {bucketViews.map((view) => {
                          const methodId = viewMethodId(view)
                          const impact = contribution(bucket.id, view.view_id)
                          return (
                            <article key={`${bucket.id}-${view.view_id}`}
                              className={`view-card ${selection.viewId === view.view_id ? 'selected' : ''}`}
                              style={{ ['--accent' as string]: METHOD_INFO[methodId].color }} role="button" tabIndex={0}
                              onClick={() => openView(view.view_id)}
                              onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openView(view.view_id) } }}>
                              <div className="view-card-head">
                                <div>
                                  <MethodBadge methodId={methodId} compact />
                                  <div className="view-title">{t(view.label)}</div>
                                  <div className="card-subline">{t('作用于')}{t(bucket.label)}{tf(' · 血缘已记录', ' · lineage recorded')}</div>
                                </div>
                                <div className="view-impact" style={{ color: impact >= 0 ? 'var(--red)' : 'var(--green)' }}>{fmtPp(impact)}</div>
                              </div>
                              <div className="view-assets"><CompactP view={view} assetById={assetById} bucketId={bucket.id} limit={4} /></div>
                              <div className="metric-row">
                                <div className="metric"><span className="k">{t('观点收益')}</span><span className="v">{fmtBp(view.Q)}</span></div>
                                <div className="metric"><span className="k">{t('置信度')}</span><span className="v">{fmtPct(view.confidence)}</span></div>
                                <div className="metric"><span className="k">{t('对本类权重')}</span><span className="v" style={{ color: impact >= 0 ? 'var(--red)' : 'var(--green)' }}>{fmtPp(impact)}</span></div>
                              </div>
                            </article>
                          )
                        })}
                        {bucketViews.length === 0 && <div className="small" style={{ padding: '8px 2px' }}>{t('本资产类别本批次无战术观点。')}</div>}
                      </div>
                    </details>
                  )
                })}
              </div>
              <div className="table-actions">
                <span className="small">{t('同一相对观点会同时出现在它影响的资产类别下。')}</span>
                <span>
                  <button className="text-btn" onClick={() => setBucketsExpanded((v) => !v)}>{bucketsExpanded ? t('收起资产类别') : t('展开全部类别')}</button>
                  <button className="text-btn" onClick={() => { setModalTab('matrix'); setFocusViewId(''); setModalOpen(true) }}>{t('打开技术工作台')}</button>
                </span>
              </div>
            </div>

            <div>
              <div className="group-title">{t('融合输出 · 后验期望收益')}</div>
              <table>
                <thead><tr><th>{t('资产桶')}</th><th className="num">{t('先验收益')}</th><th className="num">{t('后验收益')}</th><th className="num">{t('变化')}</th></tr></thead>
                <tbody>
                  {bundle.display_buckets.map((b) => {
                    const pi = bundle.prior.pi_buckets[b.id]
                    const er = bundle.posterior_ER[b.id]
                    return (
                      <tr key={b.id}>
                        <td style={{ color: b.color }}><b>{t(b.label)}</b></td>
                        <td className="num">{fmtBp(pi)}</td>
                        <td className="num">{fmtBp(er)}</td>
                        <td className="num" style={{ color: er - pi >= 0 ? 'var(--red)' : 'var(--green)' }}>{er - pi >= 0 ? '+' : ''}{fmtBp(er - pi)}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </div>
        </section>

        {/* L3 权重与归因 */}
        <section className="section" data-step={t('第三层')} id="weights">
          <h2>{t('最终权重与归因')}</h2>
          <p className="section-sub">{t('先看中国投资者视角汇总，再下钻到 27 个明细资产。')}</p>
          <div>
            <div className="group-title">{t('两层合成 · Risk Parity 战略底仓 + Black-Litterman Model 战术偏离 = 目标')}</div>
            <div className="row-stack">
              {bundle.display_buckets.map((b) => {
                const delta = target[b.id] - prior[b.id]
                const stance = bundle.bucket_stances[b.id]
                return (
                  <div key={b.id} className="weight-row" data-bucket={b.id} style={{ ['--asset-color' as string]: b.color }}>
                    <div className="weight-heading">
                      <b style={{ color: b.color }}>{t(b.label)}</b>
                      {stance && <span className={`stance-badge ${STANCE_TONE[stance]}`}>{t(stance)}</span>}
                    </div>
                    <div className="barline">
                      <div className="bar" title={`${t('战略底仓')} ${fmtPct(prior[b.id])}`}><span style={{ width: `${prior[b.id] * 100}%`, opacity: 0.45 }}></span></div>
                      <div className="bar" title={`${t('目标')} ${fmtPct(target[b.id])}`}><span style={{ width: `${target[b.id] * 100}%` }}></span></div>
                    </div>
                    <div className="weight-numbers">
                      <span>{t('底仓')} <b>{fmtPct(prior[b.id])}</b></span>
                      <span>{tf('战术', 'Tilt')} <b>{fmtPp(delta)}</b></span>
                      <span>{t('目标')} <b>{fmtPct(target[b.id])}</b></span>
                    </div>
                  </div>
                )
              })}
            </div>

            <div className="group-title">{t('汇总桶下钻 · 底层标的')}</div>
            <div className="bucket-drilldown">
              {bundle.display_buckets.map((b, index) => {
                const bucketAssets = bundle.assets.filter((a) => a.bucket === b.id)
                return (
                  <details key={b.id} className="asset-drill" style={{ ['--asset-color' as string]: b.color }} open={index === 0}>
                    <summary>
                      <span className="drill-title" style={{ color: b.color }}>{t(b.label)}</span>
                      <span className="weight-meta">{bucketAssets.length}{t('个标的 · ')}{fmtPct(target[b.id])}</span>
                    </summary>
                    <div className="underlying-list">
                      <div className="underlying-head"><span>{t('标的')}</span><span>{t('底仓')}</span><span>{t('目标')}</span><span>{t('变化')}</span></div>
                      {bucketAssets.map((a) => (
                        <div key={a.id} className="underlying-row">
                          <span className="asset-name" title={a.name}>{a.name}</span>
                          <span className="num">{fmtPct(a.prior)}</span>
                          <span className="num"><b>{fmtPct(a.target)}</b></span>
                          <span className="num" style={{ color: a.target - a.prior >= 0 ? 'var(--red)' : 'var(--green)' }}>{fmtPp(a.target - a.prior)}</span>
                        </div>
                      ))}
                      {(() => {
                        const sumTarget = bucketAssets.reduce((s, a) => s + a.target, 0)
                        const ok = Math.abs(sumTarget - target[b.id]) < 1e-6
                        return (
                          <div className="underlying-row" style={{ borderTop: '1px solid var(--line-strong)', fontWeight: 600 }}>
                            <span className="asset-name">{t('桶内标的加总')}</span>
                            <span className="num"></span>
                            <span className="num"><b>{fmtPct(sumTarget)}</b></span>
                            <span className="num" style={{ color: ok ? 'var(--green)' : 'var(--red)' }}>
                              {ok ? t('✓ 等于桶目标') : t('✗ 与桶目标不符')} {fmtPct(target[b.id])}
                            </span>
                          </div>
                        )
                      })()}
                    </div>
                  </details>
                )
              })}
            </div>

            <div className="group-title">{t('观点贡献归因 · 按汇总桶展开')}</div>
            {(() => {
              // V3 §5.5：归因默认只展开影响最大的一个桶
              const deltas = bundle.display_buckets.map((b) => {
                const parts = bundle.attribution[b.id] ?? {}
                const total = Object.values(parts).reduce((s, x) => s + x, 0)
                return Math.abs(total - (parts.prior ?? 0))
              })
              const maxIdx = deltas.indexOf(Math.max(...deltas))
              return bundle.display_buckets.map((b, index) => {
              const parts = bundle.attribution[b.id] ?? {}
              const total = Object.values(parts).reduce((s, x) => s + x, 0)
              const delta = total - (parts.prior ?? 0)
              return (
                <details key={b.id} className="attrib-drill" style={{ ['--asset-color' as string]: b.color }} open={index === maxIdx}>
                  <summary>
                    <span style={{ color: b.color }}>{t(b.label)}</span>
                    <span className="weight-meta">{t('目标')} {fmtPct(total)}</span>
                    <span className="attrib-delta" style={{ color: delta >= 0 ? 'var(--red)' : 'var(--green)' }}>{fmtPp(delta)}</span>
                  </summary>
                  <div className="attrib-parts">
                    {Object.entries(parts).map(([key, value]) => {
                      if (key === 'prior') return <span key={key} className="part prior">{t('战略底仓')} {fmtPct(value)}</span>
                      if (key === 'guardrail') {
                        return <span key={key} className="part" style={{ ['--method-color' as string]: 'var(--slate)' }} title={tf('风控投影产生的裁剪量', 'Clipping from the risk projection')}><span className="part-method">{t('风控投影')}</span> {fmtPp(value)}</span>
                      }
                      const view = viewById(key)
                      const methodId = view ? viewMethodId(view) : 'black_litterman'
                      return (
                        <button key={key} className={`part ${value >= 0 ? 'positive' : 'negative'} ${selection.viewId === key ? 'selected' : ''}`}
                          style={{ ['--method-color' as string]: METHOD_INFO[methodId].color }}
                          onClick={() => openAttribution(b.id, key)}>
                          <span className="part-method">{METHOD_INFO[methodId].name}</span> · {view?.label ?? key} {fmtPp(value)}
                        </button>
                      )
                    })}
                  </div>
                </details>
              )
              })
            })()}
          </div>
        </section>
      </section>

      {/* ===== 委员会正反检验（规则抽取，无 LLM） ===== */}
      <section className="panel" style={{ marginTop: 18 }}>
        <h2>{t('委员会正反检验')}</h2>
        <p className="section-sub">{t('正反论据由规则从决策记录确定性抽取，每条可回跳血缘；无 LLM 参与。')}</p>
        <div className={`check ${bundle.committee_review.verdict.result === 'blocked' ? 'warn' : ''}`}
          style={{ marginBottom: 12 }}>
          <b>{bundle.committee_review.verdict.result === 'clean_pass' ? t('通过质询')
            : bundle.committee_review.verdict.result === 'blocked' ? t('不予放行') : t('有保留通过')}</b>
          <span>{bundle.committee_review.verdict.text}</span>
        </div>
        <RiskPerspectiveCards perspectives={bundle.committee_review.risk_perspectives} />
        <div className="committee-grid">
          {bundle.committee_review.challenges.slice(0, committeeExpanded ? undefined : 6).map((c) => (
            <details key={c.id} className="attrib-drill" style={{ ['--asset-color' as string]: 'var(--rose)' }}>
              <summary>
                <span style={{ color: 'var(--rose)' }}>{t('质疑')}</span>
                <span className="weight-meta" style={{ flex: 1, textAlign: 'left', whiteSpace: 'normal' }}>{c.text}</span>
              </summary>
              <div style={{ padding: '8px 10px', fontSize: 12.5, lineHeight: 1.7 }}>
                <b style={{ color: 'var(--method-risk-parity)' }}>{t('回应')}</b>：{c.response.text}
                {typeof c.refs.view_id === 'string' && (
                  <button className="text-btn" style={{ marginLeft: 8 }}
                    onClick={() => openView(c.refs.view_id as string)}>{t('查看该观点血缘')}</button>
                )}
              </div>
            </details>
          ))}
        </div>
        {bundle.committee_review.challenges.length > 6 && (
          <div className="table-actions">
            <span className="small">{t('共')} {bundle.committee_review.challenges.length} {t('条质询')}</span>
            <button className="text-btn" onClick={() => setCommitteeExpanded((v) => !v)}>
              {committeeExpanded ? t('收起') : t('展开全部质询')}
            </button>
          </div>
        )}
      </section>

      {/* ===== 底部附录 ===== */}
      <section className="bottom-appendix">
        <section className="panel appendix-panel">
          <h2>{tf('明细资产权重', 'Asset Weights')} · {bundle.assets.length}{tf(' 项', '')}</h2>
          <p className="section-sub">{t('完整保留全部明细资产，用于复核汇总权重与变动。')}</p>
          <div className="detail-table">
            <table>
              <thead><tr><th>{t('资产')}</th><th>{t('汇总桶')}</th><th className="num">{t('先验')}</th><th className="num">{t('目标')}</th><th className="num">{t('变化')}</th></tr></thead>
              <tbody>
                {(detailExpanded ? bundle.assets : bundle.assets.slice(0, 9)).map((a) => (
                  <tr key={a.id}>
                    <td>{a.name}</td>
                    <td style={{ color: bucketById[a.bucket].color }}>{t(bucketById[a.bucket].label)}</td>
                    <td className="num">{fmtPct(a.prior)}</td>
                    <td className="num">{fmtPct(a.target)}</td>
                    <td className="num" style={{ color: a.target - a.prior >= 0 ? 'var(--red)' : 'var(--green)' }}>{fmtPp(a.target - a.prior)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="table-actions">
            <span className="small">{detailExpanded ? t('已显示全部明细资产。') : `${t('已隐藏')}${bundle.assets.length - 9}${t('个明细资产。')}`}</span>
            <button className="text-btn" onClick={() => setDetailExpanded((v) => !v)}>{detailExpanded ? t('收起明细') : t('显示全部明细')}</button>
          </div>
        </section>
        <section className="panel appendix-panel guardrail-panel">
          <h2>{t('风控闸门')}</h2>
          <p className="section-sub">{t('展示硬约束规则的触发状态，用于复核最终目标权重。')}</p>
          <div className="checks">
            {bundle.guardrail_actions.map((a) => (
              <div key={a.rule} className={`check ${a.triggered ? 'warn' : ''}`}>
                <b>{a.triggered ? t('触发') : t('通过')}</b>
                <span title={`${tf('规则编号：', 'Rule ID: ')}${a.rule}`}>
                  <span className="check-name">{t(a.label)}</span><br />
                  <span className="small">{a.detail}</span>
                </span>
              </div>
            ))}
          </div>
        </section>
      </section>

      <p className="footnote">{t('Demo 演示数据 · 所有数字由后端确定性代码从数据快照计算，前端只读展示 · 非投资建议')}</p>

      {/* ===== 血缘抽屉 ===== */}
      <aside className={`drawer ${drawer ? 'open' : ''}`} aria-live="polite">
        <div className="drawer-head">
          <div>
            <p className="label">{drawer?.kind ?? t('溯源')}</p>
            <h3 className="drawer-title">{drawer?.title ?? t('血缘详情')}</h3>
          </div>
          <button className="icon-btn" title={t('关闭')} aria-label={t('关闭')} onClick={closeAll}>×</button>
        </div>
        <div className="drawer-body">{drawer?.body}</div>
      </aside>

      {/* ===== 技术工作台 ===== */}
      <div className={`modal ${modalOpen ? 'open' : ''}`} role="dialog" aria-modal="true" aria-label="Black-Litterman Model 技术细节"
        onClick={(e) => { if ((e.target as HTMLElement).classList.contains('modal')) setModalOpen(false) }}>
        <div className="modal-card">
          <div className="modal-head">
            <div>
              <div className="label">{t('Black-Litterman Model 技术工作台')}</div>
              <b>{t('观点矩阵、计算过程与完整血缘')}</b>
            </div>
            <div className="modal-head-actions">
              <div className="modal-tabs" role="tablist" aria-label="技术细节视图">
                <button className={`tab-btn ${modalTab === 'matrix' ? 'active' : ''}`} role="tab" aria-selected={modalTab === 'matrix'}
                  onClick={() => { setModalTab('matrix'); setFocusViewId('') }}>{t('观点矩阵')}</button>
                <button className={`tab-btn ${modalTab === 'trace' ? 'active' : ''}`} role="tab" aria-selected={modalTab === 'trace'}
                  onClick={() => setModalTab('trace')}>{t('计算过程与溯源')}</button>
              </div>
              <button className="icon-btn" title={t('关闭')} aria-label={t('关闭')} onClick={() => setModalOpen(false)}>×</button>
            </div>
          </div>
          <div className="modal-body">
            {modalOpen && modalTab === 'matrix' && (
              <WideMatrix bundle={bundle} assetOrder={assetOrder} assetById={assetById} bucketById={bucketById}
                viewMethodId={viewMethodId}
                onTraceRow={(viewId) => { setModalTab('trace'); setFocusViewId(viewId) }} />
            )}
            {modalOpen && modalTab === 'trace' && (
              <TraceDetails bundle={bundle} focusViewId={focusViewId} viewMethodId={viewMethodId}
                viewBucketIds={viewBucketIds} contribution={contribution} assetById={assetById} bucketById={bucketById} />
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

// ---------- 子组件 ----------

function RiskPerspectiveCards({ perspectives }: { perspectives: CommitteeRiskPerspective[] }) {
  const ordered = (['aggressive', 'conservative', 'neutral'] as const).flatMap((role) => {
    const item = perspectives.find((perspective) => perspective.role === role)
    return item ? [item] : []
  })
  return (
    <section className="risk-perspective-block" data-testid="risk-perspectives">
      <div className="risk-perspective-title">
        <div>
          <h3>{t('风控三视角点评')}</h3>
          <p className="small">{t('同一组后端风控事实，由三种立场分别复核；点评不改变权重或裁决。')}</p>
        </div>
        <span className="risk-perspective-basis">{t('确定性规则直出')}</span>
      </div>
      <div className="risk-perspective-grid">
        {ordered.map((perspective) => {
          const info = RISK_ROLE_INFO[perspective.role]
          const primary = perspective.role === 'conservative'
            ? fmtPp(perspective.value, 2)
            : fmtPct(perspective.value, 1)
          return (
            <article key={perspective.id} className="risk-perspective-card"
              data-role={perspective.role} data-metric={perspective.metric}
              data-value={String(perspective.value)}>
              <div className="risk-perspective-card-head">
                <div>
                  <span className="risk-persona">{t(info.label)}</span>
                  <div className="risk-focus">{t(info.focus)}</div>
                </div>
                <span className="risk-assessment">{t(RISK_ASSESSMENT_LABEL[perspective.assessment])}</span>
              </div>
              <div className="risk-primary"><strong>{primary}</strong><span>{t(info.focus)}</span></div>
              <div className="risk-facts">
                {perspective.role === 'aggressive' && (
                  <>
                    <RiskFact label={t('组合事前波动')} value={fmtPct(perspective.metrics.portfolio_vol, 2)} />
                    <RiskFact label={t('目标波动')} value={fmtPct(perspective.metrics.target_vol, 2)} />
                    <RiskFact label={t('预算绝对余量')} value={fmtPp(perspective.metrics.remaining_vol, 2)} />
                  </>
                )}
                {perspective.role === 'conservative' && (
                  <>
                    <RiskFact label={t('最近有效上限')} value={t(perspective.metrics.subject)} />
                    <RiskFact label={t('当前占用')} value={fmtPct(perspective.metrics.current, 2)} />
                    <RiskFact label={t('约束上限')} value={fmtPct(perspective.metrics.limit, 2)} />
                  </>
                )}
                {perspective.role === 'neutral' && (
                  <>
                    <RiskFact label={t('资产单边换手代理')} value={fmtPct(perspective.metrics.asset_turnover_proxy, 2)} />
                    <RiskFact label={t('桶级净偏离')} value={fmtPct(perspective.metrics.bucket_shift, 2)} />
                    <RiskFact label={t('桶内调整代理')} value={fmtPct(perspective.metrics.intra_bucket_churn, 2)} />
                  </>
                )}
              </div>
              <p className="risk-perspective-text">{perspective.text}</p>
              {perspective.role === 'neutral' && (
                <p className="risk-perspective-note">{t('换手代理，非实际成交')}</p>
              )}
            </article>
          )
        })}
      </div>
    </section>
  )
}

function RiskFact({ label, value }: { label: string; value: string }) {
  return <div className="risk-fact"><span>{label}</span><b>{value}</b></div>
}

function MethodBadge({ methodId, compact = false }: { methodId: string; compact?: boolean }) {
  const method = METHOD_INFO[methodId] ?? { name: methodId, color: 'var(--teal)' }
  return <span className={`method-badge ${compact ? 'compact' : ''}`} style={{ ['--method-color' as string]: method.color }}>{method.name}</span>
}

function Kv({ k, v }: { k: string; v: string }) {
  return <div className="kv"><div className="k">{k}</div><div>{v}</div></div>
}

function CompactP({ view, assetById, bucketId = '', limit = Infinity }: {
  view: BLView; assetById: Record<string, { name: string; bucket: string }>; bucketId?: string; limit?: number
}) {
  const entries = Object.entries(view.P).filter(([aid]) => !bucketId || assetById[aid]?.bucket === bucketId)
  const shown = entries.slice(0, limit)
  const hidden = entries.length - shown.length
  return (
    <>
      {shown.map(([aid, exposure]) => (
        <span key={aid} className="matrix-chip">{assetById[aid]?.name ?? aid} {exposure > 0 ? '+' : ''}{exposure}</span>
      ))}
      {hidden > 0 && <span className="matrix-chip">+{hidden} 项</span>}
    </>
  )
}

function SignalCard({ signal, bucketById, selected, onOpen }: {
  signal: TracedSignal
  bucketById: Record<string, { label: string }>
  selected: boolean
  onOpen: () => void
}) {
  const method = METHOD_INFO[signal.method]
  const valueLabel = (key: string) => t(SIGNAL_VALUE_LABELS[key] ?? bucketById[key]?.label ?? key)
  const valueText = (key: string, value: number | string): string => {
    if (key === 'regime') return t(String(value))
    if (typeof value !== 'number') return String(value)
    if (signal.view_type === 'risk_budget' || ['probability', 'percentile', 'gap'].includes(key)) return fmtPct(value)
    if (value === 1) return t('看多')
    if (value === -1) return t('看空')
    if (value === 0) return t('中性')
    return String(value)
  }
  return (
    <article className={`signal-card ${selected ? 'selected' : ''}`} style={{ ['--accent' as string]: method.color }}
      role="button" tabIndex={0} onClick={onOpen}
      onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onOpen() } }}>
      <div className="card-head">
        <div>
          <div className="method">{method.name}</div>
          <div className="card-subline">{t(LAYER_LABELS[signal.layer] ?? signal.layer)} · {t(VIEW_TYPE_LABELS[signal.view_type] ?? signal.view_type)}</div>
        </div>
        <div className="confidence">
          <span>{t('置信度')}</span><b>{fmtPct(signal.confidence)}</b>
          <div className="mini-track"><span style={{ width: `${signal.confidence * 100}%` }}></span></div>
        </div>
      </div>
      <div className="chips">
        {Object.entries(signal.values).map(([key, value]) => {
          let cls = 'neutral'
          if (typeof value === 'number' && value > 0) cls = 'up'
          if (typeof value === 'number' && value < 0) cls = 'down'
          return <span key={key} className={`chip ${cls}`}>{valueLabel(key)} {valueText(key, value)}</span>
        })}
        {(signal.abstain ?? []).map((bid) => (
          <span key={bid} className="chip abstain">{t(bucketById[bid]?.label ?? bid)} {t('弃权')}</span>
        ))}
      </div>
      <div className="rationale">{signal.rationale}</div>
    </article>
  )
}

function SignalDetails({ signal }: { signal: TracedSignal }) {
  return (
    <>
      <MethodBadge methodId={signal.method} />
      <Kv k={t('信号ID')} v={signal.signal_id} />
      <Kv k={t('方法')} v={METHOD_INFO[signal.method].name} />
      <Kv k={t('层级')} v={t(LAYER_LABELS[signal.layer] ?? signal.layer)} />
      <Kv k={t('观点类型')} v={t(VIEW_TYPE_LABELS[signal.view_type] ?? signal.view_type)} />
      <Kv k={t('置信度')} v={fmtPct(signal.confidence)} />
      <Kv k={t('专家版本')} v={`${signal.agent_id} / ${signal.agent_version}`} />
      <Kv k={t('代码版本')} v={signal.code_version} />
      <Kv k={t('来源引用')} v={signal.source_refs.join(', ')} />
      <div className="codebox">{JSON.stringify({
        values: signal.values, abstain: signal.abstain, params: signal.params,
        inputs: signal.inputs, derivation: signal.derivation,
      }, null, 2)}</div>
    </>
  )
}

function ViewDetails({ view, bundle, methodId, assetById, onOpenTrace }: {
  view: BLView
  bundle: DecisionTraceBundle
  methodId: string
  assetById: Record<string, { name: string }>
  onOpenTrace: () => void
}) {
  const signals = view.source_signal_ids.map((id) => bundle.signals_by_id[id]).filter(Boolean)
  return (
    <>
      <MethodBadge methodId={methodId} />
      <Kv k={t('观点ID')} v={view.view_id} />
      <Kv k={t('来源方法')} v={METHOD_INFO[methodId].name} />
      <Kv k={t('来源信号')} v={view.source_signal_ids.join(', ')} />
      <Kv k={t('观点涉及资产')} v={Object.keys(view.P).map((id) => assetById[id]?.name ?? id).join(' / ')} />
      <Kv k={t('观点收益')} v={fmtBp(view.Q)} />
      <Kv k={t('P 构造')} v={view.P_derivation} />
      <Kv k={t('Q 推导')} v={view.Q_derivation} />
      <Kv k={t('置信度')} v={fmtPct(view.confidence)} />
      <Kv k={t('观点方差')} v={view.view_variance.toExponential(4)} />
      <Kv k={t('不确定性')} v={view.Omega.toExponential(4)} />
      <Kv k={t('权重推力')} v={`${fmtPp(view.lambda)}${view.lambda !== view.lambda_raw ? tf(`（原始 ${fmtPp(view.lambda_raw)}，已按构造纪律调整）`, ` (raw ${fmtPp(view.lambda_raw)}, adjusted by discipline)`) : ''}`} />
      <Kv k={t('推导')} v={view.derivation} />
      <button className="text-btn" type="button" onClick={onOpenTrace}>{t('在技术工作台查看完整计算')}</button>
      <div className="codebox">{JSON.stringify({ P: view.P }, null, 2)}</div>
      <div className="group-title">{t('源信号')}</div>
      {signals.map((s) => <div key={s.signal_id} className="codebox">{s.signal_id}{'\n'}{s.rationale}</div>)}
    </>
  )
}

function WideMatrix({ bundle, assetOrder, assetById, bucketById, viewMethodId, onTraceRow }: {
  bundle: DecisionTraceBundle
  assetOrder: string[]
  assetById: Record<string, { name: string; short_name: string; code: string; bucket: string }>
  bucketById: Record<string, { label: string; color: string }>
  viewMethodId: (v: BLView) => string
  onTraceRow: (viewId: string) => void
}) {
  return (
    <>
      <div className="matrix-intro">
        <span><b>{t('P 矩阵：')}</b>{t('正数表示多头暴露，负数表示空头暴露；绝对观点单腿归一，相对观点的多空两腿分别归一。')}</span>
        <span>{t('行 = ')}{bundle.bl_inputs.views.length}{t('条观点 · 列 = ')}{bundle.assets.length}{tf(' 项明细资产', ' assets')}</span>
      </div>
      <table className="wide-matrix">
        <thead>
          <tr>
            <th className="matrix-row-label" rowSpan={2}>{t('观点 / 资产')}</th>
            {bundle.display_buckets.map((b) => {
              const count = bundle.assets.filter((a) => a.bucket === b.id).length
              return <th key={b.id} className="matrix-bucket-head" colSpan={count} style={{ ['--asset-color' as string]: b.color }}>{t(b.label)} · {count}</th>
            })}
          </tr>
          <tr>
            {assetOrder.map((aid) => {
              const asset = assetById[aid]
              const bucket = bucketById[asset.bucket]
              return (
                <th key={aid} className="matrix-asset-head" title={asset.name} style={{ ['--asset-color' as string]: bucket.color }}>
                  <span className="matrix-asset-name">{asset.short_name}</span>
                  <span className="matrix-asset-code">{asset.code}</span>
                  <span className="matrix-asset-category">{t(bucket.label)}</span>
                </th>
              )
            })}
          </tr>
        </thead>
        <tbody>
          {bundle.bl_inputs.views.map((view) => (
            <tr key={view.view_id}>
              <td className="matrix-row-label">
                <MethodBadge methodId={viewMethodId(view)} compact />
                <div style={{ marginTop: 5 }}><b>{t(view.label)}</b></div>
                <div className="sid">{view.view_id}</div>
                <button className="matrix-trace-link" type="button" onClick={() => onTraceRow(view.view_id)}>{t('查看本行计算')}</button>
              </td>
              {assetOrder.map((aid) => {
                const value = view.P[aid] ?? 0
                return (
                  <td key={aid} style={{ color: value > 0 ? 'var(--red)' : value < 0 ? 'var(--green)' : 'var(--muted)' }}>
                    {value ? `${value > 0 ? '+' : ''}${value}` : ''}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </>
  )
}

function TraceDetails({ bundle, focusViewId, viewMethodId, viewBucketIds, contribution, assetById, bucketById }: {
  bundle: DecisionTraceBundle
  focusViewId: string
  viewMethodId: (v: BLView) => string
  viewBucketIds: (v: BLView) => string[]
  contribution: (bucketId: string, viewId: string) => number
  assetById: Record<string, { name: string; short_name: string }>
  bucketById: Record<string, { label: string; color: string }>
}) {
  useEffect(() => {
    if (!focusViewId) return
    const node = document.getElementById(`trace-${focusViewId}`)
    node?.scrollIntoView({ block: 'center' })
  }, [focusViewId])

  const views = bundle.bl_inputs.views
  const cfg = bundle.config as { risk_aversion?: number; tau?: number; max_view_tilt?: number }
  const delta = Number(cfg.risk_aversion ?? 4.8)
  const tau = Number(cfg.tau ?? 0.05)
  const maxTilt = Number(cfg.max_view_tilt ?? 0.05)

  // 本批次代入值（全部来自 DecisionRecord，前端只做展示换算）
  const anchorOf = (v: BLView) => Object.entries(v.P).reduce((s, [aid, w]) => s + w * (bundle.prior.pi[aid] ?? 0), 0)
  const adopted = views.filter((v) => v.lambda !== 0)
  const cappedViews = views.filter((v) => v.lambda !== 0 && Math.abs(v.lambda) < Math.abs(v.lambda_raw))
  const rejectedViews = views.filter((v) => v.lambda === 0 && v.lambda_raw !== 0)
  const piValues = Object.values(bundle.prior.pi_buckets)
  const confValues = views.map((v) => v.confidence)
  const guardrailShift = Object.values(bundle.attribution)
    .reduce((s, parts) => s + Math.abs(parts.guardrail ?? 0), 0)
  const triggeredRules = bundle.guardrail_actions.filter((a) => a.triggered)
  const methodCount = (m: string) => views.filter((v) => viewMethodId(v) === m).length
  const lamScale = Math.max(maxTilt, ...views.map((v) => Math.abs(v.lambda)), 1e-6)

  const steps = [
    {
      no: '壹', stage: t('立本'), color: 'var(--method-risk-parity)',
      title: t('Risk Parity 反推战略先验'),
      body: t('先由协方差与四大类风险预算得到战略底仓，再反向求隐含均衡收益，作为一切观点的锚。'),
      formula: 'π = δΣw_RP',
      live: <>{t('风险厌恶')} δ = <b>{delta}</b> · {t('桶级先验收益')}<b>{fmtBp(Math.min(...piValues))}</b> ~ <b>{fmtBp(Math.max(...piValues))}</b></>,
    },
    {
      no: '贰', stage: t('集议'), color: 'var(--method-cta)',
      title: t('三专家装配观点议案'),
      body: t('P 定义资产暴露，Q 锚定先验隐含收益再加信号倾斜，置信度经校准映射为不确定性 Ω。'),
      formula: 'Q = P·π + 倾斜 · Ω = ((1−c)/c)·σ²_view',
      live: <>{t('议案')}<b>{views.length}</b>{tf(' 条', '')} · {t('置信度')} <b>{fmtPct(Math.min(...confValues), 0)}</b> ~ <b>{fmtPct(Math.max(...confValues), 0)}</b></>,
    },
    {
      no: '叁', stage: t('合议'), color: 'var(--bl)',
      title: t('Black-Litterman Model 贝叶斯融合'),
      body: t('观点与先验按不确定性加权融合；置信度越低，观点对后验收益与权重推力的话语权越小。'),
      formula: 'μ_BL = π + τΣPᵀ(PτΣPᵀ+Ω)⁻¹(Q−Pπ)',
      live: <>τ = <b>{tau}</b> · {t('采纳')} <b>{adopted.length}</b> · {t('截断')} <b>{cappedViews.length}</b> · {t('未采纳')} <b>{rejectedViews.length}</b></>,
    },
    {
      no: '肆', stage: t('守界'), color: 'var(--rose)',
      title: t('推力合成与风控投影'),
      body: t('按每条观点的权重推力 λ 合成目标，再投影进禁止做空、单资产上限、波动预算与闭合约束。'),
      formula: 'w_target = Project(w_prior + Σλ_kP_k)',
      live: <>{t('单观点推力上限')} ±<b>{fmtPct(maxTilt, 0)}</b> · {t('触发规则')} <b>{triggeredRules.length}</b>{tf(' 条', '')} · {t('风控段合计')}<b>{fmtPp(guardrailShift)}</b></>,
    },
  ]

  return (
    <>
      <p className="trace-note"><b>{t('可复算边界：')}</b>{t('页面展示落库参数、公式关系和完整输入血缘；生产系统由后端确定性代码使用同一 DecisionRecord 复算，前端只读展示，不在浏览器中重新估计协方差或改写权重。')}</p>

      <div className="calc-stats">
        <span className="calc-stat">{t('本批次观点议案')}<b>{views.length}</b>{tf(' 条', '')}</span>
        <span className="calc-stat" style={{ borderColor: 'var(--method-cta)' }}>Time Series Momentum <b>{methodCount('tsmom')}</b></span>
        <span className="calc-stat" style={{ borderColor: 'var(--method-clock)' }}>Merrill Lynch Investment Clock <b>{methodCount('clock')}</b></span>
        <span className="calc-stat" style={{ borderColor: 'var(--method-erp)' }}>Equity Risk Premium <b>{methodCount('erp')}</b></span>
        <span className="calc-stat">{t('采纳')} <b>{adopted.length}</b> · {t('截断')} <b>{cappedViews.length}</b> · {t('未采纳')} <b>{rejectedViews.length}</b></span>
      </div>

      <div className="calc-pipeline">
        {steps.map((s, i) => (
          <article key={s.no} className="calc-step" style={{ ['--step-color' as string]: s.color }}>
            <div className="calc-step-no">{s.no}</div>
            <div className="calc-step-stage">{tf(`第${['一', '二', '三', '四'][i]}步`, `STEP ${i + 1}`)} · {s.stage}</div>
            <h4>{s.title}</h4>
            <p>{s.body}</p>
            <div className="formula-code">{s.formula}</div>
            <div className="calc-step-live">{s.live}</div>
          </article>
        ))}
      </div>

      <div className="group-title">{t('议案逐条复核 · 每条观点的完整算路（暴露 → 收益 → 不确定性 → 推力 → 归因）')}</div>
      <div className="trace-view-list">
        {views.map((view) => {
          const signal = bundle.signals_by_id[view.source_signal_ids[0]]
          const methodId = viewMethodId(view)
          const entries = Object.entries(view.P).sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]))
          const maxExpo = Math.max(...entries.map(([, v]) => Math.abs(v)))
          const positiveSum = entries.reduce((s, [, v]) => s + Math.max(v, 0), 0)
          const negativeSum = entries.reduce((s, [, v]) => s + Math.abs(Math.min(v, 0)), 0)
          const anchor = anchorOf(view)
          const tilt = view.Q - anchor
          const capped = view.lambda !== 0 && Math.abs(view.lambda) < Math.abs(view.lambda_raw)
          const rejected = view.lambda === 0 && view.lambda_raw !== 0
          const shownEntries = entries.slice(0, 6)
          const impacted = viewBucketIds(view)
          const sourceInputs = (signal?.inputs ?? []).map((i) => `${i.data_id} · ${i.asof} · ${i.hash}`).join('；')
          return (
            <article key={view.view_id} id={`trace-${view.view_id}`}
              className={`trace-view-card ${view.view_id === focusViewId ? 'focused' : ''}`}
              style={{ ['--method-color' as string]: METHOD_INFO[methodId].color }}>
              <div className="trace-view-head">
                <div>
                  <MethodBadge methodId={methodId} compact />
                  <div className="trace-view-title">
                    {t(view.label)}
                    {rejected && <span className="calc-badge reject">{t('未采纳')}</span>}
                    {capped && <span className="calc-badge cap">{t('已截断')}</span>}
                    {!rejected && !capped && <span className="calc-badge ok">{t('已采纳')}</span>}
                  </div>
                  <div className="sid">{view.view_id}</div>
                </div>
                <span className="view-impact" style={{ color: view.lambda >= 0 ? 'var(--red)' : 'var(--green)' }}>{fmtPp(view.lambda)}</span>
              </div>

              <div className="trace-line"><b>{t('议题范围')}</b><span>{impacted.map((id) => t(bucketById[id].label)).join(' / ')}</span></div>

              <div className="trace-line"><b>{t('暴露构成 P')}</b>
                <span>
                  {view.P_derivation}
                  <span className="p-expo">
                    {shownEntries.map(([aid, v]) => (
                      <span key={aid} className="p-expo-row">
                        <span className="p-expo-name" title={assetById[aid]?.name ?? aid}>{assetById[aid]?.short_name ?? aid}</span>
                        <span className="bar"><span style={{ width: `${(Math.abs(v) / maxExpo) * 100}%`, background: v >= 0 ? 'var(--red)' : 'var(--green)' }}></span></span>
                        <span className="num" style={{ color: v >= 0 ? 'var(--red)' : 'var(--green)' }}>{v > 0 ? '+' : ''}{v}</span>
                      </span>
                    ))}
                    {entries.length > shownEntries.length && <span className="small">{tf(`…另 ${entries.length - shownEntries.length} 项，完整暴露见观点矩阵`, `… ${entries.length - shownEntries.length} more; see View Matrix`)}</span>}
                  </span>
                  <code>{negativeSum > 0
                    ? `${t('多头腿')} ΣP⁺=${positiveSum.toFixed(3)}；${t('空头腿')} Σ|P⁻|=${negativeSum.toFixed(3)}`
                    : `${t('绝对观点腿')} ΣP=${positiveSum.toFixed(3)}`}</code>
                </span>
              </div>

              <div className="trace-line"><b>{t('观点收益 Q')}</b>
                <span>
                  <span className="q-eq">
                    <span className="q-chip"><small>{t('先验锚 P·π')}</small>{fmtBp(anchor)}</span>
                    <span className="op">+</span>
                    <span className="q-chip" style={{ borderColor: METHOD_INFO[methodId].color }}><small>{t('信号倾斜')}</small>
                      <span style={{ color: tilt >= 0 ? 'var(--red)' : 'var(--green)' }}>{tilt >= 0 ? '+' : ''}{fmtBp(tilt)}</span>
                    </span>
                    <span className="op">=</span>
                    <span className="q-chip total"><small>{t('观点收益 Q')}</small>{fmtBp(view.Q)}</span>
                  </span>
                  <span className="small">{view.Q_derivation}</span>
                </span>
              </div>

              <div className="trace-line"><b>{t('不确定性 Ω')}</b>
                <span>
                  {t('置信度')} <b>{fmtPct(view.confidence, 0)}</b>
                  <span className="conf-track" style={{ ['--method-color' as string]: METHOD_INFO[methodId].color }}><span style={{ width: `${view.confidence * 100}%` }}></span></span>
                  <br />
                  <code>Ω = ((1−{view.confidence.toFixed(2)})/{view.confidence.toFixed(2)}) × {view.view_variance.toExponential(4)} = {view.Omega.toExponential(4)}</code>
                  <span className="small">{t('置信度越低 → Ω 越大 → 该议案在合议中的话语权越小')}</span>
                </span>
              </div>

              <div className="trace-line"><b>{t('权重推力 λ')}</b>
                <span>
                  <span className="lam-scale" title={`${t('推力刻度')} ±${fmtPct(lamScale, 1)}`}>
                    <span className="lam-zero"></span>
                    <span className="lam-fill" style={{
                      left: view.lambda >= 0 ? '50%' : `${50 - (Math.abs(view.lambda) / lamScale) * 50}%`,
                      width: `${(Math.abs(view.lambda) / lamScale) * 50}%`,
                      background: view.lambda >= 0 ? 'var(--red)' : 'var(--green)',
                    }}></span>
                  </span>
                  <code>λ = {fmtPp(view.lambda)}{view.lambda !== view.lambda_raw ? tf(`（He-Litterman 原始 λ = ${fmtPp(view.lambda_raw)}）`, ` (raw He-Litterman λ = ${fmtPp(view.lambda_raw)})`) : ''}</code>
                  {rejected && <span className="small">{t('联合融合中被同资产更强议案支配，按方向纪律未采纳')}</span>}
                  {capped && <span className="small">{t('超出单观点推力上限')} ±{fmtPct(maxTilt, 0)}{t('已按 Idzorek 纪律截断')}</span>}
                </span>
              </div>

              <div className="trace-line"><b>{t('业务判断')}</b><span>{view.derivation}</span></div>

              <div className="trace-line"><b>{t('归因去向')}</b>
                <span>
                  <span className="q-eq">
                    {impacted.map((bid) => {
                      const c = contribution(bid, view.view_id)
                      return (
                        <span key={bid} className="q-chip" style={{ borderColor: bucketById[bid].color }}>
                          <small>{t(bucketById[bid].label)}</small>
                          <span style={{ color: c >= 0 ? 'var(--red)' : 'var(--green)' }}>{fmtPp(c)}</span>
                        </span>
                      )
                    })}
                  </span>
                </span>
              </div>

              <div className="trace-line"><b>{t('来源信号')}</b><span><code>{signal?.signal_id ?? ''}</code><br />{`${signal?.agent_id ?? ''} ${signal?.agent_version ?? ''} · ${signal?.code_version ?? ''}`}<br />{signal?.rationale ?? ''}</span></div>
              <div className="trace-line"><b>{t('输入与指纹')}</b><span>{sourceInputs}</span></div>
            </article>
          )
        })}
      </div>
    </>
  )
}
