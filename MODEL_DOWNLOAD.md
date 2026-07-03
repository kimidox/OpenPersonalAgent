# 实时流式转写模型下载和使用说明

本文档介绍 PersonalWindowGLM 项目中使用的实时流式语音转写（ASR）和文本转语音（TTS）模型的下载、配置和使用方法。

---

## 模型概述

PersonalWindowGLM 支持本地实时流式语音转写和文本转语音功能，使用 sherpa-onnx 框架提供的 ONNX 模型。所有模型均为离线运行，无需联网，确保隐私安全。

### 可用模型列表

| 模型类型 | 模型名称 | 大小 | 用途 |
|---------|---------|------|------|
| **实时流式 ASR** | sherpa-onnx-streaming-paraformer-bilingual-zh-en | ~100 MB | 中英双语实时语音转文字 |
| **TTS（中文）** | sherpa-onnx-vits-zh-ll | ~150 MB | 中文文字转语音，5个音色 |
| **TTS（中英文）** | vits-melo-tts-zh_en | ~200 MB | 中英文混合文字转语音 |

---

## 实时流式 ASR 模型

### 模型介绍

**sherpa-onnx-streaming-paraformer-bilingual-zh-en**

- **类型**: 流式 Paraformer 中英双语语音识别模型
- **量化**: INT8 量化版本，体积小、速度快
- **语言**: 中英双语支持
- **采样率**: 16kHz
- **用途**: 实时流式语音转写，边说边转文字
- **特点**: 支持端点检测，自动判断说话结束

### 模型文件

下载后包含以下必要文件：

```
sherpa-onnx-streaming-paraformer-bilingual-zh-en/
├── encoder.int8.onnx    # 编码器模型文件（必需）
├── decoder.int8.onnx    # 解码器模型文件（必需）
├── tokens.txt           # 词表文件（必需）
└── README.md            # 说明文档
```

### 使用场景

1. **实时语音转写**: 边说边转文字，实时显示识别结果
2. **浮动球快速录音**: 从浮动球发起录音，实时显示转写内容
3. **端点检测**: 自动判断说话结束，无需手动停止

---

## TTS 文本转语音模型

### 中文模型（sherpa-onnx-vits-zh-ll）

**特点**:
- 纯中文语音合成
- 5个可选音色
- 高质量中文发音
- 支持情感表达

**音色列表**:

| 音色 ID | 名称 | 性别 | 特点 |
|--------|------|------|------|
| 0 | 苏映雪 | 女 | 温柔甜美 |
| 1 | 顾念 | 女 | 清澈明亮 |
| 2 | 付思雨 | 女 | 活泼可爱 |
| 3 | 冰娇 | 女 | 冷静知性 |
| 4 | 巴总 | 男 | 稳重有力 |

### 中英文模型（vits-melo-tts-zh_en）

**特点**:
- 支持中英文混合朗读
- 自动识别语言切换
- 适合技术文档朗读
- 单一默认音色

### 模型文件

中文模型目录结构：

```
sherpa-onnx-vits-zh-ll/
├── model.onnx          # ONNX 模型文件（必需）
├── tokens.txt          # 词表文件（必需）
├── lexicon.txt         # 发音词典（必需）
├── dict/               # jieba 分词词典
│   ├── jieba.dict.utf8
│   ├── hmm_model.utf8
│   └── ...
├── date.fst            # 日期处理
├── number.fst          # 数字处理
├── phone.fst           # 电话号码处理
└── G_multisperaker_latest.json  # 多音色配置
```

中英文模型目录结构：

```
vits-melo-tts-zh_en/
├── model.onnx          # ONNX 模型（非量化）
├── model.int8.onnx     # INT8 量化模型
├── tokens.txt          # 词表文件
├── lexicon.txt         # 发音词典
├── dict/               # 分词词典
└── LICENSE             # 许可证
```

---

## 模型下载方法

### 方法一：程序内自动下载

程序首次使用语音功能时，会自动检测模型是否存在：

- 如果实时流式 ASR 模型不存在且 `ASR_AUTO_DOWNLOAD=true`，程序会自动下载
- 如果 TTS 模型不存在且 `TTS_AUTO_DOWNLOAD=true`，程序会自动下载
- 下载过程中会显示进度对话框
- 下载完成后自动加载模型

### 方法二：手动下载

如果自动下载失败（如网络问题），可以手动下载：

#### 实时流式 ASR 模型下载

1. 下载地址: https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-streaming-paraformer-bilingual-zh-en.tar.bz2
2. 解压到 `PersonalData/model/` 目录
3. 确保目录名为 `sherpa-onnx-streaming-paraformer-bilingual-zh-en`

#### 中文 TTS 模型下载

1. 下载地址: https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/sherpa-onnx-vits-zh-ll.tar.bz2
2. 解压到 `PersonalData/model/` 目录
3. 确保目录名为 `sherpa-onnx-vits-zh-ll`

#### 中英文 TTS 模型下载

1. 下载地址: https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/vits-melo-tts-zh_en.tar.bz2
2. 解压到 `PersonalData/model/` 目录
3. 确保目录名为 `vits-melo-tts-zh_en`

---

## 模型存储位置

### 开发模式

模型存储在项目目录下：

```
PersonalWindowGLM/
└── PersonalData/
    └── model/
        ├── sherpa-onnx-streaming-paraformer-bilingual-zh-en/  # 实时流式 ASR 模型
        ├── sherpa-onnx-vits-zh-ll/                     # 中文 TTS
        └── vits-melo-tts-zh_en/                        # 中英文 TTS
```

### 打包模式（exe）

模型存储在用户数据目录：

```
%APPDATA%/OpenPersonalAgent/
└── model/
    ├── sherpa-onnx-streaming-paraformer-bilingual-zh-en/
    ├── sherpa-onnx-vits-zh-ll/
    └── vits-melo-tts-zh_en/
```

---

## 模型配置

### 配置文件（.env）

在 `.env` 文件中添加以下配置：

```bash
# ===== 实时流式 ASR 语音转写模型配置 =====

# 实时流式模型目录路径（可选，不填则使用默认路径）
ASR_REALTIME_MODEL_PATH=

# 程序启动自动加载实时流式模型（true/false）
ASR_REALTIME_AUTO_LOAD=false

# 是否启用实时流式转写（true/false）
ASR_REALTIME_ENABLED=true

# 实时结果更新间隔（毫秒，默认 200）
ASR_REALTIME_UPDATE_INTERVAL=200

# 模型不存在时是否自动下载（true/false）
ASR_AUTO_DOWNLOAD=true

# ===== TTS 文本转语音模型配置 =====

# TTS 模型类型（zh=中文，zh_en=中英文）
TTS_MODEL_TYPE=zh

# TTS 模型目录路径（可选，不填则使用默认路径）
TTS_MODEL_PATH=

# TTS 说话人 ID（中文模型: 0-4，中英文模型: 0）
TTS_SPEAKER_ID=0

# TTS 语速（范围 0.5-2.0，默认 1.0）
TTS_SPEED=1.0

# 程序启动自动加载 TTS 模型（true/false）
TTS_AUTO_LOAD=false

# 模型不存在时是否自动下载（true/false）
TTS_AUTO_DOWNLOAD=true
```

### 配置说明

| 配置项 | 说明 | 默认值 |
|-------|------|--------|
| `ASR_REALTIME_MODEL_PATH` | 实时流式模型路径，留空使用默认 | 空 |
| `ASR_REALTIME_AUTO_LOAD` | 启动时自动加载实时流式模型 | false |
| `ASR_REALTIME_ENABLED` | 是否启用实时流式转写 | true |
| `ASR_REALTIME_UPDATE_INTERVAL` | 实时结果更新间隔（毫秒） | 200 |
| `ASR_AUTO_DOWNLOAD` | 模型不存在时自动下载 | true |
| `TTS_MODEL_TYPE` | TTS 模型类型 | zh |
| `TTS_MODEL_PATH` | TTS 模型路径，留空使用默认 | 空 |
| `TTS_SPEAKER_ID` | TTS 音色 ID | 0 |
| `TTS_SPEED` | TTS 语速 | 1.0 |
| `TTS_AUTO_LOAD` | 启动时自动加载 TTS 模型 | false |
| `TTS_AUTO_DOWNLOAD` | 模型不存在时自动下载 | true |

---

## 使用指南

### 实时流式语音转写（ASR）

1. **启用实时转写**: 在设置中启用实时流式转写功能
2. **开始录音**: 点击录音按钮或使用浮动球录音功能
3. **实时显示**: 边说边显示识别结果，无需等待录音结束
4. **端点检测**: 系统自动判断说话结束，停止录音
5. **发送消息**: 转写的内容自动填入输入框，可发送或编辑

### 文本转语音（TTS）

1. **设置界面**: 在设置中启用 TTS 功能
2. **选择音色**: 选择喜欢的音色（中文模型有5个选项）
3. **调整语速**: 设置合适的语速（0.5-2.0）
4. **朗读消息**: AI 回复后，点击朗读按钮播放语音

### 音色选择建议

- **苏映雪（ID=0）**: 适合日常对话、故事朗读
- **顾念（ID=1）**: 适合新闻播报、信息通知
- **付思雨（ID=2）**: 适合轻松聊天、娱乐内容
- **冰娇（ID=3）**: 适合专业讲解、技术文档
- **巴总（ID=4）**: 适合商务场景、正式通知

---

## 常见问题解答

### Q1: 模型下载失败怎么办？

**原因**: 网络问题或 GitHub 访问受限

**解决方案**:
1. 使用镜像站点或代理下载
2. 手动下载模型文件并解压到正确目录
3. 多次尝试自动下载

### Q2: 模型加载失败怎么办？

**原因**: 模型文件不完整或路径错误

**解决方案**:
1. 检查模型目录是否包含 `encoder.int8.onnx`、`decoder.int8.onnx` 和 `tokens.txt`
2. 删除不完整的模型目录，重新下载
3. 检查 `.env` 配置中的路径是否正确

### Q3: 实时转写效果不好怎么办？

**原因**: 录音质量、环境噪音、说话方式

**解决方案**:
1. 使用高质量麦克风
2. 在安静环境录音
3. 说话清晰、语速适中
4. 距离麦克风适当距离

### Q4: TTS 语音不自然怎么办？

**原因**: 音色选择、语速设置

**解决方案**:
1. 尝试不同音色，找到最适合的
2. 调整语速（推荐 0.9-1.1）
3. 中文内容使用中文模型，中英文混合使用 zh_en 模型

### Q5: 如何切换 TTS 模型？

**步骤**:
1. 在 `.env` 中修改 `TTS_MODEL_TYPE`（zh 或 zh_en）
2. 如果新模型未下载，手动下载或等待自动下载
3. 重启程序使配置生效

### Q6: 模型占用多少内存？

**内存占用**:
- 实时流式 ASR 模型加载后: ~150 MB
- TTS 模型加载后: ~200 MB
- 同时加载: ~350 MB

**建议**: 如果内存有限，可以设置 `ASR_REALTIME_AUTO_LOAD=false` 和 `TTS_AUTO_LOAD=false`，按需加载。

### Q7: 打包后的程序如何管理模型？

**说明**:
- 打包后的 exe 不包含模型文件
- 模型存储在 `%APPDATA%/OpenPersonalAgent/model/`
- 首次运行时自动下载（如果启用）
- 可以手动复制模型目录到该位置

### Q8: 如何卸载模型？

**步骤**:
1. 删除 `PersonalData/model/` 下的模型目录
2. 或删除 `%APPDATA%/OpenPersonalAgent/model/` 下的模型目录
3. 清空 `.env` 中的模型路径配置

---

## 技术细节

### 依赖库

语音功能依赖以下 Python 库：

```bash
pip install sherpa-onnx    # ONNX 模型推理
pip install sounddevice    # 音频录制和播放
pip install numpy          # 音频数据处理
pip install scipy          # 音频重采样（可选）
```

### 模型推理框架

使用 **sherpa-onnx** 作为 ONNX 模型推理框架：

- **实时流式 ASR**: `sherpa_onnx.OnlineRecognizer.from_paraformer()`
- **TTS**: `sherpa_onnx.OfflineTts()`

### 音频格式

- **录音格式**: WAV，16kHz，单声道，int16
- **TTS 输出格式**: WAV，由 sherpa-onnx 自动生成

---

## 更新日志

### v3.1.0
- 更改为实时流式语音转写模型（sherpa-onnx-streaming-paraformer-bilingual-zh-en）
- 支持中英双语实时转写
- 支持端点检测，自动判断说话结束
- 移除离线模型，统一使用流式模型

### v3.0.0
- 新增 ASR 语音识别功能
- 新增 TTS 文本转语音功能（sherpa-onnx-vits-zh-ll 和 vits-melo-tts-zh_en）
- 新增模型自动下载机制
- 模型外置，打包体积大幅减小

---

## 相关链接

- [sherpa-onnx 官方文档](https://k2-fsa.github.io/sherpa/onnx/)
- [sherpa-onnx GitHub](https://github.com/k2-fsa/sherpa-onnx)
- [Paraformer 流式模型介绍](https://www.modelscope.cn/models/damo/speech_paraformer_asr_nat-zh-cn-16k-common-vocab8404-online/summary)
- [VITS TTS 模型](https://github.com/jaywalnut310/vits)