# SETUP — 开发环境搭建

> 第一次接手项目读这个。预期 30-45 分钟搭好。

---

## 0. 系统要求

| 系统 | 状态 |
|---|---|
| macOS (Apple Silicon / Intel) | ✓ 完整支持 |
| Linux (Ubuntu 22+, RHEL 8+) | ✓ 完整支持 |
| Windows (WSL2) | ✓ 经 WSL2 |
| Windows native | ✗ 不支持 |

最低硬件：8 GB 内存（实际跑 DFT 推荐 16 GB+）、20 GB 磁盘。

---

## 1. 必要工具

```bash
# 1. 装 Miniconda（如果没有）
# macOS Apple Silicon:
curl -L https://repo.anaconda.com/miniconda/Miniconda3-latest-MacOSX-arm64.sh | bash
# macOS Intel:
curl -L https://repo.anaconda.com/miniconda/Miniconda3-latest-MacOSX-x86_64.sh | bash
# Linux x86_64:
curl -L https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh | bash

# 2. 装 git（macOS: xcode-select --install；Linux: 包管理器）
git --version

# 3. 装 uv（推荐，比 pip 快很多；可选）
curl -LsSf https://astral.sh/uv/install.sh | sh
```

---

## 2. 克隆 + 创建环境

```bash
git clone <repo-url> chemaster
cd chemaster

# 创建专用 conda 环境
conda create -n chemaster python=3.11 -y
conda activate chemaster

# 装核心依赖（开发模式）
pip install -e ".[dev]"
```

---

## 3. 装计算引擎（按需）

### 3.1 psi4（Phase 1 必需）

```bash
conda install -c conda-forge psi4 -y
psi4 --version    # 应输出 1.x
```

### 3.2 xTB（Phase 1 必需，构象搜索）

```bash
conda install -c conda-forge xtb crest -y
xtb --version
crest --version
```

### 3.3 ORCA（Phase 2，学术免费但要单独下载）

1. 注册 https://orcaforum.kofo.mpg.de/
2. 下载 ORCA 6.x（学术免费）
3. 解压后将路径加入 PATH：
   ```bash
   echo 'export PATH="$HOME/orca_6_0_0:$PATH"' >> ~/.zshrc
   echo 'export OPENMPI_BIN="$HOME/orca_6_0_0/openmpi"' >> ~/.zshrc   # 视情况
   source ~/.zshrc
   orca --version
   ```

### 3.4 BDF（Phase 2，国产，学术免费）

1. 在 http://182.92.69.169:7226/bdf/ 注册下载
2. 解压并设置：
   ```bash
   export BDFHOME=$HOME/bdf-pkg-pro
   export PATH=$BDFHOME/bin:$PATH
   ```
3. 测试：`bdfdrv.py --help`

### 3.5 MultiWFN（Phase 2，波函数分析，国产免费）

1. http://sobereva.com/multiwfn/ 下载
2. 解压加 PATH：
   ```bash
   export Multiwfnpath=$HOME/Multiwfn_3.8
   export PATH=$Multiwfnpath:$PATH
   ```

### 3.6 跳过商业软件

Gaussian / VASP 不在毕设范围。如果实验室有 license，可以在 `~/.chemaster/config.yaml` 里指定路径，`chem.calc.gaussian` MCP 在 Phase 5 才会写。

---

## 4. 配置 LLM API

```bash
mkdir -p ~/.chemaster
cp config.example.yaml ~/.chemaster/config.yaml
$EDITOR ~/.chemaster/config.yaml
```

填入：

```yaml
llm:
  provider: anthropic    # 或 openai / qwen / deepseek / local
  api_key: sk-ant-...    # 从 https://console.anthropic.com 拿
  model: claude-sonnet-4-6
```

或用环境变量（推荐）：

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

---

## 5. 检查环境

```bash
chemaster --check-engines
```

输出示例：

```
ChemMaster 0.1.0 environment check
  ✓ Python 3.11.7
  ✓ psi4 1.9.1
  ✓ xtb 6.7.0
  ✓ crest 3.0.1
  ⚠ orca: not found (optional, Phase 2)
  ⚠ bdf: BDFHOME not set (optional, Phase 2)
  ⚠ multiwfn: not found (optional, Phase 2)
  ✓ Anthropic API: connected
```

---

## 6. 跑 smoke test

```bash
pytest tests/unit -v          # 应全绿
pytest tests/integration -v   # 真跑 psi4，~30s
```

---

## 7. 启动 TUI

```bash
chemaster
```

进入 REPL 后试：

```
> 算 H2O 的能量
```

应该看到 Plan → Confirm → Execute 三段式。

---

## 8. 开发常用命令

```bash
# 装新依赖
pip install -e ".[dev]"

# 跑测试
pytest tests/unit                              # 快测
pytest tests/integration                       # 慢测，真跑软件
pytest tests/unit -k "test_const"              # 单文件
pytest --cov=chemaster --cov-report=html       # 覆盖率

# 静态检查
ruff check chemaster tests                     # lint
ruff format chemaster tests                    # 格式化

# 跑单个 MCP server（调试用）
python -m chemaster.mcp.const

# 列出所有 skills
chemaster skills list

# 看 KB
chemaster kb list
chemaster kb show functionals

# 清理 runs/
chemaster clean --older-than 30d
```

---

## 9. IDE 设置

### VS Code

`.vscode/settings.json`（仓库内已含模板）：

```json
{
  "python.defaultInterpreterPath": "${env:CONDA_PREFIX}/bin/python",
  "python.testing.pytestEnabled": true,
  "[python]": { "editor.defaultFormatter": "charliermarsh.ruff" }
}
```

推荐插件：Python、Pylance、Ruff、YAML、Markdown All in One。

### PyCharm

把 `chemaster` 标记为 Source Root；conda 环境作为 Python interpreter。

---

## 10. 常见环境问题

### 10.1 conda solver 极慢
```bash
conda install -n base conda-libmamba-solver
conda config --set solver libmamba
```

### 10.2 `psi4: command not found`
没 activate 环境。`conda activate chemaster`。

### 10.3 macOS 上 ORCA 跑不了
ORCA 不官方支持 macOS arm64。建议在 Docker 里跑，或在 Linux/HPC 上跑。Phase 2 之前用不到。

### 10.4 xTB 提示 OMP_NUM_THREADS
```bash
export OMP_NUM_THREADS=4
```

### 10.5 RDKit 装不上
Python 3.11 + conda-forge 通常无问题。Python 3.12 偶有 wheel 缺失。坚持 3.11。

### 10.6 中文路径
**绝对不要**把仓库放在含中文/空格/iCloud 同步的路径下。psi4/ORCA 都会出问题。

---

## 11. HPC 配置（Phase 3 才需要）

参考 [`docs/PITFALLS.md`](PITFALLS.md) §4。

`~/.chemaster/config.yaml`：

```yaml
hpc:
  default_cluster: school
  clusters:
    school:
      type: slurm
      host: hpc.your-school.edu.cn
      user: <your-username>
      ssh_key: ~/.ssh/id_rsa
      proxy_jump: <jumphost>      # 如果需要
      remote_work_dir: /scratch/<user>/chemaster-runs
      pre_run_hook: |
        module load orca/6.0
        module load openmpi/4.1
      partitions:
        - name: cpu
          max_walltime: 72:00:00
          cpus_per_node: 32
          memory_per_node_gb: 128
```

---

## 12. 第一次开发会话清单

- [ ] 装好 Miniconda
- [ ] clone 仓库
- [ ] `conda activate chemaster && pip install -e ".[dev]"`
- [ ] `chemaster --check-engines` 至少 psi4 + xTB ✓
- [ ] `pytest tests/unit` 全绿
- [ ] 读 [`CLAUDE.md`](../CLAUDE.md) 一遍
- [ ] 读 [`docs/ROADMAP.md`](ROADMAP.md) §4 当前阶段
- [ ] 读 [`docs/PITFALLS.md`](PITFALLS.md) 一遍（头脑里建立"踩坑预警"）
- [ ] 读 [`docs/MCP_GUIDE.md`](MCP_GUIDE.md) 或 [`docs/SKILLS_GUIDE.md`](SKILLS_GUIDE.md)（取决于要写哪类）
- [ ] 在 `chemaster/` 找到要写的目录
- [ ] 开始写 + 测

---

*文档版本：v1.0 (2026-04)。*
