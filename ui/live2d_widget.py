"""
Live2D 悬浮球控件 - 基于 PySide6 + OpenGL 渲染 Live2D 模型

功能:
- 使用 PySide6.QtOpenGLWidgets.QOpenGLWidget 渲染
- 使用 live2d.v3 库加载和渲染模型
- 支持鼠标拖拽（视角跟随）和点击（触发动作）
- 支持透明背景
- 提供唇形同步接口
- 提供模型加载/失败/点击信号
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QMouseEvent
from PySide6.QtOpenGLWidgets import QOpenGLWidget

from logger import get_module_logger

logger = get_module_logger("Live2DWidget")


class Live2DWidget(QOpenGLWidget):
    """
    基于 OpenGL 的 Live2D 模型渲染控件

    信号:
        model_loaded: 模型加载成功时触发
        model_load_failed: 模型加载失败时触发
        clicked: 点击模型时触发
    """

    model_loaded = Signal()
    model_load_failed = Signal(str)  # 失败原因
    clicked = Signal()

    def __init__(
        self,
        parent=None,
        model_path: Optional[Path] = None,
    ):
        super().__init__(parent)

        logger.info(f"[init] Live2DWidget 构造, parent={parent}, model_path={model_path}")

        self._model_path: Optional[Path] = model_path
        self._pending_model_path: Optional[Path] = None  # 等待 OpenGL 就绪后加载
        self._model = None
        self._initialized = False
        self._live2d = None
        self._live2d_available = False

        # 唇形同步参数索引（模型加载后缓存）
        self._lip_sync_param_index: Optional[int] = None

        # 动画定时器
        self._update_timer = QTimer(self)
        self._update_timer.setInterval(33)  # ~30fps
        self._update_timer.timeout.connect(self._on_timer_tick)

        # 鼠标状态
        self._mouse_down = False
        self._last_mouse_x = 0.0
        self._last_mouse_y = 0.0

        # 唇形同步值 (0.0 - 1.0)
        self._lip_sync_value = 0.0

        # 尝试导入 live2d
        try:
            import live2d.v3 as live2d
            self._live2d = live2d
            self._live2d_available = True
            logger.info(f"[init] live2d.v3 导入成功, 可用={self._live2d_available}")
        except ImportError as e:
            logger.warning(f"[init] live2d.v3 模块不可用: {e}")
            self._live2d_available = False

        # 设置透明属性
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_AlwaysStackOnTop, True)
        logger.info(f"[init] Live2DWidget 构造完成, size={self.width()}x{self.height()}")

    def load_model(self, model_path: Path) -> None:
        """
        加载 Live2D 模型

        Args:
            model_path: .model3.json 文件路径
        """
        logger.info(f"[load_model] 调用, path={model_path}, initialized={self._initialized}")
        self._model_path = model_path

        # 如果 OpenGL 已经就绪，直接加载
        if self._initialized:
            logger.info("[load_model] OpenGL 已就绪，直接加载")
            self._do_load_model(model_path)
        else:
            # 否则暂存路径，等待 initializeGL 时加载
            self._pending_model_path = model_path
            logger.info(f"[load_model] OpenGL 未就绪，暂存路径等待初始化: {Path(model_path).name}")

    def _do_load_model(self, model_path: Path) -> None:
        """实际执行模型加载（必须在 OpenGL 上下文中调用）"""
        logger.info(f"[_do_load_model] 开始加载, path={model_path}")

        if not self._live2d_available:
            logger.error("[_do_load_model] live2d.v3 不可用")
            self.model_load_failed.emit("live2d.v3 模块不可用")
            return

        if model_path is None or not Path(model_path).exists():
            logger.error(f"[_do_load_model] 模型文件不存在: {model_path}")
            self.model_load_failed.emit(f"模型文件不存在: {model_path}")
            return

        try:
            live2d = self._live2d

            # 如果已有模型，先清理
            if self._model is not None:
                logger.info("[_do_load_model] 清理旧模型")
                self._model = None

            # 步骤1: 创建 LAppModel
            logger.info("[_do_load_model] 步骤1: 创建 LAppModel...")
            self._model = live2d.LAppModel()
            logger.info("[_do_load_model] 步骤1 完成: LAppModel 创建成功")

            # 步骤2: 加载模型 JSON
            logger.info(f"[_do_load_model] 步骤2: 加载模型 JSON: {model_path}...")
            self._model.LoadModelJson(str(model_path))
            logger.info("[_do_load_model] 步骤2 完成: 模型 JSON 加载成功")

            logger.info(f"Live2D 模型加载成功: {Path(model_path).name}")

            # 步骤3: 缓存唇形同步参数索引
            logger.info("[_do_load_model] 步骤3: 缓存唇形同步参数索引...")
            self._cache_lip_sync_param_index()

            # 步骤4: 播放待机动画
            logger.info("[_do_load_model] 步骤4: 播放待机动画...")
            self._start_idle_motion()
            logger.info("[_do_load_model] 步骤4 完成")

            # 步骤5: 刷新显示
            logger.info("[_do_load_model] 步骤5: 触发重绘...")
            self.update()

            # 步骤6: 发射信号
            logger.info("[_do_load_model] 步骤6: 发射 model_loaded 信号")
            self.model_loaded.emit()
            logger.info("[_do_load_model] 全部完成")

        except Exception as e:
            logger.error(f"Live2D 模型加载失败: {e}", exc_info=True)
            self._model = None
            self.model_load_failed.emit(str(e))

    def set_lip_sync_value(self, value: float) -> None:
        """
        设置唇形同步值

        Args:
            value: 0.0 (闭嘴) ~ 1.0 (张嘴)
        """
        self._lip_sync_value = max(0.0, min(1.0, value))

    # ========== OpenGL 方法 ==========

    def initializeGL(self) -> None:
        """初始化 OpenGL 上下文"""
        logger.info("[initializeGL] 被调用")

        if not self._live2d_available:
            logger.warning("[initializeGL] live2d 不可用，跳过")
            return

        try:
            live2d = self._live2d

            logger.info("[initializeGL] 调用 live2d.init()...")
            live2d.init()
            logger.info("[initializeGL] live2d.init() 完成")

            logger.info("[initializeGL] 调用 live2d.glInit()...")
            live2d.glInit()
            logger.info("[initializeGL] live2d.glInit() 完成")

            self._initialized = True
            logger.info("Live2D OpenGL 初始化完成")

            # 加载模型：优先加载 pending_model_path，否则加载 model_path
            load_path = self._pending_model_path or self._model_path
            logger.info(f"[initializeGL] 待加载路径: {load_path}")
            if load_path is not None:
                self._do_load_model(load_path)
                self._pending_model_path = None  # 清空暂存

            # 启动动画循环
            logger.info("[initializeGL] 启动动画定时器")
            self._update_timer.start()
            logger.info("[initializeGL] 全部完成")

        except Exception as e:
            logger.error(f"Live2D OpenGL 初始化失败: {e}", exc_info=True)
            self.model_load_failed.emit(str(e))

    def paintGL(self) -> None:
        """渲染每一帧"""
        if not self._live2d_available or self._model is None:
            return

        try:
            live2d = self._live2d

            # 清除缓冲区
            live2d.clearBuffer()

            # 更新模型
            self._model.Update()

            # 更新唇形同步
            if self._lip_sync_param_index is not None:
                self._model.SetIndexParamValue(
                    self._lip_sync_param_index, self._lip_sync_value, 1.0
                )

            # 绘制模型
            self._model.Draw()

        except Exception as e:
            logger.error(f"Live2D 渲染失败: {e}", exc_info=True)

    def resizeGL(self, w: int, h: int) -> None:
        """处理窗口大小变化"""
        logger.info(f"[resizeGL] w={w}, h={h}, model_exists={self._model is not None}")
        if not self._live2d_available or self._model is None:
            return

        try:
            self._model.Resize(w, h)
            logger.info(f"[resizeGL] Resize 完成")
        except Exception as e:
            logger.error(f"Live2D 缩放失败: {e}", exc_info=True)

    def closeEvent(self, event):
        """清理资源"""
        logger.info("[closeEvent] 开始清理")
        self._update_timer.stop()

        if self._live2d_available and self._model is not None:
            try:
                self._model = None
                self._live2d.glRelease()
                logger.info("Live2D 资源已释放")
            except Exception as e:
                logger.error(f"Live2D 资源释放失败: {e}")

        super().closeEvent(event)

    # ========== 鼠标事件 ==========

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """鼠标按下"""
        if event.button() == Qt.MouseButton.LeftButton:
            self._mouse_down = True
            self._update_mouse_pos(event)
        # 转发给父类（FloatingBall 处理拖动）
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """鼠标释放"""
        if event.button() == Qt.MouseButton.LeftButton:
            self._mouse_down = False
        # 转发给父类
        super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """鼠标移动（拖拽视角 + 悬浮球拖动）"""
        if self._mouse_down and self._model is not None and self._live2d_available:
            self._update_mouse_pos(event)
            self._model.Drag(self._last_mouse_x, self._last_mouse_y)
        # 转发给父类（FloatingBall 处理拖动）
        super().mouseMoveEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        """双击触发动作"""
        if event.button() == Qt.MouseButton.LeftButton:
            self._trigger_random_motion()
            self.clicked.emit()

    def _update_mouse_pos(self, event: QMouseEvent) -> None:
        """将鼠标坐标转换为归一化坐标 (-1 ~ 1)"""
        w = self.width()
        h = self.height()
        if w > 0 and h > 0:
            self._last_mouse_x = (event.position().x() / w) * 2.0 - 1.0
            self._last_mouse_y = -(event.position().y() / h) * 2.0 + 1.0

    def _trigger_random_motion(self) -> None:
        """触发随机动作"""
        if self._model is None or not self._live2d_available:
            return

        try:
            motion_groups = self._model.GetMotionGroups()
            if motion_groups:
                import random
                # GetMotionGroups() returns dict {group_name: motion_count}
                group = random.choice(list(motion_groups.keys()))
                self._model.StartMotion(group, 0)
        except Exception as e:
            logger.debug(f"触发动作失败: {e}")

    def _cache_lip_sync_param_index(self) -> None:
        """缓存唇形同步参数索引"""
        if self._model is None or not self._live2d_available:
            return

        try:
            param_ids = self._model.GetParamIds()
            for idx, pid in enumerate(param_ids):
                if "MouthOpenY" in pid:
                    self._lip_sync_param_index = idx
                    logger.info(f"[_cache_lip_sync] 找到唇形同步参数: {pid} (索引={idx})")
                    return
            logger.warning("[_cache_lip_sync] 未找到唇形同步参数 ParamMouthOpenY")
        except Exception as e:
            logger.debug(f"[_cache_lip_sync] 缓存唇形参数失败: {e}")

    def _start_idle_motion(self) -> None:
        """播放待机动画"""
        if self._model is None or not self._live2d_available:
            return

        try:
            motion_groups = self._model.GetMotionGroups()
            logger.info(f"[_start_idle_motion] 可用动作组: {list(motion_groups.keys())}")

            # 尝试播放 Idle 动作组
            idle_candidates = [g for g in motion_groups if "idle" in g.lower()]
            if idle_candidates:
                logger.info(f"[_start_idle_motion] 播放 idle 动作组: {idle_candidates[0]}")
                self._model.StartMotion(idle_candidates[0], 0)
            elif motion_groups:
                # 没有 Idle，播放第一个动作组
                first_group = list(motion_groups.keys())[0]
                logger.info(f"[_start_idle_motion] 播放第一个动作组: {first_group}")
                self._model.StartMotion(first_group, 0)
            else:
                logger.warning("[_start_idle_motion] 没有可用动作组")
        except Exception as e:
            logger.debug(f"播放待机动画失败: {e}")

    def _on_timer_tick(self) -> None:
        """定时器回调，触发重绘"""
        if self._model is not None:
            self.update()
