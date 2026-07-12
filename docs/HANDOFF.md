# 项目交接 · 给下一位 AI 工程师（Codex）

> 你接手的是一个**可运行、已通过 CI 的完整项目**，不是毛坯。你的任务是在不破坏
> 既有纪律的前提下持续迭代。先完整读完本文件再动手。

## 一、项目是什么

「智策 AI 投委会」——五方法三层的资产配置决策系统 Demo：

```
Risk Parity（唯一战略底仓）
  + Time Series Momentum / Merrill Lynch Investment Clock / Equity Risk Premium（战术观点）
  → Black-Litterman Model（贝叶斯融合）
  → CVXPY 风控投影 → 27 明细资产 / 7 桶 / 5 大类 → 不可变 DecisionRecord
```

- 仓库：`flukier1016/ai-investment-committee`（GitHub，main 分支直接开发，CI 必须绿）
- 运行：`make install && make dev`（后端 :8000，前端 :5173）；`make test`（后端 61 项）；`make e2e`（Playwright 24 项）
- 技术栈：FastAPI + NumPy/SciPy/CVXPY + Pydantic v2 / React + Vite + TS + ECharts / uv + npm

## 二、铁律（违反任何一条 = 改动不合格）

1. **所有数字由确定性代码计算**。LLM（当前完全未接入）将来只允许：读新闻→输出
   象限枚举+置信度档位、生成叙事解释。LLM 永远不产权重/收益率/Ω/λ。
   契约已预埋在 `backend/app/schemas/llm.py` + `backend/app/services/llm_views.py`，
   任何 LLM 失败路径必须降级为 abstain（弃权），**绝不回退自由文本**。
2. **确定性与幂等**：相同输入（数据指纹+配置指纹）必须产生相同 decision_id 与
   逐字节相同的结果。CI 里有专门断言。不要在计算链路引入时钟、随机数、字典序
   不稳定的迭代。
3. **闭合不可破**：27 资产权重和=1；聚合到 7 桶=1；聚合到 5 大类=1；
   每桶 `prior + Σ观点段 + 风控段 = target`（容差 1e-6）。舍入用最大余数法归还残差。
4. **展示层五个方法名只用英文全称**：Risk Parity / Time Series Momentum /
   Merrill Lynch Investment Clock / Equity Risk Premium / Black-Litterman Model。
   可见区域出现 CTA/TSMOM/ERP/BL 缩写即验收不通过（e2e 有断言）。
   方法固定色：绿/蓝/金/玫红/蓝灰（CSS 变量 `--method-*`、`--bl`）。
5. **红涨绿跌**（中国惯例），正负号与文字必须与颜色双通道并存。
6. **缺数据弃权，不硬凑**：战术信号输入缺失 → 显式 abstain → `degraded_inputs`
   入记录；价格（核心输入）缺失 → 类型化异常整次中止。
7. **文件写入一律原子**（唯一临时名 + `os.replace`）。我们在 CI 上抓过两次
   并发半写竞态，回归测试在 `test_robustness.py` / `test_outcomes_committee.py`。
8. **前端只渲染不重算**：所有业务数字来自 API；前端允许的唯一计算是展示性
   加总校验。
9. **i18n**：界面中文串为词典键（`frontend/src/i18n/dict-*.ts`），EN 缺项回退中文；
   引擎生成的叙事长句保持中文。新增 UI 字符串必须包 `t()`/`tf()` 并补词条。
   页面顶层组件必须调用 `usePrefs()` 订阅切换。
10. **主题**：颜色一律走 CSS 变量（含 `--surface-1..4`），`[data-theme=dark]`
    有整套暗色 token；不要写死 hex。ECharts 颜色用 `meta.ts` 的 SOLID 常量。

## 三、权威文档优先级（冲突时从上往下服从）

1. `docs/reference/AI资产配置投委会_五方法三层_AgentSKILL_V3.md` —— 算法、字段、
   血缘、风控、审计的唯一权威（重点：第 3/5/7/8 节）
2. `docs/reference/AI前端实现交接_三层溯源看板.md` —— 决策溯源页的验收标准（第 8 节）
3. `docs/architecture.md` —— 当前实现的链路与「非教科书构造纪律」清单
   （方向纪律、Q 锚定 π、Idzorek 截断、预算中性归因、约束式 RP——改引擎前必读）
4. `docs/data_migration.md` —— 旧静态页数据的迁移与废弃口径

## 四、代码地图

```
backend/app/domain/
  market_data.py   point-in-time 切片 + 输入指纹 + 类型化错误(DataError树) + 防前视断言
  covariance.py    对数收益 → 线性收缩 → 年化
  risk_parity.py   四大类风险预算 ERC + 桶内逆波动率 + 约束式投影（唯一战略层）
  signals.py       四方法 TracedSignal（含 abstain_signal 工厂、REGIME_TILTS）
  views.py         信号 → P/Q/Ω（Q = P·π + 信号倾斜；Ω=(1-c)/c·3τ·PΣPᵀ）
  black_litterman.py  He-Litterman λ + 方向纪律 + Idzorek 倾斜截断
  guardrails.py    CVXPY 投影 min‖w−w0‖_{Σ+εI}（InfeasibleConstraintsError 响亮失败）
  pipeline.py      端到端编排 + 归因闭合 + DecisionRecord（run_decision_cached 有 lru）
  backtest.py      月度 walk-forward（委员会与基准同成本口径：目标 vs 漂移持仓）
  daily.py / spread_desk.py   日更模拟 / 利差台独立账本
backend/app/services/
  store.py         DecisionRecord JSON 落库（原子写、幂等）
  bundle.py        DecisionRecord → 前端 DecisionTraceBundle（含 committee_review）
  outcomes.py      决策-结果闭环账本（pending→resolved，命中率/α 解算）
  committee.py     正反检验（规则抽取论据，无 LLM）
  weekly.py        周报结构化生成 + Markdown
  llm_views.py     LLM 调用桩（失败即 abstain）
frontend/src/
  pages/TracePage.tsx   旗舰页（~1200 行）：三层看板+血缘抽屉+技术工作台+正反检验
  prefs.tsx / i18n/     主题+语言（langNow 必须渲染期同步，见文件内注释）
  meta.ts               方法/桶/大类色板与语言感知格式化器
tests/backend/          61 项：一文件一防线，文件头注释写明防什么事故
frontend/e2e/           24 项 Playwright（webServer 自动拉起前后端）
scripts/generate_demo_data.py   固定种子合成数据（改动后必须重跑并提交 CSV，CI 会 diff）
```

## 五、已踩过的坑（别再踩）

- **BL λ 爆炸**：低波动腿（中国债券）的观点 λ 天然放大，已用 Idzorek 截断
  （`max_view_tilt`）；被支配观点会反号，已用方向纪律置零。改融合逻辑前先读
  `black_litterman.py` 的注释块。
- **现金是零方差资产**：不许给现金建 BL 观点（退化为硬约束）；投影度量必须
  Σ+εI（纯 Σ 下现金漂移零成本）。
- **象限概率 < 50%**：时钟观点强度锚定均匀先验 0.25（`(prob−0.25)/0.75`），
  不要改回 `(prob−0.5)`——会导致观点方向反转（历史 bug）。
- **Q 必须锚定 π**：绝对观点 Q = P·π + 倾斜；裸 Q 会让"看多但低于均衡收益"
  的观点实际做空。
- **落库舍入**：权重 6 位小数 + 最大余数法；桶/大类从舍入后明细聚合。
- **并发写文件**：唯一临时名 + os.replace，已有回归测试。
- **前端语言切换**：`prefs.tsx` 的 `langNow = lang` 必须在 Provider 渲染期执行
  （useEffect 太晚，子组件会用旧语言渲染）。
- **Playwright/ESM**：e2e 与 node 脚本必须放在 `frontend/` 内（模块解析）；
  Chromium 版本要与 @playwright/test 匹配（`npx playwright install chromium`）。
- **schema 演进**：DecisionRecord 加字段必须带默认值（旧 JSON 记录要能加载，
  有 roundtrip 测试）。

## 六、每次改动的交付门禁

1. `cd backend && uv run pytest ../tests/backend -q` → 全绿（当前 61 项）
2. `cd frontend && npm run build` → 零错误
3. `cd frontend && npx playwright test` → 全绿（当前 24 项；需先无 8000/5173 占用）
4. 新功能 → 新增对应测试（沿用「一文件一防线 + 头注释写防什么」风格）
5. commit 信息中文、说清动机与影响面；push 后确认 GitHub Actions 三个 job 绿
6. 引擎行为变化 → 同步更新 `docs/architecture.md`；UI 字符串变化 → 补 i18n 词条

## 七、待迭代任务清单（按优先级，来自 TradingAgents 差距分析）

### 中优先（建议按序做）

1. **五档立场刻度**：`backend/app/domain/stance.py`，
   STANCE_5_TIER =（显著超配/超配/中性/低配/显著低配），由 `target−prior` 的
   delta 阈值（建议 ±0.4pp/±2pp）纯代码映射；DecisionRecord 增 `bucket_stances`
   （带默认值）；weekly.py、前端 L3 徽章、outcomes 命中统计共用。
   验收：单处定义、三个消费点无各自映射；旧记录可加载。
2. **决策纪要导出器**：`backend/app/services/report.py` 的
   `write_decision_report(record) -> markdown`（摘要/三层权重表/逐观点 P/Q/置信度
   与归因/护栏/血缘索引）+ `GET /api/decisions/{id}/report`（text/markdown）；
   顺手把 weekly.py / pipeline.py / committee.py 各自的 BUCKET_ZH 抽到共享模块。
3. **Typer CLI**：`backend/app/cli.py`，pyproject 注册 `invest`；
   `invest run --scenario X --asof D` / `invest backtest` /
   `invest trace <decision_id> [--view <view_id>]`（沿归因→观点→信号→输入哈希
   下钻血缘，这是独有卖点）/ `invest report <id>`（复用第 2 项）。直调 pipeline
   不走 HTTP，Rich Table 输出。
4. **Docker 一键复现**：多阶段 Dockerfile（node 构建 dist → python-slim + uv →
   非 root 用户 + 预建 data/runs 可写目录）+ compose 单服务挂 volume；README 补用法。
5. **风控三视角点评**：激进/保守/中性三个纯函数（波动预算利用率/距上限余量/
   换手相称性）并入 committee.py 论据池，前端三人格卡（用中性色，勿占方法色）。
6. **新闻 point-in-time 契约**：`news_asof_filter(articles, asof, is_backtest)`
   纯函数 + 三段式测试（未来文章剔除/回测无日期剔除/live 保留）；Demo 合成新闻
   加 publish_ts；接真实新闻源前这是红线。
7. **CHANGELOG 纪律**：`docs/CHANGELOG.md` 按里程碑回填（条目引用验收测试名），
   此后每个功能合并同步一条。
8. **LLM 客户端瘦身基建**（做 9 之前）：`backend/app/llm/`——ProviderSpec 注册表
   仅 3 类（openai 兼容云端 / deepseek 类国内端点 / ollama 无钥本地），惰性导入
   保证默认路径零新依赖；LLMTrace 落 `data/runs/llm_traces/`；SDK 原生 max_retries
   透传。provider/model/temperature 进配置指纹。
9. **接入真实 LLM 象限判断**（Phase 3，做完 6+8 再动）：
   `services/llm_views.py` 填桩；prompt 由 `build_asof_context()` 确定性渲染
   （as-of 日期锚定 + 宏观事实块 + 编号新闻块），模板 sha256 进配置指纹；
   输出走既有 QuadrantCall 契约；`test_llm_contract.py` 的对抗样本全部必须过；
   象限结果与确定性 PMI/CPI 方向不自洽时降 confidence 档位（时间序列锚定）。

### 低优先 / 明确不做

- 环境变量配置（pydantic-settings，上 Docker 后再说）；FRED 客户端（接真实数据
  时抄 TradingAgents 的 alias 表模式）；多供应商模型目录/CLI 交互选择器（不做）；
  **多 agent 自由文本辩论 / LLM 反思记忆 / LangGraph checkpoint——永远不做**
  （V3 第七节点名的注入攻击面；我们的幂等指纹已是更彻底的可恢复性）。

## 八、当前状态快照（2026-07-11）

- 后端 61 测试 / e2e 24 / CI 三 job 全绿（跑过 3 次，修掉 2 个并发竞态）
- 已完成：九模块前端、三层溯源旗舰页、技术工作台计算流水线、日/夜主题、
  中英双语、决策-结果闭环账本（回测 55 期回填：TSMOM 51.7%、Clock 55.7%、
  ERP 50%、象限 57.4% 命中，月均 α +26bp）、委员会正反检验、类型化数据错误、
  分级降级、LLM 契约预埋、CI 确定性断言
- 数据为固定种子合成（2020-01~2026-07，8 段 regime），改生成器必须同步提交 CSV
- 另一个仓库 `flukier1016/asset-allocation-kb` 是本项目的前身+知识库，
  其 PR #1 保留作历史，**不要往那边提交**
