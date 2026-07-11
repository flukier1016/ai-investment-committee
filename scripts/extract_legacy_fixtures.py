"""从旧版静态页（AI投委会_静态页面html.html）抽取可迁移的 Demo fixture。

旧页所有业务数据位于单个 <script id="__DATA_JSON__"> 内联 JSON（约 414KB）。
本脚本抽取其中口径兼容的数据块，做以下迁移处理后写入 data/demo/legacy/：

1. 28 资产 → 27 资产：cash_cny + cash_usd 两条现金腿合并为单一 cash；
2. 旧资产 id → 新资产 id 映射（spx→spy、ndx→qqq、sx5e→fez、nky→ewj、
   kospi→ewy、hsi→hsi_2800、dividend→dividend_510880、tbond_fut→cgb10y_fut、
   credit_aaa→aaa_cp_3y、ust_fut→us10y_zn、copper_sh→copper）；
3. 六引擎口径的数据（辩论、engine_priors、v3 回测净值）不迁移；
4. 全部标记 "source": "legacy_static_page"，仅作展示性 fixture，不进入计算链路。

用法：python scripts/extract_legacy_fixtures.py /path/to/AI投委会_静态页面html.html
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "demo" / "legacy"

ID_MAP = {
    "spx": "spy", "ndx": "qqq", "sx5e": "fez", "nky": "ewj", "kospi": "ewy",
    "hsi": "hsi_2800", "dividend": "dividend_510880", "tbond_fut": "cgb10y_fut",
    "credit_aaa": "aaa_cp_3y", "ust_fut": "us10y_zn", "copper_sh": "copper",
    "cash_cny": "cash", "cash_usd": "cash",
}

KEEP_METHODOLOGY = {"risk_parity", "merrill_clock", "momentum", "erp_value"}


def map_id(old: str) -> str:
    return ID_MAP.get(old, old)


def merge_weight_dict(weights: dict[str, float]) -> dict[str, float]:
    """按新资产 id 合并权重字典（双现金腿相加）。"""
    out: dict[str, float] = {}
    for k, v in weights.items():
        nk = map_id(k)
        out[nk] = round(out.get(nk, 0.0) + float(v), 6)
    return out


def load_inline_json(html_path: Path) -> dict:
    for line in html_path.open(encoding="utf-8"):
        if '__DATA_JSON__' in line and 'type="application/json"' in line:
            raw = line[line.index(">") + 1:].rstrip()
            raw = raw.removesuffix("</script>")
            return json.loads(raw)
    raise SystemExit("未找到 __DATA_JSON__ 内联数据块")


def main(html_file: str) -> None:
    data = load_inline_json(Path(html_file))
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = {"source": "legacy_static_page", "migrated_from": "AI投委会_静态页面html.html",
             "asof": data.get("meta", {}).get("asof", "2026-07-09"),
             "note": "展示性 fixture，仅供参考；计算数字一律由新引擎现算"}

    # 1. 市场快照（28 → 27，价格类数据现金取 CNY 腿）
    snap_rows, seen = [], set()
    for row in data.get("market_snapshot", []):
        nk = map_id(row["id"])
        if nk in seen:
            continue
        seen.add(nk)
        snap_rows.append({**row, "id": nk})
    write("market_snapshot.json", {"_meta": stamp, "rows": snap_rows})

    # 2. 方法论出处卡（只保留新架构四方法 + 单独存档被排除者）
    metho = data.get("methodology", {})
    kept = {k: v for k, v in metho.items() if k in KEEP_METHODOLOGY}
    dropped = {k: v for k, v in metho.items() if k not in KEEP_METHODOLOGY}
    write("methodology_cards.json", {"_meta": stamp, "cards": kept,
                                     "excluded_by_v3": list(dropped)})

    # 3. 资讯库与情绪标签（资产标签映射到新 id 体系）
    news_map = {"oil": "wti", "spx": "spy", "ndx": "qqq", "gold": "gold",
                "copper": "copper", "dxy": "usdcny", "usdcnh": "usdcny",
                "nky": "ewj", "ust10": "us10y_zn", "cgb": "cgb10y_fut",
                "hsi": "hsi_2800", "sx5e": "fez", "csi300": "csi300"}
    news = []
    for item in data.get("knowledge", []):
        assets = sorted({news_map.get(a, a) for a in item.get("assets", [])})
        news.append({**item, "assets": assets})
    write("news_library.json", {"_meta": stamp, "items": news})

    # 4. 利差台台报 + 风控官报告（挂在旧 debate 下，口径独立可用）
    debate = data.get("debate", {})
    desk = debate.get("desk_report", {})
    for strat in desk.get("strategies", []):
        if isinstance(strat.get("legs"), dict):
            strat["legs"] = merge_weight_dict(strat["legs"])
    write("spread_desk_report.json", {"_meta": stamp, **desk})
    write("risk_officer_report.json", {"_meta": stamp, **debate.get("risk_report", {})})

    # 5. 日更轨迹 / 叠加账本 / 台面赌注（top_engine 六引擎口径字段删除）
    live = data.get("live", {})
    history = [{k: v for k, v in row.items() if k != "top_engine"}
               for row in live.get("history", [])]
    write("live_daily_history.json", {"_meta": stamp, "history": history,
                                      "overlay": live.get("overlay", {}),
                                      "desk_bets": live.get("desk_bets", {})})

    # 6. 投资性格问卷（透明映射为风险参数，不改方法话语权）
    profile = data.get("profile", {})
    write("personality_quiz.json", {
        "_meta": {**stamp, "usage": "可选 Demo：问卷 → 16 型 → 风险参数(target_vol/max_drawdown/single_asset_cap/bond_floor/rebalance)，只映射约束，不改变方法权重"},
        "questionnaire": profile.get("questionnaire", []),
        "all_types": profile.get("all_types", {}),
    })

    # 7. 工程效能指标
    write("ops_metrics.json", {"_meta": stamp, **data.get("ops_metrics", {})})

    print(f"已写入 {OUT}（{len(list(OUT.glob('*.json')))} 个 fixture）")


def write(name: str, obj: dict) -> None:
    (OUT / name).write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    print(" -", name)


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else str(
        Path.home() / "Downloads" / "AI投委会_静态页面html.html")
    main(path)
