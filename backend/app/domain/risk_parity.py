"""Risk Parity 战略底仓（唯一战略层方法）。

结构（诚实声明：Roncalli 风险预算式定制，非教科书单层 ERC）：
1. 桶间：对 6 个风险桶的桶级协方差求风险预算组合——四个风险大类
   （权益/债券/商品/外汇）各承担 25% 风险贡献（V3 第三节“让四类风险
   贡献相等”），大类内两个桶各分一半预算。解通过凸的 log-barrier 等价
   形式求出：min ½ y'Σy − Σ bᵢ·ln(yᵢ)（Maillard-Roncalli-Teïletche 2010
   的预算推广），归一后风险贡献占比即等于预算 bᵢ。
2. 桶内：按波动率倒数分配到明细资产，单资产不超过桶内 50%（防止
   超低波动资产吸走整桶权重），超出部分按比例回灌。
现金桶取配置的战略现金底仓 cash_floor，风险桶合计 1 - cash_floor。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from . import universe
from .covariance import TRADING_DAYS, log_returns

# 风险预算：四大类各 25%，类内两桶均分
RISK_BUDGETS = {
    "cn_equity": 0.125, "foreign_equity": 0.125,
    "cn_bond": 0.125, "foreign_bond": 0.125,
    "commodity": 0.25, "fx": 0.25,
}
INTRA_BUCKET_CAP = 0.50


def _risk_budget_weights(sigma: np.ndarray, budgets: np.ndarray) -> np.ndarray:
    n = sigma.shape[0]

    def objective(log_y: np.ndarray) -> float:
        y = np.exp(log_y)
        return 0.5 * float(y @ sigma @ y) - float(budgets @ log_y)

    res = minimize(objective, x0=np.zeros(n), method="L-BFGS-B")
    y = np.exp(res.x)
    return y / y.sum()


def bucket_returns(prices: pd.DataFrame, window_days: int) -> pd.DataFrame:
    """桶级日收益：桶内资产等权组合的对数收益。"""
    rets = log_returns(prices, window_days)
    out = {}
    for b in universe.bucket_ids():
        if b == "cash":
            continue
        cols = [a for a in universe.assets_in_bucket(b) if a in rets.columns]
        out[b] = rets[cols].mean(axis=1)
    return pd.DataFrame(out)


def _capped_inverse_vol(vols: dict[str, float], cap: float) -> dict[str, float]:
    inv = {a: 1.0 / max(v, 1e-6) for a, v in vols.items()}
    total = sum(inv.values())
    w = {a: v / total for a, v in inv.items()}
    for _ in range(4):
        over = {a: v for a, v in w.items() if v > cap + 1e-12}
        if not over:
            break
        excess = sum(v - cap for v in over.values())
        under_total = sum(v for a, v in w.items() if a not in over)
        w = {a: cap if a in over else v + excess * v / under_total for a, v in w.items()}
    return w


def strategic_weights(prices: pd.DataFrame, window_days: int, cash_floor: float,
                      sigma_assets: np.ndarray | None = None,
                      asset_order: list[str] | None = None,
                      config=None) -> tuple[dict[str, float], dict]:
    """返回 (27 明细资产战略权重, 推导细节)。

    末步做约束式投影（single_asset_cap 等），保证战略底仓本身可投资：
    否则超低波动资产（如 1-3 年国债）会吸走远超单资产上限的权重，
    迫使风控层每次决策都对底仓做大手术，战术观点反而失焦。
    """
    brets = bucket_returns(prices, window_days)
    bucket_order = list(brets.columns)
    sigma_b = np.cov(brets.to_numpy(), rowvar=False, ddof=1) * TRADING_DAYS
    budgets = np.array([RISK_BUDGETS[b] for b in bucket_order])
    rb = _risk_budget_weights(sigma_b, budgets)
    risky_total = 1.0 - cash_floor
    bucket_w = {b: float(w) * risky_total for b, w in zip(bucket_order, rb)}
    bucket_w["cash"] = cash_floor

    rets = log_returns(prices, window_days)
    weights: dict[str, float] = {"cash": cash_floor}
    intra_raw: dict[str, dict[str, float]] = {}
    for b in bucket_order:
        cols = universe.assets_in_bucket(b)
        vols = {a: float(rets[a].std(ddof=1)) for a in cols}
        intra_raw[b] = _capped_inverse_vol(vols, INTRA_BUCKET_CAP)
        for a in cols:
            weights[a] = bucket_w[b] * intra_raw[b][a]

    constrained = False
    if sigma_assets is not None and asset_order is not None and config is not None:
        from .guardrails import project
        w_vec = np.array([weights[a] for a in asset_order])
        w_proj = project(w_vec, sigma_assets, asset_order, config, vol_cap=False)
        if np.abs(w_proj - w_vec).max() > 1e-6:
            constrained = True
        weights = {a: float(w) for a, w in zip(asset_order, w_proj)}
        bucket_w = universe.aggregate_to_buckets(weights)

    # 桶内份额（观点 P 腿使用与底仓一致的份额）
    intra: dict[str, dict[str, float]] = {}
    for b in bucket_order:
        cols = universe.assets_in_bucket(b)
        bsum = sum(weights[a] for a in cols)
        intra[b] = {a: (weights[a] / bsum if bsum > 1e-12 else 1.0 / len(cols))
                    for a in cols}

    contrib = sigma_b @ rb * rb
    total_var = float(rb @ sigma_b @ rb)
    detail = {
        "bucket_weights": {k: round(v, 6) for k, v in bucket_w.items()},
        "risk_budgets": RISK_BUDGETS,
        "bucket_risk_contrib": {b: round(float(c) / total_var, 4)
                                for b, c in zip(bucket_order, contrib)},
        "intra_bucket_inverse_vol": {b: {a: round(w, 4) for a, w in m.items()}
                                     for b, m in intra.items()},
        "constrained": constrained,
        "method": "四大类等风险贡献(风险预算ERC) + 桶内逆波动率(单资产≤桶内50%) + 约束式投影；现金=战略底仓参数",
    }
    return weights, detail
