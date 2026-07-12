import { Fragment, useEffect, useState } from 'react'
import { api } from '../api'
import Chart from '../components/Chart'
import { ScenarioPicker } from '../components/Layout'
import { useScenario } from '../scenario'
import { CLASS_META, CLASS_ORDER, SOLID, chartTheme, fmtAsof, fmtPct, fmtSignedPct } from '../meta'
import { t, tf, usePrefs } from '../prefs'

// ---- 本页局部类型（字段以 docs/api_samples/spread_desk.json 为准） ----

interface DeskTrade {
  opened: string
  closed: string
  direction: string
  pnl_bps: number
}

interface DeskStrategy {
  id: string
  name: string
  long: string
  short: string
  note: string
  z: number
  state: string
  legs: Record<string, number>
  trailing_2y: { sharpe: number; ann: number; trades: number }
  recent_trades: DeskTrade[]
}

interface ScoreRow {
  id: string
  name: string
  sharpe: number
  ann_bps: number
  trades: number
  state: string
}

interface Guardrail {
  rule: string
  label: string
  triggered: boolean
  detail: string
}

interface MacroEvent {
  date?: string
  name?: string
  days_to?: number
}

interface DeskData {
  asof: string
  thresholds: { open: number; close: number; z_window_days: number; rule: string }
  strategies: DeskStrategy[]
  scoreboard: ScoreRow[]
  overlay_ledger: { dates: string[]; nav: number[]; gross_exposure: number; gross_cap: number; accounting: string }
  constraints: { allow_net_short: boolean; gross_exposure_cap: number; overlay_risk_budget: number; isolation: string }
  core_guardrails: Guardrail[]
  core_class_weights: Record<string, number>
  events: MacroEvent[]
  legacy_note: string
}

// ---- 状态文字标签（文字 + 颜色，双通道） ----

const STATE_COLOR: Record<string, string> = {
  做收敛: 'var(--cyan)',
  做走阔: 'var(--rose)',
  持仓: 'var(--amber)',
  跟踪: 'var(--amber)',
  '持仓/跟踪': 'var(--amber)',
  观望: 'var(--muted)',
}

function StateBadge({ state }: { state: string }) {
  const color = STATE_COLOR[state] ?? 'var(--muted)'
  return (
    <span
      style={{
        display: 'inline-flex', alignItems: 'center', gap: 5, whiteSpace: 'nowrap',
        border: '1px solid currentColor', borderRadius: 999, padding: '2px 8px',
        color, fontSize: 11.5, fontWeight: 650, background: 'var(--paper)',
      }}
    >
      <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'currentColor' }} />
      {t(state)}
    </span>
  )
}

const fmtBps = (v: number) => `${v >= 0 ? '+' : ''}${v.toFixed(1)} bp`

export default function SpreadDeskPage() {
  const { theme } = usePrefs()  // 订阅语言/主题切换以触发重渲染
  const { scenarioId } = useScenario()
  const [data, setData] = useState<DeskData | null>(null)
  const [err, setErr] = useState<Error | null>(null)
  const [openRow, setOpenRow] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    setData(null)
    setErr(null)
    setOpenRow(null)
    api.spreadDesk(scenarioId)
      .then((d) => { if (alive) setData(d as DeskData) })
      .catch((e) => { if (alive) setErr(e as Error) })
    return () => { alive = false }
  }, [scenarioId])

  const openThreshold = data?.thresholds.open ?? 1.5
  const classMax = data ? Math.max(...Object.values(data.core_class_weights), 0) : 0

  return (
    <div>
      <div className="page-head">
        <div>
          <h2>{t('利差台与风控')}</h2>
          <p className="page-sub">{t('相对价值研究叠加 · 独立账本 · 默认不改变核心配置权重')}</p>
        </div>
        <ScenarioPicker />
      </div>

      <div className="demo-banner">
        {t('Demo 演示数据 · 非投资建议')}{data ? `${tf(' · 截至 ', ' · as of ')}${fmtAsof(data.asof)}` : ''}
      </div>

      {err ? (
        <div className="error-block">{err.message}</div>
      ) : !data ? (
        <div className="loading-block">{t('利差台数据加载中…')}</div>
      ) : (
        <div className="page-grid">
          {/* 台报规则卡 */}
          <div className="app-card">
            <h3>{t('台报规则')}</h3>
            <div style={{ fontSize: 13, fontWeight: 650 }}>{data.thresholds.rule}</div>
            <div className="mono" style={{ marginTop: 6, color: 'var(--muted)' }}>
              {tf(
                `z 窗口 ${data.thresholds.z_window_days} 天 · 开仓阈值 |z|≥${data.thresholds.open} · 平仓阈值 |z|≤${data.thresholds.close}`,
                `z window ${data.thresholds.z_window_days} days · entry threshold |z|≥${data.thresholds.open} · exit threshold |z|≤${data.thresholds.close}`,
              )}
            </div>
          </div>

          {/* 五策略状态表 */}
          <div className="app-card">
            <h3>{t('五策略状态')}<span className="kpi-label" style={{ fontWeight: 400 }}>{t('点击行展开近期交易')}</span></h3>
            <div className="table-scroll">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>{t('策略')}</th>
                    <th>{t('一年 z')}</th>
                    <th>{t('状态')}</th>
                    <th>{t('多空腿')}</th>
                    <th>{t('近两年 Sharpe')}</th>
                    <th>{t('近两年年化')}</th>
                    <th>{t('交易次数')}</th>
                  </tr>
                </thead>
                <tbody>
                  {data.strategies.map((s) => {
                    const expanded = openRow === s.id
                    const zWarn = Math.abs(s.z) >= openThreshold
                    const legKeys = [...new Set([s.long, s.short, ...Object.keys(s.legs)])].filter((k) => s.legs[k] !== undefined)
                    return (
                      <Fragment key={s.id}>
                        <tr onClick={() => setOpenRow(expanded ? null : s.id)} style={{ cursor: 'pointer' }}>
                          <td>
                            <span style={{ color: 'var(--muted)', marginRight: 5 }}>{expanded ? '▾' : '▸'}</span>
                            <b>{t(s.name)}</b>
                            <div style={{ fontSize: 11.5, color: 'var(--muted)', marginTop: 2 }}>{s.note}</div>
                          </td>
                          <td>
                            <span className={`mono ${zWarn ? 'status-warn' : ''}`} style={zWarn ? { fontWeight: 700 } : undefined}>
                              {s.z.toFixed(2)}
                            </span>
                          </td>
                          <td><StateBadge state={s.state} /></td>
                          <td>
                            {legKeys.map((k) => {
                              const v = s.legs[k]
                              return (
                                <span key={k} className={`mono ${v >= 0 ? 'pos' : 'neg'}`} style={{ marginRight: 10, whiteSpace: 'nowrap' }}>
                                  {k} {fmtSignedPct(v, 1)}
                                </span>
                              )
                            })}
                          </td>
                          <td className="mono">{s.trailing_2y.sharpe.toFixed(2)}</td>
                          <td className={`mono ${s.trailing_2y.ann >= 0 ? 'pos' : 'neg'}`}>{fmtSignedPct(s.trailing_2y.ann, 1)}</td>
                          <td className="mono">{s.trailing_2y.trades}</td>
                        </tr>
                        {expanded && (
                          <tr>
                            <td colSpan={7} style={{ background: 'var(--bg)' }}>
                              <div className="kpi-label" style={{ marginBottom: 4 }}>{t('近期交易')}</div>
                              {s.recent_trades.length === 0 ? (
                                <div style={{ fontSize: 12, color: 'var(--muted)' }}>{t('近两年无成交记录')}</div>
                              ) : (
                                <table className="data-table" style={{ fontSize: 12 }}>
                                  <thead>
                                    <tr><th>{t('开仓')}</th><th>{t('平仓')}</th><th>{t('方向')}</th><th>{t('盈亏')}</th></tr>
                                  </thead>
                                  <tbody>
                                    {s.recent_trades.map((tr, i) => (
                                      <tr key={i}>
                                        <td className="mono">{tr.opened}</td>
                                        <td className="mono">{tr.closed}</td>
                                        <td>{t(tr.direction)}</td>
                                        <td className={`mono ${tr.pnl_bps >= 0 ? 'pos' : 'neg'}`}>{fmtBps(tr.pnl_bps)}</td>
                                      </tr>
                                    ))}
                                  </tbody>
                                </table>
                              )}
                            </td>
                          </tr>
                        )}
                      </Fragment>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </div>

          {/* 记分牌 + 叠加账本 */}
          <div className="page-grid grid-2">
            <div className="app-card">
              <h3>{t('策略记分牌')}<span className="kpi-label" style={{ fontWeight: 400 }}>{t('按近两年 Sharpe 排序')}</span></h3>
              <Chart
                height={230}
                option={{
                  grid: { left: 118, right: 48, top: 8, bottom: 26 },
                  tooltip: {
                    trigger: 'axis',
                    formatter: (params: any) => {
                      const p = Array.isArray(params) ? params[0] : params
                      const row = [...data.scoreboard].sort((a, b) => b.sharpe - a.sharpe)[p.dataIndex]
                      return `${t(row.name)}<br/>Sharpe ${row.sharpe.toFixed(2)} · ${tf('年化', 'Ann.')} ${row.ann_bps} bp<br/>${tf(`交易 ${row.trades} 次`, `${row.trades} trades`)} · ${t(row.state)}`
                    },
                  },
                  xAxis: {
                    type: 'value',
                    axisLabel: { color: chartTheme(theme).axisLabel, fontSize: 10.5 },
                    splitLine: { lineStyle: { color: chartTheme(theme).grid } },
                  },
                  yAxis: {
                    type: 'category',
                    inverse: true,
                    data: [...data.scoreboard].sort((a, b) => b.sharpe - a.sharpe).map((r) => t(r.name)),
                    axisLabel: { color: chartTheme(theme).axisLabel, fontSize: 11 },
                  },
                  series: [{
                    type: 'bar',
                    barWidth: 14,
                    // 红涨绿跌：正 Sharpe 记红、负 Sharpe 记绿，与本页收益列和全站方向一致
                    data: [...data.scoreboard].sort((a, b) => b.sharpe - a.sharpe).map((r) => ({
                      value: r.sharpe,
                      itemStyle: { color: r.sharpe >= 0 ? SOLID.red : SOLID.green, borderRadius: 3 },
                    })),
                    label: {
                      show: true,
                      position: 'right',
                      fontSize: 10.5,
                      color: chartTheme(theme).axisLabel,
                      formatter: (p: any) => Number(p.value).toFixed(2),
                    },
                  }],
                }}
              />
            </div>

            <div className="app-card">
              <h3>{t('叠加账本')}</h3>
              <Chart
                height={170}
                option={{
                  grid: { left: 44, right: 14, top: 10, bottom: 24 },
                  tooltip: { trigger: 'axis' },
                  xAxis: {
                    type: 'category',
                    data: data.overlay_ledger.dates,
                    axisLabel: { color: chartTheme(theme).axisLabel, fontSize: 10 },
                  },
                  yAxis: {
                    type: 'value',
                    scale: true,
                    axisLabel: { color: chartTheme(theme).axisLabel, fontSize: 10.5 },
                    splitLine: { lineStyle: { color: chartTheme(theme).grid } },
                  },
                  series: [{
                    name: t('叠加净值'),
                    type: 'line',
                    data: data.overlay_ledger.nav,
                    showSymbol: false,
                    lineStyle: { width: 1.6, color: SOLID.bl },
                    itemStyle: { color: SOLID.bl },
                  }],
                }}
              />
              <div className="kpi-label" style={{ marginTop: 8 }}>{t('总敞口使用率')}</div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 4 }}>
                <div style={{ flex: 1, height: 10, background: 'var(--bg)', border: '1px solid var(--line)', borderRadius: 5, overflow: 'hidden' }}>
                  <div
                    style={{
                      width: `${data.overlay_ledger.gross_cap > 0 ? Math.min(100, (data.overlay_ledger.gross_exposure / data.overlay_ledger.gross_cap) * 100) : 0}%`,
                      height: '100%',
                      background: 'var(--teal)',
                    }}
                  />
                </div>
                <span className="mono" style={{ whiteSpace: 'nowrap' }}>
                  {fmtPct(data.overlay_ledger.gross_exposure, 0)}{tf(' / 上限 ', ' / cap ')}{fmtPct(data.overlay_ledger.gross_cap, 0)}
                </span>
              </div>
              <p style={{ margin: '10px 0 0', fontSize: 12, color: 'var(--muted)' }}>{tf('记账口径：', 'Accounting basis: ')}{data.overlay_ledger.accounting}</p>
            </div>
          </div>

          {/* 风控区 */}
          <section>
            <div style={{ borderBottom: '1px solid var(--line)', padding: '6px 0 10px', marginBottom: 14 }}>
              <h2 style={{ margin: 0, fontSize: 17 }}>{t('风控官')}</h2>
              <p style={{ margin: '4px 0 0', fontSize: 12.5, color: 'var(--muted)' }}>
                {t('核心配置账本的风控结果，利差台不改变它')}
              </p>
            </div>

            <div className="page-grid grid-3">
              {/* a. core_guardrails */}
              <div className="app-card">
                <h3>{t('核心风控闸门')}</h3>
                <div className="kpi-label" style={{ marginBottom: 6 }}>{t('核心配置账本的风控结果，利差台不改变它')}</div>
                {data.core_guardrails.map((g) => (
                  <div key={g.rule} style={{ padding: '6px 0', borderTop: '1px solid var(--line)' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, alignItems: 'baseline' }}>
                      <b style={{ fontSize: 12.5 }}>{t(g.label)}</b>
                      <span className={g.triggered ? 'status-warn' : 'status-ok'} style={{ fontSize: 12, whiteSpace: 'nowrap' }}>
                        {g.triggered ? t('⚠ 触发') : t('✓ 通过')}
                      </span>
                    </div>
                    <div style={{ fontSize: 11.5, color: 'var(--muted)', marginTop: 2 }}>{g.detail}</div>
                  </div>
                ))}
              </div>

              {/* b. core_class_weights */}
              <div className="app-card">
                <h3>{t('核心账本大类总敞口')}</h3>
                {CLASS_ORDER.filter((c) => data.core_class_weights[c] !== undefined).map((c) => {
                  const v = data.core_class_weights[c]
                  return (
                    <div key={c} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 0' }}>
                      <span style={{ width: 40, fontSize: 12.5, flexShrink: 0 }}>{t(CLASS_META[c]?.label ?? c)}</span>
                      <div style={{ flex: 1, height: 10, background: 'var(--bg)', border: '1px solid var(--line)', borderRadius: 5, overflow: 'hidden' }}>
                        <div style={{ width: `${classMax > 0 ? (v / classMax) * 100 : 0}%`, height: '100%', background: CLASS_META[c]?.color ?? 'var(--teal)' }} />
                      </div>
                      <b className="mono" style={{ width: 48, textAlign: 'right', flexShrink: 0 }}>{fmtPct(v, 1)}</b>
                    </div>
                  )
                })}
                <div className="kpi-label" style={{ marginTop: 8 }}>{t('核心配置账本 5 大类目标权重')}</div>
              </div>

              {/* c. constraints */}
              <div className="app-card">
                <h3>{t('叠加台约束')}</h3>
                <div style={{ display: 'flex', justifyContent: 'space-between', padding: '7px 0', borderBottom: '1px solid var(--line)', fontSize: 12.5 }}>
                  <span>{t('允许净做空')}</span>
                  <b>{data.constraints.allow_net_short ? t('是') : t('否')}</b>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', padding: '7px 0', borderBottom: '1px solid var(--line)', fontSize: 12.5 }}>
                  <span>{t('总敞口上限')}</span>
                  <b className="mono">{fmtPct(data.constraints.gross_exposure_cap, 0)}</b>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', padding: '7px 0', borderBottom: '1px solid var(--line)', fontSize: 12.5 }}>
                  <span>{t('叠加风险预算')}</span>
                  <b className="mono">{fmtPct(data.constraints.overlay_risk_budget, 0)}</b>
                </div>
                <p style={{ margin: '10px 0 0', fontSize: 12, color: 'var(--muted)', lineHeight: 1.6 }}>
                  {tf('账本隔离：', 'Ledger isolation: ')}{data.constraints.isolation}
                </p>
              </div>
            </div>

            {/* d. 宏观事件日历 */}
            <div className="app-card" style={{ marginTop: 14 }}>
              <h3>{t('宏观事件日历')}</h3>
              <div className="table-scroll">
                <table className="data-table">
                  <thead>
                    <tr><th>{t('日期')}</th><th>{t('事件')}</th><th>{t('距今')}</th></tr>
                  </thead>
                  <tbody>
                    {data.events.map((e, i) => (
                      <tr key={i}>
                        <td className="mono">{e.date ?? '—'}</td>
                        <td>{e.name ? t(e.name) : '—'}</td>
                        <td className="mono">
                          {e.days_to === undefined ? '—' : e.days_to === 0 ? t('今日') : tf(`${e.days_to} 天后`, `in ${e.days_to} days`)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="kpi-label" style={{ marginTop: 8 }}>{data.legacy_note}</div>
            </div>
          </section>
        </div>
      )}
    </div>
  )
}
