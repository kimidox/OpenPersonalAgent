# -*- mode: python ; coding: utf-8 -*-
"""
PersonalWindowGLM 核心版打包配置

此配置排除所有重型依赖，只打包核心功能：
- 基础对话功能（LLM API + Flet UI）
- 记忆管理（SQLite）
- 配置管理
- 技能系统（核心部分）

排除的功能：
- 语音功能（ASR/TTS）- 需要用户自行安装onnxruntime
- 悬浮球（PySide6）- 需要用户自行安装PySide6
- 自动化操作（opencv）- 需要用户自行安装opencv-python
- 音频处理（scipy）- 需要用户自行安装scipy

体积对比：
- 完整版：~150MB
- 核心版：~80MB
"""

import os
import glob
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# UPX压缩配置
upx_enable = True
upx_dir = None

# 不收集onnxruntime CUDA DLL（核心版不需要）
onnxruntime_binaries = []

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=onnxruntime_binaries,
    datas=[
        ('application.ico', '.'),
        # 只打包核心数据，排除Skills和PersonalData/Skills
        ('PersonalData/data', 'PersonalData/data'),
        ('.env', '.'),
        ('Skills', 'Skills'),
    ],
    hiddenimports=[
        'resource_path',
        'logger',
        'config',
        'agent',
        'executor',
        'skill_agent',
        'skill_agent_preferences',
        'ui',
        'ui_skill_agent',
        'base_tool',
        'base_tool.context',
        'base_tool.definitions',
        'base_tool.dispatch',
        'base_tool.schema',
        'database',
        'database.models',
        'database.utils',
        'llm',
        'llm.BaseChatModel',
        'llm.glm_chat_model',
        'llm.qwen_chat_model',
        'llm.gemma_chat_model',
        'llm.llm_config_manager',
        'llm.tools',
        'memory',
        'memory.conversation',
        'memory.memory',
        'memory.message',
        'memory.sqlite_memory',
        'skill',
        'skill.execution',
        'skill.loader',
        'skill.processing',
        'skill.registry',
        'skill.types',
        # Flet 相关模块
        'flet',
        'flet_core',
        'flet_core.app',
        'flet_core.page',
        'flet_core.controls',
        'utils.lazy_loader',
        'sqlalchemy.dialects.sqlite',
        'sqlalchemy.orm',
        'openai',
        'dotenv',
        'pyautogui',
        'PIL',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Python标准库
        'tkinter', 'tkinter.filedialog', 'tkinter.messagebox',
        'unittest', 'unittest.mock', 'test', 'tests', 'pytest', 'sphinx',
        'IPython', 'jupyter', 'jupyter_client', 'jupyter_core', 'notebook',
        'pip', 'wheel', 'distutils', 'xmlrpc',
        'pydoc', 'doctest', 'optparse', 'getopt',
        # 大型第三方库（通用）
        'matplotlib', 'matplotlib.backends', 'mpl_toolkits',
        'sympy', 'nose', 'coverage', 'pylint', 'flake8', 'autopep8', 'yapf', 'black',
        # 核心版排除的重型依赖
        'PySide6', 'PySide6.QtWidgets', 'PySide6.QtCore', 'PySide6.QtGui',
        'shiboken6', 'PyQt6', 'PyQt5',
        'scipy', 'scipy.signal', 'scipy.sparse', 'scipy.ndimage',
        'cv2', 'opencv-python', 'opencv-python-headless',
        'pandas',
        'onnxruntime', 'onnxruntime-gpu',
        'sherpa', 'sherpa-onnx',
        'live2d', 'live2d-py',
        'OpenGL', 'PyOpenGL',
        'comtypes', 'uiautomation',
    ],
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
    name='OpenPersonalAgent-Core',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=upx_enable,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
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
    upx=upx_enable,
    upx_exclude=[
        '*.png', '*.jpg', '*.jpeg', '*.gif',
        '*.zip', '*.gz', '*.rar', '*.7z',
        '*.mp3', '*.mp4', '*.avi', '*.mov',
        '*.onnx', '*.int8.onnx',
    ],
    name='OpenPersonalAgent-Core',
)