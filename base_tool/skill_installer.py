"""Skill 依赖检查与安装模块。

从 dispatch.py 拆分而来，负责：
- 检查 / 安装 skill 包的 Python 依赖
- 从 ZIP 包安装 Skill
- 获取虚拟环境已安装包列表
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import config
from logger import get_module_logger

from .environment import (
    check_installation_environment,
    _get_venv_python,
    _get_venv_pip,
)

logger = get_module_logger("ToolDispatch")


def _get_installed_packages() -> set[str]:
    """获取虚拟环境中已安装的包名集合"""
    # 延迟导入，避免与 dispatch.py 产生循环引用
    from .dispatch import _decode_output

    venv_python = _get_venv_python()
    if not venv_python:
        return set()
    try:
        result = subprocess.run(
            [venv_python, "-m", "pip", "list", "--format=freeze"],
            capture_output=True,
            text=False,
            timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0,
        )
        stdout = _decode_output(result.stdout or b"")
        packages = set()
        for line in stdout.strip().splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                pkg_name = line.split("==")[0].lower().replace("-", "_")
                packages.add(pkg_name)
        return packages
    except Exception:
        return set()


def _check_skill_dependencies(skill_dir: Path) -> tuple[bool, list[str], str]:
    """
    检查 skill 包的依赖是否已安装。
    返回 (是否需要安装, 需要安装的包列表, 错误消息)
    """
    requirements_file = skill_dir / "requirements.txt"
    if not requirements_file.exists():
        return False, [], ""
    
    required_packages = set()
    try:
        content = requirements_file.read_text(encoding="utf-8")
        for line in content.strip().splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                pkg_name = line.split("==")[0].split(">=")[0].split("<=")[0].split("[")[0]
                pkg_name = pkg_name.lower().replace("-", "_")
                required_packages.add(pkg_name)
    except Exception as e:
        return False, [], f"读取 requirements.txt 失败: {e}"
    
    if not required_packages:
        return False, [], ""
    
    installed = _get_installed_packages()
    to_install = required_packages - installed
    
    if not to_install:
        return False, [], ""
    
    return True, sorted(to_install), ""


def _install_skill_dependencies(skill_dir: Path) -> tuple[bool, str]:
    """
    安装 skill 包的依赖。
    返回 (成功与否, 消息)
    """
    # 延迟导入，避免与 dispatch.py 产生循环引用
    from .dispatch import _decode_output

    # 执行环境检查（不阻塞安装流程，仅记录状态）
    try:
        env_check = check_installation_environment()
        # 如果环境不满足要求，记录警告但不阻止安装
        if not env_check.get("pip_available"):
            logger.warning(f"环境检查警告: pip 不可用，可能导致依赖安装失败 (skill_dir: {skill_dir})")
        if not env_check.get("network_connected"):
            logger.warning(f"环境检查警告: 网络连接异常，可能导致依赖下载失败 (skill_dir: {skill_dir})")
    except Exception as e:
        # 环境检查失败不影响安装流程
        logger.debug(f"环境检查异常（已忽略）: {e}")

    requirements_file = skill_dir / "requirements.txt"
    if not requirements_file.exists():
        return True, ""

    required_packages = set()
    try:
        content = requirements_file.read_text(encoding="utf-8")
        for line in content.strip().splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                pkg_name = line.split("==")[0].split(">=")[0].split("<=")[0].split("[")[0]
                pkg_name = pkg_name.lower().replace("-", "_")
                required_packages.add(pkg_name)
    except Exception as e:
        return False, f"读取 requirements.txt 失败: {e}"

    if not required_packages:
        return True, ""

    installed = _get_installed_packages()
    to_install = required_packages - installed

    if not to_install:
        return True, ""

    pip_exe = _get_venv_pip()
    if not pip_exe:
        return False, "无法找到虚拟环境的 pip"

    try:
        result = subprocess.run(
            [pip_exe, "install", "-r", str(requirements_file)],
            capture_output=True,
            text=False,
            timeout=120,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0,
        )
        if result.returncode == 0:
            installed_names = ", ".join(sorted(to_install))
            return True, f"已安装依赖: {installed_names}"
        else:
            stderr = _decode_output(result.stderr or b"")
            return False, f"安装依赖失败: {stderr}"
    except subprocess.TimeoutExpired:
        return False, "安装依赖超时"
    except Exception as e:
        return False, f"安装依赖异常: {e}"


def check_skill_dependencies(skill_id: str, registry) -> tuple[bool, list[str], str]:
    """
    检查指定 skill 的依赖是否已安装。
    返回 (是否需要安装, 需要安装的包列表, 错误消息)
    """
    skill = registry.get(str(skill_id))
    if not skill:
        return False, [], f"未找到 Skill: {skill_id}"
    
    if not skill.relative_path.parent:
        return False, [], ""
    
    skill_dir = Path(config.WORKER_DIR) / skill.relative_path.parent
    return _check_skill_dependencies(skill_dir)


def install_skill_dependencies(skill_id: str, registry) -> tuple[bool, str]:
    """
    安装指定 skill 的依赖。
    返回 (成功与否, 消息)
    """
    skill = registry.get(str(skill_id))
    if not skill:
        return False, f"未找到 Skill: {skill_id}"
    
    if not skill.relative_path.parent:
        return True, ""
    
    skill_dir = Path(config.WORKER_DIR) / skill.relative_path.parent
    return _install_skill_dependencies(skill_dir)


def install_skill_from_zip(zip_path: str, registry, overwrite: bool = False) -> tuple[list[str], str]:
    """
    从 ZIP 包安装 Skill。
    
    Args:
        zip_path: ZIP 文件路径
        registry: SkillRegistry 实例
        overwrite: 是否覆盖已存在的 Skill
        
    Returns:
        (安装的 skill_id 列表, 错误消息)
    """
    try:
        from skill.skill_manager import get_manager
        mgr = get_manager()
        installed_ids = mgr.install_from_zip(zip_path, overwrite=overwrite)
        # 刷新 registry
        if registry and installed_ids:
            registry.reload()
        return installed_ids, ""
    except FileNotFoundError as e:
        return [], f"ZIP文件不存在: {zip_path}"
    except ValueError as e:
        return [], str(e)
    except FileExistsError as e:
        return [], f"Skill已存在: {e}，如需覆盖请设置 overwrite=True"
    except Exception as e:
        return [], f"安装ZIP包失败: {e}"
