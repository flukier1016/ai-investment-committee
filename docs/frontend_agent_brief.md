# 前端页面实现简报（供并行实现使用）

## 共享基础设施（已存在，不得修改）

- `frontend/src/api.ts` — 全部 API 调用器 + localStorage 配置/情景读写（savedConfig/saveConfig/savedScenario）
- `frontend/src/types.ts` — TS 类型（DecisionTraceBundle、TracedSignal、BLView、AllocationConfig 等）
- `frontend/src/meta.ts` — 方法名/方法色/桶色/大类色/格式化器（fmtPct/fmtPp/fmtSignedPct/fmtDecisionId/fmtAsof、BUCKET_META/CLASS_META/METHOD_META/BUCKET_SOLID/METHOD_SOLID/SOLID、BUCKET_ORDER/CLASS_ORDER、LAYER_ZH/VIEW_TYPE_ZH）
- `frontend/src/scenario.tsx` — useScenario() 全局情景上下文
- `frontend/src/components/Layout.tsx` — 导航壳 + ScenarioPicker 组件（可 import 到页头）
- `frontend/src/components/Chart.tsx` — ECharts 包装 `<Chart option={...} height={320}/>`
- `frontend/src/styles/mock.css` — 设计令牌与旗舰页样式（CSS 变量：--teal/--cyan/--amber/--slate/--rose/--violet/--cash/--method-*/--bl/--ink/--muted/--line/--paper/--red/--green）
- `frontend/src/styles/app.css` — 应用壳类：.page-head/.page-grid/.grid-2/.grid-3/.grid-4/.app-card/.kpi-value/.kpi-label/.status-ok/.status-warn/.data-table/.table-scroll/.loading-block/.error-block/.mono/.demo-banner

## API 响应样例（真实抓取，字段以此为准）

`docs/api_samples/*.json`：meta / config_defaults / decision_bundle / overview / cockpit / backtest / daily / weekly / spread_desk / compare / decisions_index

## 硬性设计规则（验收标准，违反即不通过）

1. 方法名只用英文全称：Risk Parity / Time Series Momentum / Merrill Lynch Investment Clock / Equity Risk Premium / Black-Litterman Model。可见区域出现 CTA/TSMOM/ERP/BL 即不通过。方法色固定（META 里取）。
2. 中文业务标签与单位；`decision_id`/`asof` 用 fmtDecisionId/fmtAsof 格式化为中文；机器 ID 只放详情/tooltip/mono 小字。
3. 资产桶/大类颜色用 BUCKET_META/CLASS_META（权益青绿、现金石墨灰，不得混用近似色）。涨跌用红涨绿跌 + 正负号（.pos/.neg 类）。状态不能只靠颜色，必须同时有文字或符号。
4. 页面数字全部来自 API，前端不重算业务数字（求和校验展示除外）。
5. 不出现机构名称；页脚或页头带「Demo 演示数据 · 非投资建议」提示（.demo-banner）。
6. 桌面三列网格（.grid-3），窄屏自动纵排（app.css 已处理）；不得横向溢出。
7. 每页顶部用 `.page-head`：左侧 h2 标题 + p.page-sub 说明，右侧放 `<ScenarioPicker/>`（从 components/Layout import）需要情景切换的页面都要放。
8. 加载态 `.loading-block`，错误态 `.error-block`（展示 err.message）。
9. 比例条：同类比例条长度基准一致（同一 max 值），不用超大 KPI 数字（kpi-value 22px 已定）。

## 页面数据流公约

- 情景：`const { scenarioId, scenario } = useScenario()`；scenarioId 变化时重新拉数据（useEffect 依赖）。
- 配置：`savedConfig()` 返回用户在配置页保存的 AllocationConfig 或 null；POST 类接口把它传进去（api.runDecision(scenarioId, savedConfig())、api.backtest(savedConfig())）。
- 权重展示顺序用 BUCKET_ORDER / CLASS_ORDER。
