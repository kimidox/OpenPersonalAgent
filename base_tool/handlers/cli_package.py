"""cli_package 工具处理器：CLI 包的安装与查看"""
from __future__ import annotations

import json

from .base import ToolHandler
from ..context import ToolContext
from . import register_handler


class InstallCliPackageHandler(ToolHandler):
    """从 ZIP 压缩包安装 CLI 包处理器"""

    @property
    def name(self) -> str:
        """返回工具名称"""
        return "install_cli_package"

    def execute(self, args: dict, ctx: ToolContext, registry) -> str:
        """从 ZIP 包安装 CLI 包（需含 cli.json 清单）

        Args:
            args: 工具参数字典，支持 zip_path、overwrite
            ctx: ToolContext 执行上下文
            registry: 工具注册表

        Returns:
            工具执行结果的字符串
        """
        zip_path = str(args.get("zip_path", "")).strip()
        overwrite_raw = args.get("overwrite", "false")
        overwrite = str(overwrite_raw).lower() in ("true", "1", "yes")

        if not zip_path:
            return "错误: 缺少 zip_path 参数"

        try:
            import cli_manager
            info, err = cli_manager.install_cli_package_from_zip(zip_path, overwrite=overwrite)
            if err:
                return f"错误: {err}"

            lines = [
                f"✓ CLI 包「{info['name']}」安装成功",
                "",
                f"版本: {info.get('version') or '-'}",
                f"描述: {info.get('description') or '-'}",
                f"安装目录: {info['install_dir']}",
                f"入口文件: {info['entry']}",
            ]
            commands = info.get("commands") or []
            if commands:
                lines.append("")
                lines.append("可用命令：")
                for c in commands:
                    if isinstance(c, dict):
                        lines.append(f"- {c.get('usage', '')}  # {c.get('desc', '')}")
            lines.append("")
            lines.append("后续可通过 run_command 工具在安装目录下按入口文件调用该 CLI。")
            return "\n".join(lines)
        except Exception as e:  # noqa: BLE001
            return f"错误: 安装 CLI 包失败: {e}"


class ListCliPackagesHandler(ToolHandler):
    """列出已安装 CLI 包处理器"""

    @property
    def name(self) -> str:
        """返回工具名称"""
        return "list_cli_packages"

    def execute(self, args: dict, ctx: ToolContext, registry) -> str:
        """列出所有已安装的 CLI 包及其用法

        Args:
            args: 工具参数字典（无必需参数）
            ctx: ToolContext 执行上下文
            registry: 工具注册表

        Returns:
            工具执行结果的字符串
        """
        try:
            import cli_manager
            packages = cli_manager.list_cli_packages()
            if not packages:
                return "当前没有已安装的 CLI 包。"

            lines = [f"已安装 CLI 包列表（共 {len(packages)} 个）：", ""]
            for pkg in packages:
                lines.append(f"- **{pkg['name']}**: {pkg.get('description') or '(无描述)'}")
                lines.append(f"  版本: {pkg.get('version') or '-'}")
                lines.append(f"  安装目录: {pkg['install_dir']}")
                lines.append(f"  入口文件: {pkg.get('entry', '')}")
                commands = pkg.get("commands") or []
                if commands:
                    lines.append("  可用命令：")
                    for c in commands:
                        if isinstance(c, dict):
                            lines.append(f"    - {c.get('usage', '')}  # {c.get('desc', '')}")
                lines.append("")
            return "\n".join(lines)
        except Exception as e:  # noqa: BLE001
            return f"错误: 列出 CLI 包失败: {e}"


register_handler(InstallCliPackageHandler())
register_handler(ListCliPackagesHandler())
