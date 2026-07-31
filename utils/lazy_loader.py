"""
延迟加载工具
用于延迟加载重型依赖，减少启动时间和内存占用
"""
import importlib
import logging
from typing import Optional, Any, Callable
from functools import wraps


logger = logging.getLogger(__name__)


class LazyLoader:
    """
    延迟加载重型依赖的管理器
    
    使用示例:
        scipy_loader = LazyLoader('scipy.signal', 'scipy')
        
        def process_audio():
            signal = scipy_loader.load()
            if signal:
                return signal.resample(audio_data, n_samples)
            else:
                # 降级方案
                return fallback_resample(audio_data)
    """
    
    def __init__(self, module_name: str, pip_name: Optional[str] = None):
        """
        初始化延迟加载器
        
        Args:
            module_name: Python模块名（如'scipy.signal'）
            pip_name: pip包名（如'scipy'），如果与模块名不同
        """
        self.module_name = module_name
        self.pip_name = pip_name or module_name.split('.')[0]
        self._module: Optional[Any] = None
        self._load_attempted = False
    
    def load(self) -> Optional[Any]:
        """
        加载模块，如果失败返回None
        
        Returns:
            Optional[Any]: 加载的模块对象，失败返回None
        """
        if self._module is not None:
            return self._module
        
        if self._load_attempted:
            # 已经尝试过加载，避免重复日志
            return None
        
        self._load_attempted = True
        
        try:
            self._module = importlib.import_module(self.module_name)
            logger.info(f"成功延迟加载模块: {self.module_name}")
            return self._module
        except ImportError as e:
            logger.warning(f"模块 {self.module_name} 未安装: {e}")
            logger.info(f"安装方法: pip install {self.pip_name}")
            return None
        except Exception as e:
            logger.error(f"加载模块 {self.module_name} 时发生错误: {e}")
            return None
    
    def is_available(self) -> bool:
        """
        检查模块是否可用（不加载）
        
        Returns:
            bool: 模块是否可用
        """
        return self.load() is not None
    
    def __getattr__(self, name: str) -> Any:
        """
        代理访问模块属性
        
        Args:
            name: 属性名
            
        Returns:
            Any: 模块属性
            
        Raises:
            ImportError: 如果模块不可用
        """
        module = self.load()
        if module is None:
            raise ImportError(
                f"模块 {self.module_name} 不可用。"
                f"请安装: pip install {self.pip_name}"
            )
        return getattr(module, name)
    
    def __repr__(self) -> str:
        status = "已加载" if self._module else "未加载"
        return f"<LazyLoader: {self.module_name} ({status})>"


def lazy_import(module_name: str, pip_name: Optional[str] = None):
    """
    延迟导入装饰器
    
    用于函数级别的延迟导入
    
    使用示例:
        @lazy_import('scipy.signal', 'scipy')
        def resample_audio(audio_data, target_sr, scipy_signal=None):
            return scipy_signal.resample(audio_data, target_sr)
    
    Args:
        module_name: Python模块名
        pip_name: pip包名（可选）
        
    Returns:
        装饰器函数
    """
    loader = LazyLoader(module_name, pip_name)
    
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            # 将加载的模块注入到函数参数中
            if loader.module_name.split('.')[-1] not in kwargs:
                module = loader.load()
                if module:
                    # 注入模块到kwargs
                    param_name = loader.module_name.split('.')[-1]
                    kwargs[param_name] = module
            
            return func(*args, **kwargs)
        
        return wrapper
    
    return decorator


# 预定义的延迟加载器实例
scipy_signal = LazyLoader('scipy.signal', 'scipy')
cv2_loader = LazyLoader('cv2', 'opencv-python')
pandas_loader = LazyLoader('pandas', 'pandas')


def get_scipy_signal():
    """
    获取scipy.signal模块（延迟加载）
    
    Returns:
        scipy.signal模块，如果不可用返回None
    """
    return scipy_signal.load()


def get_cv2():
    """
    获取cv2模块（延迟加载）
    
    Returns:
        cv2模块，如果不可用返回None
    """
    return cv2_loader.load()


def get_pandas():
    """
    获取pandas模块（延迟加载）
    
    Returns:
        pandas模块，如果不可用返回None
    """
    return pandas_loader.load()


if __name__ == '__main__':
    # 测试延迟加载
    print("测试延迟加载器...")
    print()
    
    print("1. 测试scipy.signal:")
    scipy_signal = LazyLoader('scipy.signal', 'scipy')
    print(f"   状态: {scipy_signal}")
    signal = scipy_signal.load()
    print(f"   加载后: {scipy_signal}")
    if signal:
        print(f"   成功: {signal}")
    print()
    
    print("2. 测试cv2:")
    cv2_loader = LazyLoader('cv2', 'opencv-python')
    print(f"   状态: {cv2_loader}")
    cv2 = cv2_loader.load()
    print(f"   加载后: {cv2_loader}")
    if cv2:
        print(f"   成功: {cv2.__version__}")
    print()
    
    print("3. 测试不存在的模块:")
    fake_loader = LazyLoader('nonexistent.module')
    print(f"   状态: {fake_loader}")
    result = fake_loader.load()
    print(f"   加载后: {fake_loader}")
    print(f"   结果: {result}")