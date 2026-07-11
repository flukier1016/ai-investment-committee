"""Black-Litterman 整合层（整合主席，非第五张普通信号卡）。

π = δ·Σ·w_strategic          （Risk Parity 先验，非教科书市值先验，属注明的定制变体）
A = P·τΣ·Pᵀ + Ω
x = A⁻¹(Q − P·π)
μ_BL = π + τΣ·Pᵀ·x           （后验期望收益）
λ_k = (τ/δ)·x_k              （He-Litterman：最优组合 = 先验组合 + Σ λ_k·P_k）

预算闭合：绝对观点会注入净权重，按「向整个先验组合融资」处理：
c_k = λ_k·(P_k − sum(P_k)·w_prior)，则 Σc_k 每条观点均预算中性，
w_uncon = w_prior + Σ c_k 严格加总为 1，归因可加、可闭合、可审计。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..schemas.decision import View


@dataclass(frozen=True)
class BLResult:
    pi: np.ndarray                     # 先验隐含收益
    mu_bl: np.ndarray                  # 后验期望收益
    lambdas: list[float]               # 每条观点应用的 λ（截断后）
    lambdas_raw: list[float]           # He-Litterman 原始 λ
    view_contribs: list[np.ndarray]    # 每条观点的预算中性权重贡献 c_k
    w_uncon: np.ndarray                # 无约束目标权重（prior + Σc_k）


def run_bl(w_prior: np.ndarray, sigma: np.ndarray, views: list[View],
           asset_order: list[str], delta: float, tau: float,
           max_view_tilt: float = 0.05) -> BLResult:
    pi = delta * sigma @ w_prior
    if not views:
        return BLResult(pi=pi, mu_bl=pi.copy(), lambdas=[], lambdas_raw=[],
                        view_contribs=[], w_uncon=w_prior.copy())
    idx = {a: i for i, a in enumerate(asset_order)}
    k, n = len(views), len(asset_order)
    P = np.zeros((k, n))
    Q = np.zeros(k)
    omega_diag = np.zeros(k)
    for r, v in enumerate(views):
        for a, w in v.P.items():
            P[r, idx[a]] = w
        Q[r] = v.Q
        omega_diag[r] = max(v.Omega, 1e-10)
    A = P @ (tau * sigma) @ P.T + np.diag(omega_diag)
    x = np.linalg.solve(A, Q - P @ pi)
    mu_bl = pi + tau * sigma @ P.T @ x
    lambdas_raw = [float(tau / delta * xi) for xi in x]
    # 两条确定性构造纪律（均记录在 DecisionRecord，可审计）：
    # 1. 观点方向纪律：联合求解下，被同资产更强观点支配的观点会得到反号 λ
    #    （观点空间多重共线性）。若 λ 与该观点自身的超额判断
    #    sign(Q_k − P_k·π) 相反，则置 0（“未采纳”），不让观点反向出现在归因里。
    # 2. Idzorek (2007) 式单观点倾斜上限：低波动腿的 λ 会天然放大，
    #    截断到 ±max_view_tilt，保证每条观点的权重推力落在人类尺度。
    excess = Q - P @ pi
    lambdas = []
    for lam_raw, ex in zip(lambdas_raw, excess):
        if abs(ex) > 1e-9 and lam_raw * ex < 0:
            lambdas.append(0.0)
        else:
            lambdas.append(float(np.clip(lam_raw, -max_view_tilt, max_view_tilt)))
    contribs = [lam * (P[r] - P[r].sum() * w_prior) for r, lam in enumerate(lambdas)]
    w_uncon = w_prior + np.sum(contribs, axis=0)
    return BLResult(pi=pi, mu_bl=mu_bl, lambdas=lambdas, lambdas_raw=lambdas_raw,
                    view_contribs=contribs, w_uncon=w_uncon)
