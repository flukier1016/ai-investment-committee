"""收益协方差估计：对数收益 → 线性收缩（向对角阵）→ 年化。

收缩是 Ledoit-Wolf (2004) 的简化确定性版本：
Σ_shrunk = (1-s)·S + s·diag(S)，s 由配置给定（默认 0.20），
保证正定、可复现，不引入额外拟合自由度。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

TRADING_DAYS = 252


def log_returns(prices: pd.DataFrame, window_days: int) -> pd.DataFrame:
    px = prices.iloc[-(window_days + 1):]
    return np.log(px / px.shift(1)).dropna()


def shrunk_covariance(prices: pd.DataFrame, asset_order: list[str],
                      window_days: int, shrinkage: float) -> np.ndarray:
    rets = log_returns(prices[asset_order], window_days)
    sample = np.cov(rets.to_numpy(), rowvar=False, ddof=1) * TRADING_DAYS
    diag = np.diag(np.diag(sample))
    sigma = (1 - shrinkage) * sample + shrinkage * diag
    # 现金列波动极小，加下限保证数值稳定
    floor = 1e-8
    np.fill_diagonal(sigma, np.maximum(np.diag(sigma), floor))
    return sigma


def annualized_vol(prices: pd.DataFrame, asset_order: list[str],
                   window_days: int) -> dict[str, float]:
    rets = log_returns(prices[asset_order], window_days)
    return {a: float(rets[a].std(ddof=1) * np.sqrt(TRADING_DAYS)) for a in asset_order}
