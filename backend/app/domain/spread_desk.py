"""利差台（相对价值研究叠加模块）：与核心配置账本完全分离。

从同一 Demo 价格面板确定性计算五个 RV 策略的 z-score、状态与叠加账本；
默认不改变核心配置权重（研究叠加，独立记账）。
开平仓阈值：|z|≥1.5 开仓、|z|≤0.5 平仓，腿按波动率倒数配平。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .market_data import _prices

Z_OPEN, Z_CLOSE = 1.5, 0.5
Z_WINDOW = 252
COST_PER_SIDE = 1e-3  # 10bp

STRATEGIES = [
    {"id": "s1_gold_silver", "name": "金银比价回归", "long": "gold", "short": "silver",
     "note": "贵金属内部相对价值：金银对数比价的 1 年 z-score"},
    {"id": "s2_wti_brent", "name": "WTI-布伦特价差", "long": "wti", "short": "brent",
     "note": "同一能源链两端的价差回归"},
    {"id": "s3_csi_style", "name": "A股大小盘风格", "long": "csi300", "short": "csi500",
     "note": "沪深300 / 中证500 风格轮动比价"},
    {"id": "s4_cn_us_10y", "name": "中美10Y期货收敛", "long": "cgb10y_fut", "short": "us10y_zn",
     "note": "中美利率期货比价（利差代理）"},
    {"id": "s5_metal_ferrous", "name": "有色-黑色比价", "long": "copper", "short": "rebar",
     "note": "工业金属对黑色系的相对强弱"},
]


def _zscore(ratio: pd.Series) -> pd.Series:
    log_ratio = np.log(ratio)
    mean = log_ratio.rolling(Z_WINDOW).mean()
    std = log_ratio.rolling(Z_WINDOW).std(ddof=1)
    return (log_ratio - mean) / std


def _legs(prices: pd.DataFrame, long: str, short: str, notional: float = 0.05) -> dict[str, float]:
    rets = np.log(prices[[long, short]] / prices[[long, short]].shift(1)).iloc[-120:]
    vol_l, vol_s = float(rets[long].std()), float(rets[short].std())
    inv = {long: 1 / max(vol_l, 1e-6), short: 1 / max(vol_s, 1e-6)}
    total = inv[long] + inv[short]
    return {long: round(notional * 2 * inv[long] / total, 4),
            short: round(-notional * 2 * inv[short] / total, 4)}


def _simulate(z: pd.Series, ratio_ret: pd.Series) -> tuple[pd.Series, list[dict]]:
    """z 穿越开平仓的逐日 PnL（做均值回归：z 高做空比价，z 低做多）。"""
    pos = 0
    pnl = pd.Series(0.0, index=z.index)
    trades: list[dict] = []
    entry_date = None
    for i, d in enumerate(z.index):
        zv = z.iloc[i]
        if np.isnan(zv):
            continue
        if pos == 0:
            if zv >= Z_OPEN:
                pos, entry_date = -1, d
                pnl.iloc[i] -= COST_PER_SIDE
            elif zv <= -Z_OPEN:
                pos, entry_date = 1, d
                pnl.iloc[i] -= COST_PER_SIDE
        else:
            pnl.iloc[i] += pos * ratio_ret.iloc[i]
            if abs(zv) <= Z_CLOSE:
                pnl.iloc[i] -= COST_PER_SIDE  # 平仓成本先入账，逐笔损益与叠加账本双边成本口径一致
                trades.append({"opened": entry_date.date().isoformat(),
                               "closed": d.date().isoformat(),
                               "direction": "做收敛" if pos < 0 else "做走阔",
                               "pnl_bps": round(float(pnl.loc[entry_date:d].sum()) * 10_000, 1)})
                pos = 0
    return pnl, trades


def desk_report(asof: str) -> dict:
    prices = _prices().loc[:pd.Timestamp(asof)]
    strategies = []
    overlay_pnl = pd.Series(dtype=float)
    scoreboard = []
    for s in STRATEGIES:
        ratio = prices[s["long"]] / prices[s["short"]]
        z = _zscore(ratio)
        zv = float(z.iloc[-1])
        if np.isnan(zv):
            continue
        if abs(zv) >= Z_OPEN:
            state = "做收敛" if zv > 0 else "做走阔"
        elif abs(zv) <= Z_CLOSE:
            state = "观望"
        else:
            state = "持仓/跟踪"
        ratio_ret = np.log(ratio / ratio.shift(1)).fillna(0.0)
        window = z.iloc[-504:]
        pnl, trades = _simulate(window, ratio_ret.reindex(window.index).fillna(0.0))
        ann = float(pnl.mean() * 252)
        vol = float(pnl.std(ddof=1) * np.sqrt(252))
        sharpe = ann / vol if vol > 0 else 0.0
        strategies.append({
            **s, "z": round(zv, 2), "state": state,
            "legs": _legs(prices, s["long"], s["short"]),
            "trailing_2y": {"sharpe": round(sharpe, 2), "ann": round(ann, 4),
                            "trades": len(trades)},
            "recent_trades": trades[-3:],
        })
        scoreboard.append({"id": s["id"], "name": s["name"], "sharpe": round(sharpe, 2),
                           "ann_bps": round(ann * 10_000), "trades": len(trades),
                           "state": state})
        overlay_pnl = pnl if overlay_pnl.empty else overlay_pnl.add(pnl, fill_value=0.0)

    overlay_nav = (1 + overlay_pnl).cumprod()
    gross = sum(sum(abs(v) for v in s["legs"].values()) for s in strategies
                if s["state"] not in ("观望",))
    return {
        "asof": asof,
        "thresholds": {"open": Z_OPEN, "close": Z_CLOSE, "z_window_days": Z_WINDOW,
                       "rule": "|z|≥1.5 开仓 · |z|≤0.5 平仓 · 腿按波动率倒数配平"},
        "strategies": strategies,
        "scoreboard": sorted(scoreboard, key=lambda x: -x["sharpe"]),
        "overlay_ledger": {
            "dates": [d.date().isoformat() for d in overlay_nav.index[-252:]],
            "nav": [round(float(v), 5) for v in overlay_nav.iloc[-252:]],
            "gross_exposure": round(gross, 4),
            "gross_cap": 1.2,
            "accounting": "昨仓×今日收益，开平仓收取 10bp/边，无前视",
        },
        "constraints": {"allow_net_short": False, "gross_exposure_cap": 1.2,
                        "overlay_risk_budget": 0.10,
                        "isolation": "独立叠加账本，默认不改变核心配置权重"},
    }
