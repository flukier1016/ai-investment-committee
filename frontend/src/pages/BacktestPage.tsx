import { useCallback, useEffect, useMemo, useState } from 'react'
import type { EChartsOption, LineSeriesOption } from 'echarts'
import { api, savedConfig } from '../api'
import { BUCKET_META, BUCKET_ORDER, BUCKET_SOLID, SOLID, chartTheme, fmtAsof, fmtPct, fmtSignedPct } from '../meta'
import { t, tf, usePrefs } from '../prefs'
import Chart from '../components/Chart'

const STRATEGY_ZH: Record<string, string> = {
  committee: '委员会组合',
  risk_parity_only: '纯 Risk Parity 底仓',
  bm_6040: '60/40 基准',
  bm_equal: '等权基准',
  cash: '现金',
}

// 净值曲线样式：委员会粗实线，基准虚线，现金点线
const NAV_SERIES: Array<{ key: string; name: string; color: string; width: number; dash?: 'dashed' | 'dotted' }> = [
  { key: 'committee', name: '委员会组合', color: SOLID.bl, width: 2.6 },
  { key: 'risk_parity_only', name: '纯 Risk Parity', color: SOLID.methodRiskParity, width: 1.4 },
  { key: 'bm_6040', name: '60·40 基准', color: SOLID.muted, width: 1.4, dash: 'dashed' },
  { key: 'bm_equal', name: '等权基准', color: SOLID.methodClock, width: 1.4, dash: 'dashed' },
  { key: 'cash', name: '现金', color: SOLID.cash, width: 1.2, dash: 'dotted' },
]

const btnStyle: React.CSSProperties = {
  font: 'inherit', fontSize: 12.5, padding: '7px 14px', borderRadius: 8,
  border: '1px solid var(--line-strong)', background: 'var(--paper)', color: 'var(--ink)', cursor: 'pointer',
}

export default function BacktestPage() {
  const { lang, theme } = usePrefs()  // 订阅语言/主题切换以触发重渲染
  const [data, setData] = useState<Record<string, any> | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [showAllRebalance, setShowAllRebalance] = useState(false)

  const load = useCallback(() => {
    setLoading(true)
    setError(null)
    api.backtest(savedConfig())
      .then((d) => setData(d))
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { load() }, [load])

  const navOption = useMemo<EChartsOption>(() => {
    if (!data) return {}
    const series: LineSeriesOption[] = NAV_SERIES.map((s) => ({
      type: 'line',
      name: t(s.name),
      data: data.nav?.[s.key] ?? [],
      showSymbol: false,
      sampling: 'lttb',
      lineStyle: { width: s.width, color: s.color, type: s.dash ?? 'solid' },
      itemStyle: { color: s.color },
      emphasis: { focus: 'series' },
    }))
    return {
      grid: { left: 56, right: 18, top: 40, bottom: 26 },
      legend: { top: 4, textStyle: { fontSize: 11.5 } },
      tooltip: { trigger: 'axis', valueFormatter: (v) => Number(v).toFixed(4) },
      xAxis: { type: 'category', data: data.dates ?? [], boundaryGap: false, axisLabel: { fontSize: 10.5 } },
      yAxis: { type: 'value', scale: true, axisLabel: { formatter: (v: number) => v.toFixed(2) }, splitLine: { lineStyle: { color: chartTheme(theme).grid } } },
      series,
    }
  }, [data, lang, theme])

  const drawdownOption = useMemo<EChartsOption>(() => {
    if (!data) return {}
    return {
      grid: { left: 56, right: 18, top: 20, bottom: 26 },
      tooltip: { trigger: 'axis', valueFormatter: (v) => `${(Number(v) * 100).toFixed(2)}%` },
      xAxis: { type: 'category', data: data.dates ?? [], boundaryGap: false, axisLabel: { fontSize: 10.5 } },
      yAxis: { type: 'value', axisLabel: { formatter: (v: number) => `${(v * 100).toFixed(0)}%` }, splitLine: { lineStyle: { color: chartTheme(theme).grid } } },
      series: [{
        type: 'line',
        name: t('委员会组合回撤'),
        data: data.drawdown ?? [],
        showSymbol: false,
        sampling: 'lttb',
        lineStyle: { width: 1.2, color: SOLID.red },
        itemStyle: { color: SOLID.red },
        areaStyle: { color: SOLID.red, opacity: 0.18 },
      }],
    }
  }, [data, lang, theme])

  const weightsOption = useMemo<EChartsOption>(() => {
    if (!data) return {}
    const history: Array<{ date: string; bucket_weights: Record<string, number> }> = data.weights_history ?? []
    const dates = history.map((h) => h.date)
    const series: LineSeriesOption[] = BUCKET_ORDER.map((bid) => ({
      type: 'line',
      name: t(BUCKET_META[bid].label),
      stack: 'weights',
      data: history.map((h) => Number(((h.bucket_weights?.[bid] ?? 0) * 100).toFixed(2))),
      showSymbol: false,
      lineStyle: { width: 0.5, color: BUCKET_SOLID[bid] },
      itemStyle: { color: BUCKET_SOLID[bid] },
      areaStyle: { color: BUCKET_SOLID[bid], opacity: 0.85 },
      emphasis: { focus: 'series' },
    }))
    return {
      grid: { left: 48, right: 18, top: 40, bottom: 26 },
      legend: { top: 4, textStyle: { fontSize: 11.5 } },
      tooltip: { trigger: 'axis', valueFormatter: (v) => `${Number(v).toFixed(1)}%` },
      xAxis: { type: 'category', data: dates, boundaryGap: false, axisLabel: { fontSize: 10.5 } },
      yAxis: { type: 'value', max: 100, axisLabel: { formatter: '{value}%' }, splitLine: { lineStyle: { color: chartTheme(theme).grid } } },
      series,
    }
  }, [data, lang, theme])

  const sortedMetrics = useMemo(() => {
    const list: Array<Record<string, any>> = [...(data?.metrics ?? [])]
    return list.sort((a, b) => (b.sharpe ?? -Infinity) - (a.sharpe ?? -Infinity))
  }, [data])

  const rebalanceRows = useMemo(() => {
    const log: Array<Record<string, any>> = [...(data?.rebalance_log ?? [])].reverse()
    return showAllRebalance ? log : log.slice(0, 12)
  }, [data, showAllRebalance])

  const rebalanceTotal: number = data?.rebalance_log?.length ?? 0

  return (
    <>
      <div className="page-head">
        <div>
          <h2>{t('回测分析')}</h2>
          <p className="page-sub">
            {data ? `${data.span?.start} ~ ${data.span?.end} · ${t('月度调仓 walk-forward · 每个调仓日只用当时可见数据')}`
              : t('月度调仓 walk-forward · 每个调仓日只用当时可见数据')}
          </p>
        </div>
        <button style={btnStyle} onClick={load} disabled={loading}>
          {loading ? t('回测运行中…') : t('重新回测')}
        </button>
      </div>

      <div className="demo-banner">
        {t('Demo 演示数据 · 非投资建议')}{data?.note ? ` · ${data.note}` : ''}
      </div>

      {error && <div className="error-block">{error}</div>}
      {loading && !error && <div className="loading-block">{t('正在逐个调仓日重放决策链，只使用各时点可见数据…')}</div>}

      {!loading && !error && data && (
        <div className="page-grid">
          <div className="app-card">
            <h3>{t('净值曲线（期初 = 1）')}</h3>
            <Chart option={navOption} height={330} />
          </div>

          <div className="page-grid grid-2">
            <div className="app-card">
              <h3>{t('委员会组合回撤')}</h3>
              <Chart option={drawdownOption} height={240} />
            </div>

            <div className="app-card">
              <h3>{t('绩效对比（按 Sharpe 降序）')}</h3>
              <div className="table-scroll">
                <table className="data-table">
                  <thead>
                    <tr><th>{t('策略')}</th><th>{t('年化收益')}</th><th>{t('年化波动')}</th><th>Sharpe</th><th>{t('最大回撤')}</th><th>Calmar</th></tr>
                  </thead>
                  <tbody>
                    {sortedMetrics.map((m) => {
                      const isCommittee = m.strategy === 'committee'
                      return (
                        <tr key={m.strategy} style={isCommittee ? { background: 'rgba(64, 93, 136, .09)', fontWeight: 600 } : undefined}>
                          <td>{t(STRATEGY_ZH[m.strategy] ?? m.strategy)}</td>
                          <td className={m.ann_return >= 0 ? 'pos' : 'neg'}>{fmtSignedPct(m.ann_return, 2)}</td>
                          <td>{fmtPct(m.ann_vol, 2)}</td>
                          <td>{m.sharpe === null || m.sharpe === undefined ? '—' : m.sharpe.toFixed(2)}</td>
                          <td>{fmtPct(m.max_drawdown, 2)}</td>
                          <td>{m.calmar === null || m.calmar === undefined ? '—' : m.calmar.toFixed(2)}</td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
              <p style={{ margin: '8px 0 0', fontSize: 11.5, color: 'var(--muted)' }}>
                {t('同窗口、同成本口径对比；负值如实呈现，不做粉饰。')}
              </p>
            </div>
          </div>

          <div className="page-grid grid-2">
            <div className="app-card">
              <h3>{t('换手与成本')}</h3>
              <div className="page-grid grid-3" style={{ gap: 10 }}>
                <div>
                  <div className="kpi-value">{fmtPct(data.ann_turnover)}</div>
                  <div className="kpi-label">{t('年化换手率')}</div>
                </div>
                <div>
                  <div className="kpi-value">{fmtPct(data.avg_rebalance_turnover)}</div>
                  <div className="kpi-label">{t('单次调仓平均换手（权重稳定性）')}</div>
                </div>
                <div>
                  <div className="kpi-value">{Number(data.cost_bps_per_side).toFixed(1)}<span style={{ fontSize: 13, fontWeight: 500 }}> {t('基点')}</span></div>
                  <div className="kpi-label">{t('单边交易成本')}</div>
                </div>
              </div>
            </div>

            <div className="app-card">
              <h3>{t('walk-forward 分折（样本外）')}</h3>
              <div className="table-scroll">
                <table className="data-table">
                  <thead>
                    <tr><th>{t('年份')}</th><th>{t('委员会年化')}</th><th>{t('等权年化')}</th><th>{t('是否跑赢')}</th></tr>
                  </thead>
                  <tbody>
                    {(data.walk_forward?.folds ?? []).map((f: Record<string, any>) => (
                      <tr key={f.year}>
                        <td>{f.year}</td>
                        <td className={f.committee_ann >= 0 ? 'pos' : 'neg'}>{fmtSignedPct(f.committee_ann, 2)}</td>
                        <td className={f.bm_equal_ann >= 0 ? 'pos' : 'neg'}>{fmtSignedPct(f.bm_equal_ann, 2)}</td>
                        <td>{f.beats
                          ? <span className="status-ok">{t('✓ 跑赢')}</span>
                          : <span className="status-warn">{t('✗ 落后')}</span>}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {data.walk_forward?.oos_note && (
                <p style={{ margin: '8px 0 0', fontSize: 11.5, color: 'var(--muted)' }}>{data.walk_forward.oos_note}</p>
              )}
            </div>
          </div>

          <div className="app-card">
            <h3>{t('桶权重历史（堆叠）')}</h3>
            <Chart option={weightsOption} height={290} />
          </div>

          <div className="app-card">
            <h3>
              {showAllRebalance
                ? tf(`调仓记录（倒序，共 ${rebalanceTotal} 条）`, `Rebalance Log (newest first, all ${rebalanceTotal})`)
                : tf(`调仓记录（倒序，最近 12 / ${rebalanceTotal} 条）`, `Rebalance Log (newest first, latest 12 of ${rebalanceTotal})`)}
              {rebalanceTotal > 12 && (
                <button style={{ ...btnStyle, marginLeft: 'auto', padding: '4px 10px', fontSize: 11.5 }}
                  onClick={() => setShowAllRebalance((v) => !v)}>
                  {showAllRebalance ? t('收起') : t('显示全部')}
                </button>
              )}
            </h3>
            <div className="table-scroll">
              <table className="data-table">
                <thead>
                  <tr><th>{t('调仓日')}</th><th>{t('换手率')}</th><th>{t('成本')}</th><th>{t('观点条数')}</th><th>{t('宏观象限')}</th><th>{t('触发规则数')}</th></tr>
                </thead>
                <tbody>
                  {rebalanceRows.map((r) => (
                    <tr key={r.decision_id ?? r.date}>
                      <td>{fmtAsof(r.date)}</td>
                      <td>{fmtPct(r.turnover)}</td>
                      <td>{Number(r.cost_bps).toFixed(1)} {t('基点')}</td>
                      <td>{r.views}</td>
                      <td>{t(String(r.regime ?? '—'))}</td>
                      <td>{(r.triggered ?? []).length > 0
                        ? <span className="status-warn">⚠ {(r.triggered ?? []).length}</span>
                        : <span className="status-ok">✓ 0</span>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
