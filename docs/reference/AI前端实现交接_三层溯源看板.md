# AI 前端实现交接 · 三层溯源看板

> 交接对象: 前端工程师 / 前端 AI coding agent
> 目标: 把现有静态页面从“信号卡片墙”升级为“一页式三层溯源看板”,让用户在同一页看到四方法信号如何进入 Black-Litterman Model,最后如何得到目标权重。资产层面要支持 27 个明细资产,展示层面要按中国投资者视角汇总成 7 个资产桶。
> 配套样例: `frontend_three_layer_trace_mock.html`

---

## 1. 正式交付包

企业微信/飞书里的正式交付 ZIP 固定为 2 个 MD + 1 个 HTML:

1. `AI前端实现交接_三层溯源看板.md`
2. `AI资产配置投委会_五方法三层_AgentSKILL_V3.md`
3. `frontend_three_layer_trace_mock.html`

其中 `AI前端实现交接_三层溯源看板.md` 给 AI/前端读,`AI资产配置投委会_五方法三层_AgentSKILL_V3.md` 是权威规格与后端/API/风控/审计口径,`frontend_three_layer_trace_mock.html` 给 AI/前端看目标效果。完整预览图 `previews/three_layer_trace_mock_preview.png` 单独发送,不放入 ZIP。不要一开始把全部研究资料都发过去,否则对方容易偏离“前端怎么实现”这个任务。

---

## 2. 前端 AI 先读这两个入口

1. `AI前端实现交接_三层溯源看板.md`
   也就是本文件,给 AI/前端的最小实现说明。

2. `frontend_three_layer_trace_mock.html`
   可直接打开的目标形态样例。请优先照它实现主页面结构与交互。

同时把 `AI资产配置投委会_五方法三层_AgentSKILL_V3.md` 随包交付并放在同目录下。前端实现遇到字段、血缘、Black-Litterman Model 装配、后端/API、风控或审计口径冲突时,以 V3 为准,尤其第 5.2 和第 5.5 节。

---

## 3. 要实现什么

主页面必须同屏展示完整链路:

```text
L1 四方法信号
Risk Parity（唯一战略底仓）
Time Series Momentum / Merrill Lynch Investment Clock / Equity Risk Premium（战术偏离）
信号、置信度、弃权、rationale、source_refs、血缘
        ↓ source_signal_ids

L2 战术观点 + Black-Litterman Model 装配
Risk Parity 战略先验 + 战术观点
→ Black-Litterman Model 按置信度做贝叶斯融合
→ 后验收益 posterior_ER
        ↓ view_id / attribution

L3 最终权重
target_weights
prior → target 对比
He-Litterman attribution 瀑布
guardrail_actions 风控闸门
```

不要只做单独的信号页,也不要只做最终权重图。用户必须在一个页面里看见“信号怎么变成 Black-Litterman Model 观点,Black-Litterman Model 怎么变成权重”。

---

## 4. 资产层级:明细资产 + 中国投资者视角汇总

### 4.1 明细资产必须支持 27 个

```text
现金

沪深300指数
中证500指数
上证红利ETF（510880）
标普500指数（SPY ETF）
纳斯达克100指数（QQQ ETF）
欧洲斯托克50指数（FEZ ETF）
日本股票（iShares MSCI日本ETF·EWJ）
韩国股票（iShares MSCI韩国ETF·EWY）
恒生指数（盈富基金2800.HK）

10年期国债期货（主力连续）
中债1-3年期国债（合成总回报）
中债AAA级中短期票据·3年（合成总回报）
美国10年期国债期货（ZN）
美元投资级公司债（LQD ETF）

螺纹钢期货（主力连续）
沪铜期货（上期所主力连续）
WTI原油期货（CL）
布伦特原油期货（BZ）
CME黄金期货（GC）
CME白银期货（SI）

美元兑人民币（在岸CNY代理）
欧元兑美元
美元兑日元
英镑兑美元
澳元兑美元
美元兑加元
```

### 4.2 目标权重汇总层:先按 5 个大类,再展示 7 个细分桶

站在中国投资者视角,主页面第一眼不要展示 27 个资产的长表。目标权重汇总层必须先按 5 个大类展示比例,再给出每个大类下面的 7 个细分桶展示:

| 大类 | 细分桶 |
|---|---|
| 权益 | 中国股票、外国股票 |
| 债券 | 中国债券、外国债券 |
| 商品 | 商品 |
| 外汇 | 外汇 |
| 现金 | 现金 |

7 个细分桶继续保留如下:

| 汇总桶 | 明细资产 |
|---|---|
| 现金 | 现金 |
| 中国股票 | 沪深300、中证500、上证红利ETF、恒生指数/盈富基金 |
| 外国股票 | SPY、QQQ、FEZ、EWJ、EWY |
| 中国债券 | 10年期国债期货、中债1-3年期国债、中债AAA中短票 |
| 外国债券 | 美国10年期国债期货、LQD |
| 商品 | 螺纹钢、沪铜、WTI、布伦特、黄金、白银 |
| 外汇 | USDCNY、EURUSD、USDJPY、GBPUSD、AUDUSD、USDCAD |

前端必须同时保留:

- `assets[]`: 27 个明细资产。
- `asset_classes[]`: 5 个目标权重大类,用于顶部目标权重汇总层。
- `display_buckets[]`: 7 个展示汇总桶。
- 每个明细资产都有 `bucket` 字段,用于汇总。
- 每个大类都有 `bucket_ids` 字段,用于汇总到 7 个细分桶。

主页面顶部必须先用第一整行展示“最终结果”,再在下一部分展示“权重生成路径”。不要把战略底仓和战术偏离放在最终结果卡上方,否则用户第一眼看到的是过程而不是结论。

第一整行“最终结果”必须包含:

- 合成目标权重 `target` 的 5 个大类比例。
- 7 个细分桶比例。
- 最终建议 `conclusion`。

5 个大类比例应直接写在总配比堆叠条内部,使用“名称 + 百分比”的双行标签;手机端空间不足时可以隐藏条内文字,但下方大类框仍必须显示比例。权益与现金不得使用近似的绿/青色,现金建议使用中性石墨灰,确保五段一眼可分。

总配比条下方使用 5 个等宽大类框。每个框都要包含大类总权重、桶内小分段条和 1-2 个细分桶分框,例如权益框内明确展示“中国股票 28% / 外国股票 20%”。商品、外汇、现金等单桶大类也保持相同框高,不要让最后一项只占半行或长度不一致。

第二部分“权重生成路径”再拆成两个清晰层次:

```text
第一层: 战略底仓 prior
Risk Parity 独立给出可穿越周期的先验底盘
并像合成目标权重一样展示 5 大类 + 7 细分桶
        +
第二层: 战术偏离 + 观点整合
Time Series Momentum / Merrill Lynch Investment Clock / Equity Risk Premium
生成结构化观点,经 Black-Litterman Model 融合成 target - prior
        =
合成目标权重 target
```

顶部先看“目标权重 48%/27%/11%/8%/6%”和“权益 = 中国股票 28% + 外国股票 20%”这样的最终结果;下一部分先用同构大类框展示 Risk Parity 战略底仓,再解释例如“权益战略底仓 43% + Black-Litterman Model 战术偏离 +5 个百分点 = 目标权重 48%”。L3 权重区域再按细分桶下钻到底层标的。完整 27 项明细资产权重表和风控规则明细放在页面最底部的全宽附录区,不要塞进 L3 右侧栏,避免三列主链路失衡。

响应式不要硬保三列:只有宽屏空间足够时才并排 L1/L2/L3;中等屏幕和手机按 L1 → L2 → L3 纵向排列。切换点必须覆盖三列最小宽度与间距之和,任何视口都不得因强行并排产生横向溢出。

### 4.3 展示层级必须是三级

前端展示层级必须明确:

```text
5 个目标权重大类
权益 / 债券 / 商品 / 外汇 / 现金
        ↓ 细分展示
7 个细分桶
中国股票 / 外国股票 / 中国债券 / 外国债券 / 商品 / 外汇 / 现金
        ↓ 展开某个汇总桶
27 个底层标的
沪深300 / 中证500 / 510880 / 2800.HK / SPY / QQQ / ...
```

每个汇总桶展开后至少显示:

- 底层标的名称。
- 所属汇总桶。
- `prior` 先验权重。
- `target` 目标权重。
- `target - prior` 变化。

底层标的权重加总必须等于该汇总桶目标权重;汇总桶权重加总必须等于组合总权重 100%。

---

## 5. 主页面最低模块

### 顶部摘要

展示:
- `decision_id`
- `asof`
- 大类目标权重:由 `asset_classes[].bucket_ids` 汇总得到
- 细分桶 `target_weights`
- 权重闭合校验: `sum(target_weights)=100%`
- 归因闭合校验: `prior + Σ attribution = target_weights`
- 风控状态
- 一句清晰最终结论,例如“超配中国股票、低配中国债券、现金保留缓冲”

主页面把 `decision_id`、`asof` 格式化为“决策批次 20260709-0930”“时点 2026年7月9日 09:30”等人类可读中文;原始字段值保留在数据包或详情中,不要把机器格式直接作为视觉主信息。

### L1 四方法信号区

展示四张信号卡:
- Risk Parity: `risk_parity`
- Time Series Momentum: `tsmom`
- Merrill Lynch Investment Clock: `clock`
- Equity Risk Premium: `erp`

层级契约固定为:

- `risk_parity.layer = strategic`,是唯一战略底仓信号。
- `tsmom.layer = tactical`、`clock.layer = tactical`、`erp.layer = tactical`,三者只生成战术观点。

每张卡至少展示:
- `method`
- `layer`
- `view_type`
- `values`
- `confidence`
- `rationale`
- `abstain`

主卡的方法名固定使用英文,层级、观点类型、业务摘要和单位使用中文;`signal_id`、`source_refs`、版本、输入 hash 等技术血缘放在点击后的抽屉。这样主页面保持可读,但审计信息不丢失。

无效资产必须显示 `abstain`,不能省略。例如 Equity Risk Premium 对商品/外汇弃权。

信号区底部再加一个轻量“信号去向”摘要,用于把第一层和第二层接起来:

- Risk Parity:标明“进入战略底仓”。
- Time Series Momentum、Merrill Lynch Investment Clock、Equity Risk Premium:标明各自生成了几条 Black-Litterman Model 观点。
- 点击摘要行也要能打开同一条 `TracedSignal` 血缘详情。

五个展示名称和方法色在全页固定,不要因区域不同而换简称或换颜色:

| method | 统一显示名称 | 固定方法色 |
|---|---|---|
| `risk_parity` | Risk Parity | 绿色 |
| `tsmom` | Time Series Momentum | 蓝色 |
| `clock` | Merrill Lynch Investment Clock | 金色 |
| `erp` | Equity Risk Premium | 玫红色 |
| `black_litterman` | Black-Litterman Model | 蓝灰色 |

展示层禁止出现 `CTA / TSMOM / ERP / BL` 等简称;`tsmom / erp / bl_inputs / μ_BL` 等只允许作为机器字段或技术公式出现。方法色用于信号卡边线/名称、信号去向、观点卡、Black-Litterman Model 装配和观点归因标签;涨跌方向继续用正负号与红绿表达,资产类别继续使用资产色。三类颜色语义不能互相替代。

### L2 战术观点与 Black-Litterman Model 装配区

展示:
- 按汇总桶展示的 `prior`
- `posterior_ER`
- `bl_inputs.views[]`

L2 顶部必须先放一条直观作用链,不能只把观点卡、先验列表和后验表依次堆放:

```text
Prior · 战略先验: Risk Parity 底仓 → π = δΣw_RP
Views · 战术观点: Time Series Momentum / Merrill Lynch Investment Clock / Equity Risk Premium
                    → P（暴露）+ Q（观点收益）+ 置信度映射 Ω（不确定性）
        ↓
Black-Litterman Model: 按 Ω 将观点与战略先验做贝叶斯融合
        ↓
Posterior · 融合输出: 后验期望收益 → 目标权重 + 可闭合观点归因
```

这条作用链必须明确 Black-Litterman Model 是“整合器”而不是第五张普通信号卡,并让业务用户理解它不是对观点做简单平均。

主页面不要把 `Q / Ω / λ` 等技术量全部摊成宽表。默认用“Black-Litterman Model 观点卡”展示业务摘要,每张卡至少展示:

- 观点名称
- 英文来源方法,统一使用“Time Series Momentum / Merrill Lynch Investment Clock / Equity Risk Premium”之一
- P 的非零资产摘要
- `P_derivation`:资产选池、打分、腿内权重和归一检查
- 观点收益 `Q`
- `Q_derivation`:原始信号分数、校准尺度、期限和截断后的数值代入
- `confidence`
- `view_variance`:由后端回测/协方差校准得到,用于解释 confidence 如何映射 `Omega`
- 权重影响 `lambda`

`view_id`、`source_signal_ids`、`Omega`、完整 `P`、`derivation` 等技术细节放在点击后的血缘抽屉或 Black-Litterman Model 技术工作台里,不要挤在主页面。

`source_signal_ids` 必须能回到 L1 对应信号卡。

观点区与 P 矩阵必须按资产身份组织:

- 主页面先按 7 个 `display_buckets[]` 分组观点:中国股票、外国股票、中国债券、外国债券、商品、外汇、现金。默认展开第一个资产类别,其余折叠。
- 同一条相对观点可以同时出现在它影响的两个资产类别下,但 `view_id` 保持唯一,贡献显示当前资产类别对应的 `attribution[bucket][view_id]`。
- 每个分组摘要显示观点条数和该资产类别的净权重影响;组内观点按当前资产类别的 `abs(attribution)` 排序。
- 提供“展开全部类别”和“打开技术工作台”入口。主页面只展示 P 的非零明细资产摘要,不要把 27 列或所有技术参数硬塞进主页面。
- 技术工作台使用两个页签:“观点矩阵”和“计算过程与溯源”。矩阵页展示完整 P;计算页展示 `Prior → P/Q/Ω → Black-Litterman Model posterior → constrained target` 的公式与逐观点血缘。
- P 矩阵表头不能只显示机器 ID。每项资产依次显示中文简称、交易代码、所属资产类别;最上层再按 7 个资产类别做跨列表头。
- 每条矩阵行都提供“查看本行计算”,跳到该观点的 P 构造、Q 推导、confidence→Omega、权重贡献、来源信号、代码版本、输入 `data_id/asof/hash`。

### L3 权重与归因区

展示:
- 汇总桶 `target_weights`
- 汇总桶 `prior → target_weights` 对比
- 汇总桶下钻到底层标的:每个桶可展开查看桶内全部底层资产的 `prior / target / delta`
- 按汇总桶展示 `attribution`
- 底部附录展示 27 个明细资产权重表,默认显示前几行,按钮展开全部
- 底部附录展示 `guardrail_actions`

归因区默认显示每个汇总桶的“目标权重 + 净战术偏离”摘要行,只展开影响最大的一个桶;用户展开后再看底仓与各观点贡献。这样 7 个汇总桶仍完整可见,同时避免 L3 因所有归因标签平铺而过长。

`attribution` 里的每个非 prior 段必须用 `view_id` 做 key。例如:

```json
{
  "cn_equity": {
    "prior": 0.24,
    "view_clock_cn_equity": 0.02,
    "view_erp_cn_equity_bond": 0.015,
    "view_tsmom_cn_equity": 0.005
  }
}
```

点击 `view_clock_cn_equity` 这段,应能定位到 L2 的 `view_clock_cn_equity`,再定位到 L1 的 `sig_...clock...`。

---

## 6. 前端消费的数据形状

前端主页面消费一个聚合对象,可称为决策追踪数据包（`DecisionTraceBundle`）。

核心字段:

```json
{
  "decision_id": "dec_20260709_0930",
  "asof": "2026-07-09T09:30:00+08:00",
  "conclusion": "最终建议: 中国股票维持核心超配,海外股票保持参与;中国债券降到中性偏低,海外债券小幅低配;商品保留黄金/铜的结构性仓位,外汇与现金用于缓冲。",
  "display_buckets": [
    {"id": "cn_equity", "label": "中国股票"},
    {"id": "foreign_equity", "label": "外国股票"},
    {"id": "cn_bond", "label": "中国债券"},
    {"id": "foreign_bond", "label": "外国债券"},
    {"id": "commodity", "label": "商品"},
    {"id": "fx", "label": "外汇"},
    {"id": "cash", "label": "现金"}
  ],
  "asset_classes": [
    {"id": "equity", "label": "权益", "bucket_ids": ["cn_equity", "foreign_equity"]},
    {"id": "bond", "label": "债券", "bucket_ids": ["cn_bond", "foreign_bond"]},
    {"id": "commodity", "label": "商品", "bucket_ids": ["commodity"]},
    {"id": "fx", "label": "外汇", "bucket_ids": ["fx"]},
    {"id": "cash", "label": "现金", "bucket_ids": ["cash"]}
  ],
  "assets": [
    {"id": "csi300", "name": "沪深300指数", "bucket": "cn_equity", "target": 0.10, "prior": 0.085}
  ],
  "input_signals": ["sig_..."],
  "bl_inputs": {
    "views": [
      {
        "view_id": "view_clock_cn_equity",
        "source_signal_ids": ["sig_20260709_clock_001"],
        "P": {"csi300": 0.35, "csi500": 0.25, "dividend_510880": 0.20, "hsi_2800": 0.20},
        "P_derivation": "限定中国股票桶,按流动性与战略风险预算映射为 35/25/20/20,再归一为多头腿",
        "Q": 0.006,
        "Q_derivation": "(复苏概率72%-中性阈值50%)*2.7%=0.594%,记为0.60%",
        "confidence": 0.72,
        "view_variance": 0.00046286,
        "Omega": 0.00018,
        "lambda": 0.02,
        "derivation": "复苏象限概率 72% → A股/港股合计超配"
      }
    ]
  },
  "posterior_ER": {"cn_equity": 0.052, "foreign_equity": 0.045},
  "attribution": {
    "cn_equity": {"prior": 0.24, "view_clock_cn_equity": 0.02, "view_erp_cn_equity_bond": 0.015, "view_tsmom_cn_equity": 0.005}
  },
  "signals_by_id": {
    "sig_20260709_clock_001": {
      "signal_id": "sig_20260709_clock_001",
      "method": "clock",
      "layer": "tactical",
      "view_type": "regime",
      "values": {"regime": "复苏", "probability": 0.72, "cn_equity": 1, "cn_bond": -1},
      "confidence": 0.72,
      "abstain": ["fx"],
      "inputs": [{"data_id": "macro:PMI_CN", "source": "mock", "asof": "2026-07-09", "hash": "hash_pmi_cn"}],
      "derivation": "增长动能上行、通胀回落 → 复苏象限",
      "source_refs": ["macro:PMI_CN", "macro:CPI_CN"]
    }
  },
  "guardrail_actions": [
    {"rule": "max_equity_60pct", "triggered": false, "detail": "目标55% < 上限60%"}
  ]
}
```

`frontend_three_layer_trace_mock.html` 内已经内置一份完整样例数据,可以直接复用字段结构。

---

## 7. 交互要求

至少实现三类点击:

1. 点击 L1 信号卡
   展开该信号血缘: `agent_version / code_version / params / inputs / derivation / source_refs`。

2. 点击 L2 Black-Litterman Model 观点卡
   高亮对应 L1 信号卡,展示该观点的 `P/Q/Ω/λ/source_signal_ids/derivation`。

3. 点击 L3 归因瀑布段
   高亮对应 L2 观点卡和 L1 信号卡,展示这段贡献如何进入目标权重。

   默认先按汇总桶折叠归因;展开某桶后再点击观点贡献段。

4. 点击“打开技术工作台”
   默认进入完整 P 观点矩阵;可切换到“计算过程与溯源”,查看公式链和逐观点可复算血缘。矩阵每行也能直接跳到该行计算详情。

5. 滚动到底部附录,点击“显示全部明细”
   展示全部 27 个明细资产权重;风控规则明细也在底部附录查看。

6. 点击或展开某个汇总桶
   展示该桶内全部底层标的及每个标的的先验、目标、变化;桶内底层标的目标权重之和要等于该桶目标权重。

---

## 8. 验收标准

必须通过:

- 主页面同屏出现 L1、L2、L3。
- 顶部第一整行必须先展示最终结果:合成目标权重、5 个大类比例、7 个细分桶比例和最终建议;不是一上来把 27 个资产堆满首屏。
- 5 个大类的百分比直接显示在总配比条内;下方 5 个大类框等宽等高,并用小分段条与细分桶分框展示 7 个桶的构成。权益与现金颜色必须明显不同。
- 顶部下一部分必须明确拆出“第一层:战略底仓 prior”和“第二层:战术偏离 + 观点整合”,解释最终结果的生成路径;战略底仓只来自 Risk Parity,并与合成目标权重一样展示 5 大类和 7 细分桶。不能把路径放在最终结果之前。
- Time Series Momentum 必须归入战术偏离,不得再与 Risk Parity 并列为战略底仓。
- L2 顶部必须直观显示“Risk Parity 先验 + 三种战术观点 → Black-Litterman Model 贝叶斯融合 → 后验收益”,不能把 Black-Litterman Model 的作用隐藏在观点表和技术字段中。
- Risk Parity / Time Series Momentum / Merrill Lynch Investment Clock / Equity Risk Premium / Black-Litterman Model 五个英文全称及绿/蓝/金/玫红/蓝灰方法色必须在信号、观点、去向、装配、归因区域一致;可见区域出现 `CTA / TSMOM / ERP / BL` 即不通过。
- 主页面展示文案优先中文化:例如用“先验收益 / 后验收益 / 变化 / 观点矩阵 / 不确定性 / 权重推力”,不要在主页面表头直接暴露 `π / E[R] / Δ / Ω / λ` 等符号;技术符号可保留在后端字段或详情说明中。
- 主页面优先展示中文业务名称和人类可读时间;`signal_id / view_id / rule ID` 等机器标识必须保留在血缘抽屉、矩阵或数据层,不应占据主卡的第二视觉层级。
- 排版必须做视觉 QA:同一组状态卡等宽对齐,短标签不做英雄大数字,长句拆成短句,避免中文单字或两字孤行。
- 小字号正文与白色背景的颜色对比度至少达到 `4.5:1`;涨跌、通过/触发等状态不能只靠颜色区分,必须同时有文字或正负号。
- L3 的底层标的与观点归因都采用“摘要行 → 展开详情”,默认不把全部明细同时摊开;移动端把三层导航和闭合状态压缩为紧凑布局,不得出现横向溢出。
- 宽屏下 L1/L2/L3 必须使用三个等宽网格轨道,三个主面板等高且外框底边对齐;中栏内容不能因技术字段而单独变宽。底部“明细资产权重 / 风控闸门”两栏也等高。
- 顶部“最终结果”和“权重生成路径”必须复用同一组左右网格轨道,让最终权重区与战略底仓区左边界一致、最终建议区与战术偏离区左边界一致。
- 5 个大类权重必须由 7 个细分桶加总得到,且大类权重加总为 100%。
- 页面包含全部 27 个明细资产,L3 能按“汇总桶 → 底层标的”展开查看;完整 27 行明细表和风控规则明细放在页面底部附录,不能挤在 L3 右侧栏里破坏三列对称。
- 任一汇总桶展开后,桶内底层标的目标权重之和必须等于该桶目标权重。
- 任一汇总桶最终权重都能追到:

```text
display bucket target
→ attribution[bucket][view_id]
→ bl_inputs.views[view_id]
→ source_signal_ids
→ signals_by_id[signal_id].inputs/hash
```

- 页面显示明细资产和汇总桶权重均闭合到 100%。
- 页面显示 `prior + Σ attribution = target bucket weight` 的闭合校验。
- `Omega / lambda / posterior_ER / target_weights / attribution` 只能来自后端或样例数据,前端不要自己编数字。
- L1 中 Equity Risk Premium 对商品/外汇等无效资产必须显式显示 `abstain`。
- L2 观点必须按 7 个资产类别折叠组织;相对观点可在两个受影响类别下重复展示,但共用同一 `view_id`。
- Black-Litterman Model 技术工作台必须包含“观点矩阵 / 计算过程与溯源”两个页签。矩阵表头显示中文简称、代码、资产类别;任一矩阵行能跳到本行的 P/Q/Omega、公式、来源信号与输入 hash。
- 最终结论必须清晰可见,不能藏在表格下面。

不通过:

- 只做信号卡片墙。
- 只做最终权重饼图或柱状图。
- 归因只是自然语言解释,没有 `view_id` 链路。
- 点击最终权重无法追到原始信号和输入数据 hash。
- 资产扩展后页面变成长表,没有汇总桶、折叠或放大机制。

---

## 9. 推荐给 AI 的实现提示词

可以把下面这段直接给前端 AI:

```text
请阅读 AI前端实现交接_三层溯源看板.md,并参考 frontend_three_layer_trace_mock.html。

目标是实现一个一页式三层溯源主页面:
左侧 L1 四方法信号,中间 L2 战术观点与 Black-Litterman Model 装配,右侧 L3 最终权重和归因。

Risk Parity 是唯一战略底仓;Time Series Momentum、Merrill Lynch Investment Clock、Equity Risk Premium 全部归入战术偏离。顶部权重生成路径的战略底仓要像合成目标权重一样展示 5 大类和 7 细分桶,第二层标题使用“战术偏离 + 观点整合”。

中间 L2 顶部先画清“Risk Parity 战略先验 + 三种战术观点 → Black-Litterman Model 贝叶斯融合 → 后验收益”,再展示观点卡、先验与后验明细。五个展示名称在全页统一使用英文全称和固定色:Risk Parity 绿、Time Series Momentum 蓝、Merrill Lynch Investment Clock 金、Equity Risk Premium 玫红、Black-Litterman Model 蓝灰。

资产层面要支持 27 个明细资产;目标权重汇总层先按 5 个大类展示: 权益、债券、商品、外汇、现金;再展示 7 个细分桶: 中国股票、外国股票、中国债券、外国债券、商品、外汇、现金。

不要只做信号卡片页,不要只做最终权重图。必须能从汇总桶目标权重追溯到 attribution[bucket][view_id],再追到 bl_inputs.views[view_id],再追到 source_signal_ids 和 signals_by_id[signal_id].inputs/hash。

L2 观点先按中国股票、外国股票、中国债券、外国债券、商品、外汇、现金分组折叠。P 矩阵会因为明细资产变多而很宽,放在双页签技术工作台中;表头显示中文简称、代码和资产类别,每行可跳到计算过程与输入血缘。完整明细资产权重表放在页面底部附录,默认显示部分行,提供“显示全部明细”。

宽屏 L1/L2/L3 使用等宽三栏;顶部最终结果与权重生成路径复用同一左右分栏比例,边界必须对齐。

目标权重汇总层必须先按大类分,再给细分展示。L3 里必须同时有汇总桶视图和底层标的下钻:用户先看到 7 个汇总桶,再展开任意汇总桶看里面有哪些底层标的、各自 prior/target/delta 多少。完整 27 行长表只作为底部附录,不能替代 L3 下钻。

请优先复用 HTML 样例的字段结构和交互逻辑,生产实现时把样例决策追踪数据包（DecisionTraceBundle）换成真实 API 返回。
```
