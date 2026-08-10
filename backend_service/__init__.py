"""Python 后端服务层（FastAPI）。

作为 Tauri 前端的唯一入口，封装 SkillAgent / Memory / Scheduler 等后端模块，
通过 HTTP REST（命令）与 WebSocket（流式事件）对外提供服务。

阶段 1：协议地基（端口握手 / 健康检查 / WS 事件 / 并发控制 / AgentEventType 桥）。
详见 .trae/documents/frontend-tauri-refactor.md。
"""
