"""
Windows 自启动模块

实现 Windows 系统开机自启动功能，使用注册表方式：
HKCU\Software\Microsoft\Windows\CurrentVersion\Run
"""
import sys
import os
import winreg
from pathlib import Path
from typing import Optional

from resource_path import paths
from logger import get_module_logger

logger = get_module_logger("autostart")

APP_NAME = "OpenPersonalAgent"
REGISTRY_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
BACKGROUND_ARG = "--background"


def _get_executable_path() -> str:
    """
    获取可执行程序路径
    
    打包环境: 返回 exe 文件路径
    开发环境: 返回 python 解释器路径
    
    Returns:
        程序路径字符串
    """
    if paths.is_frozen:
        return sys.executable
    else:
        main_script = paths.project_root / "main.py"
        if main_script.exists():
            return f'"{sys.executable}" "{main_script}"'
        return f'"{sys.executable}"'


def _get_autostart_command() -> str:
    """
    获取自启动命令
    
    Returns:
        完整的自启动命令字符串
    """
    exe_path = _get_executable_path()
    return f'{exe_path} {BACKGROUND_ARG}'


def enable_autostart() -> bool:
    """
    启用自启动
    
    在注册表中添加自启动项，程序将在用户登录时自动启动。
    启动时会附带 --background 参数标记后台模式。
    
    Returns:
        bool: True 表示成功启用，False 表示启用失败
    """
    try:
        command = _get_autostart_command()
        
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            REGISTRY_KEY,
            0,
            winreg.KEY_SET_VALUE
        )
        
        try:
            winreg.SetValueEx(
                key,
                APP_NAME,
                0,
                winreg.REG_SZ,
                command
            )
            logger.info(f"已启用自启动: {APP_NAME} -> {command}")
            return True
        finally:
            winreg.CloseKey(key)
            
    except PermissionError as e:
        logger.error(f"启用自启动失败，权限不足: {e}")
        return False
    except Exception as e:
        logger.exception(f"启用自启动失败: {e}")
        return False


def disable_autostart() -> bool:
    """
    禁用自启动
    
    从注册表中移除自启动项。
    
    Returns:
        bool: True 表示成功禁用，False 表示禁用失败
    """
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            REGISTRY_KEY,
            0,
            winreg.KEY_SET_VALUE
        )
        
        try:
            winreg.DeleteValue(key, APP_NAME)
            logger.info(f"已禁用自启动: {APP_NAME}")
            return True
        except FileNotFoundError:
            logger.info(f"自启动项不存在，无需禁用: {APP_NAME}")
            return True
        finally:
            winreg.CloseKey(key)
            
    except PermissionError as e:
        logger.error(f"禁用自启动失败，权限不足: {e}")
        return False
    except Exception as e:
        logger.exception(f"禁用自启动失败: {e}")
        return False


def is_autostart_enabled() -> bool:
    """
    检查是否已启用自启动
    
    Returns:
        bool: True 表示已启用自启动，False 表示未启用
    """
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            REGISTRY_KEY,
            0,
            winreg.KEY_READ
        )
        
        try:
            value, _ = winreg.QueryValueEx(key, APP_NAME)
            winreg.CloseKey(key)
            
            expected_command = _get_autostart_command()
            if value == expected_command:
                logger.debug(f"自启动已启用: {APP_NAME}")
                return True
            else:
                logger.debug(f"自启动命令不匹配，当前: {value}, 期望: {expected_command}")
                return True
        except FileNotFoundError:
            winreg.CloseKey(key)
            logger.debug(f"自启动未启用: {APP_NAME}")
            return False
        except Exception:
            winreg.CloseKey(key)
            return False
            
    except Exception as e:
        logger.exception(f"检查自启动状态失败: {e}")
        return False


def get_autostart_status() -> dict:
    """
    获取自启动详细状态信息
    
    Returns:
        dict: 包含状态信息的字典
            - enabled: bool, 是否已启用
            - command: str, 当前注册的命令（如果已启用）
            - expected_command: str, 期望的命令
            - executable_path: str, 可执行程序路径
    """
    result = {
        "enabled": False,
        "command": None,
        "expected_command": _get_autostart_command(),
        "executable_path": _get_executable_path()
    }
    
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            REGISTRY_KEY,
            0,
            winreg.KEY_READ
        )
        
        try:
            value, _ = winreg.QueryValueEx(key, APP_NAME)
            result["command"] = value
            result["enabled"] = True
        except FileNotFoundError:
            pass
        finally:
            winreg.CloseKey(key)
            
    except Exception as e:
        logger.exception(f"获取自启动状态失败: {e}")
    
    return result