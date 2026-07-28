"""
图片模板匹配爪子

提供模板图片管理和模板匹配功能，支持单模板和多模板匹配，
以及多尺度匹配。
"""

from __future__ import annotations

import os
import shutil
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Optional, TypedDict

from logger import get_module_logger

if TYPE_CHECKING:
    # 仅供静态分析：运行时通过方法内局部导入按需加载（重依赖懒加载）
    import cv2
    import numpy as np
    import pyautogui

logger = get_module_logger("template_matcher")


# 匹配方法类型
MatchMethod = Literal[
    "TM_CCOEFF_NORMED",
    "TM_CCORR_NORMED",
    "TM_SQDIFF_NORMED",
]


_METHOD_MAP: Optional[dict[MatchMethod, int]] = None


def _get_method_map() -> dict[MatchMethod, int]:
    """延迟构建 cv2 匹配方法映射（避免模块导入时加载 cv2）"""
    global _METHOD_MAP
    if _METHOD_MAP is None:
        import cv2
        _METHOD_MAP = {
            "TM_CCOEFF_NORMED": cv2.TM_CCOEFF_NORMED,
            "TM_CCORR_NORMED": cv2.TM_CCORR_NORMED,
            "TM_SQDIFF_NORMED": cv2.TM_SQDIFF_NORMED,
        }
    return _METHOD_MAP


class MatchResult(TypedDict):
    """匹配结果"""
    template_id: str
    position: tuple[int, int]  # (x, y) 左上角坐标
    center: tuple[int, int]  # (x, y) 中心坐标
    bbox: tuple[int, int, int, int]  # (xmin, ymin, xmax, ymax)
    confidence: float  # 匹置信度
    scale: float  # 缩放比例（多尺度匹配时）
    width: int  # 匹配区域宽度
    height: int  # 匹配区域高度


class TemplateInfo(TypedDict):
    """模板信息"""
    id: str
    name: str
    path: str
    width: int
    height: int
    created_at: str
    description: Optional[str]


@dataclass
class TemplateManager:
    """模板图片管理器"""

    template_dir: str = "Templates"

    def __post_init__(self) -> None:
        self._template_dir_path = Path(self.template_dir)
        self._ensure_template_dir()

    def _ensure_template_dir(self) -> None:
        """确保模板目录存在"""
        self._template_dir_path.mkdir(parents=True, exist_ok=True)
        # 创建元数据文件
        meta_file = self._template_dir_path / "templates_meta.json"
        if not meta_file.exists():
            meta_file.write_text("{}", encoding="utf-8")

    def _load_metadata(self) -> dict[str, Any]:
        """加载模板元数据"""
        meta_file = self._template_dir_path / "templates_meta.json"
        try:
            content = meta_file.read_text(encoding="utf-8")
            import json
            return json.loads(content) if content.strip() else {}
        except Exception:
            return {}

    def _save_metadata(self, metadata: dict[str, Any]) -> None:
        """保存模板元数据"""
        meta_file = self._template_dir_path / "templates_meta.json"
        import json
        meta_file.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

    def generate_template_id(self) -> str:
        """生成模板ID"""
        return f"tpl_{uuid.uuid4().hex[:8]}"

    def upload_template(
        self,
        image_path: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
    ) -> TemplateInfo:
        """上传模板图片"""
        source_path = Path(image_path)
        if not source_path.exists():
            raise FileNotFoundError(f"图片文件不存在: {image_path}")

        template_id = self.generate_template_id()
        template_path = self._template_dir_path / f"{template_id}.png"

        # 复制图片
        shutil.copy(source_path, template_path)

        # 获取图片尺寸
        import cv2
        img = cv2.imread(str(template_path))
        if img is None:
            raise ValueError(f"无法读取图片: {template_path}")
        height, width = img.shape[:2]

        # 更新元数据
        metadata = self._load_metadata()
        metadata[template_id] = {
            "name": name or template_id,
            "description": description,
            "created_at": datetime.now().isoformat(),
            "width": width,
            "height": height,
        }
        self._save_metadata(metadata)

        logger.info(f"已上传模板: {template_id}, 尺寸: {width}x{height}")

        return TemplateInfo(
            id=template_id,
            name=name or template_id,
            path=str(template_path),
            width=width,
            height=height,
            created_at=datetime.now().isoformat(),
            description=description,
        )

    def capture_template(
        self,
        region: Optional[tuple[int, int, int, int]] = None,
        name: Optional[str] = None,
        description: Optional[str] = None,
    ) -> TemplateInfo:
        """截取屏幕区域作为模板"""
        template_id = self.generate_template_id()
        template_path = self._template_dir_path / f"{template_id}.png"

        # 截取屏幕
        import pyautogui
        if region:
            x, y, w, h = region
            img = pyautogui.screenshot(region=(x, y, w, h))
        else:
            img = pyautogui.screenshot()

        # 保存图片
        img.save(template_path)

        # 获取尺寸
        width, height = img.size

        # 更新元数据
        metadata = self._load_metadata()
        metadata[template_id] = {
            "name": name or template_id,
            "description": description,
            "created_at": datetime.now().isoformat(),
            "width": width,
            "height": height,
            "source_region": region,
        }
        self._save_metadata(metadata)

        logger.info(f"已截取模板: {template_id}, 尺寸: {width}x{height}")

        return TemplateInfo(
            id=template_id,
            name=name or template_id,
            path=str(template_path),
            width=width,
            height=height,
            created_at=datetime.now().isoformat(),
            description=description,
        )

    def delete_template(self, template_id: str) -> bool:
        """删除模板图片"""
        template_path = self._template_dir_path / f"{template_id}.png"
        if not template_path.exists():
            logger.warning(f"模板不存在: {template_id}")
            return False

        try:
            template_path.unlink()
            # 删除元数据
            metadata = self._load_metadata()
            if template_id in metadata:
                del metadata[template_id]
                self._save_metadata(metadata)
            logger.info(f"已删除模板: {template_id}")
            return True
        except Exception as e:
            logger.error(f"删除模板失败: {e}")
            return False

    def get_template(self, template_id: str) -> Optional[TemplateInfo]:
        """获取模板信息"""
        template_path = self._template_dir_path / f"{template_id}.png"
        if not template_path.exists():
            return None

        metadata = self._load_metadata()
        info = metadata.get(template_id, {})

        import cv2
        img = cv2.imread(str(template_path))
        if img is None:
            return None
        height, width = img.shape[:2]

        return TemplateInfo(
            id=template_id,
            name=info.get("name", template_id),
            path=str(template_path),
            width=width,
            height=height,
            created_at=info.get("created_at", ""),
            description=info.get("description"),
        )

    def list_templates(self) -> list[TemplateInfo]:
        """列出所有模板图片"""
        templates = []
        metadata = self._load_metadata()

        for file in self._template_dir_path.iterdir():
            if file.suffix.lower() == ".png" and file.stem.startswith("tpl_"):
                template_id = file.stem
                info = metadata.get(template_id, {})

                import cv2
                img = cv2.imread(str(file))
                if img is not None:
                    height, width = img.shape[:2]
                    templates.append(TemplateInfo(
                        id=template_id,
                        name=info.get("name", template_id),
                        path=str(file),
                        width=width,
                        height=height,
                        created_at=info.get("created_at", ""),
                        description=info.get("description"),
                    ))

        return templates

    def update_template_info(
        self,
        template_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
    ) -> bool:
        """更新模板信息"""
        metadata = self._load_metadata()
        if template_id not in metadata:
            return False

        if name is not None:
            metadata[template_id]["name"] = name
        if description is not None:
            metadata[template_id]["description"] = description

        self._save_metadata(metadata)
        return True


@dataclass
class TemplateMatcher:
    """模板匹配器"""

    template_manager: TemplateManager = field(default_factory=TemplateManager)

    def capture_screen(self) -> np.ndarray:
        """截取屏幕"""
        import cv2
        import numpy as np
        import pyautogui
        img = pyautogui.screenshot()
        return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)

    def capture_screen_region(
        self,
        region: tuple[int, int, int, int],
    ) -> np.ndarray:
        """截取屏幕指定区域"""
        import cv2
        import numpy as np
        import pyautogui
        x, y, w, h = region
        img = pyautogui.screenshot(region=(x, y, w, h))
        return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)

    def load_template(self, template_id: str) -> np.ndarray:
        """加载模板图片"""
        import cv2
        template_info = self.template_manager.get_template(template_id)
        if template_info is None:
            raise FileNotFoundError(f"模板不存在: {template_id}")

        template = cv2.imread(template_info["path"])
        if template is None:
            raise ValueError(f"无法读取模板图片: {template_info['path']}")

        return template

    def match_template(
        self,
        template_id: str,
        threshold: float = 0.8,
        multi_match: bool = False,
        method: MatchMethod = "TM_CCOEFF_NORMED",
        screen_region: Optional[tuple[int, int, int, int]] = None,
    ) -> list[MatchResult]:
        """模板匹配"""
        start_time = time.time()

        # 加载模板
        template = self.load_template(template_id)
        th, tw = template.shape[:2]

        # 截取屏幕
        if screen_region:
            screen = self.capture_screen_region(screen_region)
            offset_x, offset_y = screen_region[0], screen_region[1]
        else:
            screen = self.capture_screen()
            offset_x, offset_y = 0, 0

        # 模板匹配
        import cv2
        result = cv2.matchTemplate(screen, template, _get_method_map()[method])

        if multi_match:
            # 多模板匹配
            locations = self._find_all_matches(result, threshold, th, tw)
        else:
            # 单模板匹配
            locations = self._find_best_match(result, method, threshold, th, tw)

        # 转换为MatchResult格式
        results = []
        for loc in locations:
            x, y = loc["position"]
            confidence = loc["confidence"]

            # 计算实际坐标（考虑偏移）
            actual_x = x + offset_x
            actual_y = y + offset_y

            results.append(MatchResult(
                template_id=template_id,
                position=(actual_x, actual_y),
                center=(actual_x + tw // 2, actual_y + th // 2),
                bbox=(actual_x, actual_y, actual_x + tw, actual_y + th),
                confidence=confidence,
                scale=1.0,
                width=tw,
                height=th,
            ))

        elapsed_ms = int((time.time() - start_time) * 1000)
        logger.debug(f"模板匹配完成: {template_id}, 找到 {len(results)} 个匹配, 耗时 {elapsed_ms}ms")

        return results

    def _find_best_match(
        self,
        result: np.ndarray,
        method: MatchMethod,
        threshold: float,
        template_height: int,
        template_width: int,
    ) -> list[dict[str, Any]]:
        """找到最佳匹配"""
        import cv2
        min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)

        if method == "TM_SQDIFF_NORMED":
            score = 1.0 - min_val
            top_left = min_loc
        else:
            score = max_val
            top_left = max_loc

        if score < threshold:
            return []

        return [{"position": top_left, "confidence": score}]

    def _find_all_matches(
        self,
        result: np.ndarray,
        threshold: float,
        template_height: int,
        template_width: int,
    ) -> list[dict[str, Any]]:
        """找到所有匹配"""
        import cv2
        locations = []
        result_copy = result.copy()

        while True:
            min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result_copy)

            if max_val < threshold:
                break

            locations.append({"position": max_loc, "confidence": max_val})

            # 标记已匹配区域，避免重复匹配
            x, y = max_loc
            cv2.rectangle(
                result_copy,
                (x, y),
                (x + template_width, y + template_height),
                0,
                -1,
            )

        return locations

    def match_multi_scale(
        self,
        template_id: str,
        scales: list[float] = [0.5, 0.75, 1.0, 1.25, 1.5],
        threshold: float = 0.8,
        method: MatchMethod = "TM_CCOEFF_NORMED",
        screen_region: Optional[tuple[int, int, int, int]] = None,
    ) -> list[MatchResult]:
        """多尺度模板匹配"""
        import cv2
        start_time = time.time()

        # 加载原始模板
        template = self.load_template(template_id)
        original_h, original_w = template.shape[:2]

        # 截取屏幕
        if screen_region:
            screen = self.capture_screen_region(screen_region)
            offset_x, offset_y = screen_region[0], screen_region[1]
        else:
            screen = self.capture_screen()
            offset_x, offset_y = 0, 0

        results = []
        best_confidence = 0.0
        best_result = None

        for scale in scales:
            # 缩放模板
            scaled_w = int(original_w * scale)
            scaled_h = int(original_h * scale)

            if scaled_w <= 0 or scaled_h <= 0:
                continue

            scaled_template = cv2.resize(template, (scaled_w, scaled_h))

            # 检查模板是否大于屏幕
            sh, sw = screen.shape[:2]
            if scaled_h > sh or scaled_w > sw:
                continue

            # 模板匹配
            result = cv2.matchTemplate(screen, scaled_template, _get_method_map()[method])
            min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)

            if method == "TM_SQDIFF_NORMED":
                score = 1.0 - min_val
                top_left = min_loc
            else:
                score = max_val
                top_left = max_loc

            if score >= threshold and score > best_confidence:
                best_confidence = score
                x, y = top_left
                actual_x = x + offset_x
                actual_y = y + offset_y

                best_result = MatchResult(
                    template_id=template_id,
                    position=(actual_x, actual_y),
                    center=(actual_x + scaled_w // 2, actual_y + scaled_h // 2),
                    bbox=(actual_x, actual_y, actual_x + scaled_w, actual_y + scaled_h),
                    confidence=score,
                    scale=scale,
                    width=scaled_w,
                    height=scaled_h,
                )

        if best_result:
            results.append(best_result)

        elapsed_ms = int((time.time() - start_time) * 1000)
        logger.debug(f"多尺度匹配完成: {template_id}, 最佳置信度 {best_confidence:.3f}, 耗时 {elapsed_ms}ms")

        return results

    def click_template(
        self,
        template_id: str,
        threshold: float = 0.8,
        click_position: Literal["center", "top_left"] = "center",
        offset: tuple[int, int] = (0, 0),
    ) -> dict[str, Any]:
        """点击模板匹配位置"""
        results = self.match_template(template_id, threshold=threshold)

        if not results:
            return {
                "success": False,
                "error": f"未找到模板 '{template_id}'",
                "template_id": template_id,
            }

        # 选择第一个匹配
        match = results[0]

        if click_position == "center":
            x, y = match["center"]
        else:
            x, y = match["position"]

        # 应用偏移
        x += offset[0]
        y += offset[1]

        # 执行点击
        import pyautogui
        try:
            pyautogui.click(x, y)
            logger.info(f"已点击模板 '{template_id}' 位置: ({x}, {y})")
            return {
                "success": True,
                "template_id": template_id,
                "click_position": (x, y),
                "confidence": match["confidence"],
                "bbox": match["bbox"],
            }
        except Exception as e:
            logger.error(f"点击失败: {e}")
            return {
                "success": False,
                "error": str(e),
                "template_id": template_id,
            }

    def verify_template_exists(
        self,
        template_id: str,
        threshold: float = 0.8,
    ) -> dict[str, Any]:
        """验证模板是否存在于屏幕上"""
        results = self.match_template(template_id, threshold=threshold)

        if results:
            return {
                "exists": True,
                "template_id": template_id,
                "confidence": results[0]["confidence"],
                "position": results[0]["position"],
            }
        else:
            return {
                "exists": False,
                "template_id": template_id,
                "confidence": 0.0,
                "position": None,
            }


# 单例实例
_template_manager: Optional[TemplateManager] = None
_template_matcher: Optional[TemplateMatcher] = None


def get_template_manager() -> TemplateManager:
    """获取模板管理器单例"""
    global _template_manager
    if _template_manager is None:
        # 使用默认模板目录
        from resource_path import paths
        template_dir = str(paths.get_data_dir() / "Templates")
        _template_manager = TemplateManager(template_dir=template_dir)
    return _template_manager


def get_template_matcher() -> TemplateMatcher:
    """获取模板匹配器单例"""
    global _template_matcher
    if _template_matcher is None:
        _template_matcher = TemplateMatcher(template_manager=get_template_manager())
    return _template_matcher


def match_template(
    template_id: str,
    threshold: float = 0.8,
    multi_match: bool = False,
) -> list[MatchResult]:
    """便捷函数：模板匹配"""
    return get_template_matcher().match_template(template_id, threshold, multi_match)


def click_template(
    template_id: str,
    threshold: float = 0.8,
) -> dict[str, Any]:
    """便捷函数：点击模板"""
    return get_template_matcher().click_template(template_id, threshold)


def upload_template(image_path: str, name: Optional[str] = None) -> TemplateInfo:
    """便捷函数：上传模板"""
    return get_template_manager().upload_template(image_path, name)


def list_templates() -> list[TemplateInfo]:
    """便捷函数：列出模板"""
    return get_template_manager().list_templates()