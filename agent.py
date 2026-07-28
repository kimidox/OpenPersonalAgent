import json
import re
import base64
from pathlib import Path

from openai import OpenAI
from openai.types.chat import ChatCompletionMessage

from executor import Executor
import config
from llm import get_chat_model






def build_system_prompt() -> str:
    step = config.SCREENSHOT_GRID_STEP_PX
    return f"""你是一个Windows桌面自动化助手。你已经收到屏幕截图，请直接分析内容并调用指定的函数完成操作。必须使用提供的functions列表中的函数。
# 坐标系（必须遵守）
截屏上已叠加与屏幕像素对齐的网格，每格为 {step}×{step} 像素，原点为左上角。调用 click、double_click、right_click、move_to 以及带位置的 scroll 时：参数 x 为列索引 gx（从左向右 0,1,2…），参数 y 为行索引 gy（从上向下 0,1,2…），与图中网格划分一致：上沿数字为列号 gx（在该列水平居中），左侧数字为行号 gy（在该行垂直居中）。读 gy 时看目标所在横条左侧居中的数，不要与顶部的 gx 数字条混淆。。
# 行为逻辑链路
1.如果是刚收到任务内容和截屏，请先分析图片和任务内容，计划下一步指令来完成任务。
2.如果是收到上一步指令执行结果和新的截屏，请思考思考任务是否完成，如果没有完成请继续思考下一步指令来完成任务。
3.如果你执行完指令，且任务任务已经完成，请发送获取最新截屏的指令，得到最新的截屏后再次思考是否符合最初的任务要求，如果确认已经完成，就发送任务完成指令；如果你认为任务没有完成，请执行2-3步。
"""

class Agent:
    def __init__(self, work_dir: str):
        self.work_dir = work_dir
        self.executor = Executor(work_dir)
        self.conversation_history = []
        self.iteration = 0
        self.max_iterations = config.MAX_ITERATIONS

    
    def run(self, task: str, log_callback=None) -> str:
        model = get_chat_model()

        # Step 1: Preliminary model pass to decide if a screenshot is needed
        current_screenshot = self.executor.screenshot()
        pre_actions = model.analyze_with_image(
            system_prompt=build_system_prompt(),
            user_prompt=f"任务: {task}",
            image_path=current_screenshot,
            executor=self.executor,
            log_callback=log_callback,
        )
        if log_callback:
            log_callback(str(pre_actions), "response")
        return "完成"
