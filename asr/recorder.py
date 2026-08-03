"""
ASR录音管理模块

此模块负责音频录音管理和异步转录功能。

职责：
1. AudioRecorder类：音频录音管理器，支持实时语音识别
2. AudioTranscribeWorker类：异步转录工作线程
3. get_recorder单例函数：获取录音器实例

依赖方向：
- recorder.py依赖service.py（转录函数）
- 作为ASR模块的Interface层，面向用户交互

功能：
1. 使用sounddevice进行录音
2. 保存为WAV格式到PersonalData/records目录
3. 使用sherpa-onnx流式模型进行实时语音识别
"""

from __future__ import annotations

import threading
import wave
from datetime import datetime
from pathlib import Path
from typing import Optional, Callable

import config
from logger import get_module_logger
from resource_path import paths

from asr.model import _online_recognizer
from asr.service import transcribe_audio_with_onnx

logger = get_module_logger("asr.recorder")


# ============================================================================
# AudioRecorder类
# ============================================================================

class AudioRecorder:
    """
    音频录音管理器

    功能：
    1. 使用 sounddevice 进行录音
    2. 保存为 WAV 格式到 PersonalData/records 目录
    3. 使用 sherpa-onnx 流式模型进行实时语音识别
    """

    def __init__(self):
        self._is_recording: bool = False
        self._recording_thread: Optional[threading.Thread] = None
        self._audio_frames: list = []
        self._sample_rate: int = 16000
        self._channels: int = 1
        self._dtype: str = 'int16'
        self._stop_event: threading.Event = threading.Event()
        self._current_audio_path: Optional[Path] = None

        # 实时识别相关
        self._realtime_callback: Optional[Callable[[str, bool], None]] = None
        self._recognition_thread: Optional[threading.Thread] = None
        self._realtime_stream = None  # sherpa-onnx OnlineStream

        self._ensure_records_dir()

    def _ensure_records_dir(self) -> Path:
        records_dir = paths.personal_data_dir / "records"
        records_dir.mkdir(parents=True, exist_ok=True)
        return records_dir

    @property
    def is_recording(self) -> bool:
        return self._is_recording

    def start_recording(self, on_started: Optional[Callable[[], None]] = None, realtime_callback: Optional[Callable[[str, bool], None]] = None) -> bool:
        """
        开始录音

        Args:
            on_started: 录音开始后的回调函数
            realtime_callback: 实时识别结果回调 (text: str, is_final: bool)
                              如果流式模型已加载，录音期间会定期回调识别结果

        Returns:
            是否成功开始录音
        """
        if self._is_recording:
            logger.warning("录音已在进行中")
            return False

        try:
            import sounddevice as sd
        except ImportError:
            logger.error("sounddevice库未安装，无法录音")
            return False

        self._audio_frames = []
        self._stop_event.clear()
        self._is_recording = True
        self._realtime_callback = realtime_callback

        # 如果流式模型已加载且有回调，创建实时识别流
        if realtime_callback and _online_recognizer is not None:
            try:
                self._realtime_stream = _online_recognizer.create_stream()
                logger.info("已创建实时识别流，录音期间将进行实时语音识别")
            except Exception as e:
                logger.warning(f"创建实时识别流失败: {e}，将仅录音不做实时识别")
                self._realtime_stream = None

        def _record_audio():
            try:
                def callback(indata, frames, time, status):
                    if self._stop_event.is_set():
                        raise sd.CallbackStop()
                    audio_chunk = indata.copy()
                    self._audio_frames.append(audio_chunk)

                    # 同时喂给实时识别流
                    if self._realtime_stream is not None:
                        try:
                            import numpy as np
                            audio_float = audio_chunk.flatten().astype(np.float32) / 32768.0
                            self._realtime_stream.accept_waveform(self._sample_rate, audio_float)
                        except Exception as e:
                            logger.warning(f"喂音频到识别流失败: {e}")

                # 获取音频输入设备配置
                device_id = config.get_audio_input_device()
                if device_id is not None:
                    logger.info(f"使用配置的音频输入设备: ID={device_id}")
                else:
                    logger.debug("使用系统默认音频输入设备")

                with sd.InputStream(
                    samplerate=self._sample_rate,
                    channels=self._channels,
                    dtype=self._dtype,
                    device=device_id,
                    callback=callback
                ):
                    while not self._stop_event.is_set():
                        sd.sleep(100)

            except Exception as e:
                logger.exception(f"录音过程中发生错误: {e}")
                self._is_recording = False

        self._recording_thread = threading.Thread(
            target=_record_audio,
            name="audio-recording",
            daemon=True
        )
        self._recording_thread.start()

        # 启动实时识别线程
        if self._realtime_stream is not None and realtime_callback is not None:
            self._recognition_thread = threading.Thread(
                target=self._realtime_recognition_loop,
                name="realtime-recognition",
                daemon=True
            )
            self._recognition_thread.start()
            logger.info("实时识别线程已启动")

        if on_started:
            try:
                on_started()
            except Exception as e:
                logger.exception(f"执行录音开始回调时发生错误: {e}")

        logger.info("录音已开始")
        return True

    def _realtime_recognition_loop(self):
        """实时识别循环，定期解码并回调结果"""
        while not self._stop_event.is_set() and self._realtime_stream is not None and self._realtime_callback is not None:
            try:
                if _online_recognizer is not None:
                    # 先尝试解码（is_ready 时才解码）
                    if _online_recognizer.is_ready(self._realtime_stream):
                        _online_recognizer.decode_stream(self._realtime_stream)

                    # 无论是否解码，都尝试获取当前累积的识别结果
                    result = _online_recognizer.get_result(self._realtime_stream)
                    if result and result.strip():
                        try:
                            self._realtime_callback(result.strip(), False)
                        except Exception as e:
                            logger.warning(f"实时识别回调失败: {e}")
            except Exception as e:
                logger.warning(f"实时识别处理失败: {e}")

            # 每 200ms 检查一次
            self._stop_event.wait(0.2)

    def stop_recording(self, on_stopped: Optional[Callable[[], None]] = None) -> Optional[Path]:
        """
        停止录音并保存音频文件

        Args:
            on_stopped: 录音停止后的回调函数

        Returns:
            保存的音频文件路径，如果失败则返回 None
        """
        if not self._is_recording:
            logger.warning("录音未在进行中")
            return None

        self._stop_event.set()
        self._is_recording = False

        # 等待识别线程结束
        if self._recognition_thread:
            self._recognition_thread.join(timeout=1.0)
            self._recognition_thread = None

        if self._recording_thread:
            self._recording_thread.join(timeout=2.0)
            self._recording_thread = None

        # 获取实时识别的最终结果
        final_text = None
        if self._realtime_stream is not None and _online_recognizer is not None:
            try:
                # 输入尾部标记（end of segment）告诉模型音频已结束
                import numpy as np
                self._realtime_stream.accept_waveform(self._sample_rate, np.zeros(0, dtype=np.float32))
                # 尝试多次解码确保获取最终结果
                for _ in range(3):
                    if _online_recognizer.is_ready(self._realtime_stream):
                        _online_recognizer.decode_stream(self._realtime_stream)
                result = _online_recognizer.get_result(self._realtime_stream)
                if result:
                    final_text = result.strip()
                    logger.info(f"实时识别最终结果: {final_text}")
                # 回调最终结果
                if final_text and self._realtime_callback:
                    try:
                        self._realtime_callback(final_text, True)
                    except Exception as e:
                        logger.warning(f"最终结果回调失败: {e}")
            except Exception as e:
                logger.warning(f"获取实时识别最终结果失败: {e}")
            finally:
                self._realtime_stream = None

        self._realtime_callback = None

        # 如果有最终识别结果且不为空，不需要保存音频文件
        # 返回 None 表示实时识别成功，text 通过回调传递
        if final_text:
            self._audio_frames = []
            if on_stopped:
                try:
                    on_stopped()
                except Exception as e:
                    logger.exception(f"执行录音停止回调时发生错误: {e}")
            return None

        if not self._audio_frames:
            logger.warning("没有录制到音频数据")
            if on_stopped:
                try:
                    on_stopped()
                except Exception as e:
                    logger.exception(f"执行录音停止回调时发生错误: {e}")
            return None

        try:
            import numpy as np

            records_dir = self._ensure_records_dir()
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"recording_{timestamp}.wav"
            audio_path = records_dir / filename

            audio_data = np.concatenate(self._audio_frames, axis=0)

            with wave.open(str(audio_path), 'wb') as wf:
                wf.setnchannels(self._channels)
                wf.setsampwidth(2)
                wf.setframerate(self._sample_rate)
                wf.writeframes(audio_data.tobytes())

            self._current_audio_path = audio_path
            self._audio_frames = []

            logger.info(f"录音已保存到: {audio_path}")

            if on_stopped:
                try:
                    on_stopped()
                except Exception as e:
                    logger.exception(f"执行录音停止回调时发生错误: {e}")

            return audio_path

        except Exception as e:
            logger.exception(f"保存音频文件时发生错误: {e}")
            self._audio_frames = []
            if on_stopped:
                try:
                    on_stopped()
                except Exception as e:
                    logger.exception(f"执行录音停止回调时发生错误: {e}")
            return None

    def transcribe_audio(self, audio_path: Path) -> Optional[str]:
        """
        将音频文件转换为文本（使用 sherpa-onnx）

        Args:
            audio_path: 音频文件路径

        Returns:
            转换后的文本，如果失败则返回 None
        """
        return transcribe_audio_with_onnx(audio_path)

    def get_current_audio_path(self) -> Optional[Path]:
        return self._current_audio_path

    def get_audio_duration(self, audio_path: Path) -> Optional[float]:
        """
        获取音频文件的时长（秒）

        Args:
            audio_path: 音频文件路径

        Returns:
            音频时长（秒），如果失败则返回 None
        """
        try:
            audio_path = Path(audio_path) if isinstance(audio_path, str) else audio_path

            if not audio_path.exists():
                logger.error(f"音频文件不存在: {audio_path}")
                return None

            with wave.open(str(audio_path), 'rb') as wf:
                frames = wf.getnframes()
                rate = wf.getframerate()
                duration = frames / float(rate)
                return duration

        except Exception as e:
            logger.exception(f"获取音频时长失败: {e}")
            return None

    def transcribe_audio_async(
        self,
        audio_path: Path,
        callback: Optional[Callable[[str, Optional[str], Optional[str]], None]] = None,
        progress_callback: Optional[Callable[[int, str], None]] = None
    ) -> Optional[AudioTranscribeWorker]:
        """
        异步转录音频文件

        Args:
            audio_path: 音频文件路径
            callback: 转录完成回调函数 (audio_path: str, text: Optional[str], error: Optional[str])
                     - text 为 None 且 error 不为 None 表示转录失败
                     - text 不为 None 且 error 为 None 表示转录成功
            progress_callback: 进度回调函数 (progress: int, status: str)

        Returns:
            AudioTranscribeWorker 实例，如果音频时长超限或文件不存在则返回 None
        """
        audio_path = Path(audio_path) if isinstance(audio_path, str) else audio_path

        # 检查音频文件是否存在
        if not audio_path.exists():
            logger.error(f"音频文件不存在: {audio_path}")
            if callback:
                callback(str(audio_path), None, f"音频文件不存在: {audio_path}")
            return None

        # 检查音频时长是否超过限制
        max_duration = getattr(config, 'ASR_MAX_AUDIO_DURATION', 3600)
        duration = self.get_audio_duration(audio_path)

        if duration is not None and duration > max_duration:
            error_msg = f"音频时长 ({duration:.1f}秒) 超过限制 ({max_duration}秒)"
            logger.warning(error_msg)
            if callback:
                callback(str(audio_path), None, error_msg)
            return None

        # 创建回调函数
        def on_finished(path: str, text: str):
            if callback:
                callback(path, text, None)

        def on_error(path: str, error: str):
            if callback:
                callback(path, None, error)

        def on_progress(progress: int, status: str):
            if progress_callback:
                progress_callback(progress, status)

        # 创建转录工作线程
        worker = AudioTranscribeWorker(
            audio_path,
            on_finished=on_finished,
            on_error=on_error,
            on_progress=on_progress
        )

        # 启动工作线程
        worker.start()

        logger.info(f"已启动异步转录任务: {audio_path}")
        return worker


# ============================================================================
# AudioTranscribeWorker类
# ============================================================================

class AudioTranscribeWorker(threading.Thread):
    """
    音频转录工作线程

    在后台线程中执行音频转录任务，避免阻塞主线程
    """

    def __init__(self, audio_path: Path,
                 on_finished: Callable[[str, str], None] = None,
                 on_error: Callable[[str, str], None] = None,
                 on_progress: Callable[[int, str], None] = None):
        """
        初始化转录工作线程

        Args:
            audio_path: 音频文件路径
            on_finished: 转录完成回调函数 (audio_path: str, text: str)
            on_error: 转录错误回调函数 (audio_path: str, error: str)
            on_progress: 转录进度回调函数 (progress: int, status: str)
        """
        super().__init__(daemon=True)
        self._audio_path = Path(audio_path) if isinstance(audio_path, str) else audio_path
        self._on_finished = on_finished
        self._on_error = on_error
        self._on_progress = on_progress
        self._stop_event = threading.Event()

    def run(self):
        """执行转录任务"""
        try:
            # 发送开始进度
            if self._on_progress:
                self._on_progress(0, "开始转录...")

            # 检查是否被取消
            if self._stop_event.is_set():
                if self._on_error:
                    self._on_error(str(self._audio_path), "转录已取消")
                return

            # 检查音频文件是否存在
            if not self._audio_path.exists():
                if self._on_error:
                    self._on_error(str(self._audio_path), f"音频文件不存在: {self._audio_path}")
                return

            # 发送进度
            if self._on_progress:
                self._on_progress(10, "正在加载音频文件...")

            # 检查是否被取消
            if self._stop_event.is_set():
                if self._on_error:
                    self._on_error(str(self._audio_path), "转录已取消")
                return

            # 发送进度
            if self._on_progress:
                self._on_progress(30, "正在进行语音识别...")

            # 执行转录
            result = transcribe_audio_with_onnx(self._audio_path)

            # 检查是否被取消
            if self._stop_event.is_set():
                if self._on_error:
                    self._on_error(str(self._audio_path), "转录已取消")
                return

            # 发送完成进度
            if self._on_progress:
                self._on_progress(100, "转录完成")

            if result is not None:
                if self._on_finished:
                    self._on_finished(str(self._audio_path), result)
            else:
                if self._on_error:
                    self._on_error(str(self._audio_path), "转录失败,返回空结果")

        except Exception as e:
            logger.exception(f"转录过程中发生错误: {e}")
            if self._on_error:
                self._on_error(str(self._audio_path), str(e))

    def request_interruption(self):
        """请求取消转录任务"""
        self._stop_event.set()

    def isInterruptionRequested(self):
        """检查是否已请求取消"""
        return self._stop_event.is_set()


# ============================================================================
# 单例函数
# ============================================================================

_recorder_instance: Optional[AudioRecorder] = None


def get_recorder() -> AudioRecorder:
    """获取录音器单例"""
    global _recorder_instance
    if _recorder_instance is None:
        _recorder_instance = AudioRecorder()
    return _recorder_instance