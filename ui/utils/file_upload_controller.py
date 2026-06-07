from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from PySide6.QtCore import QObject, Signal, QThread, QTimer

from ui.utils.file_upload_manager import UploadedFileInfo, SUPPORTED_EXTENSIONS
from recorder import get_recorder, is_onnx_model_loaded
import config

# 音频文件扩展名列表
AUDIO_EXTENSIONS = ["wav", "mp3", "m4a", "flac"]


class FileParseWorker(QThread):
    parse_finished = Signal(str, object)
    parse_error = Signal(str, str)

    def __init__(
        self,
        file_id: str,
        file_path: Path,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._file_id = file_id
        self._file_path = file_path

    def run(self) -> None:
        try:
            from document_parser import parse_file, ParserFactory
            
            if not ParserFactory.is_supported(self._file_path):
                self.parse_error.emit(self._file_id, f"不支持的文件类型: {self._file_path.suffix}")
                return
            
            result = parse_file(self._file_path)
            if result.is_success:
                self.parse_finished.emit(self._file_id, result)
            else:
                self.parse_error.emit(self._file_id, result.error or "解析失败")
        except Exception as e:
            self.parse_error.emit(self._file_id, str(e))


class AudioParseWorker(QThread):
    """
    音频转录工作线程
    
    在后台线程中执行音频转录任务
    """
    parse_finished = Signal(str, object)
    parse_error = Signal(str, str)
    parse_progress = Signal(str, int, str)  # (file_id, progress, status)

    def __init__(
        self,
        file_id: str,
        file_path: Path,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._file_id = file_id
        self._file_path = file_path
        self._result_text: Optional[str] = None
        self._result_error: Optional[str] = None

    def run(self) -> None:
        try:
            from recorder import transcribe_audio_with_onnx, is_onnx_model_loaded
            
            # 检查 ASR 模型是否已加载
            if not is_onnx_model_loaded():
                self.parse_error.emit(self._file_id, "ASR 模型未加载，请先加载模型")
                return
            
            # 定义进度回调函数
            def progress_callback(progress: int, status: str):
                self.parse_progress.emit(self._file_id, progress, status)
            
            # 直接调用转录函数（在工作线程中执行）
            result = transcribe_audio_with_onnx(self._file_path, progress_callback=progress_callback)
            
            if result is not None:
                # 创建一个简单的结果对象
                class AudioTranscriptionResult:
                    def __init__(self, content: str):
                        self.content = content
                        self.summary = None
                        self.is_success = True
                        self.error = None
                
                transcription_result = AudioTranscriptionResult(result)
                self.parse_finished.emit(self._file_id, transcription_result)
            else:
                self.parse_error.emit(self._file_id, "音频转录失败：未获取到转录结果")
        except Exception as e:
            self.parse_error.emit(self._file_id, str(e))


class FileUploadController(QObject):
    file_added = Signal(object)
    file_removed = Signal(str)
    file_parse_started = Signal(str)
    file_parse_finished = Signal(str, object)
    file_parse_error = Signal(str, str)
    file_parse_progress = Signal(str, int, str)  # (file_id, progress, status)
    files_changed = Signal()
    upload_error = Signal(str)
    asr_model_not_loaded = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._files: dict[str, UploadedFileInfo] = {}
        self._parse_workers: dict[str, FileParseWorker] = {}
        self._max_files: int = 5
        self._max_file_size: int = getattr(config, 'FILE_UPLOAD_MAX_SIZE_MB', 10) * 1024 * 1024

    def get_supported_extensions(self) -> list[str]:
        return SUPPORTED_EXTENSIONS

    def get_file_filter(self) -> str:
        extensions = self.get_supported_extensions()
        filter_parts = []
        for ext in extensions:
            filter_parts.append(f"*.{ext}")
        return f"支持的文件 ({' '.join(filter_parts)})"

    def can_add_file(self) -> bool:
        return len(self._files) < self._max_files

    def validate_file(self, file_path: Path) -> Optional[str]:
        if not file_path.exists():
            return f"文件不存在: {file_path}"
        
        if not file_path.is_file():
            return f"路径不是文件: {file_path}"
        
        extension = file_path.suffix.lower().lstrip(".")
        if extension not in SUPPORTED_EXTENSIONS:
            return f"不支持的文件类型: {file_path.suffix}"
        
        file_size = file_path.stat().st_size
        if file_size > self._max_file_size:
            size_mb = file_size / (1024 * 1024)
            return f"文件过大 ({size_mb:.1f} MB)，最大支持 10 MB"
        
        return None

    def _is_audio_file(self, extension: str) -> bool:
        """检查是否为音频文件"""
        return extension.lower() in AUDIO_EXTENSIONS

    def _check_asr_model_loaded(self) -> bool:
        """检查 ASR 模型是否已加载"""
        return is_onnx_model_loaded()

    def add_file(self, file_path: Path) -> Optional[UploadedFileInfo]:
        validation_error = self.validate_file(file_path)
        if validation_error:
            self.upload_error.emit(validation_error)
            return None
        
        if not self.can_add_file():
            self.upload_error.emit(f"最多只能上传 {self._max_files} 个文件")
            return None
        
        file_id = uuid.uuid4().hex
        extension = file_path.suffix.lower().lstrip(".")
        
        # 检查是否为音频文件，如果是则检查 ASR 模型是否已加载
        if self._is_audio_file(extension):
            if not self._check_asr_model_loaded():
                self.asr_model_not_loaded.emit(file_path.name)
                return None
        
        mime_map: dict[str, str] = {
            "txt": "text/plain",
            "pdf": "application/pdf",
            "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "xls": "application/vnd.ms-excel",
            "md": "text/markdown",
            "json": "application/json",
        }
        
        file_info = UploadedFileInfo(
            file_id=file_id,
            original_name=file_path.name,
            file_path=file_path,
            file_size=file_path.stat().st_size,
            extension=extension,
            mime_type=mime_map.get(extension),
            upload_time=datetime.now(),
        )
        
        self._files[file_id] = file_info
        self.file_added.emit(file_info)
        self.files_changed.emit()
        
        self._start_parse(file_id)
        
        return file_info

    def remove_file(self, file_id: str) -> None:
        if file_id not in self._files:
            return
        
        if file_id in self._parse_workers:
            worker = self._parse_workers[file_id]
            if worker.isRunning():
                worker.quit()
                worker.wait(1000)
            del self._parse_workers[file_id]
        
        del self._files[file_id]
        self.file_removed.emit(file_id)
        self.files_changed.emit()

    def clear_all_files(self) -> None:
        for file_id in list(self._files.keys()):
            self.remove_file(file_id)

    def get_file(self, file_id: str) -> Optional[UploadedFileInfo]:
        return self._files.get(file_id)

    def get_all_files(self) -> list[UploadedFileInfo]:
        return list(self._files.values())

    def get_parsed_files(self) -> list[UploadedFileInfo]:
        return [f for f in self._files.values() if f.is_success]

    def has_files(self) -> bool:
        return len(self._files) > 0

    def file_count(self) -> int:
        return len(self._files)

    def _start_parse(self, file_id: str) -> None:
        file_info = self._files.get(file_id)
        if not file_info:
            return
        
        file_info.is_parsing = True
        file_info.is_parsed = False
        file_info.parse_error = None
        file_info.parse_progress = 0
        file_info.parse_status = "开始解析..."
        self.file_parse_started.emit(file_id)
        
        # 根据文件类型选择不同的解析器
        if self._is_audio_file(file_info.extension):
            worker = AudioParseWorker(file_id, file_info.file_path, self)
        else:
            worker = FileParseWorker(file_id, file_info.file_path, self)
        
        worker.parse_finished.connect(self._on_parse_finished)
        worker.parse_error.connect(self._on_parse_error)
        
        # 连接进度信号（仅 AudioParseWorker 有）
        if hasattr(worker, 'parse_progress'):
            worker.parse_progress.connect(self._on_parse_progress)
        
        worker.finished.connect(lambda: self._cleanup_worker(file_id))
        
        self._parse_workers[file_id] = worker
        worker.start()

    def _on_parse_progress(self, file_id: str, progress: int, status: str) -> None:
        file_info = self._files.get(file_id)
        if not file_info:
            return
        
        file_info.parse_progress = progress
        file_info.parse_status = status
        
        self.file_parse_progress.emit(file_id, progress, status)

    def _on_parse_finished(self, file_id: str, result: Any) -> None:
        file_info = self._files.get(file_id)
        if not file_info:
            return
        
        file_info.is_parsing = False
        file_info.is_parsed = True
        file_info.parse_result = result
        file_info.parse_error = None
        file_info.parse_progress = 100
        file_info.parse_status = "解析完成"
        
        self.file_parse_finished.emit(file_id, result)

    def _on_parse_error(self, file_id: str, error: str) -> None:
        file_info = self._files.get(file_id)
        if not file_info:
            return
        
        file_info.is_parsing = False
        file_info.is_parsed = False
        file_info.parse_result = None
        file_info.parse_error = error
        file_info.parse_progress = 0
        file_info.parse_status = "解析失败"
        
        self.file_parse_error.emit(file_id, error)

    def _cleanup_worker(self, file_id: str) -> None:
        if file_id in self._parse_workers:
            worker = self._parse_workers[file_id]
            worker.deleteLater()
            del self._parse_workers[file_id]

    def generate_file_summary(self, file_info: UploadedFileInfo) -> str:
        if not file_info.is_success:
            return ""
        
        result = file_info.parse_result
        if not result:
            return ""
        
        content = result.content or ""
        summary = result.summary or ""
        
        preview = content[:300] if len(content) > 300 else content
        
        summary_parts = [
            f"【文件: {file_info.original_name}】",
            f"类型: {file_info.extension.upper()}",
            f"大小: {file_info.get_file_size_display()}",
        ]
        
        if summary:
            summary_parts.append(f"摘要: {summary}")
        
        if preview:
            summary_parts.append(f"内容预览:\n{preview}")
        
        return "\n".join(summary_parts)

    def generate_combined_summary(self) -> str:
        parsed_files = self.get_parsed_files()
        if not parsed_files:
            return ""
        
        summaries = []
        for file_info in parsed_files:
            summary = self.generate_file_summary(file_info)
            if summary:
                summaries.append(summary)
        
        if not summaries:
            return ""
        
        header = f"已上传 {len(parsed_files)} 个文件，以下是文件内容摘要："
        return header + "\n\n" + "\n\n---\n\n".join(summaries)

    def generate_file_full_content(self, file_info: UploadedFileInfo) -> str:
        if not file_info.is_success:
            return ""
        
        result = file_info.parse_result
        if not result:
            return ""
        
        content = result.content or ""
        if not content:
            return ""
        
        return f"<filename>{file_info.original_name}</filename>\n<file_content>\n{content}\n</file_content>"

    def generate_combined_full_content(self) -> str:
        parsed_files = self.get_parsed_files()
        if not parsed_files:
            return ""
        
        contents = []
        for file_info in parsed_files:
            full_content = self.generate_file_full_content(file_info)
            if full_content:
                contents.append(full_content)
        
        if not contents:
            return ""
        
        files_content = "\n\n".join(contents)
        return f"<user_upload_files>\n{files_content}\n</user_upload_files>"

    def inject_summary_to_message(self, user_message: str) -> str:
        combined_summary = self.generate_combined_summary()
        if not combined_summary:
            return user_message
        
        return f"{combined_summary}\n\n---\n\n用户消息:\n{user_message}"