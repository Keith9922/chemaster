# MOMAP Jingti Reference Data

本目录保存师姐提供的发光速率 / 非辐射速率验证数据。

## Raw files

原始文件已复制到 `raw/`，该目录被 `.gitignore` 忽略，避免把微信临时文件和较大的 PDF 误提交。

文件类型：

- `*.com`: Gaussian 输入文件，体系为 `C24H8F8I4N2`，含 I/F/N 的有机发光分子。
- `momap用户手册-中文版鸿之微(2)(1).pdf`: MOMAP 中文用户手册。
- `6790f84e09ad915db6b8b1a5620ced01.png`: 师姐整理的速率/能量表截图。
- `87f585b1f0ea1d39983b487e5a41d319.jpg`: MOMAP 手册中跃迁偶极矩读取说明截图。

## Meaning

这组数据对应 MOMAP 发光性能计算流程的前处理和验证：

1. Gaussian 优化基态/激发态结构并计算频率。
2. 从 Gaussian log/fchk 中提取基态、激发态能量、频率、跃迁偶极矩、非绝热耦合信息。
3. MOMAP 做 EVC，生成 `evc.cart.dat`、`evc.cart.nac` 等中间文件。
4. MOMAP 用 TVCF 计算辐射速率 `kr`、内转换速率 `kic`、系间窜越速率 `kisc`。

这不是单纯的 DFT 能量 benchmark，而是“量化计算输出 -> MOMAP 速率计算”的工作流 benchmark。

## Gaussian input summary

| file | purpose | route |
|---|---|---|
| `jingti-00TDopt2(1).com` | S2 singlet TDDFT 优化 + 频率 | `B3LYP/def2svp TD(singlet,nstates=10,root=2) opt freq em=gd3bj` |
| `Tjingti-00TDopt1(1).com` | T1 triplet TDDFT 优化 + 频率 | `B3LYP/def2svp TD(triplet,nstates=3,root=1) opt freq em=gd3bj` |
| `Tjingti-00TDopt2(1).com` | T1/T2 相关输入副本，需后续和输出 log 核对 | `B3LYP/def2svp TD(triplet,nstates=3,root=1) opt freq em=gd3bj` |
| `jingti-00optnacmes1(1).com` | 非绝热耦合矩阵元输入 | `td B3LYP/def2svp em=gd3bj prop=field iop(...) nosymm` |
| `jingti-00optnacmes2(1).com` | 非绝热耦合矩阵元输入 | `td B3LYP/def2svp em=gd3bj prop=field iop(...) nosymm` |

## Validation plan

短期可做：

- 解析 Gaussian `.com`，识别任务类型、元素组成、方法/基组、charge/multiplicity。
- 根据截图中的能量差和速率值生成 reference fixture。
- 验证 ChemMaster 能正确规划这类任务，而不是实际替代 Gaussian/MOMAP。

中期可做：

- 新增 Gaussian input builder/parser MCP。
- 新增 MOMAP input builder/parser MCP。
- 从 Gaussian log 中抽取 `SCF Done`、TDDFT 激发能、`transition electric dipole moments`、频率、NACME。
- 从 MOMAP log 中抽取 `kr/kic/kisc`，与 `reference_values.yaml` 对比。

长期可做：

- 支持完整的发光性能流水线：`S0/S1/S2/T1 opt+freq -> EVC -> kr/kic/kisc -> report`。

