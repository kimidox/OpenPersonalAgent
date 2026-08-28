"""压缩包暂存解压模块。

用户在对话框上传 zip 压缩包（可能是 skill 包或 CLI 包）时：
1. 解压到 PersonalData/staging/<file_id>/（含 Zip Slip 防护）
2. 生成文件树文本，随用户 query 一起注入对话，供 Agent 判断包类型
3. 暂存目录惰性清理（超过 24h 自动删除），避免 PersonalData 膨胀
"""
from __future__ import annotations

import shutil
import time
import zipfile
from pathlib import Path

from logger import get_module_logger

logger = get_module_logger("archive_staging")

# 暂存目录保留时长（秒），过期目录在下次解压时惰性清理
_STAGING_MAX_AGE_SEC = 24 * 3600

# 文件树最大条目数，避免超大压缩包撑爆上下文
_TREE_MAX_ENTRIES = 200


def _get_staging_root() -> Path:
    """暂存根目录：PersonalData/staging/"""
    import config
    root = Path(config.WORKER_DIR) / "staging"
    root.mkdir(parents=True, exist_ok=True)
    return root


def cleanup_staging(max_age_sec: int = _STAGING_MAX_AGE_SEC) -> int:
    """清理过期的暂存目录，返回删除的目录数。"""
    root = _get_staging_root()
    now = time.time()
    deleted = 0
    try:
        for entry in root.iterdir():
            try:
                if entry.is_dir() and now - entry.stat().st_mtime > max_age_sec:
                    shutil.rmtree(entry)
                    deleted += 1
            except OSError as e:
                logger.warning(f"清理暂存目录失败 {entry}: {e}")
    except OSError as e:
        logger.warning(f"遍历暂存根目录失败: {e}")
    return deleted


def extract_archive_safe(zip_path: str | Path, file_id: str) -> Path:
    """安全解压 zip 到暂存目录。

    Zip Slip 防护：逐条校验每个成员的解压目标路径必须落在暂存目录内，
    检测到路径逃逸时立即中止并抛出 ValueError。

    Args:
        zip_path: zip 文件路径
        file_id: 上传文件 ID，作为暂存目录名

    Returns:
        解压后的暂存目录路径

    Raises:
        FileNotFoundError: zip 文件不存在
        ValueError: 不是有效 zip 或检测到路径逃逸
    """
    src = Path(zip_path)
    if not src.exists():
        raise FileNotFoundError(f"ZIP文件不存在: {src}")
    if not zipfile.is_zipfile(src):
        raise ValueError(f"文件不是有效的ZIP格式: {src}")

    # 惰性清理过期暂存目录（不阻塞主流程，失败仅记录）
    try:
        cleanup_staging()
    except Exception as e:  # noqa: BLE001
        logger.debug(f"暂存目录惰性清理异常（忽略）: {e}")

    staging_dir = _get_staging_root() / file_id
    if staging_dir.exists():
        shutil.rmtree(staging_dir)
    staging_dir.mkdir(parents=True)

    resolved_root = staging_dir.resolve()
    with zipfile.ZipFile(src, "r") as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            # Zip Slip 显式防护：拒绝含 ".." 的成员路径（恶意路径逃逸标志）
            parts = Path(info.filename).parts
            if ".." in parts:
                shutil.rmtree(staging_dir, ignore_errors=True)
                raise ValueError(
                    f"检测到恶意压缩包路径（Zip Slip）：{info.filename}，已中止解压"
                )
            # 跳过隐藏文件和 __pycache__（与 skill 安装逻辑一致）
            if any(part.startswith(".") or part == "__pycache__" for part in parts):
                continue
            target = (staging_dir / info.filename).resolve()
            try:
                target.relative_to(resolved_root)
            except ValueError:
                shutil.rmtree(staging_dir, ignore_errors=True)
                raise ValueError(
                    f"检测到恶意压缩包路径（Zip Slip）：{info.filename}，已中止解压"
                )
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as fsrc, open(target, "wb") as fdst:
                shutil.copyfileobj(fsrc, fdst)

    logger.info(f"压缩包已暂存解压: {src} -> {staging_dir}")
    return staging_dir


def build_file_tree_text(staging_dir: Path, max_entries: int = _TREE_MAX_ENTRIES) -> str:
    """生成暂存目录的文件树文本（相对路径 + 大小），供 Agent 判断包类型。"""
    entries: list[tuple[Path, int]] = []
    try:
        for p in sorted(staging_dir.rglob("*")):
            if p.is_file():
                try:
                    entries.append((p, p.stat().st_size))
                except OSError:
                    continue
            if len(entries) >= max_entries:
                break
    except OSError as e:
        return f"（生成文件树失败: {e}）"

    if not entries:
        return "（压缩包为空或只包含目录结构）"

    lines = []
    for p, size in entries:
        rel = p.relative_to(staging_dir).as_posix()
        lines.append(f"- {rel} ({size} 字节)")
    if len(entries) >= max_entries:
        lines.append(f"...（文件数超过 {max_entries}，已截断）")
    return "\n".join(lines)


def build_archive_brief(zip_path: str | Path, file_id: str) -> str:
    """暂存解压并生成注入对话的完整文本块。

    内容包括：zip 原始路径（供安装工具使用）、暂存目录路径
    （供 Agent 进一步查看包内文件）、文件树、安装工具提示。
    """
    staging_dir = extract_archive_safe(zip_path, file_id)
    tree = build_file_tree_text(staging_dir)
    return (
        "【用户上传了 ZIP 压缩包，可能是 Skill 包或 CLI 包，请根据文件树结构判断类型】\n\n"
        f"压缩包原始路径（安装工具的 zip_path 参数使用此路径）: {Path(zip_path).resolve()}\n"
        f"暂存解压目录（可进一步读取包内文件内容辅助判断）: {staging_dir}\n\n"
        f"包内文件树：\n{tree}\n\n"
        "判断指引：\n"
        "- 含 SKILL.md 或多个 .md 文件的包 → 调用 install_skill_from_zip 工具安装（参数 zip_path 使用上面的压缩包原始路径）\n"
        "- 含 cli.json 清单文件的包 → 调用 install_cli_package 工具安装（参数 zip_path 使用上面的压缩包原始路径）\n"
        "- 可先读取暂存目录中的 cli.json / SKILL.md 内容确认类型后再安装\n"
        "- 如两者都不满足，告知用户该压缩包不是可安装的 Skill/CLI 包"
    )
