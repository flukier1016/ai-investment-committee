"""新闻 point-in-time 三段式防线。

防未来文章进入任何模式；回测对无日期 fail-closed，live 才保留无日期；
同时锁定时区、保序/深拷贝、非法值响亮失败与 Demo fixture 的保守日末时间戳。
"""

from __future__ import annotations

import json
import sys
from copy import deepcopy
from datetime import datetime
from pathlib import Path

import pytest
import pandas as pd

from app.domain.news import InvalidNewsTimestampError, news_asof_filter


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import extract_legacy_fixtures as extractor  # noqa: E402


def test_future_articles_are_filtered_and_boundary_is_visible():
    articles = [
        {"id": "past_z", "publish_ts": "2026-07-09T01:29:59Z", "tags": ["past"]},
        {"id": "equal_offset", "publish_ts": "2026-07-09T09:30:00+08:00"},
        {"id": "future_z", "publish_ts": "2026-07-09T01:30:01Z"},
        {"id": "past_other_offset", "publish_ts": "2026-07-08T20:29:59-05:00"},
    ]
    original = deepcopy(articles)

    visible = news_asof_filter(
        articles, "2026-07-09T09:30:00+08:00", is_backtest=True)

    assert [article["id"] for article in visible] == [
        "past_z", "equal_offset", "past_other_offset"]
    assert articles == original
    visible[0]["tags"].append("mutated output")
    assert articles[0]["tags"] == ["past"], "返回值必须深拷贝，不能反向污染输入"
    assert news_asof_filter(
        articles, "2026-07-09T09:30:00+08:00", is_backtest=True) \
        == news_asof_filter(
            articles, "2026-07-09T09:30:00+08:00", is_backtest=True)


def test_backtest_drops_every_missing_publish_ts_without_published_fallback():
    articles = [
        {"id": "dated", "publish_ts": "2026-07-08T12:00:00+08:00"},
        {"id": "missing_key", "published": "2026-07-08"},
        {"id": "none", "publish_ts": None},
        {"id": "blank", "publish_ts": "  "},
        {"id": "nan", "publish_ts": float("nan")},
        {"id": "pandas_na", "publish_ts": pd.NA},
        {"id": "pandas_nat", "publish_ts": pd.NaT},
    ]

    visible = news_asof_filter(articles, "2026-07-09", is_backtest=True)

    assert [article["id"] for article in visible] == ["dated"]
    assert "publish_ts" not in articles[1], "核心过滤器不得偷用 legacy published 回填"


def test_live_keeps_missing_in_place_but_still_filters_known_future():
    articles = [
        {"id": "missing", "assets": ["gold"]},
        {"id": "future", "publish_ts": "2026-07-10T00:00:00+08:00"},
        {"id": "none", "publish_ts": None},
        {"id": "pandas_na", "publish_ts": pd.NA},
        {"id": "pandas_nat", "publish_ts": pd.NaT},
        {"id": "past", "publish_ts": "2026-07-08T23:59:59+08:00"},
        {"id": "missing", "assets": ["gold"]},
    ]
    original = deepcopy(articles)

    visible = news_asof_filter(articles, "2026-07-09", is_backtest=False)

    assert [article["id"] for article in visible] == [
        "missing", "none", "pandas_na", "pandas_nat", "past", "missing"]
    assert visible[0] == visible[-1], "重复文章不得被去重"
    assert articles == original
    visible[0]["assets"].append("copper")
    assert articles[0]["assets"] == ["gold"]


def test_timezone_defaults_are_fixed_and_invalid_values_fail_loud():
    # naive/date-only 固定解释为项目时区 UTC+8；不读取宿主机时区，也不扩到日末。
    articles = [
        {"id": "equal_local_midnight", "publish_ts": "2026-07-09"},
        {"id": "same_utc_date_but_later_local", "publish_ts": "2026-07-09T00:00:00Z"},
    ]
    assert [article["id"] for article in news_asof_filter(
        articles, "2026-07-09", is_backtest=True)] == ["equal_local_midnight"]

    for bad in ("not-a-time", 1_720_000_000, {"date": "2026-07-09"}):
        with pytest.raises(InvalidNewsTimestampError, match="publish_ts 非法"):
            news_asof_filter(
                [{"id": "bad", "publish_ts": bad}],
                "2026-07-09", is_backtest=False,
            )
    with pytest.raises(InvalidNewsTimestampError, match="asof"):
        news_asof_filter([], "tomorrow", is_backtest=True)
    for missing_asof in (None, float("nan"), pd.NA, pd.NaT):
        with pytest.raises(InvalidNewsTimestampError, match="asof 缺失"):
            news_asof_filter([], missing_asof, is_backtest=True)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="is_backtest"):
        news_asof_filter([], "2026-07-09", is_backtest="false")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match=r"articles\[0\]"):
        news_asof_filter([None], "2026-07-09", is_backtest=True)  # type: ignore[list-item]


def test_demo_news_all_have_conservative_timestamp_policy():
    path = ROOT / "data/demo/legacy/news_library.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    articles = payload["items"]

    assert len(articles) == 195
    assert "保守日末可见代理" in payload["_meta"]["publish_ts_policy"]
    for article in articles:
        assert article["publish_ts"] == f"{article['published']}T23:59:59Z"
        parsed = datetime.fromisoformat(article["publish_ts"].replace("Z", "+00:00"))
        assert parsed.utcoffset() is not None
    assert len(news_asof_filter(articles, "2026-07-09", is_backtest=True)) == 195


def test_legacy_extractor_timestamp_and_atomic_write(tmp_path, monkeypatch):
    assert extractor.legacy_date_to_publish_ts("2026-07-07") \
        == "2026-07-07T23:59:59Z"
    with pytest.raises(ValueError, match="缺少 published"):
        extractor.legacy_date_to_publish_ts(None)
    with pytest.raises(ValueError, match="不是 ISO 日期"):
        extractor.legacy_date_to_publish_ts("07/07/2026")

    monkeypatch.setattr(extractor, "OUT", tmp_path)
    extractor.write("fixture.json", {"items": [{"id": "complete"}]})
    assert json.loads((tmp_path / "fixture.json").read_text(encoding="utf-8")) \
        == {"items": [{"id": "complete"}]}
    assert list(tmp_path.iterdir()) == [tmp_path / "fixture.json"], \
        "原子替换后不得残留临时文件"
