from __future__ import annotations

import tempfile
import wave
from pathlib import Path
from typing import Any

from ..base_parser import BaseParser
from ..models import ParseResult


class AudioParser(BaseParser):
    """音频文件解析器。

    支持的音频格式：wav、mp3、m4a、flac
    使用 sherpa-onnx ASR 模型进行语音转文本。
    """

    SUPPORTED_EXTENSIONS = [".wav", ".mp3", ".m4a", ".flac"]

    def parse(self, file_path: Path) -> ParseResult:
        """解析音频文件，将语音转换为文本。

        Args:
            file_path: 要解析的音频文件路径

        Returns:
            ParseResult: 包含转录文本、元信息和摘要的解析结果
        """
        # 导入 recorder 模块（延迟导入避免循环依赖）
        import recorder

        # 验证文件
        error = self.validate_file(file_path)
        if error:
            return ParseResult.from_error(error, file_path)

        # 检查 ASR 模型是否已加载
        if not recorder.is_online_model_loaded():
            return ParseResult.from_error(
                "实时语音识别模型未加载，请先加载模型后再解析音频文件",
                file_path
            )

        # 获取音频文件信息
        metadata = self._extract_metadata(file_path)

        # 如果不是 wav 格式，需要先转换
        temp_wav_path = None
        audio_path = file_path

        try:
            if file_path.suffix.lower() not in [".wav"]:
                temp_wav_path = self._convert_to_wav(file_path)
                if temp_wav_path is None:
                    return ParseResult.from_error(
                        f"音频格式转换失败，请确保已安装 pydub 和 ffmpeg",
                        file_path
                    )
                audio_path = temp_wav_path

            # 注意：当前版本不支持音频文件转录，仅支持实时语音识别
            # 音频文件转录功能需要后续实现
            return ParseResult.from_error(
                "当前版本仅支持实时语音识别，不支持音频文件转录功能",
                file_path
            )

            if transcript is None:
                return ParseResult.from_error(
                    "音频转录失败，无法识别语音内容",
                    file_path
                )

            # 更新元信息
            metadata["transcript_length"] = len(transcript)

            # 生成摘要
            summary = self._generate_summary(transcript, metadata)

            return ParseResult(
                content=transcript,
                metadata=metadata,
                summary=summary,
                file_path=file_path,
            )

        finally:
            # 清理临时文件
            if temp_wav_path is not None:
                try:
                    Path(temp_wav_path).unlink(missing_ok=True)
                except Exception:
                    pass

    def _convert_to_wav(self, audio_path: Path) -> Path | None:
        """将音频文件转换为 WAV 格式。

        使用 pydub 进行格式转换，需要安装 ffmpeg。

        Args:
            audio_path: 原始音频文件路径

        Returns:
            Path | None: 转换后的临时 WAV 文件路径，失败返回 None
        """
        try:
            from pydub import AudioSegment

            # 读取音频文件
            audio = AudioSegment.from_file(str(audio_path))

            # 转换为 16kHz 单声道 16-bit PCM
            audio = audio.set_frame_rate(16000)
            audio = audio.set_channels(1)
            audio = audio.set_sample_width(2)  # 16-bit

            # 创建临时文件
            temp_fd, temp_path = tempfile.mkstemp(suffix=".wav")

            # 导出为 WAV 格式
            audio.export(temp_path, format="wav")

            return Path(temp_path)

        except ImportError:
            # pydub 未安装，尝试使用 ffmpeg 直接转换
            return self._convert_to_wav_with_ffmpeg(audio_path)
        except Exception:
            return None

    def _convert_to_wav_with_ffmpeg(self, audio_path: Path) -> Path | None:
        """使用 ffmpeg 直接将音频文件转换为 WAV 格式。

        Args:
            audio_path: 原始音频文件路径

        Returns:
            Path | None: 转换后的临时 WAV 文件路径，失败返回 None
        """
        import subprocess

        try:
            # 创建临时文件
            temp_fd, temp_path = tempfile.mkstemp(suffix=".wav")

            # 使用 ffmpeg 转换
            # -ar 16000: 采样率 16kHz
            # -ac 1: 单声道
            # -acodec pcm_s16le: 16-bit PCM 编码
            result = subprocess.run(
                [
                    "ffmpeg",
                    "-y",  # 覆盖输出文件
                    "-i", str(audio_path),
                    "-ar", "16000",
                    "-ac", "1",
                    "-acodec", "pcm_s16le",
                    temp_path
                ],
                capture_output=True,
                text=True
            )

            if result.returncode != 0:
                return None

            return Path(temp_path)

        except Exception:
            return None

    def _extract_metadata(self, file_path: Path) -> dict[str, Any]:
        """提取音频文件的元信息。

        Args:
            file_path: 音频文件路径

        Returns:
            dict: 元信息字典
        """
        stat = file_path.stat()

        metadata: dict[str, Any] = {
            "content_type": "text",
            "file_name": file_path.name,
            "file_size": stat.st_size,
            "created_time": stat.st_ctime,
            "modified_time": stat.st_mtime,
            "file_extension": file_path.suffix.lower(),
        }

        # 尝试获取音频时长（仅对 WAV 文件）
        if file_path.suffix.lower() == ".wav":
            duration = self._get_wav_duration(file_path)
            if duration is not None:
                metadata["duration_seconds"] = duration

        return metadata

    def _get_wav_duration(self, wav_path: Path) -> float | None:
        """获取 WAV 文件的时长。

        Args:
            wav_path: WAV 文件路径

        Returns:
            float | None: 音频时长（秒），失败返回 None
        """
        try:
            with wave.open(str(wav_path), 'rb') as wf:
                frames = wf.getnframes()
                rate = wf.getframerate()
                return frames / float(rate)
        except Exception:
            return None

    def _generate_summary(self, transcript: str, metadata: dict[str, Any]) -> str:
        """生成音频文件的摘要。

        Args:
            transcript: 转录文本
            metadata: 元信息

        Returns:
            str: 摘要文本
        """
        duration_info = ""
        if "duration_seconds" in metadata:
            duration = metadata["duration_seconds"]
            minutes = int(duration // 60)
            seconds = int(duration % 60)
            duration_info = f"，时长 {minutes}分{seconds}秒" if minutes > 0 else f"，时长 {seconds}秒"

        transcript_preview = transcript[:100] if len(transcript) > 100 else transcript
        if len(transcript) > 100:
            transcript_preview += "..."

        return f"音频转录文本{duration_info}，共 {len(transcript)} 字: {transcript_preview}"