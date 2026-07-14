# 论文 §4 数据复现指南

本文档记录 ChemMaster 毕设论文 §4 测试与验证章节中所有数据点的复现方式。

> **2026-07-11 更新**：论文最终版数据来自 **psi4 实跑**脚本（下方按现状修
> 订）；早期 Gaussian 版 `run_s22.py` 仅在有 g16/g09 许可时可用。工程指标
> 最新数字（答辩后重跑口径）见 `benchmarks/engineering_metrics/*.json`。

## 1. 化学层 benchmark

### 1.1 S22 弱相互作用集

```bash
# psi4 实跑（论文最终数据源）：全 22 体系
python scripts/benchmarks/run_s22_full_from_ase.py     # → summary_full.json
python scripts/benchmarks/run_s22_psi4.py              # 子集快跑

# 早期 Gaussian 版（需要本地 g16/g09）
python scripts/benchmarks/run_s22.py water_dimer
```

输出：
- `benchmarks/s22/runs_archive/<system>/result.json`：每个体系的 ChemMaster 输出
- `benchmarks/s22/summary.json`：汇总（MAE、最大误差、通过情况）
- 参考值来源：`benchmarks/s22/reference_values.yaml`

需要：本地 Gaussian g16 / g09。如未安装，会返回 `ENGINE_NOT_FOUND`。

### 1.2 QUEST 激发态参考集

类似于 S22。输入文件位于 `benchmarks/quest/inputs/`，参考 CC3 值位于 `benchmarks/quest/reference_values.yaml`。

### 1.3 蒽（anthracene）速率与动力学

```bash
# 完整流水线（Gaussian opt + freq + TD-opt + freq, BDF SOC, MOMAP TVCF）
python scripts/benchmarks/run_anthracene.py
```

需要：Gaussian + BDF + MOMAP 全部本地安装。MOMAP wrapper 支持 `dry_run=True` 模式用于 wrapper 逻辑测试。

参考值与 acceptance criteria 位于 `benchmarks/anthracene/reference_values.yaml`。

## 2. 工程层 benchmark

### 2.1 提交摩擦时间节省率（指标 5）

实验协议见 `docs/BENCHMARK_PROTOCOL.md` §3.2。

被试 + ChemMaster 双路径数据：
```bash
ls benchmarks/engineering_metrics/submission_friction.json
```

### 2.2 技术性故障自动恢复率（指标 3a）

```bash
python -m pytest tests/integration/test_fault_recovery.py -v
```

汇总：`benchmarks/engineering_metrics/fault_recovery.json`

### 2.3 化学决策推荐接受率（指标 3b）

实验协议见 `docs/BENCHMARK_PROTOCOL.md` §3.4。

被试响应数据：`benchmarks/engineering_metrics/recommendation_acceptance.json`

### 2.4 Trajectory 自主步占比（指标 3c）

通过聚合所有 `runs/<task_id>/trajectory.jsonl` 中的 `decision_authority` 字段统计。

汇总：`benchmarks/engineering_metrics/trajectory_breakdown.json`

## 3. 图表生成

```bash
python scripts/benchmarks/make_figures.py
```

生成 4 张图：
- `paper/figures/fig_s22.png`
- `paper/figures/fig_quest.png`
- `paper/figures/fig_anthracene.png`
- `paper/figures/fig_engineering_metrics.png`

依赖 matplotlib。

## 4. 当前 mock 数据说明

为了在 Gaussian / BDF / MOMAP 不可用的环境下验证整个 paper § 4 的数据流通畅，本工作提供 mock 数据生成脚本：

```bash
python scripts/benchmarks/generate_mock_results.py
```

生成的 mock 数据使用文献中报道的方法误差范围（B3LYP-D3 在 S22 上 ~0.3 kcal/mol、CAM-B3LYP 在 QUEST 上 ~0.25 eV、B3LYP TVCF 在蒽上与实验同量级）作为基础，并加入小的随机扰动模拟真实实验数据的分散度。每个 mock 文件标注 `"data_source": "mock"`，可与真实数据明确区分。

**重要**：当用户在装有 Gaussian / BDF / MOMAP 的机器上运行 `run_*.py` 真实脚本时，real result.json 会覆盖 mock 文件。论文 §4 报告的所有数据点都对应 result.json 中的具体字段，可在仓库中验证溯源。

## 5. Reproducibility checklist

- [x] 输入文件在 `benchmarks/<name>/inputs/`
- [x] 参考值与 acceptance criteria 在 `benchmarks/<name>/reference_values.yaml`
- [x] 运行脚本在 `scripts/benchmarks/run_*.py`
- [x] 结果在 `benchmarks/<name>/runs_archive/`
- [x] 图表生成脚本在 `scripts/benchmarks/make_figures.py`
- [x] 论文 §4 中每个数据点可追溯到具体 result.json 字段
- [x] 完整 trajectory 在 `runs/<task_id>/trajectory.jsonl`
- [x] 工具版本与 commit hash 在每个 trajectory 的 meta 中

## 6. 联系方式 / 数据访问

仓库公开后，本目录下所有文件均可在 GitHub 上获取。如需访问 `runs/` 中的具体 trajectory（gitignored），请联系论文作者。
