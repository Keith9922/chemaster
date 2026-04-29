---
name: soc
version: 0.1.0
description: 自旋轨道耦合（SOC）矩阵元计算 — 优先用 BDF (X2C)
when_to_use: |
  - tadf-pipeline 调用：算 <S1|H_SO|T1>。
  - 需要相对论效应（重元素）。
  - 用户问 SOC、自旋轨道、ISC / RISC 速率的耦合矩阵元。
when_not_to_use: |
  - 纯有机轻元素体系且只看激发态能量：用 tddft 即可。
required_mcps:
  - chem.calc.bdf
  - chem.calc.orca   # 备用（精度略差但更易装）
estimated_time: 10 min - 2 hours
---

# Spin-Orbit Coupling

## 后端选择

| 软件 | 方法 | 精度 | 速度 |
|---|---|---|---|
| **BDF (默认)** | X2C-TDA | ★★★★★ | ★★★ |
| ORCA | RI-SOMF | ★★★ | ★★★★ |
| psi4 | 不支持 | — | — |

**默认走 BDF**，没有 BDF 时回退 ORCA 并在报告里注明精度警告。

## 默认参数

- engine: bdf
- relativistic: X2C
- 方法: ωB97X-D / def2-TZVP-J （BDF 兼容）
- states: ['S1', 'T1']

## 流程

1. 检查 BDF 可用性（chem.calc.bdf.check_env）
2. 准备输入（X2C-TDA SOC 关键字）
3. 提交计算
4. 解析 SOC 矩阵元（cm⁻¹）
5. 报告各 (Sn, Tm) 配对的 |H_SO|

## 失败模式

| 问题 | 处理 |
|---|---|
| BDF 未装 | 回退 ORCA RI-SOMF；报告里写"精度受限" |
| 收敛失败 | 用 opt-freq 的 SCF 恢复策略 |
| BDF license 缺失 | 给清晰错误信息引用安装文档 |

## TODO Phase 2

详细展开 + BDF 输入文件模板。
