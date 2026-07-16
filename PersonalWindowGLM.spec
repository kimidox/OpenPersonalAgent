# -*- mode: python ; coding: utf-8 -*-
import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# UPX压缩配置 - 需要安装UPX并添加到PATH环境变量
# UPX下载地址: https://github.com/upx/upx/releases
# 如果未安装UPX，将upx_enable设置为False
upx_enable = True
upx_dir = None  # 如果UPX不在PATH中，可以指定UPX目录路径，例如: r'C:\upx'

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        # PySide6 相关样式已移除
        # ('ui/styles/ui_skill_agent_styles.css', 'ui/styles'),
        ('application.ico', '.'),
        # 只打包必要的PersonalData子目录，排除模型目录和临时文件
        ('PersonalData/data', 'PersonalData/data'),
        ('PersonalData/Skills', 'PersonalData/Skills'),
        # 排除以下目录:
        # - PersonalData/model (模型文件，体积过大，运行时下载)
        # - PersonalData/logs (运行时日志)
        # - PersonalData/records (用户录音文件)
        # - PersonalData/tts (TTS输出音频)
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
        # 排除不必要的Python标准库模块
        'tkinter',
        'tkinter.filedialog',
        'tkinter.messagebox',
        'unittest',
        'unittest.mock',
        'test',
        'tests',
        'pytest',
        'sphinx',
        'IPython',
        'jupyter',
        'jupyter_client',
        'jupyter_core',
        'notebook',
        # setuptools 不能排除，因为 pkg_resources 依赖 xml（通过 plistlib）
        # 'setuptools',
        'pip',
        'wheel',
        'distutils',
        # email 不能排除，httpx._models.py 使用了 email
        # 'email',
        # html 不能排除，项目代码直接使用 html.escape
        # 'html',
        # xml 不能排除，plistlib 和 openpyxl 依赖 xml
        # 'xml',
        'xmlrpc',
        # multiprocessing, concurrent, asyncio 不能排除，SQLAlchemy 等库依赖这些模块
        # 'multiprocessing',
        # 'concurrent',
        # 'asyncio',
        'pydoc',
        'doctest',
        # argparse 不能排除，main.py 和 download_models.py 直接使用
        # 'argparse',
        'optparse',
        'getopt',
        # 排除不必要的大型第三方库
        'matplotlib',
        'matplotlib.backends',
        'mpl_toolkits',
        # scipy 不能排除，recorder.py 使用 scipy.signal 进行音频重采样
        # 'scipy',
        'sympy',
        'nose',
        'coverage',
        'pylint',
        'flake8',
        'autopep8',
        'yapf',
        'black',
        # 排除 PySide6 相关库（已迁移到 Flet）
        'PySide6',
        'PySide6.QtWidgets',
        'PySide6.QtCore',
        'PySide6.QtGui',
        'shiboken6',
        'PyQt6',
        'PyQt5',
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
    name='OpenPersonalAgent',
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
        # 排除不需要压缩的文件（如已压缩的文件）
        '*.png',
        '*.jpg',
        '*.jpeg',
        '*.gif',
        '*.zip',
        '*.gz',
        '*.rar',
        '*.7z',
        '*.mp3',
        '*.mp4',
        '*.avi',
        '*.mov',
        '*.onnx',  # ONNX模型文件已压缩
        '*.int8.onnx',  # int8量化模型
    ],
    name='OpenPersonalAgent',
)
