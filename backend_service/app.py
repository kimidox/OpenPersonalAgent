"""FastAPI 应用工厂 + lifespan + 健康检查 + token 中间件 + BACKEND_READY marker。

启动流程（3.12 节）：
1. 解析 --port / --token / --dev
2. lifespan：init_backend_components → 注入 stream_bridge / app.state
3. lifespan 完成 → 输出 stdout marker：BACKEND_READY {"port":...,"token":...,"pid":...}
4. Tauri 读取 marker 后注入前端

健康检查（3.13 节）：
- GET /api/health  → 永远 200，反映运行时状态
- GET /api/ready   → lifespan 完成前 503，完成后 200

token 校验（3.12 节）：
- 打包模式：除 /api/health / /api/ready 外的 /api/* 请求需带 X-Backend-Token
- 开发模式（--dev）：跳过校验
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from logger import get_logger, install_exception_hook, setup_logger

from backend_service.lifecycle import (
    BackendComponents,
    init_backend_components,
    shutdown_backend_components,
    start_scheduler,
)
from backend_service.runner import run_coordinator
from backend_service.ws.manager import ws_manager
from backend_service.ws.stream_bridge import stream_bridge
from backend_service.routers import conversations as conversations_router
from backend_service.routers import messages as messages_router
from backend_service.routers import ws as ws_router
from backend_service.routers import agent as agent_router
from backend_service.routers import skills as skills_router
from backend_service.routers import recording as recording_router
from backend_service.routers import files as files_router
from backend_service.routers import settings as settings_router
from backend_service.routers import floating_ball as floating_ball_router
from backend_service.routers import cli as cli_router
from backend_service.schemas import HealthResponse, ReadyResponse


# =====================================================================
# 启动参数解析
# =====================================================================

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="PersonalWindowGLM Backend Service")
    parser.add_argument("--port", type=int, default=8765, help="监听端口")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址（默认 127.0.0.1）")
    parser.add_argument("--token", default="", help="Tauri 生成的随机 token（打包模式必填）")
    parser.add_argument("--dev", action="store_true", help="开发模式（跳过 token 校验）")
    return parser.parse_args(argv)


# =====================================================================
# lifespan
# =====================================================================

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """应用生命周期：初始化 → 标记就绪 → 等待关闭 → 清理。"""
    # 阶段 6：原 main.py 的启动初始化迁入此处
    setup_logger()
    install_exception_hook()
    try:
        from performance import start_monitoring
        start_monitoring()
    except Exception as e:  # noqa: BLE001
        pass
    try:
        from recorder import ensure_model_dirs, migrate_models_to_separate_dirs
        ensure_model_dirs()
        migrate_models_to_separate_dirs()
    except Exception as e:  # noqa: BLE001
        pass

    logger = get_logger()
    logger.info("[lifespan] 后端启动中...")

    # 1. 保存事件循环引用（供 stream_bridge 从工作线程投递事件）
    loop = asyncio.get_running_loop()
    app.state.loop = loop
    stream_bridge.set_loop(loop)
    ws_manager.set_logger(logger)

    # 2. 初始化后端组件（init_db / Executor / Memory / SkillAgent）
    components: BackendComponents = init_backend_components()
    app.state.components = components
    app.state.skill_agent = components.skill_agent
    app.state.memory = components.memory
    app.state.executor = components.executor

    # 3. 注入 SkillAgent 到 stream_bridge（设置 event_callback）—— 已在 init_backend_components 内完成

    # 4. 启动 TaskScheduler（backend 模式）
    start_scheduler(components)

    # 5. 悬浮球托管（阶段 5）：注入依赖 + 启动预启动模式
    if components.floating_ball is not None:
        try:
            components.floating_ball.set_dependencies(
                stream_bridge=stream_bridge,
                run_coordinator=run_coordinator,
                skill_agent=components.skill_agent,
                memory=components.memory,
                loop=loop,
            )
            # StreamBridge 注入悬浮球引用（_emit 分流转发）
            stream_bridge.set_floating_ball_manager(components.floating_ball)
            # 预启动悬浮球（窗口初始隐藏，等待 SHOW_WINDOW）
            components.floating_ball.start(prestart=True)
            logger.info("[lifespan] 悬浮球已预启动")
        except Exception as e:  # noqa: BLE001
            logger.exception(f"[lifespan] 悬浮球启动失败: {e}")

    # 6. 标记就绪
    app.state.ready = True
    app.state.started_at = time.time()
    logger.info("[lifespan] 后端就绪")

    # 6. 输出 BACKEND_READY marker（3.12 节，供 Tauri 解析）
    args: argparse.Namespace = app.state.args
    marker = {
        "port": args.port,
        "token": args.token,
        "pid": os.getpid(),
    }
    sys.stdout.write(f"BACKEND_READY {json.dumps(marker, ensure_ascii=False)}\n")
    sys.stdout.flush()

    try:
        yield
    finally:
        # 关闭
        logger.info("[lifespan] 后端关闭中...")
        app.state.ready = False
        # 中断所有未完成 run（3.13 节，崩溃恢复路径）
        try:
            aborted = run_coordinator.abort_all(reason="shutdown")
            if aborted:
                stream_bridge.abort_runs(aborted, reason="shutdown")
                # 给事件循环一点时间把 run.aborted 推出去
                await asyncio.sleep(0.1)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[lifespan] abort_all 异常: {e}")
        try:
            shutdown_backend_components(components)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[lifespan] shutdown_backend_components 异常: {e}")
        # 停止性能监控
        try:
            from performance import stop_monitoring
            stop_monitoring()
        except Exception as e:  # noqa: BLE001
            pass
        logger.info("[lifespan] 后端已关闭")


# =====================================================================
# token 中间件
# =====================================================================

class TokenAuthMiddleware(BaseHTTPMiddleware):
    """X-Backend-Token 校验中间件（3.12 节）。

    - 开发模式（args.dev=True）：跳过
    - 白名单路径（/api/health / /api/ready / /ws/* / /docs / /openapi.json）：跳过
    - 其余 /api/* 与 /ws/* 请求需带匹配的 X-Backend-Token
    """

    WHITELIST_PREFIXES = ("/api/health", "/api/ready")
    WHITELIST_EXACT = {"/docs", "/redoc", "/openapi.json", "/"}

    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        args: argparse.Namespace = request.app.state.args
        path = request.url.path

        # 白名单
        if path in self.WHITELIST_EXACT:
            return await call_next(request)
        for prefix in self.WHITELIST_PREFIXES:
            if path == prefix or path.startswith(prefix + "/"):
                return await call_next(request)

        # 开发模式或未配置 token：跳过
        if getattr(args, "dev", False) or not getattr(args, "token", ""):
            return await call_next(request)

        # 校验
        if path.startswith("/api/") or path.startswith("/ws/"):
            token = request.headers.get("X-Backend-Token", "")
            if token != args.token:
                return JSONResponse(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    content={"detail": "invalid or missing X-Backend-Token"},
                )

        return await call_next(request)


# =====================================================================
# 应用工厂
# =====================================================================

def create_app(args: argparse.Namespace) -> FastAPI:
    """构造 FastAPI 应用（含 lifespan / 中间件 / 路由）。"""
    app = FastAPI(
        title="PersonalWindowGLM Backend",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )
    app.state.args = args
    app.state.ready = False
    app.state.started_at = 0.0
    app.state.skill_agent = None
    app.state.memory = None
    app.state.executor = None
    app.state.components = None
    app.state.loop = None

    # 中间件
    app.add_middleware(TokenAuthMiddleware)
    # CORS：允许各运行模式的前端源跨域
    # - http://localhost:5173 / 1420：浏览器 dev（Vite）
    # - tauri://localhost：macOS 打包（WKWebView）
    # - http://tauri.localhost：Windows 打包（WebView2）
    # - http://localhost：Linux 打包（WebKitGTK）
    # 缺一会导致打包后前端所有 REST 请求被 CORS 预检拦截（400 Disallowed CORS origin）
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://localhost:1420",
            "tauri://localhost",
            "http://tauri.localhost",
            "http://localhost",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 健康检查路由（直接挂在 app，不走 token 中间件白名单已覆盖）
    @app.get("/api/health", response_model=HealthResponse, tags=["health"])
    def health() -> HealthResponse:
        ready = getattr(app.state, "ready", False)
        components: BackendComponents | None = getattr(app.state, "components", None)
        scheduler_running = (
            components is not None
            and components.task_scheduler is not None
            and components.task_scheduler.is_running
        )
        started_at = getattr(app.state, "started_at", 0.0)
        uptime_s = (time.time() - started_at) if started_at else 0.0
        # 悬浮球退出请求（Tauri 健康巡检兜底通道）
        floating_ball = components.floating_ball if components is not None else None
        quit_requested = bool(getattr(floating_ball, "quit_requested", False))
        return HealthResponse(
            status="ok",
            uptime_s=uptime_s,
            skill_agent_ready=(
                components is not None and components.skill_agent is not None
            ),
            scheduler_running=scheduler_running,
            active_runs=1 if run_coordinator.is_busy() else 0,
            queue_size=run_coordinator.queue_size(),
            ws_clients=ws_manager.total_clients(),
            quit_requested=quit_requested,
        )

    @app.get("/api/ready", response_model=ReadyResponse, tags=["health"])
    def ready() -> JSONResponse:
        is_ready = bool(getattr(app.state, "ready", False))
        return JSONResponse(
            status_code=status.HTTP_200_OK if is_ready else status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"ready": is_ready},
        )

    @app.post("/api/quit", tags=["health"])
    async def request_quit() -> dict:
        """请求后端优雅退出（Tauri quit_app 统一调用）。

        - BACKEND_EXTERNAL 模式（PyCharm 调试后端）：这是终止后端的唯一手段，
          否则 Tauri 退出后外部后端进程会残留。
        - sidecar 模式：与 taskkill 互补，让 DB / 调度器 / 悬浮球先做清理。

        实现：置 uvicorn Server.should_exit → 停止接受新连接并关闭 WS
        → lifespan 清理（shutdown_backend_components 会 stop 悬浮球子进程）
        → 进程退出。延迟 0.3s 置位，让本响应先发出去。
        """
        server = getattr(app.state, "uvicorn_server", None)
        if server is None:
            return {"status": "no-server"}
        asyncio.get_running_loop().call_later(
            0.3, setattr, server, "should_exit", True
        )
        return {"status": "quitting"}

    # 业务路由
    app.include_router(conversations_router.router)
    app.include_router(messages_router.router)
    app.include_router(agent_router.router)
    app.include_router(skills_router.router)
    app.include_router(recording_router.router)
    app.include_router(files_router.router)
    app.include_router(settings_router.router)
    app.include_router(floating_ball_router.router)
    app.include_router(cli_router.router)
    app.include_router(ws_router.router)

    return app


# =====================================================================
# 入口（uvicorn 直接运行用）
# =====================================================================

def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    import uvicorn
    app = create_app(args)
    # 显式构造 Server 并存入 app.state，供 /api/quit 触发优雅退出
    # （uvicorn.run 内部就是 Server(config).run()，行为等价）
    config = uvicorn.Config(app, host=args.host, port=args.port, log_level="info")
    server = uvicorn.Server(config)
    app.state.uvicorn_server = server
    server.run()


if __name__ == "__main__":
    main()
