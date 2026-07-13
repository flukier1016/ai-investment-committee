# 资产配置方法论优化方案 V4（实施规格）

> 状态：Proposal，尚未替代 V3 权威规格。  
> 文档方法版本：4.2.0。
> 目标读者：负责修改战略底仓、风控投影、配置契约和回测门禁的工程 Agent。  
> 核心目标：解决低波动中国债券吸收过多资本、权益资本权重长期过低、问卷可放宽治理上限，以及真实数据接入后协方差被平滑行情放大的问题。

## 1. 先给结论

当前实现是“资产类别风险预算 ERC + 桶内逆波动率”，不是严格意义上的宏观环境平衡。低波动中国债券为了取得与股票相近的风险贡献，会自然获得很高的资本权重；当前约束又只有债券下限、没有债券上限和权益下限，因此该偏置可以一直放大。

本次优化分两阶段，但必须区分“治理止血”和“方法修复”：

1. **Phase A：Bounded Risk Parity**。保持现有 Risk Parity 和 Black-Litterman 主链，补齐治理约束、政策权重区间、黄金防御子袖、压力协方差和战术偏离上限。该阶段优先止血，但中国债券最终落在 30% 不能被表述为方法论成功；如果去掉 cap 又回到 60%，说明只是约束在替模型做决定。
2. **Phase B：Macro-Factor & Risk-Source Balance**。把“资产桶等风险”改为“宏观环境风险平衡 + 独立风险源去重 + 资本分散软正则”。中国债券权重必须由久期、曲线、信用、流动性和环境贡献共同生成，而不是由 `cn_bond_cap` 生成。该阶段通过 feature flag 并行回测，验证通过后才是 V4 的目标战略模型。

不应只修改 `RISK_BUDGETS`，也不应把“中国债券刚好等于 30%”当作验收目标。单纯提高权益风险预算仍可能得到很低的权益资本权重，也无法解决债券行情平滑、同类债券被误认成多个独立机会、期货权重语义和治理上限被问卷覆盖的问题。

## 2. 方法论目标与边界

### 2.1 目标

- 战略组合不依赖单一低波动资产或单一宏观环境。
- 资本权重满足投资授权；风险权重尽量平衡宏观环境。
- 战略 Beta 与战术 Alpha 分离，战术观点不能重写战略资产结构。
- 真实数据异常必须在进入协方差前显式失败或降级，不能静默制造低波动。
- 所有计算保持确定性、可回放、可归因、可闭合。

### 2.2 非目标

- 不复制或声称复现 Bridgewater 的非公开持仓和优化器。
- 不引入 LLM 直接生成权重、风险预算、协方差或约束参数。
- 不在本次改造中接入自动下单、融资或真实杠杆。
- 不以提高历史收益作为唯一验收条件。

### 2.3 公开方法依据

Bridgewater 对 All Weather 的公开描述是平衡四类经济意外，而不是简单让每个资产类别风险贡献相等：

- 增长高于预期；
- 增长低于预期；
- 通胀高于预期；
- 通胀低于预期。

公开资料同时强调战略 Beta 与战术 Alpha 分离、全球液体市场分散、通胀保护资产、压力环境检验，以及在允许时用衍生品和适度杠杆让低波动资产达到目标风险。参考：

- [Bridgewater: The All Weather Story](https://www.bridgewater.com/research-and-insights/the-all-weather-story)
- [Bridgewater: Investing in a New World](https://www.bridgewater.com/research-and-insights/investing-in-a-new-world-capturing-opportunity-and-weathering-uncertainty)
- [Bridgewater: A New Era of Higher Inflation Risks](https://www.bridgewater.com/research-and-insights/a-new-era-of-higher-inflation-risks)
- [World Gold Council: Gold as a strategic asset](https://www.gold.org/goldhub/research/relevance-of-gold-as-a-strategic-asset-2025)
- [NBER: The Golden Dilemma](https://www.nber.org/papers/w18706)
- [Roncalli & Weisang: Risk Parity Portfolios with Risk Factors](https://www.thierry-roncalli.com/download/risk-factor-parity.pdf)
- [Getmansky, Lo & Makarov: Serial Correlation and Illiquidity](https://www.nber.org/papers/w9571)
- [BIS: Interest-rate risk, duration and PV01](https://www.bis.org/basel_framework/chapter/SRP/98.htm)
- [López de Prado: Hierarchical Risk Parity](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2708678)
- [Meucci, Santangelo & Deguest: Effective Number of Bets](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2276632)

黄金行业研究强调其流动性和分散作用，但 NBER 的长期研究也提醒：黄金在实用投资期限内并不是稳定、机械的通胀对冲。因此本方案只把黄金定义为**有上限的防御分散器**，不把它写成必然上涨的通胀资产，也不根据单个年份的事后收益反推长期权重。

本方案只能称为 **All Weather-inspired macro balance**。

### 2.4 核心方法选择

V4.2 的目标方法不是“给资产桶做更多硬约束”，而是以下三层：

```text
真实风险层      债券 DV01/关键期限/信用/流动性 + 去平滑收益 + 压力情景
结构配置层      四宏观环境 sleeve 等风险 + 重复风险源只计一次
资本选择层      在贴近环境平衡解的前提下，最大化独立资本来源的有效数量
```

硬约束继续存在，但只承担投资授权、极端输入和求解错误的最后防线。正常月份中 `cn_bond_cap`、总债券上限和单资产上限应保持明显松弛；若长期贴边，模型不得继续标记为“方法已修复”。

## 3. 当前问题的确定性定位

### 3.1 Risk Parity 平衡的是风险，不是资本

当前桶间优化：

```text
min 0.5 × y'Σy - Σ bᵢ ln(yᵢ)
```

中国债券波动越低，为取得给定风险预算 `bᵢ` 所需的资金权重越高。这是算法属性，不是求解器故障。

### 3.2 约束方向不对称

当前约束包含：

- long-only；
- 单资产上限；
- 中国股票上限；
- 权益大类上限；
- 债券大类下限；
- 组合波动率上限。

缺少：

- 中国债券桶上限；
- 债券大类上限；
- 权益大类下限；
- 现金硬下限；
- 战术层相对战略底仓的累计偏离上限。

因此系统限制“股票不能太多、债券不能太少”，却不限制“债券不能太多”。

### 3.3 性格问卷混淆风险偏好与治理权限

问卷目前可以把默认 10% 的单资产上限提高到 25%—35%甚至更高的前端展示值。风险偏好可以改变目标波动率和战略风险预算，但不应放宽机构级集中度红线。

必须拆分：

```text
effective_cap = min(governance_cap, profile_cap, asset_specific_cap)
```

任何用户画像只能收紧、不能放宽 `governance_cap`。

后端 `PersonalityProfile.apply_to()` 至少改为：

```python
"single_asset_cap": min(config.single_asset_cap, self.single_asset_cap)
```

前端 `applyType()` 不再直接写入更大的 `single_asset_cap`；可以展示画像建议值，但保存配置时必须保留当前更严格值。启用 V4 后还要再与 `governance_single_asset_cap` 取最小值。

### 3.4 真实债券数据可能产生“假低波动”

以下情况会系统性抬高中国债券权重：

- 估值型债券指数连续零收益或价格平滑；
- 缺失数据被上游前值填充；
- 中外交易日不一致后直接拼接；
- 期货连续合约换月跳点未处理；
- 国债期货价格风险被错误解释为资金占比；
- 信用债指数没有流动性和信用压力期；
- 仅使用近期样本协方差，没有长期或压力状态。

数据质量门禁必须先于任何优化器调整。

### 3.5 黄金被普通商品桶稀释

当前商品桶包含螺纹钢、铜、原油、黄金和白银等不同经济暴露。若商品政策中枢为 10% 并在六项资产内等权展开，黄金的战略中枢只有约 1.67%；TSMOM 又先把资产分数平均成商品桶方向，强黄金信号可能被弱原油或黑色商品稀释。

对提供的 v3 历史数据做严格 point-in-time 检查，截点为 2023-12-29：

- 黄金 12-1 动量约 `+12.36%`；
- 60 日年化波动约 `14.00%`；
- 标准化动量分数约 `+0.88`，在六项商品中最高；
- 近 504 个观测中，黄金与沪深 300、标普 500 的相关系数约为 `0.11`、`0.08`，与三项中国债券约为 `-0.10` 至 `-0.06`。

这些都是 2024-01-01 当时可见的信息，足以支持“黄金具有不同于工业品和能源的组合角色”。黄金在 2024 年随后上涨约 27.5% 只能作为事后验证，禁止进入政策中枢、阈值或回测筛选条件，也不能证明 3% 是普适最优权重。

### 3.6 三只中国债券不是三个独立风险来源

`tbond_fut`、`cgb_1_3`、`credit_aaa` 虽是三个资产 ID，但主要共同暴露于中国利率曲线；信用债只是在共同久期之外增加信用利差与流动性暴露。按资产数或桶内逆波动率分配，会把“多了两个载体”误判成“多了两个独立风险机会”。

V4.2 必须同时维护：

- 多重因子暴露矩阵 `B`：资产可以同时加载中国曲线 level/slope、信用利差、权益增长、工业通胀、黄金货币属性和外汇因子；
- 唯一主风险源映射 `G`：每项资产只归属一个用于资本分散统计的 `primary_risk_source`，避免一个资产重复增加资本有效赌注数。

风险预算使用 `B` 和宏观 sleeve；资本分散使用 `G`。两者不能用“资产桶名称”代替。

### 3.7 无杠杆等风险与低债券资本不可同时免费获得

Bridgewater 的公开例子明确说明：低波动债券需要更多名义敞口，若要在保持收益目标的同时平衡风险，通常还需适度杠杆。当前项目是 long-only、无杠杆资金权重模型，因此不可能同时保证：

1. 四环境严格等风险；
2. 中国债券资本很低；
3. 组合仍达到与高风险资产相近的收益/波动目标。

V4.2 必须显式选择运行模式：

- `unlevered_capital_balanced`：接受环境风险贡献存在容差，用资本分散软正则避免低波动资产吞噬资金；
- `notional_risk_balanced`：允许受治理的期货/衍生品名义敞口，在 exposure 空间平衡风险，再单独核算保证金和抵押现金。

禁止在无杠杆模式下声称完全复现 All Weather，也禁止把高债券名义敞口直接显示成同等比例的资金占用。

## 4. Phase A：Bounded Risk Parity

### 4.1 推荐的初始政策区间

以下参数只作为“无杠杆、平衡型多资产账户”的起始候选，必须允许投资授权覆盖：

| 维度 | 中枢 | 下限 | 上限 |
|---|---:|---:|---:|
| 权益大类 | 30% | 20% | 45% |
| 债券大类 | 45% | 30% | 60% |
| 商品大类 | 10% | 5% | 20% |
| 黄金防御子袖 | 3% | 1% | 5% |
| 外汇风险 | 10% | 0% | 15% |
| 现金 | 5% | 5% | 15% |
| 中国债券桶 | — | — | 40% |
| 中国股票桶 | — | — | 35% |
| 单一明细资产 | — | — | 10% |

对应的初始桶级政策中枢为：

```text
cn_equity       15%
foreign_equity  15%
cn_bond         30%
foreign_bond    15%
commodity       10%
fx              10%
cash             5%
```

以上 `cn_bond=30%` 只属于 `bounded_risk_parity` 的过渡政策锚和可行性基线，不是 `macro_factor_balanced` 的目标、下限或期望输出。Phase B 不把任何中国债券资本中枢写入目标函数；页面也必须把它标注为“Fallback policy”，不能展示成模型发现。

表中的黄金是商品大类内部子袖，不是额外大类；预检大类下限合计时只能计入商品一次，禁止把商品 10% 与黄金 3% 相加成 13%。

`policy_bucket_targets` 必须完整覆盖当前 universe 的展示桶并严格加总为 1。V4 第一版原则上按桶内等权展开，但增加唯一、版本化的黄金防御子袖例外：先从 `commodity` 目标中分配 `gold_policy_target` 给 universe 中唯一标记为 `strategic_role=defensive_gold` 的资产，再把剩余商品目标等权分配给非黄金商品。第一版不开放任意资产级覆盖字典，避免形成未经治理的权重入口。

默认商品目标为 10% 时，展开结果为黄金 3%，其余五项商品合计 7%（每项 1.4%）。若黄金角色缺失、重复，或剩余商品目标在单资产上限下不可行，V4 必须失败；不得回退到按资产 ID 猜测，也不得临时提高单资产上限。展开结果仍须经过同一套硬约束投影，得到真正可行的 `w_policy`。

说明：

- “外汇风险”不是外币现金余额，也不应机械获得 25% 风险预算；货币配置与资产 Beta 应分开记录。
- 若账户明确是固收增强型，应通过一套命名场景覆盖上述区间，而不是让问卷临时放宽集中度红线。
- 三只中国债券在 10% 单资产上限下最多合计 30%；如果希望桶上限为 40%，应增加真正不同风险来源的债券工具，而不是放宽单券上限。
- 黄金是商品大类中的独立治理子袖，不新增第八个展示桶；白银具有更强工业属性，第一版仍归入普通商品，不得自动并入黄金子袖。
- `gold_floor/gold_cap` 同时作用于战略政策投影和最终战术投影；黄金仍受更严格的有效单资产上限约束。
- 非现金资产受 10% 单资产上限约束；基础货币现金不受该上限约束，但受现金上下限约束。
- 如果一个现金桶包含多个币种，默认现金中枢只能分配给 `AllocationConfig.currency` 对应的基础货币现金；其他币种现金属于外汇风险，必须显式配置。

### 4.2 新增配置字段

为保持历史配置指纹、默认 decision ID 和旧 DecisionRecord JSON 形状不变，不要把所有 V4 字段直接平铺到 `AllocationConfig`。使用一个默认值为 `None` 的可选嵌套配置：

```python
from typing import Literal

from pydantic import BaseModel, Field, model_validator


def default_policy_targets() -> dict[str, float]:
    return {
        "cn_equity": 0.15, "foreign_equity": 0.15,
        "cn_bond": 0.30, "foreign_bond": 0.15,
        "commodity": 0.10, "fx": 0.10, "cash": 0.05,
    }


class MethodologyV4Config(BaseModel):
    model_config = {"validate_default": True}

    schema_version: Literal["v4"] = "v4"
    method_version: Literal["4.2.0"] = "4.2.0"
    strategic_model: Literal["bounded_risk_parity", "macro_factor_balanced"] = \
        "bounded_risk_parity"
    implementation_mode: Literal["unlevered_capital_balanced", "notional_risk_balanced"] = \
        "unlevered_capital_balanced"
    risk_source_schema_version: Literal["source_v1"] = "source_v1"
    bond_risk_model: Literal["factor_scenario_hac"] = "factor_scenario_hac"
    bond_hac_lags: int = Field(default=5, ge=1, le=21)
    scenario_cov_weight: float = Field(default=0.30, ge=0, le=1)
    capital_regularizer: Literal["max_entropy_tracking"] = "max_entropy_tracking"
    max_strategic_tracking_error: float = Field(default=0.015, gt=0, le=0.10)
    min_effective_capital_sources: float = Field(default=5.0, ge=1)
    governance_single_asset_cap: float = Field(default=0.10, gt=0, le=1)
    cn_bond_cap: float = Field(default=0.40, gt=0, le=1)
    bond_class_floor: float = Field(default=0.30, ge=0, le=1)
    bond_class_cap: float = Field(default=0.60, gt=0, le=1)
    equity_class_floor: float = Field(default=0.20, ge=0, le=1)
    equity_class_cap: float = Field(default=0.45, gt=0, le=1)
    commodity_floor: float = Field(default=0.05, ge=0, le=1)
    commodity_cap: float = Field(default=0.20, gt=0, le=1)
    gold_policy_target: float = Field(default=0.03, ge=0, le=1)
    gold_floor: float = Field(default=0.01, ge=0, le=1)
    gold_cap: float = Field(default=0.05, ge=0, le=1)
    fx_floor: float = Field(default=0.00, ge=0, le=1)
    fx_cap: float = Field(default=0.15, gt=0, le=1)
    cash_hard_floor: float = Field(default=0.05, ge=0, le=1)
    cash_policy_target: float = Field(default=0.05, ge=0, le=1)
    cash_cap: float = Field(default=0.15, gt=0, le=1)
    policy_anchor_weight: float = Field(default=0.50, ge=0, le=1)
    max_bucket_tactical_tilt: float = Field(default=0.05, ge=0, le=0.30)
    max_total_tactical_deviation: float = Field(default=0.15, ge=0, le=1)
    stress_cov_weight: float = Field(default=0.30, ge=0, le=1)
    stress_vol_window_days: int = Field(default=60, ge=20)
    stress_history_days: int = Field(default=1260, ge=120)
    stress_vol_quantile: float = Field(default=0.90, gt=0.50, lt=1)
    min_stress_windows: int = Field(default=120, ge=30)
    policy_bucket_targets: dict[str, float] = Field(default_factory=default_policy_targets)

class AllocationConfig(BaseModel):
    # 原有字段保持不变。
    methodology_v4: MethodologyV4Config | None = None
```

`MethodologyV4Config` 必须使用 `model_validator(mode="after")` 校验各组 floor/cap、政策目标加总和基础字段关系；还必须校验 `gold_floor ≤ gold_policy_target ≤ gold_cap ≤ commodity_cap`、`gold_policy_target ≤ policy_bucket_targets["commodity"]`、`cash_hard_floor ≤ cash_policy_target ≤ cash_cap`。依赖 universe 的主风险源数量和剩余商品容量由求解前的结构预检校验。不要只依赖 CVXPY 才发现显然错误的配置。

兼容纪律：

- `methodology_v4 is None` 是唯一 legacy 开关；此时不得执行任何 V4 逻辑。
- `policy_anchor_weight` 和 `policy_bucket_targets` 只供 `bounded_risk_parity`；`macro_factor_balanced` 不得把 `cn_bond=30%` 读入战略目标函数。
- `stress_cov_weight` 只供 Phase A 的 price-based recent/stress 混合；`scenario_cov_weight` 只供 Phase B 的 factor/scenario 混合。两条路径不得先后套用两个权重，避免压力风险被重复计算。
- `macro_factor_balanced` 的资本中性先验来自版本化独立风险源的等权分布，不来自资产数量、地区市值或历史最优权重。
- `fingerprint_payload()` 使用 `model_dump(exclude_none=True)`；`pipeline.py` 写入 `DecisionRecord.config` 时必须复用 `fingerprint_payload()`，不能另调裸 `model_dump()`。
- `/api/config/defaults`、`run_decision_cached` 和所有配置哈希调用点都要审计 `model_dump()` / `model_dump_json()`，确保 `methodology_v4=None` 不进入历史默认 payload。
- V4 非空时，完整嵌套配置必须进入配置指纹、缓存键和 DecisionRecord。
- `method_version` 覆盖压力协方差、政策投影、约束修复和 sleeve 构造的数值语义；任一规则发生不兼容变化都必须升级版本，禁止原地改义。
- 原有 `single_asset_cap` 继续保留；V4 生效上限为 `min(single_asset_cap, governance_single_asset_cap, asset_specific_cap)`。
- 原有上限类字段与 V4 上限取较小值；原有下限类字段与 V4 下限取较大值。这样启用 V4 不会放宽用户已有约束。
- 旧 DecisionRecord 只读取和展示，不用当前配置重算；旧记录反序列化不得自动补一个非空 V4 对象。
- API 和前端必须明确区分“投资偏好”与“治理红线”。

提交配置改造前先执行：

```bash
rg -n "model_dump\\(|model_dump_json\\(" backend tests
```

逐个确认默认 `None` 是否会改变序列化、指纹、缓存键或固定 fixture。

### 4.3 战略底仓构造

先把当前 `strategic_weights()` 拆成“计算原始 RP”与“投影”两个内部步骤。legacy 路径必须按原顺序调用并保持结果不变；V4 使用尚未经过 legacy 约束投影的 `w_rp_raw`，避免把两套约束叠加后误称为原始 RP。

桶级政策中枢按规则展开为 `w_policy_requested`，再解：

```text
min ||w - w_policy_requested||²
s.t. 全部 V4 硬约束（包括波动率上限）
```

得到已知可行点 `w_policy`。若该问题不可行，直接输出第 4.8 节的诊断，不再运行正式战略优化。随后计算：

```text
min_w
    (1 - α) × (w - w_rp_raw)' M_norm (w - w_rp_raw)
  + α × ||w - w_policy||²

s.t.
    Σw = 1
    w ≥ 0
    单资产、桶、大类上下限
    gold_floor ≤ w_gold ≤ gold_cap
    cash ≥ cash_hard_floor
```

其中：

- `M_norm = Σ_effective / max(trace(Σ_effective), 1e-12) + εI`，避免协方差量纲使政策项完全支配或完全失效；
- `α = policy_anchor_weight ∈ [0,1]`，建议初始 0.50；
- `α=0` 仍受硬约束，不等同 legacy；`α=1` 为最接近政策锚的组合；
- `ε` 使用固定常量并写入方法版本，不能随机器环境变化；
- 战略投影阶段不使用战术观点；
- 输出必须同时保存 `policy_target_requested`、`w_rp_raw`、`w_policy`、`w_strategic` 和战略投影差异；
- `w_strategic` 必须先满足全部 V4 硬约束，确保最终战术投影至少存在一个已知可行点。

上述目标是凸二次目标，配合线性边界和现有二次波动率约束满足 CVXPY DCP 规则，可继续使用 CLARABEL。

### 4.4 压力协方差

将当前单一滚动样本协方差升级为：

```text
Σ_effective = (1 - ρ) × Σ_recent + ρ × Σ_stress
```

- `ρ = stress_cov_weight`，建议初始 30%。
- `Σ_recent` 继续使用 point-in-time 收缩协方差。
- 第一版使用可直接实现且天然 PSD 的压力波动放大法：
  1. 从 `Σ_recent` 得到经 eigenvalue floor 修复的相关矩阵 `R_recent`；
  2. 对每个资产在截至 as-of、最多 `stress_history_days` 的窗口内计算 `stress_vol_window_days` 日滚动年化波动率序列；
  3. `stress_volᵢ = max(recent_volᵢ, rolling_volᵢ 的 90% 分位)`；
  4. `Σ_stress = diag(stress_vol) × R_recent × diag(stress_vol)`；
  5. 对 `Σ_effective` 再做对称化与固定 eigenvalue floor，并记录修复前最小特征值。
- 压力分位只使用 as-of 前可见历史；有效滚动窗口数不得少于 `min_stress_windows`。
- 压力历史不足时，V4 计算必须失败并给出 `InsufficientStressHistoryError`；影子阶段可以捕获并显示失败，但不能静默使用普通协方差冒充压力协方差。
- 后续可以加入历史压力窗口相关性，但必须作为独立版本，不能修改同一 `schema_version` 的含义。
- 不允许对单个资产直接手填较大波动率后与原协方差混用。

### 4.5 数据质量门禁

每个风险资产至少检查：

| 检查 | 建议规则 | 失败动作 |
|---|---|---|
| 新鲜度 | 最新价格与 as-of 差值不超过资产日历阈值 | 核心资产失败则中止 |
| 缺失率 | 窗口内缺失率低于配置阈值 | 失败或剔除并记录 |
| 连续零收益 | 最长连续零收益不超过资产阈值 | 标记平滑风险，禁止直接进协方差 |
| 价格跳点 | 超过历史稳健尺度的异常跳点 | 要求换月/复权说明 |
| 重复序列 | 相关系数近 1 且收益逐点相同 | 拒绝重复风险来源 |
| 交易日历 | 使用资产日历对齐策略 | 禁止无记录的全局前值填充 |
| 期货语义 | 合约乘数、保证金、展期、目标名义敞口完整 | 不完整则不可投资 |
| 黄金币种与载体 | 明确本币总回报、外币未对冲或期货连续合约口径 | 口径不明则黄金子袖不可投资 |

所有门禁结果进入 DecisionRecord 的输入血缘或独立 `data_quality` 区块。

对于 CNY 账户，禁止把未换算的美元黄金价格与人民币资产直接拼成“人民币组合收益”。黄金输入必须选择以下一种并写入血缘：人民币可投资总回报载体；美元黄金收益叠加明确的 USD/CNY 敞口；或带抵押品、展期和保证金账本的期货收益。独立外汇桶不得与黄金载体中的同一货币风险重复计算。

协方差输入的第一版对齐规则固定为：

1. 上游保留原始缺失，不允许跨交易日历做无记录的全局 `ffill`。
2. 每个资产先按自身交易日历判定“正常休市”与“异常缺失”。
3. 生成收益后再取所有入选资产的共同有效日期；不得把休市日收益写成 0。
4. `effective_cov_observations` 使用最终收益矩阵的真实行数，而不是价格表行数。
5. 有效观测不足 `cov_window_days` 时，按现有契约记录 `cov_window_full=false`；少于配置最低值则中止战略计算。
6. 若共同有效日期损失过多，第二版可以增加“周频协方差”作为独立模型版本；第一版禁止临时切换频率。

不要直接改成 pairwise covariance：不同资产对使用不同样本会使矩阵不一定 PSD，并破坏后续二次规划。

当前输入指纹只依赖价格表长度和最后一行，无法识别历史窗口中间值被修订；但协方差、压力波动率和动量都会消费历史序列。为了同时保持 legacy decision ID 不变，MarketSlice 必须并存两套指纹：

- `fingerprint_v1`：完全保留当前算法，只供 `methodology_v4=None` 使用；
- `fingerprint_v2`：对实际参与计算的可见价格、宏观和 ERP 窗口做 canonical hash，只供 V4/影子模型使用；
- hash 必须包含日期、列顺序、缺失位置和数值；
- 任一被消费历史值改变，都必须改变 `input_fingerprint`、decision ID 和缓存键；
- 不允许只 hash 最后一行或文件修改时间；
- V4 DecisionRecord 的 `input_fingerprint` 使用带 `v2:` 前缀的指纹；旧记录和 legacy 新决策继续使用原 v1 字节值；
- `fingerprint_v2` 还必须包含 universe 文件的 canonical hash；资产归属、币种或工具类型变化必须使 V4 决策失效重算；
- `MarketSlice.input_meta()` 必须由 pipeline 显式传入或选择指纹版本，禁止默认拿错版本。

### 4.6 期货与现金资产的权重语义

不得把期货“名义风险敞口”与 ETF/指数“资金占用权重”混在同一字段中。

至少拆分：

```text
target_exposure_weight   # 参与收益与风险计算的名义敞口
capital_allocation       # 真实资金占用/保证金/现金抵押
dv01_or_contracts        # 固收期货执行口径
collateral_currency      # 抵押品币种
```

在执行层完成 `target_exposure_weight → 合约数/DV01/保证金` 转换；战略优化器不得假设 10% 国债期货等于占用 10% 现金。

### 4.7 战术层约束

Black-Litterman 继续负责观点融合，但最终战术偏离必须满足：

```text
|bucket_target - bucket_strategic| ≤ max_bucket_tactical_tilt
0.5 × Σ|w_target - w_strategic| ≤ max_total_tactical_deviation
```

建议初始：

- 单桶累计偏离不超过 5pp；
- 全组合理论单边换手不超过 15%；
- 每条观点现有 `max_view_tilt` 继续保留，但不能替代累计偏离约束。

这样可以防止多条各自合规的观点叠加后共同重写战略底仓。

黄金 TSMOM 在进入 BL 前单独构造一条确定性观点，不再参与非黄金商品桶的分数平均：

```text
P_gold = {gold_asset: 1.0}
tilt_gold = clip(score_gold, -2, 2) × TSMOM_Q_SCALE
Q_gold = P_gold · π + tilt_gold
Ω_gold = 与现有 TSMOM 相同的 confidence → view variance 规则
```

- `score_gold` 仍使用现有 12-1 动量和 60 日波动率，不新增黄金专用回看期或阈值；
- `|score_gold| < 0.25` 时黄金战术观点弃权；
- 非黄金商品桶的 TSMOM 分数、P 腿和归因必须排除黄金，避免同一信号重复进入两条观点；
- 只新增一条 P 行，不修改现有 BL 的 Q/Ω、联合求解、方向纪律或单观点倾斜公式；
- 最终黄金权重仍受 `gold_floor/gold_cap`、商品大类边界、单桶偏离和全组合总偏离共同约束。

这样既能响应 2024-01-01 当时已经存在的黄金强趋势，又不会因为 2024 年事后上涨而永久提高整个商品桶。

这里的第二项是“目标相对战略底仓的理论单边偏离”，不是目标相对漂移后真实持仓的成交换手；字段和前端都不得使用 `turnover` 命名。

### 4.8 约束预检、求解与落库修复

新增 `ConstraintSet` 和 `validate_constraint_set()`，战略投影与最终投影复用同一个约束构造器，禁止复制两套索引逻辑。

调用 CVXPY 前至少完成以下确定性预检：

- 所有 floor/cap 均在 `[0,1]` 且 `floor ≤ cap`；
- 各大类下限合计不超过 1，各大类上限合计不低于 1；
- 每个桶/大类的下限不超过其成员单资产 cap 之和；
- `cn_bond_cap ≤ bond_class_cap`；
- `policy_bucket_targets` 的键与当前 universe 完全一致且加总误差小于 `1e-9`；
- universe 中 `strategic_role=defensive_gold` 必须唯一，且黄金目标、上下限和商品剩余容量可行；
- 基础货币现金资产唯一可识别；
- `cash_hard_floor ≤ cash_policy_target ≤ cash_cap`，风险资本总额严格等于 `1-cash_policy_target`；
- 每个风险资产在 `G` 中恰有一个主风险源，可投资主风险源数量不低于 `min_effective_capital_sources`；
- `macro_factor_balanced` 所需债券均具备完整 DV01/CS01/情景版本，`B/G/V` 维度与资产顺序一致；
- 资产级风险金额上限换算后仍能满足各类下限。

之后先解一个零目标可行性问题，再解正式目标。若加入波动率上限后不可行，错误必须至少返回：

```text
status
target_vol
minimum_feasible_vol（用同约束另解最小方差组合得到）
binding floors/caps
bucket/class capacity
```

不得自动放宽权益下限、债券上限或治理 cap 来换取可行。

当前 `project()` 在求解后执行 `maximum(0)` 再整体除以权重和，这可能把单资产或大类重新推过上限。V4 必须改为：

1. 不做无条件归一化；
2. 对原始解按统一容差验证权重和、非负、单资产、桶、大类和波动率；
3. 仅修复容差内的微小负数和闭合残差；
4. 闭合残差只能分配给仍具有单资产、桶和大类共同剩余空间的资产；减残差只能从不破坏任何下限的资产扣除；候选按资产 ID 排序保证确定性；
5. 修复后再次完整验证；没有合法修复路径就响亮失败；
6. 落库到 6 位小数后再验证一次，不能继续使用“把残差加给最大资产”的无约束规则。

建议把这些步骤封装为：

```text
build_constraint_set(...)
preflight_constraints(...)
solve_projection(...)
repair_and_validate_solution(...)
round_with_constraints(...)
```

求解器状态只接受 `optimal`；`optimal_inaccurate` 只有在全部后验校验通过且误差低于独立严格容差时才允许，否则视为失败。

### 4.9 历史 Demo universe 的 Phase A 可行性快照

在当前 27 资产 universe、2026-07-09 的现有收缩协方差上，对 V4.0 默认政策目标和 Phase A 约束做过只读原型求解，基线结果为：

```text
policy projection status   optimal
equity                     30.00%
bond                       45.00%
commodity                  10.00%
fx                         10.00%
cash                        5.00%
max non-cash asset         10.00%以内
portfolio vol               5.06%
minimum feasible vol        2.91%
target vol 7% / 8% / 15%   均为 optimal
30% 压力协方差混合后       仍为 optimal，组合波动约 5.23%
```

V4.1 新增黄金 3% 政策中枢和 1%—5% 边界后，政策权重的结构容量仍然可行：黄金 3%，其余五项商品各 1.4%，商品合计 10%，均低于单资产上限。但上面的 5.06%/5.23% 数字属于 V4.0 基线，不得冒充当前 V4.2 的数值验证；实现提交必须用 4.2 配置重新生成固定 fixture，并把黄金权重、风险源资本、组合波动和约束利用率写入测试。

该快照只证明结构约束存在可行候选，不代表真实数据、压力协方差或未来资产池一定可行，也不构成收益表现证据。正式实现必须把同类检查写成自动测试，不能依赖此处静态数字。

### 4.10 2024-01-01 时点审计与收益口径

使用提供的 v3 历史导出、严格截断到 2023-12-29，并按 V4.0 price-only 目标（Risk Parity + TSMOM，Clock/ERP 因缺输入弃权）计算：

```text
2024-01-01 事前有效协方差波动率       约 5.04%
2024 年固定目标、月度再平衡累计收益   约 6.27%
按日历天数折算年化收益                约 6.21%
2024 年实现年化波动率                 约 4.07%
```

上述 6.21%/4.07% 是 2024 年事后、样本外观察，不是 2024-01-01 可知的预期收益和预期波动。V4 当前没有经过治理的长期收益预测器，因此决策日不得展示“预期年化收益”；BL 的 `π` 或 `μ_BL` 只用于权重融合，也不得直接包装成客户收益承诺。

该历史导出明确写有“价格未做货币折算”，并混合 ETF、指数、商品/外汇价格和合成现金净值；上述组合收益未计交易成本、税费、期货展期、保证金和人民币汇兑，因此只可作为算法审计近似，不能作为 CNY 实盘业绩。V4.2 实现后必须重新生成同一时点 fixture，并同时报告 V4.0/V4.2 的中国债权重、黄金权重、风险源资本、收益、波动、最大回撤和成本后差异；禁止只展示黄金上涨或债券下降带来的收益改善。

## 5. Phase B：Macro-Factor & Risk-Source Balance

### 5.1 先重建债券“真实风险”，再谈配置

中国债券不能只用 ETF/估值净价的日波动率计风险。对每项债券至少维护 modified duration、关键期限 DV01、信用 CS01、币种、流动性等级和可执行载体。情景损失近似为：

```text
ΔP/P ≈ -D_mod × Δy + 0.5 × Convexity × (Δy)² - CS01 × Δspread + liquidity_loss
```

统计风险使用因子模型，而不是对每个债券价格序列单独算低波动：

```text
r = B f + ε
Σ_stat = B F B' + D_HAC
```

- `B` 包含中国曲线 level/slope、海外曲线、信用利差、权益增长、工业通胀、黄金货币属性和外汇等暴露；
- `F` 是 point-in-time 因子协方差；
- `D_HAC` 使用带自相关修正的残差长期方差，不能让估值平滑把风险压到零；
- 对连续零收益或显著正自相关的债券，普通样本方差只作诊断，不参与生产权重。

把版本化利率、信用和流动性情景损失写成矩阵 `L`，情景概率对角矩阵为 `Π`；`Π` 的非负对角元素严格加总为 1：

```text
Σ_scenario = L' Π L
Σ_method = (1 - ρ_scn) × Σ_stat + ρ_scn × Σ_scenario
```

这里的 `Σ_scenario` 是未中心化的压力损失二阶矩，不是历史收益的样本协方差；保留共同不利冲击是有意设计。该构造天然 PSD，并让“曲线突然上移、变陡、信用走阔、流动性折价”进入风险。不得通过给中国债手填更大波动率来压权重。若缺少 DV01/CS01/曲线历史或无法解释 `L`，`macro_factor_balanced` 必须保持影子失败，不能退回平滑价格协方差后继续生产。

### 5.2 区分多重因子暴露与唯一资本风险源

设 `B ∈ R^(n×k)` 为多重因子暴露，设 `G ∈ {0,1}^(g×n)` 为唯一主风险源映射，每列只允许一个 1。第一版主风险源建议为：

```text
cn_growth              中国权益增长
global_growth          海外权益增长
cn_duration            中国利率曲线
global_duration        海外利率曲线
credit                 信用利差
industrial_inflation   工业品/能源通胀
monetary_gold          黄金货币/危机分散
currency               主动外汇风险
```

`credit_aaa` 可以在 `B` 中同时加载中国 duration 和 credit，但在 `G` 中只能选择一个主要资本风险源。`tbond_fut` 与 `cgb_1_3` 同属 `cn_duration`，增加第二只同类债券不会增加新的资本风险源，也不会自动获得第二份风险预算。

主风险源由版本化 universe 元数据决定，层次聚类只做反证诊断：若经验相关簇长期与元数据严重冲突，触发人工复核；禁止每月根据聚类结果自动改标签，造成结构漂移。

### 5.3 先按风险源构造四个环境 sleeve

建立四个战略环境 sleeve：

| 环境 | 主要受益风险源 | 当前结构性缺口 |
|---|---|---|
| 增长上行 | 中国/海外增长、部分信用和工业品 | 信用与权益风险可能重复 |
| 增长下行 | 中国/海外 duration、现金、有限黄金 | 久期和现金不能视为同一风险 |
| 通胀上行 | 工业品、能源、黄金、通胀挂钩债券 | 当前缺少通胀挂钩债券 |
| 通胀下行 | 中国/海外 duration、部分高质量信用 | 与增长下行 sleeve 重叠 |

设四个 sleeve 组成 `V ∈ R^(n×4)`：

1. 每个环境先选择允许的**主风险源**，再在风险源内部选择资产；不能直接把所有资产平铺后做逆波动率。
2. 同一风险源内部才允许用 `Σ_method` 的压力波动率倒数分配，并叠加流动性/成本排序；多个同类载体共同分享一份 source allocation。
3. 每列 `vⱼ` long-only 且加总为 1；黄金可以进入两个环境，但最终聚合后只算一次资本与风险。
4. 计算 `Σ_sleeve = V' Σ_method V`。
5. 在四维 sleeve 空间复用 risk-budget log-barrier，预算为 `[0.25, 0.25, 0.25, 0.25]`，得到 `a`。
6. 合成未经资本正则的环境解 `w_env = V a`。

```text
RC_envⱼ = aⱼ × (Σ_sleeve a)ⱼ / (a' Σ_sleeve a)
```

必须保存 `B`、`G`、`V`、`Σ_method`、`Σ_sleeve`、`a`、`RC_env` 和 source-level 归因。Phase B 不再把 `w_env` 投影到 `cn_bond=30%` 的政策锚。

四个 sleeve 的任意非同义两列余弦相似度超过 0.98、任一 sleeve 少于两个独立主风险源，或缺少通胀上行保护时，抛 `MacroSleeveCoverageError`。在当前缺少通胀挂钩债券的 universe 中，模型必须明确显示覆盖缺口。

### 5.4 用资本分散软正则选解，不用中国债硬上限造结果

环境等风险解仍可能用大量低波动资本。无杠杆模式下，固定战略现金为 `cash_policy_target`，风险资本为 `1-cash_policy_target`。定义主风险源资本份额：

```text
c = G w / (1 - cash_policy_target)
q = 对当期可投资主风险源等权
N_eff_capital = exp(-Σ c_g ln(c_g))
```

从所有贴近环境解的组合中，选择最接近等风险源资本分布的组合：

```text
min_w  D_KL(c || q) = Σ c_g ln(c_g / q_g)

s.t.
    (w - w_env)' Σ_method (w - w_env) ≤ strategic_tracking_error²
    sqrt(w' Σ_method w) ≤ target_vol
    Σw = 1, w ≥ 0
    cash = cash_policy_target
    治理硬约束
```

这是凸优化：`c` 是 `w` 的仿射映射，KL 项可用 CVXPY `rel_entr`，tracking-error 和波动率约束是凸二次约束。`max_strategic_tracking_error` 建议初始为年化 1.5%，只能通过跨时期稳定性和压力风险治理调整，禁止按历史收益调参。

该步骤不指定中国债目标。三只中国债中的两只 duration 工具共用一个 `cn_duration` 资本份额；若该风险源继续吞噬资本，KL 代价自然上升。只有在保持环境解所必需时，中国债才可以高于等风险源资本先验。

`N_eff_capital` 建议至少为 5。该阈值衡量全局独立资本来源，不是中国债上限；若当前资产池无法达到，应报告 `InsufficientRiskSourceBreadthError`，而不是把同类债券拆成更多 ID 来凑数量。

#### 中国债权重如何在没有目标上限时下降

以当前三只中国债为例，方法链必须产生以下效果：

1. `tbond_fut` 与 `cgb_1_3` 共享中国曲线 level/slope 风险，不能因为有两个资产 ID 获得两份环境预算；`credit_aaa` 的共同久期和额外信用风险通过 `B` 同时体现。
2. 曲线、信用和流动性情景会把估值平滑遗漏的尾部损失补进 `Σ_method`，不再把“近期净值平稳”直接解释为“几乎无风险”。
3. 四环境先在 source-level 分配风险；增长下行和通胀下行虽都可持有久期，但共享同一 `cn_duration` 来源，聚合时不会被重复计为两个独立机会。
4. 在环境风险相近的可行解中，KL 目标会优先把资本转向尚未充分使用的增长、工业通胀、黄金、海外久期和货币来源，而不是继续堆叠中国久期。
5. 最终仍可能得到高于或低于 30% 的中国债权重；合格标准不是某个整数，而是解除集中度上限后结果基本不变、来源资本和压力风险可解释。

因此方法论降低的是中国债获得资本的三个错误理由——低估风险、重复计算来源、忽略资本机会成本；它不会为了得到预设的 30% 而反向调参。

### 5.5 两种实现模式

#### 无杠杆资本平衡

`unlevered_capital_balanced` 直接以上述 `w` 作为资金权重。它接受四环境风险贡献相对 25% 有一定偏差，并同时报告：

- `environment_risk_budget_error`；
- `N_eff_capital`；
- `strategic_tracking_error`；
- `vol_budget_utilization`。

#### 名义风险平衡

`notional_risk_balanced` 在名义敞口 `x` 空间运行第 5.3 节的环境风险平衡，允许 `Σx > 1`，再通过合约乘数、DV01、保证金率和抵押币种转换为：

```text
target_exposure_weight
capital_allocation
initial_and_stress_margin
collateral_cash
gross_exposure
```

该模式更接近 Bridgewater 公开描述的风险平衡，但必须先实现 `gross_exposure_cap`、压力保证金、流动性折扣和去杠杆瀑布。在这些模块上线前，只能影子运行。

### 5.6 证明不是硬约束在替模型做决定

每个决策必须额外运行一次只读 `constraint_release_shadow`：保留 long-only、现金、数据可投资性和波动预算，但解除中国债、总债券和相关单资产集中度上限，重新求解方法组合 `w_release`。

至少落库：

```text
cn_bond_constraint_release_delta = sum_cn_bond(w_release) - sum_cn_bond(w_final)
guardrail_projection_distance = 0.5 × Σ|w_final - w_method|
binding_constraint_count
binding_frequency_rolling_24m
```

初始验收建议：

- 中国债约束释放后权重变化不超过 2pp；
- 风控投影单边距离不超过 5%；
- 任一集中度上限在 24 个月内贴边比例不超过 10%；
- `N_eff_capital ≥ 5`；
- 四环境风险预算最大绝对误差和压力损失不劣于批准阈值。

只要中国债长期等于 30%、约束释放后又跳回约 60%，就必须判定 `methodology_concentration_failure=true`；不得用“最终合规”掩盖方法失败。

### 5.7 当前数据下的上线边界

提供的历史 Excel 只有价格/净值，不包含中国债关键期限 DV01、收益率曲线、信用 CS01、可执行保证金和完整 point-in-time 宏观 surprise。它足以暴露现有方法的问题，但不足以让 `macro_factor_balanced` 成为生产默认。

最低可运行数据契约：

| 数据 | 最低要求 | 主要用途 |
|---|---|---|
| 中国国债曲线 | 1Y/3Y/5Y/7Y/10Y point-in-time 日变化 | level/slope 因子与关键期限冲击 |
| 信用利差 | 与信用债久期匹配的 AAA/政策金融债利差 | CS01 与信用走阔情景 |
| 债券载体 | duration、convexity、key-rate DV01、CS01、成交/估值属性 | 从曲线冲击映射到资产损失 |
| 流动性 | 买卖价差、成交量或版本化保守折价 | liquidity loss 与执行优先级 |
| 海外资产 | 基础币种总回报及对冲状态 | 避免把汇率重复算成独立收益 |
| 期货 | 合约乘数、保证金、展期、抵押币种 | 区分名义风险和资金占用 |

所有字段必须带 `effective_date`、`available_at` 和来源指纹，决策日只能消费当时已发布版本。

在补齐上述数据前：

- `bounded_risk_parity` 只作为受约束的过渡生产路径；
- `macro_factor_balanced` 只做影子权重、来源归因和 constraint-release 诊断；
- 不得用 ETF 平滑波动率替代 DV01 风险，也不得把 Phase A 的中国债 30% 结果称为 Phase B 输出。

## 6. 代码改造地图

建议按以下顺序实施：

1. `backend/app/schemas/config.py`
   - 新增可选 `methodology_v4` 嵌套配置、校验器和稳定序列化入口。
   - 性格画像只能收紧治理上限。
2. `data/demo/assets.json` 与真实 universe schema
   - 增加 `instrument_type`、`currency`、`base_currency_cash`、`strategic_role`、`primary_risk_source`、因子暴露先验、交易日历、数据质量阈值、期货合约乘数和连续合约处理标识。
   - 债券增加 duration、key-rate DV01、CS01、流动性等级、估值/成交价属性和风险数据来源。
   - 黄金载体必须且只能有一个 `strategic_role=defensive_gold`；不得在算法中硬编码 `gold` 资产 ID。
3. `backend/app/domain/market_data.py`
   - 增加真实数据质量报告、收益率曲线/信用利差输入、类型化失败和 v1/v2 双版本输入指纹。
4. `backend/app/domain/fixed_income_risk.py`
   - 新文件，计算 DV01/CS01、HAC 残差方差和版本化情景损失矩阵 `L`。
5. `backend/app/domain/risk_sources.py`
   - 新文件，构造并校验多重因子暴露 `B`、唯一主风险源映射 `G`、资本份额和 `N_eff_capital`。
6. `backend/app/domain/covariance.py`
   - 构造 `B F B' + D_HAC`、情景协方差、recent/stress 组合、eigenvalue floor 和 PSD 检查。
7. `backend/app/domain/guardrails.py`
   - 新增共享 `ConstraintSet`、预检、可行性诊断、解修复和落库精度校验。
   - 增加中国债、总债券、权益、商品、外汇、现金与战术偏离约束。
   - 约束必须同时用于战略底仓投影和最终目标投影。
8. `backend/app/domain/risk_parity.py`
   - 保留 legacy 路径。
   - 新增政策目标构造、黄金子袖展开、可行政策锚和 bounded 路径。
9. `backend/app/domain/macro_balance.py`
   - 构造按独立风险源组织的四环境 `V`，输出 `w_env` 和环境/来源归因。
10. `backend/app/domain/capital_diversification.py`
    - 新文件，使用 `rel_entr` 完成风险源资本最大熵 tracking projection，并生成 constraint-release shadow。
11. `backend/app/domain/signals.py`
   - legacy TSMOM 保持逐字节不变；V4 把黄金分数作为独立子袖输出，并用排除黄金后的成员计算普通商品桶方向。
12. `backend/app/domain/views.py`
   - 从普通商品 TSMOM 观点中排除黄金，使用完全相同的 Q/Ω 规则构造独立黄金 P 行。
13. `backend/app/domain/pipeline.py`
   - `methodology_v4 is None` 走原路径；非空时按嵌套 `strategic_model` 选择新模型。
   - 使用同一配置序列化入口，保持归因闭合；同时保存 method、release shadow 和最终 guardrail 三组权重。
14. `backend/app/schemas/decision.py`
   - 新增战略模型版本、`B/G/V` 版本、债券风险来源、黄金子袖归因、环境贡献、资本有效赌注数、constraint-release 和约束利用率字段。
15. `frontend/src/pages/ConfigPage.tsx`
   - 分开展示风险偏好与治理红线；问卷不能覆盖治理字段。
16. `frontend/src/pages/TracePage.tsx`
    - 展示真实债券风险、风险源资本、环境贡献、方法原始权重、constraint-release、黄金战略/战术贡献、最终风控和 cap 是否真正非绑定。

### 6.1 建议拆成十个可独立回滚的提交

1. **Config compatibility**：只加可选嵌套配置、序列化测试和问卷 cap 修复，不改变默认权重。
2. **Constraint engine**：共享约束构造器、预检、债券/权益/现金边界和精度安全落库；仍由 legacy RP 提供目标。
3. **Data quality report**：先通过独立诊断端点或影子结果报告真实数据质量，不写入 legacy DecisionRecord、不 fail-closed、不改变权重。
4. **Bounded strategic model**：政策锚、标准化目标函数和压力协方差，通过 V4 feature flag 启用。
5. **Gold defensive sleeve**：universe 角色、3% 政策展开、1%—5% 边界、独立 TSMOM P 行和确定性测试；不改 BL 数学。
6. **Fixed-income risk**：DV01/CS01、HAC、曲线/信用/流动性情景和因子协方差，只生成诊断。
7. **Risk-source schema**：`B/G`、唯一主风险源、有效资本来源数量和冲突诊断。
8. **Macro sleeves**：按风险源构造 `V` 和 `w_env`，启用 `macro_factor_balanced` 影子模型。
9. **Capital diversification**：最大熵 tracking projection、constraint-release shadow 和方法失败标记。
10. **Shadow comparison and UI**：并列展示 bounded 与 macro-factor，不切默认。

禁止把上述十项压成一次提交，否则出现权重变化时无法区分是序列化、债券风险、风险源映射、资本正则、约束还是战术观点导致。

引擎行为改变后同步更新：

- `docs/reference/AI资产配置投委会_五方法三层_AgentSKILL_V3.md` 或新建正式 V4；
- `docs/architecture.md`；
- `docs/HANDOFF.md`；
- `docs/CHANGELOG.md`；
- `docs/api_samples/*.json`。

## 7. 必须新增的测试

### 7.1 约束测试

- 非现金资产满足 `single_asset ≤ effective governance cap`。
- 中国债券桶不超过 `cn_bond_cap`。
- 债券大类不超过 `bond_class_cap`。
- 权益大类不低于 `equity_class_floor`。
- 黄金权重位于 `gold_floor/gold_cap`，且黄金与其余商品之和仍满足商品大类边界。
- 现金不低于 `cash_hard_floor`。
- 不可行约束必须抛 `InfeasibleConstraintsError`。
- 性格问卷对单资产上限只能收紧，不能放宽。
- 求解结果经过修复与 6 位落库后仍满足全部约束。
- `optimal_inaccurate` 但后验校验失败时必须拒绝结果。
- 对当前 27 资产 universe，本文默认政策目标和约束必须通过结构预检与 CVXPY 可行性求解。
- 缺失或重复 `strategic_role=defensive_gold`、黄金目标超过商品目标、非黄金商品剩余容量不足时必须预检失败。

### 7.2 数据质量测试

- 连续零价格、连续零收益、缺失、重复列、未来数据、陈旧数据分别有明确失败路径。
- 中国/海外节假日错位不会因静默前值填充制造零波动。
- 期货连续合约换月异常在进入协方差前被识别。
- 美元黄金未转换为基础币种且没有独立 FX/抵押品账本时，不得报告基础币种组合收益。
- 债券缺少 duration/key-rate DV01/CS01 或情景版本时，`macro_factor_balanced` 必须类型化失败，禁止回退到价格低波动率。
- 对带正自相关的平滑债券 fixture，`D_HAC` 风险必须高于未修正样本残差风险。
- `Σ_stat`、`Σ_scenario` 和 `Σ_method` 必须分别对称、PSD 且可复算。
- 压力协方差必须对称、PSD、确定性可复现。
- legacy `fingerprint_v1` 保持固定 fixture 不变；修改历史消费窗口中的任意一个价格值都会改变 V4 `fingerprint_v2`、V4 decision ID 和 V4 缓存键。

### 7.3 战略与归因测试

- `methodology_v4=None` 时默认配置 payload、配置摘要、默认 decision ID、固定 API fixture 和目标权重保持逐字节兼容。
- `methodology_v4` 非空时，其全部字段进入配置摘要，任一字段变化都会改变缓存键/decision ID。
- `bounded_risk_parity` 保存 raw RP、policy anchor、strategic projection 三段且闭合。
- `macro_factor_balanced` 保存 `B/G/V` 版本，四环境贡献可加总回战略权重，每项资产在 `G` 中恰有一个主风险源。
- 增加第二只完全相同的中国国债载体不会增加独立风险源数量，也不会获得一份新的 source allocation。
- 资本最大熵投影满足 tracking-error，且 `N_eff_capital`、KL 值和来源资本份额可复算。
- constraint-release shadow 解除集中度边界后不得改变其他数据、风险模型或战术观点。
- 黄金政策中枢能从商品桶确定性展开；黄金 TSMOM 只生成一条 P 行，普通商品 P 行不再包含黄金。
- 固定截至 2023-12-29 的 point-in-time fixture 应复算 `score_gold≈0.883`，并证明修改任意 2024 年价格不会改变 2024-01-01 决策。
- 战术桶偏离和总偏离均不超过配置。
- 最终 `prior + views + guardrail = target` 继续在 1e-6 内闭合。
- 同一输入跨 direct/cached/API 三条路径得到完全相同结果。

### 7.4 Walk-forward 门禁

不能只看年化收益。至少比较：

- 最大单资产、最大桶、最大大类权重；
- 权益处于下限、债券处于上限的月份比例；
- 事前/事后波动率与波动预算利用率；
- 最大回撤、最差月、压力窗口损失；
- 换手和交易成本；
- 参数微扰后的桶权重 L1 变化；
- 相对旧模型的环境暴露集中度。
- `N_eff_capital`、环境预算误差、方法权重到风控权重的投影距离；
- 中国债约束释放变化、上限贴边频率，以及 `methodology_concentration_failure` 次数；
- 黄金战略/战术权重、黄金对组合风险和压力窗口损失的边际贡献；不得只比较加入黄金后的历史收益。

新模型只有在集中度显著改善、压力风险没有恶化、换手可控且确定性测试通过后，才允许成为默认值。历史收益更高不是必要条件，也不是充分条件。

### 7.5 建议测试文件

```text
tests/backend/test_v4_config_compat.py
tests/backend/test_v4_constraint_feasibility.py
tests/backend/test_v4_solution_rounding.py
tests/backend/test_data_quality_real_inputs.py
tests/backend/test_stress_covariance.py
tests/backend/test_bounded_risk_parity.py
tests/backend/test_gold_defensive_sleeve.py
tests/backend/test_fixed_income_factor_risk.py
tests/backend/test_risk_source_mapping.py
tests/backend/test_macro_factor_balance.py
tests/backend/test_capital_diversification.py
tests/backend/test_constraint_release_shadow.py
tests/backend/test_v4_walk_forward.py
```

### 7.6 每个提交的验证命令

```bash
# 快速定向测试
cd backend
pytest -q ../tests/backend/test_v4_config_compat.py \
  ../tests/backend/test_v4_constraint_feasibility.py \
  ../tests/backend/test_v4_solution_rounding.py

# 后端完整回归
cd ..
make test

# 前端类型与构建；只有修改前端时必跑
make build

# 修改交互或展示后必跑
make e2e

# 补丁卫生
git diff --check
git status --short
```

实现新测试文件之前，命令中不存在的文件应从定向列表暂时移除；完整 `make test` 始终必须通过。

## 8. 迁移与回滚

### 8.1 发布顺序

1. 合并配置兼容层，确认 `methodology_v4=None` 的历史摘要和 fixture 完全不变。
2. 先发布独立数据质量报告，不改变权重、不写 legacy DecisionRecord、不 fail-closed。
3. 发布共享约束引擎；legacy 默认路径仍使用原配置，V4 路径才启用新增边界。
4. 启用 `bounded_risk_parity` 影子计算；影子失败不得影响主决策，只记录类型化错误。
5. 完成 walk-forward 与至少一个完整再平衡周期的真实数据并行观察后，由人工审批切换默认配置为非空 V4。
6. 补齐 DV01/CS01、风险源元数据和情景风险后，上线 `macro_factor_balanced` 影子模型；不得与 bounded 同时切默认。
7. constraint-release 指标和来源归因连续通过后，才允许人工审批把 `strategic_model` 从 bounded 切到 macro-factor。

影子结果必须使用独立 `decision_id`/缓存命名空间，不得覆盖 legacy DecisionRecord，也不得进入实际日更、周报、结果账本或调仓提示。

### 8.2 回滚条件

出现以下任一情况立即把 `methodology_v4` 设回 `None`：

- 约束集频繁不可行；
- 数据质量门禁造成核心资产大面积不可用且无明确原因；
- 权重闭合或归因闭合失败；
- 同输入无法产生相同结果；
- 实际换手显著超过配置；
- 压力窗口损失显著恶化。
- `N_eff_capital` 持续低于门槛、集中度边界频繁贴边，或 constraint-release 证明结果主要由 cap 生成。

旧 DecisionRecord 永远按其记录的模型版本重放，不使用当前默认模型重算。

### 8.3 切换默认值前的书面确认

负责人必须确认：

- 投资授权接受本文政策区间；
- 对权益下限和债券上限造成的风险变化知情；
- 真实数据质量报告连续通过；
- 影子模型没有不可解释的边界常驻；
- 中国债、总债券和单资产 cap 的 release delta 与贴边频率通过第 5.6 节门禁；
- DV01/CS01、`B/G/V`、情景矩阵和资本有效来源数量能够在 Trace 页面复算；
- 压力协方差、政策锚和硬约束的归因能够在 Trace 页面复算；
- 回滚只需把 `methodology_v4` 设回 `None`，不需要迁移或删除历史记录。

## 9. 给实现 Agent 的执行指令

按以下顺序工作，不要一次性实现全部 V4：

1. 先提交 Phase A 的配置契约、硬约束和测试。
2. 不改 Black-Litterman 的 Q/Ω、联合求解和归因数学；黄金只按第 4.7 节增加一条确定性 P 行，并从普通商品 P 行排除。
3. 不删除 legacy Risk Parity；所有新行为置于 feature flag 后。
4. 性格问卷不得再提高单资产治理上限。
5. 所有新约束必须同时进入战略投影和最终投影。
6. 新增数据质量诊断时先只报告，再单独提交 fail-closed 行为。
7. 不得保留求解后的无条件归一化或无约束最大余数修复。
8. 每个提交都运行后端测试、API 测试和适用的 walk-forward 稳定性比较。
9. 若投资授权参数不明确，只允许在显式 V4 Demo/影子配置中使用本文候选值；生产默认仍保持 legacy，参数不得表述为普适最优值。
10. 不得把 Phase A 的政策锚传入 `macro_factor_balanced`；Phase B 的中国债资本权重只能来自真实风险、环境 sleeve 和资本分散步骤。
11. 若真实 DV01/CS01 和曲线历史尚未接入，停止在 Phase B 影子失败状态，不得用价格协方差补洞。

Phase A 最小完成定义：

```text
非现金单资产 ≤ 10%
中国债券 ≤ 40%
债券大类 ≤ 60%
权益大类 ≥ 20%
现金 ≥ 5%
黄金战略/最终权重位于 1%—5%，且商品大类总权重仍满足 5%—20%
问卷不能放宽上述治理红线
战术单桶相对战略底仓偏离 ≤ 5pp
目标相对战略底仓的理论单边偏离 ≤ 15%
methodology_v4=None 时历史默认 payload/ID/权重不变
求解、修复、6 位落库后三次约束校验均通过
全部闭合、确定性、不可行约束和回测测试通过
```

Phase B 方法完成定义：

```text
债券风险由 B F B' + D_HAC 与版本化情景协方差共同生成
每项资产具有多重因子暴露 B 和唯一主风险源 G
同类中国债载体不会增加独立风险源数量
四环境 sleeve 在风险源层构造并保存可复算贡献
资本最大熵投影满足 strategic tracking-error 和 N_eff_capital ≥ 5
macro_factor_balanced 不读取 cn_bond=30% 政策锚
constraint-release 后中国债变化 ≤ 2pp
风控投影单边距离 ≤ 5%，集中度边界 24 月贴边频率 ≤ 10%
未满足上述条件时 methodology_concentration_failure=true，禁止切默认
```

## 10. 交付前检查表

交付这份规格或后续实现补丁前逐项确认：

- [ ] `methodology_v4=None` 是唯一且可测试的 legacy 路径。
- [ ] 所有 V4 默认值都在嵌套对象内，没有污染旧配置 payload。
- [ ] 政策桶目标加总为 1，并能在当前 universe 下投影为可行资产权重。
- [ ] `macro_factor_balanced` 不读取 fallback policy 的中国债 30% 中枢。
- [ ] 债券 DV01/CS01、HAC 修正和曲线/信用/流动性情景均有版本与输入血缘。
- [ ] `B/G/V` 可复算，同类债券不会因为资产 ID 数量增加而取得更多风险预算。
- [ ] `N_eff_capital`、环境预算误差、tracking-error 和 KL 目标均进入 DecisionRecord。
- [ ] constraint-release shadow 证明中国债结果不是由 cap 生成。
- [ ] 黄金角色唯一，3% 政策中枢从商品桶内扣除，普通商品剩余目标仍可行。
- [ ] 共享约束构造器同时服务战略和最终投影。
- [ ] V4 不会通过问卷、个性画像或风险金额配置放宽治理上限。
- [ ] 协方差矩阵经过真实 PSD 检查，而不是只用 `psd_wrap` 声明。
- [ ] 求解后没有无条件归一化；落库舍入不会造成二次越界。
- [ ] `max_total_tactical_deviation` 没有被错误表述为实际成交换手。
- [ ] 黄金 TSMOM 与普通商品 TSMOM 没有重复使用黄金分数，2024 年事后价格没有进入 2024-01-01 fixture。
- [ ] 期货的名义敞口、资金占用和 DV01 没有混用。
- [ ] 影子模型失败不会阻断 legacy 主决策或污染结果账本。
- [ ] Phase B 使用 `V'ΣV` 的四 sleeve 可复算方法，不靠人工合并重叠资产。
- [ ] 文档、固定 API 样例、CHANGELOG 和测试名同步更新。
