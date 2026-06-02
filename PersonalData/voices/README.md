# TTS 音色权重目录

本目录用于存放 Sherpa-ONNX TTS 预训练模型文件。

## 推荐中文模型

### 1. vits-zh-hf-fanchen (推荐)
- 特点：中文发音自然，支持多音色
- 来源：Hugging Face

### 2. melo-tts-zh
- 特点：基于 MyShell.ai 的 MeloTTS，中文效果优秀
- 来源：Sherpa 官方

### 3. vits-piper-zh_CN-huayan
- 特点：Piper 中文模型，轻量级
- 来源：Sherpa 官方

## 模型下载链接

### Sherpa 官方模型库
- GitHub: https://github.com/k2-fsa/sherpa-onnx/releases
- 模型列表: https://github.com/k2-fsa/sherpa-onnx#tts-text-to-speech

### Hugging Face 模型库
- vits-zh-hf-fanchen: https://huggingface.co/csukuangfj/vits-zh-hf-fanchen-C
- melo-tts: https://huggingface.co/csukuangfj/sherpa-onnx-conda-wheels-2023-05-16/tree/main/tts

## 模型文件结构要求

每个 TTS 模型目录必须包含以下文件：

```
模型目录名/
├── model.onnx          # ONNX 模型文件（必需）
├── model.onnx.json     # 模型配置文件（必需）
├── tokens.txt          # 词表文件（可选，部分模型需要）
└── lexicon.txt         # 词典文件（可选，部分模型需要）
```

**注意**：
- `.onnx` 和 `.json` 文件必须成对出现
- 文件名可能因模型而异（如 `decoder.onnx`、`encoder.onnx` 等）
- 下载模型后请保持原始文件名

## 目录放置示例

```
PersonalData/voices/
├── README.md
├── vits-zh-hf-fanchen/
│   ├── model.onnx
│   └── model.onnx.json
├── melo-tts-zh/
│   ├── model.onnx
│   ├── model.onnx.json
│   └── tokens.txt
└── vits-piper-zh_CN-huayan/
    ├── model.onnx
    └── model.onnx.json
```

## 使用方法

1. 从上述链接下载模型压缩包
2. 解压缩后将模型文件夹放入本目录
3. 在应用设置中选择对应的 TTS 引擎和音色
4. 确保模型文件完整（.onnx + .json 配对）

## 常见问题

### Q: 模型加载失败？
A: 检查模型文件是否完整，确保 `.onnx` 和 `.json` 文件在同一目录下。

### Q: 如何测试模型是否可用？
A: 可以使用 sherpa-onnx 命令行工具测试：
```bash
sherpa-onnx-offline-tts --model=./模型目录/model.onnx --tokens=./模型目录/tokens.txt --output-filename=test.wav "测试文本"
```

### Q: 推荐哪个模型？
A: 对于中文场景，推荐使用 `vits-zh-hf-fanchen` 或 `melo-tts-zh`，发音自然且效果好。