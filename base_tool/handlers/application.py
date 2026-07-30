"""application 工具处理器

包含2个Handler类:
- StartApplicationHandler
- ListInstalledAppsHandler
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from .base import ToolHandler
from ..context import ToolContext
from . import register_handler


class StartApplicationHandler(ToolHandler):
    """启动应用程序工具处理器"""

    @property
    def name(self) -> str:
        """返回工具名称"""
        return "start_application"

    def execute(self, args: dict, ctx: ToolContext, registry) -> str:
        """启动应用程序，支持按名称、路径或URL方式启动

        Args:
            args: 工具参数字典，支持 app、method、wait_time、args
            ctx: ToolContext 执行上下文
            registry: 工具注册表

        Returns:
            工具执行结果的字符串
        """
        from ..dispatch import _ensure_uia, UIA_AVAILABLE, get_controller

        app = args.get("app", "")
        method = args.get("method", "by_name")
        wait_time = args.get("wait_time", 2.0)
        app_args = args.get("args", "")

        # 检查停止条件
        controller = get_controller()
        check_result = controller.check_before_operation(f"start_{app}")
        if not check_result.get("can_continue"):
            return f"【任务终止】{check_result.get('stop_reason', '达到停止条件')}\n\n请不要再继续尝试，应重新规划任务或放弃。"

        if not app:
            return "错误: 缺少 app 参数"

        try:
            import webbrowser
            import time

            if method == "by_url":
                # 通过URL启动（打开浏览器）
                webbrowser.open(app)
                if wait_time > 0:
                    time.sleep(wait_time)
                return f"已打开URL: {app}\n\n✓ 操作成功。如果任务已完成，请调用 finish 结束。"

            elif method == "by_path":
                # 通过路径启动
                # 判断是否是快捷方式
                if app.lower().endswith('.lnk'):
                    # 快捷方式使用 os.startfile
                    os.startfile(app)
                else:
                    # 可执行文件使用 subprocess
                    cmd = [app]
                    if app_args:
                        cmd.append(app_args)
                    subprocess.Popen(cmd, shell=False)
                if wait_time > 0:
                    time.sleep(wait_time)

                # 【状态验证】验证启动结果
                if UIA_AVAILABLE:
                    from ..dispatch import ActionExecutor
                    executor = ActionExecutor()
                    verify_result = executor.verify_start_result(app, timeout=wait_time + 2)
                    if verify_result.get("success"):
                        return f"已启动程序: {app}\n验证: {verify_result.get('reason', '已验证')}\n\n✓ 操作成功。如果任务已完成，请调用 finish 结束。"
                    else:
                        # 记录失败
                        failure_info = controller.record_failure(f"start_{app}", verify_result.get("reason", "启动验证失败"))
                        return f"警告: 程序已启动但验证失败: {verify_result.get('reason', '')}\n\n{failure_info.get('stop_reason', '')}\n\n【失败统计】{controller.failure_counter.get_status_summary()}"

                return f"已启动程序: {app}\n\n✓ 操作成功。如果任务已完成，请调用 finish 结束。"

            elif method == "by_name":
                # 通过程序名启动
                if sys.platform == "win32":
                    # Windows: 尝试多种方式启动

                    # 方式1: 尝试 os.startfile（适用于快捷方式和PATH中的程序）
                    try:
                        os.startfile(app)
                        if wait_time > 0:
                            time.sleep(wait_time)

                        # 【状态验证】验证启动结果
                        if _ensure_uia():
                            from ..dispatch import ActionExecutor
                            executor = ActionExecutor()
                            verify_result = executor.verify_start_result(app, timeout=wait_time + 2)
                            if verify_result.get("success"):
                                status_summary = controller.get_status_summary()
                                return f"已启动程序: {app}\n验证: {verify_result.get('reason', '已验证')}\n\n【任务状态】{status_summary}\n\n✓ 操作成功。如果任务已完成，请调用 finish 结束。"
                            else:
                                # 验证失败但程序可能已启动
                                status_summary = controller.get_status_summary()
                                return f"已启动程序: {app}\n警告: 验证失败 - {verify_result.get('reason', '')}\n\n【任务状态】{status_summary}\n\n✓ 操作成功。如果任务已完成，请调用 finish 结束。"

                        return f"已启动程序: {app}\n\n✓ 操作成功。如果任务已完成，请调用 finish 结束。"
                    except Exception:
                        pass

                    # 方式2: 使用 subprocess.Popen + shell=True
                    try:
                        cmd = app
                        if app_args:
                            cmd = f"{app} {app_args}"
                        subprocess.Popen(cmd, shell=True)
                        if wait_time > 0:
                            time.sleep(wait_time)
                        return f"已启动程序: {app}\n\n✓ 操作成功。如果任务已完成，请调用 finish 结束。"
                    except Exception:
                        pass

                    # 方式3: 使用 cmd /c start
                    try:
                        cmd = f'cmd /c start "" "{app}"'
                        if app_args:
                            cmd = f'cmd /c start "" "{app}" "{app_args}"'
                        subprocess.run(cmd, shell=True, timeout=10)
                        if wait_time > 0:
                            time.sleep(wait_time)
                        return f"已启动程序: {app}\n\n✓ 操作成功。如果任务已完成，请调用 finish 结束。"
                    except Exception as e:
                        # 记录失败
                        failure_info = controller.record_failure(f"start_{app}", str(e))
                        return f"错误: 所有启动方式都失败: {e}\n\n{failure_info.get('stop_reason', '')}\n\n【失败统计】{controller.failure_counter.get_status_summary()}"
                else:
                    # Linux/Mac: 直接执行
                    cmd = [app]
                    if app_args:
                        cmd.append(app_args)
                    subprocess.Popen(cmd)
                    if wait_time > 0:
                        time.sleep(wait_time)
                    return f"已启动程序: {app}\n\n✓ 操作成功。如果任务已完成，请调用 finish 结束。"

            else:
                return f"错误: 未知的启动方式: {method}"

        except Exception as e:
            # 记录失败
            failure_info = controller.record_failure(f"start_{app}", str(e))
            return f"错误: 启动程序失败: {e}\n\n{failure_info.get('stop_reason', '')}\n\n【失败统计】{controller.failure_counter.get_status_summary()}"


class ListInstalledAppsHandler(ToolHandler):
    """列出已安装应用工具处理器"""

    @property
    def name(self) -> str:
        """返回工具名称"""
        return "list_installed_apps"

    def execute(self, args: dict, ctx: ToolContext, registry) -> str:
        """列出系统中已安装的应用程序，支持关键字过滤

        Args:
            args: 工具参数字典，支持 filter、max_results
            ctx: ToolContext 执行上下文
            registry: 工具注册表

        Returns:
            工具执行结果的字符串
        """
        filter_keyword = args.get("filter", "")
        max_results = args.get("max_results", 50)

        try:

            apps = []

            # 1. 查询 Windows 开始菜单快捷方式（并解析目标路径）
            if sys.platform == "win32":
                start_menu_paths = [
                    Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs",
                    Path(os.environ.get("PROGRAMDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs",
                ]

                for start_path in start_menu_paths:
                    if start_path.exists():
                        for lnk_file in start_path.rglob("*.lnk"):
                            try:
                                name = lnk_file.stem
                                if filter_keyword and filter_keyword.lower() not in name.lower():
                                    continue

                                # 解析快捷方式获取目标路径
                                target_path = ""
                                try:
                                    # 使用 PowerShell 解析快捷方式
                                    ps_script = f'''
                                    $shell = New-Object -ComObject WScript.Shell
                                    $shortcut = $shell.CreateShortcut("{str(lnk_file)}")
                                    $shortcut.TargetPath
                                    '''
                                    result = subprocess.run(
                                        ["powershell", "-Command", ps_script],
                                        capture_output=True,
                                        text=True,
                                        timeout=5,
                                    )
                                    if result.returncode == 0 and result.stdout.strip():
                                        target_path = result.stdout.strip()
                                except Exception:
                                    pass

                                apps.append({
                                    "name": name,
                                    "shortcut_path": str(lnk_file),
                                    "target_path": target_path,  # 实际启动路径
                                    "type": "shortcut",
                                    "launch_command": target_path if target_path else str(lnk_file),
                                })
                                if len(apps) >= max_results:
                                    break
                            except Exception:
                                pass

            # 2. 查询 PATH 环境变量中的可执行程序
            path_env = os.environ.get("PATH", "")
            path_dirs = path_env.split(os.pathsep)

            common_apps = {
                "notepad": ("记事本", "C:\\Windows\\notepad.exe"),
                "calc": ("计算器", "calc.exe"),
                "mspaint": ("画图", "mspaint.exe"),
                "explorer": ("文件资源管理器", "explorer.exe"),
                "cmd": ("命令提示符", "cmd.exe"),
                "powershell": ("PowerShell", "powershell.exe"),
                "chrome": ("Chrome浏览器", "chrome.exe"),
                "firefox": ("Firefox浏览器", "firefox.exe"),
                "msedge": ("Edge浏览器", "msedge.exe"),
                "excel": ("Excel", "excel.exe"),
                "word": ("Word", "winword.exe"),
                "powerpnt": ("PowerPoint", "powerpnt.exe"),
                "outlook": ("Outlook", "outlook.exe"),
                "code": ("VS Code", "code.exe"),
                "notepad++": ("Notepad++", "notepad++.exe"),
                "python": ("Python", "python.exe"),
                "git": ("Git", "git.exe"),
            }

            for path_dir in path_dirs:
                if not path_dir:
                    continue
                try:
                    for exe_file in Path(path_dir).glob("*.exe"):
                        exe_name = exe_file.stem.lower()
                        display_name, default_launch = common_apps.get(exe_name, (exe_name, exe_name))
                        if filter_keyword:
                            if filter_keyword.lower() not in exe_name.lower() and filter_keyword.lower() not in display_name.lower():
                                continue
                        apps.append({
                            "name": display_name,
                            "exe_name": exe_name,
                            "path": str(exe_file),
                            "type": "exe",
                            "in_path": True,
                            "launch_command": exe_name,  # 可以直接用程序名启动
                        })
                        if len(apps) >= max_results:
                            break
                except Exception:
                    pass

            # 3. 查询注册表中的已安装程序（Windows）
            if sys.platform == "win32" and len(apps) < max_results:
                try:
                    # 使用 PowerShell 查询注册表，获取更详细的路径信息
                    ps_script = '''
                    Get-ItemProperty HKLM:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*,
                                     HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\* |
                    Where-Object { $_.DisplayName } |
                    Select-Object DisplayName, InstallLocation, DisplayIcon, UninstallString |
                    ConvertTo-Json -Depth 1
                    '''
                    result = subprocess.run(
                        ["powershell", "-Command", ps_script],
                        capture_output=True,
                        text=True,
                        timeout=30,
                    )
                    if result.returncode == 0 and result.stdout:
                        reg_apps = json.loads(result.stdout)
                        if isinstance(reg_apps, list):
                            for app in reg_apps:
                                name = app.get("DisplayName", "")
                                location = app.get("InstallLocation", "")
                                icon = app.get("DisplayIcon", "")
                                uninstall_string = app.get("UninstallString", "")

                                if filter_keyword and filter_keyword.lower() not in name.lower():
                                    continue

                                # 尝试从安装路径推断可执行文件
                                exe_path = ""
                                if location:
                                    try:
                                        # 查找安装目录下的exe文件
                                        for exe in Path(location).glob("*.exe"):
                                            exe_path = str(exe)
                                            break
                                    except Exception:
                                        pass

                                # 尝试从图标路径推断
                                if not exe_path and icon:
                                    exe_path = icon

                                apps.append({
                                    "name": name,
                                    "install_location": location,
                                    "exe_path": exe_path,
                                    "icon": icon,
                                    "type": "installed",
                                    "launch_command": exe_path if exe_path else f"需手动查找: {location}",
                                })
                                if len(apps) >= max_results:
                                    break
                except Exception:
                    pass

            # 去重并格式化输出
            seen_names = set()
            unique_apps = []
            for app in apps:
                name_lower = app.get("name", "").lower()
                if name_lower not in seen_names:
                    seen_names.add(name_lower)
                    unique_apps.append(app)

            # 格式化输出（包含启动路径）
            output_lines = [f"找到 {len(unique_apps)} 个已安装的应用程序:"]
            output_lines.append("")
            output_lines.append("【程序列表】")
            for i, app in enumerate(unique_apps[:max_results], 1):
                name = app.get("name", "")
                app_type = app.get("type", "")
                launch_command = app.get("launch_command", "")

                if app_type == "exe":
                    path = app.get("path", "")
                    output_lines.append(f"{i}. {name}")
                    output_lines.append(f"   - 类型: PATH可执行文件")
                    output_lines.append(f"   - 路径: {path}")
                    output_lines.append(f"   - 启动命令: start_application(app='{launch_command}')")
                elif app_type == "shortcut":
                    shortcut_path = app.get("shortcut_path", "")
                    target_path = app.get("target_path", "")
                    output_lines.append(f"{i}. {name}")
                    output_lines.append(f"   - 类型: 快捷方式")
                    output_lines.append(f"   - 快捷方式路径: {shortcut_path}")
                    output_lines.append(f"   - 目标路径: {target_path}")
                    if target_path:
                        output_lines.append(f"   - 启动命令: start_application(app='{target_path}', method='by_path')")
                    else:
                        output_lines.append(f"   - 启动命令: start_application(app='{shortcut_path}', method='by_path')")
                elif app_type == "installed":
                    location = app.get("install_location", "")
                    exe_path = app.get("exe_path", "")
                    output_lines.append(f"{i}. {name}")
                    output_lines.append(f"   - 类型: 已安装程序")
                    output_lines.append(f"   - 安装路径: {location}")
                    output_lines.append(f"   - 可执行文件: {exe_path}")
                    if exe_path and exe_path.endswith('.exe'):
                        output_lines.append(f"   - 启动命令: start_application(app='{exe_path}', method='by_path')")
                    else:
                        output_lines.append(f"   - 启动命令: 需手动查找可执行文件")
                else:
                    output_lines.append(f"{i}. {name}")
                output_lines.append("")

            output_lines.append("【建议】")
            output_lines.append("根据用户意图选择合适的程序，复制上面的启动命令即可启动程序。")

            return "\n".join(output_lines) + "\n\n✓ 操作成功。如果任务已完成，请调用 finish 结束。"

        except Exception as e:
            return f"错误: 查询已安装程序失败: {e}"


# 注册所有 Handler
register_handler(StartApplicationHandler())
register_handler(ListInstalledAppsHandler())
