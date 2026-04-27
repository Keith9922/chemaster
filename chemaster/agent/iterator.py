"""Iterator —— benchmark 闭环，给定测试集自动分级方法直到误差收敛。

Phase 4 核心模块。论文重点。
"""

from __future__ import annotations


class BenchmarkIterator:
    """在 benchmark 上自动迭代方法分级。

    Phase 4 实现：
    - 输入：体系列表 + 参考值 + 容差
    - 算法：
        1. 用最便宜方法（xTB / B3LYP-3c）算全部
        2. 误差超阈值的体系升级到下一级（B3LYP/6-31G* → ωB97X-D/def2-TZVP → DLPNO-CCSD(T)）
        3. 终止条件：所有体系 ε < 阈值，或最高方法用尽
    - 输出：(error vs cost) 曲线 + 每个体系的最终方法
    """

    def __init__(self) -> None:
        raise NotImplementedError("Phase 4: implement BenchmarkIterator.")
