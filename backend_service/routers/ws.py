"""WebSocket 路由：流式事件订阅 + ?since= 重放（3.14 节）。

端点：ws://host/ws/stream?conversation_id={id}&since={lastEventId}

生命周期：
1. 接受连接 → ws_manager.connect（含重放）
2. 阻塞接收客户端消息（心跳/未来扩展）
3. 断开 → ws_manager.disconnect

WSManager.broadcast 在事件循环内执行，路由层只需管连接生命周期。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect, status

from backend_service.deps import get_ws_manager
from backend_service.ws.manager import WSManager

router = APIRouter(tags=["ws"])


@router.websocket("/ws/stream")
async def ws_stream(
    websocket: WebSocket,
    ws_manager: WSManager = Depends(get_ws_manager),
) -> None:
    """WS 流式端点。

    Query 参数：
        conversation_id: 必填，订阅该会话的全部流式事件。
        since: 可选，上次收到的最大 event_id；用于断线重连重放。
    """
    conversation_id = websocket.query_params.get("conversation_id", "").strip()
    if not conversation_id:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    since_str = websocket.query_params.get("since", "0")
    try:
        since = max(0, int(since_str))
    except ValueError:
        since = 0

    await ws_manager.connect(websocket, conversation_id, since=since)

    try:
        # 阻塞接收客户端消息（心跳或未来控制消息）
        # 当前协议无客户端→服务端消息定义，收到即忽略
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception:
        # 其他异常（如运行时关闭）也按断开处理
        pass
    finally:
        await ws_manager.disconnect(websocket, conversation_id)
        try:
            await websocket.close()
        except Exception:
            pass
