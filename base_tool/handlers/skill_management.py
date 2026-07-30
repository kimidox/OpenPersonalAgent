"""skill_management 工具处理器"""
from __future__ import annotations

import json
from pathlib import Path

from .base import ToolHandler
from ..context import ToolContext
from . import register_handler


class InstallSkillFromZipHandler(ToolHandler):
    """从 ZIP 包安装 Skill 处理器"""

    @property
    def name(self) -> str:
        """返回工具名称"""
        return "install_skill_from_zip"

    def execute(self, args: dict, ctx: ToolContext, registry) -> str:
        """从 ZIP 包安装 Skill，并验证安装结果

        Args:
            args: 工具参数字典，支持 zip_path、overwrite
            ctx: ToolContext 执行上下文
            registry: 工具注册表

        Returns:
            工具执行结果的字符串
        """
        from ..dispatch import verify_skill_installation

        zip_path = args.get("zip_path", "")
        overwrite = args.get("overwrite", "false")
        if not zip_path:
            return "错误: 缺少 zip_path 参数"

        overwrite_bool = overwrite.lower() in ("true", "1", "yes")

        try:
            from skill.skill_manager import get_manager
            mgr = get_manager()
            installed_ids = mgr.install_from_zip(zip_path, overwrite=overwrite_bool)
            if not installed_ids:
                return "安装完成，但未成功注册任何 Skill"

            # 刷新 registry
            if registry:
                registry.reload()

            result_lines = [f"✓ 已从 ZIP 包安装 {len(installed_ids)} 个 Skill：", ""]
            result_lines.append("【安装结果】")

            # 验证每个安装的 Skill
            verification_results = []
            for sid in installed_ids:
                skill = mgr.get_skill_metadata(sid)
                skill_name = skill.name if skill else sid

                # 构建 Skill 目录路径
                skill_dir = Path(mgr.skills_dir) / sid

                # 执行验证
                verify_success, verify_msg = verify_skill_installation(str(skill_dir))

                if verify_success:
                    result_lines.append(f"✓ **{sid}**: {skill_name}")
                    result_lines.append(f"  验证状态: 成功")
                else:
                    result_lines.append(f"⚠ **{sid}**: {skill_name}")
                    result_lines.append(f"  验证状态: 失败")
                    result_lines.append(f"  错误信息: {verify_msg}")

                verification_results.append((sid, verify_success, verify_msg))

            # 添加验证总结
            result_lines.append("")
            result_lines.append("【验证总结】")
            success_count = sum(1 for _, success, _ in verification_results if success)
            fail_count = len(verification_results) - success_count

            if fail_count == 0:
                result_lines.append(f"✓ 所有 {len(installed_ids)} 个 Skill 验证通过")
            else:
                result_lines.append(f"⚠ 成功: {success_count} 个，失败: {fail_count} 个")
                result_lines.append("")
                result_lines.append("【故障排查建议】")
                for sid, success, msg in verification_results:
                    if not success:
                        result_lines.append(f"- {sid}: {msg}")

            return "\n".join(result_lines)
        except FileNotFoundError as e:
            return f"错误: {e}"
        except ValueError as e:
            return f"错误: {e}"
        except FileExistsError as e:
            return f"错误: Skill已存在 - {e}。如需覆盖安装，请设置 overwrite=true"
        except Exception as e:
            return f"错误: 安装ZIP包失败: {e}"


class ManageSkillHandler(ToolHandler):
    """Skill 管理工具处理器

    支持 list/get_info/edit 三种操作。
    """

    @property
    def name(self) -> str:
        """返回工具名称"""
        return "manage_skill"

    def execute(self, args: dict, ctx: ToolContext, registry) -> str:
        """管理 Skill，支持 list/get_info/edit 三种操作

        Args:
            args: 工具参数字典，支持 action、skill_id、content
            ctx: ToolContext 执行上下文
            registry: 工具注册表

        Returns:
            工具执行结果的字符串
        """
        action = args.get("action", "")
        if not action:
            return "错误: 缺少 action 参数"

        if action == "list":
            # 列出所有用户自定义 Skill
            if not registry:
                return "错误: SkillRegistry 不可用"
            user_skills = []
            for skill in registry.list_user_skills():
                user_skills.append({
                    "id": skill.skill_id,
                    "name": skill.name,
                    "description": skill.description[:100] + "..." if len(skill.description) > 100 else skill.description
                })
            if not user_skills:
                return "未找到用户自定义 Skill"
            result_lines = ["用户自定义 Skill 列表：", ""]
            for s in user_skills:
                result_lines.append(f"- **{s['id']}**: {s['name']}")
                result_lines.append(f"  描述：{s['description']}")
            return "\n".join(result_lines)

        if action == "get_info":
            skill_id = args.get("skill_id", "")
            if not skill_id:
                return "错误: 缺少 skill_id 参数"
            if not registry:
                return "错误: SkillRegistry 不可用"
            skill = registry.get(str(skill_id))
            if not skill:
                return f"错误: 未找到 Skill '{skill_id}'"
            info = {
                "id": skill.skill_id,
                "name": skill.name,
                "description": skill.description,
                "skill_type": skill.skill_type,
                "file_path": str(skill.relative_path) if skill.relative_path else "unknown"
            }
            return json.dumps(info, ensure_ascii=False, indent=2)

        if action == "edit":
            skill_id = args.get("skill_id", "")
            content = args.get("content", "")
            if not skill_id:
                return "错误: 缺少 skill_id 参数"
            if not content:
                return "错误: 缺少 content 参数"
            if not registry:
                return "错误: SkillRegistry 不可用"
            # 检查是否为内置 Skill
            skill = registry.get(str(skill_id))
            if not skill:
                return f"错误: 未找到 Skill '{skill_id}'"
            if skill.skill_type == "builtin":
                return f"错误: 内置 Skill '{skill_id}' 不可修改，仅支持优化用户自定义 Skill"
            # 使用 SkillManager 编辑 Skill
            try:
                from skill.skill_manager import get_manager
                mgr = get_manager()
                success = mgr.edit_skill(str(skill_id), content)
                if success:
                    return f"✓ Skill '{skill_id}' 文档已更新"
                else:
                    return f"错误: Skill '{skill_id}' 更新失败"
            except Exception as e:
                return f"错误: 编辑 Skill 失败: {e}"

        return f"错误: 未知的 action 参数: {action}"


register_handler(InstallSkillFromZipHandler())
register_handler(ManageSkillHandler())
