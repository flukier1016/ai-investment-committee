"""L3 风控闸门：把无约束 BL 目标投影到约束集内（CVXPY）。

设计：min (w − w_uncon)ᵀ Σ (w − w_uncon)
      s.t. 长期约束集（long-only、单资产上限、桶/大类上限、债券底仓、
           波动预算、权重闭合）。
无约束目标本身可行时解就是它本身（风控段为 0），
被裁剪时给出离它最近（协方差度量）的合规组合——
「风控只裁剪、不重定向」，裁剪量单独入账，归因仍闭合。
"""

from __future__ import annotations

import cvxpy as cp
import numpy as np

from ..schemas.config import AllocationConfig
from ..schemas.decision import GuardrailAction
from . import universe

TOL = 1e-6


def _short_name(asset_id: str) -> str:
    for a in universe.load_universe()["assets"]:
        if a["id"] == asset_id:
            return a["short_name"]
    return asset_id


def asset_caps(asset_order: list[str], config: AllocationConfig) -> np.ndarray:
    """明细资产上限：single_asset_cap 与（若配置）风险敞口上限（万元→比例）取小。"""
    idx = {a: i for i, a in enumerate(asset_order)}
    caps = np.full(len(asset_order), config.single_asset_cap)
    caps[idx["cash"]] = 1.0
    for aid, wan in config.risk_caps_wan.items():
        if aid in idx and config.principal > 0:
            caps[idx[aid]] = min(caps[idx[aid]], wan * 10_000 / config.principal)
    return caps


def project(w_target: np.ndarray, sigma: np.ndarray, asset_order: list[str],
            config: AllocationConfig, vol_cap: bool = True) -> np.ndarray:
    """把目标权重投影到约束集内（离目标最近的合规组合）。

    投影度量 Σ + εI：纯 Σ 度量下现金（方差≈0）的偏移零成本，会被求解器
    当作自由变量任意挪动；加 εI 让每单位权重偏移都有代价。
    """
    n = len(asset_order)
    idx = {a: i for i, a in enumerate(asset_order)}
    bucket_map = universe.bucket_of()
    class_map = universe.class_of_bucket()
    caps = asset_caps(asset_order, config)
    cn_eq = [idx[a] for a in asset_order if bucket_map[a] == "cn_equity"]
    equity = [idx[a] for a in asset_order if class_map[bucket_map[a]] == "equity"]
    bond = [idx[a] for a in asset_order if class_map[bucket_map[a]] == "bond"]

    w = cp.Variable(n)
    constraints = [
        cp.sum(w) == 1,
        w >= 0,
        w <= caps,
        cp.sum(w[cn_eq]) <= config.cn_equity_cap,
        cp.sum(w[equity]) <= config.equity_class_cap,
        cp.sum(w[bond]) >= config.bond_floor,
    ]
    if vol_cap:
        constraints.append(cp.quad_form(w, cp.psd_wrap(sigma)) <= config.target_vol ** 2)
    metric = sigma + 2e-3 * np.eye(n)
    problem = cp.Problem(cp.Minimize(cp.quad_form(w - w_target, cp.psd_wrap(metric))), constraints)
    problem.solve(solver=cp.CLARABEL)
    if w.value is None:
        raise RuntimeError(f"风控投影求解失败: {problem.status}")
    w_proj = np.maximum(np.asarray(w.value).flatten(), 0.0)
    return w_proj / w_proj.sum()


def apply_guardrails(w_uncon: np.ndarray, sigma: np.ndarray, asset_order: list[str],
                     config: AllocationConfig) -> tuple[np.ndarray, list[GuardrailAction]]:
    n = len(asset_order)
    idx = {a: i for i, a in enumerate(asset_order)}
    bucket_map = universe.bucket_of()
    class_map = universe.class_of_bucket()
    caps = asset_caps(asset_order, config)
    cn_eq = [idx[a] for a in asset_order if bucket_map[a] == "cn_equity"]
    equity = [idx[a] for a in asset_order if class_map[bucket_map[a]] == "equity"]
    bond = [idx[a] for a in asset_order if class_map[bucket_map[a]] == "bond"]

    w_final = project(w_uncon, sigma, asset_order, config, vol_cap=True)

    port_vol_uncon = float(np.sqrt(max(w_uncon @ sigma @ w_uncon, 0.0)))
    port_vol_final = float(np.sqrt(max(w_final @ sigma @ w_final, 0.0)))
    cn_eq_w = float(w_final[cn_eq].sum())
    eq_w = float(w_final[equity].sum())
    bond_w = float(w_final[bond].sum())
    max_asset_i = int(np.argmax(w_final - caps))
    clipped = bool(np.abs(w_final - w_uncon).max() > 1e-4)

    actions = [
        GuardrailAction(rule="long_only", label="禁止做空",
                        triggered=bool((w_uncon < -TOL).any()),
                        detail="无约束目标出现负权重，已投影回多头区" if (w_uncon < -TOL).any()
                        else "所有明细资产目标权重均不低于 0"),
        GuardrailAction(rule=f"single_asset_cap_{config.single_asset_cap:.0%}", label="单一资产上限",
                        triggered=bool((w_uncon > caps + TOL).any()),
                        detail=f"最接近上限：{_short_name(asset_order[max_asset_i])} "
                               f"{w_final[max_asset_i]:.1%}（上限 {caps[max_asset_i]:.1%}）"),
        GuardrailAction(rule=f"max_cn_equity_{config.cn_equity_cap:.0%}", label="中国股票桶上限",
                        triggered=bool(sum(w_uncon[i] for i in cn_eq) > config.cn_equity_cap + TOL),
                        detail=f"中国股票 {cn_eq_w:.1%}，上限 {config.cn_equity_cap:.0%}"),
        GuardrailAction(rule=f"max_equity_{config.equity_class_cap:.0%}", label="权益大类上限",
                        triggered=bool(sum(w_uncon[i] for i in equity) > config.equity_class_cap + TOL),
                        detail=f"权益大类 {eq_w:.1%}，上限 {config.equity_class_cap:.0%}"),
        GuardrailAction(rule=f"bond_floor_{config.bond_floor:.0%}", label="债券底仓下限",
                        triggered=bool(sum(w_uncon[i] for i in bond) < config.bond_floor - TOL),
                        detail=f"债券大类 {bond_w:.1%}，下限 {config.bond_floor:.0%}"),
        GuardrailAction(rule=f"vol_budget_{config.target_vol:.0%}", label="波动预算",
                        triggered=bool(port_vol_uncon > config.target_vol + TOL),
                        detail=f"组合事前波动 {port_vol_final:.2%}，预算 {config.target_vol:.0%}"
                               + (f"（裁剪前 {port_vol_uncon:.2%}）" if port_vol_uncon > config.target_vol else "")),
        GuardrailAction(rule="weight_sum", label="权重闭合",
                        triggered=False,
                        detail=f"明细权重加总 {w_final.sum():.6f}，闭合误差 < 1e-6"),
        GuardrailAction(rule="projection", label="风控投影",
                        triggered=clipped,
                        detail="约束触发，已按协方差度量投影到最近合规组合" if clipped
                        else "无约束目标本身合规，未发生裁剪"),
    ]
    return w_final, actions
