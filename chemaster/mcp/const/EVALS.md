# chem.const evals

## 应该触发的

| Prompt | 期望 tool | 期望参数 |
|---|---|---|
| 普朗克常数是多少？ | get_constant | name=planck or h |
| 1 Hartree 等于多少 kcal/mol？ | convert_unit | from=hartree, to=kcal/mol |
| 把 0.5 Bohr 转成 Angstrom | convert_unit | from=bohr, to=angstrom |
| 阿伏伽德罗常数 | get_constant | name=NA or avogadro |
| 玻尔兹曼常数的值 | get_constant | name=kb |

## 不应该触发的

| Prompt | 不应触发 | 原因 |
|---|---|---|
| 算 H2O 的能量 | get_constant | 应路由到 opt-freq skill / chem.calc.psi4 |
| 优化苯的几何 | (任意 const tool) | 同上 |
| H2O 的偶极矩是多少 | (任意 const tool) | 这是 calc 任务，不是查常数 |
