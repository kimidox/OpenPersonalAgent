from __future__ import annotations

import shutil
from pathlib import Path

from logger import get_module_logger

from .loader import load_all_skills, load_builtin_skills, load_skill_from_path, resolve_skill_markdown_in_package
from .skill_manager import SkillManager
from .types import SkillDefinition

logger = get_module_logger("skill_registry")


class SkillRegistry:
    """管理 Skills 目录：每个 Skill 为根目录下的一级子文件夹，内含主 .md（见 loader）。"""

    def __init__(self, skills_dir: str | Path, builtin_dir: str | Path | None = None) -> None:
        self.skills_dir = Path(skills_dir).resolve()
        self._builtin_dir = Path(builtin_dir).resolve() if builtin_dir else None
        self._by_id: dict[str, SkillDefinition] = {}
        self.reload()

    def reload(self) -> None:
        user_skills = load_all_skills(self.skills_dir)
        for s in user_skills:
            s.skill_type = "user"
        
        builtin_skills: list[SkillDefinition] = []
        if self._builtin_dir and self._builtin_dir.is_dir():
            builtin_skills = load_builtin_skills(self._builtin_dir)
        
        self._by_id = {}
        for s in user_skills:
            self._by_id[s.skill_id] = s
        for s in builtin_skills:
            self._by_id[s.skill_id] = s

    def list_skills(self) -> list[SkillDefinition]:
        return list(self._by_id.values())

    def list_user_skills(self) -> list[SkillDefinition]:
        return [s for s in self._by_id.values() if s.skill_type == "user"]

    def list_builtin_skills(self) -> list[SkillDefinition]:
        return [s for s in self._by_id.values() if s.skill_type == "builtin"]

    def get(self, skill_id: str) -> SkillDefinition | None:
        return self._by_id.get((skill_id or "").strip())

    def load_file(self, path: str | Path) -> SkillDefinition:
        p = Path(path)
        if p.is_file():
            s = load_skill_from_path(p)
        else:
            rel = self.skills_dir / p
            if rel.is_dir():
                md = resolve_skill_markdown_in_package(rel)
                if md is None:
                    raise FileNotFoundError(f"Skill 包目录中未找到 .md 文件: {rel}")
                s = load_skill_from_path(md)
            elif rel.is_file():
                s = load_skill_from_path(rel)
            else:
                pkg = self.skills_dir / p.name
                if pkg.is_dir():
                    md = resolve_skill_markdown_in_package(pkg)
                    if md is None:
                        raise FileNotFoundError(f"Skill 包目录中未找到 .md 文件: {pkg}")
                    s = load_skill_from_path(md)
                else:
                    raise FileNotFoundError(f"找不到 Skill 文件或包: {rel}")
        self._by_id[s.skill_id] = s
        return s

    def delete_skill(self, skill_id: str) -> bool:
        skill = self.get(skill_id)
        if skill is None:
            logger.warning(f"Skill「{skill_id}」不存在")
            return False
        
        skill_type = getattr(skill, 'skill_type', 'user')
        if skill_type == "builtin":
            logger.warning(f"系统内置 Skill「{skill_id}」不可移除")
            return False
        
        skill_path = None
        if skill.relative_path:
            skill_path = self.skills_dir / skill.relative_path.parent
        else:
            skill_path = self.skills_dir / skill_id
        
        if skill_path is None or not skill_path.exists():
            logger.warning(f"无法找到 Skill「{skill_id}」的文件路径")
            return False
        
        try:
            if skill_path.is_dir():
                shutil.rmtree(skill_path)
                logger.info(f"已删除 Skill 目录: {skill_path}")
            elif skill_path.is_file():
                skill_path.unlink()
                logger.info(f"已删除 Skill 文件: {skill_path}")
            else:
                logger.warning(f"Skill 路径「{skill_path}」既不是目录也不是文件")
                return False
            
            if skill_id in self._by_id:
                del self._by_id[skill_id]
            
            return True
        except Exception as e:
            logger.error(f"删除 Skill「{skill_id}」时发生错误: {e}")
            return False

    def install_skill_from_zip(self, zip_path: str, overwrite: bool = False) -> tuple[list[str], str]:
        """从 ZIP 包安装 Skill。

        Args:
            zip_path: ZIP 文件路径。
            overwrite: 是否覆盖已存在的 Skill。

        Returns:
            (installed_ids, error_message) 元组。成功时 error_message 为空字符串，
            失败时 installed_ids 为空列表。
        """
        try:
            manager = SkillManager(self.skills_dir)
            installed_ids = manager.install_from_zip(zip_path, overwrite=overwrite)
            self.reload()
            logger.info(f"从 ZIP 包安装 Skill 成功: {installed_ids}")
            return (installed_ids, "")
        except FileNotFoundError as e:
            msg = f"ZIP文件不存在: {zip_path}"
            logger.error(msg)
            return ([], msg)
        except ValueError as e:
            msg = str(e)
            logger.error(msg)
            return ([], msg)
        except FileExistsError as e:
            msg = f"Skill已存在: {e}，如需覆盖请设置 overwrite=True"
            logger.error(msg)
            return ([], msg)
        except Exception as e:
            msg = f"安装ZIP包失败: {e}"
            logger.error(msg)
            return ([], msg)
