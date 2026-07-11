import { Navigate, Route, Routes } from 'react-router-dom'
import Layout from './components/Layout'
import OverviewPage from './pages/OverviewPage'
import ConfigPage from './pages/ConfigPage'
import TracePage from './pages/TracePage'
import CockpitPage from './pages/CockpitPage'
import ScenariosPage from './pages/ScenariosPage'
import BacktestPage from './pages/BacktestPage'
import DailyPage from './pages/DailyPage'
import WeeklyPage from './pages/WeeklyPage'
import SpreadDeskPage from './pages/SpreadDeskPage'

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        {/* V3 第5.5节：三层溯源看板是进入系统后的主页面 */}
        <Route path="/" element={<Navigate to="/trace" replace />} />
        <Route path="/overview" element={<OverviewPage />} />
        <Route path="/config" element={<ConfigPage />} />
        <Route path="/trace" element={<TracePage />} />
        <Route path="/cockpit" element={<CockpitPage />} />
        <Route path="/scenarios" element={<ScenariosPage />} />
        <Route path="/backtest" element={<BacktestPage />} />
        <Route path="/daily" element={<DailyPage />} />
        <Route path="/weekly" element={<WeeklyPage />} />
        <Route path="/spread-desk" element={<SpreadDeskPage />} />
      </Route>
    </Routes>
  )
}
