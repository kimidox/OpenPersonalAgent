"""CLI 包管理器。

CLI 包 = 含 cli.json 清单的压缩包，安装到 PersonalData/CLI/<name>/。
Agent 安装后通过 run_command 按清单中的 entry/commands 调用。

cli.json 清单规范（最小集）：
{
  "name": "ffmpeg-tool",          # 必填，包名（同时作为安装目录名）
  "version": "1.0.0",             # 可选
  "description": "格式转换工具",    # 可选
  "entry": "bin/main.py",         # 必填，入口文件（相对包根）
  "commands": [                   # 可选，命令用法说明
    {"usage": "python bin/main.py convert <in> <out>", "desc": "格式转换"}
  ]
}
"""
from __future__ import annotations

import json
import re
import shutil
import zipfile
from pathlib import Path

from logger import get_module_logger

logger = get_module_logger("cli_manager")

# 包名合法性：字母/数字/连字符/下划线，防路径注入
_NAME_RE = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")

_MANIFEST_FILENAME = "cli.json"


def get_cli_packages_dir() -> Path:
    """CLI 包安装根目录：PersonalData/CLI/"""
    import config
    cli_dir = Path(config.WORKER_DIR) / "CLI"
    cli_dir.mkdir(parents=True, exist_ok=True)
    return cli_dir


def _find_manifest_in_zip(zf: zipfile.ZipFile) -> tuple[str, dict] | None:
    """在 zip 中定位 cli.json 并返回 (zip内路径, 解析后的 manifest)。

    支持两种位置：zip 根目录、唯一一级子目录下。
    """
    names = [n for n in zf.namelist() if not n.endswith("/")]
    root_manifests = [n for n in names if n == _MANIFEST_FILENAME]
    if root_manifests:
        return _load_manifest(zf, root_manifests[0])

    # 子目录下的 manifest：取第一个匹配（多子目录时不猜测）
    subdir_manifests = [
        n for n in names
        if n.count("/") == 1 and n.endswith("/" + _MANIFEST_FILENAME)
    ]
    if len(subdir_manifests) == 1:
        return _load_manifest(zf, subdir_manifests[0])
    return None


def _load_manifest(zf: zipfile.ZipFile, manifest_name: str) -> tuple[str, dict] | None:
    try:
        raw = zf.read(manifest_name).decode("utf-8")
        data = json.loads(raw)
        if isinstance(data, dict):
            return manifest_name, data
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        logger.warning(f"cli.json 解析失败 ({manifest_name}): {e}")
    return None


def _validate_manifest(manifest: dict) -> tuple[str, str]:
    """校验 manifest 必填字段，返回 (错误信息, name)。错误为空表示通过。"""
    name = str(manifest.get("name", "")).strip()
    entry = str(manifest.get("entry", "")).strip()
    if not _NAME_RE.match(name):
        return f"cli.json 的 name 字段非法（仅允许字母/数字/连字符/下划线，长度1-64）: {name!r}", ""
    if not entry:
        return "cli.json 缺少 entry 字段（入口文件，相对包根路径）", ""
    return "", name


def install_cli_package_from_zip(zip_path: str, overwrite: bool = False) -> tuple[dict, str]:
    """从 zip 安装 CLI 包。

    Args:
        zip_path: zip 文件路径
        overwrite: 是否覆盖已安装的同名包

    Returns:
        (manifest信息, 错误信息)。错误非空表示失败。
    """
    src = Path(zip_path)
    if not src.exists():
        return {}, f"ZIP文件不存在: {zip_path}"
    if not zipfile.is_zipfile(src):
        return {}, f"文件不是有效的ZIP格式: {zip_path}"

    try:
        with zipfile.ZipFile(src, "r") as zf:
            found = _find_manifest_in_zip(zf)
            if found is None:
                return {}, "ZIP 包中未找到 cli.json 清单文件（不是有效的 CLI 包）"
            manifest_name, manifest = found

            err, name = _validate_manifest(manifest)
            if err:
                return {}, err
            entry = str(manifest.get("entry", "")).strip()

            # manifest 所在的包根（根目录 或 唯一一级子目录）
            pkg_root_prefix = ""
            if "/" in manifest_name:
                pkg_root_prefix = manifest_name.split("/")[0] + "/"

            target_dir = get_cli_packages_dir() / name
            if target_dir.exists():
                if not overwrite:
                    return {}, f"CLI 包「{name}」已安装（{target_dir}），如需覆盖请设置 overwrite=true"
                shutil.rmtree(target_dir)

            # Zip Slip 防护解压
            target_dir.mkdir(parents=True)
            resolved_root = target_dir.resolve()
            try:
                for info in zf.infolist():
                    if info.is_dir():
                        continue
                    parts = Path(info.filename).parts
                    # Zip Slip 显式防护：拒绝含 ".." 的成员路径（恶意路径逃逸标志）
                    if ".." in parts:
                        shutil.rmtree(target_dir, ignore_errors=True)
                        return {}, f"检测到恶意压缩包路径（Zip Slip）：{info.filename}"
                    if any(part.startswith(".") or part == "__pycache__" for part in parts):
                        continue
                    # 只提取包根下的内容；zip 根目录模式 pkg_root_prefix 为空
                    if pkg_root_prefix and not info.filename.startswith(pkg_root_prefix):
                        continue
                    rel_name = info.filename[len(pkg_root_prefix):]
                    target = (target_dir / rel_name).resolve()
                    try:
                        target.relative_to(resolved_root)
                    except ValueError:
                        shutil.rmtree(target_dir, ignore_errors=True)
                        return {}, f"检测到恶意压缩包路径（Zip Slip）：{info.filename}"
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(info) as fsrc, open(target, "wb") as fdst:
                        shutil.copyfileobj(fsrc, fdst)
            except Exception:
                shutil.rmtree(target_dir, ignore_errors=True)
                raise

            # 校验入口文件存在
            if not (target_dir / entry).is_file():
                shutil.rmtree(target_dir, ignore_errors=True)
                return {}, f"cli.json 的 entry 文件不存在: {entry}"

            info_out = {
                "name": name,
                "version": str(manifest.get("version", "")),
                "description": str(manifest.get("description", "")),
                "entry": entry,
                "install_dir": str(target_dir),
                "commands": manifest.get("commands", []) if isinstance(manifest.get("commands"), list) else [],
            }
            logger.info(f"CLI 包安装成功: {name} -> {target_dir}")
            return info_out, ""
    except zipfile.BadZipFile:
        return {}, f"文件不是有效的ZIP格式: {zip_path}"


def list_cli_packages() -> list[dict]:
    """列出已安装的 CLI 包（扫描 PersonalData/CLI/ 下含 cli.json 的目录）。"""
    result = []
    root = get_cli_packages_dir()
    try:
        for entry in sorted(root.iterdir()):
            manifest_path = entry / _MANIFEST_FILENAME
            if entry.is_dir() and manifest_path.is_file():
                try:
                    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                    result.append({
                        "name": str(manifest.get("name", entry.name)),
                        "version": str(manifest.get("version", "")),
                        "description": str(manifest.get("description", "")),
                        "entry": str(manifest.get("entry", "")),
                        "install_dir": str(entry),
                        "commands": manifest.get("commands", []) if isinstance(manifest.get("commands"), list) else [],
                    })
                except (OSError, json.JSONDecodeError) as e:
                    logger.warning(f"读取 CLI 包清单失败 {manifest_path}: {e}")
    except OSError as e:
        logger.warning(f"扫描 CLI 包目录失败: {e}")
    return result


def get_cli_package(name: str) -> dict | None:
    """按包名获取已安装的 CLI 包信息。"""
    for pkg in list_cli_packages():
        if pkg.get("name") == name:
            return pkg
    return None


def format_cli_usage_text(pkg: dict) -> str:
    """格式化 CLI 包的用法说明文本（供注入 Agent 上下文）。"""
    lines = [
        f"# CLI 工具: {pkg.get('name', '')}",
        "",
        f"描述: {pkg.get('description') or '(无描述)'}",
        f"版本: {pkg.get('version') or '-'}",
        f"安装目录: {pkg.get('install_dir', '')}",
        f"入口文件: {pkg.get('entry', '')}",
    ]
    commands = pkg.get("commands") or []
    if commands:
        lines.append("")
        lines.append("可用命令：")
        for c in commands:
            if isinstance(c, dict):
                lines.append(f"- {c.get('usage', '')}  # {c.get('desc', '')}")
    return "\n".join(lines)
