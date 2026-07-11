---
name: asset-allocation-committee-agent
description: 用一个"AI 投资委员会"式的多智能体架构,对股/债/商品/外汇四类资产给出大类资产配置建议。内核是五个经典学术方法(Risk Parity、Time Series Momentum、Merrill Lynch Investment Clock、Equity Risk Premium、Black-Litterman Model)组成的三层结构:战略打底 → 战术偏离 → 整合,并内置全链路可追溯与三层对抗鲁棒性(AI/量化/系统)。当需要设计/实现一个可解释、可回测、抗操纵、可接入实时行情与新闻源的资产配置 agent 时使用。
version: "2.0"
scope: 大类资产配置(股、债、商品、外汇);不含个股选股、不含高频、不含另类/私募
requires: LLM(带 function calling / structured output)+ 可执行确定性量化代码的运行环境;实时行情与新闻源为可选增强(见第六节);上线前须通过第八节检查清单
---

# AI 大类资产配置投资委员会 · 五方法三层 Agent Skill

> **一句话定位**:把五个经典资产配置方法当成投委会里五位不同流派的专家,各自对股债商汇出结构化信号,再由 Black-Litterman Model 作为"整合主席"融合成一份可解释、可回测的目标配置。数字全部由确定性代码算,LLM 只负责读新闻、判象限、生成观点与整合叙述——绝不"想象"数字、绝不直接下单。

---

## 第〇节　这个 Skill 解决什么问题

**目标**:输入当前市场状态(行情 + 宏观 + 新闻),输出**股 / 债 / 商品 / 外汇**四类资产的**目标权重建议 + 归因解释 + 风控报告**。

**为什么是这五个方法、这三层**:它们的收益来源正交、失效场景错开,天然分工——
- **战略打底(不预测周期)**:只保留 Risk Parity。按风险贡献生成可穿越周期的唯一底仓与 BL 先验。
- **战术偏离(表达阶段性观点)**:Time Series Momentum、Merrill Lynch Investment Clock、Equity Risk Premium。三者只生成相对底仓的结构化观点,不直接构成战略底仓。
- **整合**:Black-Litterman Model。把三种战术方法的观点与 Risk Parity 先验做贝叶斯融合,输出后验收益、目标权重和可闭合归因。

> 原六大方法论中的**耶鲁多元分散**未纳入:它是另类资产 / 超长期限 / 非流动性溢价的底仓框架,不参与股债商汇这类流动市场的战术配置,故排除。

**适用**:多资产 SAA/TAA、固收+、投委会决策支持、配置研究自动化。
**不适用**:个股 alpha、日内高频、私募/另类配置、无回测护栏的实盘自动下单。

---

## 第一节　核心隐喻:AI 投委会 = 五专家 + 一主席

| 专家(方法) | 流派 | 一句话主张 | 层 |
|---|---|---|---|
| Risk Parity / 全天候 | 均衡派 | 别赌方向,让各类资产风险贡献相等,穿越周期 | 战略打底 |
| Time Series Momentum | 趋势派 | 别判贵贱,只跟涨跌,把趋势转成阶段性超低配观点 | 战术偏离 |
| Merrill Lynch Investment Clock | 宏观派 | 按"增长 × 通胀"象限,轮动债 / 股 / 商品 / 现金 | 战术偏离 |
| Equity Risk Premium | 估值派 | 极端分位处,做股债相对的均值回归 | 战术偏离 |
| Black-Litterman Model | 整合主席 | 把大家的观点按置信度融进均衡先验,给出最终配置 | 整合 |

**这不是凭空设计——业界与学界都收敛到"多专家 + 一整合层"**:BlackRock **AlphaAgents**(基本面/情绪/估值三专家辩论→共识,arXiv:2508.11152)、**TradingAgents**(多空辩论+风控+基金经理裁决,arXiv:2412.20138)、**TradExpert**(4 专家各管一路数据 → General Expert 整合,arXiv:2411.00782)、**FinCon**(经理-分析师分层 + 风控组,arXiv:2407.06567)。而零售智投 **Betterment / Wealthfront** 的核心引擎就是 Black-Litterman Model——把 BL 放在整合层,是最有先例、最好解释的选择。

---

## 第二节　三层 × 五方法架构

```
                    ┌──────────────────────────────────────────────┐
   战术偏离层  ────▶ │ Time Series Momentum · Merrill Lynch Investment Clock · Equity Risk Premium│ ──┐
   (阶段性观点)      └──────────────────────────────────────────────┘   │ 观点 P/Q/Ω
                    ┌──────────────────────────────────────────────┐   ▼
   战略打底层  ────▶ │ Risk Parity(唯一底仓与风险预算)                  │ ──▶ Black-Litterman Model
   (穿越周期)        └──────────────────────────────────────────────┘  先验 π + 观点
                                                                      │
                                                                      ▼
                                                           目标权重 + 归因 + 风控
```

- **战略层给"底仓与先验"**:Risk Parity 独立算出各资产**风险预算 / 中枢权重** `w_strategic`,反向优化成 BL 的**先验隐含收益** `π = δ·Σ·w_strategic`(把教科书 BL 的"市值权重先验"替换成"Risk Parity 先验",是常见定制变体,须注明非标准 BL)。战略层不再混入 CTA 或其他方向性方法。
- **战术层给"观点"**:Time Series Momentum 输出**方向与强度**,Merrill Lynch Investment Clock 输出**象限概率**,Equity Risk Premium 输出**历史分位**。三者统一转成 BL 的观点矩阵 `(P, Q, Ω)`,只决定相对 Risk Parity 底仓的阶段性偏离。
- **整合层出"配置"**:BL 把先验 π 与观点 (P,Q,Ω) 贝叶斯融合 → 后验期望收益 `E[R]` → 均值方差 / 风险预算优化 → 目标权重。

---

## 第三节　五方法在"股债商汇"上的信号化(落地关键)

**每个方法覆盖哪些资产要诚实**——不是每个方法对四类都同等适用:

| 方法 | 股 | 债 | 商品 | 汇 | 输出信号(view_type)与依据 |
|---|:-:|:-:|:-:|:-:|---|
| **Risk Parity** | ✓ | ✓ | ✓ | ✓ | `risk_budget`:按协方差让四类风险贡献相等 → 中枢权重 `w_strategic`。四类皆适用(有价格即可估协方差) |
| **Time Series Momentum** | ✓ | ✓ | ✓ | ✓ | `direction`:各资产按过去 12 个月收益正负出 +1/0/−1,波动率倒数定强度。期货/远期天然覆盖四类 |
| **Merrill Lynch Investment Clock** | ✓ | ✓ | ✓ | △ | `regime`:增长×通胀四象限概率 → 债/股/商品/现金 tilt;**汇率**仅 G10 部分周期显著(美元在再通胀-复苏强、日元澳元在过热强),弱信号 |
| **Equity Risk Premium** | ✓ | ✓ | ✗ | ✗ | `percentile`:盈利收益率 − 十年国债收益率的历史分位 → **仅股 vs 债**的相对观点。商品/汇率不适用,须显式弃权 |
| **Black-Litterman Model** | ✓ | ✓ | ✓ | ✓ | 整合层:把上面所有观点融进 Risk Parity 先验 → 四类目标权重 |

> **关键纪律**:ERP 只对股债有话语权,商品和汇率由 CTA / Risk Parity / 时钟主导。让每个专家**只在自己有效的资产上发言**、其余弃权(输出 `abstain`),是防止"专家越界幻觉"的核心——这与文献中"每个专家只吃一路信息"(TradExpert、FinCon)的设计一致。

### 统一信号契约(Signal schema)

所有方法无论内部逻辑如何,都吐同一形状的结构化对象,便于黑板聚合与 BL 消费。用 **Pydantic / JSON Schema** 定义,LLM 端用 structured output 强约束:

```json
{
  "method": "TSMOM",                 // risk_parity | tsmom | clock | erp
  "layer": "tactical",               // strategic | tactical | integration;TSMOM 固定为 tactical
  "asof": "2026-07-08T00:00:00Z",    // point-in-time 时间戳(严防未来函数)
  "view_type": "direction",          // direction | percentile | risk_budget | regime | expected_return | abstain
  "assets": ["equity", "bond", "commodity", "fx"],
  "values": {"equity": 1, "bond": -1, "commodity": 1, "fx": 0},
  "strength": {"equity": 0.8, "bond": 0.6, "commodity": 0.5, "fx": 0.0},
  "confidence": 0.7,                 // 0–1,映射 BL 的 Ω(观点不确定性)
  "horizon_days": 60,
  "rationale": "股/债/商品 12M 超额收益 > 0,波动率标准化后…",
  "source_refs": ["px:SHFE.cu", "news:id123"]   // 可溯源到具体数据/新闻
}
```

> 上面是**基础**信号契约;每条信号的**完整血缘**(唯一 ID、哪个专家出的、何时、基于哪些数据/新闻、代码版本与参数)见第五节 TracedSignal——它是全链路可追溯的原子单元。

### 各方法 → BL 的装配方式

- **Risk Parity → 先验**:`w_strategic` 经反向优化 `π = δΣw_strategic` 成隐含均衡收益,作 BL 先验(非观点)。
- **CTA → 绝对/相对观点**:`direction` 转 P 矩阵行(如"股>债"= `[+1,−1,0,0]`),Q 给期望超额,Ω 由 confidence 反推。
- **Merrill Lynch Investment Clock → 绝对观点 tilt**:象限概率的集中度决定 confidence,概率越集中观点越强。
- **ERP → 股债相对观点**:高分位=股相对便宜 → `[+1,−1,0,0]` 超配股;仅此一行。
- **Ω 的确定性映射(重要)**:`Ω_ii ∝ (1−confidence)·PᵢΣPᵢᵀ`,由代码算,**绝不让 LLM 直接编 Ω 数字**。有直接范式:LLM-Enhanced Black-Litterman(arXiv:2504.14345)把 LLM 预测的置信度系统性转成 Ω。

---

## 第四节　Agent 工作流与四层架构

```
L0 数据层    行情 + 宏观 + 新闻 → 统一 schema、point-in-time 落库 → 事件总线分发
                                   │
L1 信号层    五方法各自算信号(多为确定性 tool;时钟/观点生成为 LLM agent)→ 写入共享黑板
                                   │  List[Signal]
L2 整合层    Black-Litterman Model(Orchestrator):先验 π + 观点 P/Q/Ω → 后验 E[R] → 优化 → 目标权重
                                   │  TargetWeights + Rationale(建议,非指令)
L3 输出+风控  确定性硬约束闸门(仓位/杠杆/换手/回撤)+ 护栏 + 回测门禁 + 审计 → 最终建议
```

**编排选型**(基于业界实践):
- **默认 LangGraph**:把流程建成有状态图(节点=方法/工具,边=控制流),支持并行、条件分支、持久化、human-in-the-loop 中断,最适合"固定 DAG + 需审计回放"的投委会流程(TradingAgents 即用 LangGraph)。CrewAI 落地最快、AutoGen 最擅长辩论,可按需混用。
- **架构模式**:**Orchestrator–Worker**(BL 整合 agent 统筹五方法专家,对应 Anthropic 的 lead→并行子 agent→汇总)+ **Blackboard**(五方法把信号写进共享 state,BL 读取)。
- **量化方法优先做"确定性 tool"而非 LLM agent**:Risk Parity、Time Series Momentum、Equity Risk Premium 的数字由代码算准(`risk_parity()`、`tsmom()`、`erp()`),LLM 只负责调度与整合叙述。**只有需要读新闻/推理的环节**(Merrill Lynch Investment Clock 象限判断、BL 观点生成)才升级为真正的 LLM agent。这是 ReAct 范式(arXiv:2210.03629)的应用,也是防幻觉的第一道结构性防线。

**一次决策的时序**:
1. L0 按频率触发(日频价格 / 月频宏观 / 事件驱动新闻)→ 更新黑板数据。
2. L1 五方法并行算信号 → 各自写 `Signal`(有效资产发言、无效资产 `abstain`)。
3. L2 BL 装配 π 与 (P,Q,Ω) → 后验 → 优化 → 目标权重 + 归因(展示谁支持谁反对、分歧点)。
4. L3 硬约束裁剪 + 回测门禁 + 审计 → 输出建议(默认不自动下单)。

---

## 第五节　可解释与全链路可追溯(每个观点、每个专家都能回溯)

> 投委会场景的硬需求:**任意一个配置决策,都能反查到——是谁(哪个专家)、基于什么(哪条数据/新闻)、在什么时候、用什么参数、怎么算出的观点;而且任意历史时刻的完整决策过程能原样重放。** 合规、事后复盘、问责,全靠这条追溯链。

### 5.1 三个层次的可追溯

- **观点级(每个 Signal)**:谁出的(专家/方法/版本)+ 何时(asof)+ 基于什么(每个输入数据/新闻的具体 ID 与快照哈希)+ 怎么算的(代码版本、参数)+ 置信度 + 原始特征值 + 自然语言依据。
- **决策级(每次配置)**:用了哪些观点 + Risk Parity 先验 + BL 融合参数 + 后验 + 目标权重 + **每个观点对每个资产权重的贡献** + 哪些风控闸门触发 + 审批人。
- **时间级(任意历史时刻)**:能 as-of 重放某一天的完整决策链,用"当时可得"的数据版本(严防未来函数)。

### 5.2 可追溯的数据模型(TracedSignal + 不可变 DecisionRecord)

在第三节 Signal 基础上加血缘字段;每次决策落一条**不可变**记录:

```json
// TracedSignal = Signal + 血缘(谁/何时/基于什么/怎么算)
{
  "signal_id": "sig_20260708_tsmom_001",
  "agent_id": "tsmom_expert", "agent_version": "v1.3.0",
  "code_version": "git:a1b2c3", "params": {"lookback_m": 12, "vol_window": 60},
  "inputs": [
    {"data_id": "px:CSI300", "source": "tushare", "asof": "2026-07-08", "hash": "9f2a…"},
    {"data_id": "px:CGB10Y", "source": "wind",    "asof": "2026-07-08", "hash": "3c1b…"}
  ],
  "derivation": "mom_12_1=0.14; vol_20d=0.11; signal=sign(mom)*0.4/vol",
  "asof": "2026-07-08T00:00:00Z"
  // …外加第三节 Signal 的全部字段(view_type / values / confidence / rationale / source_refs)
}

// DecisionRecord = 一次完整决策的不可变记录
{
  "decision_id": "dec_20260708_0930",
  "asof": "2026-07-08T09:30:00Z",
  "input_signals": ["sig_…tsmom_001", "sig_…erp_001", "sig_…clock_001", "sig_…rp_001"],
  "prior": {"w_strategic": {...}, "pi": {...}},          // Risk Parity 先验
  "bl_inputs": {                                         // 观点矩阵(Ω 由代码算,非 LLM 编)
    "asset_order": ["equity", "bond", "commodity", "fx"],
    "views": [
      {
        "view_id": "view_clock_equity",
        "source_signal_ids": ["sig_…clock_001"],
        "P": [1, 0, 0, 0],
        "P_derivation": "资产选池 + 打分 + 观点腿归一规则与数值代入",
        "Q": 0.008,
        "Q_derivation": "原始信号分数 × 校准尺度,并注明期限/截断规则",
        "confidence": 0.72,
        "view_variance": 0.00049,
        "Omega": 0.00019,
        "lambda": 0.08,
        "derivation": "clock regime=复苏 → equity absolute tilt; Ω=(1-c)/c·3τ·PΣPᵀ"
      }
    ]
  },
  "posterior_ER": {...},
  "target_weights": {"equity": 0.55, "bond": 0.30, "commodity": 0.10, "fx": 0.05},
  "attribution": {                                        // ★ 每个观点对每类资产权重的贡献
    "equity": {"prior": 0.40, "view_clock_equity": 0.08, "view_erp_equity_bond": 0.05, "view_tsmom_equity": 0.02}
  },
  "guardrail_actions": [{"rule": "max_equity_60pct", "triggered": false}],
  "llm_traces": ["trace:clock_llm_xyz", "trace:bl_view_gen_abc"],  // LLM 环节 trace ID
  "approver": "pending | user_id"
}
```

每条 Signal 和 Decision 都有唯一 ID、时间戳、输入哈希——**观点 → 数据/新闻、配置 → 观点** 两级血缘全程闭合可查。

### 5.3 BL 让归因有数学保证(不是 LLM 事后编的)

Black-Litterman Model 的 He-Litterman(1999)定理:**最优组合 = 均衡组合 + 各观点组合的加权和**——每一分对先验的偏离都能**唯一分解**到具体观点。所以"股票为什么从先验的 40% 调到 55%"能精确拆成"时钟象限观点 +8pct、ERP 分位观点 +5pct、CTA 趋势观点 +2pct"(见上 `attribution` 字段)。这是把 BL 放整合层的关键红利:归因是**可加总、可闭合、可审计**的数学结果,而不是让 LLM 事后编一段解释。

### 5.4 时间旅行 / 决策重放(工程实现)

- **事件溯源(Event Sourcing)**:所有数据更新、信号生成、决策落地都作为**不可变事件**追加到事件日志;任意时刻状态 = 重放到该时刻的事件序列,天然支持"回到过去任意一刻"。
- **point-in-time 数据快照**:数据层按发布时间戳存储(第六节),重放时取"当时可得"版本,杜绝未来函数污染回溯。
- **LangGraph checkpointing + time-travel**:LangGraph 原生支持状态检查点(checkpointer)与"时间旅行"——回到任意历史 checkpoint 重放或分支,天然契合决策回溯与调试。
- **LLM 可观测性(observability)**:每个 LLM 调用(时钟象限判断、BL 观点生成)的 prompt、输出、token、延迟、中间推理都记成 trace 可回放。工具:LangSmith(LangChain 系)、Langfuse(开源)、OpenTelemetry(分布式追踪标准)。

### 5.5 前端:一页式三层溯源看板(必须优先实现)

前端第一屏必须是一张**三层过程总览页**,不是把"信号 / Black-Litterman Model / 归因"拆散到三个互相独立的页面。用户在一页内要能顺着同一条链路看到:

```
L1 四方法信号(Risk Parity 独立战略打底;Time Series Momentum/Merrill Lynch Investment Clock/Equity Risk Premium 形成战术观点)
        ↓ source_signal_ids
L2 战术观点 + Black-Litterman Model 装配(Risk Parity 先验 + 战术观点 → 贝叶斯融合 → 后验收益)
        ↓ view_id / attribution
L3 最终配置(先验权重 → 目标权重 → He-Litterman 归因瀑布 → 风控闸门)
```

**页面布局最低要求**:
1. **顶部决策摘要**:展示 `decision_id`、`asof`、目标权重 `target_weights`、风控状态、数据模式(demo/live),并标明"非投资建议/研究推演"。目标权重汇总层必须先按 `asset_classes[]` 展示权益/债券/商品/外汇/现金 5 个大类比例,再展示每个大类下面的 `display_buckets[]` 细分桶。其下“权重生成路径”中,第一层战略底仓必须像合成目标权重一样展示 5 大类与 7 细分桶,并明确唯一来源是 Risk Parity;第二层标题固定为“战术偏离 + 观点整合”,展示三种战术方法及合成偏离。`decision_id`、`asof` 在主页面应格式化为中文可读的决策批次和时点,原始机器值留在数据包或详情中。
2. **L1 信号层**:四张专家卡按“Risk Parity=唯一战略底仓”和“Time Series Momentum/Merrill Lynch Investment Clock/Equity Risk Premium=战术偏离”分组,方法名固定使用英文全称,`layer / view_type / values / strength / confidence / rationale / abstain` 等业务标签和单位使用中文;`signal_id / source_refs`、版本和输入 hash 放入点击后的血缘抽屉,不要让机器标识占据主卡第二视觉层级。无效资产必须以 `abstain` 标签显示,不能省略。信号区底部应有“信号去向”摘要,标明 Risk Parity 进入战略底仓,其余三种方法各生成几条 Black-Litterman Model 观点。
3. **L2 战术观点与 Black-Litterman Model 装配层**:主页面顶部必须直接画出“Prior · Risk Parity 战略先验 + Views · Time Series Momentum/Merrill Lynch Investment Clock/Equity Risk Premium 战术观点 → Black-Litterman Model 贝叶斯融合 → Posterior 后验收益”的作用链,让非技术用户一眼看出 Black-Litterman Model 不是第五张普通信号卡,而是把先验与观点按置信度融合的整合器。其下再展示 `prior.w_strategic`、`prior.pi` 和 `bl_inputs.views[]` 的业务摘要卡。观点必须先按 7 个 `display_buckets[]` 组织;相对观点可同时出现在两个受影响资产类别下,但共用唯一 `view_id`。每张观点卡至少显示统一英文来源方法、观点名称、当前资产类别内 `P` 的非零资产摘要、`Q`、`confidence`、该类别的 `attribution`;`view_id`、`source_signal_ids`、`Omega`、完整 `P`、`derivation` 等技术细节放到血缘抽屉或技术工作台,不要在主页面摊成技术参数表。观点卡必须用方法固定色和高亮表明它来自哪张 L1 信号卡。
4. **L3 权重层**:展示 `prior → target_weights` 的柱状/条形对比、`asset_classes[] → display_buckets[] → assets[]` 的层级下钻,以及按资产的 `attribution` 瀑布。底层标的与观点归因均采用“汇总桶摘要行 → 展开详情”;归因默认只展开影响最大的一个桶,避免 7 个桶的贡献标签全部平铺。瀑布段必须使用 `view_id` 作为 key,这样点击某段能回到 Black-Litterman Model 观点行,再回到源 Signal。
5. **血缘抽屉**:点击任意信号卡、观点行或瀑布段,右侧/弹层展开完整血缘:专家版本、代码版本、参数、输入数据 `data_id/source/asof/hash`、推导式、LLM trace ID(如有)。

**资产扩展展示要求**:生产实现可以在 Black-Litterman Model/风控层使用更细的 `assets[]` 明细资产(如 27 个 ETF/期货/货币对),但前端第一屏目标权重汇总层必须先按中国投资者视角汇总为 `asset_classes[]`(权益、债券、商品、外汇、现金),再展示可读的 `display_buckets[]`(中国股票、外国股票、中国债券、外国债券、商品、外汇、现金)。5 个大类比例直接写在总配比堆叠条内;条下使用 5 个等宽等高大类框,每框展示总权重、桶内小分段条和细分桶分框。权益与现金不得使用近似色,现金建议使用中性石墨灰。L3 必须支持从任一汇总桶展开到底层标的,展示桶内每个标的的 `prior / target / delta`,并显示桶内标的加总等于该桶目标权重。观点区按 7 个资产类别折叠组织,每组显示观点条数和净影响;组内按当前类别的 `abs(attribution)` 排序。完整 P 矩阵与计算细节放入双页签技术工作台,明细资产权重表默认折叠,避免首屏变成长表。

**主页面中文化与方法一致性要求**:展示层优先使用中文业务标签和中文单位;五个展示名称在全页只能使用英文全称“Risk Parity / Time Series Momentum / Merrill Lynch Investment Clock / Equity Risk Premium / Black-Litterman Model”,不得在任何可见区域缩写成“CTA”“TSMOM”“时钟”“ERP”“BL”或使用另一套主名称。机器字段和技术公式允许保留 `tsmom / erp / bl_inputs / μ_BL` 等稳定标识,但不能把它们当作页面标题、卡片名或来源方法名。方法身份使用固定色:Risk Parity=绿、Time Series Momentum=蓝、Merrill Lynch Investment Clock=金、Equity Risk Premium=玫红、Black-Litterman Model=蓝灰;信号卡、观点卡、信号去向和归因标签必须复用同一方法色。涨跌方向仍以正负号和红绿表达,资产类别继续使用资产色,三套颜色语义不得混用。`signal_id / view_id / rule ID`、`π / E[R] / Ω / λ` 等机器标识或技术符号保留在抽屉、技术工作台或数据字段中。风控闸门主页面显示“中国股票上限 / 单一资产上限 / 禁止做空 / 权重闭合”等中文规则名,原始 rule ID 可放在悬浮说明或详情中。移动端将闭合状态卡与三层导航压缩为紧凑布局,不得横向溢出。小字号正文与白色背景的颜色对比度至少达到 `4.5:1`,涨跌与通过/触发状态必须同时使用文字或正负号,不能只靠颜色。宽屏下 L1/L2/L3 使用三个等宽网格轨道并保持底边对齐;顶部最终结果与权重生成路径复用同一左右分栏轨道;底部明细资产与风控两栏等高。

**Black-Litterman Model 技术工作台要求**:提供“观点矩阵 / 计算过程与溯源”两个页签。矩阵页按 7 个资产类别做跨列表头,每项资产显示中文简称、交易代码、所属类别,每条观点行能跳到本行计算。计算页按 `π = δΣw_RP → P/Q/Ω → μ_BL → constrained target` 展示公式链,并逐观点列出 `P_derivation` 的选池/打分/腿内归一、`Q_derivation` 的原始分数与校准尺度、`confidence + view_variance → Omega` 的数值代入、归因贡献、来源信号版本、输入 `data_id/asof/hash`。前端只展示 DecisionRecord 落库值,不得在浏览器重估协方差或改写目标权重。

**验收标准(前端不得降级)**:
- 不接受只有"四方法信号卡片墙"或只有"最终权重饼图/柱图"的页面;必须同屏出现 L1→L2→L3 的过程链。
- 目标权重汇总层必须先按 5 个大类展示比例,再展示 7 个细分桶比例;5 个大类权重必须由 7 个细分桶加总得到。
- 战略底仓必须只来自 Risk Parity,并与合成目标权重使用同构的 5 大类 + 7 细分桶展示;Time Series Momentum 必须归入战术偏离。
- L2 必须可视化“战略先验 + 战术观点 → Black-Litterman Model 融合 → 后验收益”,不能只把观点卡和后验表上下堆放而不解释 Black-Litterman Model 的作用。
- 五个方法/模型的英文全称和固定色必须在信号、观点、去向、装配、归因等区域一致;可见区域出现 `CTA / TSMOM / ERP / BL` 即不通过。
- 观点必须按 7 个资产类别组织;技术工作台必须能从任一 P 矩阵行跳到该行的 P/Q/Omega 计算与输入血缘。
- 任一最终权重数字都必须能追到 `attribution[asset][view_id]`、`bl_inputs.views[view_id]`、`source_signal_ids`、再到 TracedSignal 的输入哈希;追不到即视为不可审计。
- `sum(target_weights)` 必须在前端显示闭合校验(容差建议 `1e-6`);`prior + Σ attribution` 与目标权重不闭合时必须显示红色异常,不能静默。
- `Ω`、`λ`、`posterior_ER`、`target_weights`、`attribution` 都来自确定性代码/API;前端只渲染,不自行重算,LLM 不补数字。
- 若使用明细资产,必须同时展示汇总桶闭合与明细资产闭合;任一汇总桶都能展开到底层标的,且桶内标的目标权重加总必须等于该桶目标权重;同时能从汇总桶归因下钻到具体 `view_id` 与源信号。
- 分页可以存在,但只能作为下钻:时间轴回放、Diff、风控详情、新闻原文。三层总览页是进入系统后的主页面。

**后续增强视图**:
- **时间轴**:滑块回放任意历史日的完整决策(五专家当时各说了什么、BL 怎么整合的)。
- **Diff**:今天 vs 昨天的配置变化,归因到"哪个观点变了 / 哪条新闻来了 / 哪个数据更新了"。
- **来源下钻**:点新闻/数据源查看原文或快照。

这是 TradingAgents"12 阶段流水线看板"、AlphaAgents"辩论轨迹"的加强版——不只展示当次过程,还能**反查来源 + 重放历史**,PM 更接受这种能看到并追溯推理过程的系统。

### 5.6 合规对齐

> **监管口径更新(2026-04-17)**:美联储/FDIC/OCC 已正式**废止 SR 11-7**(及配套 OCC Bulletin 2011-12),代之以按重要性分级、原则导向的新框架 **SR 2026-02**。GenAI / agentic 系统"不在传统范围内,但需继承其核心原则"——独立验证(validator 与开发者无汇报关系)、outcomes analysis(输出 vs 实际结果比对)、benchmarking、敏感性分析、持续监控,且证据须"作为模型构建方式的自然产物,而非事后补造"。详见第七节 7.4。

上面的不可变 DecisionRecord + 两级血缘 + LLM trace + 审批记录,正是为满足新旧监管口径共同要求的"可解释、可追溯、有独立审查与记录"而设计的审计基础。

---

## 第六节　数据接口设计(预留实时行情 + 新闻源)

### 实时行情(驱动 CTA / Risk Parity / ERP)

统一封装 `MarketDataAdapter` → 时序库(TimescaleDB)+ 缓存(Redis)+ 事件总线(Kafka topic `px.*`)+ WebSocket 推送。

| 方法 | 需要数据 | 刷新频率 |
|---|---|---|
| Time Series Momentum | 四类资产价格时序 | 每根 bar 收盘 → 重算波动率标准化动量 |
| Risk Parity | 收益协方差 Σ | 日/周滚动窗重估 → 风险预算 |
| ERP Equity Risk Premium | 股票 E/P + 十年国债收益率 | 日 → 重算 gap 与历史分位 |
| Merrill Lynch Investment Clock | 增长(PMI/产出缺口)+ 通胀(CPI) | 月度低频 + 新闻 nowcasting 月内提频 |

**数据源**:海外 Bloomberg(BLPAPI)/ Polygon.io / Alpaca / Finnhub / Nasdaq Data Link;中国 Wind / Tushare Pro / AkShare / 迅投 QMT-xtquant(Level-2)/ CTP(期货);加密 CCXT。(`yfinance` 仅原型用,非官方。)

### 新闻源(驱动时钟象限判断 + BL 观点)

三步流水线:**采集(带 point-in-time 时间戳)→ NLP 结构化 → 映射为信号**。
- **NLP 结构化**:FinBERT 情绪打分(arXiv:1908.10063)+ 事件抽取(加息/PMI 超预期/地缘冲突/油价冲击)+ LLM 摘要打分(**必须配 RAG + 引用来源**以抑制幻觉)。
- **→ Merrill Lynch Investment Clock 象限**:把新闻情绪 / 宏观意外聚合成"增长轴 + 通胀轴"nowcasting → 四象限概率(把月度低频时钟提频的关键)。参考 GDELT + FinBERT 做宏观 nowcasting(arXiv:2505.16136)。
- **→ BL 观点**:如"地缘冲突 + 油价新闻密集"→ 商品绝对观点上调,confidence 由新闻量 + 观点一致性决定。多 LLM 情绪聚合 → BL 可降低单模型波动。
- **数据源**:海外 GDELT(免费全球事件库)/ RavenPack / Finnhub News / Alpha Vantage NEWS_SENTIMENT;中国 财新(含财新 PMI)/ 同花顺 iFinD / Wind 资讯 / 巨潮资讯(公告)。

---

## 第七节　对抗鲁棒性与稳健性:能被攻击,也要扛得住

> 一个接新闻源、给真金白银配置建议的 agent,"能被对抗"不是假设而是必然——新闻文本是天然的注入通道,协方差与观点是天然的操纵靶子,回测是天然的自欺工具。本节按 **AI 侧 / 量化侧 / 系统侧** 三层给出真实攻击手法与对应加固,每条均有可核实文献支撑。这是继"反幻觉铁律"之后本 skill 的第二道生命线。

### 7.1 三层威胁模型总览

| 层 | 最大攻击面 | 典型手法 | 核心防线 |
|---|---|---|---|
| **AI 侧** | 新闻/文本输入通道 | 间接 prompt injection、同形异义字/隐藏文本操纵情绪、RAG/记忆投毒、多 agent 间"病毒式"传染 | 结构化输出约束 + 输入隔离(Dual-LLM/Spotlighting)+ 多源共识 |
| **量化侧** | 协方差、观点权重、可预测调仓规则 | 估计误差被优化器放大、拥挤踩踏、被抢跑、动量崩溃、regime 切换失效 | 稳健优化 + 协方差收缩 + 波动率目标化 + 执行随机化 |
| **系统侧** | 数据管道、回测流程、运行时 | 行情/新闻源故障或投毒、回测过拟合(样本内凑数)、极端行情下系统崩溃 | 断路器+优雅降级 + DSR/PBO/CPCV 门禁 + 红队 + kill switch |

### 7.2 AI 侧:新闻/数据注入攻击与防御

**真实攻击已被证实针对金融交易 LLM**:Rizvani, Apruzzese & Laskov, "Adversarial News and Lost Profits: Manipulating Headlines in LLM-Driven Algorithmic Trading," IEEE SaTML 2026(arXiv:2601.13082)——用**同形异义字替换**(Unicode homoglyph)和**人眼不可见的隐藏文本**篡改新闻标题情感,在 14 个月周期的"一天式攻击"下让 LLM 驱动的交易策略年化收益最多损失 **17.7 个百分点**;FinBERT 对同形异义字攻击的错误分析率高达 **99%**。这精确对应本系统"用新闻驱动 Merrill Lynch Investment Clock 象限判断和 BL 观点"的攻击面。

**OWASP Agentic AI Top 10(2026)中对本系统最致命的三项组合**:
- **ASI01(Agent Goal Hijack)**:恶意内容篡改 agent 目标——对应"新闻注入操纵象限判断"。
- **ASI06(Memory/Context Poisoning)**:对应 RAG/新闻库投毒。PoisonedRAG(Zou et al., USENIX Security 2025, arXiv:2402.07867)证明**仅需 5 条恶意文本注入百万级知识库,攻击成功率达 90%**。
- **ASI08(Cascading Failures)**:单一象限误判 → BL 观点污染 → 三层整合叙述层层放大。

**多 agent 特有风险**:Prompt Infection(Lee & Tiwari, 2024, arXiv:2410.07283)证明恶意 prompt 能像病毒一样在多 agent 系统间自我复制,GPT-4o 场景下自我复制式注入成功率超 **80%**——若五个专家方法共享同一上游 LLM 或同一整合叙述层,该整合层就是单点故障。**LLM 多智能体系统的拜占庭容错(BFT)理论仍处早期研究阶段**(arXiv:2511.10400),工程可靠性存疑,**不可**作为生产级风控的唯一保障。

**分层防御(按有效性排序,已核实)**:
1. **结构化输出强制约束(本 skill 已有的核心设计天然是最强防线)**:象限判断限定为预定义枚举 + 置信度、BL 观点限定为 `(资产,方向,幅度区间,置信度)` schema,用 **Guardrails AI** 做 schema 强制校验——攻击的杀伤力建立在"LLM 自由解读情感→直接改数字"这条路径上,结构化约束从根上切断它。
2. **Dual-LLM 隔离**(Simon Willison, 2023):负责读新闻的 LLM(Q-LLM)只能输出结构化观点,不能调用工具、不能直接进入决策链;特权 LLM(P-LLM)只处理可信内部数据。
3. **Spotlighting**(Hines et al., 微软 2024, arXiv:2403.14720):对不可信新闻文本做 delimiting/datamarking/encoding 标记,encoding 模式可把攻击成功率从 >50% 压到 **<2%**。
4. **多源一致性门槛(对抗 pump-and-dump 式操纵的关键)**:单条新闻/单一信源不可单独触发象限切换或大幅 BL 观点调整,须多条、多源新闻一致投票或加权共识;低信誉源(社媒/论坛)权重显著低于官方通讯社。极端单点情绪触发**熔断/人工复核**而非自动执行。
5. **架构层阻断**:CaMeL(Google DeepMind 2025, arXiv:2503.18813)用自定义解释器显式提取控制流/数据流、以"能力元数据"限制不可信数据能做什么;LlamaFirewall(Meta 2025, arXiv:2505.03574)把攻击成功率降低 **90%+**。二者代表"从架构而非提示词防注入"的方向,优于纯 prompt 层防御。
6. **锚定校验**:AutoRedTrader(arXiv:2605.09185)红队测试发现,**用历史市场数据做"时间序列锚定"能显著降低攻击成功率**——即任何由新闻驱动的信号变化,必须能对照真实历史数据自洽,而不是单纯信任新闻文本的语气。

### 7.3 量化侧:组合稳健性与抗操纵

**核心风险**:均值-方差优化本身是"估计误差放大器"(Michaud, 1989),会系统性超配被高估收益/低估方差的资产;协方差矩阵在资产数接近样本数时噪声主导;可预测的调仓规则会被抢跑;策略规模化后同质化持仓会踩踏。

| 风险 | 加固手段 | 关键文献 |
|---|---|---|
| MVO 放大估计误差 | Black-Litterman Model 本身已是缓解手段(均衡先验 + 增量观点修正);进一步可用重采样有效前沿做置信区间(注意 Scherer 2002 指出其过度平滑的批评,只用于生成区间、不作最终权重)、稳健 MVO(置信椭球,Goldfarb & Iyengar 2003)、CVaR 优化(Rockafellar & Uryasev 2000)、分布鲁棒优化/Wasserstein DRO(Mohajerin Esfahani & Kuhn 2018) | Michaud (1989) *FAJ*; DeMiguel, Garlappi & Uppal (2009) *RFS* 实证 14 种优化模型均未稳定跑赢 1/N |
| 协方差矩阵噪声主导 | **Ledoit-Wolf 非线性收缩**(2017,基于特征值逐个收缩,渐近最优,优于线性收缩)+ **随机矩阵理论(RMT)去噪**(剔除 Marchenko-Pastur 噪声带内特征值)双重处理,Risk Parity 与 BL 先验用的协方差都要过这一关 | Ledoit & Wolf (2004) *JPM*; Ledoit & Wolf (2017) *RFS*; Laloux et al. (1999) *PRL*(arXiv:cond-mat/9810255) |
| Regime 切换致 Merrill Lynch Investment Clock/Equity Risk Premium 失效 | 引入 Markov-switching regime 探测器动态识别当前 regime,调整时钟象限判定阈值与 ERP 回看窗口;须承认 Merrill Lynch Investment Clock 是"事后划相位"的业界框架而非可实时判定的学术结论 | Ang & Bekaert (2002) *RFS*; Kritzman, Page & Turkington (2012) *FAJ*; McLean & Pontiff (2016) *JF*——已发表因子样本外收益平均衰减 26%,发表后进一步衰减 58% |
| 策略拥挤 / 去杠杆踩踏 | 建拥挤度仪表盘(杠杆倍数、持仓集中度、融资利差扩大),监测到异常时 BL 整合层自动降权该信号并触发去杠杆预案 | Stein (2009) *JF*(拥挤度理论根源:无锚策略无法知道同行有多少人在做同一笔交易); Khandani & Lo (2011) *JFM*(2007 年 8 月 quant quake 实证); Asness, Frazzini & Pedersen (2012) *FAJ*; Brunnermeier & Pedersen (2009) *RFS*(融资流动性螺旋) |
| 可预测调仓被抢跑 | 调仓不在固定可预测日期机械执行,引入执行时点随机化或分批执行 | Petajisto (2011) *JEF*——可预测再平衡年化隐性成本 21–28bp,增补股票纳入前跑赢指数达 22% |
| 情绪/新闻信号被操纵(pump-and-dump) | 对 ERP/情绪类原始信号做异常跳变检测(价格-成交量异常模式),过滤脱离基本面的极端信号 | Kamps & Kleinberg (2018) *Crime Science*——加密资产"累积-拉升-出货"三阶段操纵模式,可类比情绪信号操纵 |
| 动量崩溃 / 尾部风险 | **CTA 层强制波动率目标化**(如年化 10–15%),可几乎消除动量崩溃、夏普接近翻倍;时序动量本身对权益/债券因子暴露低,是天然的尾部对冲 | Daniel & Moskowitz (2016) *JFE*; Barroso & Santa-Clara (2015) *JFE*; Moreira & Muir (2017) *JF*; Harvey et al. (2018) *JPM*; Moskowitz, Ooi & Pedersen (2012) *JFE* |
| 2022 式股债相关性转正 | ⚠️ 具体回撤数字(60/40 约 −17.5%,Risk Parity 基金 −15%至−25%)出自多篇机构报告综合表述而非单一学术论文,引用时须标注为业界共识、非学术定论 | CFA Institute《The Performance of the 60/40 Portfolio》等多份行业报告 |

**对本 agent 的具体改造**:BL 观点层对情绪/新闻类来源默认给低置信度、设单一观点最大权重上限(Idzorek 2007 式隐含权重倾斜法);预期收益不直接喂优化器,只作为 BL 观点做增量修正;整合层输出权重带置信区间,极端行情自动切换 CVaR/最坏情形目标。

### 7.4 系统侧:容错、回测防过拟合、对抗性红队

**数据容错**:对行情/新闻源调用包**断路器**(circuit breaker:closed/open/half-open,错误率或延迟超阈值即熔断);某专家方法所需数据缺失时应**弃权(abstain)**而非硬凑信号,BL 聚合层需正确处理"缺失观点"而非把 NaN 当 0;point-in-time 一致性校验防止用"未来才可得"的修订数据污染历史序列;关键不确定性场景下应"halt and escalate"(停止并升级人工),而非继续输出配置建议。

**回测防过拟合(核心,证据最扎实的领域,核心作者 David H. Bailey 与 Marcos López de Prado)**:

| 方法 | 用途 | 来源 |
|---|---|---|
| **Deflated Sharpe Ratio(DSR)** | 对夏普比率做多重检验+非正态性校正,区分真实 alpha 与统计噪声 | Bailey & López de Prado (2014) *JPM* |
| **PBO(Probability of Backtest Overfitting)** | 量化"策略选择过程"本身导致过拟合的概率 | Bailey, Borwein et al., *The Probability of Backtest Overfitting* |
| **CSCV(组合对称交叉验证)** | 计算 PBO 的具体框架:切成 S 个等长子集枚举样本内/外互换 | 同上;开源实现见 mlfinlab |
| **CPCV(组合清洗交叉验证)** | 出自 López de Prado《Advances in Financial Machine Learning》第 7/11 章:训练集"purging"(剔除与测试集标签期重叠的样本)+"embargo"(测试集后留缓冲期),生成多条独立回测路径而非单一路径 | mlfinlab CPCV 文档 |

实证对比(SSRN/ScienceDirect,已核实)显示 **CPCV 在降低 PBO、提升 DSR 上明显优于传统 Walk-Forward 和 K-Fold**,但 Walk-Forward 仍更贴近真实交易模拟——**两者建议并用而非互相替代**。落地要求:五个方法在被纳入 BL 融合权重前,都应单独过一遍 DSR + PBO 检验,防止某方法只是"在这段样本内凑巧好看";用 CPCV 生成的多路径分布(而非单一净值曲线)向风控/合规展示。

**对抗性红队(2026 年新出现的一批金融 LLM agent 专用评测框架,均已核实)**:
- **TraderBench**(arXiv:2603.00285)——测试 agent 在对抗性资本市场环境下的韧性,发现现有 agent 在对抗场景下有显著性能退化,尚不足以在真实混沌市场中可靠部署。
- **TradeTrap**(arXiv:2512.02261)——系统性压力测试交易 agent 四大组件,核心发现是 **agent 的"解释"往往与其实际决策过程不一致**(faithfulness gap),对 prompt injection、数据投毒等攻击向量存在明显脆弱性。这直接警示本系统:归因看板(第五节)展示的理由未必真正反映决策过程,须用 TradeTrap 式方法定期核验"解释"与"实际计算路径"的一致性。
- **AutoRedTrader**(arXiv:2605.09185)——三类攻击(认知偏差操纵、语义级微扰、风格改写规避检测),达到 69% 错误信息曝光率、26.67% 攻击成功率;关键发现已用于 7.2 的"时间序列锚定"防御。
- **Agent Security Bench / ASB**(arXiv:2410.02644)——覆盖 10 场景(含金融)、27 种攻击/防御方法,可直接复用其攻击分类法做本系统的红队测试大纲。

**运行时监控**:至少跟踪日度 P&L、Sharpe、信号命中率、平均滑点四维度,显著偏离历史分布即触发复核;新策略上线前应"影子运行"(paper trading)与实盘预测持续比对,容差内匹配才能"转正";新因子上线前做"拥挤度/新颖度"检查,防止与已知拥挤因子高度重合;kill switch 的核心原则是"failure investment 应与失败爆炸半径成正比"——资金决策类 agent 默认"遇不确定则停止升级",而非自行猜测继续。

**合规**:详见第五节 5.6——SR 11-7 已于 2026-04-17 被废止,新框架 SR 2026-02 按模型重要性分级,仍要求独立验证、outcomes analysis、持续监控三项核心能力,且这些证据应是系统设计的自然产物(即上文的 DecisionRecord/DSR-PBO 报告/红队记录),而非事后补造的备忘录。

---

## 第八节　上线前对抗性/稳健性检查清单

> 每项建议指定负责人 + pass/fail 阈值,作为发布门禁(release gate)。任一大类未通过,不得进入下一阶段(呼应第九节路线图)。

**A. 数据与运行时容错**
- [ ] 行情源/新闻源均有断路器,阈值与半开探测周期已压测触发过
- [ ] 任一专家方法在关键数据缺失时能弃权(abstain),BL 聚合层正确处理"缺失观点"
- [ ] Point-in-time 校验就位(无未来数据泄露、无前瞻偏差);单位/时区/交易日历/离群值自动校验规则上线
- [ ] "halt and escalate"路径可用

**B. 回测防过拟合**
- [ ] 每个专家方法与最终组合均通过 Deflated Sharpe Ratio 校正后仍显著为正
- [ ] PBO(经 CSCV/CPCV 计算)低于团队预设阈值(常见业界经验阈值 <0.5)
- [ ] Walk-Forward + CPCV 双轨验证,结论不冲突
- [ ] 记录策略挑选过程中试验过的候选数量(防隐藏的多重检验)

**C. 对抗性评估 / 红队**
- [ ] 新闻输入通道已用 AutoRedTrader 式方法(认知偏差注入+语义微扰+风格改写)测试,记录曝光率/攻击成功率
- [ ] 已做多轮(non-single-turn)红队测试
- [ ] 信号生成层强制"历史数据锚定"校验(7.2 第 6 点)
- [ ] 已覆盖 ASB 分类下至少直接注入、间接注入、记忆投毒三类攻击的防御测试
- [ ] 归因"解释"与实际计算路径的一致性已用 TradeTrap 式方法核验(防 faithfulness gap)

**D. 极端行情压力测试**
- [ ] 覆盖标准化冲击(利率±100bp、股指±10% 等)、历史重演(2008 GFC、2020 闪崩、2022 股债双杀)、至少 1 个针对本系统持仓特征的假设情景
- [ ] "股债相关性反转"场景已单独验证
- [ ] 极端行情下不崩溃/卡死/输出无效权重(如超界、和不为 1)

**E. Agent 一致性 / 鲁棒性**
- [ ] 同一市场情形用不同新闻措辞/数据呈现方式重复输入,配置建议保持一致(内部一致性测试集,覆盖至少 10 组语义等价改写)
- [ ] 五方法+BL 融合结果对合理范围内的参数微扰不出现权重剧烈跳变

**F. 运行时监控与护栏**
- [ ] 漂移监控看板上线(P&L / Sharpe / 信号命中率 / 滑点)
- [ ] Kill switch 就位:连续异常(如连续 N 次超阈值亏损或异常配置)自动限制新输出并通知人工
- [ ] 新因子/新信号上线前完成拥挤度/新颖度检查
- [ ] 独立验证团队(非开发团队)已完成 SR 2026-02 意义上的"有效挑战"并签署可版本化的验证记录

---

## 第九节　落地路线图(对应"后续接入实时行情与新闻源")

| 阶段 | 内容 | 数据 | 交付 |
|---|---|---|---|
| **Phase 1 · 离线内核** | 五方法确定性 tool + BL 整合 + 风控闸门,先跑通"信号 → 权重" | 历史行情(Tushare/AkShare/Qlib 数据集) | 可回测的配置引擎,对标等权/60-40 基线 |
| **Phase 2 · 接实时行情** | 上 MarketDataAdapter + 事件总线,行情驱动 CTA/Risk Parity/ERP 增量刷新 | 实时/准实时行情 API | 日频自动出配置建议 |
| **Phase 3 · 接新闻源** | 新闻 NLP 流水线 → 时钟象限 nowcasting + BL 观点提频 | GDELT/财新/RavenPack + FinBERT/LLM | 事件驱动的战术偏离 |
| **Phase 4 · 投委会前端** | 一页式三层溯源决策看板(L1信号 + L2 BL装配 + L3权重归因 + 风控),human-in-the-loop | — | 可解释、可下钻、可审计的投委会决策支持系统 |

> 每个阶段都以"跑赢朴素基线 + 通过第八节检查清单对应大类"为进入下一阶段的红线:Phase 1 对应 A/B 类,Phase 2 追加 D/F 类,Phase 3(接新闻源)必须先过 C 类红队测试才能上线,Phase 4 追加 E 类。

---

## 第十节　参考(全部已核实,截至 2026-07)

**架构与整合范式(agent)**
- TradingAgents:多智能体交易框架(LangGraph,分析师→辩论→交易员→风控). arXiv:2412.20138
- TradExpert:4 专家 LLM + General Expert 整合(最贴合"多方法+一整合层"). arXiv:2411.00782
- FinCon:经理-分析师分层 + 风控组 + 概念化言语强化. arXiv:2407.06567
- LLMoE / Automate Strategy Finding:按 regime 动态加权门控整合. arXiv:2501.09636 / arXiv:2409.06289
- AlphaAgents(BlackRock):基本面/情绪/估值专家辩论→共识. arXiv:2508.11152
- ReAct(工具调用范式,防幻觉基础). arXiv:2210.03629 · Reflexion. arXiv:2303.11366 · Multi-agent Debate. arXiv:2305.14325
- 综述:LLM Agent in Financial Trading: A Survey. arXiv:2408.06361

**整合层与数据(BL / 新闻 / 评估)**
- LLM-Enhanced Black-Litterman(LLM 预测 → BL 观点+置信度). arXiv:2504.14345
- Macroeconomic Forecasting with LLMs. arXiv:2407.00890 · 通胀 nowcasting 情绪. arXiv:2410.20198
- FinBERT(金融情绪). arXiv:1908.10063 · GDELT+FinBERT 宏观 nowcasting. arXiv:2505.16136
- Can ChatGPT Forecast Stock Movements(新闻情绪奠基). arXiv:2304.07619
- PortBench(评估警示:~90% 跑不赢等权). arXiv:2605.27887

**五方法基石文献**
- Risk Parity:Maillard, Roncalli & Teïletche (2010), On the Properties of Equally-Weighted Risk Contributions Portfolios, *JPM*. SSRN:1271972
- Time Series Momentum:Moskowitz, Ooi & Pedersen (2012), Time Series Momentum, *JFE*. SSRN:2089463
- Merrill Lynch Investment Clock:Greetham & Hartnett (2004), The Investment Clock, Merrill Lynch
- Equity Risk Premium:Asness (2003), Fight the Fed Model, *JPM*(Fed model 为业界启发式,非学术定论);ERP 数据 Damodaran (NYU Stern)
- Black-Litterman Model:Black & Litterman (1992), Global Portfolio Optimization, *FAJ*

**工程框架**:LangGraph · AutoGen · CrewAI · Microsoft Qlib / RD-Agent · FinRobot/FinGPT(AI4Finance)· NeMo Guardrails · Guardrails AI · Instructor(结构化输出)

**AI 侧对抗攻防(第七节 7.2,全部已核实)**
- Rizvani, Apruzzese & Laskov, Adversarial News and Lost Profits: Manipulating Headlines in LLM-Driven Algorithmic Trading, IEEE SaTML 2026. arXiv:2601.13082
- INJECAGENT(间接注入基准), ACL Findings 2024 · AgentDojo(97 任务/629 测试用例). arXiv:2406.13352
- OWASP Top 10 for Agentic Applications 2026(ASI01/06/08 最相关)
- PoisonedRAG(RAG 投毒,5 文档 90% 攻击成功率), USENIX Security 2025. arXiv:2402.07867
- Prompt Infection(多 agent 自我复制注入,GPT-4o 下 >80% 成功率), 2024. arXiv:2410.07283
- Byrd, Exploring Sentiment Manipulation by LLM-Enabled Intelligent Trading Agents, 2025. arXiv:2502.16343
- Spotlighting(微软,encoding 模式压 ASR 至 <2%), 2024. arXiv:2403.14720
- Dual-LLM 模式(Simon Willison, 2023,博客原文)
- CaMeL(Google DeepMind,架构层阻断注入), 2025. arXiv:2503.18813
- LlamaFirewall(Meta,ASR 降低 >90%), 2025. arXiv:2505.03574
- Rethinking the Reliability of Multi-agent System: A Perspective from BFT, AAAI 2026. arXiv:2511.10400(⚠️理论早期,不作生产级保障)

**量化侧组合稳健性(第七节 7.3,全部已核实)**
- Michaud, The Markowitz Optimization Enigma, *FAJ* 1989 · Scherer, Portfolio Resampling: Review and Critique, *FAJ* 2002
- Goldfarb & Iyengar, Robust Portfolio Selection Problems, *Math. of OR* 2003
- Rockafellar & Uryasev, Optimization of Conditional Value-at-Risk, *Journal of Risk* 2000
- Mohajerin Esfahani & Kuhn, Data-driven DRO Using the Wasserstein Metric, *Math. Programming* 2018. arXiv:1505.05116
- DeMiguel, Garlappi & Uppal, Optimal versus Naive Diversification, *RFS* 2009
- Ledoit & Wolf, Honey I Shrunk the Sample Covariance Matrix, *JPM* 2004 · Nonlinear Shrinkage…, *RFS* 2017
- Laloux, Cizeau, Bouchaud & Potters, Noise Dressing of Financial Correlation Matrices, *PRL* 1999. arXiv:cond-mat/9810255
- Ang & Bekaert, International Asset Allocation with Regime Shifts, *RFS* 2002 · Kritzman, Page & Turkington, Regime Shifts, *FAJ* 2012
- McLean & Pontiff, Does Academic Research Destroy Stock Return Predictability?, *JF* 2016
- Stein, Presidential Address: Sophisticated Investors and Market Efficiency, *JF* 2009
- Khandani & Lo, What Happened to the Quants in August 2007?, *JFM* 2011(NBER w14465)
- Asness, Frazzini & Pedersen, Leverage Aversion and Risk Parity, *FAJ* 2012
- Brunnermeier & Pedersen, Market Liquidity and Funding Liquidity, *RFS* 2009
- Petajisto, The Index Premium and Its Hidden Cost for Index Funds, *JEF* 2011
- Kamps & Kleinberg, To the Moon: Defining and Detecting Cryptocurrency Pump-and-Dumps, *Crime Science* 2018
- Daniel & Moskowitz, Momentum Crashes, *JFE* 2016(NBER w20439)· Barroso & Santa-Clara, Momentum Has Its Moments, *JFE* 2015 · Moreira & Muir, Volatility-Managed Portfolios, *JF* 2017 · Harvey et al., The Impact of Volatility Targeting, *JPM* 2018

**系统侧容错与评估(第七节 7.4,全部已核实)**
- Bailey & López de Prado, The Deflated Sharpe Ratio, *JPM* 2014 · The Probability of Backtest Overfitting(PBO/CSCV), Bailey/Borwein et al.
- López de Prado, *Advances in Financial Machine Learning*(CPCV,第 7/11 章);开源实现 mlfinlab
- TraderBench(对抗性资本市场韧性测试). arXiv:2603.00285
- TradeTrap(交易 agent faithfulness gap). arXiv:2512.02261
- AutoRedTrader(合成错误信息红队,时间序列锚定防御). arXiv:2605.09185
- Agent Security Bench / ASB(10 场景/27 种攻防). arXiv:2410.02644
- 美联储 SR 2026-02(取代已废止的 SR 11-7,2026-04-17 生效)

> 标 arXiv/SSRN 者均经 API 或一手来源核对(ID + 标题 + 作者一致)。业界产品名均可联网核实。设计中的"Risk Parity 先验 BL""五方法三层""三层对抗鲁棒性"为本方案的自定义组合,非某单一论文的现成结论——但每个积木都有上述先例支撑。标 ⚠️ 者为置信度较低或来源为多篇行业报告综合表述,已在正文注明。

---

## 第十一节　一句话总结

**五位专家各在自己擅长的资产上出结构化信号(数字由代码算),Black-Litterman Model 主席按置信度把观点融进 Risk Parity 先验,给出四类资产的目标配置;LLM 只读新闻、判象限、生成观点与解释,永远隔着一道确定性风控闸门,不碰真实资金;每个观点、每次决策都有血缘可查、可反查、可重放;上线前必须扛住 AI 侧注入、量化侧操纵、系统侧过拟合三重红队检验。** 先离线跑赢等权基线并通过检查清单,再接实时行情,再接新闻源。
