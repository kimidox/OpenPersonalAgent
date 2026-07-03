# 打包优化指南

本文档详细介绍 PersonalWindowGLM 项目的打包流程、优化技巧和常见问题解答。

---

## 目录

1. [打包概述](#打包概述)
2. [打包方式对比](#打包方式对比)
3. [打包流程详解](#打包流程详解)
4. [模型外置机制](#模型外置机制)
5. [UPX压缩配置](#upx压缩配置)
6. [依赖优化](#依赖优化)
7. [打包体积分析](#打包体积分析)
8. [常见问题解答](#常见问题解答)

---

## 打包概述

PersonalWindowGLM 使用 PyInstaller 进行打包，支持两种打包模式：

- **目录模式 (onedir)**: 生成包含exe和依赖文件的目录
- **单文件模式 (onefile)**: 生成单个exe文件

### 打包工具

- **build.bat**: Windows打包脚本，提供交互式打包选项
- **PersonalWindowGLM.spec**: 目录模式打包配置
- **PersonalWindowGLM_onefile.spec**: 单文件模式打包配置

### 打包特点

| 特性 | 说明 |
|------|------|
| 模型外置 | ASR/TTS模型不打包，运行时下载 |
| UPX压缩 | 支持UPX压缩减小体积 |
| 依赖优化 | 排除不必要的Python模块 |
| 用户数据隔离 | 打包exe使用独立用户数据目录 |

---

## 打包方式对比

### 目录模式 (onedir)

**优点**:
- 启动速度快（无需解压）
- 支持UPX压缩
- 更新方便（可替换单个文件）
- 调试容易（可查看依赖文件）

**缺点**:
- 分发需要整个目录
- 文件数量多

**适用场景**:
- 本地部署
- 日常使用
- 需要快速启动

### 单文件模式 (onefile)

**优点**:
- 单exe文件，便于分发
- 无需额外依赖文件

**缺点**:
- 启动较慢（需解压到临时目录）
- 不支持UPX压缩（启动会更慢）
- 每次启动都有解压开销

**适用场景**:
- 远程分发
- 便携使用
- 不在乎启动速度

### 推荐选择

| 场景 | 推荐方式 |
|------|----------|
| 本地使用 | 目录模式 + UPX |
| 分发给他人 | 单文件模式 |
| 开发测试 | 目录模式 |
| 生产部署 | 目录模式 + UPX |

---

## 打包流程详解

### 步骤1: 环境准备

#### 安装PyInstaller

```bash
pip install pyinstaller
```

#### 安装UPX（可选）

UPX可以压缩exe和dll文件，减小打包体积约30-50%。

**下载地址**: https://github.com/upx/upx/releases

**安装方法**:

1. 下载最新版本（如 `upx-4.2.2-win64.zip`）
2. 解压到任意目录，例如 `C:\upx`
3. 将UPX目录添加到系统PATH环境变量

**添加PATH环境变量**:
- 右键"此电脑" → 属性 → 高级系统设置 → 环境变量
- 在"系统变量"中找到"Path"，点击编辑
- 添加UPX目录路径（如 `C:\upx`）

**验证安装**:
```bash
upx --version
```

### 步骤2: 清理临时文件

打包前建议清理临时文件，避免打包不必要的文件：

```bash
# 清理Python缓存
python -c "import pathlib; [p.unlink() for p in pathlib.Path('.').rglob('*.py[co]')]"
python -c "import pathlib; [p.rmdir() for p in pathlib.Path('.').rglob('__pycache__')]"

# 或使用build.bat自动清理
build.bat
```

### 步骤3: 运行打包脚本

#### 使用build.bat（推荐）

```bash
build.bat
```

交互式选择：
- 选项1: 目录模式（启用UPX）- 推荐
- 选项2: 单文件模式
- 选项3: 目录模式（禁用UPX）

#### 手动执行PyInstaller

```bash
# 目录模式
pyinstaller PersonalWindowGLM.spec --clean

# 单文件模式
pyinstaller PersonalWindowGLM_onefile.spec --clean
```

### 步骤4: 检查打包结果

#### 目录模式

```
dist/
└── OpenPersonalAgent/
    ├── OpenPersonalAgent.exe    # 主程序
    ├── _internal/               # 内部依赖
    │   ├── Python311.dll
    │   ├── PySide6/
    │   └── ...
    ├── PersonalData/
    │   ├── data/
    │   └── Skills/
    ├── Skills/
    ├── ui/
    └── .env
```

#### 单文件模式

```
dist/
└── OpenPersonalAgent.exe    # 单exe文件
```

### 步骤5: 测试打包结果

```bash
# 目录模式
cd dist/OpenPersonalAgent
OpenPersonalAgent.exe

# 单文件模式
dist/OpenPersonalAgent.exe
```

---

## 模型外置机制

### 为什么模型外置？

| 原因 | 说明 |
|------|------|
| 体积过大 | ASR+TTS模型约430MB |
| 按需下载 | 用户可能不需要语音功能 |
| 版本更新 | 模型可独立更新，无需重新打包 |
| 分发便捷 | 减小分发体积 |

### 模型列表

| 模型 | 类型 | 大小 | 用途 |
|------|------|------|------|
| sherpa-onnx-paraformer-zh-int8 | ASR | ~80 MB | 中文语音识别 |
| sherpa-onnx-vits-zh-ll | TTS | ~150 MB | 中文语音合成 |
| vits-melo-tts-zh_en | TTS | ~200 MB | 中英文语音合成 |

### 模型存储位置

#### 开发模式

```
PersonalWindowGLM/
└── PersonalData/
    └── model/
        ├── sherpa-onnx-paraformer-zh-int8-2025-10-07/
        ├── sherpa-onnx-vits-zh-ll/
        └── vits-melo-tts-zh_en/
```

#### 打包模式

```
%APPDATA%/OpenPersonalAgent/
└── model/
    ├── sherpa-onnx-paraformer-zh-int8-2025-10-07/
    ├── sherpa-onnx-vits-zh-ll/
    └── vits-melo-tts-zh_en/
```

### 模型下载方式

#### 方式1: 程序自动下载

首次使用语音功能时，程序自动检测并下载模型：
- `ASR_AUTO_DOWNLOAD=true`（默认启用）
- `TTS_AUTO_DOWNLOAD=true`（默认启用）

#### 方式2: 使用下载脚本

```bash
# 下载所有模型
python download_models.py --all

# 仅下载ASR模型
python download_models.py --asr

# 仅下载TTS模型
python download_models.py --tts zh
```

#### 方式3: 手动下载

从GitHub下载并解压到模型目录：
- ASR: https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-paraformer-zh-int8-2025-10-07.tar.bz2
- TTS (zh): https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/sherpa-onnx-vits-zh-ll.tar.bz2
- TTS (zh_en): https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/vits-melo-tts-zh_en.tar.bz2

### 打包后模型部署

如果需要预先部署模型：

1. 下载模型到开发目录
2. 打包程序
3. 将模型目录复制到用户数据目录：

```bash
# 复制模型到打包后的用户数据目录
xcopy /E /I PersonalData\model "%APPDATA%\OpenPersonalAgent\model"
```

---

## UPX压缩配置

### UPX简介

UPX (Ultimate Packer for eXecutables) 是一个开源的可执行文件压缩工具，可以压缩exe、dll等文件。

### 压缩效果

| 文件类型 | 原始大小 | 压缩后大小 | 压缩率 |
|----------|----------|------------|--------|
| exe文件 | 10 MB | 3-4 MB | 60-70% |
| dll文件 | 5 MB | 2-3 MB | 40-60% |
| 总体效果 | 150 MB | 100-120 MB | 30-50% |

### spec文件配置

#### PersonalWindowGLM.spec（目录模式）

```python
# UPX压缩配置
upx_enable = True  # 启用UPX压缩
upx_dir = None     # UPX目录路径，None表示使用PATH中的UPX

# EXE配置
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='OpenPersonalAgent',
    upx=upx_enable,  # 启用UPX
    ...
)

# COLLECT配置
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    upx=upx_enable,  # 启用UPX
    upx_exclude=[
        # 排除已压缩的文件
        '*.png',
        '*.jpg',
        '*.onnx',
        '*.gz',
        '*.zip',
    ],
    ...
)
```

#### PersonalWindowGLM_onefile.spec（单文件模式）

```python
# 单文件模式默认禁用UPX
upx_enable = False  # 禁用UPX（避免启动过慢）
```

### UPX排除配置

以下文件类型不建议UPX压缩：

| 文件类型 | 原因 |
|----------|------|
| *.png, *.jpg | 已压缩的图片 |
| *.onnx | 已压缩的模型文件 |
| *.gz, *.zip | 已压缩的压缩包 |
| *.mp3, *.mp4 | 已压缩的音视频 |

### UPX安装问题

#### 问题1: UPX未安装

**错误信息**: `UPX is not available`

**解决方案**:
1. 下载并安装UPX
2. 或在spec文件中设置 `upx_enable = False`

#### 问题2: UPX不在PATH中

**解决方案**:
- 在spec文件中指定UPX路径：
```python
upx_dir = r'C:\upx'  # 指定UPX目录
```

#### 问题3: UPX压缩失败

**解决方案**:
- 检查UPX版本是否兼容
- 尝试禁用UPX压缩
- 检查文件是否被其他程序占用

---

## 依赖优化

### 排除不必要的模块

spec文件中已配置排除以下模块：

#### Python标准库

```python
excludes=[
    'tkinter',        # Tkinter GUI（不使用）
    'unittest',       # 单元测试
    'pytest',         # 测试框架
    'sphinx',         # 文档生成
    'IPython',        # IPython交互
    'jupyter',        # Jupyter notebook
    'setuptools',     # 包管理
    'pip',            # 包安装
    'wheel',          # 包构建
    'email',          # 邮件处理
    'html',           # HTML解析
    'xml',            # XML解析
    ...
]
```

#### 大型第三方库

```python
excludes=[
    'matplotlib',     # 绑图库（不使用）
    'scipy',          # 科学计算（不使用）
    'sympy',          # 符号计算（不使用）
    'nose',           # 测试框架
    'coverage',       # 代码覆盖
    'pylint',         # 代码检查
    'flake8',         # 代码检查
    ...
]
```

### 优化效果

| 优化措施 | 减少体积 |
|----------|----------|
| 排除tkinter | ~10 MB |
| 排除matplotlib | ~30 MB |
| 排除scipy | ~20 MB |
| 排除测试框架 | ~5 MB |
| 总计 | ~50-70 MB |

### 添加必要模块

确保以下模块被正确包含：

```python
hiddenimports=[
    'PySide6.QtWidgets',
    'PySide6.QtCore',
    'PySide6.QtGui',
    'sqlalchemy.dialects.sqlite',
    'openai',
    'jieba',
    'sounddevice',
    'numpy',
    ...
]
```

### 数据文件打包

只打包必要的数据文件：

```python
datas=[
    ('ui/styles/ui_skill_agent_styles.css', 'ui/styles'),
    ('application.ico', '.'),
    ('PersonalData/data', 'PersonalData/data'),
    ('PersonalData/Skills', 'PersonalData/Skills'),
    ('.env', '.'),
    ('Skills', 'Skills'),
]
```

**排除的数据目录**:
- `PersonalData/model/` - 模型文件（外置）
- `PersonalData/logs/` - 运行时日志
- `PersonalData/records/` - 用户录音
- `PersonalData/tts/` - TTS输出音频

---

## 打包体积分析

### 体积组成

| 组成部分 | 目录模式 | 单文件模式 |
|----------|----------|------------|
| 主exe | ~10 MB | ~150 MB |
| PySide6 | ~50 MB | 包含在exe中 |
| Python运行时 | ~20 MB | 包含在exe中 |
| 其他依赖 | ~30 MB | 包含在exe中 |
| 数据文件 | ~10 MB | 包含在exe中 |
| **总计** | ~120-150 MB | ~150-180 MB |

### UPX压缩效果

| 模式 | 无UPX | 有UPX | 压缩率 |
|------|-------|-------|--------|
| 目录模式 | 150 MB | 100 MB | ~33% |
| 单文件模式 | 150 MB | 不推荐 | - |

### 体积对比（含模型）

| 情况 | 体积 |
|------|------|
| 打包结果（无模型） | ~100-150 MB |
| 打包结果 + ASR模型 | +80 MB |
| 打包结果 + 中文TTS | +150 MB |
| 打包结果 + 所有模型 | +430 MB |

**结论**: 模型外置可减少约430MB打包体积。

---

## 常见问题解答

### Q1: 打包后程序无法启动？

**可能原因**:
1. 缺少必要的依赖模块
2. 数据文件未正确打包
3. 配置文件路径问题

**解决方案**:
1. 检查spec文件中的`hiddenimports`
2. 检查spec文件中的`datas`
3. 使用控制台模式调试：
```python
# 在spec文件中设置
console=True
```

### Q2: 打包体积过大？

**解决方案**:
1. 启用UPX压缩
2. 检查是否包含不必要的模块
3. 确保模型文件已外置
4. 清理临时文件后重新打包

### Q3: UPX压缩失败？

**可能原因**:
1. UPX未安装或不在PATH中
2. UPX版本不兼容
3. 文件被其他程序占用

**解决方案**:
1. 安装UPX并添加到PATH
2. 更新UPX到最新版本
3. 关闭占用文件的程序
4. 禁用UPX压缩

### Q4: 单文件模式启动慢？

**原因**: 单文件模式需要解压到临时目录

**解决方案**:
1. 使用目录模式
2. 单文件模式不建议启用UPX（会更慢）

### Q5: 打包后找不到配置文件？

**原因**: 打包exe使用独立的用户数据目录

**解决方案**:
配置文件位于 `%APPDATA%/OpenPersonalAgent/.env`

### Q6: 如何更新打包后的程序？

**目录模式**:
- 直接替换exe文件或整个目录

**单文件模式**:
- 替换整个exe文件

### Q7: 打包后模型下载失败？

**可能原因**:
1. 网络问题
2. GitHub访问受限

**解决方案**:
1. 手动下载模型文件
2. 使用代理或镜像站点
3. 运行 `python download_models.py --check` 检查状态

### Q8: 如何减小打包体积？

**优化措施**:
1. 启用UPX压缩（减少30-50%）
2. 模型外置（减少430MB）
3. 排除不必要的模块（减少50MB）
4. 清理临时文件

### Q9: 打包时出现警告？

**常见警告**:
- `WARNING: lib not found` - 可以忽略
- `WARNING: hidden import not found` - 检查是否必要

**处理建议**:
- 运行程序测试功能是否正常
- 如果功能正常，可以忽略警告

### Q10: 如何调试打包问题？

**调试步骤**:
1. 使用控制台模式查看错误信息
2. 检查日志文件 `%APPDATA%/OpenPersonalAgent/logs/`
3. 使用PyInstaller的`--debug`选项

```bash
pyinstaller PersonalWindowGLM.spec --clean --debug
```

---

## 附录

### A. spec文件完整配置

详见项目文件：
- `PersonalWindowGLM.spec` - 目录模式配置
- `PersonalWindowGLM_onefile.spec` - 单文件模式配置

### B. 相关文档

- [MODEL_DOWNLOAD.md](./MODEL_DOWNLOAD.md) - 模型下载说明
- [readme_CN.md](./readme_CN.md) - 项目中文说明

### C. 打包命令参考

```bash
# 基本打包
pyinstaller PersonalWindowGLM.spec

# 清理后打包
pyinstaller PersonalWindowGLM.spec --clean

# 调试模式打包
pyinstaller PersonalWindowGLM.spec --debug

# 控制台模式打包（用于调试）
# 需修改spec文件：console=True

# 查看打包分析
pyinstaller PersonalWindowGLM.spec --log-level DEBUG
```

---

## 更新日志

### v3.0.0
- 模型外置机制，大幅减小打包体积
- 新增UPX压缩支持
- 优化依赖排除配置
- 新增build.bat交互式打包脚本
- 新增PACKAGING_GUIDE.md打包指南

---

**如有其他问题，请提交Issue或查看项目文档。**