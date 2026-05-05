# GitHub 仓库发布指南

> 把 ChemMaster 推到 GitHub 公开发布，并在毕设论文里引用 GitHub 链接。
>
> 本文档假设你已经有 GitHub 账号。

---

## 一、Step 1：在 GitHub 创建空仓库（你做）

1. 打开 https://github.com/new
2. 填写：
   - **Repository name**: `chemaster`（推荐；与论文 README 中的链接对齐）
   - **Description**: `Local computational-chemistry agent built on LLM and MCP protocol — undergraduate thesis project at Jilin University, College of Chemistry.`
   - **Public**（推荐——毕设答辩可作为开源工作展示）
   - 不要勾 `Initialize with README / .gitignore / LICENSE`（仓库已有）
3. 点 `Create repository`
4. 复制屏幕上显示的 git URL，形如 `git@github.com:Keith9922/chemaster.git` 或 `https://github.com/Keith9922/chemaster.git`

---

## 二、Step 2：合并工作树分支到主线（必须做）

当前 v3.0 全部工作（36 个改动文件）在 worktree 分支 `claude/funny-aryabhata-7d1804`。需要先合到主线分支再推。

打开新终端：

```bash
cd /Users/ronggang/code/funcode/chemaster

# 看看当前在哪个分支
git branch --show-current
# 输出可能是: feat/web-server-streaming

# 合并 worktree 分支（含 v3.0 所有提交）到当前主线
git merge claude/funny-aryabhata-7d1804 --no-ff -m "merge: v3.0 labor-saving collaborator + multi-frontend + benchmark"

# 如果有冲突：手动解决冲突（极少出现，因为 worktree 是从 main 分出去的）

# 验证
git log --oneline -5
# 应能看到 6c3ec65 feat(v3.0): ...
```

---

## 三、Step 3：添加 GitHub remote 并首次推送

```bash
# 添加 remote（用上一步复制的 URL；改成你自己的）
git remote add origin git@github.com:Keith9922/chemaster.git

# 验证
git remote -v
# 应输出:
# origin  git@github.com:Keith9922/chemaster.git (fetch)
# origin  git@github.com:Keith9922/chemaster.git (push)

# 推 main / master 分支
git branch -M main           # 把当前分支重命名为 main（如果你想要标准命名）
git push -u origin main
```

如果你用 HTTPS 不是 SSH，会提示输入用户名 + Personal Access Token（不是密码——GitHub 已禁用密码推送）。生成 token：https://github.com/settings/tokens

---

## 四、Step 4：把 GitHub URL 填回论文

如果你创建的仓库 URL 与默认占位 `https://github.com/Keith9922/chemaster` 不同，更新这两个地方：

```bash
cd /Users/ronggang/code/funcode/chemaster/.claude/worktrees/funny-aryabhata-7d1804

# 1. 改 scripts/generate_thesis_docx.py 顶部的 GITHUB_URL 常量
sed -i '' 's|https://github.com/Keith9922/chemaster|<你的真实 URL>|g' scripts/generate_thesis_docx.py

# 2. 改 README.md（仓库根 + worktree 都改）
sed -i '' 's|https://github.com/Keith9922/chemaster|<你的真实 URL>|g' README.md
sed -i '' 's|https://github.com/Keith9922/chemaster|<你的真实 URL>|g' /Users/ronggang/code/funcode/chemaster/README.md

# 3. 重新生成 docx
python scripts/generate_thesis_docx.py
```

---

## 五、Step 5：仓库公开后的 GitHub 设置（建议做）

仓库推上去后，访问 https://github.com/<你>/chemaster/settings 配置：

1. **About**（仓库主页右上角）
   - Description: 复制 README 第一段
   - Topics: `computational-chemistry` `llm-agent` `mcp-protocol` `quantum-chemistry` `python`

2. **README 截图渲染检查**
   - 访问仓库主页，确认 README 顶部 3 张截图正确显示
   - 确认架构图（v4 drawio）渲染清晰

3. **Releases**
   - 在 https://github.com/<你>/chemaster/releases/new 创建 `v0.3.0-thesis` 标签
   - Title: `v0.3.0 — Bachelor Thesis Submission`
   - Description: 复制论文摘要前两段

---

## 六、Step 6：在论文里引用 GitHub URL

论文已经在三个位置引用了 GitHub 链接（占位）：

1. 摘要段末尾："本工作的全部代码、Benchmark 数据、运行轨迹与可复现脚本均已开源：<URL>"
2. §4.1 复现说明："本工作的全部源代码、Benchmark 数据、可复现脚本与运行轨迹均已开源，发布于 <URL>"
3. README 底部 BibTeX

如果你想加一个**显著的 GitHub 徽标**到封面，需要：

```python
# 在 scripts/generate_thesis_docx.py 的 write_cover() 末尾加：
from docx.shared import Pt
p = doc.add_paragraph()
set_para_format(p, alignment=WD_ALIGN_PARAGRAPH.CENTER, line_spacing=1.5)
r = p.add_run(f"项目主页：{GITHUB_URL}")
set_run_font(r, font_cn="宋体", font_en="Times New Roman", size_pt=SIZE["小四"])
```

---

## 七、Step 7：清理（可选但推荐）

合并完后删除工作树：

```bash
cd /Users/ronggang/code/funcode/chemaster
git worktree remove .claude/worktrees/funny-aryabhata-7d1804 --force
git branch -D claude/funny-aryabhata-7d1804
```

---

## 八、验证清单

推送完成后访问 https://github.com/<你>/chemaster ，确认：

- [ ] README 渲染正常，3 张顶部截图可见
- [ ] 架构图 / 对比图等 v4 drawio 输出图清晰
- [ ] `paper/thesis_draft.docx` 在仓库中可下载
- [ ] `benchmarks/` 目录的 JSON 数据存在
- [ ] License 显示为 MIT
- [ ] CLAUDE.md / docs/ 等文档全在
- [ ] 所有 PNG 图都能渲染（不要有 broken image）

---

## 常见问题

### Q: 推送被拒，提示 large file

A: 检查是否有 > 100 MB 文件被误提：

```bash
git ls-files | xargs -I {} du -h {} 2>/dev/null | sort -h | tail -10
```

如果有大文件，从 git 历史移除（用 `git filter-repo` 或 `git lfs`）。

### Q: README 里的图不显示

A: GitHub 渲染的 README 图片路径是相对仓库根。检查路径是否是 `paper/figures/...` 而不是 `./paper/figures/...` 或绝对路径。

### Q: 想隐藏 commit 历史中的某些信息

A: 先 `git log --all` 检查；如有敏感信息（API key、密码），用 `git filter-repo` 重写历史 *before* push。

---

*最后更新：2026-05-05。本文是 v3.0 发布的一次性指南，未来版本会写到 docs/PACKAGING.md。*
