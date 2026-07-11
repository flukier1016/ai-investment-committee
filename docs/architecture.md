# 架构与运行说明

## 一句话

五方法三层：Risk Parity 唯一战略底仓 → Time Series Momentum / Merrill Lynch
Investment Clock / Equity Risk Premium 三种战术观点 → Black-Litterman Model
贝叶斯融合 → 风控投影 → 不可变 Decision Record；九个前端模块消费同一份结果。

## 运行

```bash
make install   # backend: uv sync；frontend: npm install
make data      # 重新生成确定性 Demo 数据（可选，仓库已含生成结果）
make dev       # 后端 8000 + 前端 5173
# 打开 http://localhost:5173
make test      # 后端 28 项测试（含 15 项核心数据验收）
make e2e       # Playwright 交互测试（自动拉起前后端）
make build     # 构建 frontend/dist（backend 同端口托管，单进程部署）
```

## 端到端计算链路

```
data/demo（合成行情 / 宏观(point-in-time 发布日) / ERP 输入）
  → MarketSlice as-of 切片 + sha256 输入指纹        market_data.py
  → 协方差（对数收益 + 线性收缩 + 年化）             covariance.py
  → Risk Parity 战略底仓（四大类风险预算 ERC
    + 桶内逆波动率 + 约束式投影）                   risk_parity.py
  → TSMOM / Clock / ERP 战术信号（TracedSignal，
    无效资产显式 abstain）                          signals.py
  → 观点标准化：P 腿归一、Q = P·π + 信号倾斜、
    Ω = (1-c)/c · 3τ·PΣPᵀ（确定性映射）             views.py
  → Black-Litterman：π = δΣw_RP，μ_BL 后验，
    He-Litterman λ + 方向纪律 + Idzorek 倾斜上限     black_litterman.py
  → 风控投影：min ‖w−w_uncon‖_{Σ+εI} s.t. 约束集
    （long-only/单资产/桶/大类/债券底仓/波动预算）    guardrails.py (CVXPY)
  → 27 明细资产 → 7 桶 → 5 大类（严格闭合）
  → 归因：prior + Σ观点段 + 风控段 = target          pipeline.py
  → 不可变 DecisionRecord（JSON 落库，输入指纹幂等）  services/store.py
```

**确定性承诺**：所有数字由代码计算；相同输入（数据指纹 + 配置指纹）产生相同
decision_id 与相同结果。LLM 不参与任何数字生成（Demo 中 `llm_used: false`）。

### 记录的构造纪律（非教科书部分，全部落库可审计）

1. **约束式 Risk Parity**：底仓构建时即满足单资产/桶上限，否则超低波动资产
   （1-3 年国债）会吸走远超上限的权重，迫使风控层每次对底仓做大手术。
2. **Q 锚定 π**：绝对观点 Q = P·π + 信号倾斜。不锚定时“看多但 Q 低于均衡收益”
   的观点在贝叶斯融合中实际是看空。
3. **方向纪律**：联合求解下被同资产更强观点支配的观点 λ 会反号；此时置 0 记
   “未采纳”，不让观点反向出现在归因里。
4. **Idzorek 倾斜上限**：低波动腿的 λ 天然放大，截断到 ±max_view_tilt（默认 5pp）。
5. **预算中性归因**：c_k = λ_k(P_k − ΣP_k·w_prior)，每条观点贡献预算中性，
   prior + Σc_k 严格加总为 1。
6. **风控段入账**：投影产生的裁剪量作为归因的 `guardrail` 段，闭合不被破坏。

## 目录

```
backend/app/domain    信号、BL、优化、风控、回测、日更、利差台
backend/app/api       FastAPI 11 端点
backend/app/schemas   Pydantic 数据契约（TracedSignal/View/DecisionRecord/Config）
backend/app/services  DecisionRecord 存储 / bundle 组装 / 周报
data/demo             Demo 输入与情景（+ legacy/ 旧页迁移 fixture）
data/runs             运行期决策记录与派生缓存（gitignore，可重算）
frontend/src/pages    9 个模块页面（TracePage 为旗舰）
tests/backend         15 项核心验收 + API 测试
tests/e2e             Playwright 交互测试
scripts               Demo 数据生成器 / 旧页数据抽取器
docs                  本文档、数据迁移说明、API 样例
```

## API

交互式文档：后端启动后访问 `http://localhost:8000/docs`。
真实响应样例：`docs/api_samples/*.json`。

| 端点 | 用途 |
|---|---|
| POST /api/decisions/run | 执行完整链路，落 DecisionRecord，返回 DecisionTraceBundle |
| GET /api/decisions[/{id}[/record]] | 决策索引 / bundle / 原始记录 |
| GET /api/overview · /api/cockpit | 总览 / 驾驶舱（与溯源同数据源） |
| POST /api/backtest/run | walk-forward 回测（按配置指纹缓存） |
| GET /api/daily | 日更模拟（免交易带） |
| GET /api/weekly-report | 周度纪要（结构化 + Markdown） |
| GET /api/spread-desk | 利差台 + 风控官（独立叠加账本） |
| GET /api/scenarios/compare | 双情景 as-of 重算对比 |
| GET /api/meta · /api/config/defaults · /api/health | 元数据 |

## Demo 数据

`scripts/generate_demo_data.py` 固定种子生成 2020-01 ~ 2026-07 的 27 资产
日频总回报面板，内置 8 段宏观 regime（新冠崩盘→再通胀→扩张→滞胀→衰退触底→
复苏→过热→复苏确认），月频 PMI/CPI 带发布日（point-in-time），三个 Demo 情景
在不同 as-of 产生方向不同的真实信号。合成数据仅用于演示，非任何真实行情。
