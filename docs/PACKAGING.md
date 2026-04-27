# PACKAGING — 打包与发布流程

> Phase 7 执行。本文档描述如何把 ChemMaster 打包成可分发的产品。
> 目标：让一个不懂内部架构的化学专业研究生，5 行命令内装上能用。

---

## 0. 发布渠道矩阵

| 渠道 | 受众 | 优先级 | 安装方式 |
|---|---|---|---|
| **PyPI** (`pip install chemaster`) | Python 用户、开发者 | P0 | `pip install chemaster` |
| **conda-forge** (`conda install -c conda-forge chemaster`) | 化学/科研用户（主流） | P0 | `conda install chemaster` |
| **Homebrew tap** | macOS 用户 | P1 | `brew install chemaster/tap/chemaster` |
| **Docker Hub / GHCR** | 想完整环境的用户、CI、HPC | P1 | `docker pull ghcr.io/<user>/chemaster:latest` |
| **Claude Code Plugin** | Claude Code 用户 | P2 | `/plugin install <user>/chemaster` |
| **GitHub Release**（带预编译 wheel + 安装脚本） | 不太懂 Python 的研究生 | P0 | 一键脚本 `curl ... | bash` |

PyPI + conda-forge 是 P0 主战场；其他渠道做完前者再陆续加。

---

## 1. 版本号约定

遵循 [SemVer](https://semver.org/lang/zh-CN/)：`MAJOR.MINOR.PATCH`。

- 0.x：未 release。可以随便破坏 API。
- 1.0.0：MVP 闭环跑通 + TADF 标杆完成 + 文档完整。**这是毕设答辩前要拿到的版本号**。
- 1.x.0：新增 MCP / Skill / 后端，向后兼容。
- 1.0.x：bug 修复。
- 2.0.0：架构级变更（如换 LLM SDK）。

预发布：`1.0.0a1`（alpha）、`1.0.0b1`（beta）、`1.0.0rc1`（候选）。

每次 release 打 git tag：`v1.0.0`。

---

## 2. PyPI 发布

### 2.1 包构建

`pyproject.toml` 已用 `hatchling` 后端（见根目录）。本地构建：

```bash
pip install build twine
python -m build              # 在 dist/ 生成 .whl 和 .tar.gz
twine check dist/*           # 检查 metadata 合法性
```

### 2.2 发布步骤

```bash
# 1. 注册 PyPI 账号 + 配置 API token（一次性）
# https://pypi.org/manage/account/token/

# 2. 测试发布到 TestPyPI 验证
twine upload --repository testpypi dist/*
pip install --index-url https://test.pypi.org/simple/ chemaster

# 3. 验证无误后正式发布
twine upload dist/*
```

### 2.3 自动化（GitHub Actions）

`.github/workflows/release.yml` 见 §7。打 git tag → CI 自动构建 + 发布。

### 2.4 trusted publisher（推荐）

PyPI 现在支持 OIDC trusted publisher，比 token 安全。在 PyPI 项目设置里关联 GitHub repo 后，CI 不用配 secret。

---

## 3. conda-forge 发布

科研用户绝大多数用 conda。psi4、ORCA 等都在 conda-forge 上，**这是必须做的**。

### 3.1 提交 staged-recipes

1. fork [conda-forge/staged-recipes](https://github.com/conda-forge/staged-recipes)。
2. 在 `recipes/chemaster/meta.yaml` 写 conda recipe（PyPI 已有的话用 `pypi-package` skeleton 自动生成）：
   ```bash
   pip install grayskull
   grayskull pypi chemaster
   ```
3. 提 PR，等 conda-forge 团队 review 合并。**首次 review 通常 1-2 周**，预留时间。

### 3.2 后续维护

合并后 conda-forge 自动建一个 `conda-forge/chemaster-feedstock` 仓库。每次 PyPI 发新版，bot 会自动开 PR 升级 feedstock。你 review 合并即可。

### 3.3 依赖处理

- psi4、xTB、cclib、RDKit 都在 conda-forge 上，列入 `meta.yaml` 的 `requirements/run`。
- ORCA、BDF、Gaussian 不在 conda-forge（license 问题）→ 不写依赖，文档教用户单独装。
- 安装时 `chemaster --check-engines` 检测哪些能用，给清晰提示。

---

## 4. Homebrew tap

macOS 用户友好。但 Homebrew 不太适合 Python 包，建议做成 wrapper：

```bash
# 1. 建仓库 homebrew-tap （命名固定）
# 2. 写 Formula/chemaster.rb：
class Chemaster < Formula
  desc "AI agent for computational chemistry"
  homepage "https://github.com/<user>/chemaster"
  url "https://files.pythonhosted.org/packages/source/c/chemaster/chemaster-1.0.0.tar.gz"
  sha256 "..."
  license "MIT"

  depends_on "python@3.11"

  def install
    virtualenv_install_with_resources
  end

  test do
    system "#{bin}/chemaster", "--version"
  end
end
```

3. 用户：`brew install <user>/tap/chemaster`。

---

## 5. Docker 镜像

提供两个镜像：

### 5.1 `chemaster:slim` — 仅核心包

```dockerfile
FROM python:3.11-slim
RUN pip install chemaster
ENTRYPOINT ["chemaster"]
```

### 5.2 `chemaster:full` — 含 psi4 + xTB + ORCA（可选）

```dockerfile
FROM mambaorg/micromamba:1.5
USER root
RUN micromamba install -n base -c conda-forge -y \
    python=3.11 chemaster psi4 xtb cclib rdkit ase \
    && micromamba clean --all --yes
USER $MAMBA_USER
ENTRYPOINT ["chemaster"]
```

- ORCA / BDF / Gaussian 因 license 不打进镜像；用户挂 volume 接入。
- 构建+推送（GHCR）：

```bash
docker build -t ghcr.io/<user>/chemaster:1.0.0-full -f Dockerfile.full .
docker push ghcr.io/<user>/chemaster:1.0.0-full
```

CI 自动化见 §7。

---

## 6. Claude Code Plugin

让 Claude Code 用户可以 `/plugin install` 直接装用。

### 6.1 plugin manifest

仓库根加 `plugin.json`：

```json
{
  "name": "chemaster",
  "version": "1.0.0",
  "description": "AI agent for computational chemistry: TADF, DFT workflows, HPC integration",
  "author": "<user>",
  "homepage": "https://github.com/<user>/chemaster",
  "skills": [
    "chemaster/skills/tadf-pipeline",
    "chemaster/skills/opt-freq",
    "chemaster/skills/tddft",
    "chemaster/skills/soc",
    "chemaster/skills/conformer",
    "chemaster/skills/ts-search",
    "chemaster/skills/pes-scan",
    "chemaster/skills/pka",
    "chemaster/skills/dlpno-ccsdt",
    "chemaster/skills/solvation"
  ],
  "mcp_servers": {
    "chem-const":             {"command": "chemaster-mcp", "args": ["const"]},
    "chem-io-ase":            {"command": "chemaster-mcp", "args": ["io_ase"]},
    "chem-calc-psi4":         {"command": "chemaster-mcp", "args": ["calc_psi4"]},
    "chem-calc-orca":         {"command": "chemaster-mcp", "args": ["calc_orca"]},
    "chem-calc-bdf":          {"command": "chemaster-mcp", "args": ["calc_bdf"]},
    "chem-calc-xtb":          {"command": "chemaster-mcp", "args": ["calc_xtb"]},
    "chem-parse-cclib":       {"command": "chemaster-mcp", "args": ["parse_cclib"]},
    "chem-analysis-multiwfn": {"command": "chemaster-mcp", "args": ["analysis_multiwfn"]},
    "chem-viz":               {"command": "chemaster-mcp", "args": ["viz"]},
    "chem-hpc-slurm":         {"command": "chemaster-mcp", "args": ["hpc_slurm"]},
    "chem-kb":                {"command": "chemaster-mcp", "args": ["kb"]},
    "chem-pdf":               {"command": "chemaster-mcp", "args": ["pdf"]}
  },
  "commands": [
    {"name": "tadf",          "description": "Run full TADF emitter screening pipeline"},
    {"name": "opt-freq",      "description": "Geometry optimization with frequency confirmation"},
    {"name": "scan",          "description": "Potential energy surface scan"}
  ]
}
```

### 6.2 marketplace 提交

提到 [Claude Code plugin marketplace](https://docs.claude.com/en/docs/claude-code/plugins) 后，用户能直接 `/plugin install <user>/chemaster`。

---

## 7. GitHub Actions（CI/CD）

### 7.1 `.github/workflows/ci.yml` — 每次 push/PR

```yaml
name: CI
on: [push, pull_request]
jobs:
  test:
    runs-on: ${{ matrix.os }}
    strategy:
      matrix:
        os: [ubuntu-latest, macos-latest]
        python: ["3.11", "3.12"]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "${{ matrix.python }}" }
      - run: pip install -e ".[dev]"
      - run: ruff check chemaster tests
      - run: pytest tests/unit -v
```

### 7.2 `.github/workflows/integration.yml` — 慢测，每周 + release 前

```yaml
name: Integration
on:
  schedule: [{cron: "0 3 * * 1"}]   # 每周一 UTC 03:00
  workflow_dispatch:
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: conda-incubator/setup-miniconda@v3
        with: { auto-update-conda: true, python-version: "3.11" }
      - run: conda install -c conda-forge psi4 xtb cclib rdkit ase
      - run: pip install -e ".[dev]"
      - run: pytest tests/integration -v --tb=short
```

### 7.3 `.github/workflows/release.yml` — 打 tag 时发布

```yaml
name: Release
on:
  push:
    tags: ["v*"]
jobs:
  pypi:
    runs-on: ubuntu-latest
    permissions:
      id-token: write    # for OIDC trusted publishing
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.11" }
      - run: pip install build
      - run: python -m build
      - uses: pypa/gh-action-pypi-publish@release/v1

  docker:
    runs-on: ubuntu-latest
    permissions: { packages: write }
    steps:
      - uses: actions/checkout@v4
      - uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      - uses: docker/build-push-action@v5
        with:
          push: true
          tags: |
            ghcr.io/${{ github.repository }}:${{ github.ref_name }}
            ghcr.io/${{ github.repository }}:latest
```

### 7.4 `.github/workflows/docs.yml` — 文档站

用 [mkdocs-material](https://squidfunk.github.io/mkdocs-material/) 把 `docs/` 自动构建到 GitHub Pages：

```yaml
name: Docs
on:
  push:
    branches: [main]
jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: pip install mkdocs-material
      - run: mkdocs gh-deploy --force
```

---

## 8. 预发布 checklist（每个 release 前过一遍）

- [ ] 版本号在 `pyproject.toml` 与 `chemaster/__init__.py` 一致
- [ ] `CHANGELOG.md` 更新本次变更
- [ ] `tests/unit` 全绿
- [ ] `tests/integration` 全绿（手动跑或等 weekly CI）
- [ ] `chemaster --version` 输出正确
- [ ] `chemaster --check-engines` 在干净环境（Docker）能跑
- [ ] H2O smoke test 通过（`chemaster eval examples/h2o.yaml`）
- [ ] 文档无死链（`mkdocs build --strict`）
- [ ] README 安装命令最新
- [ ] git tag 已打且 push 到远端
- [ ] GitHub Release notes 写清"亮点 / 破坏性变更 / 修复"

---

## 9. 一键安装脚本（给非 Python 背景的用户）

`install.sh`（放在仓库根，README 引导）：

```bash
#!/usr/bin/env bash
set -euo pipefail

if ! command -v conda &>/dev/null; then
  echo "请先装 Miniconda: https://docs.conda.io/en/latest/miniconda.html"
  exit 1
fi

conda create -n chemaster python=3.11 -y
conda install -n chemaster -c conda-forge chemaster psi4 xtb cclib rdkit ase -y
conda run -n chemaster chemaster --check-engines

cat <<EOF

✅ ChemMaster 装好了。

激活环境：
  conda activate chemaster

第一次运行：
  chemaster init      # 配置 LLM API key
  chemaster           # 进入 TUI

EOF
```

用户：

```bash
curl -sSL https://raw.githubusercontent.com/<user>/chemaster/main/install.sh | bash
```

---

## 10. 发布后维护

- **issue triage**：标签 `bug` / `enhancement` / `chemistry-question` / `good-first-issue`。
- **CHANGELOG.md** 用 [Keep a Changelog](https://keepachangelog.com/) 风格。
- **bug fix → patch release**：周期 1-2 周。
- **新功能 → minor release**：周期 4-8 周。
- **每个 release 在 README 顶部更新 badge**：PyPI 版本、CI 状态、覆盖率。

---

## 11. 论文与学术引用

毕设答辩后准备：

- 在 GitHub README 加 `CITATION.cff`。
- 投 [JOSS](https://joss.theoj.org/) (Journal of Open Source Software) 拿正式 DOI 引用。
- 在 [Zenodo](https://zenodo.org/) 上为每个 release 自动 archive，拿 DOI。

---

*文档版本：v1.0 (2026-04)。*
