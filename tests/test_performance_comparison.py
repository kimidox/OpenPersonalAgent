"""
性能对比测试

对比双进程架构和单进程架构的性能差异

测试指标：
1. 启动时间
2. 内存占用（进程启动后立即测量）
3. 消息传递延迟
"""
from __future__ import annotations

import sys
import time
import psutil
import subprocess
from pathlib import Path

# 确保项目根目录在 Python 路径中
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from logger import get_logger


def get_process_memory_mb(pid: int) -> float:
    """获取进程内存占用（MB）"""
    try:
        process = psutil.Process(pid)
        return process.memory_info().rss / 1024 / 1024
    except Exception:
        return 0.0


def test_single_process_startup() -> dict:
    """测试单进程架构启动性能"""
    logger = get_logger()
    logger.info("=" * 60)
    logger.info("测试单进程架构启动性能")
    logger.info("=" * 60)
    
    # 导入单进程原型
    from floating_ball.floating_ball_thread_prototype import QtThreadManager
    
    # 记录启动前内存
    start_time = time.time()
    start_memory = get_process_memory_mb(psutil.Process().pid)
    
    # 启动 Qt 线程
    manager = QtThreadManager()
    success = manager.start()
    
    if not success:
        logger.error("单进程架构启动失败")
        return {"success": False}
    
    # 记录启动后内存
    end_time = time.time()
    end_memory = get_process_memory_mb(psutil.Process().pid)
    
    # 测试消息传递延迟（10次）
    latencies = []
    for i in range(10):
        start = time.time()
        manager.send_to_qt({"type": "test", "data": i})
        msg = manager.receive_from_qt(timeout=1.0)
        if msg:
            latency = (time.time() - start) * 1000  # 毫秒
            latencies.append(latency)
        time.sleep(0.1)
    
    # 停止 Qt 线程
    manager.stop(timeout=3.0)
    
    # 计算结果
    startup_time = end_time - start_time
    memory_increase = end_memory - start_memory
    avg_latency = sum(latencies) / len(latencies) if latencies else 0
    max_latency = max(latencies) if latencies else 0
    min_latency = min(latencies) if latencies else 0
    
    results = {
        "success": True,
        "startup_time_s": startup_time,
        "memory_increase_mb": memory_increase,
        "avg_latency_ms": avg_latency,
        "max_latency_ms": max_latency,
        "min_latency_ms": min_latency,
        "test_count": len(latencies),
    }
    
    logger.info(f"启动时间: {startup_time:.3f}s")
    logger.info(f"内存增加: {memory_increase:.2f}MB")
    logger.info(f"平均延迟: {avg_latency:.2f}ms")
    logger.info(f"最大延迟: {max_latency:.2f}ms")
    logger.info(f"最小延迟: {min_latency:.2f}ms")
    
    return results


def test_dual_process_startup() -> dict:
    """测试双进程架构启动性能"""
    logger = get_logger()
    logger.info("=" * 60)
    logger.info("测试双进程架构启动性能")
    logger.info("=" * 60)
    
    # 记录主进程内存
    main_pid = psutil.Process().pid
    start_memory = get_process_memory_mb(main_pid)
    
    # 启动双进程悬浮球（使用子进程方式）
    start_time = time.time()
    
    try:
        from multiprocessing import get_context, Queue
        from floating_ball.floating_ball_process import run_floating_ball_process
        
        ctx = get_context("spawn")
        to_ball = ctx.Queue()
        from_ball = ctx.Queue()
        
        # 启动子进程
        process = ctx.Process(
            target=run_floating_ball_process,
            args=(to_ball, from_ball, main_pid, False, None, 200, 200, False),
            name="FloatingBallProcess",
            daemon=False,
        )
        process.start()
        
        # 等待进程启动
        time.sleep(2)  # 给子进程足够的启动时间
        
        # 记录启动时间和内存
        end_time = time.time()
        
        # 获取子进程内存
        child_memory = get_process_memory_mb(process.pid) if process.pid else 0
        main_memory_after = get_process_memory_mb(main_pid)
        total_memory = main_memory_after + child_memory
        
        # 测试消息传递延迟（10次）
        latencies = []
        for i in range(10):
            start = time.time()
            to_ball.put({"type": "test", "data": i})
            try:
                msg = from_ball.get(timeout=1.0)
                latency = (time.time() - start) * 1000
                latencies.append(latency)
            except Exception:
                pass
            time.sleep(0.1)
        
        # 停止子进程
        to_ball.put({"type": "exit"})
        process.join(timeout=3)
        if process.is_alive():
            process.terminate()
            process.join(timeout=2)
        
        # 计算结果
        startup_time = end_time - start_time
        memory_increase = total_memory - start_memory
        avg_latency = sum(latencies) / len(latencies) if latencies else 0
        max_latency = max(latencies) if latencies else 0
        min_latency = min(latencies) if latencies else 0
        
        results = {
            "success": True,
            "startup_time_s": startup_time,
            "memory_increase_mb": memory_increase,
            "avg_latency_ms": avg_latency,
            "max_latency_ms": max_latency,
            "min_latency_ms": min_latency,
            "test_count": len(latencies),
            "child_process_pid": process.pid,
            "child_memory_mb": child_memory,
        }
        
        logger.info(f"启动时间: {startup_time:.3f}s")
        logger.info(f"内存增加: {memory_increase:.2f}MB (主进程: {main_memory_after:.2f}MB, 子进程: {child_memory:.2f}MB)")
        logger.info(f"平均延迟: {avg_latency:.2f}ms")
        logger.info(f"最大延迟: {max_latency:.2f}ms")
        logger.info(f"最小延迟: {min_latency:.2f}ms")
        
        return results
    
    except Exception as e:
        logger.exception(f"双进程架构测试失败: {e}")
        return {"success": False, "error": str(e)}


def compare_architectures():
    """对比两种架构的性能"""
    logger = get_logger()
    
    print("\n" + "=" * 80)
    print("架构性能对比测试")
    print("=" * 80)
    
    # 测试单进程架构
    print("\n[1/2] 测试单进程架构...")
    single_results = test_single_process_startup()
    
    # 测试双进程架构
    print("\n[2/2] 测试双进程架构...")
    dual_results = test_dual_process_startup()
    
    # 对比结果
    print("\n" + "=" * 80)
    print("性能对比结果")
    print("=" * 80)
    
    if single_results["success"] and dual_results["success"]:
        print(f"\n启动时间对比:")
        print(f"  单进程: {single_results['startup_time_s']:.3f}s")
        print(f"  双进程: {dual_results['startup_time_s']:.3f}s")
        improvement = (dual_results['startup_time_s'] - single_results['startup_time_s']) / dual_results['startup_time_s'] * 100
        print(f"  改进: {improvement:.1f}%")
        
        print(f"\n内存占用对比:")
        print(f"  单进程: {single_results['memory_increase_mb']:.2f}MB")
        print(f"  双进程: {dual_results['memory_increase_mb']:.2f}MB")
        improvement = (dual_results['memory_increase_mb'] - single_results['memory_increase_mb']) / dual_results['memory_increase_mb'] * 100
        print(f"  改进: {improvement:.1f}%")
        
        print(f"\n消息延迟对比:")
        print(f"  单进程: {single_results['avg_latency_ms']:.2f}ms (max: {single_results['max_latency_ms']:.2f}ms)")
        print(f"  双进程: {dual_results['avg_latency_ms']:.2f}ms (max: {dual_results['max_latency_ms']:.2f}ms)")
        
        # 总结
        print("\n" + "=" * 80)
        print("结论")
        print("=" * 80)
        
        if single_results['startup_time_s'] < dual_results['startup_time_s']:
            print(f"✓ 单进程架构启动更快")
        
        if single_results['memory_increase_mb'] < dual_results['memory_increase_mb']:
            print(f"✓ 单进程架构内存占用更低")
        
        if single_results['avg_latency_ms'] < dual_results['avg_latency_ms']:
            print(f"✓ 单进程架构消息延迟更低")
        
        print(f"\n推荐: {'单进程架构' if single_results['startup_time_s'] < dual_results['startup_time_s'] else '双进程架构'}")
    
    else:
        print(f"\n测试失败:")
        if not single_results["success"]:
            print(f"  单进程架构: {single_results.get('error', '未知错误')}")
        if not dual_results["success"]:
            print(f"  双进程架构: {dual_results.get('error', '未知错误')}")


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    
    compare_architectures()