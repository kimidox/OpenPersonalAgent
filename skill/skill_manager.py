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
import zipfile
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

    def __init__(self, skills_dir: str | None = None) -> None:
        if skills_dir is None:
            skills_dir = str(paths.get_skills_dir() / "user_defined")
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
        else:
            # 文件没有YAML front matter，添加新的
            yaml_dict = {
                "id": skill_id,
                "name": source_path.stem,
                "description": "",
                "tags": [],
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }
            updated_yaml = yaml.dump(yaml_dict, allow_unicode=True, default_flow_style=False)
            content = f"---\n{updated_yaml}---\n\n{content}"

        skill_file.write_text(content, encoding="utf-8")
        logger.info(f"已导入Skill: {skill_id}")

        return skill_id

    def check_zip_conflicts(self, zip_path: str) -> list[str]:
        """预检查ZIP包中的Skill是否与已有Skill冲突

        只扫描ZIP结构，不提取任何文件。

        Args:
            zip_path: ZIP文件路径

        Returns:
            冲突的目录名列表（空列表表示无冲突）

        Raises:
            FileNotFoundError: ZIP文件不存在
            ValueError: ZIP文件无效或未找到Markdown文件
        """
        zip_file = Path(zip_path)
        if not zip_file.exists():
            raise FileNotFoundError(f"ZIP文件不存在: {zip_path}")

        if not zipfile.is_zipfile(zip_path):
            raise ValueError(f"文件不是有效的ZIP格式: {zip_path}")

        conflicts: list[str] = []

        with zipfile.ZipFile(zip_path, "r") as zf:
            names = zf.namelist()

            # 过滤隐藏文件和 __pycache__
            filtered_names = [
                n for n in names
                if not any(
                    part.startswith(".") or part == "__pycache__"
                    for part in Path(n).parts
                )
            ]

            # 扫描ZIP结构，确定模式
            root_md_files: list[str] = []
            subdir_md_files: dict[str, list[str]] = {}

            for name in filtered_names:
                parts = Path(name).parts
                if name.endswith((".md", ".markdown")):
                    if len(parts) == 1:
                        root_md_files.append(name)
                    elif len(parts) >= 2:
                        subdir_name = parts[0]
                        if subdir_name not in subdir_md_files:
                            subdir_md_files[subdir_name] = []
                        subdir_md_files[subdir_name].append(name)

            if not root_md_files and not subdir_md_files:
                raise ValueError("ZIP 包中未找到有效的 Skill Markdown 文件")

            if root_md_files:
                # Flat模式
                skill_dir_name = zip_file.stem
                target_dir = Path(self.skills_dir) / skill_dir_name
                if target_dir.exists():
                    conflicts.append(skill_dir_name)
            else:
                # Package模式
                for subdir_name in subdir_md_files:
                    target_dir = Path(self.skills_dir) / subdir_name
                    if target_dir.exists():
                        conflicts.append(subdir_name)

        return conflicts

    def install_from_zip(self, zip_path: str, overwrite: bool = False) -> list[str]:
        """从ZIP包安装Skill

        支持两种ZIP结构：
        - Flat模式：ZIP根目录直接包含 .md/.markdown 文件
        - Package模式：ZIP根目录包含子目录，每个子目录中有 .md/.markdown 文件

        Args:
            zip_path: ZIP文件路径
            overwrite: 是否覆盖已存在的Skill

        Returns:
            安装的skill_id列表

        Raises:
            FileNotFoundError: ZIP文件不存在
            ValueError: ZIP文件无效或未找到Markdown文件
            FileExistsError: Skill已存在且overwrite=False
        """
        zip_file = Path(zip_path)
        if not zip_file.exists():
            parent = zip_file.parent
            extra = ""
            if parent.exists():
                try:
                    files = [p.name for p in parent.iterdir() if p.is_file()]
                    extra = f" (目录存在，文件数: {len(files)})"
                except OSError as e:
                    extra = f" (目录存在但无法列出: {e})"
            else:
                extra = " (父目录不存在)"
            raise FileNotFoundError(f"ZIP文件不存在: {zip_path}{extra}")

        if not zipfile.is_zipfile(zip_path):
            raise ValueError(f"文件不是有效的ZIP格式: {zip_path}")

        installed_ids: list[str] = []

        with zipfile.ZipFile(zip_path, "r") as zf:
            names = zf.namelist()

            # 过滤隐藏文件和 __pycache__
            filtered_names = [
                n for n in names
                if not any(
                    part.startswith(".") or part == "__pycache__"
                    for part in Path(n).parts
                )
            ]

            # 扫描ZIP结构，确定模式
            root_md_files: list[str] = []  # 根目录下的.md文件
            subdir_md_files: dict[str, list[str]] = {}  # 子目录 -> [.md文件列表]

            for name in filtered_names:
                parts = Path(name).parts
                # 检查是否为 .md/.markdown 文件
                if name.endswith((".md", ".markdown")):
                    if len(parts) == 1:
                        # 根目录下的 .md 文件
                        root_md_files.append(name)
                    elif len(parts) >= 2:
                        # 子目录下的 .md 文件
                        subdir_name = parts[0]
                        if subdir_name not in subdir_md_files:
                            subdir_md_files[subdir_name] = []
                        subdir_md_files[subdir_name].append(name)

            # 验证是否找到有效的Markdown文件
            if not root_md_files and not subdir_md_files:
                raise ValueError("ZIP 包中未找到有效的 Skill Markdown 文件")

            if root_md_files:
                # Flat模式：使用ZIP文件名作为Skill目录名
                skill_dir_name = zip_file.stem
                target_dir = Path(self.skills_dir) / skill_dir_name

                if target_dir.exists():
                    if not overwrite:
                        raise FileExistsError(
                            f"Skill目录已存在: {target_dir}，如需覆盖请设置 overwrite=True"
                        )
                    # 覆盖安装前先清空旧目录，避免旧文件残留导致安装旧版本内容
                    shutil.rmtree(target_dir)

                # 提取所有内容到目标目录
                for name in filtered_names:
                    # 跳过目录条目
                    if name.endswith("/"):
                        continue
                    target_path = target_dir / name
                    target_path.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(name) as src, open(target_path, "wb") as dst:
                        dst.write(src.read())

                logger.info(f"已从ZIP提取Skill文件到: {target_dir}")

                # 更新YAML front matter
                skill_id = self._update_skill_front_matter(target_dir)
                if skill_id:
                    installed_ids.append(skill_id)
            else:
                # Package模式：每个包含.md文件的子目录为一个Skill
                for subdir_name, md_files in subdir_md_files.items():
                    target_dir = Path(self.skills_dir) / subdir_name

                    if target_dir.exists():
                        if not overwrite:
                            raise FileExistsError(
                                f"Skill目录已存在: {target_dir}，如需覆盖请设置 overwrite=True"
                            )
                        # 覆盖安装前先清空旧目录，避免旧文件残留导致安装旧版本内容
                        shutil.rmtree(target_dir)

                    # 提取该子目录的内容
                    for name in filtered_names:
                        parts = Path(name).parts
                        if len(parts) >= 2 and parts[0] == subdir_name:
                            # 跳过目录条目
                            if name.endswith("/"):
                                continue
                            # 去掉顶层子目录前缀
                            relative_path = Path(name).relative_to(subdir_name)
                            target_path = target_dir / relative_path
                            target_path.parent.mkdir(parents=True, exist_ok=True)
                            with zf.open(name) as src, open(target_path, "wb") as dst:
                                dst.write(src.read())

                    logger.info(f"已从ZIP提取Skill '{subdir_name}' 到: {target_dir}")

                    # 更新YAML front matter
                    skill_id = self._update_skill_front_matter(target_dir)
                    if skill_id:
                        installed_ids.append(skill_id)

        logger.info(f"从ZIP安装完成，共安装 {len(installed_ids)} 个Skill")
        return installed_ids

    def _update_skill_front_matter(self, skill_dir: Path) -> Optional[str]:
        """更新Skill目录中的Markdown文件YAML front matter

        更新id为新生成的skill_id，更新created_at为当前时间。
        如果Markdown文件不叫SKILL.md，会自动重命名为SKILL.md。
        同时将目录重命名为skill_id。
        如果文件没有YAML front matter，会自动添加。

        Args:
            skill_dir: Skill目录路径

        Returns:
            更新后的skill_id，如果未找到.md文件则返回None
        """
        # 优先查找 SKILL.md
        skill_md_path = skill_dir / "SKILL.md"
        md_file = None
        
        if skill_md_path.exists():
            # 已有 SKILL.md，直接使用
            md_file = skill_md_path
        else:
            # 查找其他 .md/.markdown 文件
            for f in skill_dir.iterdir():
                if f.is_file() and f.suffix in (".md", ".markdown"):
                    md_file = f
                    break

        if md_file is None:
            logger.warning(f"Skill目录中未找到Markdown文件: {skill_dir}")
            return None

        content = md_file.read_text(encoding="utf-8")
        skill_id = generate_skill_id()

        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                yaml_content = parts[1].strip()
                yaml_dict = yaml.safe_load(yaml_content) or {}
                yaml_dict["id"] = skill_id
                yaml_dict["created_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
                updated_yaml = yaml.dump(yaml_dict, allow_unicode=True, default_flow_style=False)
                content = f"---\n{updated_yaml}---\n\n{parts[2].strip()}"
        else:
            # 文件没有YAML front matter，添加新的
            yaml_dict = {
                "id": skill_id,
                "name": skill_dir.name,
                "description": "",
                "tags": [],
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }
            updated_yaml = yaml.dump(yaml_dict, allow_unicode=True, default_flow_style=False)
            content = f"---\n{updated_yaml}---\n\n{content}"

        # 如果文件名不是SKILL.md，重命名为SKILL.md
        if md_file.name != "SKILL.md":
            target_path = md_file.parent / "SKILL.md"
            # 如果目标文件已存在，先删除（Windows 上 rename 不允许覆盖）
            if target_path.exists():
                target_path.unlink()
            md_file.rename(target_path)
            md_file = target_path
            logger.info(f"已重命名Markdown文件为SKILL.md: {skill_dir}")

        md_file.write_text(content, encoding="utf-8")
        logger.info(f"已更新Skill front matter: {skill_id}")

        # 将目录重命名为skill_id
        parent_dir = skill_dir.parent
        new_dir = parent_dir / skill_id
        if skill_dir.name != skill_id:
            # 如果目标目录已存在，先删除
            if new_dir.exists():
                shutil.rmtree(new_dir)
            skill_dir.rename(new_dir)
            logger.info(f"已重命名Skill目录: {skill_dir.name} -> {skill_id}")

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