# Tools: PDF Structure Extraction

> 这是 ChemMaster 升级前的独立工具，目前作为 `chem.pdf` MCP 的后端被复用。
>
> **TODO Phase 5**: 把根目录的 `scripts/annotate_pdf_smiles.py` 等脚本迁移到此处，
> 并在 `chemaster/mcp/pdf/server.py` 中包装为 MCP 工具。

## 历史背景

- 原始 README 见仓库历史 commits（升级前的 `README.md`）。
- 现有产物保留在 `output/chem_pdf/` 与 `output/chemical_structure_candidates/`。
- 主要脚本在 `scripts/annotate_pdf_smiles.py` 与 `scripts/extract_chemical_structure_candidates.py`。

## 当前可用命令（Phase 5 前不变）

```bash
/opt/miniconda3/envs/chem-ocr/bin/python scripts/annotate_pdf_smiles.py /path/to/article.pdf
```

详细用法见根目录原 `scripts/` 的 docstring。

## 迁移计划（Phase 5）

1. 把 `scripts/` 移到 `tools/pdf-structure-extract/`
2. 把环境定义（chem-ocr conda env）写成 `environment.yml`
3. 在 `chemaster/mcp/pdf/server.py` 中提供 `extract_structures(pdf_path)` MCP 工具
4. tadf-pipeline skill 接入此 MCP，实现"读论文 → 自动复算 → 对比"端到端 demo
