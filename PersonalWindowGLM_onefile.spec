# -*- mode: python ; coding: utf-8 -*-
import os
import glob
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# UPX压缩配置 - 需要安装UPX并添加到PATH环境变量
# UPX下载地址: https://github.com/upx/upx/releases
# 如果未安装UPX，将upx_enable设置为False
upx_enable = False
upx_dir = None  # 如果UPX不在PATH中，可以指定UPX目录路径，例如: r'C:\upx'

# ===== 收集 onnxruntime 的 CUDA provider DLL =====
# onnxruntime-gpu 的 CUDA provider DLL（如 onnxruntime_providers_cuda.dll）
# 位于 onnxruntime/capi/ 目录下，PyInstaller 默认不会收集这些 DLL
onnxruntime_binaries = []
try:
    import onnxruntime
    onnxruntime_dir = os.path.dirname(onnxruntime.__file__)
    capi_dir = os.path.join(onnxruntime_dir, 'capi')
    if os.path.exists(capi_dir):
        # 收集 capi 目录下的所有 DLL
        dll_files = glob.glob(os.path.join(capi_dir, '*.dll'))
        for dll_path in dll_files:
            dll_name = os.path.basename(dll_path)
            onnxruntime_binaries.append((dll_path, 'onnxruntime/capi'))
            print(f"[Packaging] 收集 onnxruntime DLL: {dll_name}")
except ImportError:
    print("[Packaging] 警告: onnxruntime 未安装，跳过 DLL 收集")
except Exception as e:
    print(f"[Packaging] 警告: 收集 onnxruntime DLL 失败: {e}")

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=onnxruntime_binaries,
    datas=[
        ('ui/styles/ui_skill_agent_styles.css', 'ui/styles'),
        ('application.ico', '.'),
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
        'recorder',
        'prompt_template_config',
        'tts',
        'ui',
        'ui_skill_agent',
        'scheduled_tasks',
        'scheduler',
        'notification',
        'autostart',
        'automation',
        'prompt',
        'document_parser',
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
        'PySide6.QtWidgets',
        'PySide6.QtCore',
        'PySide6.QtGui',
        'sqlalchemy.dialects.sqlite',
        'sqlalchemy.orm',
        'openai',
        'dotenv',
        'pyautogui',
        'PIL',
        'openpyxl',
        'xlrd',
        'jieba',
        'python-docx',
        'pdfplumber',
        'sounddevice',
        'numpy',
        'faster-whisper',
        'onnxruntime',
        'comtypes',
        'uiautomation',
        'scipy'
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
        'black'
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
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='OpenPersonalAgent',
    debug=False,
    bootloader_ignore_signals=False,
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
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='application.ico',
)
