"""Demo 数据装载与 point-in-time 切片。

所有下游模块只能通过 MarketSlice 拿数据：切片按 as-of 截断，
宏观数据额外按 publish_date 过滤（发布日晚于 as-of 的数据不可见），
从结构上杜绝未来函数。切片自带输入指纹（sha256），进入 DecisionRecord。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
DEMO = ROOT / "data" / "demo"


@lru_cache(maxsize=1)
def _prices() -> pd.DataFrame:
    return pd.read_csv(DEMO / "market_prices.csv", index_col=0, parse_dates=True)


@lru_cache(maxsize=1)
def _macro() -> pd.DataFrame:
    df = pd.read_csv(DEMO / "macro.csv")
    df["publish_date"] = pd.to_datetime(df["publish_date"])
    return df


@lru_cache(maxsize=1)
def _erp_inputs() -> pd.DataFrame:
    return pd.read_csv(DEMO / "erp_inputs.csv", index_col=0, parse_dates=True)


@dataclass(frozen=True)
class MarketSlice:
    """as-of 时点可见的全部数据。"""

    asof: pd.Timestamp
    prices: pd.DataFrame      # 日频总回报指数，index<=asof
    macro: pd.DataFrame       # 月频宏观，publish_date<=asof
    erp: pd.DataFrame         # 日频 ERP 输入，index<=asof
    fingerprint: str          # 输入指纹

    def input_meta(self, data_id: str, source: str = "demo") -> dict:
        return {"data_id": data_id, "source": source,
                "asof": self.asof.date().isoformat(),
                "hash": self.fingerprint[:16]}


def trading_dates() -> pd.DatetimeIndex:
    return _prices().index


MIN_HISTORY_ROWS = 300  # TSMOM 12-1 回看 + 协方差估计的最低可用历史


def load_slice(asof: str | pd.Timestamp) -> MarketSlice:
    ts = pd.Timestamp(asof)
    px = _prices().loc[:ts]
    if px.empty:
        raise ValueError(f"as-of {ts.date()} 早于数据起点")
    if len(px) < MIN_HISTORY_ROWS:
        raise ValueError(
            f"as-of {ts.date()} 可见历史仅 {len(px)} 个交易日，"
            f"少于引擎最低要求 {MIN_HISTORY_ROWS} 日（协方差与动量回看窗）")
    macro = _macro()
    macro_visible = macro[macro["publish_date"] <= ts].copy()
    erp = _erp_inputs().loc[:ts]
    digest = hashlib.sha256()
    digest.update(str(px.index[-1].date()).encode())
    digest.update(str(len(px)).encode())
    digest.update(json.dumps(px.iloc[-1].round(4).to_dict(), sort_keys=True).encode())
    if not macro_visible.empty:
        digest.update(json.dumps(macro_visible.iloc[-1].astype(str).to_dict(), sort_keys=True).encode())
    if not erp.empty:
        digest.update(json.dumps(erp.iloc[-1].round(6).to_dict(), sort_keys=True).encode())
    return MarketSlice(asof=ts, prices=px, macro=macro_visible, erp=erp,
                       fingerprint=digest.hexdigest())
