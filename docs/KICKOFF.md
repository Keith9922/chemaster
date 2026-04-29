# KICKOFF — 新会话启动指南

> 每次开新会话前读这个。给"自己"或后续模型用。
> 包含可直接复制粘贴的 prompt 模板。
>
> **核心原则**：约束 LLM 的自由度。永远让它**先读文档、再做一件小事、用 pytest 验证**，不允许"我觉得我做完了"。
>
> ⭐ **V2 注意（2026-04-29）**：架构已重构。新会话开始时先 `cat CLAUDE.md` 看 §2.1（五层）和 §11（当前状态）；旧的 V1 三段式 Planner/Executor 仍然在 `agent/` 下作为兼容层，但**主路径走 ChemAgent + tool-use loop**。看 `tests/integration/test_agent_real_psi4.py` 是 V2 的端到端范例。

---

## 0. 通用开场白（每次新会话第一段）

复制下面这段，开新会话时**第一句话**就贴进去。无论用 Claude Code、Cowork、还是其他 IDE 集成。

```
你接手的是 ChemMaster 项目（chemaster/ 仓库）。在做任何事之前：

1. Read /Users/ronggang/code/funcode/chemaster/CLAUDE.md（完整读完）
2. Read /Users/ronggang/code/funcode/chemaster/docs/PITFALLS.md（重点看 §1 §2 §5）
3. Read /Users/ronggang/code/funcode/chemaster/docs/ROADMAP.md 的 "当前 Phase" 章节
4. 读完后用一段话**复述**：本项目是什么、当前在哪个 Phase、下一步该做什么。

然后等我下一条指令，不要自己开始动代码。
```

> 等模型回复复述（5-10 句话）。如果复述里漏了关键约定（不让 LLM 算数 / Skill 与 MCP 分工 / Plan-Confirm-Execute），让它再读一遍。**复述不通过不开始动手**。

---

## 1. 场景化启动 prompt

### 1.1 场景 A — "继续往下做"

```
按 CLAUDE.md §8 第 N 项推进。

约束：
- 一次只做这一项，做完就停。
- 写完代码后跑：pytest tests/unit/test_<对应名> -v —— 必须全绿。
- 不要去改其他文件（除非 PITFALLS 明确要求）。
- 不要去重构现有代码。
- 写完 commit：feat(<scope>): <subject>
```

把 `N` 换成 1-10 的具体数字（CLAUDE.md §8 列出了 1-10 步）。

### 1.2 场景 B — "写一个新 MCP server"

```
任务：实现 chemaster/mcp/<name>/server.py。

执行步骤（**严格按顺序**）：

1. Read /Users/ronggang/code/funcode/chemaster/docs/MCP_GUIDE.md
2. Read /Users/ronggang/code/funcode/chemaster/docs/PITFALLS.md（重点 §2 §3 §5）
3. Read /Users/ronggang/code/funcode/chemaster/chemaster/mcp/const/server.py（参考模板）
4. Read /Users/ronggang/code/funcode/chemaster/chemaster/mcp/<name>/README.md（工具范围）
5. 写 server.py，遵循 MCP_GUIDE 的 §3-§7 全部约定：
   - 入参严格 typed，无 **kwargs
   - 返回 {ok, result, warnings, meta} 三段式
   - 物理量带 unit 字段
   - 错误转 error_code，不抛异常
   - docstring 含 when_to_use / when_not_to_use / examples / 常见 error_codes
6. 写对应 tests/unit/test_<name>.py（参考 tests/unit/test_constants.py）
7. 跑 pytest tests/unit/test_<name>.py -v —— 必须全绿
8. 更新 chemaster/mcp/<name>/README.md 的 Error codes 节
9. 写完 commit：feat(mcp/<name>): implement <tools-list>

完成定义：pytest 全绿 + README 有内容 + commit 落地。
```

### 1.3 场景 C — "写一个新 Skill"

```
任务：完善 chemaster/skills/<name>/SKILL.md。

执行步骤：

1. Read /Users/ronggang/code/funcode/chemaster/docs/SKILLS_GUIDE.md
2. Read /Users/ronggang/code/funcode/chemaster/chemaster/skills/opt-freq/SKILL.md（参考模板）
3. 如果是 tadf-pipeline 相关：Read /Users/ronggang/code/funcode/chemaster/docs/TADF_PIPELINE.md
4. 按 SKILLS_GUIDE §3 模板补全 SKILL.md：
   - frontmatter 完整（name / description / when_to_use / when_not_to_use / required_mcps）
   - 详细步骤含具体 MCP 调用与参数
   - 失败模式表
   - 与其他 skill 的边界
5. 在 chemaster/kb/rules/workflows.yaml 登记本 skill
6. 写完 commit：feat(skill/<name>): complete SKILL.md

不要写代码，只写 Markdown。
```

### 1.4 场景 D — "调试一个具体错误"

```
环境出现以下错误：
<贴完整错误信息 / stack trace>

执行步骤：

1. Read /Users/ronggang/code/funcode/chemaster/docs/PITFALLS.md
2. 在 PITFALLS 里找匹配的坑条目（应该写出第几条）
3. 如果找不到：在 PITFALLS 末尾加一条新坑（按 §11 格式）
4. 按坑里的"✅ 正确做法"修复
5. 跑相关 pytest 验证修复
6. commit：fix(<scope>): <subject> (refs PITFALLS §X.Y)
```

### 1.5 场景 E — "推进整个 Phase"

```
开始 Phase N（参见 docs/ROADMAP.md §N）。

执行步骤：

1. Read CLAUDE.md
2. Read docs/ROADMAP.md 的 §"Phase N"
3. 用 TodoWrite 把该 Phase 的所有 [ ] 待办项变成 todo
4. 按依赖顺序逐个做（每做一个就跑 pytest 验证）
5. 每完成一个 todo 就 commit
6. 不要跨 Phase 推进；本 Phase 验收标准达到就停

每开始一个 todo 前用一句话告诉我"现在开始做 X"，不要批量跑。
```

### 1.6 场景 F — "MVP 第一次跑通 H2O"

```
目标：跑通端到端 H2O opt+freq 闭环。

前置：chem.const、chem.io.ase、chem.calc.psi4、chem.parse.cclib 都已实现。

执行步骤：

1. Read CLAUDE.md §8
2. 写 chemaster/agent/planner.py 的硬编码版（识别 H2O 关键词 → 出 opt+freq Plan）
3. 写 chemaster/agent/executor.py 的最简版（按 Plan 顺序调 MCP）
4. 写 tests/integration/test_h2o_e2e.py
5. 跑 pytest tests/integration/test_h2o_e2e.py -v --tb=short
6. 跑完输出 runs/<task-id>/report.md，cat 给我看
7. commit：feat(agent): H2O end-to-end smoke test passing

不要做任何 Phase 1 计划外的事。
```

---

## 2. 给笨模型的"硬规矩"（每次会话都贴）

如果用 Haiku、本地小模型、或经常走偏的 Sonnet，可以把以下规则附在场景 prompt 后面：

```
硬规矩（违反任何一条立刻停下来问我）：

1. 不许跳过 Read 步骤直接写代码。
2. 不许同时改超过 3 个文件。
3. 不许写 print() 调试，用 logging。
4. 不许在代码里硬编码任何路径、API key、绝对路径。
5. 不许 import 没在 pyproject.toml 中声明的依赖。
6. 不许写"# TODO"或"# FIXME"在已 commit 的代码里 ——
   如果不能完成就停下来问我，不许半成品 commit。
7. 不许"我觉得我做完了"。完成 = pytest 全绿 + commit 落地。
8. 不许重构本任务范围以外的代码（哪怕你觉得它很烂）。
9. 不许把 LLM 当计算器 —— 任何浮点运算走 chemaster.kb.formulas。
10. 不许让 LLM "自由发挥" 选基组/泛函 —— 必须查 kb/rules。
```

---

## 3. 验收 / 完成标准（不允许模型自己判断）

每个常见任务的"完成"由可执行命令定义。模型必须跑通后才能宣称 done：

| 任务 | 完成命令 |
|---|---|
| 装环境 | `chemaster --check-engines` 至少 psi4 + xtb ✓ |
| 新 MCP 完成 | `pytest tests/unit/test_<name>.py -v` 全绿 + `chemaster mcps list` 含本 server |
| 新 Skill 完成 | `chemaster skills list` 含本 skill + `chemaster skills route --prompt "<触发例>"` 命中 |
| 新公式模块 | `pytest tests/unit/test_<module>.py -v` 全绿 |
| MVP 闭环 | `pytest tests/integration/test_h2o_e2e.py` 全绿 + report.md 含能量数字 |
| 一个 Phase 完成 | ROADMAP §对应 Phase 的"验收标准"全 ✓ |
| 准备 release | `pytest && ruff check && twine check dist/*` 全绿 |

---

## 4. "复述检查点"（笨模型必跑）

在让模型动手前，让它先跑这一段自检：

```
在动代码前，请用 5-10 行回答以下 5 个问题：

1. 本项目的标杆问题是什么？
2. Skill 与 MCP 的分工是什么？给一个反例。（V2: Skill 是 `kb/skills/` 下被 `use_skill` 工具读取的文档，不是架构层）
3. "LLM 不算数" 在实践中怎么体现？
4. Agent 在什么情况下需要先和用户确认？（V2: 当工具的 `is_destructive` 或 `is_long_running` 标志为真，会回调 `confirm_callback`）
5. 当前任务的"完成"如何验证？

回答完等我确认。如果你说不出来，回去再读 CLAUDE.md。
```

第 1-4 题答错任何一道：让它**回去重读 CLAUDE.md** §0、§2.2、§5、§3，再答一次。

---

## 5. Cowork 模式 vs Claude Code 的差异

| 模式 | 用法 | 文件路径形式 |
|---|---|---|
| **Claude Code (CLI)** | `cd chemaster && claude`，自动读根 CLAUDE.md | 相对路径 (`docs/PITFALLS.md`) 即可 |
| **Cowork (Claude Desktop)** | 选 chemaster 文件夹后开会话 | 用绝对路径 (`/Users/ronggang/code/funcode/chemaster/...`) 更稳 |
| **VS Code + Claude 插件** | 同 Claude Code | 相对路径 |
| **API 直接调用** | 自写 agent loop | 把 CLAUDE.md 内容塞进 system prompt 第一段 |

本指南的所有 prompt **同时支持** 这几种模式。差异只在 Read 时的路径写法。

---

## 6. 一段话总结（贴墙上）

> 启动新会话三件事：
>
> 1. **粘开场白**（§0）让模型读 CLAUDE.md + PITFALLS + ROADMAP
> 2. **要求复述**（§4）确认它真读懂了
> 3. **给场景 prompt**（§1）一次一件事，pytest 验收

---

*文档版本：v1.0 (2026-04)。每次开发流程有变化时更新本文档。*
