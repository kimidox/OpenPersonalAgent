"""
失败计数和任务控制模块

提供失败计数器、任务计时器和停止条件检查功能，
防止大模型陷入死循环和无限重试。
"""

import time
from typing import Dict, Any, Optional
from dataclasses import dataclass, field


@dataclass
class FailureRecord:
    """失败记录"""
    step_id: str
    failure_count: int = 0
    last_error: str = ""
    last_time: float = 0.0


class FailureCounter:
    """失败计数器"""
    
    def __init__(self):
        """初始化失败计数器"""
        self.step_failures: Dict[str, FailureRecord] = {}
        self.total_failures: int = 0
        self.max_step_retries: int = 3  # 单步最多重试3次
        self.max_total_failures: int = 5  # 整体最多失败5次
    
    def record_step_failure(self, step_id: str, error: str = "") -> dict:
        """
        记录步骤失败
        
        Args:
            step_id: 步骤标识（可以是操作类型+元素名）
            error: 错误信息
        
        Returns:
            失败状态信息
        """
        if step_id not in self.step_failures:
            self.step_failures[step_id] = FailureRecord(step_id=step_id)
        
        record = self.step_failures[step_id]
        record.failure_count += 1
        record.last_error = error
        record.last_time = time.time()
        self.total_failures += 1
        
        return {
            "step_id": step_id,
            "step_failures": record.failure_count,
            "remaining_retries": self.max_step_retries - record.failure_count,
            "total_failures": self.total_failures,
            "remaining_total": self.max_total_failures - self.total_failures,
            "should_stop": self.should_stop(step_id),
            "stop_reason": self.get_stop_reason(step_id),
        }
    
    def should_stop(self, step_id: str) -> bool:
        """
        判断是否应该停止
        
        Args:
            step_id: 步骤标识
        
        Returns:
            是否应该停止
        """
        # 检查单步失败次数
        if self.step_failures.get(step_id, FailureRecord(step_id)).failure_count >= self.max_step_retries:
            return True
        
        # 检查整体失败次数
        if self.total_failures >= self.max_total_failures:
            return True
        
        return False
    
    def get_stop_reason(self, step_id: str) -> str:
        """
        获取停止原因
        
        Args:
            step_id: 步骤标识
        
        Returns:
            停止原因字符串
        """
        record = self.step_failures.get(step_id, FailureRecord(step_id))
        
        if record.failure_count >= self.max_step_retries:
            return (
                f"【停止条件】步骤 '{step_id}' 失败次数已达上限（{self.max_step_retries}次）。\n"
                f"建议：尝试备选方案或跳过该步骤，不要继续重试相同操作。"
            )
        
        if self.total_failures >= self.max_total_failures:
            return (
                f"【停止条件】任务整体失败次数已达上限（{self.max_total_failures}次）。\n"
                f"建议：重新规划任务或放弃，不要继续尝试。"
            )
        
        return ""
    
    def get_status_summary(self) -> str:
        """
        获取状态摘要
        
        Returns:
            状态摘要字符串
        """
        if self.total_failures == 0:
            return "当前无失败记录"
        
        summary_lines = [
            f"【失败统计】",
            f"- 整体失败次数: {self.total_failures}/{self.max_total_failures}",
            f"- 剩余整体尝试机会: {self.max_total_failures - self.total_failures}",
        ]
        
        for step_id, record in self.step_failures.items():
            summary_lines.append(
                f"- 步骤 '{step_id}': {record.failure_count}/{self.max_step_retries}次失败"
            )
        
        return "\n".join(summary_lines)
    
    def reset(self):
        """重置计数器"""
        self.step_failures.clear()
        self.total_failures = 0


class TaskTimer:
    """任务计时器"""
    
    def __init__(self, max_duration: float = 60.0):
        """
        初始化计时器
        
        Args:
            max_duration: 最大执行时间（秒），默认60秒
        """
        self.start_time: float = time.time()
        self.max_duration: float = max_duration
        self._last_check_time: float = self.start_time
    
    def should_stop(self) -> bool:
        """
        判断是否应该停止（时间限制）
        
        Returns:
            是否超过时间限制
        """
        return time.time() - self.start_time > self.max_duration
    
    def get_elapsed_time(self) -> float:
        """
        获取已执行时间
        
        Returns:
            已执行时间（秒）
        """
        return time.time() - self.start_time
    
    def get_remaining_time(self) -> float:
        """
        获取剩余时间
        
        Returns:
            剩余时间（秒）
        """
        return self.max_duration - self.get_elapsed_time()
    
    def get_stop_reason(self) -> str:
        """
        获取停止原因
        
        Returns:
            停止原因字符串
        """
        elapsed = self.get_elapsed_time()
        if elapsed > self.max_duration:
            return (
                f"【停止条件】任务执行时间超过限制（{elapsed:.1f}秒 > {self.max_duration}秒）。\n"
                f"建议：重新规划任务或放弃，不要继续尝试。"
            )
        return ""
    
    def get_time_warning(self) -> str:
        """
        获取时间警告
        
        Returns:
            时间警告字符串（如果接近限制）
        """
        remaining = self.get_remaining_time()
        elapsed = self.get_elapsed_time()
        
        if remaining < 10:
            return f"【时间警告】剩余时间不足10秒（{remaining:.1f}秒），请尽快完成或准备结束任务"
        
        if remaining < 20:
            return f"【时间提示】剩余时间：{remaining:.1f}秒，已执行：{elapsed:.1f}秒"
        
        return ""
    
    def check_and_warn(self) -> str:
        """
        检查并返回警告信息
        
        Returns:
            警告信息（如果有）
        """
        if self.should_stop():
            return self.get_stop_reason()
        return self.get_time_warning()


class TaskController:
    """任务控制器 - 综合管理失败计数和时间限制"""
    
    def __init__(self, max_duration: float = 60.0, max_step_retries: int = 3, max_total_failures: int = 5):
        """
        初始化任务控制器
        
        Args:
            max_duration: 最大执行时间（秒）
            max_step_retries: 单步最大重试次数
            max_total_failures: 整体最大失败次数
        """
        self.failure_counter = FailureCounter()
        self.failure_counter.max_step_retries = max_step_retries
        self.failure_counter.max_total_failures = max_total_failures
        self.timer = TaskTimer(max_duration)
    
    def should_stop(self, step_id: str = None) -> bool:
        """
        判断是否应该停止
        
        Args:
            step_id: 步骤标识（可选）
        
        Returns:
            是否应该停止
        """
        # 检查时间限制
        if self.timer.should_stop():
            return True
        
        # 检查失败限制
        if step_id and self.failure_counter.should_stop(step_id):
            return True
        
        if self.failure_counter.total_failures >= self.failure_counter.max_total_failures:
            return True
        
        return False
    
    def record_failure(self, step_id: str, error: str = "") -> dict:
        """
        记录失败
        
        Args:
            step_id: 步骤标识
            error: 错误信息
        
        Returns:
            失败状态信息
        """
        return self.failure_counter.record_step_failure(step_id, error)
    
    def get_stop_reason(self, step_id: str = None) -> str:
        """
        获取停止原因
        
        Args:
            step_id: 步骤标识（可选）
        
        Returns:
            停止原因
        """
        # 先检查时间限制
        if self.timer.should_stop():
            return self.timer.get_stop_reason()
        
        # 再检查失败限制
        if step_id:
            return self.failure_counter.get_stop_reason(step_id)
        
        return ""
    
    def get_status_summary(self) -> str:
        """
        获取状态摘要
        
        Returns:
            状态摘要
        """
        time_info = f"执行时间: {self.timer.get_elapsed_time():.1f}秒/{self.timer.max_duration}秒"
        failure_info = self.failure_counter.get_status_summary()
        
        return f"{time_info}\n{failure_info}"
    
    def check_before_operation(self, step_id: str) -> dict:
        """
        操作前检查
        
        Args:
            step_id: 步骤标识
        
        Returns:
            检查结果
        """
        result = {
            "can_continue": True,
            "warnings": [],
            "stop_reason": "",
        }
        
        # 检查时间
        time_warning = self.timer.check_and_warn()
        if time_warning:
            if self.timer.should_stop():
                result["can_continue"] = False
                result["stop_reason"] = time_warning
            else:
                result["warnings"].append(time_warning)
        
        # 检查失败次数
        if self.failure_counter.should_stop(step_id):
            result["can_continue"] = False
            result["stop_reason"] = self.failure_counter.get_stop_reason(step_id)
        
        return result
    
    def reset(self):
        """重置控制器"""
        self.failure_counter.reset()
        self.timer = TaskTimer(self.timer.max_duration)


# 单例任务控制器
_controller: Optional[TaskController] = None


def get_controller() -> TaskController:
    """获取任务控制器单例"""
    global _controller
    if _controller is None:
        _controller = TaskController()
    return _controller


def reset_controller():
    """重置任务控制器（用于新任务开始时）"""
    global _controller
    if _controller is not None:
        _controller.reset()
    else:
        _controller = TaskController()