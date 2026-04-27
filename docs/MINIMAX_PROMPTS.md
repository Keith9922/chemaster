# MINIMAX_PROMPTS — Phase 1 前 10 步交给 MiniMax 的 prompt 集

> 给 MiniMax 2.7（或同档非 Claude 模型）调好的可直接复制 prompt。
> 用法见 [`KICKOFF.md`](KICKOFF.md) §A-§E。
> 每个 prompt 自包含：开新会话贴一个，跑完关掉再开下一个。

---

## 总流程

```
Prompt 0   环境验证（一次性）
Prompt 1   chem.io.ase MCP
Prompt 2   chem.parse.cclib MCP
Prompt 3   chem.calc.xtb MCP
Prompt 4   chem.calc.psi4: single_point
Prompt 5   chem.calc.psi4: optimize
Prompt 6   chem.calc.psi4: frequency
Prompt 7   chem.viz MCP
Prompt 8   Planner 硬编码 H2O 版
Prompt 9   Executor 最简版
Prompt 10  H2O 端到端 integration test (Phase 1 验收)
```

每完成一步：
1. MiniMax 输出代码 → 你贴回 Claude 让审 → Claude 修正后给最终版
2. 你保存到文件 + 跑 pytest
3. 把 pytest 结果贴回 Claude → 通过则 commit
4. 关掉 MiniMax 会话，开新会话做下一步

---

## Prompt 0 — 环境验证

```
ChemMaster 项目首次环境验证。

请按顺序执行，每完成一步告诉我结果：

1. 检查 conda 是否在 PATH：conda --version
2. 在仓库根目录 /Users/ronggang/code/funcode/chemaster/ 下：
   conda create -n chemaster python=3.11 -y
   conda activate chemaster
   pip install -e ".[dev]"
3. 安装计算引擎：
   conda install -c conda-forge psi4 xtb cclib rdkit ase -y
4. 跑：chemaster --check-engines
5. 跑：pytest tests/unit -v

期望：步骤 5 的 4 个测试文件全部通过。
若任何步骤报错，停下来把完整错误信息发给我，不要自己尝试修复。
```

---

## Prompt 1 — chem.io.ase MCP

见仓库 docs/MINIMAX_PROMPTS_FULL.md（或 Claude 会话历史）。
内容：实现 smiles_to_xyz / xyz_to_smiles / parse_geometry / lookup_by_name 四个 tool。

---

## Prompt 2 — chem.parse.cclib MCP

实现 parse_output / extract_orbitals 两个 tool，用 cclib.io.ccread。

---

## Prompt 3 — chem.calc.xtb MCP

subprocess 调用 xtb。先实现 single_point 与 optimize。

---

## Prompt 4-6 — chem.calc.psi4 MCP（分三次）

- Prompt 4: single_point
- Prompt 5: optimize（不动 single_point）
- Prompt 6: frequency（不动前两个）

分三步是因为 psi4 MCP 是核心，每步都需要细致 review；一次写 3 个 tool MiniMax 容易乱。

---

## Prompt 7 — chem.viz MCP

plot_3d (matplotlib + ase) / plot_ir（高斯展宽 PNG）。

---

## Prompt 8 — Planner 硬编码 H2O 版

不接 LLM，仅识别 "h2o" / "水" / "water" 关键词，返回完整 Plan 对象。

---

## Prompt 9 — Executor 最简版

按 ApprovedPlan 顺序调 MCP，自动把上一步 geometry 注入下一步参数，
写产物到 runs/<task-id>/，校验 confirm_token 非空。

---

## Prompt 10 — H2O 端到端 integration test

@pytest.mark.integration 真跑 psi4，断言：
- final_energy ∈ (-76.5, -76.3) Hartree
- n_imaginary == 0
- 3 个频率都 > 1500 cm^-1
- 端到端耗时 < 5 min

跑通即 Phase 1 MVP 完成。

---

## 监控 Checklist（每步 review 时）

每次 MiniMax 给你代码后，把它贴给 Claude，Claude 用以下清单审：

- [ ] 仿照 chem.const 的格式（imports, mcp 实例, @mcp.tool, main()）
- [ ] 三段式返回 {ok, result/error_code, warnings, meta}
- [ ] 物理量带 unit 字段
- [ ] 函数签名严格 typed，无 **kwargs
- [ ] 错误转 error_code，不抛 Exception 给 LLM
- [ ] docstring 含 when_to_use / Args / Returns / Examples
- [ ] 没硬编码绝对路径、API key
- [ ] 没用 print()，用 logging
- [ ] 测试覆盖 1 正例 + ≥1 反例（有具体数值断言，不是 assert True）
- [ ] PITFALLS 相关条目都已应对（看 prompt 中提到的 §X.Y）

---

*文档版本：v1.0 (2026-04)。前 10 步完成后追加 Phase 2 prompt 集。*
