"""
core_vision.py — Tầng nhận diện hình ảnh của AI Game Agent
============================================================
Nền tảng: PC (Windows DirectX game)
Chiến lược 3 tầng theo tốc độ/chi phí:
  Tầng 1: mss + OpenCV template matching  → 0 token, ~5ms   (nút cố định)
  Tầng 2: RapidOCR                         → 0 token, ~20ms  (số mana/HP)
  Tầng 3: Gemini Vision (multimodal)       → tốn token, ~500ms (exception)

Yêu cầu cài đặt:
    pip install mss opencv-python rapidocr-onnxruntime
"""

import os
import re
import json
import time
import random
import logging
import unicodedata
from pathlib import Path
from typing import Optional, Tuple, List, Dict

import cv2
import mss
import numpy as np
from dotenv import load_dotenv
from ai_client import UnifiedAIClient
from window_manager import get_game_client_geometry


def normalize_text(text: str) -> str:
    """Loại bỏ dấu tiếng Việt, đưa về chữ thường và chuẩn hóa ký tự đ/d."""
    if not text:
        return ""
    text = unicodedata.normalize('NFD', text)
    text = ''.join(c for c in text if unicodedata.category(c) != 'Mn')
    return text.lower().replace('đ', 'd').replace('Đ', 'd').strip()


load_dotenv()
logger = logging.getLogger(__name__)

# ── Đường dẫn gốc dự án ──────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent.parent


# ══════════════════════════════════════════════════════════════════════════════
# ScreenCapture — Tầng 0: chụp màn hình bằng mss (thay pyautogui)
# ══════════════════════════════════════════════════════════════════════════════

class ScreenCapture:
    """
    Wrapper quanh mss để chụp màn hình nhanh.
    Hỗ trợ chụp toàn màn hình hoặc vùng crop cụ thể.
    """

    def __init__(self, region: Optional[dict] = None):
        """
        Args:
            region: dict với keys {top, left, width, height} hoặc None để chụp toàn màn
        """
        # Đảm bảo thread được gắn vào InputDesktop của Windows để tránh lỗi BitBlt
        try:
            import ctypes
            user32 = ctypes.windll.user32
            hdesk = user32.OpenInputDesktop(0, False, 0x01FF)
            if hdesk:
                user32.SetThreadDesktop(hdesk)
        except Exception:
            pass

        self._sct = mss.mss()
        self.region = region  # None = toàn màn hình

    def grab(self) -> np.ndarray:
        """Chụp màn hình, trả về numpy array BGR (tương thích OpenCV)."""
        if self.region and all(v is not None for v in self.region.values()):
            monitor = self.region
        else:
            monitor = self._sct.monitors[1]  # monitor chính

        screenshot = self._sct.grab(monitor)
        frame = np.array(screenshot)
        return cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)

    def close(self):
        self._sct.close()


# ══════════════════════════════════════════════════════════════════════════════
# TemplateMatcher — Tầng 1: OpenCV template matching
# ══════════════════════════════════════════════════════════════════════════════

class TemplateMatcher:
    """
    Tìm kiếm hình ảnh con (template) trong ảnh chụp màn hình.
    Template được cache trong RAM sau lần đọc đầu tiên.
    """

    def __init__(self, threshold: float = 0.82):
        self.threshold = threshold
        self._cache: dict[str, np.ndarray] = {}

    def _load_template(self, template_path: str) -> Optional[np.ndarray]:
        """Load và cache template từ đường dẫn tuyệt đối."""
        if template_path in self._cache:
            return self._cache[template_path]

        abs_path = PROJECT_ROOT / template_path
        if not abs_path.exists():
            logger.warning("[VISION] Template khong ton tai: %s", abs_path)
            return None

        tpl = cv2.imread(str(abs_path), cv2.IMREAD_COLOR)
        if tpl is None:
            logger.warning("[VISION] Khong doc duoc anh: %s", abs_path)
            return None

        self._cache[template_path] = tpl
        return tpl

    def find(
        self,
        frame: np.ndarray,
        template_path: str,
        threshold: Optional[float] = None,
    ) -> Optional[Tuple[int, int, int, int]]:
        """
        Tìm template trong frame.

        Returns:
            (x, y, w, h) tọa độ góc trên-trái của vùng khớp, hoặc None nếu không tìm thấy.
            x, y là tọa độ tuyệt đối trên màn hình (đã cộng với offset region nếu có).
        """
        tpl = self._load_template(template_path)
        if tpl is None:
            return None

        thresh = threshold or self.threshold
        result = cv2.matchTemplate(frame, tpl, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)

        if max_val >= thresh:
            h, w = tpl.shape[:2]
            x, y = max_loc
            return (x, y, w, h)

        return None

    def find_center(
        self,
        frame: np.ndarray,
        template_path: str,
        threshold: Optional[float] = None,
    ) -> Optional[Tuple[int, int]]:
        """
        Tìm template và trả về tọa độ tâm (cx, cy).

        Returns:
            (cx, cy) tọa độ tâm, hoặc None.
        """
        match = self.find(frame, template_path, threshold)
        if match is None:
            return None
        x, y, w, h = match
        return (x + w // 2, y + h // 2)

    def is_visible(
        self,
        frame: np.ndarray,
        template_path: str,
        threshold: Optional[float] = None,
    ) -> bool:
        """Kiểm tra template có xuất hiện trên màn hình không."""
        return self.find(frame, template_path, threshold) is not None

    def find_all_centers(
        self,
        frame: np.ndarray,
        template_path: str,
        min_distance_px: int = 30,
    ) -> list[Tuple[int, int]]:
        """Mọi vị trí khớp (đã gộp các điểm sát nhau), sắp xếp từ trên xuống."""
        tpl = self._load_template(template_path)
        if tpl is None:
            return []

        result = cv2.matchTemplate(frame, tpl, cv2.TM_CCOEFF_NORMED)
        ys, xs = np.where(result >= self.threshold)
        h, w = tpl.shape[:2]
        centers: list[Tuple[int, int]] = []
        for x, y in sorted(zip(xs.tolist(), ys.tolist()), key=lambda p: -result[p[1], p[0]]):
            cx, cy = x + w // 2, y + h // 2
            if all(abs(cx - ox) > min_distance_px or abs(cy - oy) > min_distance_px for ox, oy in centers):
                centers.append((cx, cy))
        return sorted(centers, key=lambda c: c[1])


# ══════════════════════════════════════════════════════════════════════════════
# OCRReader — Tầng 2: RapidOCR đọc số (mana, HP, lượt)
# ══════════════════════════════════════════════════════════════════════════════

class OCRReader:
    """
    Đọc văn bản số từ vùng ảnh cắt ra bằng RapidOCR.
    Lazy-load engine để không chiếm RAM khi không cần.
    """

    def __init__(self):
        self._engine = None

    def _get_engine(self):
        if self._engine is None:
            try:
                from rapidocr_onnxruntime import RapidOCR
                self._engine = RapidOCR()
                logger.info("[VISION] RapidOCR engine khoi dong thanh cong.")
            except ImportError:
                logger.warning("[VISION] RapidOCR chua duoc cai dat.")
                self._engine = None
        return self._engine

    def read_number(self, frame: np.ndarray, region: dict) -> Optional[int]:
        """
        Đọc số nguyên từ vùng crop trong frame.

        Args:
            frame: Ảnh gốc (full screenshot)
            region: dict {top, left, width, height} — vùng cần đọc

        Returns:
            Số nguyên đọc được, hoặc None nếu thất bại.
        """
        engine = self._get_engine()
        if engine is None:
            return None

        if any(v is None for v in region.values()):
            return None  # Region chưa được cấu hình

        top, left, width, height = region['top'], region['left'], region['width'], region['height']
        crop = frame[top:top+height, left:left+width]

        result, _ = engine(crop)
        if result is None:
            return None

        # Gộp tất cả text, lọc lấy số
        full_text = ''.join([line[1] for line in result])
        digits = ''.join(filter(str.isdigit, full_text))

        return int(digits) if digits else None

    def read_fraction(self, crop: np.ndarray) -> Optional[Tuple[int, int]]:
        """Đọc chuỗi dạng 'hiện tại/tối đa' (vd '207/288') → (207, 288)."""
        engine = self._get_engine()
        if engine is None or crop.size == 0:
            return None

        # 1. Thử đọc trực tiếp
        result, _ = engine(crop)
        text = ''.join(line[1] for line in result).replace(' ', '') if result else ''
        match = re.search(r'(\d+)\s*/\s*(\d+)', text)

        # 2. Nếu không ra, tiền xử lý: grayscale -> resize 2x -> binary threshold
        if match is None:
            gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if len(crop.shape) == 3 else crop
            resized = cv2.resize(gray, (0, 0), fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
            _, binarized = cv2.threshold(resized, 180, 255, cv2.THRESH_BINARY)
            result_bin, _ = engine(binarized)
            if result_bin:
                text = ''.join(line[1] for line in result_bin).replace(' ', '')
                match = re.search(r'(\d+)\s*/\s*(\d+)', text)

        if match is None:
            logger.debug("OCR không thấy dạng a/b trong '%s'", text)
            return None
        return int(match.group(1)), int(match.group(2))

    def find_all_text(self, frame: np.ndarray, min_score: float = 0.5) -> List[Dict]:
        """
        Nhận diện toàn bộ text trên frame bằng RapidOCR.
        Trả về danh sách dict: [{'text': str, 'norm': str, 'score': float, 'center': (cx, cy), 'box': box}]
        """
        engine = self._get_engine()
        if engine is None or frame is None or frame.size == 0:
            return []

        result, _ = engine(frame)
        if not result:
            return []

        items = []
        for box, text, score in result:
            if float(score) >= min_score:
                cx = int((box[0][0] + box[2][0]) / 2)
                cy = int((box[0][1] + box[2][1]) / 2)
                raw_text = text.strip()
                items.append({
                    'text': raw_text,
                    'norm': normalize_text(raw_text),
                    'score': float(score),
                    'center': (cx, cy),
                    'box': box
                })
        return items

    def find_keywords(self, frame: np.ndarray, keywords: list[str] | str, min_score: float = 0.5) -> List[Dict]:
        """
        Tìm tất cả các mục text khớp với danh sách từ khóa (theo dạng contains trên chuỗi đã normalize).
        """
        if isinstance(keywords, str):
            keywords = [keywords]
        norm_kws = [normalize_text(kw) for kw in keywords if kw]

        all_items = self.find_all_text(frame, min_score)
        matched = []
        for item in all_items:
            norm_item = item['norm']
            if any(kw in norm_item for kw in norm_kws):
                matched.append(item)
        return matched

    def find_keyword(self, frame: np.ndarray, keywords: list[str] | str, min_score: float = 0.5) -> Optional[Tuple[int, int]]:
        """Trả về tâm (cx, cy) của từ khóa đầu tiên tìm thấy."""
        matches = self.find_keywords(frame, keywords, min_score)
        if matches:
            return matches[0]['center']
        return None



# ══════════════════════════════════════════════════════════════════════════════
# GeminiVision / MultimodalVision — Tầng 3: Multimodal (Gemini -> Qwen2.5-VL Fallback)
# ══════════════════════════════════════════════════════════════════════════════

class GeminiVision:
    """
    Tầng 3 Vision: Phân tích màn hình & UI Grounding.
    Ưu tiên Gemini 3.8 Flash, tự động fallback sang Qwen2.5-VL (Ollama / OpenRouter).
    CHỈ dùng khi Tầng 1 và 2 không xác định được trạng thái.
    """

    ANALYZE_PROMPT = (
        "Đây là ảnh chụp màn hình game Ark Re-Code. "
        "Hãy mô tả ngắn gọn: màn hình đang hiển thị gì (lobby, battle, victory, popup, error...), "
        "và nếu có popup/dialog cần đóng, tọa độ tương đối (x%, y%) của nút cần bấm là bao nhiêu? "
        "Trả lời dạng JSON duy nhất: {\"screen_type\": \"...\", \"action\": \"click|wait|none\", \"click_x_pct\": 0.0, \"click_y_pct\": 0.0, \"description\": \"...\"}"
    )

    def __init__(self):
        self._ai = UnifiedAIClient()

    def analyze_screen(self, frame: np.ndarray) -> dict:
        """Phân tích màn hình game bằng VLM (Gemini -> Qwen2.5-VL fallback)."""
        result = self._ai.generate_json_vision(frame, self.ANALYZE_PROMPT)
        if "action" not in result:
            result["action"] = "none"
        return result

    def locate_element(self, frame: np.ndarray, element_description: str) -> Optional[Tuple[float, float]]:
        """Hỏi VLM vị trí phần tử UI; trả về (x_pct, y_pct) trên toàn frame hoặc None."""
        prompt = (
            "Ảnh chụp desktop có cửa sổ game Ark Re-Code. "
            f"Tìm phần tử: {element_description}. "
            "Trả JSON duy nhất theo định dạng: {\"found\": true, \"x_pct\": 0.0, \"y_pct\": 0.0} với tọa độ tâm "
            "tính theo tỉ lệ 0.0 đến 1.0 của TOÀN BỘ ảnh. Nếu không tìm thấy, trả về {\"found\": false}."
        )
        data = self._ai.generate_json_vision(frame, prompt)
        if not data.get('found'):
            return None
        try:
            return float(data['x_pct']), float(data['y_pct'])
        except (KeyError, TypeError, ValueError):
            return None


MultimodalVision = GeminiVision


# ══════════════════════════════════════════════════════════════════════════════
# GameVision — Facade gộp cả 3 tầng, dùng trong FSM
# ══════════════════════════════════════════════════════════════════════════════

class GameVision:
    """
    Interface chính cho FSM sử dụng.
    Tự động chọn tầng phù hợp (nhanh/rẻ trước, chậm/tốn sau).
    """

    def __init__(self, game_config: dict):
        self.cfg = game_config
        region_cfg = game_config.get('screen_region', {})
        # Chỉ dùng region nếu tất cả giá trị đều được điền
        valid_region = (
            region_cfg if all(v is not None for v in region_cfg.values())
            else None
        )
        self.capture = ScreenCapture(region=valid_region)
        self.matcher = TemplateMatcher(threshold=game_config.get('match_threshold', 0.82))
        self.ocr = OCRReader()
        self.gemini = GeminiVision()
        self._last_frame: Optional[np.ndarray] = None

    def grab_frame(self) -> np.ndarray:
        """Chụp frame mới và cache lại."""
        self._last_frame = self.capture.grab()
        return self._last_frame

    @property
    def last_frame(self) -> Optional[np.ndarray]:
        return self._last_frame

    # ── Các hàm nhận diện trạng thái ──────────────────────────────────────

    def is_on_screen(self, template_key: str) -> bool:
        """Kiểm tra template (theo key trong config) có trên màn hình không."""
        frame = self.grab_frame()
        path = self.cfg['templates'].get(template_key)
        if not path:
            print(f"[VISION] ⚠️  Không có template key: {template_key}")
            return False
        return self.matcher.is_visible(frame, path)

    def find_on_screen(self, template_key: str) -> Optional[Tuple[int, int]]:
        """Tìm tâm của template trên màn hình. Trả về (cx, cy) hoặc None."""
        frame = self.grab_frame()
        path = self.cfg['templates'].get(template_key)
        if not path:
            return None
        return self.matcher.find_center(frame, path)

    def read_mana(self) -> Optional[int]:
        """Đọc số mana hiện tại bằng OCR."""
        frame = self.grab_frame()
        mana_region = self.cfg.get('ocr_regions', {}).get('mana_value', {})
        return self.ocr.read_number(frame, mana_region)

    def find_in_frame(self, frame: np.ndarray, template_key: str) -> Optional[Tuple[int, int]]:
        """Tìm tâm template trong frame đã chụp sẵn (tránh chụp lại nhiều lần mỗi tick)."""
        path = self.cfg['templates'].get(template_key)
        if not path:
            logger.warning("Không có template key: %s", template_key)
            return None
        return self.matcher.find_center(frame, path)

    def grab_game_frame(self) -> Tuple[np.ndarray, Tuple[int, int]]:
        """
        Chụp và crop chuẩn xác theo vùng Client của cửa sổ game Ark Re-Code.
        Trả về (client_frame, (origin_x, origin_y)).
        Nếu không lấy được cửa sổ, fallback về toàn bộ desktop frame và (0, 0).
        """
        desktop = self.grab_frame()
        geom = get_game_client_geometry()
        if geom:
            ox, oy, w, h = geom
            dh, dw = desktop.shape[:2]
            ox = max(0, min(ox, dw))
            oy = max(0, min(oy, dh))
            w = min(w, dw - ox)
            h = min(h, dh - oy)
            if w > 100 and h > 100:
                return desktop[oy:oy+h, ox:ox+w], (ox, oy)
        return desktop, (0, 0)

    def find_text_on_game(self, keywords: list[str] | str, frame: Optional[np.ndarray] = None, origin: Optional[Tuple[int, int]] = None, min_score: float = 0.5) -> Optional[Tuple[int, int]]:
        """
        Tìm từ khóa trong game và trả về tọa độ desktop tuyệt đối (để click trực tiếp).
        """
        if frame is None or origin is None:
            f, orig = self.grab_game_frame()
        else:
            f, orig = frame, origin

        center = self.ocr.find_keyword(f, keywords, min_score)
        if center:
            return (orig[0] + center[0], orig[1] + center[1])
        return None

    def find_all_texts_on_game(self, keywords: list[str] | str, frame: Optional[np.ndarray] = None, origin: Optional[Tuple[int, int]] = None, min_score: float = 0.5) -> List[Tuple[int, int]]:
        """Tìm tất cả các tọa độ desktop của từ khóa."""
        if frame is None or origin is None:
            f, orig = self.grab_game_frame()
        else:
            f, orig = frame, origin

        matches = self.ocr.find_keywords(f, keywords, min_score)
        return [(orig[0] + m['center'][0], orig[1] + m['center'][1]) for m in matches]

    def has_text_on_game(self, keywords: list[str] | str, frame: Optional[np.ndarray] = None, min_score: float = 0.5) -> bool:
        """Kiểm tra sự xuất hiện của từ khóa trong vùng game."""
        f = frame if frame is not None else self.grab_game_frame()[0]
        return self.ocr.find_keyword(f, keywords, min_score) is not None

    def read_energy(self, frame: Optional[np.ndarray] = None) -> Optional[Tuple[int, int]]:
        """
        Đọc năng lượng 'hiện tại/tối đa' trên HUD.
        Ưu tiên OCR tìm chuỗi dạng 'xxx/yyy' ở thanh trạng thái đỉnh màn hình (nhanh & không phụ thuộc template).
        Fallback sang template matching energy_icon nếu cần.
        """
        client_f, _ = self.grab_game_frame() if frame is None else (frame, (0, 0))

        # 1. Quét OCR dải trên cùng của màn hình (chiều cao 150px)
        top_bar = client_f[:min(150, client_f.shape[0]), :]
        top_items = self.ocr.find_all_text(top_bar, min_score=0.6)
        for item in top_items:
            text = item['text'].replace(' ', '')
            if '/' in text:
                parts = text.split('/')
                if len(parts) >= 2 and parts[-1].isdigit():
                    max_e = int(parts[-1])
                    if 50 <= max_e <= 1000:
                        cur_str = parts[-2]
                        if cur_str and any(c.isdigit() for c in cur_str):
                            digits_only = ''.join(c for c in cur_str if c.isdigit())
                            # Năng lượng thường tối đa 3-4 chữ số
                            cur_e = int(digits_only[-3:]) if len(digits_only) > 3 else int(digits_only)
                            return cur_e, max_e


        # 2. Fallback sang template icon truyền thống
        icon_path = self.cfg.get('templates', {}).get('energy_icon')
        offset = self.cfg.get('ocr_regions', {}).get('energy_from_icon')
        if icon_path and offset:
            icon = self.matcher.find(client_f, icon_path)
            if icon is not None:
                icon_x, icon_y, icon_w, _ = icon
                left = icon_x + icon_w + offset['dx']
                top = max(icon_y + offset['dy'], 0)
                crop = client_f[top:top + offset['height'], left:left + offset['width']]
                return self.ocr.read_fraction(crop)

        return None


    def analyze_stuck_screen(self) -> dict:
        """Gọi Gemini Vision để phân tích khi FSM bị kẹt."""
        frame = self._last_frame if self._last_frame is not None else self.grab_frame()
        logger.info("[VISION] Dang goi Multimodal Vision de phan tich man hinh ket...")
        return self.gemini.analyze_screen(frame)

    def close(self):
        self.capture.close()


# ══════════════════════════════════════════════════════════════════════════════
# Factory function
# ══════════════════════════════════════════════════════════════════════════════

def create_vision(game_target: str) -> GameVision:
    """
    Tạo GameVision instance từ tên game.

    Args:
        game_target: Tên thư mục game (vd: 'ark_recode')

    Returns:
        GameVision đã được cấu hình.
    """
    config_path = PROJECT_ROOT / 'games' / game_target / 'config.json'
    if not config_path.exists():
        raise FileNotFoundError(f"Không tìm thấy config: {config_path}")

    with open(config_path, 'r', encoding='utf-8') as f:
        game_config = json.load(f)

    return GameVision(game_config)


# ══════════════════════════════════════════════════════════════════════════════
# Test thủ công
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=== Test core_vision.py ===")
    vision = create_vision('ark_recode')

    print("\n[1] Chụp màn hình...")
    frame = vision.grab_frame()
    print(f"    Kích thước frame: {frame.shape[1]}x{frame.shape[0]} px")

    # Lưu ảnh test để kiểm tra
    test_path = PROJECT_ROOT / 'ark_recode_data' / '_test_capture.png'
    cv2.imwrite(str(test_path), frame)
    print(f"    Đã lưu ảnh test: {test_path}")

    print("\n[2] Đọc mana (OCR)...")
    mana = vision.read_mana()
    print(f"    Mana đọc được: {mana} (None = OCR region chưa cấu hình)")

    vision.close()
    print("\n✅ Test xong!")
