"""
Markdown格式Skill管理器

提供Markdown格式Skill文件的CRUD操作，支持YAML front matter解析。
"""

from __future__ import annotations

import os
import re
import shutil
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

from logger import get_module_logger

logger = get_module_logger("skill_manager")


@dataclass
class SkillMetadata:
    """Skill元数据"""
    id: str
    name: str
    description: str
    tags: list[str]
    created_at: str
    updated_at: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "tags": self.tags,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass
class SkillData:
    """完整的Skill数据"""
    metadata: SkillMetadata
    content: str  # Markdown内容（不含YAML front matter）

    def to_markdown(self) -> str:
        """生成完整的Markdown文件内容"""
        yaml_front = yaml.dump(self.metadata.to_dict(), allow_unicode=True, default_flow_style=False)
        return f"---\n{yaml_front}---\n\n{self.content}"


def generate_skill_id() -> str:
    """生成Skill ID"""
    return f"skill_{uuid.uuid4().hex[:8]}"


def parse_skill_metadata(skill_file: str) -> SkillMetadata:
    """解析Markdown文件的YAML front matter"""
    path = Path(skill_file)
    if not path.exists():
        raise FileNotFoundError(f"文件不存在: {skill_file}")

    content = path.read_text(encoding="utf-8")

    # 解析YAML front matter
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            yaml_content = parts[1].strip()
            try:
                metadata_dict = yaml.safe_load(yaml_content) or {}
                return SkillMetadata(
                    id=metadata_dict.get("id", ""),
                    name=metadata_dict.get("name", ""),
                    description=metadata_dict.get("description", ""),
                    tags=metadata_dict.get("tags", []),
                    created_at=metadata_dict.get("created_at", ""),
                    updated_at=metadata_dict.get("updated_at"),
                )
            except yaml.YAMLError as e:
                logger.warning(f"YAML解析失败: {e}")
                # 返回默认元数据
                return SkillMetadata(
                    id=path.parent.name,
                    name=path.parent.name,
                    description="",
                    tags=[],
                    created_at="",
                )

    # 无YAML front matter，返回默认元数据
    return SkillMetadata(
        id=path.parent.name,
        name=path.parent.name,
        description="",
        tags=[],
        created_at="",
    )


def parse_skill_content(skill_file: str) -> str:
    """解析Markdown文件的内容部分（不含YAML front matter）"""
    path = Path(skill_file)
    if not path.exists():
        raise FileNotFoundError(f"文件不存在: {skill_file}")

    content = path.read_text(encoding="utf-8")

    # 移除YAML front matter
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            return parts[2].strip()

    return content


def load_skill(skill_id: str, skills_dir: str) -> SkillData:
    """加载完整的Skill数据"""
    skill_file = Path(skills_dir) / skill_id / "SKILL.md"
    if not skill_file.exists():
        raise FileNotFoundError(f"Skill文件不存在: {skill_file}")

    metadata = parse_skill_metadata(str(skill_file))
    content = parse_skill_content(str(skill_file))

    return SkillData(metadata=metadata, content=content)


def save_skill(skill_id: str, skill_data: SkillData, skills_dir: str) -> None:
    """保存Skill数据"""
    skill_dir = Path(skills_dir) / skill_id
    skill_dir.mkdir(parents=True, exist_ok=True)

    skill_file = skill_dir / "SKILL.md"
    markdown_content = skill_data.to_markdown()
    skill_file.write_text(markdown_content, encoding="utf-8")
    logger.info(f"已保存Skill: {skill_id}")


def generate_skill_markdown_template(skill_id: str, name: str, description: str, tags: list[str]) -> str:
    """生成Skill Markdown模板"""
    metadata = SkillMetadata(
        id=skill_id,
        name=name,
        description=description,
        tags=tags,
        created_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
    )

    template_content = f"""# {name}

{description}

## 使用方法

用户需要提供以下参数：
- `param_name`: 参数描述

## 执行流程

1. 使用 /tool_name 执行操作
   - 参数：param1="value1", param2="value2"

2. 使用 /another_tool 执行下一步
   - 参数：element="{{step_1_result}}"

## 示例

用户输入："执行示例操作"

执行结果：
- 步骤1完成
- 步骤2完成
- 任务完成

## 注意事项

- 注意事项1
- 注意事项2
"""

    skill_data = SkillData(metadata=metadata, content=template_content)
    return skill_data.to_markdown()


class SkillManager:
    """Markdown格式Skill管理器"""

    def __init__(self, skills_dir: str = "PersonalData/Skills/user_defined") -> None:
        self.skills_dir = skills_dir
        self._ensure_skills_dir()

    def _ensure_skills_dir(self) -> None:
        """确保Skill目录存在"""
        Path(self.skills_dir).mkdir(parents=True, exist_ok=True)

    def create_skill(
        self,
        name: str,
        description: str,
        tags: list[str],
    ) -> str:
        """创建新Skill（Markdown格式）"""
        skill_id = generate_skill_id()
        skill_dir = Path(self.skills_dir) / skill_id
        skill_dir.mkdir(parents=True, exist_ok=True)

        skill_file = skill_dir / "SKILL.md"
        skill_content = generate_skill_markdown_template(skill_id, name, description, tags)

        skill_file.write_text(skill_content, encoding="utf-8")
        logger.info(f"已创建Skill: {skill_id} ({name})")

        return skill_id

    def edit_skill(self, skill_id: str, skill_content: str) -> bool:
        """编辑Skill（Markdown格式）"""
        skill_file = Path(self.skills_dir) / skill_id / "SKILL.md"

        if not skill_file.exists():
            logger.warning(f"Skill '{skill_id}' 不存在")
            return False

        try:
            # 更新updated_at时间
            metadata = parse_skill_metadata(str(skill_file))
            metadata.updated_at = time.strftime("%Y-%m-%dT%H:%M:%S")

            # 解析新内容
            new_content = skill_content
            if skill_content.startswith("---"):
                parts = skill_content.split("---", 2)
                if len(parts) >= 3:
                    # 更新元数据中的updated_at
                    yaml_content = parts[1].strip()
                    yaml_dict = yaml.safe_load(yaml_content) or {}
                    yaml_dict["updated_at"] = metadata.updated_at
                    updated_yaml = yaml.dump(yaml_dict, allow_unicode=True, default_flow_style=False)
                    new_content = f"---\n{updated_yaml}---\n\n{parts[2].strip()}"

            skill_file.write_text(new_content, encoding="utf-8")
            logger.info(f"已更新Skill: {skill_id}")
            return True

        except Exception as e:
            logger.error(f"更新Skill失败: {e}")
            return False

    def delete_skill(self, skill_id: str) -> bool:
        """删除Skill"""
        skill_dir = Path(self.skills_dir) / skill_id

        if not skill_dir.exists():
            logger.warning(f"Skill目录不存在: {skill_dir}")
            return False

        try:
            shutil.rmtree(skill_dir)
            logger.info(f"已删除Skill: {skill_id}")
            return True
        except Exception as e:
            logger.error(f"删除Skill失败: {e}")
            return False

    def import_skill(self, file_path: str) -> str:
        """导入Skill（Markdown格式）"""
        source_path = Path(file_path)
        if not source_path.exists():
            raise FileNotFoundError(f"文件不存在: {file_path}")

        # 生成新ID避免冲突
        skill_id = generate_skill_id()
        skill_dir = Path(self.skills_dir) / skill_id
        skill_dir.mkdir(parents=True, exist_ok=True)

        skill_file = skill_dir / "SKILL.md"

        # 复制文件内容并更新ID
        content = source_path.read_text(encoding="utf-8")
        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                yaml_content = parts[1].strip()
                yaml_dict = yaml.safe_load(yaml_content) or {}
                yaml_dict["id"] = skill_id
                yaml_dict["created_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
                updated_yaml = yaml.dump(yaml_dict, allow_unicode=True, default_flow_style=False)
                content = f"---\n{updated_yaml}---\n\n{parts[2].strip()}"

        skill_file.write_text(content, encoding="utf-8")
        logger.info(f"已导入Skill: {skill_id}")

        return skill_id

    def export_skill(self, skill_id: str, export_path: str) -> bool:
        """导出Skill（Markdown格式）"""
        skill_file = Path(self.skills_dir) / skill_id / "SKILL.md"

        if not skill_file.exists():
            logger.warning(f"Skill '{skill_id}' 不存在")
            return False

        try:
            shutil.copy(skill_file, export_path)
            logger.info(f"已导出Skill '{skill_id}' 到 '{export_path}'")
            return True
        except Exception as e:
            logger.error(f"导出Skill失败: {e}")
            return False

    def list_skills(self) -> list[SkillMetadata]:
        """列出所有Skill"""
        skills = []
        skills_dir = Path(self.skills_dir)

        if skills_dir.exists():
            for skill_dir in skills_dir.iterdir():
                if skill_dir.is_dir():
                    skill_file = skill_dir / "SKILL.md"
                    if skill_file.exists():
                        try:
                            metadata = parse_skill_metadata(str(skill_file))
                            skills.append(metadata)
                        except Exception as e:
                            logger.warning(f"解析Skill '{skill_dir.name}' 失败: {e}")

        return skills

    def get_skill(self, skill_id: str) -> Optional[SkillData]:
        """获取完整的Skill数据"""
        try:
            return load_skill(skill_id, self.skills_dir)
        except FileNotFoundError:
            return None

    def get_skill_metadata(self, skill_id: str) -> Optional[SkillMetadata]:
        """获取Skill元数据"""
        skill_file = Path(self.skills_dir) / skill_id / "SKILL.md"
        if not skill_file.exists():
            return None

        try:
            return parse_skill_metadata(str(skill_file))
        except Exception:
            return None

    def search_skills(self, keyword: str) -> list[SkillMetadata]:
        """搜索Skill"""
        all_skills = self.list_skills()
        keyword_lower = keyword.lower()

        return [
            skill for skill in all_skills
            if keyword_lower in skill.name.lower()
            or keyword_lower in skill.description.lower()
            or any(keyword_lower in tag.lower() for tag in skill.tags)
        ]

    def filter_skills_by_tag(self, tag: str) -> list[SkillMetadata]:
        """按标签筛选Skill"""
        all_skills = self.list_skills()
        tag_lower = tag.lower()

        return [
            skill for skill in all_skills
            if any(tag_lower in t.lower() for t in skill.tags)
        ]

    def publish_skill(self, skill_id: str) -> bool:
        """发布Skill到Skill根目录
        
        将用户自定义Skill从 user_defined 目录复制到 Skills 根目录，
        使其可以被SkillAgent正常加载和使用。
        
        Args:
            skill_id: Skill ID
            
        Returns:
            发布成功返回True，失败返回False
        """
        from resource_path import paths
        
        # 源目录：user_defined
        source_dir = Path(self.skills_dir) / skill_id
        source_file = source_dir / "SKILL.md"
        
        if not source_file.exists():
            logger.warning(f"Skill '{skill_id}' 不存在")
            return False
        
        # 目标目录：Skills根目录
        target_skills_dir = paths.get_skills_dir()
        target_dir = target_skills_dir / skill_id
        target_file = target_dir / "SKILL.md"
        
        # 检查目标目录是否已存在同名Skill
        if target_dir.exists():
            logger.warning(f"目标目录已存在Skill '{skill_id}'，将被覆盖")
            try:
                shutil.rmtree(target_dir)
            except Exception as e:
                logger.error(f"删除目标目录失败: {e}")
                return False
        
        try:
            # 复制整个Skill目录
            shutil.copytree(source_dir, target_dir)
            logger.info(f"已发布Skill '{skill_id}' 到 {target_skills_dir}")
            return True
        except Exception as e:
            logger.error(f"发布Skill失败: {e}")
            return False

    def unpublish_skill(self, skill_id: str) -> bool:
        """取消发布Skill
        
        从Skills根目录删除已发布的Skill（保留user_defined中的源文件）。
        
        Args:
            skill_id: Skill ID
            
        Returns:
            取消发布成功返回True，失败返回False
        """
        from resource_path import paths
        
        # 目标目录：Skills根目录
        target_skills_dir = paths.get_skills_dir()
        target_dir = target_skills_dir / skill_id
        
        if not target_dir.exists():
            logger.warning(f"已发布的Skill '{skill_id}' 不存在")
            return False
        
        try:
            shutil.rmtree(target_dir)
            logger.info(f"已取消发布Skill '{skill_id}'")
            return True
        except Exception as e:
            logger.error(f"取消发布Skill失败: {e}")
            return False

    def is_skill_published(self, skill_id: str) -> bool:
        """检查Skill是否已发布
        
        Args:
            skill_id: Skill ID
            
        Returns:
            已发布返回True，未发布返回False
        """
        from resource_path import paths
        
        target_skills_dir = paths.get_skills_dir()
        target_dir = target_skills_dir / skill_id
        target_file = target_dir / "SKILL.md"
        
        return target_file.exists()


# 单例实例
_manager: Optional[SkillManager] = None


def get_manager() -> SkillManager:
    """获取管理器单例"""
    global _manager
    if _manager is None:
        from resource_path import paths
        skills_dir = str(paths.get_skills_dir() / "user_defined")
        _manager = SkillManager(skills_dir=skills_dir)
    return _manager