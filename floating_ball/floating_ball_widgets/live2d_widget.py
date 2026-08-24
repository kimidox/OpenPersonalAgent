"""
Live2D 渲染组件 - 作为悬浮球的子组件

从 floating_ball_process.py 内部类提取，逻辑完全等价。

Business purpose:
    使用 live2d-py 库渲染 Live2D 模型，作为悬浮球的子组件。

Modification notes:
    2026-07-29: 从 run_floating_ball_process 内部类提取为独立模块

Related tests:
    tests/test_floating_ball_widgets.py (待补充)
"""
from __future__ import annotations

import time
import traceback
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import QWidget

from logger import get_logger


class Live2DWidget(QOpenGLWidget):
    """
    Live2D 渲染组件 - 作为悬浮球的子组件

    使用 live2d-py 库渲染 Live2D 模型
    参考: https://github.com/EasyLive2D/live2d-py/tree/main/demos/PyQt
    """

    def __init__(
        self,
        model_path: str,
        parent: Optional[QWidget] = None,
    ) -> None:
        """
        初始化 Live2D 渲染组件

        Args:
            model_path: 模型 JSON 文件路径（.model3.json）
            parent: 父窗口

        Raises:
            RuntimeError: 如果 Live2D 初始化或模型加载失败
        """
        super().__init__(parent)
        self._logger = get_logger()
        self._model_path = model_path
        self._model = None
        self._live2d_initialized = False
        self._render_frame_count = 0
        self._render_timer_id: int | None = None  # 渲染定时器 ID

        # 渲染节流相关状态
        self._is_interactive = False  # 用户是否正在交互（悬停/点击）
        self._last_interaction_time = 0.0  # 上次交互时间
        self._throttle_mode = False  # 是否处于节流模式（降低渲染频率）
        self._throttle_frame_skip = 0  # 节流模式下的帧跳过计数

        # 性能监控相关状态
        self._perf_last_frame_time = 0.0  # 上帧渲染时间
        self._perf_frame_times: list[float] = []  # 最近 N 帧的渲染时间（用于计算平均值）
        self._perf_fps_samples: list[float] = []  # 最近 N 帧的 FPS 样本
        self._perf_last_report_time = 0.0  # 上次性能报告时间
        self._perf_frames_since_report = 0  # 自上次报告以来的帧数

        # 设置组件属性（作为子组件，不需要窗口标志）
        # 注意：某些系统/显卡下，透明背景会导致 Live2D 渲染不出来
        # 暂时使用半透明红色背景进行测试，便于观察窗口是否真的显示
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet("background:transparent")

        # 初始化 Live2D 框架（在 OpenGL 上下文创建后）
        # 注意: initializeGL 会在组件显示后自动调用

    def initializeGL(self) -> None:
        """初始化 OpenGL 上下文和 Live2D 框架"""
        try:
            # 导入 Live2D（延迟导入以便捕获错误）
            try:
                import live2d.v3 as live2d
            except ImportError as e:
                self._logger.error(
                    f"导入 live2d-py 失败，请确保已安装 live2d-py 包。"
                    f"错误类型: {type(e).__name__}, 错误信息: {e}",
                    exc_info=True
                )
                # 设置错误标志
                self._live2d_initialized = False
                # 通知父窗口 Live2D 加载失败
                if self.parent():
                    self.parent()._live2d_widget = None
                return

            # 初始化 OpenGL 上下文（glInit 而不是 init）
            try:
                # Cubism 框架已在 run_floating_ball_process 中初始化
                # 这里只需要初始化 OpenGL 绑定
                live2d.glInit()
                self._live2d_initialized = True
                self._logger.info("Live2D OpenGL 上下文初始化成功")
            except Exception as e:
                self._logger.error(
                    f"Live2D OpenGL 上下文初始化失败。"
                    f"错误类型: {type(e).__name__}, 错误信息: {e}",
                    exc_info=True
                )
                # 设置错误标志
                self._live2d_initialized = False
                # 通知父窗口 Live2D 加载失败
                if self.parent():
                    self.parent()._live2d_widget = None
                return

            # 创建模型实例
            self._logger.info("步骤 1/5: 准备创建 Live2D 模型实例...")
            try:
                self._model = live2d.LAppModel()
                self._logger.info("步骤 1/5: ✓ Live2D 模型实例创建成功")
            except Exception as e:
                self._logger.error(
                    f"步骤 1/5: ✗ 创建 Live2D 模型实例失败。"
                    f"错误类型: {type(e).__name__}, 错误信息: {e}",
                    exc_info=True
                )
                # 设置错误标志
                self._live2d_initialized = False
                # 通知父窗口 Live2D 加载失败
                if self.parent():
                    self.parent()._live2d_widget = None
                return

            # 加载模型
            self._logger.info(f"步骤 2/5: 准备加载 Live2D 模型...")
            model_path_obj = Path(self._model_path)
            self._logger.info(f"步骤 2/5: 模型路径对象创建完成: {model_path_obj}")
            self._logger.info(f"步骤 2/5: 模型路径（字符串）: {self._model_path}")
            self._logger.info(f"步骤 2/5: 模型路径（绝对路径）: {model_path_obj.absolute()}")
            self._logger.info(f"步骤 2/5: 模型路径是否存在: {model_path_obj.exists()}")

            if not model_path_obj.exists():
                self._logger.error(
                    f"步骤 2/5: ✗ Live2D 模型文件不存在。路径: {self._model_path}, "
                    f"绝对路径: {model_path_obj.absolute()}"
                )
                # 设置错误标志
                self._live2d_initialized = False
                # 通知父窗口 Live2D 加载失败
                if self.parent():
                    self.parent()._live2d_widget = None
                return

            try:
                self._logger.info(f"步骤 2/5: 开始调用 LoadModelJson...")
                self._model.LoadModelJson(self._model_path)
                self._logger.info(f"步骤 2/5: ✓ Live2D 模型加载成功: {self._model_path}")
            except Exception as e:
                self._logger.error(
                    f"步骤 2/5: ✗ 加载 Live2D 模型失败。模型路径: {self._model_path}, "
                    f"错误类型: {type(e).__name__}, 错误信息: {e}",
                    exc_info=True
                )
                # 设置错误标志
                self._live2d_initialized = False
                # 通知父窗口 Live2D 加载失败
                if self.parent():
                    self.parent()._live2d_widget = None
                return

            # 启动 idle 动作
            self._logger.info("步骤 3/5: 准备启动 Live2D idle 动作...")
            try:
                self._model.StartMotion("idle", 0, 3)
                self._logger.info("步骤 3/5: ✓ Live2D idle 动作已启动")
            except Exception as e:
                self._logger.warning(f"步骤 3/5: ⚠ 启动 idle 动作失败: {e} (可能是模型没有该动作)")

            # 设置初始视图矩阵
            self._logger.info("步骤 4/5: 准备设置初始视图矩阵...")
            self._update_view_matrix()
            self._logger.info("步骤 4/5: ✓ 初始视图矩阵设置完成")

            # 启动渲染定时器（30 FPS，降低 CPU/GPU 占用）
            self._logger.info("步骤 5/5: 准备启动渲染定时器（30 FPS）...")
            self._render_timer_id = self.startTimer(int(1000 / 30))
            self._logger.info(f"步骤 5/5: ✓ 渲染定时器已启动，定时器 ID: {self._render_timer_id}")

            # 记录初始化完成
            self._logger.info("Live2D initializeGL 完成，等待第一帧渲染")

        except Exception as e:
            self._logger.error(
                f"Live2D 初始化过程中发生未知错误。"
                f"错误类型: {type(e).__name__}, 错误信息: {e}",
                exc_info=True
            )
            # 设置错误标志
            self._live2d_initialized = False
            # 通知父窗口 Live2D 加载失败
            if self.parent():
                self.parent()._live2d_widget = None

    def paintGL(self) -> None:
        """渲染 Live2D 模型（包含性能监控）"""
        # 在方法开始处添加日志（仅在前几帧和每300帧记录）
        if self._render_frame_count < 5:
            self._logger.info(f"paintGL 被调用，当前帧数: {self._render_frame_count}")

        # 记录帧开始时间
        frame_start_time = time.time()

        # 检查 OpenGL 上下文是否仍然有效
        if self.context() is None or not self.context().isValid():
            self._logger.error("paintGL: OpenGL 上下文已失效")
            return

        if not self._live2d_initialized or self._model is None:
            self._logger.error("paintGL called but model not initialized!")
            return

        try:
            from PySide6.QtGui import QOpenGLContext
            import live2d.v3 as live2d

            # 获取 OpenGL 函数
            gl = QOpenGLContext.currentContext().functions()

            # 设置 OpenGL 视口（关键！）
            gl.glViewport(0, 0, self.width(), self.height())

            # 启用 Alpha 混合（透明背景必需）
            # 注意：QOpenGLFunctions 中没有 GL_BLEND 常量，使用 OpenGL 原生常量
            try:
                from OpenGL.GL import GL_BLEND, GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA
                gl.glEnable(GL_BLEND)
                gl.glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
            except Exception:
                # 如果 PyOpenGL 未安装，尝试使用 Qt 中的常量
                from PySide6.QtOpenGL import QOpenGL
                gl.glEnable(QOpenGL.GL_BLEND)
                gl.glBlendFunc(QOpenGL.GL_SRC_ALPHA, QOpenGL.GL_ONE_MINUS_SRC_ALPHA)

            # 清除缓冲区（透明背景）
            live2d.clearBuffer(0.0, 0.0, 0.0, 0.0)

            # 更新模型状态
            self._model.Update()

            # 渲染模型
            self._model.Draw()

            # 检查 OpenGL 错误
            error = gl.glGetError()
            if error != 0:  # GL_NO_ERROR = 0
                self._logger.warning(f"OpenGL 错误: {error}")

            # 记录渲染成功
            self._render_frame_count += 1

            # ----------------- 性能监控 -----------------
            frame_end_time = time.time()
            frame_time = frame_end_time - frame_start_time

            # 计算帧率（FPS）
            if self._perf_last_frame_time > 0:
                delta_time = frame_end_time - self._perf_last_frame_time
                if delta_time > 0:
                    fps = 1.0 / delta_time
                    self._perf_fps_samples.append(fps)

                    # 只保留最近 60 帧的数据
                    if len(self._perf_fps_samples) > 60:
                        self._perf_fps_samples.pop(0)

            self._perf_last_frame_time = frame_end_time

            # 记录渲染时间
            self._perf_frame_times.append(frame_time)
            if len(self._perf_frame_times) > 60:
                self._perf_frame_times.pop(0)

            # 统计帧数
            self._perf_frames_since_report += 1

            # 每 10 秒记录一次性能统计
            if frame_end_time - self._perf_last_report_time >= 10.0:
                if self._perf_fps_samples and self._perf_frame_times:
                    avg_fps = sum(self._perf_fps_samples) / len(self._perf_fps_samples)
                    avg_frame_time = sum(self._perf_frame_times) / len(self._perf_frame_times)
                    total_frames = self._perf_frames_since_report
                    actual_fps = total_frames / 10.0

                    self._logger.info(
                        f"Live2D 性能统计: "
                        f"平均帧率={avg_fps:.1f} FPS, "
                        f"实际帧率={actual_fps:.1f} FPS, "
                        f"平均渲染时间={avg_frame_time*1000:.2f} ms, "
                        f"总帧数={self._render_frame_count}, "
                        f"节流模式={'是' if self._throttle_mode else '否'}"
                    )

                self._perf_last_report_time = frame_end_time
                self._perf_frames_since_report = 0

            # 第一帧时记录详细的模型信息（第1帧）
            if self._render_frame_count == 1:
                try:
                    # 获取模型信息
                    model_info = {
                        "window_size": f"{self.width()}x{self.height()}",
                        "model_path": self._model_path,
                        "window_visible": self.isVisible(),
                        "window_opacity": self.windowOpacity(),
                        "widget_opacity": self.opacity(),
                    }

                    # 尝试获取模型画布信息（如果有API）
                    try:
                        if hasattr(self._model, 'GetCanvasWidth'):
                            model_info["canvas_width"] = self._model.GetCanvasWidth()
                        if hasattr(self._model, 'GetCanvasHeight'):
                            model_info["canvas_height"] = self._model.GetCanvasHeight()
                        if hasattr(self._model, 'GetModelColor'):
                            model_info["has_color"] = True
                    except Exception as e:
                        self._logger.warning(f"获取模型属性失败: {e}")

                    # 检查 OpenGL 状态
                    try:
                        gl_error = gl.glGetError()
                        model_info["gl_error"] = gl_error
                        model_info["viewport"] = f"{gl.glGetIntegerv(gl.GL_VIEWPORT)}" if hasattr(gl, 'GL_VIEWPORT') else "unknown"
                    except Exception as e:
                        self._logger.warning(f"获取 OpenGL 状态失败: {e}")

                    self._logger.info(f"Live2D 第一帧渲染信息: {model_info}")
                except Exception as e:
                    self._logger.warning(f"获取模型信息失败: {e}")

            # 第30帧时记录渲染成功（从 60 改为 30，适应新的帧率）
            elif self._render_frame_count == 30:
                self._logger.info(f"Live2D 第一秒渲染成功！窗口大小: {self.width()}x{self.height()}")
            # 每300帧记录一次（从 60 改为 300，适应新的帧率）
            elif self._render_frame_count % 300 == 0:
                self._logger.info(f"Live2D 已渲染 {self._render_frame_count} 帧")

        except Exception as e:
            self._logger.error(f"Live2D 渲染异常: {e}")
            import traceback
            self._logger.error(f"异常堆栈: {traceback.format_exc()}")

    def timerEvent(self, event) -> None:
        """定时器事件：触发重绘（支持渲染节流）"""
        # 仅在前 10 次定时器触发时记录日志
        if self._render_frame_count < 10:
            self._logger.debug(
                f"timerEvent 触发，帧数: {self._render_frame_count}, "
                f"live2d_initialized: {self._live2d_initialized}, "
                f"model is None: {self._model is None}, "
                f"timer_id: {self._render_timer_id}"
            )

        if self._render_frame_count == 0:
            self._logger.debug("Live2D 渲染定时器触发，等待第一帧")

        # 检查是否需要切换到节流模式
        current_time = time.time()
        if self._is_interactive:
            # 有交互，更新交互时间并禁用节流模式
            self._last_interaction_time = current_time
            if self._throttle_mode:
                self._throttle_mode = False
                self._throttle_frame_skip = 0
                self._logger.debug("Live2D 恢复正常渲染频率（用户交互）")
        else:
            # 无交互，检查是否超过 5 秒
            if current_time - self._last_interaction_time > 5.0 and not self._throttle_mode:
                self._throttle_mode = True
                self._logger.debug("Live2D 进入节流模式（无交互超过 5 秒）")

        # 节流模式：每 6 帧渲染一次（30 FPS / 6 ≈ 5 FPS）
        if self._throttle_mode:
            self._throttle_frame_skip += 1
            if self._throttle_frame_skip < 6:
                return  # 跳过本次渲染
            self._throttle_frame_skip = 0

        self.update()

    def showEvent(self, event) -> None:
        """窗口显示事件"""
        super().showEvent(event)
        self._logger.info(f"Live2D 窗口 showEvent: visible={self.isVisible()}, geometry={self.geometry()}")

    def hideEvent(self, event) -> None:
        """窗口隐藏事件"""
        super().hideEvent(event)
        import traceback
        self._logger.warning(f"Live2D 窗口 hideEvent: 调用堆栈:\n{''.join(traceback.format_stack())}")

    def closeEvent(self, event) -> None:
        """窗口关闭事件 - 清理资源"""
        self._logger.info("Live2D 窗口 closeEvent: 开始清理资源")

        # 停止渲染定时器
        if self._render_timer_id is not None:
            try:
                self.killTimer(self._render_timer_id)
                self._logger.info(f"渲染定时器已停止 (ID: {self._render_timer_id})")
                self._render_timer_id = None
            except Exception as e:
                self._logger.error(f"停止渲染定时器失败: {e}")

        # 清理 Live2D 资源
        try:
            self.cleanup()
            self._logger.info("Live2D 资源清理完成")
        except Exception as e:
            self._logger.error(f"清理 Live2D 资源失败: {e}")

        # 调用父类方法
        super().closeEvent(event)

        import traceback
        self._logger.info(f"Live2D 窗口 closeEvent 完成，调用堆栈:\n{''.join(traceback.format_stack())}")

    def resizeGL(self, width: int, height: int) -> None:
        """窗口尺寸变化时更新视图矩阵"""
        self._update_view_matrix(width, height)

    def _update_view_matrix(self, width: Optional[int] = None, height: Optional[int] = None) -> None:
        """更新模型视图矩阵"""
        if not self._live2d_initialized or self._model is None:
            return

        try:
            w = width if width is not None else self.width()
            h = height if height is not None else self.height()

            # 设置视图矩阵（根据窗口尺寸调整）
            # live2d-py 会自动处理视图矩阵更新
            self._model.Resize(w, h)

        except Exception as e:
            self._logger.error(f"更新视图矩阵失败: {e}")

    def cleanup(self) -> None:
        """清理资源"""
        # 清理 Live2D 模型
        if self._model is not None:
            try:
                # 如果模型有清理方法，调用它
                if hasattr(self._model, "Dispose"):
                    self._model.Dispose()
            except Exception as e:
                self._logger.error(f"清理 Live2D 模型失败: {e}")

        self._model = None

        # 清理性能监控数据（释放内存）
        self._perf_frame_times.clear()
        self._perf_fps_samples.clear()

        # 重置状态标志
        self._live2d_initialized = False

        self._logger.info("Live2D 资源已清理（包括性能监控数据）")

    # ----------------- Live2D 模型动作 -----------------

    def play_click_animation(self, hit_area: str | None = None) -> None:
        """
        播放点击动画（供外部调用）

        Args:
            hit_area: 点击的区域名称，如果为 None 则自动选择动作
        """
        if not self._live2d_initialized or self._model is None:
            return

        try:
            # 根据点击区域选择动作
            motion_played = False

            # 优先使用点击区域对应的动作
            if hit_area:
                try:
                    self._model.StartMotion(hit_area, 0, 3)
                    self._logger.info(f"Live2D 播放 {hit_area} 动作")
                    motion_played = True
                except Exception as e:
                    self._logger.debug(f"播放 {hit_area} 动作失败: {e}")

            # 如果指定区域动作失败，尝试其他常见动作
            if not motion_played:
                # 尝试 touch_body
                try:
                    self._model.StartMotion("touch_body", 0, 3)
                    self._logger.info("Live2D 播放 touch_body 动作")
                    motion_played = True
                except Exception:
                    pass

            # 如果 touch_body 失败，尝试 touch_head
            if not motion_played:
                try:
                    self._model.StartMotion("touch_head", 0, 3)
                    self._logger.info("Live2D 播放 touch_head 动作")
                    motion_played = True
                except Exception:
                    pass

            # 如果都失败，记录警告
            if not motion_played:
                self._logger.warning("Live2D 模型没有 touch_body 或 touch_head 动作")

        except Exception as e:
            self._logger.error(f"播放 Live2D 点击动画失败: {e}")

    def check_model_hit_test(self, x: int, y: int) -> bool:
        """
        检测点击是否在模型上（碰撞检测）

        Args:
            x: 点击的 x 坐标（窗口坐标系）
            y: 点击的 y 坐标（窗口坐标系）

        Returns:
            True 如果点击在模型上
        """
        hit_area = self.get_hit_area(x, y)
        return hit_area is not None

    def get_hit_area(self, x: int, y: int) -> str | None:
        """
        获取点击的区域名称（碰撞检测）

        Args:
            x: 点击的 x 坐标（窗口坐标系）
            y: 点击的 y 坐标（窗口坐标系）

        Returns:
            点击的区域名称（如 "touch_body", "touch_head"），如果没有点击到任何区域则返回 None
        """
        if not self._live2d_initialized or self._model is None:
            # 如果模型未初始化，返回 None
            return None

        try:
            # 尝试使用模型的碰撞检测
            # live2d-py 的 HitTest 方法需要标准化的坐标 [0, 1]
            # 需要将窗口坐标转换为模型坐标
            norm_x = x / self.width()
            norm_y = y / self.height()

            # 调用模型的碰撞检测（如果可用）
            if hasattr(self._model, "HitTest"):
                # HitTest 返回点击的区域名称，如果没有点击到任何区域则返回 None
                hit_area = self._model.HitTest(norm_x, norm_y)
                self._logger.debug(f"Live2D 碰撞检测: ({x}, {y}) -> norm=({norm_x:.3f}, {norm_y:.3f}) -> hit_area={hit_area}")
                return hit_area

            # 如果模型没有 HitTest 方法，返回 None
            return None

        except Exception as e:
            self._logger.error(f"Live2D 碰撞检测失败: {e}")
            return None

    # ----------------- 鼠标事件转发（确保拖拽功能正常） -----------------

    def mousePressEvent(self, event) -> None:
        """鼠标按下事件 - 转发到父窗口以支持拖拽"""
        # 由于我们是父窗口的子组件，直接忽略事件让父窗口处理
        if self.parent():
            event.ignore()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        """鼠标移动事件 - 转发到父窗口以支持拖拽"""
        if self.parent():
            event.ignore()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        """鼠标释放事件 - 转发到父窗口以支持拖拽和点击"""
        if self.parent():
            event.ignore()
        else:
            super().mouseReleaseEvent(event)

    def enterEvent(self, event) -> None:
        """鼠标进入事件 - 设置交互状态，提高渲染频率"""
        self._is_interactive = True
        self._last_interaction_time = time.time()
        if self._throttle_mode:
            self._throttle_mode = False
            self._throttle_frame_skip = 0
            self._logger.debug("Live2D 恢复正常渲染频率（鼠标悬停）")
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        """鼠标离开事件 - 记录交互结束时间"""
        self._is_interactive = False
        self._last_interaction_time = time.time()
