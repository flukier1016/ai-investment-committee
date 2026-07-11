"""确定性 Demo 市场数据生成器。

生成 2022-01 ~ 2026-07 的 26 个风险资产 + 现金的日频总回报指数、
月频宏观序列（PMI/CPI，含发布日以支持 point-in-time）、
日频 ERP 输入（沪深300 E/P 与 10Y 国债收益率）。

固定随机种子，任何机器上重跑输出完全一致。
数据内置四段宏观情景（滞胀 2022 → 衰退触底 2023H1 → 复苏 2023H2-2024 →
过热 2025 → 复苏确认 2026），使 TSMOM / Investment Clock / ERP 在不同
as-of 日期产生方向不同的信号，支撑情景回放与回测。

运行：uv run --project backend python scripts/generate_demo_data.py
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "data" / "demo"
SEED = 20260709

START, END = "2020-01-02", "2026-07-09"

# 各资产基准年化参数: (基础漂移, 年化波动)
BASE_PARAMS: dict[str, tuple[float, float]] = {
    "csi300": (0.05, 0.19), "csi500": (0.05, 0.23), "dividend_510880": (0.06, 0.15),
    "hsi_2800": (0.04, 0.24), "spy": (0.08, 0.17), "qqq": (0.10, 0.22),
    "fez": (0.06, 0.19), "ewj": (0.06, 0.17), "ewy": (0.05, 0.22),
    "cgb10y_fut": (0.03, 0.045), "cgb_1_3": (0.025, 0.012), "aaa_cp_3y": (0.032, 0.018),
    "us10y_zn": (0.025, 0.07), "lqd": (0.035, 0.08),
    "rebar": (0.01, 0.24), "copper": (0.04, 0.22), "wti": (0.02, 0.33),
    "brent": (0.02, 0.31), "gold": (0.06, 0.14), "silver": (0.05, 0.26),
    "usdcny": (0.01, 0.04), "eurusd": (0.0, 0.07), "usdjpy": (0.01, 0.09),
    "gbpusd": (0.0, 0.08), "audusd": (0.0, 0.09), "usdcad": (0.0, 0.06),
}

# 情景区间: (起, 止, 名称, 各桶漂移调整/年化)
REGIMES = [
    ("2020-01-02", "2020-03-20", "covid_crash", {
        "cn_equity": -0.85, "foreign_equity": -1.10, "cn_bond": 0.06,
        "foreign_bond": 0.10, "commodity": -0.95, "fx_usd": 0.18,
    }),
    ("2020-03-23", "2020-12-31", "reflation_rebound", {
        "cn_equity": 0.42, "foreign_equity": 0.50, "cn_bond": 0.01,
        "foreign_bond": 0.03, "commodity": 0.38, "fx_usd": -0.10,
    }),
    ("2021-01-04", "2021-12-31", "expansion", {
        "cn_equity": 0.02, "foreign_equity": 0.16, "cn_bond": 0.02,
        "foreign_bond": -0.03, "commodity": 0.22, "fx_usd": -0.02,
    }),
    ("2022-01-03", "2022-12-30", "stagflation", {
        "cn_equity": -0.22, "foreign_equity": -0.25, "cn_bond": -0.01,
        "foreign_bond": -0.14, "commodity": 0.28, "fx_usd": 0.10,
    }),
    ("2023-01-02", "2023-06-30", "recession_trough", {
        "cn_equity": -0.04, "foreign_equity": 0.10, "cn_bond": 0.045,
        "foreign_bond": 0.06, "commodity": -0.16, "fx_usd": -0.04,
    }),
    ("2023-07-03", "2024-12-31", "recovery", {
        "cn_equity": 0.14, "foreign_equity": 0.12, "cn_bond": 0.015,
        "foreign_bond": 0.03, "commodity": 0.05, "fx_usd": -0.02,
    }),
    ("2025-01-01", "2025-12-31", "overheat", {
        "cn_equity": 0.06, "foreign_equity": 0.05, "cn_bond": -0.025,
        "foreign_bond": -0.05, "commodity": 0.20, "fx_usd": 0.03,
    }),
    ("2026-01-01", "2026-07-09", "recovery_confirmed", {
        "cn_equity": 0.24, "foreign_equity": 0.14, "cn_bond": 0.01,
        "foreign_bond": -0.03, "commodity": -0.06, "fx_usd": -0.05,
    }),
]

BUCKET_OF = {
    "csi300": "cn_equity", "csi500": "cn_equity", "dividend_510880": "cn_equity",
    "hsi_2800": "cn_equity", "spy": "foreign_equity", "qqq": "foreign_equity",
    "fez": "foreign_equity", "ewj": "foreign_equity", "ewy": "foreign_equity",
    "cgb10y_fut": "cn_bond", "cgb_1_3": "cn_bond", "aaa_cp_3y": "cn_bond",
    "us10y_zn": "foreign_bond", "lqd": "foreign_bond",
    "rebar": "commodity", "copper": "commodity", "wti": "commodity",
    "brent": "commodity", "gold": "commodity", "silver": "commodity",
    "usdcny": "fx", "eurusd": "fx", "usdjpy": "fx",
    "gbpusd": "fx", "audusd": "fx", "usdcad": "fx",
}
# 外汇桶按“美元多头暴露”方向吃 fx_usd 漂移
FX_USD_SIGN = {"usdcny": 1, "eurusd": -1, "usdjpy": 1, "gbpusd": -1, "audusd": -1, "usdcad": 1}

CASH_ANNUAL = 0.018


def block_correlation(assets: list[str]) -> np.ndarray:
    intra = {"cn_equity": 0.72, "foreign_equity": 0.68, "cn_bond": 0.62,
             "foreign_bond": 0.66, "commodity": 0.45, "fx": 0.35}
    cross = {
        ("cn_equity", "foreign_equity"): 0.42, ("cn_equity", "cn_bond"): -0.12,
        ("cn_equity", "foreign_bond"): -0.05, ("cn_equity", "commodity"): 0.22,
        ("cn_equity", "fx"): 0.05, ("foreign_equity", "cn_bond"): -0.05,
        ("foreign_equity", "foreign_bond"): -0.15, ("foreign_equity", "commodity"): 0.25,
        ("foreign_equity", "fx"): 0.08, ("cn_bond", "foreign_bond"): 0.30,
        ("cn_bond", "commodity"): -0.08, ("cn_bond", "fx"): 0.02,
        ("foreign_bond", "commodity"): -0.05, ("foreign_bond", "fx"): 0.10,
        ("commodity", "fx"): 0.12,
    }
    n = len(assets)
    corr = np.eye(n)
    for i in range(n):
        for j in range(i + 1, n):
            bi, bj = BUCKET_OF[assets[i]], BUCKET_OF[assets[j]]
            if bi == bj:
                c = intra[bi]
            else:
                c = cross.get((bi, bj)) or cross.get((bj, bi)) or 0.0
            corr[i, j] = corr[j, i] = c
    # 保证正定
    eigval, eigvec = np.linalg.eigh(corr)
    eigval = np.clip(eigval, 1e-4, None)
    corr = eigvec @ np.diag(eigval) @ eigvec.T
    d = np.sqrt(np.diag(corr))
    return corr / np.outer(d, d)


def regime_drift(asset: str, regime_adj: dict[str, float]) -> float:
    bucket = BUCKET_OF[asset]
    if bucket == "fx":
        return regime_adj["fx_usd"] * FX_USD_SIGN[asset]
    return regime_adj[bucket]


def generate_prices() -> pd.DataFrame:
    rng = np.random.default_rng(SEED)
    dates = pd.bdate_range(START, END)
    assets = list(BASE_PARAMS)
    n, t = len(assets), len(dates)
    corr = block_correlation(assets)
    chol = np.linalg.cholesky(corr)
    vols = np.array([BASE_PARAMS[a][1] for a in assets]) / np.sqrt(252)

    drift_daily = np.zeros((t, n))
    for start, end, _, adj in REGIMES:
        mask = (dates >= start) & (dates <= end)
        for j, a in enumerate(assets):
            total = BASE_PARAMS[a][0] * 0.3 + regime_drift(a, adj)
            drift_daily[mask, j] = total / 252

    shocks = rng.standard_normal((t, n)) @ chol.T * vols
    log_ret = drift_daily - 0.5 * vols**2 + shocks
    levels = 100 * np.exp(np.cumsum(log_ret, axis=0))
    df = pd.DataFrame(levels, index=dates, columns=assets)
    cash = 100 * np.exp(np.arange(t) * CASH_ANNUAL / 252)
    df.insert(0, "cash", cash)
    df.index.name = "date"
    return df.round(4)


def generate_macro(dates: pd.DatetimeIndex) -> pd.DataFrame:
    """月频 PMI / CPI，publish_date = 数据月的次月 10 日（point-in-time 用）。"""
    months = pd.period_range(dates[0], dates[-1], freq="M")
    segs = {
        "covid_crash": (43.0, -1.2, 2.8, -0.25),
        "reflation_rebound": (51.5, 0.35, 1.2, 0.05),
        "expansion": (51.5, -0.02, 2.4, 0.12),
        "stagflation": (47.5, -0.08, 5.8, 0.28),      # PMI 低走弱, CPI 高企
        "recession_trough": (48.0, 0.10, 3.0, -0.30),
        "recovery": (50.8, 0.06, 1.6, 0.02),
        "overheat": (52.8, 0.02, 3.4, 0.22),
        "recovery_confirmed": (51.8, 0.10, 1.4, -0.08),
    }
    rng = np.random.default_rng(SEED + 1)
    rows = []
    pmi, cpi = 50.5, 2.2
    for m in months:
        mid = m.to_timestamp() + pd.Timedelta(days=14)
        name = next((nm for s, e, nm, _ in REGIMES
                     if pd.Timestamp(s) <= mid <= pd.Timestamp(e) + pd.Timedelta(days=31)),
                    "recovery_confirmed")
        anchor_pmi, slope_pmi, anchor_cpi, slope_cpi = segs[name]
        pmi = 0.75 * pmi + 0.25 * anchor_pmi + slope_pmi + rng.normal(0, 0.25)
        cpi = 0.85 * cpi + 0.15 * anchor_cpi + slope_cpi + rng.normal(0, 0.06)
        publish = (m + 1).to_timestamp() + pd.Timedelta(days=9)
        rows.append({
            "month": str(m), "pmi_cn": round(pmi, 1), "cpi_yoy_cn": round(cpi, 2),
            "publish_date": publish.date().isoformat(), "source": "demo:macro_cn",
        })
    return pd.DataFrame(rows)


def generate_erp_inputs(prices: pd.DataFrame) -> pd.DataFrame:
    """沪深300 E/P（由盈利指数/价格推出）与 10Y 国债收益率（情景锚定的均值回复路径）。"""
    dates = prices.index
    t = len(dates)
    earnings = 100 * 0.075 * np.exp(np.arange(t) * 0.05 / 252)  # 盈利缓慢增长
    ep = earnings / prices["csi300"].to_numpy()
    anchors = {"covid_crash": 0.0255, "reflation_rebound": 0.0310, "expansion": 0.0295,
               "stagflation": 0.0295, "recession_trough": 0.0262, "recovery": 0.0240,
               "overheat": 0.0228, "recovery_confirmed": 0.0192}
    rng = np.random.default_rng(SEED + 2)
    y10 = np.empty(t)
    level = 0.0285
    for i, d in enumerate(dates):
        name = next((nm for s, e, nm, _ in REGIMES
                     if pd.Timestamp(s) <= d <= pd.Timestamp(e)), "recovery_confirmed")
        level += 0.02 * (anchors[name] - level) + rng.normal(0, 0.00012)
        y10[i] = level
    return pd.DataFrame({
        "date": dates, "csi300_ep": np.round(ep, 5), "cgb10y_yield": np.round(y10, 5),
    }).set_index("date")


def main() -> None:
    DEMO.mkdir(parents=True, exist_ok=True)
    prices = generate_prices()
    prices.to_csv(DEMO / "market_prices.csv")
    macro = generate_macro(prices.index)
    macro.to_csv(DEMO / "macro.csv", index=False)
    erp = generate_erp_inputs(prices)
    erp.to_csv(DEMO / "erp_inputs.csv")
    manifest = {
        "seed": SEED, "start": START, "end": END,
        "regimes": [{"start": s, "end": e, "name": n} for s, e, n, _ in REGIMES],
        "files": ["market_prices.csv", "macro.csv", "erp_inputs.csv"],
        "note": "Demo 合成数据，固定种子可复现；所有下游数字由引擎从本数据确定性计算。",
    }
    (DEMO / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    print(f"prices: {prices.shape}, macro: {len(macro)} months, erp: {len(erp)} days")
    print("首尾净值样本:", prices.iloc[-1][["csi300", "cgb10y_fut", "gold"]].to_dict())


if __name__ == "__main__":
    main()
