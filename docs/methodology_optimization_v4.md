# 资产配置方法论优化方案 V4（实施规格）

> 状态：Proposal，尚未替代 V3 权威规格。  
> 目标读者：负责修改战略底仓、风控投影、配置契约和回测门禁的工程 Agent。  
> 核心目标：解决低波动中国债券吸收过多资本、权益资本权重长期过低、问卷可放宽治理上限，以及真实数据接入后协方差被平滑行情放大的问题。

## 1. 先给结论

当前实现是“资产类别风险预算 ERC + 桶内逆波动率”，不是严格意义上的宏观环境平衡。低波动中国债券为了取得与股票相近的风险贡献，会自然获得很高的资本权重；当前约束又只有债券下限、没有债券上限和权益下限，因此该偏置可以一直放大。

本次优化分两阶段：

1. **Phase A：Bounded Risk Parity**。保持现有 Risk Parity 和 Black-Litterman 主链，补齐治理约束、政策权重区间、压力协方差和战术偏离上限。该阶段优先落地。
2. **Phase B：Macro-Balanced Strategic Allocation**。把“股票/债券/商品/外汇各分风险”改为“增长上行/增长下行/通胀上行/通胀下行四类环境分风险”。该阶段通过 feature flag 并行回测，不直接覆盖旧模型。

不应只修改 `RISK_BUDGETS`。单纯提高权益风险预算仍可能得到很低的权益资本权重，也无法解决债券行情平滑、期货权重语义和治理上限被问卷覆盖的问题。

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

本方案只能称为 **All Weather-inspired macro balance**。

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

## 4. Phase A：Bounded Risk Parity

### 4.1 推荐的初始政策区间

以下参数只作为“无杠杆、平衡型多资产账户”的起始候选，必须允许投资授权覆盖：

| 维度 | 中枢 | 下限 | 上限 |
|---|---:|---:|---:|
| 权益大类 | 30% | 20% | 45% |
| 债券大类 | 45% | 30% | 60% |
| 商品大类 | 10% | 5% | 20% |
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

`policy_bucket_targets` 必须完整覆盖当前 universe 的展示桶并严格加总为 1。V4 第一版固定按桶内等权展开，不开放资产级政策覆盖，避免又引入一套未经治理的权重入口。展开结果必须经过同一套硬约束投影，得到真正可行的 `w_policy`。不得因为某桶资产数量不足而临时提高单资产上限。

说明：

- “外汇风险”不是外币现金余额，也不应机械获得 25% 风险预算；货币配置与资产 Beta 应分开记录。
- 若账户明确是固收增强型，应通过一套命名场景覆盖上述区间，而不是让问卷临时放宽集中度红线。
- 三只中国债券在 10% 单资产上限下最多合计 30%；如果希望桶上限为 40%，应增加真正不同风险来源的债券工具，而不是放宽单券上限。
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
    method_version: Literal["4.0.0"] = "4.0.0"
    strategic_model: Literal["bounded_risk_parity", "macro_balanced"] = \
        "bounded_risk_parity"
    governance_single_asset_cap: float = Field(default=0.10, gt=0, le=1)
    cn_bond_cap: float = Field(default=0.40, gt=0, le=1)
    bond_class_floor: float = Field(default=0.30, ge=0, le=1)
    bond_class_cap: float = Field(default=0.60, gt=0, le=1)
    equity_class_floor: float = Field(default=0.20, ge=0, le=1)
    equity_class_cap: float = Field(default=0.45, gt=0, le=1)
    commodity_floor: float = Field(default=0.05, ge=0, le=1)
    commodity_cap: float = Field(default=0.20, gt=0, le=1)
    fx_floor: float = Field(default=0.00, ge=0, le=1)
    fx_cap: float = Field(default=0.15, gt=0, le=1)
    cash_hard_floor: float = Field(default=0.05, ge=0, le=1)
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

`MethodologyV4Config` 必须使用 `model_validator(mode="after")` 校验各组 floor/cap、政策目标加总和基础字段关系；不要只依赖 CVXPY 才发现显然错误的配置。

兼容纪律：

- `methodology_v4 is None` 是唯一 legacy 开关；此时不得执行任何 V4 逻辑。
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

所有门禁结果进入 DecisionRecord 的输入血缘或独立 `data_quality` 区块。

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

这里的第二项是“目标相对战略底仓的理论单边偏离”，不是目标相对漂移后真实持仓的成交换手；字段和前端都不得使用 `turnover` 命名。

### 4.8 约束预检、求解与落库修复

新增 `ConstraintSet` 和 `validate_constraint_set()`，战略投影与最终投影复用同一个约束构造器，禁止复制两套索引逻辑。

调用 CVXPY 前至少完成以下确定性预检：

- 所有 floor/cap 均在 `[0,1]` 且 `floor ≤ cap`；
- 各大类下限合计不超过 1，各大类上限合计不低于 1；
- 每个桶/大类的下限不超过其成员单资产 cap 之和；
- `cn_bond_cap ≤ bond_class_cap`；
- `policy_bucket_targets` 的键与当前 universe 完全一致且加总误差小于 `1e-9`；
- 基础货币现金资产唯一可识别；
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

### 4.9 当前 Demo universe 的可行性快照

在当前 27 资产 universe、2026-07-09 的现有收缩协方差上，对本文默认政策目标和 Phase A 约束做只读原型求解，结果为：

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

该快照只证明当前 Demo universe 的结构约束可行，不代表真实数据、压力协方差或未来资产池一定可行，也不构成收益表现证据。正式实现必须把同类检查写成自动测试，不能依赖此处静态数字。

## 5. Phase B：宏观环境平衡

### 5.1 从资产桶风险预算改为环境组合风险预算

建立四个战略环境 sleeve：

| 环境 | 主要受益资产 | 当前资产池的结构性缺口 |
|---|---|---|
| 增长上行 | 中国/海外权益、部分商品、信用 | 信用与权益风险可能重复 |
| 增长下行 | 高质量名义国债、现金 | 久期和现金不能视为同一风险 |
| 通胀上行 | 商品、黄金、通胀挂钩债券 | 当前缺少通胀挂钩债券 |
| 通胀下行 | 名义国债、部分高质量信用 | 与增长下行 sleeve 重叠 |

关键纪律：

- 资产可以服务多个环境，但重复暴露必须显式计算，不能按桶名去重。
- 外汇不再作为固定 25% 风险类别；货币风险单独决定是否对冲。
- 在缺少通胀挂钩债券时，系统必须显示“通胀上行保护不完整”，不能声称实现完整 All Weather。

### 5.2 推荐的可实现版本

第一版不直接拟合复杂非线性宏观因子模型，采用确定性 sleeve 矩阵。设资产数为 `n`，四个环境 sleeve 组成 `V ∈ R^(n×4)`：

1. 为每个环境维护版本化的允许资产集合和经济方向。
2. 每个 sleeve 内用压力波动率倒数分配，并应用单资产和重复风险来源上限。
3. 每列 `vⱼ` 必须 long-only 且加总为 1；四列按固定顺序排列。
4. 计算 sleeve 协方差 `Σ_sleeve = V' Σ_effective V`。
5. 在四维 sleeve 空间复用现有 risk-budget log-barrier，预算固定为 `[0.25, 0.25, 0.25, 0.25]`，得到 `a`，且 `Σa=1`。
6. 合成环境平衡资产权重 `w_env = V a`；即使同一资产出现在多个 sleeve，贡献也通过矩阵乘法自然相加，不做人工去重。
7. 把 `w_env` 作为 Phase A 优化中的风险平衡候选，替代 `w_rp_raw`，再投影到政策资本区间。

环境风险贡献按以下公式落库：

```text
RC_envⱼ = aⱼ × (Σ_sleeve a)ⱼ / (a' Σ_sleeve a)
```

必须保存 `V` 的版本、每列资产权重、`Σ_sleeve`、`a`、`RC_env` 和最终战略投影差异。这样四环境贡献能被独立复算，而不是只有一段叙事标签。

四个 sleeve 可能因资产池不足而高度相似，使 `Σ_sleeve` 近奇异。实现必须：

- 报告每两列 sleeve 的余弦相似度；任意非同义环境超过 0.98 时抛 `MacroSleeveCoverageError`；
- 每个 sleeve 至少包含两个可投资风险来源；
- 用 `κ = 1e-6 × max(trace(Σ_sleeve) / 4, 1e-12)` 做固定对角正则，并记录正则前后的最小特征值；
- 当前缺少通胀挂钩债券时，`macro_balanced` 只能运行影子诊断，不能切为生产默认。

Phase B v1 不允许 FX 资产直接进入四个 sleeve，因为货币对方向、基础币种和资产币种对冲是另一套问题。FX 只通过政策锚保留有限资本区间；后续若加入货币 overlay，必须使用独立账本和 gross/net exposure 约束。

后续只有在宏观 surprise 数据具备 point-in-time 历史后，才允许升级为估计型暴露矩阵 `B`。估计暴露必须向预设经济方向收缩，禁止完全由短窗回归决定符号。

### 5.3 杠杆处理

Bridgewater 风格的风险平衡通常通过衍生品提高低波动 sleeve 的风险贡献。本项目当前是无杠杆资金权重模型，因此：

- V4 第一版不自动加杠杆；
- `target_vol` 继续作为上限，不得伪装成已达到的目标；
- 必须展示 `vol_budget_utilization = portfolio_vol / target_vol`；
- 若未来支持杠杆，新增独立 `gross_exposure_cap`、保证金压力和去杠杆测试；
- 在杠杆模块上线前，政策资本区间是防止债券资本权重失控的必要组成。

## 6. 代码改造地图

建议按以下顺序实施：

1. `backend/app/schemas/config.py`
   - 新增可选 `methodology_v4` 嵌套配置、校验器和稳定序列化入口。
   - 性格画像只能收紧治理上限。
2. `data/demo/assets.json` 与真实 universe schema
   - 增加 `instrument_type`、`currency`、`base_currency_cash`、交易日历、数据质量阈值、期货合约乘数和连续合约处理标识。
3. `backend/app/domain/market_data.py`
   - 增加真实数据质量报告、类型化失败和 v1/v2 双版本输入指纹。
4. `backend/app/domain/covariance.py`
   - 新增 recent/stress 协方差组合、eigenvalue floor 和 PSD 检查。
5. `backend/app/domain/guardrails.py`
   - 新增共享 `ConstraintSet`、预检、可行性诊断、解修复和落库精度校验。
   - 增加中国债、总债券、权益、商品、外汇、现金与战术偏离约束。
   - 约束必须同时用于战略底仓投影和最终目标投影。
6. `backend/app/domain/risk_parity.py`
   - 保留 legacy 路径。
   - 新增政策目标构造、可行政策锚和 bounded 路径。
7. `backend/app/domain/macro_balance.py`
   - 新文件，承载版本化四环境 sleeve 矩阵；不得塞入 `signals.py`。
8. `backend/app/domain/pipeline.py`
   - `methodology_v4 is None` 走原路径；非空时按嵌套 `strategic_model` 选择新模型。
   - 使用同一配置序列化入口，保持归因闭合。
9. `backend/app/schemas/decision.py`
   - 新增战略模型版本、数据质量、环境贡献和约束利用率字段。
10. `frontend/src/pages/ConfigPage.tsx`
   - 分开展示风险偏好与治理红线；问卷不能覆盖治理字段。
11. `frontend/src/pages/TracePage.tsx`
    - 展示原始 RP、政策锚、环境贡献、战略投影、战术偏离和最终风控。

### 6.1 建议拆成六个可独立回滚的提交

1. **Config compatibility**：只加可选嵌套配置、序列化测试和问卷 cap 修复，不改变默认权重。
2. **Constraint engine**：共享约束构造器、预检、债券/权益/现金边界和精度安全落库；仍由 legacy RP 提供目标。
3. **Data quality report**：先通过独立诊断端点或影子结果报告真实数据质量，不写入 legacy DecisionRecord、不 fail-closed、不改变权重。
4. **Bounded strategic model**：政策锚、标准化目标函数和压力协方差，通过 V4 feature flag 启用。
5. **Shadow comparison**：API/前端并列展示 legacy 与 bounded，不切默认。
6. **Macro sleeves**：最后增加 `macro_balanced` 影子模型。

禁止把上述六项压成一次提交，否则出现权重变化时无法区分是序列化、约束、协方差还是战略模型导致。

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
- 现金不低于 `cash_hard_floor`。
- 不可行约束必须抛 `InfeasibleConstraintsError`。
- 性格问卷对单资产上限只能收紧，不能放宽。
- 求解结果经过修复与 6 位落库后仍满足全部约束。
- `optimal_inaccurate` 但后验校验失败时必须拒绝结果。
- 对当前 27 资产 universe，本文默认政策目标和约束必须通过结构预检与 CVXPY 可行性求解。

### 7.2 数据质量测试

- 连续零价格、连续零收益、缺失、重复列、未来数据、陈旧数据分别有明确失败路径。
- 中国/海外节假日错位不会因静默前值填充制造零波动。
- 期货连续合约换月异常在进入协方差前被识别。
- 压力协方差必须对称、PSD、确定性可复现。
- legacy `fingerprint_v1` 保持固定 fixture 不变；修改历史消费窗口中的任意一个价格值都会改变 V4 `fingerprint_v2`、V4 decision ID 和 V4 缓存键。

### 7.3 战略与归因测试

- `methodology_v4=None` 时默认配置 payload、配置摘要、默认 decision ID、固定 API fixture 和目标权重保持逐字节兼容。
- `methodology_v4` 非空时，其全部字段进入配置摘要，任一字段变化都会改变缓存键/decision ID。
- `bounded_risk_parity` 保存 raw RP、policy anchor、strategic projection 三段且闭合。
- `macro_balanced` 四环境贡献可加总回战略权重。
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

新模型只有在集中度显著改善、压力风险没有恶化、换手可控且确定性测试通过后，才允许成为默认值。历史收益更高不是必要条件，也不是充分条件。

### 7.5 建议测试文件

```text
tests/backend/test_v4_config_compat.py
tests/backend/test_v4_constraint_feasibility.py
tests/backend/test_v4_solution_rounding.py
tests/backend/test_data_quality_real_inputs.py
tests/backend/test_stress_covariance.py
tests/backend/test_bounded_risk_parity.py
tests/backend/test_macro_balance.py
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
6. 最后上线 `macro_balanced` 影子模型；不得与 bounded 同时切默认。

影子结果必须使用独立 `decision_id`/缓存命名空间，不得覆盖 legacy DecisionRecord，也不得进入实际日更、周报、结果账本或调仓提示。

### 8.2 回滚条件

出现以下任一情况立即把 `methodology_v4` 设回 `None`：

- 约束集频繁不可行；
- 数据质量门禁造成核心资产大面积不可用且无明确原因；
- 权重闭合或归因闭合失败；
- 同输入无法产生相同结果；
- 实际换手显著超过配置；
- 压力窗口损失显著恶化。

旧 DecisionRecord 永远按其记录的模型版本重放，不使用当前默认模型重算。

### 8.3 切换默认值前的书面确认

负责人必须确认：

- 投资授权接受本文政策区间；
- 对权益下限和债券上限造成的风险变化知情；
- 真实数据质量报告连续通过；
- 影子模型没有不可解释的边界常驻；
- 压力协方差、政策锚和硬约束的归因能够在 Trace 页面复算；
- 回滚只需把 `methodology_v4` 设回 `None`，不需要迁移或删除历史记录。

## 9. 给实现 Agent 的执行指令

按以下顺序工作，不要一次性实现全部 V4：

1. 先提交 Phase A 的配置契约、硬约束和测试。
2. 不改 Black-Litterman 的 P/Q/Ω 和归因逻辑。
3. 不删除 legacy Risk Parity；所有新行为置于 feature flag 后。
4. 性格问卷不得再提高单资产治理上限。
5. 所有新约束必须同时进入战略投影和最终投影。
6. 新增数据质量诊断时先只报告，再单独提交 fail-closed 行为。
7. 不得保留求解后的无条件归一化或无约束最大余数修复。
8. 每个提交都运行后端测试、API 测试和适用的 walk-forward 稳定性比较。
9. 若投资授权参数不明确，只允许在显式 V4 Demo/影子配置中使用本文候选值；生产默认仍保持 legacy，参数不得表述为普适最优值。

Phase A 最小完成定义：

```text
非现金单资产 ≤ 10%
中国债券 ≤ 40%
债券大类 ≤ 60%
权益大类 ≥ 20%
现金 ≥ 5%
问卷不能放宽上述治理红线
战术单桶相对战略底仓偏离 ≤ 5pp
目标相对战略底仓的理论单边偏离 ≤ 15%
methodology_v4=None 时历史默认 payload/ID/权重不变
求解、修复、6 位落库后三次约束校验均通过
全部闭合、确定性、不可行约束和回测测试通过
```

## 10. 交付前检查表

交付这份规格或后续实现补丁前逐项确认：

- [ ] `methodology_v4=None` 是唯一且可测试的 legacy 路径。
- [ ] 所有 V4 默认值都在嵌套对象内，没有污染旧配置 payload。
- [ ] 政策桶目标加总为 1，并能在当前 universe 下投影为可行资产权重。
- [ ] 共享约束构造器同时服务战略和最终投影。
- [ ] V4 不会通过问卷、个性画像或风险金额配置放宽治理上限。
- [ ] 协方差矩阵经过真实 PSD 检查，而不是只用 `psd_wrap` 声明。
- [ ] 求解后没有无条件归一化；落库舍入不会造成二次越界。
- [ ] `max_total_tactical_deviation` 没有被错误表述为实际成交换手。
- [ ] 期货的名义敞口、资金占用和 DV01 没有混用。
- [ ] 影子模型失败不会阻断 legacy 主决策或污染结果账本。
- [ ] Phase B 使用 `V'ΣV` 的四 sleeve 可复算方法，不靠人工合并重叠资产。
- [ ] 文档、固定 API 样例、CHANGELOG 和测试名同步更新。
