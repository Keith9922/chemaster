# Benchmarks

> Phase 4 的核心数据集。

## tadf-literature/

5-10 个已发表的 TADF 分子，用于验证 `tadf-pipeline` skill 的精度。

每个 `.yaml` 文件含：

```yaml
name: 4CzIPN
smiles: <SMILES>
geometry: |
  <可选 xyz 块>
charge: 0
multiplicity: 1
literature_values:
  delta_E_ST_eV: 0.10
  oscillator_f_S1: 0.06
  krisc_per_s: 5.0e+6
  source: "Uoyama et al., Nature 2012, 492, 234. DOI: 10.1038/nature11687"
```

## gmtkn55-subset/

GMTKN55 的精选子集（W4-11、BH9 等），用于通用精度 benchmark + Iterator 模块。

数据下载脚本（待 Phase 4 加）：

```bash
chemaster benchmarks fetch gmtkn55-subset
```

## 运行 benchmark

```bash
chemaster eval benchmarks/tadf-literature/4CzIPN.yaml
chemaster benchmarks run --suite tadf-literature
```
