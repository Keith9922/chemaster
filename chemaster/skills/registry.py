"""SkillRegistry —— 加载、索引、查询所有 Skill。

参考 EvoMaster SkillRegistry，针对计算化学扩展三层信息模型：

Level 1 (meta_info, ~100 tokens)：
  始终注入 Agent system prompt，让 LLM 知道"有什么 Skill 可用"。
  来自 SKILL.md frontmatter 的 name/description/when_to_use/level1_summary。

Level 2 (full_info, 500-2000 tokens)：
  按需加载（LLM 主动调用 use_skill 工具时）。
  来自 SKILL.md body 的完整方法论文档。

Level 3 (scripts)：
  可执行脚本，位于 skills/<name>/scripts/ 目录。
  目前 ChemMaster 的 Skill 是纯方法论文档，暂无 scripts；
  预留扩展点（如未来的自动化流程脚本）。

Usage::

    from chemaster.skills.registry import SkillRegistry
    registry = SkillRegistry.from_package()
    # 获取 context 用的 meta 摘要
    context_str = registry.get_meta_context()
    # 按需获取完整 skill 文档
    full_doc = registry.get_full_info("opt-freq")
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


class SkillMeta:
    """Level 1：Skill 元信息（始终在 context 中）。"""

    def __init__(self, data: dict[str, Any], skill_path: Path) -> None:
        self.name: str = data.get("name", skill_path.name)
        self.version: str = data.get("version", "0.1.0")
        self.description: str = data.get("description", "")
        self.when_to_use: str = data.get("when_to_use", "")
        self.when_not_to_use: str = data.get("when_not_to_use", "")
        self.required_mcps: list[str] = data.get("required_mcps", [])
        self.estimated_time: str = data.get("estimated_time", "未知")
        # level1_summary: 可选的精简描述（100 tokens 内）
        # 未设置时从 description + when_to_use 自动生成
        self._level1_summary: str = data.get("level1_summary", "")

    @property
    def level1_summary(self) -> str:
        """Level 1 摘要（100 tokens 内），常驻 context。"""
        if self._level1_summary:
            return self._level1_summary
        # 自动生成：name + description 前 200 字符
        desc = self.description[:200].replace("\n", " ")
        when = self.when_to_use.strip().split("\n")[0][:100] if self.when_to_use else ""
        parts = [f"[{self.name}] {desc}"]
        if when:
            parts.append(f"使用场景: {when}")
        return " | ".join(parts)

    def to_context_line(self) -> str:
        """单行格式，注入 system prompt。"""
        mcps = ", ".join(self.required_mcps) if self.required_mcps else "无"
        return (
            f"• **{self.name}** (v{self.version}) — {self.description}\n"
            f"  适用: {self.when_to_use.strip().split(chr(10))[0] if self.when_to_use else '见文档'}\n"
            f"  依赖 MCP: {mcps} | 预估耗时: {self.estimated_time}"
        )


class Skill:
    """单个 Skill 的完整表示（Level 1 + 2 + 3）。"""

    def __init__(self, skill_dir: Path) -> None:
        self.skill_dir = skill_dir
        self.skill_md = skill_dir / "SKILL.md"

        if not self.skill_md.exists():
            raise FileNotFoundError(f"SKILL.md 不存在: {self.skill_md}")

        raw = self.skill_md.read_text(encoding="utf-8")
        frontmatter, body = self._parse_frontmatter(raw)
        self.meta = SkillMeta(frontmatter, skill_dir)
        self._body = body  # Level 2 内容

        # Level 3：scripts 目录
        self.scripts_dir = skill_dir / "scripts"
        self.available_scripts: list[Path] = []
        if self.scripts_dir.exists():
            self.available_scripts = [
                p for p in self.scripts_dir.iterdir()
                if p.suffix in (".py", ".sh", ".js") and p.is_file()
            ]

    @staticmethod
    def _parse_frontmatter(raw: str) -> tuple[dict[str, Any], str]:
        """解析 YAML frontmatter（--- ... ---）+ body。"""
        if not raw.startswith("---"):
            return {}, raw

        end = raw.find("\n---", 3)
        if end == -1:
            return {}, raw

        fm_str = raw[3:end].strip()
        body = raw[end + 4:].strip()
        try:
            fm = yaml.safe_load(fm_str) or {}
        except yaml.YAMLError as exc:
            logger.warning("SKILL.md frontmatter 解析失败: %s", exc)
            fm = {}
        return fm, body

    @property
    def name(self) -> str:
        return self.meta.name

    def get_full_info(self) -> str:
        """Level 2：完整方法论文档（按需加载）。"""
        return self._body

    def get_script_path(self, script_name: str) -> Path | None:
        """Level 3：按名称获取脚本路径。"""
        for p in self.available_scripts:
            if p.name == script_name:
                return p
        return None

    def has_scripts(self) -> bool:
        return bool(self.available_scripts)

    def to_context_line(self) -> str:
        return self.meta.to_context_line()


class SkillRegistry:
    """管理所有 Skill 的注册中心。"""

    def __init__(self) -> None:
        self._skills: dict[str, Skill] = {}

    # ------------------------------------------------------------------
    # 加载
    # ------------------------------------------------------------------

    @classmethod
    def from_package(cls) -> "SkillRegistry":
        """从 chemaster/skills/ 目录自动加载所有 Skill。"""
        skills_root = Path(__file__).parent
        registry = cls()
        registry.load_from_directory(skills_root)
        return registry

    @classmethod
    def from_directory(cls, directory: str | Path) -> "SkillRegistry":
        """从指定目录加载。"""
        registry = cls()
        registry.load_from_directory(Path(directory))
        return registry

    def load_from_directory(
        self,
        directory: Path,
        skill_names: list[str] | None = None,
    ) -> None:
        """扫描目录，加载所有含 SKILL.md 的子目录。

        Args:
            directory: 要扫描的目录。
            skill_names: 白名单（None 表示全部加载）。
        """
        if not directory.exists():
            logger.warning("Skill 目录不存在: %s", directory)
            return

        loaded = 0
        for item in sorted(directory.iterdir()):
            if not item.is_dir():
                continue
            if item.name.startswith((".", "_")):
                continue
            if skill_names and item.name not in skill_names:
                continue
            skill_md = item / "SKILL.md"
            if not skill_md.exists():
                continue
            try:
                skill = Skill(item)
                self._skills[skill.name] = skill
                loaded += 1
                logger.debug("已加载 Skill: %s", skill.name)
            except Exception as exc:
                logger.warning("加载 Skill '%s' 失败: %s", item.name, exc)

        logger.info("共加载 %d 个 Skill（来自 %s）", loaded, directory)

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    def get(self, name: str) -> Skill | None:
        """按名称获取 Skill。"""
        return self._skills.get(name)

    def all(self) -> list[Skill]:
        """返回所有已加载的 Skill。"""
        return list(self._skills.values())

    def names(self) -> list[str]:
        return list(self._skills.keys())

    def search(self, query: str) -> list[Skill]:
        """按关键词搜索 Skill（name/description/when_to_use）。"""
        q = query.lower()
        results = []
        for skill in self._skills.values():
            text = (
                skill.name
                + " " + skill.meta.description
                + " " + skill.meta.when_to_use
            ).lower()
            if q in text:
                results.append(skill)
        return results

    # ------------------------------------------------------------------
    # Context 注入
    # ------------------------------------------------------------------

    def get_meta_context(self) -> str:
        """获取所有 Skill 的 Level 1 摘要，用于注入 system prompt。

        格式（每个 Skill 一段）：
        ## 可用 Skills
        • opt-freq (v0.1.0) — ...
          适用: ...
          依赖 MCP: ...
        """
        if not self._skills:
            return ""

        lines = ["## 可用 Skills（方法论知识库）\n"]
        for skill in sorted(self._skills.values(), key=lambda s: s.name):
            lines.append(skill.to_context_line())
            lines.append("")

        lines.append(
            "使用方式：调用 `use_skill` 工具并传入 skill_name 获取完整方法论文档。"
        )
        return "\n".join(lines)

    def get_level1_summary(self) -> str:
        """精简版 Level 1 摘要（适合 token 敏感场景）。"""
        if not self._skills:
            return ""
        summaries = [
            f"- {s.meta.level1_summary}"
            for s in sorted(self._skills.values(), key=lambda s: s.name)
        ]
        return "可用 Skills:\n" + "\n".join(summaries)

    # ------------------------------------------------------------------
    # ChemAgent 兼容接口
    # ------------------------------------------------------------------

    def list_skills_level1(self) -> dict[str, str]:
        """返回 {skill_name: level1_summary} 字典，供 ChemAgent 注入 system prompt。"""
        return {
            skill.name: skill.meta.level1_summary
            for skill in self._skills.values()
        }

    def get_skill(self, name: str) -> Skill | None:
        """按名称获取 Skill（与 ChemAgent._tool_use_skill 对齐）。

        Skill 对象的 .full_content 属性返回完整 Markdown body；
        .meta_info 属性返回 Level 1 摘要字符串。
        """
        skill = self._skills.get(name)
        if skill is None:
            return None
        # 动态添加 ChemAgent 期望的属性别名
        if not hasattr(skill, "full_content"):
            skill.full_content = skill.get_full_info()   # type: ignore[attr-defined]
        if not hasattr(skill, "meta_info"):
            skill.meta_info = skill.meta.level1_summary  # type: ignore[attr-defined]
        return skill

    def __len__(self) -> int:
        return len(self._skills)

    def __repr__(self) -> str:
        return f"SkillRegistry(skills={self.names()})"
