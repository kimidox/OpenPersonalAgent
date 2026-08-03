"""安装验证与报告模块。

从 dispatch.py 拆分而来，负责：
- SkillHub CLI 安装验证
- Skill 包安装验证
- 验证报告生成
- SKILL.md YAML front matter 解析
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml

from logger import get_module_logger

logger = get_module_logger("ToolDispatch")


def verify_skillhub_installation() -> tuple[bool, str]:
    """
    验证 SkillHub CLI 是否安装成功。

    执行 `skillhub --version` 命令，检查 SkillHub CLI 是否可用。

    Returns:
        tuple[bool, str]: (是否验证成功, 版本信息或错误消息)
    """
    # 延迟导入，避免与 dispatch.py 产生循环引用
    from .dispatch import _decode_output

    try:
        # 执行 skillhub --version 命令
        result = subprocess.run(
            ["skillhub", "--version"],
            capture_output=True,
            text=False,
            timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0,
        )

        # 解码输出
        stdout = _decode_output(result.stdout or b"")
        stderr = _decode_output(result.stderr or b"")

        if result.returncode == 0:
            # 提取版本信息
            version_info = stdout.strip() if stdout.strip() else "版本信息未知"
            logger.info(f"SkillHub CLI 验证成功: {version_info}")
            return True, f"验证成功，版本信息: {version_info}"
        else:
            error_msg = stderr.strip() if stderr.strip() else "未知错误"
            logger.warning(f"SkillHub CLI 验证失败: {error_msg}")
            return False, f"验证失败，错误: {error_msg}"

    except FileNotFoundError:
        # skillhub 命令不存在
        error_msg = "SkillHub CLI 未安装或未添加到 PATH 环境变量"
        logger.warning(error_msg)
        return False, error_msg + _get_skillhub_installation_guide()
    except subprocess.TimeoutExpired:
        error_msg = "验证超时，SkillHub CLI 可能未正确安装"
        logger.warning(error_msg)
        return False, error_msg
    except Exception as e:
        error_msg = f"验证异常: {e}"
        logger.error(error_msg)
        return False, error_msg


def verify_skill_installation(skill_dir: str) -> tuple[bool, str]:
    """
    验证 Skill 是否安装成功。

    检查目标目录是否存在 SKILL.md 文件，并验证元数据是否正确。

    Args:
        skill_dir: Skill 安装目录路径

    Returns:
        tuple[bool, str]: (是否验证成功, 消息)
    """
    try:
        skill_path = Path(skill_dir)

        # 检查目录是否存在
        if not skill_path.exists():
            return False, f"Skill 目录不存在: {skill_dir}"

        if not skill_path.is_dir():
            return False, f"路径不是目录: {skill_dir}"

        # 检查 SKILL.md 文件是否存在
        skill_file = skill_path / "SKILL.md"
        if not skill_file.exists():
            return False, f"SKILL.md 文件不存在: {skill_file}"

        if not skill_file.is_file():
            return False, f"SKILL.md 不是文件: {skill_file}"

        # 读取并解析 SKILL.md 文件
        try:
            content = skill_file.read_text(encoding="utf-8")
        except Exception as e:
            return False, f"读取 SKILL.md 失败: {e}"

        # 解析 YAML front matter
        metadata = _parse_skill_yaml_front_matter(content)

        if metadata is None:
            return False, f"SKILL.md 文件格式错误: 缺少有效的 YAML front matter"

        # 验证必要的元数据字段
        required_fields = ["id", "name"]
        missing_fields = [field for field in required_fields if not metadata.get(field)]

        if missing_fields:
            return False, f"SKILL.md 元数据缺少必要字段: {', '.join(missing_fields)}"

        # 验证成功
        skill_id = metadata.get("id", "")
        skill_name = metadata.get("name", "")
        skill_description = metadata.get("description", "")

        logger.info(f"Skill 验证成功: ID={skill_id}, Name={skill_name}")

        return True, (
            f"验证成功:\n"
            f"- Skill ID: {skill_id}\n"
            f"- 名称: {skill_name}\n"
            f"- 描述: {skill_description[:50]}..." if len(skill_description) > 50 else f"- 描述: {skill_description}"
        )

    except Exception as e:
        error_msg = f"验证异常: {e}"
        logger.error(error_msg)
        return False, error_msg


def _parse_skill_yaml_front_matter(content: str) -> dict | None:
    """
    解析 SKILL.md 文件的 YAML front matter。

    Args:
        content: Markdown 文件内容

    Returns:
        dict | None: 解析后的元数据字典，解析失败返回 None
    """
    try:
        if not content.startswith("---"):
            return None

        parts = content.split("---", 2)
        if len(parts) < 3:
            return None

        yaml_content = parts[1].strip()

        try:
            metadata = yaml.safe_load(yaml_content)
            if not isinstance(metadata, dict):
                return None
            return metadata
        except yaml.YAMLError as e:
            logger.warning(f"YAML 解析失败: {e}")
            return None

    except Exception as e:
        logger.warning(f"解析 YAML front matter 失败: {e}")
        return None


def _get_skillhub_installation_guide() -> str:
    """
    获取 SkillHub CLI 安装指引。

    Returns:
        str: 安装指引字符串
    """
    return """

【SkillHub CLI 安装指引】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

方法1: 使用 pip 安装（推荐）
pip install skillhub-cli

方法2: 使用安装脚本
Invoke-WebRequest -Uri "https://skillhub.cn/install.ps1" | Invoke-Expression

方法3: 从 GitHub 安装
pip install git+https://github.com/skillhub/skillhub-cli.git

【验证安装】
安装完成后，请在新的终端窗口中运行：
skillhub --version

如果提示"命令未找到"，请：
1. 确认 Python 已正确安装并添加到 PATH
2. 重新打开终端窗口
3. 检查 pip 安装路径是否在 PATH 中
"""


def verify_and_report_skillhub_installation() -> str:
    """
    验证 SkillHub CLI 安装并返回详细的报告。

    Returns:
        str: 验证报告字符串
    """
    success, message = verify_skillhub_installation()

    if success:
        report = f"""
✓ SkillHub CLI 安装验证成功

{message}

【下一步】
您可以开始使用 SkillHub CLI 安装 Skill：
1. 列出可用的 Skill: skillhub list
2. 安装 Skill: skillhub install <skill_id>
3. 查看帮助: skillhub --help
"""
    else:
        report = f"""
✗ SkillHub CLI 安装验证失败

{message}

【故障排查建议】
1. 确认已正确安装 SkillHub CLI
2. 检查 Python 和 pip 是否正确安装
3. 确认安装路径已添加到 PATH 环境变量
4. 尝试重新打开终端窗口
"""

    return report


def verify_and_report_skill_installation(skill_dir: str) -> str:
    """
    验证 Skill 安装并返回详细的报告。

    Args:
        skill_dir: Skill 安装目录路径

    Returns:
        str: 验证报告字符串
    """
    success, message = verify_skill_installation(skill_dir)

    if success:
        report = f"""
✓ Skill 安装验证成功

安装目录: {skill_dir}

{message}

【下一步】
您现在可以使用此 Skill：
- 查看 Skill 详情: manage_skill(action="get_info", skill_id="<id>")
- 列出已安装 Skill: manage_skill(action="list")
"""
    else:
        report = f"""
✗ Skill 安装验证失败

安装目录: {skill_dir}

{message}

【故障排查建议】
1. 确认 Skill 目录路径正确
2. 检查 SKILL.md 文件是否存在
3. 验证 SKILL.md 文件格式是否正确（YAML front matter）
4. 检查元数据是否包含必要的字段（id、name）
"""

    return report
