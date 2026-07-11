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


# ---- 类型化数据错误：类型数 = 引擎应做出的反应数 ----
# 借鉴 TradingAgents 0.3.0 的 data-access contract：调用方按类型决定
# 「整次中止 / 单信号弃权 / 稍后重试」，API 层按类型映射 4xx/5xx。

class DataError(Exception):
    """数据层错误基类。"""


class NoDataError(DataError):
    """请求窗口内完全无数据（as-of 早于数据起点等）——核心输入缺失应整次中止。"""


class InsufficientHistoryError(DataError):
    """有数据但历史长度不满足估计窗口——核心输入不可用应整次中止。"""


class StaleDataError(DataError):
    """最新可见数据距 as-of 超过新鲜度阈值——接真实行情源后启用。"""


class ProviderNotConfiguredError(DataError):
    """请求了未配置的数据供应商——配置错误，启动/请求期响亮失败。"""


def load_slice(asof: str | pd.Timestamp) -> MarketSlice:
    ts = pd.Timestamp(asof)
    px = _prices().loc[:ts]
    if px.empty:
        raise NoDataError(f"as-of {ts.date()} 早于数据起点")
    if len(px) < MIN_HISTORY_ROWS:
        raise InsufficientHistoryError(
            f"as-of {ts.date()} 可见历史仅 {len(px)} 个交易日，"
            f"少于引擎最低要求 {MIN_HISTORY_ROWS} 日（协方差与动量回看窗）")
    macro = _macro()
    macro_visible = macro[macro["publish_date"] <= ts].copy()
    erp = _erp_inputs().loc[:ts]
    # 防前视硬断言（不信任上游预过滤，V3 5.4 point-in-time 纪律的最后一道闸）
    assert px.index.max() <= ts, "价格切片含未来数据"
    assert erp.empty or erp.index.max() <= ts, "ERP 切片含未来数据"
    assert macro_visible.empty or macro_visible["publish_date"].max() <= ts, \
        "宏观切片含发布日晚于 as-of 的数据"
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
