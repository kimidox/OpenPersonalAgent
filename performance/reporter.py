"""
性能报告生成器

提供：
- 日报生成
- 周报生成
- 性能趋势分析
"""
from __future__ import annotations

import time
import json
import statistics
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from pathlib import Path

from logger import get_logger
from resource_path import paths
from .metrics import PerformanceSnapshot, MetricValue
from .config import PerformanceConfig


class PerformanceReporter:
    """
    性能报告生成器

    基于历史性能数据生成报告
    """

    def __init__(self, history_data: List[PerformanceSnapshot]):
        """
        Args:
            history_data: 历史性能数据
        """
        self._logger = get_logger()
        self._history = history_data

    def generate_daily_report(self, date: Optional[datetime] = None) -> Dict[str, Any]:
        """
        生成日报

        Args:
            date: 报告日期（默认今天）

        Returns:
            报告数据字典
        """
        if date is None:
            date = datetime.now()

        # 过滤当天数据
        start_time = date.replace(hour=0, minute=0, second=0, microsecond=0)
        end_time = start_time + timedelta(days=1)

        daily_data = [
            s for s in self._history
            if start_time.timestamp() <= s.timestamp < end_time.timestamp()
        ]

        if not daily_data:
            return {
                "date": date.strftime("%Y-%m-%d"),
                "message": "当日无性能数据",
            }

        # 生成报告
        report = {
            "date": date.strftime("%Y-%m-%d"),
            "generated_at": datetime.now().isoformat(),
            "data_points": len(daily_data),
            "metrics": self._aggregate_metrics(daily_data),
            "alerts": self._analyze_alerts(daily_data),
            "trends": self._analyze_trends(daily_data),
            "recommendations": self._generate_recommendations(daily_data),
        }

        return report

    def generate_weekly_report(self, end_date: Optional[datetime] = None) -> Dict[str, Any]:
        """
        生成周报

        Args:
            end_date: 周报结束日期（默认今天）

        Returns:
            报告数据字典
        """
        if end_date is None:
            end_date = datetime.now()

        # 计算周范围
        start_date = end_date - timedelta(days=7)

        # 过滤周数据
        weekly_data = [
            s for s in self._history
            if start_date.timestamp() <= s.timestamp <= end_date.timestamp()
        ]

        if not weekly_data:
            return {
                "period": f"{start_date.strftime('%Y-%m-%d')} ~ {end_date.strftime('%Y-%m-%d')}",
                "message": "本周无性能数据",
            }

        # 生成报告
        report = {
            "period": f"{start_date.strftime('%Y-%m-%d')} ~ {end_date.strftime('%Y-%m-%d')}",
            "generated_at": datetime.now().isoformat(),
            "data_points": len(weekly_data),
            "metrics": self._aggregate_metrics(weekly_data),
            "alerts": self._analyze_alerts(weekly_data),
            "trends": self._analyze_trends(weekly_data),
            "daily_breakdown": self._daily_breakdown(weekly_data),
            "recommendations": self._generate_recommendations(weekly_data),
        }

        return report

    def _aggregate_metrics(self, data: List[PerformanceSnapshot]) -> Dict[str, Any]:
        """聚合指标数据"""
        if not data:
            return {}

        aggregated = {}

        # 获取所有指标名称
        all_metrics = data[0].get_all_metrics()
        metric_names = [m.name for m in all_metrics]

        for metric_name in metric_names:
            values = []
            for snapshot in data:
                for metric in snapshot.get_all_metrics():
                    if metric.name == metric_name:
                        values.append(metric.value)
                        break

            if values:
                aggregated[metric_name] = {
                    "min": min(values),
                    "max": max(values),
                    "avg": statistics.mean(values),
                    "median": statistics.median(values),
                    "std_dev": statistics.stdev(values) if len(values) > 1 else 0,
                    "count": len(values),
                }

        return aggregated

    def _analyze_alerts(self, data: List[PerformanceSnapshot]) -> Dict[str, Any]:
        """分析告警"""
        # 简化版：统计指标超过基线的次数
        alerts = {}
        baselines = PerformanceConfig.get_all_baselines()

        for metric_name, baseline in baselines.items():
            violations = 0
            for snapshot in data:
                for metric in snapshot.get_all_metrics():
                    if metric.name == metric_name:
                        is_lower_better = PerformanceConfig.is_lower_better(metric_name)
                        if is_lower_better:
                            if metric.value > baseline:
                                violations += 1
                        else:
                            if metric.value < baseline:
                                violations += 1
                        break

            if violations > 0:
                alerts[metric_name] = {
                    "baseline": baseline,
                    "violations": violations,
                    "violation_rate": violations / len(data) * 100,
                }

        return alerts

    def _analyze_trends(self, data: List[PerformanceSnapshot]) -> Dict[str, Any]:
        """分析性能趋势"""
        if len(data) < 2:
            return {}

        trends = {}

        # 将数据分成前半段和后半段，比较平均值
        mid = len(data) // 2
        first_half = data[:mid]
        second_half = data[mid:]

        for metric_name in PerformanceConfig.get_all_baselines().keys():
            first_values = self._extract_metric_values(first_half, metric_name)
            second_values = self._extract_metric_values(second_half, metric_name)

            if first_values and second_values:
                first_avg = statistics.mean(first_values)
                second_avg = statistics.mean(second_values)

                if first_avg != 0:
                    change_percent = (second_avg - first_avg) / first_avg * 100

                    # 判断趋势
                    if abs(change_percent) < 5:
                        trend = "stable"
                    elif change_percent > 0:
                        trend = "increasing"
                    else:
                        trend = "decreasing"

                    trends[metric_name] = {
                        "trend": trend,
                        "change_percent": change_percent,
                        "first_avg": first_avg,
                        "second_avg": second_avg,
                    }

        return trends

    def _extract_metric_values(self, data: List[PerformanceSnapshot], metric_name: str) -> List[float]:
        """提取指定指标的值"""
        values = []
        for snapshot in data:
            for metric in snapshot.get_all_metrics():
                if metric.name == metric_name:
                    values.append(metric.value)
                    break
        return values

    def _daily_breakdown(self, data: List[PerformanceSnapshot]) -> Dict[str, Any]:
        """按天分解数据"""
        daily_data = {}

        for snapshot in data:
            date_str = datetime.fromtimestamp(snapshot.timestamp).strftime("%Y-%m-%d")
            if date_str not in daily_data:
                daily_data[date_str] = []
            daily_data[date_str].append(snapshot)

        breakdown = {}
        for date_str, snapshots in daily_data.items():
            breakdown[date_str] = {
                "data_points": len(snapshots),
                "metrics": self._aggregate_metrics(snapshots),
            }

        return breakdown

    def _generate_recommendations(self, data: List[PerformanceSnapshot]) -> List[str]:
        """生成优化建议"""
        recommendations = []

        if not data:
            return recommendations

        # 分析各指标，生成建议
        aggregated = self._aggregate_metrics(data)

        # CPU 使用率建议
        if "cpu_percent" in aggregated:
            avg_cpu = aggregated["cpu_percent"]["avg"]
            if avg_cpu > 50:
                recommendations.append(
                    f"CPU 平均使用率较高（{avg_cpu:.1f}%），建议优化计算密集型任务或考虑异步处理"
                )

        # 内存使用建议
        if "memory_mb" in aggregated:
            avg_memory = aggregated["memory_mb"]["avg"]
            if avg_memory > 400:
                recommendations.append(
                    f"内存平均使用量较高（{avg_memory:.1f}MB），建议检查内存泄漏或优化数据缓存策略"
                )

        # 响应延迟建议
        for metric_name in ["ui_response_ms", "llm_first_token_ms", "ipc_latency_ms"]:
            if metric_name in aggregated:
                avg_latency = aggregated[metric_name]["avg"]
                baseline = PerformanceConfig.get_all_baselines().get(metric_name, 0)
                if avg_latency > baseline:
                    recommendations.append(
                        f"{metric_name} 平均延迟 {avg_latency:.1f}ms，超过基线 {baseline}ms，建议优化相关逻辑"
                    )

        # 成功率建议
        for metric_name in ["llm_success_rate", "tool_success_rate"]:
            if metric_name in aggregated:
                avg_rate = aggregated[metric_name]["avg"]
                baseline = PerformanceConfig.get_all_baselines().get(metric_name, 100)
                if avg_rate < baseline:
                    recommendations.append(
                        f"{metric_name} 平均成功率 {avg_rate:.1f}%，低于基线 {baseline}%，建议检查错误处理"
                    )

        return recommendations

    def save_report(self, report: Dict[str, Any], filename: str) -> Path:
        """
        保存报告到文件

        Args:
            report: 报告数据
            filename: 文件名

        Returns:
            文件路径
        """
        # 确保报告目录存在
        report_dir = paths.personal_data_dir / "performance_reports"
        report_dir.mkdir(parents=True, exist_ok=True)

        # 保存 JSON 文件
        report_path = report_dir / f"{filename}.json"
        with open(report_path, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

        self._logger.info(f"性能报告已保存: {report_path}")
        return report_path


def generate_and_save_daily_report(history_data: List[PerformanceSnapshot]) -> Path:
    """生成并保存日报"""
    reporter = PerformanceReporter(history_data)
    report = reporter.generate_daily_report()
    filename = f"daily_{datetime.now().strftime('%Y%m%d')}"
    return reporter.save_report(report, filename)


def generate_and_save_weekly_report(history_data: List[PerformanceSnapshot]) -> Path:
    """生成并保存周报"""
    reporter = PerformanceReporter(history_data)
    report = reporter.generate_weekly_report()
    filename = f"weekly_{datetime.now().strftime('%Y%m%d')}"
    return reporter.save_report(report, filename)