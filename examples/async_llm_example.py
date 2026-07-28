"""
LLM 异步调用示例

演示如何使用异步接口实现并发 LLM 调用，避免阻塞主线程。
"""

import threading
import time
from typing import Optional

from llm import get_chat_model
from llm.BaseChatModel import StreamResult


def example_basic_async_call():
    """基础异步调用示例：单个任务"""
    print("\n===== 基础异步调用示例 =====")

    # 获取模型实例
    model = get_chat_model(enable_thinking=False)

    # 准备消息
    messages = [
        {"role": "system", "content": "你是一个友好的助手。"},
        {"role": "user", "content": "请用一句话介绍Python编程语言。"}
    ]

    # 准备回调函数（线程安全）
    response_parts = []
    callback_lock = threading.Lock()

    def stream_callback(content: str, msg_type: str) -> None:
        """流式回调函数（线程安全）"""
        with callback_lock:
            response_parts.append(content)
            print(f"[回调] {msg_type}: {content}")

    # 提交异步任务
    task_id, future = model.async_stream_request_llm_with_tools(
        messages=messages,
        tools=[],
        stream_callback=stream_callback,
    )

    print(f"任务已提交: task_id={task_id}")

    # 可以在此期间处理其他任务（模拟并发）
    print("\n[主线程] 在等待LLM响应的同时，我可以处理其他任务...")
    for i in range(3):
        time.sleep(0.5)
        print(f"[主线程] 正在处理其他任务 {i+1}/3...")

    # 等待任务完成
    print("\n[主线程] 等待LLM任务完成...")
    try:
        result = model.wait_for_async_task(task_id, timeout=30.0)
        print(f"\n任务完成!")
        print(f"完整响应: {result.content}")
    except TimeoutError:
        print(f"任务超时，正在取消...")
        model.cancel_async_task(task_id)
    except Exception as e:
        print(f"任务失败: {e}")


def example_concurrent_calls():
    """并发调用示例：多个LLM请求同时执行"""
    print("\n\n===== 并发调用示例 =====")

    # 获取模型实例
    model = get_chat_model(enable_thinking=False)

    # 准备多个问题
    questions = [
        "什么是人工智能？",
        "Python有什么优势？",
        "云计算的特点是什么？",
    ]

    # 存储任务信息
    task_infos = []
    callback_lock = threading.Lock()

    def make_callback(question_idx: int):
        """创建线程安全的回调函数"""
        def callback(content: str, msg_type: str) -> None:
            with callback_lock:
                print(f"[问题{question_idx+1}] {msg_type}: {content[:50]}...")
        return callback

    # 提交多个异步任务
    print("提交3个并发任务...")
    for i, question in enumerate(questions):
        messages = [
            {"role": "system", "content": "你是一个简洁的助手，请用一句话回答。"},
            {"role": "user", "content": question},
        ]

        task_id, future = model.async_stream_request_llm_with_tools(
            messages=messages,
            tools=[],
            stream_callback=make_callback(i),
        )

        task_infos.append({
            "task_id": task_id,
            "question": question,
            "future": future,
        })

        print(f"任务{i+1}已提交: {task_id}")

    # 等待所有任务完成
    print("\n等待所有任务完成...")
    results = []
    for info in task_infos:
        try:
            result = model.wait_for_async_task(info["task_id"], timeout=30.0)
            results.append({
                "question": info["question"],
                "answer": result.content,
                "success": True,
            })
        except Exception as e:
            results.append({
                "question": info["question"],
                "error": str(e),
                "success": False,
            })

    # 输出结果
    print("\n===== 所有任务结果 =====")
    for i, result in enumerate(results):
        if result["success"]:
            print(f"\n问题{i+1}: {result['question']}")
            print(f"答案: {result['answer']}")
        else:
            print(f"\n问题{i+1}: {result['question']}")
            print(f"失败: {result['error']}")

    # 获取统计信息
    stats = model.get_async_task_stats()
    print(f"\n线程池统计: {stats}")


def example_task_cancellation():
    """任务取消示例"""
    print("\n\n===== 任务取消示例 =====")

    # 获取模型实例
    model = get_chat_model(enable_thinking=False)

    # 准备一个需要长时间回答的问题
    messages = [
        {"role": "system", "content": "你是一个详细的助手。"},
        {"role": "user", "content": "请详细解释量子计算的原理和应用（至少500字）。"},
    ]

    response_parts = []
    callback_lock = threading.Lock()

    def stream_callback(content: str, msg_type: str) -> None:
        with callback_lock:
            response_parts.append(content)
            print(f"[流式输出] {content[:50]}...")

    # 提交异步任务
    task_id, future = model.async_stream_request_llm_with_tools(
        messages=messages,
        tools=[],
        stream_callback=stream_callback,
    )

    print(f"任务已提交: {task_id}")

    # 检查任务状态
    print(f"任务状态: {model.get_async_task_state(task_id)}")

    # 模拟用户取消操作
    print("\n模拟用户在2秒后取消任务...")
    time.sleep(2)

    # 取消任务
    cancelled = model.cancel_async_task(task_id)
    print(f"任务取消结果: {cancelled}")

    # 检查取消后的状态
    time.sleep(0.5)  # 等待状态更新
    print(f"取消后状态: {model.get_async_task_state(task_id)}")


def example_with_callback():
    """使用回调函数的示例"""
    print("\n\n===== 回调函数示例 =====")

    # 获取模型实例
    model = get_chat_model(enable_thinking=False)

    # 准备消息
    messages = [
        {"role": "system", "content": "你是一个简洁的助手。"},
        {"role": "user", "content": "什么是机器学习？"},
    ]

    # 准备回调函数
    callback_lock = threading.Lock()

    def stream_callback(content: str, msg_type: str) -> None:
        """流式回调"""
        with callback_lock:
            print(f"[流式] {msg_type}: {content}")

    def on_complete(task_result):
        """任务完成回调"""
        print(f"\n[完成回调] 任务成功完成!")
        print(f"耗时: {task_result.duration_ms:.2f}ms")

    def on_error(error: Exception):
        """任务错误回调"""
        print(f"\n[错误回调] 任务失败: {error}")

    # 提交异步任务（带回调）
    task_id, future = model.async_stream_request_llm_with_tools(
        messages=messages,
        tools=[],
        stream_callback=stream_callback,
        on_complete=on_complete,
        on_error=on_error,
    )

    print(f"任务已提交: {task_id}")

    # 主线程可以继续做其他事情
    print("\n[主线程] 任务在后台执行，我继续处理其他事情...")
    time.sleep(1)
    print("[主线程] 处理完成")

    # 等待任务完成
    try:
        result = model.wait_for_async_task(task_id, timeout=30.0)
        print(f"\n完整响应: {result.content}")
    except Exception as e:
        print(f"\n任务执行出错: {e}")


def example_stats_and_cleanup():
    """统计信息和清理示例"""
    print("\n\n===== 统计信息和清理示例 =====")

    # 获取模型实例
    model = get_chat_model(enable_thinking=False)

    # 获取当前统计信息
    stats = model.get_async_task_stats()
    print(f"当前统计信息: {stats}")

    # 执行一些任务（简化版）
    messages = [
        {"role": "user", "content": "你好"},
    ]

    for i in range(3):
        task_id, _ = model.async_stream_request_llm_with_tools(
            messages=messages,
            tools=[],
            stream_callback=lambda c, t: None,  # 空回调
        )
        print(f"提交任务{i+1}: {task_id}")

    # 等待任务完成
    import time
    time.sleep(5)

    # 再次获取统计信息
    stats = model.get_async_task_stats()
    print(f"\n执行任务后统计: {stats}")

    # 清理旧任务（立即清理）
    cleaned = model.cleanup_async_tasks(max_age_seconds=0.1)
    print(f"\n清理了 {cleaned} 个任务")

    # 最终统计
    stats = model.get_async_task_stats()
    print(f"清理后统计: {stats}")


def main():
    """运行所有示例"""
    print("=" * 60)
    print("LLM 异步调用示例")
    print("=" * 60)

    # 运行示例（根据需要选择）
    try:
        # 基础示例
        example_basic_async_call()

        # 并发示例（可选，会同时发起多个请求）
        # example_concurrent_calls()

        # 取消示例
        # example_task_cancellation()

        # 回调示例
        # example_with_callback()

        # 统计和清理示例
        # example_stats_and_cleanup()

    except KeyboardInterrupt:
        print("\n\n用户中断执行")
    except Exception as e:
        print(f"\n执行出错: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()