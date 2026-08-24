"""后端组件生命周期：SkillAgent / Executor / Memory / TaskScheduler 的初始化与关闭。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import config
from logger import get_logger
from database import init_db
from memory.migration import is_migration_completed
from executor import Executor
from memory import SqliteMemory
from scheduler import TaskScheduler
from skill_agent import SkillAgent

from backend_service.runner import run_coordinator
from backend_service.ws.stream_bridge import stream_bridge


@dataclass
class BackendComponents:
    """lifespan 启动后填充的组件容器。"""
    skill_agent: SkillAgent | None = None
    memory: SqliteMemory | None = None
    executor: Executor | None = None
    task_scheduler: TaskScheduler | None = None
    floating_ball: Any = None  # FloatingBallManager（阶段 5 接入）


def init_backend_components() -> BackendComponents:
    """初始化数据库 + Executor + Memory + SkillAgent + TaskScheduler。

    SkillAgent 创建后由 stream_bridge 注入并设置 event_callback。
    TaskScheduler 在 backend 模式下经 runner/bridge/skill_agent 触发 agent_conversation。
    """
    logger = get_logger()
    components = BackendComponents()

    # 1. 数据库
    try:
        init_db()
        logger.info("[lifecycle] 数据库初始化完成")
    except Exception as e:  # noqa: BLE001
        logger.exception(f"[lifecycle] 数据库初始化失败: {e}")

    # 2. 记忆迁移检查
    try:
        if not is_migration_completed():
            logger.info("[lifecycle] 记忆迁移检查通过（迁移功能已禁用）")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[lifecycle] 记忆迁移检查异常: {e}")

    # 3. Executor
    try:
        work_dir = config.WORKER_DIR
        components.executor = Executor(work_dir)
        logger.info(f"[lifecycle] Executor 初始化完成: {work_dir}")
    except Exception as e:  # noqa: BLE001
        logger.exception(f"[lifecycle] Executor 初始化失败: {e}")

    # 4. Memory
    try:
        components.memory = SqliteMemory(username=config.DEFAULT_SKILL_AGENT_USER)
        logger.info(f"[lifecycle] Memory 初始化完成: {config.DEFAULT_SKILL_AGENT_USER}")
    except Exception as e:  # noqa: BLE001
        logger.exception(f"[lifecycle] Memory 初始化失败: {e}")

    # 5. SkillAgent
    try:
        if components.executor is None or components.memory is None:
            raise RuntimeError("Executor 或 Memory 未就绪，无法创建 SkillAgent")
        components.skill_agent = SkillAgent(
            config.WORKER_DIR,
            executor=components.executor,
            memory=components.memory,
            username=config.DEFAULT_SKILL_AGENT_USER,
            # event_callback 由 stream_bridge.set_skill_agent 内部设置
        )
        logger.info("[lifecycle] SkillAgent 初始化完成")
    except Exception as e:  # noqa: BLE001
        logger.exception(f"[lifecycle] SkillAgent 初始化失败: {e}")

    # 6. StreamBridge 注入 SkillAgent（设置 event_callback）
    if components.skill_agent is not None:
        stream_bridge.set_skill_agent(components.skill_agent)

    # 7. TaskScheduler（backend 模式）
    if components.skill_agent is not None:
        try:
            components.task_scheduler = TaskScheduler(
                tray_icon=None,           # 托盘移交 Tauri（阶段 6）
                runner=run_coordinator,
                bridge=stream_bridge,
                skill_agent=components.skill_agent,
            )
            logger.info("[lifecycle] TaskScheduler 初始化完成（backend 模式）")
        except Exception as e:  # noqa: BLE001
            logger.exception(f"[lifecycle] TaskScheduler 初始化失败: {e}")

    # 8. 悬浮球托管（阶段 5）：创建但不启动（启动在 lifespan 中按 background 模式决定）
    try:
        from backend_service.floating_ball import FloatingBallManager

        components.floating_ball = FloatingBallManager()
        # 注入依赖（loop 在 lifespan 中设置后由 app.py 调用 set_dependencies）
        logger.info("[lifecycle] FloatingBallManager 初始化完成（未启动）")
    except Exception as e:  # noqa: BLE001
        logger.exception(f"[lifecycle] FloatingBallManager 初始化失败: {e}")

    return components


def start_scheduler(components: BackendComponents) -> None:
    """lifespan 启动阶段调用：启动 TaskScheduler。"""
    logger = get_logger()
    if components.task_scheduler is not None:
        try:
            components.task_scheduler.start()
            logger.info("[lifecycle] TaskScheduler 已启动")
        except Exception as e:  # noqa: BLE001
            logger.exception(f"[lifecycle] TaskScheduler 启动失败: {e}")


def shutdown_backend_components(components: BackendComponents) -> None:
    """关闭后端组件。"""
    logger = get_logger()
    if components.task_scheduler is not None:
        try:
            components.task_scheduler.stop()
            logger.info("[lifecycle] TaskScheduler 已停止")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[lifecycle] TaskScheduler 停止异常: {e}")
    if components.floating_ball is not None:
        try:
            components.floating_ball.stop()
            logger.info("[lifecycle] 悬浮球已停止")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[lifecycle] 悬浮球停止异常: {e}")

