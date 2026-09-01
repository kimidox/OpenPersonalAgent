"""
统一路径管理器 - 集中管理所有路径逻辑

数据存储策略（开发/打包统一，消除双路径维护）:
┌─────────────────┬──────────────────────────────────────────────┐
│     数据类型     │ 路径                                          │
├─────────────────┼──────────────────────────────────────────────┤
│ 只读资源        │ dev: 项目根 / pkg: sys._MEIPASS                │
│ 应用级配置(.env)│ dev: 项目根 / pkg: 安装根/.env                 │
│ 用户数据        │ dev: 项目根/PersonalData（.env 可重定向）      │
│                 │ pkg: 安装根/PersonalData（不可写时回退APPDATA）│
│ 工作目录        │ 同用户数据（可用环境变量 PERSONAL_DATA_DIR 覆盖）│
└─────────────────┴──────────────────────────────────────────────┘

打包模式下"安装根目录"指 Tauri exe 所在目录（backend_service/ 的上一级），
PersonalData 随安装路径走，用户可直接把已有 PersonalData 放到安装根目录使用。
PERSONAL_DATA_DIR 环境变量可重定向工作数据目录（测试/多实例隔离）。
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
        """
        项目根目录 (开发: 项目根目录, 打包: 安装根目录)

        打包时 PyInstaller onedir 产物作为 Tauri 资源安装在 <安装目录>/backend_service/
        下（exe 位于 backend_service/ 内部），安装根目录需上跳一级取得，
        PersonalData/.env 等用户数据随安装根目录（Tauri exe 同级）走。
        """
        if self._is_frozen:
            exe_dir = Path(sys.executable).resolve().parent
            if exe_dir.name == "backend_service":
                return exe_dir.parent
            return exe_dir
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
        应用数据根目录（存放 .env 等应用级文件）
        开发/打包统一: %APPDATA%/OpenPersonalAgent/
        注意: 用户工作数据在 personal_data_dir (PersonalData子目录) 下
        """
        app_data = Path(os.environ.get('APPDATA', os.path.expanduser('~')))
        data_dir = app_data / self._app_name
        data_dir.mkdir(parents=True, exist_ok=True)
        return data_dir

    @property
    def personal_data_dir(self) -> Path:
        """
        PersonalData目录 - 统一存放用户工作数据
        开发: 优先读项目根 .env 的 PERSONAL_DATA_DIR，未配置则 项目根/PersonalData/
        打包: 安装根目录/PersonalData/（随安装路径走，避免 %APPDATA% 跨用户/跨目录不一致；
              安装目录不可写时回退 %APPDATA%/OpenPersonalAgent/PersonalData/）
        环境变量 PERSONAL_DATA_DIR 优先级最高（测试/多实例隔离）
        """
        override = os.environ.get('PERSONAL_DATA_DIR')
        if not override and not self._is_frozen:
            # 开发环境：从项目根 .env 读取用户数据目录配置
            override = self._read_env_value('PERSONAL_DATA_DIR')
        if override:
            data_dir = Path(override).expanduser().resolve()
        else:
            data_dir = self.project_root / self._personal_data_dir
        try:
            data_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            # 安装目录不可写（如装到 Program Files）→ 回退 %APPDATA%，避免启动即崩溃
            data_dir = self.user_data_dir / self._personal_data_dir
            data_dir.mkdir(parents=True, exist_ok=True)
        return data_dir

    def _read_env_value(self, key: str) -> str | None:
        """读取项目根 .env 中的指定键（不写入 os.environ，无 dotenv 时返回 None）。"""
        env_path = self.project_root / ".env"
        if not env_path.is_file():
            return None
        try:
            import dotenv
            value = dotenv.dotenv_values(dotenv_path=str(env_path)).get(key)
            return value.strip() if value and value.strip() else None
        except Exception:
            return None
    
    def get_bundled_resource(self, relative_path: str) -> Path:
        """获取打包资源路径"""
        return self.internal_dir / relative_path
    
    def get_user_config_path(self, filename: str) -> Path:
        """
        获取用户配置文件路径
        统一: %APPDATA%/OpenPersonalAgent/PersonalData/config/{filename}
        """
        config_dir = self.personal_data_dir / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        return config_dir / filename
    
    def get_database_path(self, filename: str = "app.db") -> Path:
        """
        获取数据库文件路径
        统一: %APPDATA%/OpenPersonalAgent/PersonalData/data/{filename}
        """
        data_dir = self.personal_data_dir / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        return data_dir / filename
    
    def get_skills_dir(self) -> Path:
        """
        获取Skills目录
        统一: %APPDATA%/OpenPersonalAgent/PersonalData/Skills/
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
        统一: %APPDATA%/OpenPersonalAgent/PersonalData/venv/
        """
        return self.personal_data_dir / "venv"
    
    def get_cache_dir(self) -> Path:
        """
        获取缓存目录
        统一: %APPDATA%/OpenPersonalAgent/PersonalData/cache/
        """
        cache_dir = self.personal_data_dir / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        return cache_dir
    
    def get_log_dir(self) -> Path:
        """
        获取日志目录
        统一: %APPDATA%/OpenPersonalAgent/PersonalData/logs/
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
