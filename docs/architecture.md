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
make test      # 后端完整验收测试
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
  → 桶立场：target − Risk Parity prior 映射为五档      stance.py
  → 不可变 DecisionRecord（JSON 落库，输入指纹幂等）  services/store.py
```

**确定性承诺**：所有数字由代码计算；相同输入（数据指纹 + 配置指纹）产生相同
decision_id 与相同结果；配置默认值也经 Pydantic 类型校验，避免直跑/缓存
路径因 int/float 表示差异产生不同指纹。LLM 不参与任何数字生成（Demo 中
`llm_used: false`）。

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
7. **五档立场单一口径**：以落库精度的 `target − Risk Parity prior` 为唯一
   输入，在 ±0.4pp / ±2pp 处映射为显著超配/超配/中性/低配/显著低配；
   权重先按落库十进制值相减，边界值进入外档。映射只定义在 `stance.py`，
   周报、L3 与结果账本只消费
   `DecisionRecord.bucket_stances`；旧记录缺字段时由同一函数确定性补算。

## 目录

```
backend/app/domain    信号、BL、优化、风控、回测、日更、利差台
backend/app/api       FastAPI 端点
backend/app/cli.py    Typer 直调命令行（run/backtest/trace/report）
backend/app/schemas   Pydantic 数据契约（TracedSignal/View/DecisionRecord/Config）
backend/app/services  DecisionRecord 存储 / bundle 组装 / 决策纪要 / 周报
Dockerfile/compose     Node 构建 + Python/uv 非 root 单服务及运行卷
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
| GET /api/decisions/{id}/report | 从不可变记录导出确定性 Markdown 决策纪要 |
| GET /api/overview · /api/cockpit | 总览 / 驾驶舱（与溯源同数据源） |
| POST /api/backtest/run | walk-forward 回测（按配置指纹缓存） |
| GET /api/daily | 日更模拟（免交易带） |
| GET /api/weekly-report | 周度纪要（结构化 + Markdown） |
| GET /api/spread-desk | 利差台 + 风控官（独立叠加账本） |
| GET /api/scenarios/compare | 双情景 as-of 重算对比 |
| GET /api/meta · /api/config/defaults · /api/health | 元数据 |

决策纪要由 `services/report.py` 只读 `DecisionRecord` 与静态资产宇宙生成，不重查
行情、不重跑引擎、不写文件。报告顺序固定为摘要 → 5 大类/7 桶/27 资产三层
权重 → 逐观点 P/Q/置信度与归因 → 风控与闭合 → 完整血缘索引，相同记录输出
逐字节一致。桶/大类中文名由 `domain/labels.py` 单一定义。

## CLI

`invest` 由 `backend/pyproject.toml` 注册到 `app.cli:app`。`run` 与 API 使用同一
pipeline、原子存储与结果账本生命周期，`backtest` 直调 walk-forward
回测；两者都不通过 HTTP。`trace` 和 `report` 只读已落库的不可变
`DecisionRecord`，前者按桶归因 → 观点 → 信号 → 输入哈希下钻，后者
原样复用确定性 Markdown 纪要，两者都不重查行情或重跑引擎。

## 容器化

`Dockerfile` 保留引擎的仓库相对路径契约：`/app/backend/app` 向上回到
`/app`，同根读取 `data/demo`、`frontend/dist`，仅向 `data/runs` 写入。
前端由 Node 22 阶段构建，运行阶段为 Python 3.12 slim + 官方固定版本 uv；
项目保持 editable 源码安装，避免 `__file__` 落到 site-packages 后破坏上述路径。

运行用户固定 UID/GID 10001，根文件系统只读，`data/runs` 预建为可写目录并
由 Compose 本地命名卷持久化（不挂载整个 `data`，防止遮住 Demo 输入）。健康
检查同时验证 `/api/health`、Demo manifest 可读与运行卷可写。构建参数
`APP_REVISION` 经格式校验后进入 `code_version`，即使构建上下文排除 `.git`
也保留提交血缘。

前端生产托管的 SPA fallback 仅适用于 GET/HEAD、非 `/api/`、无扩展名路由；
缺失静态资源与未知 API 仍返回 404，不会被 `index.html` 伪装成成功。

## Demo 数据

`scripts/generate_demo_data.py` 固定种子生成 2020-01 ~ 2026-07 的 27 资产
日频总回报面板，内置 8 段宏观 regime（新冠崩盘→再通胀→扩张→滞胀→衰退触底→
复苏→过热→复苏确认），月频 PMI/CPI 带发布日（point-in-time），三个 Demo 情景
在不同 as-of 产生方向不同的真实信号。合成数据仅用于演示，非任何真实行情。


## 借鉴 TradingAgents 的工程与产品补强（2026-07）

对照 [TauricResearch/TradingAgents](https://github.com/tauricresearch/tradingagents)
（arXiv:2412.20138）做了差距分析后引入 8 项改进。其多 agent 自由辩论/反思记忆
是 V3 第七节点名的 Prompt Infection 攻击面，刻意不搬；引入的是其工程纪律的
确定性版本：

1. **决策-结果闭环账本**（`services/outcomes.py`，`GET /api/outcomes`）：
   pending→resolved 生命周期；到期用 point-in-time 价格解算实现收益、
   vs 等权/60·40 α、逐观点方向命中（P 加权超额收益方向 vs 观点倾斜方向）、
   五档桶立场方向命中（中性不计分）与象限命中；回测 55 期一键回填。
   账本读-改-原子替换全段由线程锁 + Unix 文件锁串行化，防止并发不同决策
   相互覆盖。对应 V3 7.4 outcomes analysis。
2. **委员会正反检验**（`services/committee.py`，bundle.committee_review）：
   TradingAgents 辩论形态的去 LLM 化——质疑/回应论据全部由规则从
   DecisionRecord 抽取（截断/未采纳/方向冲突/风控触发/输入降级），
   每条可回跳血缘，裁决由计分规则给出。论据池同时派生固定顺序的激进/保守/
   中性三视角：激进只读 `portfolio_vol / target_vol`；保守复用
   `guardrails.asset_caps()` 并和中国股票桶、权益大类上限一起找最小绝对余量；
   中性以 `0.5 × Σ|target − Risk Parity prior|` 作为理论单边换手代理，并用
   `0.5 × Σ|bucket target − attribution.prior|` 量化桶级可解释比例。记录没有
   漂移后当前持仓，因此该代理不得表述为实际成交。三视角只按硬边界与 1e-6
   闭合容差分类，不另造经验阈值，不改裁决计分、权重、DecisionRecord 或
   decision_id；前端只展示后端数值，三卡共用中性色。
3. **防前视双重断言**：load_slice 末尾对价格/宏观/ERP 三路数据硬断言
   不含未来（不信任上游预过滤）。
4. **类型化数据错误**：NoData/InsufficientHistory/Stale/ProviderNotConfigured
   异常树；API 按类型返回结构化 400。
5. **核心/可选数据分级**：价格（核心）缺失整次中止；战术信号（可选）缺失
   显式弃权、BL 退回先验、`degraded_inputs` 入记录并在前端标注。
6. **LLM 结构化输出契约预埋**（`schemas/llm.py` + `services/llm_views.py`）：
   象限枚举 + 置信度档位（数值由代码映射进 Ω）+ citations 防幻觉校验；
   任何失败降级为 abstain，绝不回退自由文本。当前零 LLM 依赖。
7. **测试盲区补强**：+31 项（输入变坏弃权、参数微扰有界、不可行约束
   响亮失败、回测口径不变量、存储容错、同形异义字对抗样本）。
8. **CI 门禁**（`.github/workflows/ci.yml`）：后端验收 / 前端构建+e2e /
   确定性承诺 CI 级断言（重跑数据生成器 diff、同 as-of 重放 decision_id 不变）。
