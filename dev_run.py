"""
Flet 开发模式启动脚本

===========================================
Flet 热重载功能使用说明
===========================================

Flet 支持热重载功能，可以在修改代码后自动刷新界面，无需手动重启应用。

## 启动方式

### 方式 1: 使用 Flet CLI 命令（推荐）
在项目根目录下运行以下命令：

    flet run --recursive ui_flet/main.py

参数说明：
- `run`: Flet 运行命令
- `--recursive` 或 `-r`: 监视脚本所在目录及子目录的更改
- `ui_flet/main.py`: 应用入口文件

### 方式 2: 直接运行此脚本
    python dev_run.py

## 热重载特性

- 修改 UI 布局参数（如间距、颜色、大小）后自动刷新
- 修改组件属性后自动更新
- 保存文件后立即看到效果

## 注意事项

1. 此脚本仅用于开发环境，生产环境请使用 ui_flet/main.py 的原有启动方式
2. 热重载不会重新执行全局作用域的代码，只重新加载 main 函数
3. 如果修改了全局配置或导入模块，可能需要手动重启应用
4. 多进程 IPC（悬浮球）部分在热重载时可能需要重新启动才能生效

## 生产环境启动方式

生产环境仍使用 ui_flet/main.py 中的 ft.run() 方式：
    python ui_flet/main.py

===========================================
"""

import subprocess
import sys
from pathlib import Path

from logger import get_module_logger

logger = get_module_logger("dev_run")


def print_development_banner():
    """打印开发模式横幅"""
    banner = """
╔═══════════════════════════════════════════════════════════════╗
║                   Flet 开发模式 - 热重载已启用                  ║
╠═══════════════════════════════════════════════════════════════╣
║  监视目录: ui_flet/ 及其子目录                                  ║
║  修改代码后界面将自动刷新                                        ║
║  按 Ctrl+C 停止应用                                             ║
╚═══════════════════════════════════════════════════════════════╝
"""
    logger.info(banner)


def main():
    """启动开发模式"""
    print_development_banner()
    logger.info("正在启动 Flet 应用（开发模式）...")

    # 获取项目根目录
    project_root = Path(__file__).resolve().parent

    # 入口文件路径
    entry_point = project_root / "ui_flet" / "main.py"

    if not entry_point.exists():
        logger.error("入口文件不存在: %s", entry_point)
        sys.exit(1)

    # 构建命令
    # 使用 flet run --recursive 启用热重载
    # 注意：flet-cli 通过 console_scripts 安装，应直接调用 flet 命令
    # 而不是 python -m flet
    import shutil

    # 查找 flet 命令
    flet_cmd = shutil.which("flet")

    if flet_cmd:
        # 使用 flet 命令（推荐）
        cmd = [
            flet_cmd, "run",
            "--recursive",  # 监视子目录
            str(entry_point)
        ]
    else:
        # 回退到使用 Python 模块方式
        cmd = [
            sys.executable, "-m", "flet_cli", "run",
            "--recursive",
            str(entry_point)
        ]

    logger.info("执行命令: %s", " ".join(cmd))

    try:
        # 运行 Flet 开发服务器
        subprocess.run(cmd, cwd=str(project_root))
    except KeyboardInterrupt:
        logger.info("应用已停止")
    except Exception as e:
        logger.error("启动失败: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()