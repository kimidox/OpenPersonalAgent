from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass
class Message:
    """与 `database.models.Messages` 对应的领域消息（供 Memory 与业务层使用）。"""

    message_id: str
    conversation_id: str
    role: str
    content: str
    ext: dict[str, Any] | None = None
    created_at: datetime | None = None

    def _process_image_refs(self, content: str | list) -> str | list:
        """处理 content 中的图片引用，转换为 image_url 格式。

        参数：
            content: 消息内容，可能是字符串或列表

        返回：
            处理后的内容，可能是字符串或列表
        """
        # 获取 logger
        logger = logging.getLogger(__name__)

        # 如果 content 是字符串，尝试解析为 JSON list
        if isinstance(content, str):
            # 尝试解析为 JSON
            try:
                parsed_content = json.loads(content)
                if not isinstance(parsed_content, list):
                    # 不是列表，说明是纯文本字符串
                    return content
                content_list = parsed_content
            except (json.JSONDecodeError, TypeError):
                # JSON 解析失败，说明是纯文本字符串
                return content
        else:
            # content 已经是列表
            content_list = content

        # 检查是否包含 image_ref
        has_image_ref = any(
            isinstance(item, dict) and item.get("type") == "image_ref"
            for item in content_list
        )

        if not has_image_ref:
            # 没有 image_ref，返回解析后的列表（如果是 JSON 字符串转换的）
            # 这样可以确保内容格式统一
            return content_list

        # 导入图片加载服务
        try:
            from document_parser.file_storage import load_image_as_base64
        except ImportError as e:
            logger.error(f"导入图片加载服务失败: {e}")
            # 降级处理：替换所有 image_ref 为占位符
            processed_content = []
            for item in content_list:
                if isinstance(item, dict) and item.get("type") == "image_ref":
                    file_name = item.get("file_name", "未知文件")
                    processed_content.append({
                        "type": "text",
                        "text": f"[图片文件加载失败: {file_name}]"
                    })
                else:
                    processed_content.append(item)
            return processed_content

        # 处理图片引用
        processed_content = []
        for item in content_list:
            if isinstance(item, dict) and item.get("type") == "image_ref":
                # 提取图片引用信息
                file_path = item.get("file_path")
                file_name = item.get("file_name", "未知文件")

                if not file_path:
                    logger.warning(f"图片引用缺少 file_path: {item}")
                    processed_content.append({
                        "type": "text",
                        "text": f"[图片文件路径缺失: {file_name}]"
                    })
                    continue

                # 尝试加载图片
                try:
                    data_url = load_image_as_base64(file_path)
                    # 转换为 image_url 格式
                    processed_content.append({
                        "type": "image_url",
                        "image_url": {"url": data_url}
                    })
                    logger.debug(f"成功加载图片: {file_name} from {file_path}")
                except FileNotFoundError:
                    logger.warning(f"图片文件不存在: {file_path}")
                    processed_content.append({
                        "type": "text",
                        "text": f"[图片文件已丢失: {file_name}]"
                    })
                except Exception as e:
                    logger.error(f"加载图片失败: {file_path}, 错误: {e}")
                    processed_content.append({
                        "type": "text",
                        "text": f"[图片文件加载失败: {file_name}]"
                    })
            else:
                # 非 image_ref 元素，直接添加
                processed_content.append(item)

        return processed_content

    def to_llm_dict(self) -> dict[str, Any]:
        """拼装为 `BaseChatModel.complete_with_tools` 所需的 message 字典。

        关键修复：还原 OpenAI tool calling 协议要求的消息结构。
        - assistant 工具调用记录（ext.type == "tool_call"）还原为
          {"role": "assistant", "content": ..., "tool_calls": [...]}
          使后续的 tool 结果消息有正确的前置 assistant 消息关联。
        - tool 消息同时附带 tool_call_id（与前置 assistant.tool_calls[].id 对应），
          以满足 OpenAI 新格式与部分国产模型（Qwen/GLM）的校验要求。
        """
        ext = self.ext or {}

        # assistant 工具调用记录：还原为带 tool_calls 的 assistant 消息
        if self.role == "assistant" and ext.get("type") == "tool_call":
            name = str(ext.get("name", ""))
            args = ext.get("args") or "{}"
            if isinstance(args, (dict, list)):
                args = __import__("json").dumps(args, ensure_ascii=False)
            call_id = str(ext.get("tool_call_id") or "call_unknown")
            tool_calls = [{
                "id": call_id,
                "type": "function",
                "function": {"name": name, "arguments": str(args)},
            }]
            # content 可为 None（纯工具调用）或推理文本
            content = self.content if self.content else None
            return {
                "role": "assistant",
                "content": content,
                "tool_calls": tool_calls,
            }

        # 普通消息
        d: dict[str, Any] = {"role": self.role}

        # 处理图片引用，转换 content
        processed_content = self._process_image_refs(self.content)
        d["content"] = processed_content

        # tool 消息：附带 name 和 tool_call_id
        if self.role == "tool" and ext.get("name"):
            d["name"] = str(ext["name"])
            # 兜底：旧数据可能未持久化 tool_call_id，使用与 assistant 一致的默认值
            call_id = str(ext.get("tool_call_id") or "call_unknown")
            d["tool_call_id"] = call_id
        return d

    def to_record_dict(self) -> dict[str, Any]:
        """含 `metadata`（来自 ext）的记录，供 UI 恢复历史；不含 system 时可与 LLM 字典同构并附加元数据。

        关键修复：把 `to_llm_dict()` 里为 None 的 `content` 归一为空字符串，
        避免 UI 加载历史时通过 `str(None)` 渲染成字符串 "None"。
        """
        d = dict(self.to_llm_dict())
        if d.get("content") is None:
            d["content"] = ""
        if self.ext:
            d["metadata"] = dict(self.ext)
        return d

    @classmethod
    def from_orm(cls, row: Any) -> Message:
        from database.models import Messages as MessagesRow

        if not isinstance(row, MessagesRow):
            raise TypeError(f"expected Messages ORM row, got {type(row)!r}")
        return cls(
            message_id=str(row.message_id),
            conversation_id=str(row.conversation_id),
            role=str(row.role),
            content=str(row.content) if row.content is not None else "",
            ext=dict(row.ext) if row.ext is not None else None,
            created_at=row.created_at,
        )
