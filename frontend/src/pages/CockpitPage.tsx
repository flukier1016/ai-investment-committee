import { useEffect, useMemo, useState, type CSSProperties } from 'react'
import type { EChartsOption } from 'echarts'
import { api } from '../api'
import { useScenario } from '../scenario'
import { ScenarioPicker } from '../components/Layout'
import Chart from '../components/Chart'
import { BUCKET_META, BUCKET_ORDER, fmtAsof, fmtDecisionId, fmtPct, fmtSignedPct } from '../meta'
import { t, tf, usePrefs } from '../prefs'

// 与 meta.ts SOLID 同值的图表实色
const C_COMMITTEE = '#405d88' // 委员会组合（--bl）
const C_BM = '#66706c' // 60·40 基准（muted）
const C_BAND = '#8a5b06' // 免交易带（amber）
const C_REBAL = '#9f6500' // 调仓日高亮（金）

interface SnapshotRow {
  id: string
  name: string
  short_name: string
  bucket: string
  px: number
  chg_1w: number
  ytd: number
  vol_3m: number
}

interface DriftDay {
  date: string
  max_drift: number
  drift: number
  rebalanced: boolean
  decision_id: string
}

const subNote: CSSProperties = { fontSize: 11.5, color: 'var(--muted)', marginTop: 4 }

function BucketTag({ bucket }: { bucket: string }) {
  const meta = BUCKET_META[bucket]
  if (!meta) return <span>{bucket}</span>
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, whiteSpace: 'nowrap' }}>
      <span style={{ width: 8, height: 8, borderRadius: '50%', background: meta.color, flex: '0 0 auto' }} />
      {t(meta.label)}
    </span>
  )
}

function CockpitBody({ data }: { data: Record<string, any> }) {
  const { lang } = usePrefs() // 语言切换时重建 ECharts option
  const staleDays: number = data.data_freshness?.macro_staleness_days ?? 0
  const macroStale = staleDays > 35
  const driftHistory: DriftDay[] = data.drift?.history ?? []
  const band: number = data.drift?.band ?? 0
  const weightsOk = Math.abs((data.closure?.weights ?? 0) - 1) < 1e-6
  const engineOk = data.system_health?.engine === 'ok'
  const storeOk = data.system_health?.store === 'ok'

  const snapshotRows = useMemo<SnapshotRow[]>(() => {
    const rows: SnapshotRow[] = [...(data.market_snapshot ?? [])]
    return rows.sort((a, b) => BUCKET_ORDER.indexOf(a.bucket) - BUCKET_ORDER.indexOf(b.bucket))
  }, [data])

  const navOption = useMemo<EChartsOption>(() => ({
    tooltip: {
      trigger: 'axis',
      valueFormatter: (v: unknown) => (typeof v === 'number' ? v.toFixed(4) : '—'),
    },
    legend: { top: 0, data: [t('委员会组合'), t('60·40 基准')] },
    grid: { left: 8, right: 14, top: 34, bottom: 6, containLabel: true },
    xAxis: { type: 'category', data: data.nav?.dates ?? [], boundaryGap: false },
    yAxis: {
      type: 'value',
      scale: true,
      axisLabel: { formatter: (v: number) => v.toFixed(2) },
      splitLine: { lineStyle: { color: '#dde4db' } },
    },
    series: [
      {
        name: t('委员会组合'),
        type: 'line',
        data: data.nav?.committee ?? [],
        showSymbol: false,
        lineStyle: { width: 2, color: C_COMMITTEE },
        itemStyle: { color: C_COMMITTEE },
      },
      {
        name: t('60·40 基准'),
        type: 'line',
        data: data.nav?.bm_6040 ?? [],
        showSymbol: false,
        lineStyle: { width: 1.5, color: C_BM, type: 'dashed' },
        itemStyle: { color: C_BM },
      },
    ],
  }), [data, lang])

  const driftOption = useMemo<EChartsOption>(() => ({
    tooltip: {
      trigger: 'axis',
      valueFormatter: (v: unknown) => (typeof v === 'number' ? fmtPct(v, 2) : '—'),
    },
    legend: { top: 0, data: [t('每日最大偏离'), t('调仓日')] },
    grid: { left: 8, right: 14, top: 34, bottom: 6, containLabel: true },
    xAxis: {
      type: 'category',
      data: driftHistory.map((h) => h.date),
      axisLabel: { formatter: (d: string) => d.slice(5) },
    },
    yAxis: {
      type: 'value',
      axisLabel: { formatter: (v: number) => `${(v * 100).toFixed(1)}%` },
      splitLine: { lineStyle: { color: '#dde4db' } },
    },
    series: [
      {
        name: t('每日最大偏离'),
        type: 'bar',
        data: driftHistory.map((h) => h.max_drift),
        barMaxWidth: 14,
        itemStyle: { color: C_COMMITTEE, opacity: 0.85 },
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
        data: driftHistory.map((h) => (h.rebalanced ? h.max_drift : null)),
        symbolSize: 11,
        itemStyle: { color: C_REBAL },
        z: 5,
      },
    ],
  // driftHistory/band 均由 data 派生，依赖 data 即可
  }), [data, lang]) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="page-grid">
      <div className="page-grid grid-4">
        <div className="app-card">
          <div className="kpi-label">{t('风险预算使用率')}</div>
          <div className="kpi-value">{fmtPct(data.risk_budget_use, 1)}</div>
          <div style={subNote}>
            {t('组合波动')} {fmtPct(data.portfolio_vol, 1)} · {t('目标波动')} {fmtPct(data.target_vol, 1)}
          </div>
        </div>
        <div className="app-card">
          <div className="kpi-label">{t('当前回撤')}</div>
          <div className={`kpi-value ${data.current_drawdown >= 0 ? 'pos' : 'neg'}`}>
            {fmtSignedPct(data.current_drawdown, 2)}
          </div>
          <div style={subNote}>{t('相对模拟期净值高点')}</div>
        </div>
        <div className="app-card">
          <div className="kpi-label">{t('数据新鲜度')}</div>
          <div className="kpi-value">
            <span className={macroStale ? 'status-warn' : ''}>{staleDays} {tf('天', 'd')}</span>
            <span style={{ fontSize: 12, fontWeight: 400, color: 'var(--muted)' }}> {t('宏观滞后')}</span>
          </div>
          <div style={subNote}>
            {t('行情截至')} {fmtAsof(data.data_freshness?.prices_asof ?? '')} ·{' '}
            {macroStale
              ? <span className="status-warn">! {t('宏观数据偏旧')}</span>
              : <span className="status-ok">✓ {t('新鲜度正常')}</span>}
          </div>
        </div>
        <div className="app-card">
          <div className="kpi-label">{t('最近计算耗时')}</div>
          <div className="kpi-value">
            {Number(data.engine_runtime_ms ?? 0).toFixed(1)}
            <span style={{ fontSize: 12, fontWeight: 400, color: 'var(--muted)' }}> {t('毫秒')}</span>
          </div>
          <div style={subNote}>{t('单次全流程决策重算')}</div>
        </div>
      </div>

      <div className="page-grid grid-2">
        <div className="app-card">
          <h3>{t('净值走势（模拟期）')}</h3>
          <Chart option={navOption} height={320} />
        </div>
        <div className="app-card">
          <h3>
            {t('权重漂移与免交易带')}
            <span style={{ fontSize: 11.5, fontWeight: 400, color: 'var(--muted)' }}>
              {t('当前最大偏离')} {fmtPct(data.drift?.max_drift, 2)} · {t('带宽')} {fmtPct(band, 1)}
            </span>
          </h3>
          <Chart option={driftOption} height={320} />
        </div>
      </div>

      <div className="page-grid grid-2">
        <div className="app-card">
          <h3>{t('未来事件带')}</h3>
          <div style={{ display: 'flex', gap: 10, overflowX: 'auto', paddingBottom: 4 }}>
            {(data.events ?? []).map((ev: { date: string; name: string; days_to: number }) => (
              <div
                key={`${ev.date}-${ev.name}`}
                style={{
                  flex: '0 0 auto',
                  minWidth: 118,
                  border: '1px solid var(--line)',
                  borderRadius: 8,
                  padding: '8px 10px',
                }}
              >
                <div className="mono" style={{ color: ev.days_to === 0 ? 'var(--red)' : 'var(--muted)' }}>
                  {ev.days_to === 0 ? t('今日') : tf(`${ev.days_to} 天后`, `in ${ev.days_to}d`)}
                </div>
                <div style={{ fontSize: 12.5, marginTop: 3 }}>{ev.name}</div>
                <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>{ev.date}</div>
              </div>
            ))}
          </div>
          {data.events_note && <div style={{ ...subNote, marginTop: 8 }}>{data.events_note}</div>}
        </div>

        <div className="app-card">
          <h3>{t('闭合检查与系统健康')}</h3>
          <div style={{ display: 'grid', gap: 8, fontSize: 12.5 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
              <span style={{ color: 'var(--muted)' }}>{t('权重合计闭合')}</span>
              <span className={weightsOk ? 'status-ok' : 'status-warn'}>
                {fmtPct(data.closure?.weights, 1)} {weightsOk ? tf('✓ 闭合', '✓ closed') : tf('! 不闭合', '! not closed')}
              </span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
              <span style={{ color: 'var(--muted)' }}>{t('贡献归因闭合')}</span>
              <span className={data.closure?.attribution ? 'status-ok' : 'status-warn'}>
                {data.closure?.attribution ? tf('✓ 通过', '✓ pass') : tf('! 未通过', '! fail')}
              </span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
              <span style={{ color: 'var(--muted)' }}>{t('计算引擎')}</span>
              <span className={engineOk ? 'status-ok' : 'status-warn'}>
                {engineOk ? tf('✓ 正常', '✓ OK') : `! ${data.system_health?.engine ?? t('异常')}`}
              </span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
              <span style={{ color: 'var(--muted)' }}>{t('决策留痕存储')}</span>
              <span className={storeOk ? 'status-ok' : 'status-warn'}>
                {storeOk ? tf('✓ 正常', '✓ OK') : `! ${data.system_health?.store ?? t('异常')}`}
              </span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
              <span style={{ color: 'var(--muted)' }}>{t('已留痕决策数')}</span>
              <span>{tf(`${data.system_health?.decisions_stored ?? 0} 条`, `${data.system_health?.decisions_stored ?? 0}`)}</span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
              <span style={{ color: 'var(--muted)' }}>{t('当前决策')}</span>
              <span>{fmtDecisionId(data.decision_id ?? '')}</span>
            </div>
          </div>
          <div className="mono" style={{ marginTop: 8, color: 'var(--muted)', fontSize: 10.5 }}>
            {data.decision_id}
          </div>
        </div>
      </div>

      <div className="app-card">
        <h3>
          {t('市场快照')}
          <span style={{ fontSize: 11.5, fontWeight: 400, color: 'var(--muted)' }}>
            {tf(`${snapshotRows.length} 项资产 · 按资产桶分组 · 红涨绿跌`, `${snapshotRows.length} assets · grouped by bucket · red up, green down`)}
          </span>
        </h3>
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th>{t('资产')}</th>
                <th>{t('所属桶')}</th>
                <th style={{ textAlign: 'right' }}>{t('现价')}</th>
                <th style={{ textAlign: 'right' }}>{t('近一周')}</th>
                <th style={{ textAlign: 'right' }}>{t('年初至今')}</th>
                <th style={{ textAlign: 'right' }}>{t('3月年化波动')}</th>
              </tr>
            </thead>
            <tbody>
              {snapshotRows.map((row) => (
                <tr key={row.id}>
                  <td title={row.name}>{row.short_name}</td>
                  <td><BucketTag bucket={row.bucket} /></td>
                  <td style={{ textAlign: 'right' }}>{row.px.toFixed(2)}</td>
                  <td style={{ textAlign: 'right' }} className={row.chg_1w >= 0 ? 'pos' : 'neg'}>
                    {fmtSignedPct(row.chg_1w, 2)}
                  </td>
                  <td style={{ textAlign: 'right' }} className={row.ytd >= 0 ? 'pos' : 'neg'}>
                    {fmtSignedPct(row.ytd, 1)}
                  </td>
                  <td style={{ textAlign: 'right' }}>{fmtPct(row.vol_3m, 1)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}

export default function CockpitPage() {
  usePrefs() // 订阅语言/主题切换
  const { scenarioId } = useScenario()
  const [data, setData] = useState<Record<string, any> | null>(null)
  const [err, setErr] = useState<Error | null>(null)

  useEffect(() => {
    let alive = true
    setData(null)
    setErr(null)
    api.cockpit(scenarioId)
      .then((d) => { if (alive) setData(d) })
      .catch((e: Error) => { if (alive) setErr(e) })
    return () => { alive = false }
  }, [scenarioId])

  return (
    <div>
      <header className="page-head">
        <div>
          <h2>{t('组合驾驶舱')}</h2>
          <p className="page-sub">
            {t('风险预算、净值、权重漂移、事件与市场快照一屏总览')}
            {data ? ` · ${tf('截至', 'as of')} ${fmtAsof(data.asof)}` : ''}
          </p>
        </div>
        <ScenarioPicker />
      </header>

      {err
        ? <div className="error-block">{t('加载失败：')}{err.message}</div>
        : !data
          ? <div className="loading-block">{t('正在加载组合驾驶舱数据…')}</div>
          : <CockpitBody data={data} />}

      <div className="demo-banner">{t('Demo 演示数据 · 非投资建议')}</div>
    </div>
  )
}
