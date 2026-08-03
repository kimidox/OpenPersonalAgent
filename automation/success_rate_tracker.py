"""
成功率统计模块

记录和分析自动化操作的成功率，帮助大模型选择更好的方法。
"""

import json
import time
from pathlib import Path
from typing import Dict, Any, Optional

from logger import get_module_logger

logger = get_module_logger("SuccessRateTracker")


class SuccessRateTracker:
    """成功率统计器"""
    
    def __init__(self, stats_file: str = None):
        """
        初始化统计器
        
        Args:
            stats_file: 统计数据文件路径，默认在工作目录下
        """
        if stats_file is None:
            # 使用工作目录下的统计数据文件
            stats_file = Path.cwd() / "automation_stats.json"
        self.stats_file = Path(stats_file)
        self.stats = self._load_stats()
    
    def _load_stats(self) -> Dict[str, Any]:
        """加载统计数据"""
        if self.stats_file.exists():
            try:
                return json.loads(self.stats_file.read_text(encoding="utf-8"))
            except Exception as e:
                logger.debug("记录操作结果异常: %s", e)
        return {
            "find_methods": {},
            "operations": {},
            "elements": {},
            "session_stats": {
                "start_time": time.time(),
                "total_operations": 0,
                "successful_operations": 0,
            }
        }
    
    def _save_stats(self):
        """保存统计数据"""
        try:
            self.stats_file.write_text(
                json.dumps(self.stats, indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
        except Exception as e:
            logger.debug("获取成功率异常: %s", e)
    
    def record_find_attempt(self, method: str, success: bool, element_name: str = None):
        """
        记录查找尝试
        
        Args:
            method: 查找方法（by_name, by_automation_id等）
            success: 是否成功
            element_name: 元素名称（可选）
        """
        # 记录方法统计
        if method not in self.stats["find_methods"]:
            self.stats["find_methods"][method] = {"total": 0, "success": 0}
        
        self.stats["find_methods"][method]["total"] += 1
        if success:
            self.stats["find_methods"][method]["success"] += 1
        
        # 记录元素统计
        if element_name:
            elem_key = f"find_{element_name}"
            if elem_key not in self.stats["elements"]:
                self.stats["elements"][elem_key] = {"total": 0, "success": 0}
            self.stats["elements"][elem_key]["total"] += 1
            if success:
                self.stats["elements"][elem_key]["success"] += 1
        
        # 更新会话统计
        self.stats["session_stats"]["total_operations"] += 1
        if success:
            self.stats["session_stats"]["successful_operations"] += 1
        
        self._save_stats()
    
    def record_operation_attempt(self, operation: str, method: str, success: bool, element_name: str = None):
        """
        记录操作尝试
        
        Args:
            operation: 操作类型（click, type_text等）
            method: 操作方法（invoke, mouse, value等）
            success: 是否成功
            element_name: 元素名称（可选）
        """
        key = f"{operation}_{method}"
        if key not in self.stats["operations"]:
            self.stats["operations"][key] = {"total": 0, "success": 0}
        
        self.stats["operations"][key]["total"] += 1
        if success:
            self.stats["operations"][key]["success"] += 1
        
        # 记录元素统计
        if element_name:
            elem_key = f"{operation}_{element_name}"
            if elem_key not in self.stats["elements"]:
                self.stats["elements"][elem_key] = {"total": 0, "success": 0}
            self.stats["elements"][elem_key]["total"] += 1
            if success:
                self.stats["elements"][elem_key]["success"] += 1
        
        # 更新会话统计
        self.stats["session_stats"]["total_operations"] += 1
        if success:
            self.stats["session_stats"]["successful_operations"] += 1
        
        self._save_stats()
    
    def get_success_rate(self, category: str, key: str) -> float:
        """
        获取成功率
        
        Args:
            category: 类别（find_methods, operations, elements）
            key: 具体键名
        
        Returns:
            成功率（0.0-1.0）
        """
        if category not in self.stats:
            return 0.0
        
        stats = self.stats[category].get(key, {})
        total = stats.get("total", 0)
        success = stats.get("success", 0)
        
        if total == 0:
            return 0.0
        
        return success / total
    
    def get_recommendation(self, category: str) -> str:
        """
        获取推荐方法
        
        Args:
            category: 类别（find_methods, operations）
        
        Returns:
            推荐信息字符串
        """
        if category not in self.stats:
            return ""
        
        methods = self.stats[category]
        
        # 找出成功率最高的方法
        best_method = None
        best_rate = 0.0
        min_attempts = 3  # 最少尝试次数
        
        for method, stats in methods.items():
            total = stats.get("total", 0)
            if total < min_attempts:
                continue  # 样本太少，不推荐
            
            rate = self.get_success_rate(category, method)
            if rate > best_rate:
                best_rate = rate
                best_method = method
        
        if best_method and best_rate > 0.5:
            return f"【历史统计】推荐使用 {best_method}（成功率: {best_rate:.1%}，尝试次数: {methods[best_method]['total']}）"
        
        return ""
    
    def get_session_summary(self) -> str:
        """
        获取当前会话的统计摘要
        
        Returns:
            会话统计摘要字符串
        """
        session = self.stats["session_stats"]
        total = session.get("total_operations", 0)
        success = session.get("successful_operations", 0)
        
        if total == 0:
            return "当前会话暂无操作记录"
        
        rate = success / total if total > 0 else 0
        
        return f"【会话统计】总操作: {total}次，成功: {success}次，成功率: {rate:.1%}"
    
    def get_failure_warning(self, category: str, key: str) -> str:
        """
        获取失败警告
        
        Args:
            category: 类别
            key: 键名
        
        Returns:
            警告信息（如果成功率低）
        """
        rate = self.get_success_rate(category, key)
        
        if rate < 0.3 and self.stats[category].get(key, {}).get("total", 0) >= 3:
            return f"【警告】{key} 成功率较低（{rate:.1%}），建议尝试其他方法"
        
        return ""


# 单例统计器
_tracker: Optional[SuccessRateTracker] = None


def get_tracker() -> SuccessRateTracker:
    """获取统计器单例"""
    global _tracker
    if _tracker is None:
        _tracker = SuccessRateTracker()
    return _tracker