# HPC_PLATFORMS.md — 商业云 HPC 平台调研

> ChemMaster 设计上对接多种 HPC 平台。本文档调研主流商业云超算平台的接入方式，
> 为 `chemaster/mcp/hpc_slurm/` 中 platform adapter 接口设计提供依据。
>
> **当前 v3.0 阶段**：本毕设范围内只做**接口预留**与**本地 SLURM 占位 demo**，
> 真实商业云接入推到未来工作。
>
> 文档版本：v1.0 (2026-05-05)

---

## 1. 平台概览

国内化学/材料计算研究者常用的商业云超算平台：

| 平台 | 主体 | 主要面向 | 化学软件支持 | 接入方式 |
|---|---|---|---|---|
| **并行科技 (Paratera)** | 北京并行科技股份有限公司 | 综合 HPC | Gaussian / VASP / Materials Studio / LAMMPS / GROMACS / NAMD | SSH + SLURM/PBS |
| **鸿之微 (HZWTECH)** | 上海鸿之微信息科技有限公司 | 化学/材料/生物 | Gaussian / VASP / ORCA / NWChem / MOMAP（特色支持）| Web + SSH/CLI |
| **超算云 (E-HPC, 阿里云)** | 阿里云 | 通用 HPC | 用户自带 | OpenAPI + SSH/SLURM |
| **腾讯云 BatchCompute** | 腾讯 | 通用批处理 | 用户自带 | API + Docker |
| **中国超算互联网平台** | 国家级 | 综合 HPC | 用户自带 | Web + SSH |

ChemMaster 的目标是支持**任意提供 SSH + SLURM/PBS 的平台**，并对**鸿之微**这类原生支持 MOMAP 的平台特别优化。

---

## 2. 通用接入模式

绝大部分商业 HPC 走 **SSH + 作业调度器** 的范式：

```
用户终端
  │  SSH (paramiko)
  ▼
登录节点 (login node)
  │  scp/rsync 上传输入文件
  │  sbatch / qsub 提交作业
  │  squeue / qstat 监控状态
  ▼
计算节点 (compute node)
  │  实际运行 Gaussian / BDF / MOMAP
  │  写输出到共享存储
  ▼
登录节点
  │  scp/rsync 拉回结果
  ▼
用户终端
```

ChemMaster 的 `chemaster/mcp/hpc_slurm/` 已实现：
- paramiko SSH 连接
- sbatch / squeue / scontrol 命令封装
- rsync 上传/拉回
- 异步监控

需要补的是 **platform adapter** 抽象层：不同平台的 sbatch 参数、queue 名、计费账号、文件分区路径不同，需要一个 `PlatformConfig` 抽象。

---

## 3. 各平台详情

### 3.1 并行科技 (Paratera)

**官网**：https://www.paratera.com

**接入流程**：
1. 注册 + 实名认证
2. 通过 web 控制台申请计算节点（按机时计费）
3. 获得 SSH 登录信息：`<username>@<login_node>` + 密钥
4. 上传应用许可证（如 Gaussian g16 license）

**SLURM 提交模板（典型）**：
```bash
#!/bin/bash
#SBATCH -J chemaster_job
#SBATCH -p gpu_a100              # 队列名（平台特定）
#SBATCH -N 1
#SBATCH --ntasks-per-node=8
#SBATCH --gres=gpu:0             # CPU-only Gaussian 不需要
#SBATCH -A <account_id>          # 计费账号
#SBATCH -o stdout.%j.log
#SBATCH -e stderr.%j.log

module load gaussian/16          # 平台预装
g16 < input.gjf > output.log
```

**特色**：
- 节点资源较丰富（A100 / H100 GPU 可选）
- Gaussian 16 通常预装
- 支持 Module 系统（`module load gaussian/16`）

**接入要点**：
- 队列名（partition）需要从 `sinfo` 查询
- 账号格式平台特定（`<project_id>` 或 `<billing_id>`）
- 文件分区：home 通常有配额，scratch 用 `/work/<username>` 或类似

### 3.2 鸿之微 (HZWTECH)

**官网**：https://www.hzwtech.com

**接入流程**：
1. 注册 + 选购套餐（按算力时长计费）
2. Web 界面创建项目 / 提交作业
3. 也提供 SSH/CLI 接入（用户拉来 ssh key）

**特色**：
- **原生支持 MOMAP**（很多其他平台需要用户自装）
- 内置 Gaussian / ORCA / VASP / NWChem
- 提供 Web 控制台 + 文件管理器
- 有 BDF（北大开发，鸿之微作为合作方支持）

**SLURM 提交模板**：与并行科技类似，队列名和账号格式不同。

**接入要点**：
- Web API 文档相对完整（适合 ChemMaster 的 Web 前端集成）
- MOMAP 调用方式可能不需要用户自装
- BDF 许可文件由平台代管

### 3.3 通用 SSH+SLURM 路径

不论哪家平台，ChemMaster 的 platform adapter 需要抽象：

```python
class PlatformConfig:
    name: str                      # "paratera", "hzwtech", "generic", "local_slurm"
    hostname: str                  # SSH 登录节点
    username: str
    ssh_key_path: str | None
    
    # SLURM 参数
    partition: str                 # 队列名
    account: str | None            # 计费账号
    qos: str | None                # 服务质量
    
    # 文件路径
    workdir_template: str          # e.g. "/work/{username}/chemaster/{task_id}"
    
    # 软件 module 加载命令
    pre_commands: list[str]        # e.g. ["module load gaussian/16"]
    
    # 软件路径（如果不用 module）
    gaussian_bin: str | None       # e.g. "g16"
    bdf_bin: str | None
    momap_bin: str | None
```

---

## 4. ChemMaster 当前实现状态

### 4.1 已有

`chemaster/mcp/hpc_slurm/server.py` 347 行，已实现：
- `submit(command, hpc_config, ...)`：通过 paramiko SSH + sbatch 提交作业
- `status(job_id)`：查询作业状态
- `fetch(job_id, local_dir)`：拉回作业产物
- 基础 paramiko 包装与错误处理

### 4.2 需要补

- **PlatformConfig 抽象**：把当前散在 submit 参数里的平台特定项抽出来
- **`local_slurm` adapter**：在本地 Docker 起一个 SLURM controller，跑 demo 任务证明接口设计成立
- **`paratera` adapter（占位）**：根据本文档 §3.1 写参数，但不真实接入
- **`hzwtech` adapter（占位）**：根据本文档 §3.2 写参数，但不真实接入

### 4.3 不在毕设范围

- 真实商业云账号申请与接入测试
- 计费集成（监控用了多少机时）
- MOMAP 在鸿之微平台的特殊调用路径
- 商业云特定的安全合规（数据加密、IAM 等）

---

## 5. 论文中的描述（草稿）

§3.8 商业云 HPC 接口设计章节将这样写：

> ChemMaster 通过 PlatformConfig 抽象层支持多种 HPC 平台。底层基于 paramiko 的 SSH 通道与 SLURM 调度器命令封装已实现于 `chemaster/mcp/hpc_slurm/`，对国内主流商业云超算平台（并行科技、鸿之微等）完成了接口设计与参数调研（详见 docs/HPC_PLATFORMS.md），并提供 local_slurm 占位 adapter 通过 Docker 化 SLURM controller 演示了端到端流程的可行性。本工作未对真实商业云账号进行接入测试，相关验证留待未来工作。

§5.3 未来工作章节会补充：

> ChemMaster 的 HPC 接入未来计划在并行科技或鸿之微平台上完成端到端真实测试，特别针对鸿之微对 MOMAP 的原生支持探索更深度的集成（如 Web 提交 API 直连而非 SSH+SLURM 路径）。

---

## 6. 引用资料

调研所基于的公开资料（截至 2026-05-05）：

1. 并行科技用户手册：https://docs.paratera.com/
2. 鸿之微产品介绍：https://www.hzwtech.com/products
3. SLURM 官方文档：https://slurm.schedmd.com/sbatch.html
4. paramiko 文档：https://www.paramiko.org/

由于无真实账号，部分平台细节（队列名、账号格式、配额数值）取自上述文档与社区分享，**实际接入时需以平台最新文档为准**。

---

*本文档将在 ChemMaster v0.4 阶段（毕设之后）拓展为真实接入指南。*
