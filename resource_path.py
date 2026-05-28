"""
统一路径管理器 - 集中管理所有路径逻辑

数据存储策略:
┌─────────────────┬─────────────────────┬──────────────────────────────────┐
│     数据类型     │     开发环境         │            打包环境               │
├─────────────────┼─────────────────────┼──────────────────────────────────┤
│ 只读资源        │ 项目根目录           │ sys._MEIPASS (打包内部)           │
│ 用户数据        │ PersonalData/       │ %APPDATA%/App/PersonalData/      │
│ 工作目录        │ PersonalData/       │ %APPDATA%/App/PersonalData/      │
└─────────────────┴─────────────────────┴──────────────────────────────────┘
"""
import sys
import os
from pathlib import Path
from typing import Optional


class PathManager:
    """统一路径管理器 - 单例模式"""
    
    _instance: Optional['PathManager'] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        
        self._is_frozen = getattr(sys, 'frozen', False)
        self._app_name = "OpenPersonalAgent"
        self._personal_data_dir = "PersonalData"
        
    @property
    def is_frozen(self) -> bool:
        """是否为打包环境"""
        return self._is_frozen
    
    @property
    def project_root(self) -> Path:
        """项目根目录 (开发: 项目根目录, 打包: exe所在目录)"""
        if self._is_frozen:
            return Path(sys.executable).resolve().parent
        return Path(__file__).resolve().parent
    
    @property
    def internal_dir(self) -> Path:
        """打包内部目录 (开发: 项目根目录, 打包: sys._MEIPASS)"""
        if self._is_frozen:
            return Path(sys._MEIPASS)
        return Path(__file__).resolve().parent
    
    @property
    def user_data_dir(self) -> Path:
        """
        用户数据根目录
        开发: 项目根目录/PersonalData/
        打包: %APPDATA%/OpenPersonalAgent/
        注意: 打包后实际数据在 personal_data_dir (PersonalData子目录) 下
        """
        if self._is_frozen:
            app_data = Path(os.environ.get('APPDATA', os.path.expanduser('~')))
            data_dir = app_data / self._app_name
            data_dir.mkdir(parents=True, exist_ok=True)
            return data_dir
        return self.project_root / self._personal_data_dir
    
    @property
    def personal_data_dir(self) -> Path:
        """
        PersonalData目录 - 统一存放用户工作数据
        开发: 项目根目录/PersonalData/
        打包: %APPDATA%/OpenPersonalAgent/PersonalData/
        """
        if self._is_frozen:
            data_dir = self.user_data_dir / self._personal_data_dir
        else:
            data_dir = self.project_root / self._personal_data_dir
        data_dir.mkdir(parents=True, exist_ok=True)
        return data_dir
    
    def get_bundled_resource(self, relative_path: str) -> Path:
        """获取打包资源路径"""
        return self.internal_dir / relative_path
    
    def get_user_config_path(self, filename: str) -> Path:
        """
        获取用户配置文件路径
        开发: PersonalData/config/{filename}
        打包: %APPDATA%/OpenPersonalAgent/PersonalData/config/{filename}
        """
        config_dir = self.personal_data_dir / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        return config_dir / filename
    
    def get_database_path(self, filename: str = "app.db") -> Path:
        """
        获取数据库文件路径
        开发: PersonalData/data/{filename}
        打包: %APPDATA%/OpenPersonalAgent/PersonalData/data/{filename}
        """
        data_dir = self.personal_data_dir / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        return data_dir / filename
    
    def get_skills_dir(self) -> Path:
        """
        获取Skills目录
        开发: PersonalData/Skills/
        打包: %APPDATA%/OpenPersonalAgent/PersonalData/Skills/
        """
        skills_dir = self.personal_data_dir / "Skills"
        skills_dir.mkdir(parents=True, exist_ok=True)
        return skills_dir
    
    def get_builtin_skills_dir(self) -> Path:
        """
        获取内置Skills目录（只读）
        开发: 项目根目录/Skills/
        打包: sys._MEIPASS/Skills/
        """
        return self.internal_dir / "Skills"
    
    def get_venv_dir(self) -> Path:
        """
        获取虚拟环境目录
        开发: PersonalData/venv/
        打包: %APPDATA%/OpenPersonalAgent/PersonalData/venv/
        """
        return self.personal_data_dir / "venv"
    
    def get_cache_dir(self) -> Path:
        """
        获取缓存目录
        开发: PersonalData/cache/
        打包: %APPDATA%/OpenPersonalAgent/PersonalData/cache/
        """
        cache_dir = self.personal_data_dir / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        return cache_dir
    
    def get_log_dir(self) -> Path:
        """
        获取日志目录
        开发: PersonalData/logs/
        打包: %APPDATA%/OpenPersonalAgent/PersonalData/logs/
        """
        log_dir = self.personal_data_dir / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        return log_dir
    
    def get_env_file(self) -> Path:
        """
        获取环境配置文件
        开发: 项目根目录/.env
        打包: exe目录/.env 或 打包资源
        """
        env_path = self.project_root / ".env"
        if not env_path.exists() and self._is_frozen:
            bundled = self.get_bundled_resource(".env")
            if bundled.exists():
                return bundled
        return env_path


paths = PathManager()


def is_frozen() -> bool:
    """兼容旧接口 - 是否为打包环境"""
    return paths.is_frozen


def get_app_dir() -> Path:
    """兼容旧接口 - 获取项目根目录"""
    return paths.project_root


def get_app_data_path() -> Path:
    """兼容旧接口 - 获取用户数据目录"""
    return paths.user_data_dir


def get_bundled_resource(relative_path: str) -> Path:
    """兼容旧接口 - 获取打包资源路径"""
    return paths.get_bundled_resource(relative_path)


def _internal_dir() -> Path:
    """兼容旧接口 - 获取打包内部目录"""
    return paths.internal_dir
