"""Сетевые индексы качества кластеризации: AVI, AVU, ANUI и модулярность Ньюмана (04.10.2026).

Статус: определения AVI/AVU/ANUI подтверждены двумя независимыми источниками (см. ниже) и численной сверкой;
определение «MQ» из условий конкурса НЕ установлено, поэтому ключа «MQ» здесь нет (см. `MQ_STATUS`).

Обозначения. A — симметричная неотрицательная матрица весов рёбер сети (n × n), нули на диагонали; labels — метки
кластеров; K — число кластеров. S — матрица K × K суммарных весов между кластерами: S_kl = Σ_{i∈k, j∈l} A_ij.
Внутренние рёбра входят в S_kk дважды (A симметрична). out_k = Σ_{l≠k} S_kl, in_l = Σ_{k≠l} S_kl (для симметричной A
совпадают).

* Изолированность кластера k:   I_k = S_kk / Σ_l S_kl.            AVI = (1/K) Σ_k I_k,          больше — лучше, ∈ [0, 1].
* Склонность k и l к слиянию:   U_kl = S_kl / (out_k + in_l − S_kl).  AVU = (1/K) Σ_k Σ_{l≠k} U_kl, меньше — лучше.
* Сводный индекс:               ANUI = 1 / (AVU + 1/AVI),                                          больше — лучше.
* Модулярность Ньюмана (взвешенная): Q = Σ_k [ S_kk/(2m) − (d_k/(2m))² ], 2m = Σ_ij A_ij, d_k = Σ_l S_kl.   больше — лучше.

Источники определений:
1. Эталонная реализация Shalileh S., github.com/Sorooshi/Pattern, metrics/clustering_metrics.py (коммит e5ff50b, GPL-3.0):
   класс AdjacencyClusteringMetrics, поля AVI, AVU, ANUI, modularity. Код здесь НЕ перенесён: реализация написана заново
   по формулам выше; эталон используется только как внешняя проверка в тесте (опционально, `SBERINDEX_PATTERN_REF`).
2. Публичный репозиторий quizzes1/sberindex, src/icvi.py (без лицензии; код не использовался), называет первоисточником
   статью «Defining quality metrics for graph clustering evaluation», Expert Systems with Applications 71 (2017) 1–17.
   Саму статью мы не открывали: соответствие определений ей подтверждено только через эти два источника.

Соглашения, которые влияют на числа (зафиксированы, как у эталона):
* кластер без единого ребра (Σ_l S_kl = 0): I_k = 0 (а не NaN) — такие кластеры учитываются в `clusters_without_edges`;
* пара (k, l) с нулевым знаменателем в AVU даёт 0;
* K = 1: AVU = 0, AVI = 1 (если в сети есть рёбра), ANUI = 1/(0 + 1) = 1;
* AVI не нормируется на K, поэтому естественно падает при росте K (вопрос о нормировке задан организаторам не был).
"""
from __future__ import annotations

import numpy as np

#: Определение «MQ» из условий конкурса (SW/CH/S_Dbw/AVI/AVU/MQ) в найденных материалах не раскрыто. Возможны как минимум
#: модулярность Ньюмана и «Modularization Quality» (Mancoridis и др.), и это разные величины. Пока организатор не ответил,
#: в отчётах писать «MQ: SPEC_UNRESOLVED», а `modularity_newman` показывать под собственным именем.
MQ_STATUS = "SPEC_UNRESOLVED"

BETTER = {"AVI": +1, "AVU": -1, "ANUI": +1, "modularity_newman": +1}


def _check(A: np.ndarray, labels: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    A = np.asarray(A, dtype=float)
    labels = np.asarray(labels)
    if A.ndim != 2 or A.shape[0] != A.shape[1]:
        raise ValueError("A должна быть квадратной матрицей")
    if labels.shape != (A.shape[0],):
        raise ValueError("labels должна иметь длину n")
    if not np.isfinite(A).all():
        raise ValueError("в A есть NaN/inf")
    if (A < 0).any():
        raise ValueError("веса рёбер должны быть неотрицательными")
    if not np.allclose(A, A.T, rtol=0, atol=1e-12):
        raise ValueError("A должна быть симметричной (неориентированная сеть)")
    if np.diag(A).any():
        raise ValueError("на диагонали A должны быть нули (петель нет)")
    return A, labels


def block_sums(A: np.ndarray, labels: np.ndarray) -> np.ndarray:
    """S (K × K): суммы весов между кластерами в порядке np.unique(labels)."""
    A, labels = _check(A, labels)
    _, inv = np.unique(labels, return_inverse=True)
    K = int(inv.max()) + 1
    M = np.zeros((len(labels), K))
    M[np.arange(len(labels)), inv] = 1.0
    return M.T @ A @ M


def _avi_s(S: np.ndarray) -> float:
    row = S.sum(axis=1)
    return float(np.divide(np.diag(S), row, out=np.zeros(len(S)), where=row != 0).mean())


def _avu_s(S: np.ndarray) -> float:
    K = len(S)
    out = S.sum(axis=1) - np.diag(S)
    inn = S.sum(axis=0) - np.diag(S)
    den = out[:, None] + inn[None, :] - S
    np.fill_diagonal(den, 1.0)
    U = np.divide(S, den, out=np.zeros_like(S), where=den != 0)
    np.fill_diagonal(U, 0.0)
    return float(U.sum() / K)


def _anui_s(S: np.ndarray) -> float:
    a, u = _avi_s(S), _avu_s(S)
    return 0.0 if a == 0 else float(1.0 / (u + 1.0 / a))


def _q_s(S: np.ndarray) -> float:
    two_m = S.sum()
    if two_m == 0:
        return float("nan")
    d = S.sum(axis=1)
    return float(np.sum(np.diag(S) / two_m - (d / two_m) ** 2))


def avi(A: np.ndarray, labels: np.ndarray) -> float:
    """Average Isolability, больше — лучше."""
    return _avi_s(block_sums(A, labels))


def avu(A: np.ndarray, labels: np.ndarray) -> float:
    """Average Unifiability, меньше — лучше."""
    return _avu_s(block_sums(A, labels))


def anui(A: np.ndarray, labels: np.ndarray) -> float:
    """ANUI = 1 / (AVU + 1/AVI); 0, если AVI = 0."""
    return _anui_s(block_sums(A, labels))


def modularity_newman(A: np.ndarray, labels: np.ndarray) -> float:
    """Взвешенная модулярность Ньюмана–Гирвана; NaN для сети без рёбер. НЕ называть «MQ» (см. MQ_STATUS)."""
    return _q_s(block_sums(A, labels))


def clusters_without_edges(A: np.ndarray, labels: np.ndarray) -> int:
    """Сколько кластеров не имеют ни одного ребра (для них I_k принят равным 0)."""
    return int((block_sums(A, labels).sum(axis=1) == 0).sum())


def random_partition_null(A: np.ndarray, labels: np.ndarray, B: int = 300, seed: int = 20261005) -> dict:
    """Нулевая модель: индексы разбиения при случайной перестановке меток (размеры групп сохраняются, структура сети разрушается).

    Нужна, потому что AVI не нормирован на число групп: при случайных метках и K равных группах AVI ≈ 1/K (K = 5 → 0,20; K = 33 → 0,03),
    а группа-гигант делает AVI высоким без всякого качества. Возвращает среднее, стандартное отклонение и z-оценку фактического значения.
    """
    from scipy.sparse import csr_matrix

    A, labels = _check(A, labels)
    As = csr_matrix(A)
    _, inv = np.unique(labels, return_inverse=True)
    K = int(inv.max()) + 1
    rng = np.random.default_rng(seed)

    def blocks(lab_idx):
        M = np.zeros((len(lab_idx), K))
        M[np.arange(len(lab_idx)), lab_idx] = 1.0
        return M.T @ (As @ M)

    fns = {"AVI": _avi_s, "AVU": _avu_s, "ANUI": _anui_s, "modularity_newman": _q_s}
    S_obs = blocks(inv)
    obs = {k: fn(S_obs) for k, fn in fns.items()}
    draws = {k: [] for k in fns}
    for _ in range(B):
        S = blocks(rng.permutation(inv))
        for k, fn in fns.items():
            draws[k].append(fn(S))
    out = {}
    for key in fns:
        vals = np.array(draws[key])
        sd = float(vals.std())
        out[key] = {"observed": obs[key], "null_mean": float(vals.mean()), "null_sd": sd,
                    "z": float((obs[key] - vals.mean()) / sd) if sd > 0 else float("nan")}
    out["B"] = B
    return out


def compute_network_indices(A: np.ndarray, labels: np.ndarray) -> dict:
    """AVI, AVU, ANUI, модулярность Ньюмана и служебные поля для одного разбиения."""
    A, labels = _check(A, labels)
    return {
        "K": int(len(np.unique(labels))),
        "AVI": avi(A, labels),
        "AVU": avu(A, labels),
        "ANUI": anui(A, labels),
        "modularity_newman": modularity_newman(A, labels),
        "clusters_without_edges": clusters_without_edges(A, labels),
        "MQ": MQ_STATUS,
    }
