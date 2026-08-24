# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec：生成 backend_service.exe（Tauri sidecar）。

阶段 6 打包流程（见 frontend-tauri-refactor.md 3.6 节）：
1. PyInstaller 生成 backend_service.exe（本 spec）
2. 复制到 frontend/src-tauri/binaries/backend_service-x86_64-pc-windows-msvc.exe
3. cd frontend && npm run tauri build

产物名约定（Tauri externalBin 要求平台后缀）：
- Windows: backend_service-x86_64-pc-windows-msvc.exe
- macOS:   backend_service-x86_64-apple-darwin
- Linux:   backend_service-x86_64-unknown-linux-gnu

构建命令：
    pyinstaller backend_service.spec --noconfirm --distpath dist-sidecar

注意：
- 悬浮球子进程（PySide6 + live2d-py）代码与后端打包在一起，
  FloatingBallManager 用 multiprocessing.Process spawn 子进程时
  会重新 import 本 exe，需 hiddenimports 覆盖。
"""

import sys
from pathlib import Path

block_cipher = None

# 项目根
PROJECT_ROOT = Path(SPECPATH).parent if SPECPATH.endswith('frontend') or SPECPATH.endswith('backend_service') else Path(SPECPATH)

a = Analysis(
    ['main.py'],
    pathex=[str(PROJECT_ROOT)],
    binaries=[],
    datas=[
        # 数据资源（技能/图标）
        # 注意: PersonalData 不打包——用户数据统一在 %APPDATA%/OpenPersonalAgent/PersonalData，
        # 运行时按需创建，避免把开发机的 venv/模型/日志/数据库塞进安装包
        ('Skills', 'Skills'),
        ('application.ico', '.'),
    ],
    hiddenimports=[
        # 后端服务层
        'backend_service.app',
        'backend_service.lifecycle',
        'backend_service.floating_ball',
        'backend_service.runner',
        'backend_service.deps',
        'backend_service.schemas',
        'backend_service.ws.manager',
        'backend_service.ws.stream_bridge',
        'backend_service.ws.events',
        'backend_service.routers.conversations',
        'backend_service.routers.messages',
        'backend_service.routers.agent',
        'backend_service.routers.skills',
        'backend_service.routers.recording',
        'backend_service.routers.files',
        'backend_service.routers.settings',
        'backend_service.routers.floating_ball',
        'backend_service.routers.ws',
        # 悬浮球子进程（multiprocessing spawn 重新 import）
        'floating_ball.floating_ball_ipc',
        'floating_ball.floating_ball_process',
        'floating_ball.ipc_optimizer',
        'floating_ball.live2d_model_manager',
        # 后端核心
        'skill_agent',
        'skill_agent._agent',
        'executor',
        'recorder',
        'tts',
        'asr',
        'memory',
        'database',
        'config',
        'logger',
        'performance',
        'scheduler',
        'agent_events',
        # FastAPI / uvicorn
        'uvicorn',
        'uvicorn.logging',
        'uvicorn.loops',
        'uvicorn.loops.auto',
        'uvicorn.protocols',
        'uvicorn.protocols.http',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.websockets',
        'uvicorn.protocols.websockets.auto',
        'uvicorn.lifespan',
        'uvicorn.lifespan.on',
        'fastapi',
        'fastapi.middleware.cors',
        'pydantic',
        # 数据处理
        'pandas',
        'openpyxl',
        # 文档解析
        'docx',
        'pdfplumber',
        # 音频
        'sounddevice',
        'scipy',
        # 自动化
        'pyautogui',
        'uiautomation',
        'comtypes',
        'cv2',
        # Live2D（悬浮球子进程）
        'live2d',
        'OpenGL',
        # IPC
        'msgpack',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='backend_service',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,  # sidecar 需 stdout 输出 BACKEND_READY marker，必须保留 console
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='application.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='backend_service',
)
