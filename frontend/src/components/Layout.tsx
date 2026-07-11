import { NavLink, Outlet } from 'react-router-dom'
import { useScenario } from '../scenario'
import { t, usePrefs } from '../prefs'

const NAV = [
  { path: '/overview', label: '总览', index: '01' },
  { path: '/config', label: '配置', index: '02' },
  { path: '/trace', label: '决策溯源', index: '03', flagship: true },
  { path: '/cockpit', label: '组合驾驶舱', index: '04' },
  { path: '/scenarios', label: '情景回放', index: '05' },
  { path: '/backtest', label: '回测分析', index: '06' },
  { path: '/daily', label: '日更驾驶舱', index: '07' },
  { path: '/weekly', label: '周度纪要', index: '08' },
  { path: '/spread-desk', label: '利差台与风控', index: '09' },
]

export function ScenarioPicker() {
  const { scenarioId, setScenarioId, scenarios } = useScenario()
  usePrefs()
  return (
    <label className="scenario-picker">
      {t('当前情景')}
      <select value={scenarioId} onChange={(e) => setScenarioId(e.target.value)}>
        {scenarios.map((s) => (
          <option key={s.id} value={s.id}>{t(s.label)}</option>
        ))}
      </select>
    </label>
  )
}

export default function Layout() {
  const { theme, lang, toggleTheme, toggleLang } = usePrefs()
  return (
    <div className="app-shell">
      <nav className="app-nav">
        <div className="brand-block">
          <h1>{t('智策 AI投委会')}</h1>
          <span className="tag">{t('五方法三层 · Demo 研究推演')}</span>
          <div className="pref-toggles">
            <button className="pref-btn" onClick={toggleTheme}
              title={theme === 'light' ? t('夜间') : t('日间')}
              aria-label={theme === 'light' ? t('夜间') : t('日间')}>
              {theme === 'light' ? '🌙' : '☀️'} {theme === 'light' ? t('夜间') : t('日间')}
            </button>
            <button className="pref-btn" onClick={toggleLang}
              title={lang === 'zh' ? 'Switch to English' : '切换到中文'}
              aria-label={lang === 'zh' ? 'English' : '中文'}>
              {lang === 'zh' ? 'EN' : '中'}
            </button>
          </div>
        </div>
        <div className="nav-group-label">{t('导航')}</div>
        {NAV.map((item) => (
          <NavLink
            key={item.path}
            to={item.path}
            end={false}
            className={({ isActive }) => `${isActive ? 'active' : ''} ${item.flagship ? 'flagship' : ''}`}
          >
            <span className="nav-index">{item.index}</span>
            {t(item.label)}
            {item.flagship && <span style={{ marginLeft: 'auto', fontSize: 10, color: 'var(--bl)' }}>{t('旗舰')}</span>}
          </NavLink>
        ))}
      </nav>
      <main className="app-main">
        <Outlet />
      </main>
    </div>
  )
}
