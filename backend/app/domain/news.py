"""新闻 point-in-time 可见性契约。

只按调用方给定的 as-of 过滤，不读时钟、不排序、不去重，也不解释新闻内容。
缺失时间与非法时间严格区分：回测对缺失时间 fail-closed，live 允许原样保留；
非空但非法的时间戳始终响亮失败，未来调用方必须降级为 abstain。
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from copy import deepcopy
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

import pandas as pd


# 项目面向中国投资者；无时区/date-only 输入固定解释为 UTC+8 当日 00:00。
PROJECT_TIMEZONE = timezone(timedelta(hours=8), name="Asia/Shanghai")
UTC = timezone.utc


class InvalidNewsTimestampError(ValueError):
    """新闻时间非法或 as-of 缺失/非法；调用方必须显式降级。"""


def _is_missing_timestamp(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    try:
        return bool(pd.isna(value))  # 标量 NaN / pandas.NA / pandas.NaT
    except (TypeError, ValueError):
        return False  # list/dict/array 不是“缺失标量”，交给解析器判非法


def _parse_timestamp(value: object, *, field: str) -> datetime:
    """解析为 UTC；naive/date-only 按固定项目时区解释，不依赖宿主机时区。"""
    if _is_missing_timestamp(value):
        raise InvalidNewsTimestampError(f"{field} 缺失")
    parsed: datetime
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime.combine(value, time.min)
    elif isinstance(value, str):
        raw = value.strip()
        normalized = f"{raw[:-1]}+00:00" if raw.lower().endswith("z") else raw
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError as exc:
            raise InvalidNewsTimestampError(
                f"{field} 不是合法 ISO-8601 时间戳：{value!r}") from exc
    else:
        raise InvalidNewsTimestampError(
            f"{field} 不是合法 ISO-8601 时间戳：{value!r}")

    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=PROJECT_TIMEZONE)
    return parsed.astimezone(UTC)


def news_asof_filter(
    articles: Iterable[Mapping[str, Any]],
    asof: str | date | datetime,
    is_backtest: bool,
) -> list[dict[str, Any]]:
    """返回 as-of 时点可见新闻的深拷贝，保持输入顺序与重复项。

    - `publish_ts <= asof`：保留；未来文章始终剔除（live 也一样）。
    - 缺失 `publish_ts`：回测剔除，live 保留。
    - 非空但非法 `publish_ts`：显式 ValueError，绝不当作“缺失”放行。
    """
    if type(is_backtest) is not bool:
        raise TypeError("is_backtest 必须是 bool")
    cutoff = _parse_timestamp(asof, field="asof")
    visible: list[dict[str, Any]] = []
    for index, article in enumerate(articles):
        if not isinstance(article, Mapping):
            raise TypeError(f"articles[{index}] 必须是映射对象")
        published = article.get("publish_ts")
        if _is_missing_timestamp(published):
            if not is_backtest:
                visible.append(deepcopy(dict(article)))
            continue
        try:
            publish_ts = _parse_timestamp(published, field="publish_ts")
        except InvalidNewsTimestampError as exc:
            identity = (article.get("id") or article.get("slug")
                        or article.get("title") or f"index={index}")
            raise InvalidNewsTimestampError(
                f"新闻 {identity!r} 的 publish_ts 非法") from exc
        if publish_ts <= cutoff:
            visible.append(deepcopy(dict(article)))
    return visible


__all__ = ["InvalidNewsTimestampError", "PROJECT_TIMEZONE", "news_asof_filter"]
