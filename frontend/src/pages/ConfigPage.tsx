import { useEffect, useMemo, useState } from 'react'
import type { CSSProperties, ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { api, saveConfig, savedConfig } from '../api'
import { useScenario } from '../scenario'
import { ScenarioPicker } from '../components/Layout'
import { CLASS_META, CLASS_ORDER, fmtAsof, fmtDecisionId, fmtPct, fmtPp } from '../meta'
import { t, tf, usePrefs } from '../prefs'
import type { AllocationConfig, DecisionTraceBundle } from '../types'

// ---------- 本地类型（问卷 fixture 结构以 config_defaults 样例为准，兼容 map/array 两种形态） ----------

interface PQuestion {
  dim?: number
  q: string
  options: string[]
}

interface PType {
  type: string
  type_name: string
  target_vol: number
  max_drawdown: number
  single_asset_cap: number
  bond_floor: number
  rebalance: string
}

interface AssetOption {
  id: string
  name: string
  short_name: string
  bucket: string
}

interface CapRow {
  asset: string
  wan: number
}

const REBALANCE_ZH: Record<string, string> = { weekly: '每周', monthly: '每月', quarterly: '每季度' }

// 16 型四个维度的字母对：每维两题（1-4 分），均值 ≤2.5 判前一字母，否则判后一字母
const DIM_LETTERS: [string, string][] = [
  ['A', 'D'],
  ['L', 'S'],
  ['T', 'C'],
  ['R', 'P'],
]

function normalizeTypes(raw: unknown): PType[] {
  if (Array.isArray(raw)) {
    return (raw as Record<string, unknown>[]).map((v) => ({
      type: String(v.type ?? ''),
      type_name: String(v.type_name ?? v.name ?? v.type ?? ''),
      target_vol: Number(v.target_vol),
      max_drawdown: Number(v.max_drawdown),
      single_asset_cap: Number(v.single_asset_cap),
      bond_floor: Number(v.bond_floor),
      rebalance: String(v.rebalance ?? 'monthly'),
    }))
  }
  if (raw && typeof raw === 'object') {
    return Object.entries(raw as Record<string, Record<string, unknown>>).map(([code, v]) => ({
      type: code,
      type_name: String(v.type_name ?? v.name ?? code),
      target_vol: Number(v.target_vol),
      max_drawdown: Number(v.max_drawdown),
      single_asset_cap: Number(v.single_asset_cap),
      bond_floor: Number(v.bond_floor),
      rebalance: String(v.rebalance ?? 'monthly'),
    }))
  }
  return []
}

function computeTypeCode(questions: PQuestion[], answers: (number | null)[]): string {
  const acc: Record<number, { sum: number; n: number }> = {}
  questions.forEach((q, i) => {
    const dim = q.dim ?? Math.floor(i / 2) + 1
    const a = answers[i]
    if (a === null || a === undefined) return
    const cur = acc[dim] ?? { sum: 0, n: 0 }
    acc[dim] = { sum: cur.sum + (a + 1), n: cur.n + 1 }
  })
  return [1, 2, 3, 4]
    .map((d) => {
      const pair = DIM_LETTERS[d - 1]
      const s = acc[d]
      if (!s || s.n === 0) return pair[0]
      return s.sum / s.n <= 2.5 ? pair[0] : pair[1]
    })
    .join('')
}

// ---------- 共用输入样式 ----------

const inputStyle: CSSProperties = {
  font: 'inherit',
  fontSize: 13,
  padding: '6px 10px',
  border: '1px solid var(--line-strong)',
  borderRadius: 8,
  background: 'var(--paper)',
  color: 'var(--ink)',
  width: '100%',
  boxSizing: 'border-box',
}

const btnStyle: CSSProperties = {
  font: 'inherit',
  fontSize: 13,
  fontWeight: 600,
  padding: '8px 16px',
  borderRadius: 8,
  border: '1px solid var(--line-strong)',
  background: 'var(--paper)',
  color: 'var(--ink)',
  cursor: 'pointer',
}

const primaryBtnStyle: CSSProperties = {
  ...btnStyle,
  background: 'var(--teal)',
  borderColor: 'var(--teal)',
  color: '#fff',
}

function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: 12.5, minWidth: 0 }}>
      <span style={{ color: 'var(--muted)', fontSize: 11.5 }}>{label}</span>
      {children}
      {hint && <span style={{ color: 'var(--muted)', fontSize: 11 }}>{hint}</span>}
    </label>
  )
}

// min/max 与后端 AllocationConfig 的 Field 约束对应，onChange 时夹取到合法区间
function PctField({
  label,
  value,
  onChange,
  step = 0.5,
  hint,
  minPct = 0,
  maxPct = 100,
}: {
  label: string
  value: number
  onChange: (v: number) => void
  step?: number
  hint?: string
  minPct?: number
  maxPct?: number
}) {
  const rangeHint = `${tf('合法范围', 'Valid range')} ${minPct}% ~ ${maxPct}%${hint ? ` · ${hint}` : ''}`
  return (
    <Field label={tf(`${label}（%）`, `${label} (%)`)} hint={rangeHint}>
      <input
        type="number"
        style={inputStyle}
        value={Number((value * 100).toFixed(4))}
        step={step}
        min={minPct}
        max={maxPct}
        onChange={(e) => {
          const n = e.target.valueAsNumber
          if (!Number.isNaN(n)) onChange(Math.min(Math.max(n, minPct), maxPct) / 100)
        }}
      />
    </Field>
  )
}

function NumField({
  label,
  value,
  onChange,
  step = 0.1,
  hint,
  min,
  max,
}: {
  label: string
  value: number
  onChange: (v: number) => void
  step?: number
  hint?: string
  min?: number
  max?: number
}) {
  const bounds = min !== undefined || max !== undefined
    ? `${tf('合法范围', 'Valid range')} ${min ?? '—'} ~ ${max ?? '—'}${hint ? ` · ${hint}` : ''}`
    : hint
  return (
    <Field label={label} hint={bounds}>
      <input
        type="number"
        style={inputStyle}
        value={value}
        step={step}
        min={min}
        max={max}
        onChange={(e) => {
          const n = e.target.valueAsNumber
          if (Number.isNaN(n)) return
          let v = n
          if (min !== undefined) v = Math.max(v, min)
          if (max !== undefined) v = Math.min(v, max)
          onChange(v)
        }}
      />
    </Field>
  )
}

const fieldGrid: CSSProperties = { display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))', gap: 10 }

// ---------- 页面 ----------

export default function ConfigPage() {
  usePrefs() // 订阅语言/主题切换
  const { scenarioId } = useScenario()

  const [defaults, setDefaults] = useState<AllocationConfig | null>(null)
  const [questions, setQuestions] = useState<PQuestion[]>([])
  const [types, setTypes] = useState<PType[]>([])
  const [assets, setAssets] = useState<AssetOption[]>([])
  const [loadErr, setLoadErr] = useState<Error | null>(null)
  const [loading, setLoading] = useState(true)

  const [form, setForm] = useState<AllocationConfig | null>(null)
  const [capRows, setCapRows] = useState<CapRow[]>([])

  const [running, setRunning] = useState(false)
  const [runErr, setRunErr] = useState<Error | null>(null)
  const [result, setResult] = useState<DecisionTraceBundle | null>(null)

  const [answers, setAnswers] = useState<(number | null)[]>([])
  const [myType, setMyType] = useState<PType | null>(null)

  useEffect(() => {
    let cancelled = false
    Promise.all([api.configDefaults(), api.meta()])
      .then(([cfg, meta]) => {
        if (cancelled) return
        const p = cfg.personality as { questionnaire?: PQuestion[]; all_types?: unknown }
        const qs = p?.questionnaire ?? []
        setDefaults(cfg.config)
        setQuestions(qs)
        setTypes(normalizeTypes(p?.all_types))
        setAnswers(new Array(qs.length).fill(null))
        const u = meta.universe as { assets?: AssetOption[] }
        setAssets(u?.assets ?? [])
        const base: AllocationConfig = { ...cfg.config, ...(savedConfig() ?? {}) }
        setForm(base)
        setCapRows(Object.entries(base.risk_caps_wan ?? {}).map(([asset, wan]) => ({ asset, wan: Number(wan) })))
      })
      .catch((e: Error) => {
        if (!cancelled) setLoadErr(e)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  const set = (patch: Partial<AllocationConfig>) => setForm((f) => (f ? { ...f, ...patch } : f))

  const buildConfig = (): AllocationConfig | null =>
    form
      ? {
          ...form,
          risk_caps_wan: Object.fromEntries(capRows.filter((r) => r.asset && r.wan > 0).map((r) => [r.asset, r.wan])),
        }
      : null

  const onRun = async () => {
    const cfg = buildConfig()
    if (!cfg) return
    setRunning(true)
    setRunErr(null)
    setResult(null)
    try {
      const bundle = await api.runDecision(scenarioId, cfg)
      // 只有后端校验通过的配置才持久化，避免非法配置污染其他页面
      saveConfig(cfg)
      setResult(bundle)
    } catch (e) {
      setRunErr(e as Error)
    } finally {
      setRunning(false)
    }
  }

  const onReset = () => {
    if (defaults) {
      setForm({ ...defaults })
      setCapRows(Object.entries(defaults.risk_caps_wan ?? {}).map(([asset, wan]) => ({ asset, wan: Number(wan) })))
    }
    saveConfig(null)
    setResult(null)
    setRunErr(null)
  }

  const allAnswered = answers.length > 0 && answers.every((a) => a !== null)
  const onSubmitQuiz = () => {
    const code = computeTypeCode(questions, answers)
    setMyType(types.find((t) => t.type === code) ?? null)
  }

  const applyType = (t: PType) => {
    set({
      target_vol: t.target_vol,
      max_drawdown_tolerance: t.max_drawdown,
      single_asset_cap: t.single_asset_cap,
      bond_floor: t.bond_floor,
      rebalance: t.rebalance,
    })
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h2>{t('配置')}</h2>
          <p className="page-sub">{t('编辑账户、风险与执行参数，保存后重新执行完整决策计算链路')}</p>
        </div>
        <ScenarioPicker />
      </div>

      {loading && <div className="loading-block">{t('正在加载默认配置…')}</div>}
      {!loading && loadErr && <div className="error-block">{t('加载失败：')}{loadErr.message}</div>}

      {!loading && !loadErr && form && (
        <div className="page-grid">
          <div className="page-grid grid-3">
            <AccountCard form={form} set={set} />
            <ExecutionCard form={form} set={set} />
            <ModelCard form={form} set={set} />
          </div>

          <RiskCard form={form} set={set} />

          <CapsCard capRows={capRows} setCapRows={setCapRows} assets={assets} />

          <ActionCard
            running={running}
            onRun={onRun}
            onReset={onReset}
            runErr={runErr}
          />

          {result && <ResultCard result={result} />}

          <QuizCard
            questions={questions}
            answers={answers}
            setAnswers={setAnswers}
            allAnswered={allAnswered}
            onSubmit={onSubmitQuiz}
            myType={myType}
            form={form}
            applyType={applyType}
          />

          <div className="demo-banner">
            {t('Demo 演示数据 · 非投资建议 · 投资性格问卷为旧版静态页迁移 fixture，仅作展示；其结果只透明映射到风险参数与约束，不改变任何方法的话语权')}
          </div>
        </div>
      )}
    </>
  )
}

// ---------- 分组卡片 ----------

function AccountCard({ form, set }: { form: AllocationConfig; set: (p: Partial<AllocationConfig>) => void }) {
  // 与后端 AllocationConfig.currency 契约一致：^(CNY|USD)$
  const currencies = ['CNY', 'USD']
  return (
    <div className="app-card">
      <h3>{t('账户')}</h3>
      <div style={fieldGrid}>
        <NumField
          label={t('本金（万元）')}
          value={Number((form.principal / 10000).toFixed(2))}
          step={100}
          onChange={(v) => set({ principal: v * 10000 })}
          hint={tf(`即 ${form.principal.toLocaleString('zh-CN')} 元`, `i.e. ${form.principal.toLocaleString('en-US')} yuan`)}
        />
        <Field label={t('计价币种')}>
          <select style={inputStyle} value={form.currency} onChange={(e) => set({ currency: e.target.value })}>
            {currencies.map((c) => (
              <option key={c} value={c}>{c}</option>
            ))}
          </select>
        </Field>
      </div>
    </div>
  )
}

function ExecutionCard({ form, set }: { form: AllocationConfig; set: (p: Partial<AllocationConfig>) => void }) {
  return (
    <div className="app-card">
      <h3>{t('执行')}</h3>
      <div style={fieldGrid}>
        <Field label={t('调仓频率')}>
          <select style={inputStyle} value={form.rebalance} onChange={(e) => set({ rebalance: e.target.value })}>
            <option value="weekly">{t('每周')}</option>
            <option value="monthly">{t('每月')}</option>
            <option value="quarterly">{t('每季度')}</option>
          </select>
        </Field>
        <PctField label={t('免动带')} value={form.no_trade_band} step={0.1} minPct={0} maxPct={10} onChange={(v) => set({ no_trade_band: v })} hint={t('漂移低于此值不交易')} />
        <NumField label={t('单边成本（基点）')} value={form.cost_bps_per_side} step={1} min={0} max={200} onChange={(v) => set({ cost_bps_per_side: v })} />
      </div>
    </div>
  )
}

function ModelCard({ form, set }: { form: AllocationConfig; set: (p: Partial<AllocationConfig>) => void }) {
  return (
    <div className="app-card">
      <h3>{t('模型参数')}</h3>
      <details>
        <summary style={{ cursor: 'pointer', fontSize: 12.5, color: 'var(--muted)' }}>{t('高级参数（一般无需调整）')}</summary>
        <div style={{ ...fieldGrid, marginTop: 10 }}>
          <NumField label={t('风险厌恶系数 δ')} value={form.risk_aversion} step={0.1} min={0.5} max={20} onChange={(v) => set({ risk_aversion: v })} />
          <NumField label={t('先验不确定性 τ')} value={form.tau} step={0.01} min={0.01} max={1} onChange={(v) => set({ tau: v })} />
          <PctField label={t('单观点最大倾斜')} value={form.max_view_tilt} step={0.5} minPct={1} maxPct={30} onChange={(v) => set({ max_view_tilt: v })} />
          <NumField label={t('协方差窗口（交易日）')} value={form.cov_window_days} step={21} min={120} max={1260} onChange={(v) => set({ cov_window_days: Math.round(v) })} />
          <NumField label={t('协方差收缩系数')} value={form.shrinkage} step={0.05} min={0} max={1} onChange={(v) => set({ shrinkage: v })} />
        </div>
      </details>
    </div>
  )
}

function RiskCard({ form, set }: { form: AllocationConfig; set: (p: Partial<AllocationConfig>) => void }) {
  return (
    <div className="app-card">
      <h3>{t('风险与约束')}</h3>
      <div style={fieldGrid}>
        <PctField label={t('目标波动率')} value={form.target_vol} minPct={1} maxPct={40} onChange={(v) => set({ target_vol: v })} />
        <PctField label={t('最大回撤容忍')} value={form.max_drawdown_tolerance} minPct={1} maxPct={80} onChange={(v) => set({ max_drawdown_tolerance: v })} />
        <PctField label={t('单一资产上限')} value={form.single_asset_cap} minPct={1} maxPct={100} onChange={(v) => set({ single_asset_cap: v })} />
        <PctField label={t('中国股票桶上限')} value={form.cn_equity_cap} minPct={1} maxPct={100} onChange={(v) => set({ cn_equity_cap: v })} />
        <PctField label={t('权益大类上限')} value={form.equity_class_cap} minPct={1} maxPct={100} onChange={(v) => set({ equity_class_cap: v })} />
        <PctField label={t('债券底仓下限')} value={form.bond_floor} minPct={0} maxPct={80} onChange={(v) => set({ bond_floor: v })} />
        <PctField label={t('现金下限')} value={form.cash_floor} minPct={0} maxPct={50} onChange={(v) => set({ cash_floor: v })} />
      </div>
    </div>
  )
}

function CapsCard({
  capRows,
  setCapRows,
  assets,
}: {
  capRows: CapRow[]
  setCapRows: (rows: CapRow[]) => void
  assets: AssetOption[]
}) {
  const usedIds = new Set(capRows.map((r) => r.asset))
  const firstUnused = assets.find((a) => !usedIds.has(a.id))

  return (
    <div className="app-card">
      <h3>{t('明细资产风险敞口上限（万元）')}</h3>
      <p style={{ margin: '0 0 10px', fontSize: 12, color: 'var(--muted)' }}>
        {t('对单个明细资产设置绝对金额上限，随配置一并传入决策引擎；未列出的资产不设额外上限。')}
      </p>
      {capRows.length === 0 && (
        <div style={{ fontSize: 12.5, color: 'var(--muted)', marginBottom: 10 }}>{t('暂无明细上限，点击下方按钮新增。')}</div>
      )}
      <div style={{ display: 'grid', gap: 8, maxWidth: 560 }}>
        {capRows.map((row, i) => (
          <div key={i} style={{ display: 'grid', gridTemplateColumns: 'minmax(0,1fr) 130px 60px', gap: 8, alignItems: 'center' }}>
            <select
              style={inputStyle}
              value={row.asset}
              onChange={(e) => setCapRows(capRows.map((r, j) => (j === i ? { ...r, asset: e.target.value } : r)))}
            >
              {assets
                .filter((a) => a.id === row.asset || !usedIds.has(a.id))
                .map((a) => (
                  <option key={a.id} value={a.id}>{a.name}</option>
                ))}
            </select>
            <input
              type="number"
              style={inputStyle}
              value={row.wan}
              min={0}
              step={100}
              onChange={(e) => {
                const n = e.target.valueAsNumber
                if (!Number.isNaN(n)) setCapRows(capRows.map((r, j) => (j === i ? { ...r, wan: n } : r)))
              }}
            />
            <button type="button" style={{ ...btnStyle, padding: '6px 10px', fontWeight: 400 }} onClick={() => setCapRows(capRows.filter((_, j) => j !== i))}>
              {t('删除')}
            </button>
          </div>
        ))}
      </div>
      <button
        type="button"
        style={{ ...btnStyle, marginTop: 10, fontWeight: 400 }}
        disabled={!firstUnused}
        onClick={() => firstUnused && setCapRows([...capRows, { asset: firstUnused.id, wan: 500 }])}
      >
        {t('＋ 新增一行')}
      </button>
    </div>
  )
}

function ActionCard({
  running,
  onRun,
  onReset,
  runErr,
}: {
  running: boolean
  onRun: () => void
  onReset: () => void
  runErr: Error | null
}) {
  return (
    <div className="app-card">
      <h3>{t('重新计算')}</h3>
      <p style={{ margin: '0 0 10px', fontSize: 12, color: 'var(--muted)' }}>
        {t('保存当前配置后重新执行完整决策链路：数据输入 → 四方法信号 → 观点 → Black-Litterman Model 整合 → 风控投影。')}
      </p>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, alignItems: 'center' }}>
        <button type="button" style={{ ...primaryBtnStyle, opacity: running ? 0.6 : 1 }} disabled={running} onClick={onRun}>
          {running ? t('正在执行完整计算链路…') : t('保存配置并重新计算')}
        </button>
        <button type="button" style={btnStyle} disabled={running} onClick={onReset}>
          {t('恢复默认')}
        </button>
        {running && <span style={{ fontSize: 12.5, color: 'var(--muted)' }}>{t('正在执行完整计算链路，请稍候…')}</span>}
      </div>
      {runErr && <div className="error-block" style={{ padding: '14px 0 0', textAlign: 'left' }}>{t('计算失败：')}{runErr.message}</div>}
    </div>
  )
}

function ResultCard({ result }: { result: DecisionTraceBundle }) {
  const triggered = result.guardrail_actions.filter((g) => g.triggered)
  const maxW = Math.max(
    ...CLASS_ORDER.map((id) => Math.max(result.class_weights[id] ?? 0, result.prior.class_weights[id] ?? 0)),
    0.0001,
  )
  return (
    <div className="app-card" style={{ borderColor: 'var(--teal)' }}>
      <h3>
        {t('计算完成')} <span className="status-ok" style={{ fontSize: 12 }}>✓ {t('新决策已生成')}</span>
      </h3>
      <div style={{ fontSize: 13, marginBottom: 4 }}>
        {fmtDecisionId(result.decision_id)} · {fmtAsof(result.asof)} · {t('引擎耗时')}{' '}
        <span className="mono">{result.engine_runtime_ms.toFixed(1)}ms</span>
      </div>
      <div className="mono" style={{ color: 'var(--muted)', marginBottom: 12, overflowWrap: 'anywhere' }}>{result.decision_id}</div>

      <div style={{ fontSize: 11.5, color: 'var(--muted)', marginBottom: 6 }}>
        {t('五大类权重（上粗条为新目标，下细条为战略底仓，同一长度基准）')}
      </div>
      <div style={{ display: 'grid', gap: 8, maxWidth: 640, marginBottom: 12 }}>
        {CLASS_ORDER.map((id) => {
          const meta = CLASS_META[id]
          const w = result.class_weights[id] ?? 0
          const prior = result.prior.class_weights[id] ?? 0
          const d = w - prior
          const flat = Math.abs(d) < 0.001
          return (
            <div key={id} style={{ display: 'grid', gridTemplateColumns: '52px minmax(0,1fr) 190px', gap: 10, alignItems: 'center' }}>
              <div style={{ fontSize: 12.5 }}>{t(meta.label)}</div>
              <div title={tf(`${meta.label}：战略底仓 ${fmtPct(prior)} → 目标 ${fmtPct(w)}`, `${t(meta.label)}: strategic base ${fmtPct(prior)} → target ${fmtPct(w)}`)}>
                <div style={{ width: `${(w / maxW) * 100}%`, height: 10, borderRadius: 3, background: meta.color, marginBottom: 3 }} />
                <div style={{ width: `${(prior / maxW) * 100}%`, height: 5, borderRadius: 3, background: meta.color, opacity: 0.35 }} />
              </div>
              <div style={{ fontSize: 11.5, color: 'var(--muted)', fontVariantNumeric: 'tabular-nums' }}>
                {fmtPct(prior)} → <span style={{ color: 'var(--ink)', fontWeight: 600 }}>{fmtPct(w)}</span>{' '}
                {flat ? <span>{t('≈ 持平')}</span> : (
                  <span className={d > 0 ? 'pos' : 'neg'}>
                    {d > 0 ? '↑' : '↓'} {fmtPp(d)}
                  </span>
                )}
              </div>
            </div>
          )
        })}
      </div>

      <p style={{ margin: '0 0 10px', fontSize: 13, lineHeight: 1.7 }}>{result.conclusion}</p>

      <div style={{ fontSize: 11.5, color: 'var(--muted)', marginBottom: 4 }}>{t('风控触发情况')}</div>
      {triggered.length === 0 ? (
        <div className="status-ok" style={{ fontSize: 12.5, marginBottom: 10 }}>✓ {t('风控全部通过')}</div>
      ) : (
        <ul style={{ margin: '0 0 10px', paddingLeft: 18, fontSize: 12.5, display: 'grid', gap: 4 }}>
          {triggered.map((g) => (
            <li key={g.rule}>
              <span className="status-warn">⚠ {t(g.label)}</span>
              <span style={{ color: 'var(--muted)' }}> — {g.detail}</span>
            </li>
          ))}
        </ul>
      )}

      <Link to="/trace" style={{ fontSize: 13, fontWeight: 600, color: 'var(--bl)' }}>
        {t('前往决策溯源，查看这次计算的完整三层链路 →')}
      </Link>
    </div>
  )
}

function QuizCard({
  questions,
  answers,
  setAnswers,
  allAnswered,
  onSubmit,
  myType,
  form,
  applyType,
}: {
  questions: PQuestion[]
  answers: (number | null)[]
  setAnswers: (a: (number | null)[]) => void
  allAnswered: boolean
  onSubmit: () => void
  myType: PType | null
  form: AllocationConfig
  applyType: (t: PType) => void
}) {
  const paramRows = useMemo(
    () =>
      myType
        ? [
            { label: '目标波动率', typeVal: fmtPct(myType.target_vol, 2), curVal: fmtPct(form.target_vol, 2) },
            { label: '最大回撤容忍', typeVal: fmtPct(myType.max_drawdown, 2), curVal: fmtPct(form.max_drawdown_tolerance, 2) },
            { label: '单一资产上限', typeVal: fmtPct(myType.single_asset_cap), curVal: fmtPct(form.single_asset_cap) },
            { label: '债券底仓下限', typeVal: fmtPct(myType.bond_floor), curVal: fmtPct(form.bond_floor) },
            {
              label: '调仓频率',
              typeVal: REBALANCE_ZH[myType.rebalance] ?? myType.rebalance,
              curVal: REBALANCE_ZH[form.rebalance] ?? form.rebalance,
            },
          ]
        : [],
    [myType, form],
  )

  if (questions.length === 0) return null

  return (
    <div className="app-card">
      <h3>{t('投资性格问卷（可选 Demo）')}</h3>
      <p style={{ margin: '0 0 12px', fontSize: 12, color: 'var(--muted)' }}>
        {t('8 题（每题 4 档单选）判定 16 型投资性格，并透明映射到风险参数与约束：只影响目标波动率、回撤容忍、上下限与调仓频率，不改变任何方法的话语权。')}
      </p>
      <div className="page-grid grid-2" style={{ gap: 10 }}>
        {questions.map((q, i) => (
          <div key={i} style={{ border: '1px solid var(--line)', borderRadius: 8, padding: '10px 12px' }}>
            <div style={{ fontSize: 12.5, fontWeight: 600, marginBottom: 6 }}>
              {i + 1}. {q.q}
            </div>
            <div style={{ display: 'grid', gap: 4 }}>
              {q.options.map((opt, oi) => (
                <label key={oi} style={{ display: 'flex', alignItems: 'flex-start', gap: 6, fontSize: 12, cursor: 'pointer' }}>
                  <input
                    type="radio"
                    name={`pq_${i}`}
                    checked={answers[i] === oi}
                    onChange={() => setAnswers(answers.map((a, j) => (j === i ? oi : a)))}
                    style={{ marginTop: 2 }}
                  />
                  {opt}
                </label>
              ))}
            </div>
          </div>
        ))}
      </div>
      <button type="button" style={{ ...primaryBtnStyle, marginTop: 12, opacity: allAnswered ? 1 : 0.5 }} disabled={!allAnswered} onClick={onSubmit}>
        {t('计算我的类型')}
      </button>
      {!allAnswered && <span style={{ fontSize: 11.5, color: 'var(--muted)', marginLeft: 10 }}>{t('答完全部 8 题后可计算')}</span>}

      {myType && (
        <div style={{ marginTop: 14, border: '1px solid var(--line-strong)', borderRadius: 8, padding: '12px 14px' }}>
          <div style={{ fontSize: 14, fontWeight: 700 }}>
            {t('你的类型：')}<span className="mono" style={{ fontSize: 13 }}>{myType.type}</span> · {myType.type_name}
          </div>
          <div style={{ fontSize: 11.5, color: 'var(--muted)', margin: '6px 0 8px' }}>{t('透明映射的风险参数对照（类型建议值 vs 当前表单值）')}</div>
          <div className="table-scroll">
            <table className="data-table" style={{ maxWidth: 480 }}>
              <thead>
                <tr>
                  <th>{t('参数')}</th>
                  <th>{t('类型建议值')}</th>
                  <th>{t('当前表单值')}</th>
                </tr>
              </thead>
              <tbody>
                {paramRows.map((r) => (
                  <tr key={r.label}>
                    <td>{t(r.label)}</td>
                    <td>{t(r.typeVal)}</td>
                    <td>{t(r.curVal)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <button type="button" style={{ ...btnStyle, marginTop: 10 }} onClick={() => applyType(myType)}>
            {t('应用到配置')}
          </button>
          <span style={{ fontSize: 11.5, color: 'var(--muted)', marginLeft: 10 }}>
            {t('只映射风险参数与约束，不改变任何方法的话语权')}
          </span>
        </div>
      )}
    </div>
  )
}
