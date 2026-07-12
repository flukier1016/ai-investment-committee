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
路径因 int/float 表示差异产生不同指纹。默认关闭 LLM 时有效配置 payload 与历史
字节完全相同；启用时 provider/model/temperature 及重试、超时、固定 endpoint
版本进入配置指纹，但 API key 永不进入。LLM 不直接生成任何权重、收益率或 Ω
数字（Demo 中 `llm_used: false`）。

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
backend/app/llm       固定 provider 注册表 / 惰性 transport / 内容寻址 trace
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

新闻时间边界独立定义在 `domain/news.py::news_asof_filter()`，暂不接入
MarketSlice、决策指纹或权重链。带有效 `publish_ts` 的文章只有在
`publish_ts <= asof` 时可见；无时间文章在回测中 fail-closed 剔除，live 模式
才原样保留；非空但非法的时间戳响亮失败，未来调用方必须降级为 abstain。
过滤保持输入顺序与重复项，返回深拷贝，不读取当前时间。带 offset 的时间统一
转 UTC；naive/date-only 按固定 UTC+8 的当日 00:00 解释，不依赖宿主机时区。

`data/demo/legacy/news_library.json` 的 195 条展示资讯只有日期，因此保留
`published` 并补 `23:59:59Z` 的保守日末 `publish_ts` 代理；该策略不代表真实
发布时间，并写入 fixture 元数据。接真实新闻/LLM 前的固定顺序必须是
`news_asof_filter → 编号上下文 → 结构化象限契约`，过滤前文本不得进入 prompt。

## LLM 客户端瘦身基建（Phase 3 前置）

`backend/app/llm/` 只保留一套 OpenAI-compatible Chat Completions transport，
provider 注册表是不可变的三项：`openai_compatible`、`deepseek`、`ollama`。
三者 endpoint 固定，不开放请求级 `base_url`，避免第四类隐式 provider 与 SSRF；
云端 key 只从约定环境变量读取，本地 Ollama 使用其官方兼容层要求但会忽略的占位
key。默认 `uv sync` 不安装 OpenAI SDK，只有 `uv sync --extra llm` 才安装；SDK
在 build client 时惰性导入，`max_retries` 和有界 timeout 原样透传，外层不重试。

共同兼容面选择 `response_format={"type":"json_object"}`，client 不暗加 system
prompt；JSON 内容随后必须通过调用方给定的 Pydantic schema。这个取舍低于 OpenAI
专属 JSON Schema 的服务端严格度，但同时覆盖 DeepSeek/Ollama 明确承诺的 JSON
mode；空内容、截断、自由文本、非法 JSON 或 schema 不符均抛类型化错误，统一进入
既有 abstain 边界。参考：[OpenAI Chat Completions JSON mode](https://platform.openai.com/docs/api-reference/chat)、
[DeepSeek JSON Output](https://api-docs.deepseek.com/guides/json_mode/)、
[Ollama OpenAI compatibility](https://docs.ollama.com/api/openai-compatibility)。

可信 `LLMRuntimeConfig` 不属于公开 `AllocationConfig`，防止匿名 API 请求借服务器
密钥触发计费；只有 provider/model/temperature/max_retries/timeout 与 ProviderSpec
版本合并进 effective config。关闭时不增加任何字段，保留旧配置 hash、默认
decision_id 与旧记录 JSON 形状；启用时使用更长配置摘要降低模型字符串碰撞面。

每个逻辑调用的 `trace_id` 由 provider/spec/model/temperature/retry/timeout、调用键、
prompt SHA、response schema SHA 与允许引用集合共同做 canonical SHA-256，禁止 UUID
和墙钟进入 ID。`data/runs/llm_traces/` 使用 0700 目录、0600 文件、同目录完整 UUID
临时名 + `os.replace`；同 trace 跨线程/进程锁住“读缓存 → 调用 → 写入”，首次结果
胜出，后续直接重放。trace 仅保存脱敏 prompt 与已验证结构化输出，不保存 SDK 原始
自由文本、隐藏推理或密钥；同 ID 不同输出响亮报碰撞，损坏文件不覆盖。

本阶段仍不从 pipeline 发起任何 LLM 网络请求，DecisionRecord 的 `llm_traces` 继续
为空。下一项接入真实象限时必须复用 trace cache，并把所选 trace/output SHA 纳入
决策输入血缘；否则空缓存机器上的首次非确定响应仍可能与既有 decision_id 冲突。


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
6. **LLM 结构化输出契约与可选客户端基建**（`schemas/llm.py`、
   `services/llm_views.py`、`llm/`）：
   象限枚举 + 置信度档位（数值由代码映射进 Ω）+ citations 防幻觉校验；
   任何失败降级为 abstain，绝不回退自由文本。默认路径零 LLM 依赖；可选 SDK
   只提供固定三 provider 的 JSON transport，本阶段不接决策链。
7. **测试盲区补强**：+31 项（输入变坏弃权、参数微扰有界、不可行约束
   响亮失败、回测口径不变量、存储容错、同形异义字对抗样本）。
8. **CI 门禁**（`.github/workflows/ci.yml`）：后端验收 / 前端构建+e2e /
   确定性承诺 CI 级断言（重跑数据生成器 diff、同 as-of 重放 decision_id 不变）。
