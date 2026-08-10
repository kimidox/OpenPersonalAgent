"""技能路由：list / toggle / bindings / install / delete。

SkillRegistry 在 SkillAgent 内部维护（agent.registry）。
disabled_skill_ids 与 skill_bindings 持久化在 skill_agent_preferences。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from pydantic import BaseModel

import skill_agent_preferences as prefs
from backend_service.deps import require_skill_agent

router = APIRouter(prefix="/api/skills", tags=["skills"])


# =====================================================================
# 模型
# =====================================================================

class SkillSummary(BaseModel):
    id: str
    name: str
    description: str = ""
    is_builtin: bool = False
    is_disabled: bool = False


class ToggleSkillRequest(BaseModel):
    disabled: bool


class SkillBindingsRequest(BaseModel):
    """conversation_type -> [skill_id] 的映射。"""
    bindings: dict[str, list[str]]


class SkillBindingsResponse(BaseModel):
    bindings: dict[str, list[str]]


class InstallSkillResponse(BaseModel):
    installed: list[str]
    message: str


# =====================================================================
# 辅助
# =====================================================================

def _skill_to_summary(skill: Any, disabled_ids: set[str]) -> SkillSummary:
    # SkillDefinition 只有 skill_id / skill_type 字段，没有 id / is_builtin 字段。
    # 同时兼容旧版可能直接挂 id / is_builtin 属性的对象。
    skill_id = getattr(skill, "skill_id", "") or getattr(skill, "id", "")
    skill_type = getattr(skill, "skill_type", "") or (
        "builtin" if getattr(skill, "is_builtin", False) else "user"
    )
    return SkillSummary(
        id=skill_id,
        name=getattr(skill, "name", ""),
        description=getattr(skill, "description", "") or "",
        is_builtin=(skill_type == "builtin"),
        is_disabled=(skill_id in disabled_ids),
    )


def _get_registry(agent: Any) -> Any:
    registry = getattr(agent, "registry", None)
    if registry is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SkillRegistry 未初始化",
        )
    return registry


# =====================================================================
# 路由
# =====================================================================

@router.get("", response_model=list[SkillSummary])
def list_skills(agent=Depends(require_skill_agent)) -> list[SkillSummary]:
    """列出全部技能（含 disabled 状态）。"""
    registry = _get_registry(agent)
    disabled_ids = prefs.load_disabled_skill_ids()
    skills = registry.list_skills()
    return [_skill_to_summary(s, disabled_ids) for s in skills]


@router.get("/user", response_model=list[SkillSummary])
def list_user_skills(agent=Depends(require_skill_agent)) -> list[SkillSummary]:
    """仅列出用户技能。"""
    registry = _get_registry(agent)
    disabled_ids = prefs.load_disabled_skill_ids()
    skills = registry.list_user_skills()
    return [_skill_to_summary(s, disabled_ids) for s in skills]


@router.get("/builtin", response_model=list[SkillSummary])
def list_builtin_skills(agent=Depends(require_skill_agent)) -> list[SkillSummary]:
    """仅列出内置技能。"""
    registry = _get_registry(agent)
    disabled_ids = prefs.load_disabled_skill_ids()
    skills = registry.list_builtin_skills()
    return [_skill_to_summary(s, disabled_ids) for s in skills]


@router.put("/{skill_id}/toggle", response_model=SkillSummary)
def toggle_skill(
    skill_id: str,
    body: ToggleSkillRequest,
    agent=Depends(require_skill_agent),
) -> SkillSummary:
    """启用/禁用技能。"""
    registry = _get_registry(agent)
    skill = registry.get(skill_id)
    if skill is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"技能不存在: {skill_id}")

    disabled_ids = prefs.load_disabled_skill_ids()
    if body.disabled:
        disabled_ids.add(skill_id)
    else:
        disabled_ids.discard(skill_id)
    prefs.save_disabled_skill_ids(disabled_ids)
    return _skill_to_summary(skill, disabled_ids)


@router.get("/bindings", response_model=SkillBindingsResponse)
def get_bindings() -> SkillBindingsResponse:
    """获取会话类型 → 默认技能绑定。"""
    return SkillBindingsResponse(bindings=prefs.load_skill_bindings())


@router.put("/bindings", response_model=SkillBindingsResponse)
def set_bindings(body: SkillBindingsRequest) -> SkillBindingsResponse:
    """设置会话类型 → 默认技能绑定。"""
    prefs.save_skill_bindings(body.bindings)
    return SkillBindingsResponse(bindings=body.bindings)


@router.delete("/{skill_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_skill(
    skill_id: str,
    agent=Depends(require_skill_agent),
) -> None:
    """删除用户技能（内置技能不可删）。"""
    registry = _get_registry(agent)
    skill = registry.get(skill_id)
    if skill is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"技能不存在: {skill_id}")
    if bool(getattr(skill, "is_builtin", False)):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="内置技能不可删除")
    ok = registry.delete_skill(skill_id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="删除失败")
    # 同步从 disabled 列表移除
    disabled_ids = prefs.load_disabled_skill_ids()
    disabled_ids.discard(skill_id)
    prefs.save_disabled_skill_ids(disabled_ids)


@router.post("/install", response_model=InstallSkillResponse)
async def install_skill(
    agent=Depends(require_skill_agent),
    file: UploadFile = File(...),
) -> InstallSkillResponse:
    """从 zip 安装技能。"""
    registry = _get_registry(agent)
    # 写入临时文件
    import tempfile
    import os
    suffix = os.path.splitext(file.filename or "skill.zip")[1] or ".zip"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name
    try:
        installed, msg = registry.install_skill_from_zip(tmp_path, overwrite=False)
        return InstallSkillResponse(installed=installed, message=msg)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"安装失败: {e}",
        )
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass
