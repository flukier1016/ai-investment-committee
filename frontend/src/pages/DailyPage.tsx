import { useEffect, useMemo, useState, type CSSProperties } from 'react'
import type { EChartsOption } from 'echarts'
import { api } from '../api'
import { useScenario } from '../scenario'
import { ScenarioPicker } from '../components/Layout'
import Chart from '../components/Chart'
import { BUCKET_META, BUCKET_ORDER, SOLID, chartTheme, fmtAsof, fmtPct, fmtSignedPct } from '../meta'
import { t, tf, usePrefs } from '../prefs'

// 图表实色统一取自 meta.ts SOLID，避免与 CSS 令牌漂移
const C_IDEAL = SOLID.bl // 理想权重（--bl）
const C_HELD = SOLID.teal // 当前持仓（--teal）
const C_BAND = SOLID.amber // 免交易带（amber）
const C_REBAL = SOLID.methodClock // 调仓日（金）

const FREQ_ZH: Record<string, string> = { daily: '每日', weekly: '每周', monthly: '每月', quarterly: '每季' }

interface AssetInfo {
  id: string
  name: string
  short_name: string
  bucket: string
}

interface DriftDay {
  date: string
  max_drift: number
  drift: number
  rebalanced: boolean
  decision_id: string
}

const subNote: CSSProperties = { fontSize: 11.5, color: 'var(--muted)', marginTop: 4 }

const DEFAULT_ROWS = 8

function DailyBody({ data, assets }: { data: Record<string, any>; assets: AssetInfo[] }) {
  const { lang, theme } = usePrefs() // 语言/主题切换时重建 ECharts option
  const [showAll, setShowAll] = useState(false)

  const history: DriftDay[] = data.history ?? []
  const band: number = data.no_trade_band ?? 0
  const withinBand = (data.max_drift ?? 0) <= band
  const rebalToday: boolean = !!data.rebalanced_today

  const driftOption = useMemo<EChartsOption>(() => ({
    tooltip: {
      trigger: 'axis',
      valueFormatter: (v: unknown) => (typeof v === 'number' ? fmtPct(v, 2) : '—'),
    },
    legend: { top: 0, data: [t('每日最大偏离'), t('调仓日')] },
    grid: { left: 8, right: 14, top: 34, bottom: 6, containLabel: true },
    xAxis: {
      type: 'category',
      data: history.map((h) => h.date),
      boundaryGap: false,
      axisLabel: { formatter: (d: string) => d.slice(5) },
    },
    yAxis: {
      type: 'value',
      axisLabel: { formatter: (v: number) => `${(v * 100).toFixed(1)}%` },
      splitLine: { lineStyle: { color: chartTheme(theme).grid } },
    },
    series: [
      {
        name: t('每日最大偏离'),
        type: 'line',
        data: history.map((h) => h.max_drift),
        showSymbol: false,
        lineStyle: { width: 2, color: C_IDEAL },
        itemStyle: { color: C_IDEAL },
        markLine: {
          symbol: 'none',
          silent: true,
          lineStyle: { color: C_BAND, type: 'dashed', width: 1.5 },
          label: { formatter: `${t('免交易带')} ${fmtPct(band, 1)}`, color: C_BAND, position: 'insideEndTop' },
          data: [{ yAxis: band }],
        },
      },
      {
        name: t('调仓日'),
        type: 'scatter',
        data: history.map((h) => (h.rebalanced ? h.max_drift : null)),
        symbolSize: 10,
        itemStyle: { color: C_REBAL },
        z: 5,
      },
    ],
  // history/band 均由 data 派生，依赖 data 即可
  }), [data, lang, theme]) // eslint-disable-line react-hooks/exhaustive-deps

  const bucketOption = useMemo<EChartsOption>(() => ({
    tooltip: {
      trigger: 'axis',
      valueFormatter: (v: unknown) => (typeof v === 'number' ? fmtPct(v, 2) : '—'),
    },
    legend: { top: 0, data: [t('理想权重'), t('当前持仓')] },
    grid: { left: 8, right: 14, top: 34, bottom: 6, containLabel: true },
    xAxis: {
      type: 'category',
      data: BUCKET_ORDER.map((b) => t(BUCKET_META[b]?.label ?? b)),
      axisLabel: { interval: 0 },
    },
    yAxis: {
      type: 'value',
      axisLabel: { formatter: (v: number) => `${(v * 100).toFixed(0)}%` },
      splitLine: { lineStyle: { color: chartTheme(theme).grid } },
    },
    series: [
      {
        name: t('理想权重'),
        type: 'bar',
        data: BUCKET_ORDER.map((b) => data.ideal_buckets?.[b] ?? 0),
        barMaxWidth: 26,
        itemStyle: { color: C_IDEAL },
      },
      {
        name: t('当前持仓'),
        type: 'bar',
        data: BUCKET_ORDER.map((b) => data.held_buckets?.[b] ?? 0),
        barMaxWidth: 26,
        itemStyle: { color: C_HELD },
      },
    ],
  }), [data, lang, theme])

  const assetRows = useMemo(() => {
    return [...assets]
      .sort((a, b) => BUCKET_ORDER.indexOf(a.bucket) - BUCKET_ORDER.indexOf(b.bucket))
      .map((a) => {
        const ideal: number = data.ideal_weights?.[a.id] ?? 0
        const held: number = data.held_weights?.[a.id] ?? 0
        return { ...a, ideal, held, diff: held - ideal }
      })
  }, [assets, data])

  const visibleRows = showAll ? assetRows : assetRows.slice(0, DEFAULT_ROWS)
  const timeline = [...history].slice(-10).reverse()

  return (
    <div className="page-grid">
      <div className="page-grid grid-4">
        <div className="app-card">
          <div className="kpi-label">{t('今日是否调仓')}</div>
          <div className="kpi-value" style={rebalToday ? { color: C_REBAL } : undefined}>
            {rebalToday ? t('已调仓') : t('未触发')}
          </div>
          <div style={subNote}>
            {rebalToday ? t('桶级偏离越带，已重置到理想权重') : t('桶级偏离在免交易带内，继续持有')}
          </div>
        </div>
        <div className="app-card">
          <div className="kpi-label">{t('当前最大偏离')}</div>
          <div className="kpi-value">{fmtPct(data.max_drift, 2)}</div>
          <div style={subNote}>
            {t('免交易带')} {fmtPct(band, 1)} ·{' '}
            {withinBand
              ? <span className="status-ok">✓ {t('带内')}</span>
              : <span className="status-warn">! {t('越带')}</span>}
          </div>
        </div>
        <div className="app-card">
          <div className="kpi-label">{t('最近一次调仓')}</div>
          <div className="kpi-value">{fmtAsof(data.last_rebalance ?? '')}</div>
          <div style={subNote}>
            {t('目标频率')} {t(FREQ_ZH[data.rebalance_freq] ?? data.rebalance_freq)} · {t('免交易带触发')}
          </div>
        </div>
        <div className="app-card">
          <div className="kpi-label">{t('模拟期调仓次数')}</div>
          <div className="kpi-value">
            {data.rebalance_count ?? 0}
            <span style={{ fontSize: 12, fontWeight: 400, color: 'var(--muted)' }}>{tf(' 次', ' times')}</span>
          </div>
          <div style={subNote}>{tf(`${history.length} 个交易日模拟期内触发`, `over ${history.length} simulated trading days`)}</div>
        </div>
      </div>

      <div className="page-grid grid-2">
        <div className="app-card">
          <h3>{t('偏离演进与免交易带')}</h3>
          <Chart option={driftOption} height={300} />
        </div>
        <div className="app-card">
          <h3>{t('今日理想 vs 当前持仓（资产桶）')}</h3>
          <Chart option={bucketOption} height={300} />
        </div>
      </div>

      <div className="page-grid grid-2">
        <div className="app-card">
          <h3>
            {t('明细资产：理想 vs 持仓')}
            <span style={{ fontSize: 11.5, fontWeight: 400, color: 'var(--muted)' }}>
              {tf(`共 ${assetRows.length} 项 · 偏离红正绿负`, `${assetRows.length} assets · drift red +, green −`)}
            </span>
          </h3>
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th>{t('资产')}</th>
                  <th>{t('所属桶')}</th>
                  <th style={{ textAlign: 'right' }}>{t('理想权重')}</th>
                  <th style={{ textAlign: 'right' }}>{t('当前持仓')}</th>
                  <th style={{ textAlign: 'right' }}>{t('偏离')}</th>
                </tr>
              </thead>
              <tbody>
                {visibleRows.map((row) => {
                  const meta = BUCKET_META[row.bucket]
                  return (
                    <tr key={row.id}>
                      <td title={row.name}>{row.short_name}</td>
                      <td>
                        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, whiteSpace: 'nowrap' }}>
                          <span style={{ width: 8, height: 8, borderRadius: '50%', background: meta?.color ?? 'var(--muted)', flex: '0 0 auto' }} />
                          {t(meta?.label ?? row.bucket)}
                        </span>
                      </td>
                      <td style={{ textAlign: 'right' }}>{fmtPct(row.ideal, 2)}</td>
                      <td style={{ textAlign: 'right' }}>{fmtPct(row.held, 2)}</td>
                      <td style={{ textAlign: 'right' }} className={row.diff >= 0 ? 'pos' : 'neg'}>
                        {fmtSignedPct(row.diff, 2)}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
          {assetRows.length > DEFAULT_ROWS && (
            <div style={{ textAlign: 'center', marginTop: 10 }}>
              <button
                type="button"
                onClick={() => setShowAll((s) => !s)}
                style={{
                  font: 'inherit',
                  fontSize: 12.5,
                  color: 'var(--ink)',
                  background: 'var(--paper)',
                  border: '1px solid var(--line-strong)',
                  borderRadius: 8,
                  padding: '6px 14px',
                  cursor: 'pointer',
                }}
              >
                {showAll ? t('收起') : tf(`显示全部 ${assetRows.length} 项资产`, `Show all ${assetRows.length} assets`)}
              </button>
            </div>
          )}
        </div>

        <div className="app-card">
          <h3>
            {t('决策记录时间线')}
            <span style={{ fontSize: 11.5, fontWeight: 400, color: 'var(--muted)' }}>{t('最近 10 个交易日')}</span>
          </h3>
          <div style={{ display: 'grid' }}>
            {timeline.map((h) => (
              <div
                key={h.decision_id}
                style={{
                  display: 'flex',
                  alignItems: 'baseline',
                  gap: 10,
                  padding: '7px 0',
                  borderBottom: '1px solid var(--line)',
                  fontSize: 12.5,
                }}
              >
                <span className="mono" style={{ color: 'var(--muted)', width: 82, flex: '0 0 auto' }}>{h.date}</span>
                <span style={{ width: 58, flex: '0 0 auto', fontVariantNumeric: 'tabular-nums' }}>
                  {fmtPct(h.max_drift, 2)}
                </span>
                <span style={h.rebalanced ? { color: C_REBAL, fontWeight: 600 } : { color: 'var(--muted)' }}>
                  {h.rebalanced ? `● ${t('触发调仓')}` : `○ ${t('带内持有')}`}
                </span>
                <span
                  className="mono"
                  style={{
                    marginLeft: 'auto',
                    color: 'var(--muted)',
                    fontSize: 10.5,
                    whiteSpace: 'nowrap',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    maxWidth: 200,
                  }}
                  title={h.decision_id}
                >
                  {h.decision_id}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}

export default function DailyPage() {
  usePrefs() // 订阅语言/主题切换
  const { scenarioId } = useScenario()
  const [data, setData] = useState<Record<string, any> | null>(null)
  const [assets, setAssets] = useState<AssetInfo[] | null>(null)
  const [err, setErr] = useState<Error | null>(null)

  useEffect(() => {
    let alive = true
    setData(null)
    setErr(null)
    Promise.all([api.daily(scenarioId), api.meta()])
      .then(([d, m]) => {
        if (!alive) return
        setData(d)
        setAssets((m.universe as { assets: AssetInfo[] }).assets)
      })
      .catch((e: Error) => { if (alive) setErr(e) })
    return () => { alive = false }
  }, [scenarioId])

  return (
    <div>
      <header className="page-head">
        <div>
          <h2>{t('日更驾驶舱')}</h2>
          <p className="page-sub">
            {t('每日重算理想权重，桶级偏离超过免交易带才触发调仓')}
            {data ? ` · ${tf('截至', 'as of')} ${fmtAsof(data.asof)}` : ''}
          </p>
        </div>
        <ScenarioPicker />
      </header>

      {err
        ? <div className="error-block">{t('加载失败：')}{err.message}</div>
        : !data || !assets
          ? <div className="loading-block">{t('正在加载日更驾驶舱数据…')}</div>
          : <DailyBody data={data} assets={assets} />}

      <div className="demo-banner">
        {data?.note ? `${data.note} · ` : ''}{t('Demo 演示数据 · 非投资建议')}
      </div>
    </div>
  )
}
