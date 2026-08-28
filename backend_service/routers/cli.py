"""CLI 包路由：list。

已安装 CLI 包的信息由 cli_manager 扫描 PersonalData/CLI/ 获得。
"""
from __future__ import annotations

from fastapi import APIRouter

import cli_manager

router = APIRouter(prefix="/api/cli", tags=["cli"])


@router.get("")
def list_cli_packages() -> list[dict]:
    """列出所有已安装的 CLI 包（含用法说明），供前端「/」引用菜单使用。"""
    return cli_manager.list_cli_packages()
