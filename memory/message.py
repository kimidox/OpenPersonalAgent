from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

# 占位符语法：<Skill:id/>、<File:file_id/>、<Cli:name/>
# content 中仅作为位置锚点；权威数据在 ext（forced_refs / files）。
_REF_PLACEHOLDER_RE = re.compile(r"<(Skill|File|Cli):([A-Za-z0-9_\-]+)/>")


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

    def _ref_backing(self, kind: str, ref_id: str) -> dict[str, Any] | None:
        """校验占位符是否有 ext 元数据背书；返回对应的元数据项（无背书返回 None）。

        防止用户手打伪造的占位符被渲染为引用标记。
        """
        ext = self.ext or {}
        refs = ext.get("forced_refs") or []
        files = ext.get("files") or []
        if kind == "File":
            for f in files:
                if isinstance(f, dict) and f.get("file_id") == ref_id:
                    return f
            for r in refs:
                if isinstance(r, dict) and r.get("type") == "file" and r.get("id") == ref_id:
                    return r
            return None
        ref_type = {"Skill": "skill", "Cli": "cli"}.get(kind)
        if ref_type is None:
            return None
        for r in refs:
            if isinstance(r, dict) and r.get("type") == ref_type and r.get("id") == ref_id:
                return r
        return None

    def _render_ref_marker(self, m: re.Match) -> str:
        """把单个占位符渲染为历史轮短标记（无背书时原样保留）。"""
        kind, ref_id = m.group(1), m.group(2)
        backing = self._ref_backing(kind, ref_id)
        if backing is None:
            return m.group(0)
        if kind == "File":
            name = backing.get("file_name") or backing.get("original_name") or ref_id
            return (
                f"[用户曾上传文件「{name}」（file_id: {ref_id}），"
                f"需要内容时调用 read_uploaded_file 工具获取]"
            )
        if kind == "Skill":
            name = backing.get("name") or ref_id
            return f"[用户曾强制引用 Skill「{name}」]"
        return f"[用户曾强制引用 CLI「{ref_id}」]"

    def _process_refs(self, content: str | list) -> str | list:
        """扫描 content 中的占位符，历史轮统一降级为短标记。

        仅处理 user 角色的文本内容（图片走 image_ref 通道，互不干扰）。
        当前轮（发送给 LLM 的最新 user 消息）不经过本方法：
        由 SkillAgent 在发送时刻注入完整文档，此处只负责历史轮降级，
        避免每轮重复注入 skill 文档 / 文件全文导致上下文膨胀。
        """
        if isinstance(content, str):
            if not _REF_PLACEHOLDER_RE.search(content):
                return content
            return _REF_PLACEHOLDER_RE.sub(self._render_ref_marker, content)
        if isinstance(content, list):
            has_ref = any(
                isinstance(item, dict)
                and item.get("type") == "text"
                and _REF_PLACEHOLDER_RE.search(str(item.get("text", "")))
                for item in content
            )
            if not has_ref:
                return content
            return [
                {
                    **item,
                    "text": _REF_PLACEHOLDER_RE.sub(
                        self._render_ref_marker, str(item.get("text", ""))
                    ),
                }
                if isinstance(item, dict) and item.get("type") == "text"
                else item
                for item in content
            ]
        return content

    def to_llm_dict(self, *, render_refs: bool = True) -> dict[str, Any]:
        """拼装为 `BaseChatModel.complete_with_tools` 所需的 message 字典。

        关键修复：还原 OpenAI tool calling 协议要求的消息结构。
        - assistant 工具调用记录（ext.type == "tool_call"）还原为
          {"role": "assistant", "content": ..., "tool_calls": [...]}
          使后续的 tool 结果消息有正确的前置 assistant 消息关联。
        - tool 消息同时附带 tool_call_id（与前置 assistant.tool_calls[].id 对应），
          以满足 OpenAI 新格式与部分国产模型（Qwen/GLM）的校验要求。

        Args:
            render_refs: 是否把 user 消息中的占位符降级为历史轮短标记。
                LLM 上下文构建传 True（默认）；UI 历史恢复（to_record_dict）
                传 False 以保留原始占位符供前端渲染 chip。
        """
        ext = self.ext or {}

        # assistant 工具调用记录：还原为带 tool_calls 的 assistant 消息
        if self.role == "assistant" and ext.get("type") == "tool_call":
            name = str(ext.get("name", ""))
            args = ext.get("args") or "{}"
            if isinstance(args, (dict, list)):
                args = __import__("json").dumps(args, ensure_ascii=False)
            elif isinstance(args, str):
                # 校验历史存储的 args 是否为有效 JSON，防止非 JSON 字符串导致 API 报错
                try:
                    __import__("json").loads(args)
                except (ValueError, __import__("json").JSONDecodeError):
                    args = "{}"
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

        # user 消息中的占位符（<Skill:id/> 等）历史轮降级为短标记
        if self.role == "user" and render_refs:
            processed_content = self._process_refs(processed_content)

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

        占位符不做降级（render_refs=False）：content 保留 `<Skill:id/>` 等
        原始占位符，前端结合 metadata 渲染引用 chip。
        """
        d = dict(self.to_llm_dict(render_refs=False))
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
