"""
多模态消息处理工具

提供多模态消息格式处理功能，从包含文本和图片的消息中提取显示内容。
"""
from __future__ import annotations

import json
from typing import Any

from logger import get_logger


def extract_display_content(content: str | list[Any]) -> dict[str, Any]:
    """
    从多模态消息中提取文本和图片信息

    Args:
        content: 消息内容，可以是以下两种格式：
            - 字符串：纯文本消息
            - 列表：多模态消息，包含 text 和 image_url 元素
                例如：[
                    {"type": "text", "text": "这是一段文本"},
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}
                ]

    Returns:
        dict: 结构化数据，格式如下：
            {
                "text": str,  # 合并后的文本内容
                "images": [{"url": str, "mime_type": str}],  # 图片列表
                "has_images": bool  # 是否包含图片
            }

    Examples:
        >>> extract_display_content("你好")
        {"text": "你好", "images": [], "has_images": False}

        >>> extract_display_content([
        ...     {"type": "text", "text": "看这张图"},
        ...     {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}
        ... ])
        {"text": "看这张图", "images": [{"url": "data:image/png;base64,...", "mime_type": "image/png"}], "has_images": True}
    """
    logger = get_logger()

    # 初始化返回结构
    result = {
        "text": "",
        "images": [],
        "has_images": False
    }

    try:
        # 情况 1: 输入为字符串（纯文本消息）
        if isinstance(content, str):
            logger.debug(f"处理纯文本消息，长度: {len(content)}")
            result["text"] = content
            return result

        # 情况 2: 输入为列表（多模态消息）
        if isinstance(content, list):
            logger.debug(f"处理多模态消息，元素数量: {len(content)}")

            texts = []
            images = []

            # 遍历列表中的每个元素
            for idx, item in enumerate(content):
                if not isinstance(item, dict):
                    logger.warning(f"列表元素 {idx} 不是字典类型，跳过: {type(item)}")
                    continue

                # 获取元素类型
                item_type = item.get("type")

                # 提取文本内容
                if item_type == "text":
                    text = item.get("text", "")
                    if text:
                        texts.append(str(text))
                    logger.debug(f"提取文本元素 {idx}，长度: {len(text)}")

                # 提取图片信息
                elif item_type == "image_url":
                    image_url_data = item.get("image_url")
                    if isinstance(image_url_data, dict):
                        url = image_url_data.get("url", "")
                        if url:
                            # 提取 MIME 类型
                            mime_type = _extract_mime_type(url)

                            images.append({
                                "url": url,
                                "mime_type": mime_type
                            })
                            logger.debug(f"提取图片元素 {idx}，MIME 类型: {mime_type}")
                    else:
                        logger.warning(f"图片元素 {idx} 的 image_url 格式无效")

            # 合并所有文本内容（用换行符分隔）
            if texts:
                result["text"] = "\n".join(texts)
            elif images:
                # 如果只有图片没有文本，返回提示文本
                result["text"] = "[图片消息]"
                logger.debug("消息只包含图片，设置默认文本")

            # 设置图片列表
            result["images"] = images
            result["has_images"] = len(images) > 0

            logger.debug(
                f"多模态消息处理完成 - 文本长度: {len(result['text'])}, "
                f"图片数量: {len(images)}"
            )

            return result

        # 情况 3: 无法识别的格式，尝试转换为字符串
        logger.warning(f"无法识别的消息格式: {type(content)}，尝试转换为字符串")
        result["text"] = str(content)
        return result

    except Exception as e:
        logger.error(f"提取显示内容时发生错误: {e}", exc_info=True)
        # 错误情况下返回原始内容的字符串形式
        result["text"] = str(content)
        return result


def _extract_mime_type(url: str) -> str:
    """
    从 data URL 或普通 URL 中提取 MIME 类型

    Args:
        url: 图片 URL，可以是 data URL（data:image/png;base64,...）或普通 URL

    Returns:
        str: MIME 类型，如 "image/png"，如果无法提取则返回 "image/jpeg"

    Examples:
        >>> _extract_mime_type("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgA...")
        "image/png"

        >>> _extract_mime_type("https://example.com/image.jpg")
        "image/jpeg"
    """
    logger = get_logger()

    try:
        # 处理 data URL
        if url.startswith("data:"):
            # data URL 格式：data:image/png;base64,...
            # 提取 MIME 类型部分
            parts = url.split(",")
            if len(parts) > 0:
                # 获取 data:image/png;base64 部分
                data_part = parts[0]
                # 移除 "data:" 前缀
                if data_part.startswith("data:"):
                    mime_part = data_part[5:]
                    # 提取 MIME 类型（去除 ;base64 等参数）
                    if ";" in mime_part:
                        mime_type = mime_part.split(";")[0]
                    else:
                        mime_type = mime_part

                    if mime_type.startswith("image/"):
                        logger.debug(f"从 data URL 提取 MIME 类型: {mime_type}")
                        return mime_type

        # 处理普通 URL，尝试从扩展名推断
        if url.startswith("http") or url.startswith("/"):
            # 常见图片扩展名
            extensions = {
                ".png": "image/png",
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".gif": "image/gif",
                ".webp": "image/webp",
                ".bmp": "image/bmp",
                ".svg": "image/svg+xml",
            }

            url_lower = url.lower()
            for ext, mime in extensions.items():
                if ext in url_lower:
                    logger.debug(f"从 URL 扩展名推断 MIME 类型: {mime}")
                    return mime

        # 默认返回 JPEG 类型
        logger.debug("无法提取 MIME 类型，使用默认值: image/jpeg")
        return "image/jpeg"

    except Exception as e:
        logger.error(f"提取 MIME 类型时发生错误: {e}")
        return "image/jpeg"


def is_multimodal_content(content: Any) -> bool:
    """
    判断内容是否为多模态格式

    Args:
        content: 消息内容

    Returns:
        bool: 如果是列表格式则返回 True，否则返回 False

    Examples:
        >>> is_multimodal_content("纯文本")
        False

        >>> is_multimodal_content([{"type": "text", "text": "文本"}])
        True
    """
    return isinstance(content, list)


def try_parse_json_content(content: str) -> str | list[Any]:
    """
    尝试将字符串内容解析为 JSON（多模态格式）

    Args:
        content: 字符串内容

    Returns:
        如果解析成功且为列表格式，返回解析后的列表；否则返回原始字符串

    Examples:
        >>> try_parse_json_content('[{"type": "text", "text": "hello"}]')
        [{"type": "text", "text": "hello"}]

        >>> try_parse_json_content("纯文本")
        "纯文本"
    """
    logger = get_logger()

    # 如果不是字符串，直接返回
    if not isinstance(content, str):
        return content

    # 如果不以 '[' 开头，不可能是多模态格式
    stripped = content.strip()
    if not stripped.startswith("["):
        return content

    try:
        parsed = json.loads(content)
        # 只接受列表格式的 JSON
        if isinstance(parsed, list):
            logger.debug("成功解析多模态 JSON 内容")
            return parsed
        return content
    except json.JSONDecodeError:
        logger.debug("JSON 解析失败，保持原始字符串格式")
        return content