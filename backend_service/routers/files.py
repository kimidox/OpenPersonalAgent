"""文件上传与解析路由。

流程：
1. 文件持久化到 uploads 存储（manifest 索引 + sidecar 解析文本）
2. 解析通过 ParserFactory（document_parser/parser_factory.py）
3. 发送时由 SkillAgent 按 query 中 <File:fid/> 占位符从持久层懒加载注入
   （/set-content 旧接口仅为兼容保留，标记 deprecated）
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from pydantic import BaseModel

from backend_service.deps import require_skill_agent

router = APIRouter(prefix="/api/files", tags=["files"])


# =====================================================================
# 模型
# =====================================================================

class UploadResponse(BaseModel):
    file_id: str
    original_name: str
    file_size: int
    mime_type: str | None = None
    parsed_text: str = ""
    parsed_pages: int = 0


class SetUploadedContentRequest(BaseModel):
    """把已解析的内容设置到 SkillAgent（供后续 run 使用）。"""
    content: str | dict


class SetUploadedContentResponse(BaseModel):
    set: bool


class CleanupResponse(BaseModel):
    deleted_count: int
    total_size: int


# =====================================================================
# 路由
# =====================================================================

def _get_storage() -> Any:
    from document_parser.file_storage import FileStorage
    # 默认 storage_dir（PersonalData 下）
    return FileStorage()


@router.post("/upload", response_model=UploadResponse)
async def upload_file(
    agent=Depends(require_skill_agent),
    file: UploadFile = File(...),
) -> UploadResponse:
    """上传文件 → 持久化保存 → 解析 → 返回 file_id 与解析文本。

    文件与解析文本存入 PersonalData/uploads（manifest 索引 + sidecar），
    供占位符注入与 read_uploaded_file 工具跨会话懒加载。
    """
    from document_parser import file_storage

    content_bytes = await file.read()
    original_name = file.filename or "upload.bin"
    try:
        info = file_storage.save_upload(
            content_bytes,
            original_name=original_name,
            mime_type=file.content_type,
        )
    except Exception as e:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"保存文件失败: {e}",
        )

    # 压缩包分支：暂存解压 + 文件树注入（不走文档解析）
    # zip 可能是 Skill 包或 CLI 包，解压到 PersonalData/staging/ 供 Agent 判断类型并安装
    if original_name.lower().endswith(".zip"):
        parsed_text = ""
        try:
            from backend_service.archive_staging import build_archive_brief
            parsed_text = build_archive_brief(Path(info["file_path"]), info["file_id"])
        except ValueError as e:
            parsed_text = f"[压缩包处理失败: {e}]"
        except Exception as e:  # noqa: BLE001
            parsed_text = f"[压缩包处理失败: {e}]"
        # 压缩包 brief 一并持久化（sidecar）
        _persist_sidecar(info["file_id"], parsed_text)
        return UploadResponse(
            file_id=info["file_id"],
            original_name=original_name,
            file_size=info["file_size"],
            mime_type=info["mime_type"],
            parsed_text=parsed_text,
            parsed_pages=0,
        )

    # 解析
    parsed_text = ""
    parsed_pages = 0
    try:
        from document_parser.parser_factory import parse_file
        result = parse_file(Path(info["file_path"]))
        # ParseResult 的文本在 content 属性，不是 text
        parsed_text = result.content or ""
        # page_count 不是 ParseResult 标准字段，从 metadata 中尝试获取
        parsed_pages = result.metadata.get("page_count", 0) or 0
    except Exception as e:  # noqa: BLE001
        # 解析失败不阻断上传，但记录到 detail
        parsed_text = f"[解析失败: {e}]"

    # 解析文本持久化为 sidecar（发送时懒加载，无需前端回传）
    _persist_sidecar(info["file_id"], parsed_text)

    return UploadResponse(
        file_id=info["file_id"],
        original_name=original_name,
        file_size=info["file_size"],
        mime_type=info["mime_type"],
        parsed_text=parsed_text,
        parsed_pages=parsed_pages,
    )


def _persist_sidecar(file_id: str, parsed_text: str) -> None:
    """把解析文本写入 sidecar 并更新 manifest（save_upload 未传 parsed_text 时补写）。"""
    try:
        from document_parser.file_storage import persist_parsed_text
        persist_parsed_text(file_id, parsed_text)
    except Exception:  # noqa: BLE001
        pass


@router.post("/set-content", response_model=SetUploadedContentResponse)
def set_uploaded_content(
    body: SetUploadedContentRequest,
    agent=Depends(require_skill_agent),
) -> SetUploadedContentResponse:
    """把解析后的内容设置到 SkillAgent，供下一次 run 使用。"""
    try:
        agent.set_uploaded_files_content(body.content)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"设置上传内容失败: {e}",
        )
    return SetUploadedContentResponse(set=True)


@router.get("/{file_id}", response_model=dict)
def get_file_info(file_id: str) -> dict:
    """查询文件元信息（持久层 manifest）。"""
    from document_parser.file_storage import get_upload_info

    info = get_upload_info(file_id)
    if info is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文件不存在")
    return info


@router.get("/{file_id}/download")
def download_file(file_id: str) -> bytes:
    """下载文件原始字节（持久层）。"""
    from document_parser.file_storage import get_upload_info, _get_uploads_storage

    info = get_upload_info(file_id)
    if info is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文件不存在")
    file_path = _get_uploads_storage() / info.get("stored_name", "")
    if not file_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文件不存在")
    with open(file_path, "rb") as f:
        return f.read()


@router.delete("/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_file(file_id: str) -> None:
    """删除文件（原始文件 + sidecar + manifest 条目）。"""
    from document_parser.file_storage import delete_upload

    ok = delete_upload(file_id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文件不存在")


@router.post("/cleanup", response_model=CleanupResponse)
def cleanup_files(max_age_hours: int = 24) -> CleanupResponse:
    """清理超过 max_age_hours 小时的临时文件。"""
    storage = _get_storage()
    deleted = storage.cleanup_old_files(max_age_hours=max_age_hours)
    # FileStorage.cleanup_old_files 返回删除条数，无 total_size
    return CleanupResponse(deleted_count=deleted, total_size=storage.get_storage_size())


@router.post("/images/cleanup", response_model=CleanupResponse)
def cleanup_images(days: int | None = None) -> CleanupResponse:
    """清理过期图片（document_parser/file_storage.cleanup_old_images）。"""
    from document_parser.file_storage import cleanup_old_images
    result = cleanup_old_images(days=days)
    return CleanupResponse(
        deleted_count=result.get("deleted_count", 0),
        total_size=result.get("total_size", 0),
    )
