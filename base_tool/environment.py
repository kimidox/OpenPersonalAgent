"""环境检查与虚拟环境管理模块。

从 dispatch.py 拆分而来，负责：
- pip / 网络可用性检测
- 操作系统类型识别
- 虚拟环境的创建与路径查询
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from logger import get_module_logger
from resource_path import paths

logger = get_module_logger("ToolDispatch")

_VENV_DIR = paths.get_venv_dir()


# ============================================================
# 环境检查
# ============================================================

def check_pip_available() -> bool:
    """
    检查 pip 是否可用。

    执行 `pip --version` 命令，检查 pip 是否正常工作。

    Returns:
        bool: pip 是否可用
    """
    import shutil

    # 优先检查虚拟环境中的 pip
    venv_pip = _get_venv_pip()
    if venv_pip and Path(venv_pip).exists():
        try:
            result = subprocess.run(
                [venv_pip, "--version"],
                capture_output=True,
                timeout=5,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0,
            )
            if result.returncode == 0:
                logger.debug(f"检测到虚拟环境 pip 可用: {venv_pip}")
                return True
        except Exception as e:
            logger.warning(f"虚拟环境 pip 检查失败: {e}")

    # 检查系统 pip
    pip_path = shutil.which("pip")
    if pip_path:
        try:
            result = subprocess.run(
                [pip_path, "--version"],
                capture_output=True,
                timeout=5,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0,
            )
            if result.returncode == 0:
                logger.debug(f"检测到系统 pip 可用: {pip_path}")
                return True
        except Exception as e:
            logger.warning(f"系统 pip 检查失败: {e}")

    # 检查 python -m pip
    python_path = shutil.which("python") or shutil.which("python3")
    if python_path:
        try:
            result = subprocess.run(
                [python_path, "-m", "pip", "--version"],
                capture_output=True,
                timeout=5,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0,
            )
            if result.returncode == 0:
                logger.debug(f"检测到 python -m pip 可用: {python_path}")
                return True
        except Exception as e:
            logger.warning(f"python -m pip 检查失败: {e}")

    logger.warning("未检测到可用的 pip")
    return False


def check_network_connection() -> bool:
    """
    检查网络连接状态。

    尝试访问 https://pypi.org 或执行 ping 命令检查网络连接。

    Returns:
        bool: 网络是否连接
    """
    import urllib.request
    import socket

    # 方法1: 尝试访问 PyPI
    test_urls = [
        "https://pypi.org",
        "https://mirrors.aliyun.com/pypi/simple/",  # 国内镜像
    ]

    for url in test_urls:
        try:
            request = urllib.request.Request(url, method='HEAD')
            request.add_header('User-Agent', 'Mozilla/5.0')
            urllib.request.urlopen(request, timeout=5)
            logger.debug(f"网络连接正常，成功访问: {url}")
            return True
        except urllib.error.URLError as e:
            logger.debug(f"访问 {url} 失败: {e}")
        except Exception as e:
            logger.debug(f"访问 {url} 异常: {e}")

    # 方法2: 使用 ping 命令检查网络（作为备用方案）
    try:
        # 检测操作系统
        os_type = detect_os_type()

        # 根据操作系统选择 ping 命令
        if os_type == "Windows":
            ping_cmd = ["ping", "-n", "1", "pypi.org"]
        else:  # Linux/Mac
            ping_cmd = ["ping", "-c", "1", "pypi.org"]

        result = subprocess.run(
            ping_cmd,
            capture_output=True,
            timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0,
        )

        if result.returncode == 0:
            logger.debug("网络连接正常（ping 测试成功）")
            return True
        else:
            logger.warning("网络连接异常（ping 测试失败）")
            return False

    except Exception as e:
        logger.warning(f"网络检查异常: {e}")
        return False


def detect_os_type() -> str:
    """
    检测操作系统类型。

    Returns:
        str: 操作系统类型，返回 "Windows"、"Linux" 或 "Mac"
    """
    import platform

    system = platform.system().lower()

    if system == "windows":
        return "Windows"
    elif system == "linux":
        return "Linux"
    elif system == "darwin":
        return "Mac"
    else:
        logger.warning(f"未识别的操作系统: {system}")
        return system.capitalize()


def check_installation_environment() -> dict:
    """
    执行完整的环境检查。

    Returns:
        dict: 包含各项环境检查结果的字典
    """
    import time

    start_time = time.time()

    results = {
        "os_type": detect_os_type(),
        "pip_available": check_pip_available(),
        "network_connected": check_network_connection(),
        "check_time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "elapsed_ms": 0,
    }

    # 计算耗时
    results["elapsed_ms"] = int((time.time() - start_time) * 1000)

    # 记录检查结果
    logger.info(
        f"环境检查完成 - "
        f"操作系统: {results['os_type']}, "
        f"pip可用: {results['pip_available']}, "
        f"网络连接: {results['network_connected']}, "
        f"耗时: {results['elapsed_ms']}ms"
    )

    # 如果环境不满足要求，记录警告
    if not results["pip_available"]:
        logger.warning("pip 不可用，可能导致依赖安装失败")

    if not results["network_connected"]:
        logger.warning("网络连接异常，可能导致下载安装脚本失败")

    return results


# ============================================================
# 虚拟环境管理
# ============================================================

def _find_system_python() -> str | None:
    """
    查找系统安装的 Python 解释器（非虚拟环境）。
    始终查找系统级 Python，避免使用虚拟环境中的 Python 来创建新虚拟环境，
    因为虚拟环境可能缺少 ensurepip 模块导致创建的 venv 没有 pip。
    """
    import shutil
    
    candidate_names = ["python", "python3", "py"]
    
    for name in candidate_names:
        python_path = shutil.which(name)
        if python_path and python_path.lower().find("\\venv\\") == -1 and python_path.lower().find("\\virtualenvs\\") == -1:
            return python_path
    
    common_paths = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Python" / "Python311" / "python.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Python" / "python.exe",
        Path(os.environ.get("PROGRAMFILES", "")) / "Python" / "python.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Python" / "python.exe",
    ]
    for p in common_paths:
        if p.exists() and p.is_file():
            return str(p)
    
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Python\PythonCore") as key:
            i = 0
            while True:
                version = winreg.EnumKey(key, i)
                subkey = winreg.OpenKey(key, version)
                install_path, _ = winreg.QueryValueEx(subkey, "InstallPath")
                python_exe = Path(install_path) / "python.exe"
                if python_exe.exists():
                    return str(python_exe)
                i += 1
    except (ImportError, OSError, FileNotFoundError):
        pass
    
    return None


def _ensure_venv_exists() -> bool:
    """确保 PersonalData 下存在虚拟环境,如果不存在则创建"""
    if _VENV_DIR.exists() and (_VENV_DIR / "Scripts" / "python.exe").exists():
        return True
    try:
        system_python = _find_system_python()
        if not system_python:
            return False
        
        subprocess.run(
            [system_python, "-m", "venv", str(_VENV_DIR)],
            capture_output=True,
            timeout=60,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0,
        )
        
        venv_python = str(_VENV_DIR / "Scripts" / "python.exe")
        if not Path(venv_python).exists():
            return False
        
        pip_exe = _VENV_DIR / "Scripts" / "pip.exe"
        if not pip_exe.exists():
            import urllib.request
            import tempfile
            
            get_pip_url = "https://bootstrap.pypa.io/get-pip.py"
            
            with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False, encoding='utf-8') as f:
                temp_file = f.name
            
            try:
                urllib.request.urlretrieve(get_pip_url, temp_file)
                subprocess.run(
                    [venv_python, temp_file],
                    capture_output=True,
                    timeout=120,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0,
                )
            except Exception as e:
                logger.error(f"安装pip失败: {e}")
            finally:
                try:
                    os.unlink(temp_file)
                except:
                    pass
        
        return True
    except Exception as e:
        logger.error(f"创建虚拟环境异常: {e}")
        return False


def _get_venv_python() -> str | None:
    """获取虚拟环境中的 Python 可执行文件路径"""
    if not _ensure_venv_exists():
        return None
    return str(_VENV_DIR / "Scripts" / "python.exe")


def _get_venv_activate_script() -> str | None:
    """获取激活虚拟环境的脚本路径（不包含call关键字）"""
    if not _ensure_venv_exists():
        return None
    activate_script = _VENV_DIR / "Scripts" / "activate.bat"
    if activate_script.exists():
        return str(activate_script)
    return None


def _get_venv_pip() -> str | None:
    """获取虚拟环境中的 pip 可执行文件路径"""
    if not _ensure_venv_exists():
        return None
    pip_exe = _VENV_DIR / "Scripts" / "pip.exe"
    if pip_exe.exists():
        return str(pip_exe)
    return None
