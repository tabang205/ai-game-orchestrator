"""
fast_snatcher.py — Động cơ theo dõi và giật Túi Lộc siêu tốc (Top Heroes).
Tuân thủ tiêu chuẩn Clean Code, logging chuẩn hóa ISO 8601 và thuật toán xác thực 3 tầng:
  1. Phân tích nền thẻ Cam Vàng Ấm (Amber Card) với tỷ lệ hình học chuẩn (2.0 <= cw/ch <= 5.5).
     Loại bỏ hoàn toàn các thanh tiêu đề mỏng như 'Vua Lượn Mây' hay 'Trang trại tôi' (cw/ch > 7.0).
  2. Xác thực sự hiện diện của Túi Quà Hồng Đào (Pink Pouch) bên trong thân thẻ.
  3. Xác thực viên Kim Cương Lam (Cyan Gem) đính kèm.
"""

import ctypes
import json
import logging
import time
from pathlib import Path
from typing import Dict, Optional, Tuple

import cv2
import mss
import numpy as np

try:
    import win32gui
    import win32con
    _HAS_WIN32 = True
except ImportError:
    _HAS_WIN32 = False

# Đảm bảo Windows DPI Awareness
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

logger = logging.getLogger("Core.Snatcher")

MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
MK_LBUTTON = 0x0001


class FastInput:
    """Mô phỏng click chuột và chạm cảm ứng trực tiếp qua Windows API chuẩn xác."""

    def __init__(self, hwnd: Optional[int] = None):
        self.hwnd = hwnd
        self._user32 = ctypes.windll.user32

    def click_screen(self, screen_x: int, screen_y: int, hold_sec: float = 0.035):
        """Di chuyển và nhấp giữ chuột với thời gian hold chuẩn (~35ms) để game nhận diện."""
        self._user32.SetCursorPos(int(screen_x), int(screen_y))
        self._user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        if hold_sec > 0:
            time.sleep(hold_sec)
        self._user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)

    def click_window(self, client_x: int, client_y: int, hold_sec: float = 0.035):
        """Click trực tiếp vào hàng đợi tin nhắn của cửa sổ game qua PostMessage."""
        if not self.hwnd:
            return
        l_param = (int(client_y) << 16) | (int(client_x) & 0xFFFF)
        self._user32.PostMessageW(self.hwnd, WM_LBUTTONDOWN, MK_LBUTTON, l_param)
        if hold_sec > 0:
            time.sleep(hold_sec)
        self._user32.PostMessageW(self.hwnd, WM_LBUTTONUP, 0, l_param)


class FastCapture:
    """Chụp khung hình siêu tốc chỉ trong phạm vi bounding box ROI."""

    def __init__(self):
        self._attach_desktop()
        self._sct = mss.MSS() if hasattr(mss, "MSS") else mss.mss()

    @staticmethod
    def _attach_desktop():
        try:
            user32 = ctypes.windll.user32
            hdesk = user32.OpenInputDesktop(0, False, 0x01FF)
            if hdesk:
                user32.SetThreadDesktop(hdesk)
        except Exception:
            pass

    def grab_roi(self, top: int, left: int, width: int, height: int) -> np.ndarray:
        """Chụp vùng chữ nhật ROI trả về ảnh BGR OpenCV."""
        monitor = {"top": int(top), "left": int(left), "width": int(width), "height": int(height)}
        raw_shot = self._sct.grab(monitor)
        frame_bgra = np.frombuffer(raw_shot.raw, dtype=np.uint8).reshape((int(height), int(width), 4))
        return cv2.cvtColor(frame_bgra, cv2.COLOR_BGRA2BGR)

    def close(self):
        self._sct.close()


class BagDetector:
    """
    Nhận diện thẻ Túi Lộc hoạt động độc lập với độ phân giải.
    Áp dụng quy tắc xác thực 3 tầng: Nền cam ấm + Túi hồng đào + Kim cương lam.
    """

    def __init__(self, target_dir: Path, cfg: dict):
        self.cfg = cfg
        card_cfg = cfg.get("color_filters", {}).get("card_bg_hsv", {})
        self.h_min = card_cfg.get("h_min", 15)
        self.s_min = card_cfg.get("s_min", 60)
        self.v_min = card_cfg.get("v_min", 180)
        self.h_max = card_cfg.get("h_max", 28)
        self.s_max = card_cfg.get("s_max", 255)
        self.v_max = card_cfg.get("v_max", 255)
        self.min_area_pct = card_cfg.get("min_card_area_pct", 0.03)

    def detect_bag(self, roi_bgr: np.ndarray) -> Optional[Tuple[int, int, float]]:
        """
        Phát hiện thẻ túi lộc đang hoạt động (còn lượt nhận).
        Loại bỏ 100% các tin nhắn chia sẻ Puffel (Vua Lượn Mây), Trang trại, Chia sẻ tọa độ.
        """
        h, w = roi_bgr.shape[:2]
        if h <= 10 or w <= 10:
            return None

        hsv = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2HSV)
        mask_amber = cv2.inRange(
            hsv, (self.h_min, self.s_min, self.v_min), (self.h_max, self.s_max, self.v_max)
        )

        min_card_area = h * w * self.min_area_pct
        contours, _ = cv2.findContours(mask_amber, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        for c in contours:
            area = cv2.contourArea(c)
            if area < min_card_area:
                continue

            x, y, cw, ch = cv2.boundingRect(c)
            ratio = cw / max(1, ch)

            # TIÊU CHUẨN 1: Tỷ lệ hình học (Aspect Ratio) của toàn bộ thẻ
            # Thẻ túi lộc thật: 2.0 <= cw/ch <= 5.5
            # Thanh tiêu đề Puffel (Vua Lượn Mây) hay Trang Trại có ratio > 6.5 -> Loại bỏ!
            if not (2.0 <= ratio <= 5.5 and cw >= w * 0.28):
                logger.debug("[Filter.Reject] Bỏ qua dải tiêu đề: cw=%d, ch=%d, ratio=%.2f", cw, ch, ratio)
                continue

            # TIÊU CHUẨN 2: Xác thực Túi Quà Hồng Đào (Pink Pouch) bên trong thân thẻ
            card_roi = roi_bgr[y:y + ch, x:x + cw]
            card_hsv = cv2.cvtColor(card_roi, cv2.COLOR_BGR2HSV)
            mask_pink = cv2.inRange(card_hsv, (145, 60, 110), (178, 255, 255))
            pink_count = cv2.countNonZero(mask_pink)

            # Túi quà hồng phải chiếm ít nhất 1.2% diện tích thẻ
            if pink_count < (cw * ch * 0.012):
                logger.debug("[Filter.Reject] Thiếu túi hồng đào: pink_count=%d", pink_count)
                continue

            # TIÊU CHUẨN 3: Xác thực Viên Kim Cương Lam (Cyan Gem)
            mask_cyan = cv2.inRange(card_hsv, (80, 80, 140), (115, 255, 255))
            cyan_count = cv2.countNonZero(mask_cyan)
            if cyan_count < (cw * ch * 0.004):
                logger.debug("[Filter.Reject] Thiếu kim cương lam: cyan_count=%d", cyan_count)
                continue

            # Cả 3 tiêu chuẩn đều khớp -> Xác nhận 100% Túi Lộc thật
            cx = x + cw // 2
            cy = y + ch // 2
            score = min(1.0, area / (h * w * 0.15))
            return cx, cy, float(score)

        return None


class CloseModalDetector:
    """Nhận diện và định vị nút X màu đỏ đóng popup kết quả."""

    def __init__(self, target_dir: Path, cfg: dict):
        self.cfg = cfg
        red_cfg = cfg.get("color_filters", {}).get("red_close_btn_hsv", {})
        r1 = red_cfg.get("range1", [0, 80, 140, 12, 255, 255])
        r2 = red_cfg.get("range2", [168, 80, 140, 180, 255, 255])
        self.red_lower1, self.red_upper1 = np.array(r1[:3]), np.array(r1[3:])
        self.red_lower2, self.red_upper2 = np.array(r2[:3]), np.array(r2[3:])

    def locate_close_button(self, roi_bgr: np.ndarray) -> Optional[Tuple[int, int]]:
        """Định vị tâm nút X đỏ trong ROI bằng phân tích đường viền hình tròn."""
        h, w = roi_bgr.shape[:2]
        if h <= 10 or w <= 10:
            return None

        hsv = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2HSV)
        m1 = cv2.inRange(hsv, self.red_lower1, self.red_upper1)
        m2 = cv2.inRange(hsv, self.red_lower2, self.red_upper2)
        mask = m1 | m2

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        min_btn_area = max(40.0, h * w * 0.02)

        for c in contours:
            area = cv2.contourArea(c)
            if area >= min_btn_area:
                x, y, cw, ch = cv2.boundingRect(c)
                ratio = cw / max(1, ch)
                if 0.65 <= ratio <= 1.5:
                    return x + cw // 2, y + ch // 2

        return None


class CaravanDetector:
    """
    Phát hiện tin nhắn mời Thương Đội (Thẻ đỏ) và định vị nút 'Gia Nhập' màu xanh.
    Xác thực 3 tầng:
      1. Nút bấm màu xanh lá/vàng lục với tỷ lệ chữ nhật chuẩn: 2.0 <= cw/ch <= 4.5
      2. Khối thân thẻ màu đỏ/san hô đặc thù của Thương Đội ngay phía trên nút bấm (>= 20% pixel đỏ).
      3. Phân loại 2 dạng thương đội:
         - 'regular': Thương đội đỏ thường (có biểu tượng con ngựa màu đỏ).
         - 'season': Thương đội mùa giải (không có biểu tượng con ngựa màu đỏ).
    """

    def __init__(self, cfg: dict, target_dir: Optional[Path] = None):
        self.cfg = cfg
        c_cfg = cfg.get("color_filters", {}).get("caravan_green_btn_hsv", {})
        self.h_min = c_cfg.get("h_min", 28)
        self.s_min = c_cfg.get("s_min", 50)
        self.v_min = c_cfg.get("v_min", 80)
        self.h_max = c_cfg.get("h_max", 55)
        self.s_max = c_cfg.get("s_max", 255)
        self.v_max = c_cfg.get("v_max", 255)
        self.min_ratio = c_cfg.get("min_aspect_ratio", 2.0)
        self.max_ratio = c_cfg.get("max_aspect_ratio", 4.5)

        caravan_cfg = cfg.get("caravan_settings", {})
        self.horse_match_threshold = float(caravan_cfg.get("horse_match_threshold", 0.70))
        self.btn_match_threshold = float(caravan_cfg.get("btn_match_threshold", 0.70))
        self.max_body_white_ratio = float(caravan_cfg.get("max_body_white_ratio", 0.15))
        self.max_header_blue_ratio = float(caravan_cfg.get("max_header_blue_ratio", 0.15))

        if target_dir is None:
            target_dir = Path(__file__).resolve().parent / "targets"
        horse_path = target_dir / "caravan_red_horse.png"
        self.horse_template = cv2.imread(str(horse_path)) if horse_path.exists() else None
        btn_path = target_dir / "caravan_green_btn.png"
        self.btn_template = cv2.imread(str(btn_path)) if btn_path.exists() else None

    def _classify_caravan_type(self, roi_bgr: np.ndarray, bx: int, by: int, bw: int, bh: int) -> str:
        """
        Phân biệt thương đội đỏ thường (có ngựa đỏ) và thương đội mùa giải (không có ngựa đỏ).
        """
        if self.horse_template is None:
            return "regular"

        h, w = roi_bgr.shape[:2]
        scale = bw / 66.0
        cw = int(2.6 * bw)
        ch = int(6.5 * bh)
        card_x1 = max(0, bx - int(0.8 * bw))
        card_y1 = max(0, by - int(5.2 * bh))

        ix1 = max(0, card_x1 + int(0.02 * cw))
        ix2 = min(w, card_x1 + int(0.45 * cw))
        iy1 = max(0, card_y1 + int(0.10 * ch))
        iy2 = min(h, card_y1 + int(0.60 * ch))
        icon_roi = roi_bgr[iy1:iy2, ix1:ix2]

        tw = max(10, int(self.horse_template.shape[1] * scale))
        th = max(10, int(self.horse_template.shape[0] * scale))

        if icon_roi.shape[0] >= th and icon_roi.shape[1] >= tw:
            scaled_tpl = cv2.resize(self.horse_template, (tw, th))
            res = cv2.matchTemplate(icon_roi, scaled_tpl, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, _ = cv2.minMaxLoc(res)
            if max_val >= self.horse_match_threshold:
                return "regular"

        return "season"

    def detect_join_button(self, roi_bgr: np.ndarray) -> Optional[Tuple[int, int, str]]:
        """
        Quét vùng ROI chat tìm nút 'Gia Nhập' màu xanh trên thẻ Thương Đội đỏ.
        Trả về (cx, cy, caravan_type) tương đối trong ROI nếu phát hiện.

        Quy trình lọc 4 tầng ngăn chặn nhận nhầm thẻ không phải thương đội (như 'Nhà Tí Tách'):
          Tầng 1: Khớp mẫu template nút 'Gia Nhập' (loại bỏ nút 'Thăm' hoặc nút khác).
          Tầng 2: Xác thực vùng thân thẻ ngay trên nút có tỷ lệ pixel đỏ/san hô >= 20%.
          Tầng 3: Kiểm tra tỷ lệ nền trắng/kem của thẻ; từ chối nếu > 15% (loại bỏ Nhà Tí Tách nền trắng).
          Tầng 4: Kiểm tra dải tiêu đề đỉnh thẻ; từ chối nếu có màu xanh lam > 15% (Nhà Tí Tách header xanh lam).
        """
        h, w = roi_bgr.shape[:2]
        if h <= 15 or w <= 15:
            return None

        hsv = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2HSV)
        mask_green = cv2.inRange(
            hsv, (self.h_min, self.s_min, self.v_min), (self.h_max, self.s_max, self.v_max)
        )

        min_btn_area = max(50.0, h * w * 0.005)
        contours, _ = cv2.findContours(mask_green, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        for c in contours:
            area = cv2.contourArea(c)
            if area < min_btn_area:
                continue

            bx, by, bw, bh = cv2.boundingRect(c)
            ratio = bw / max(1, bh)

            if not (self.min_ratio <= ratio <= self.max_ratio):
                continue

            # Tầng 1: Khớp mẫu template nút 'Gia Nhập' (loại bỏ triệt để nút 'Thăm' trên thẻ Nhà Tí Tách)
            btn_roi = roi_bgr[by : by + bh, bx : bx + bw]
            if (
                self.btn_template is not None
                and btn_roi.shape[0] >= 10
                and btn_roi.shape[1] >= 20
            ):
                scaled_btn = cv2.resize(self.btn_template, (bw, bh))
                res_btn = cv2.matchTemplate(btn_roi, scaled_btn, cv2.TM_CCOEFF_NORMED)
                _, btn_score, _, _ = cv2.minMaxLoc(res_btn)
                if btn_score < self.btn_match_threshold:
                    continue

            # Tầng 2 & 3: Kiểm tra vùng thân thẻ ngay phía trên nút bấm
            check_h = int(bh * 2.8)
            y_top = max(0, by - check_h)
            x_left = max(0, bx - 10)
            x_right = min(w, bx + bw + 10)
            above_region = roi_bgr[y_top:by, x_left:x_right]

            if above_region.size == 0:
                continue

            hsv_above = cv2.cvtColor(above_region, cv2.COLOR_BGR2HSV)
            total_pixels = above_region.shape[0] * above_region.shape[1]

            # Kiểm tra tỷ lệ màu đỏ/san hô (thẻ thương đội thật có > 20% đỏ)
            m1 = cv2.inRange(hsv_above, (0, 40, 100), (15, 255, 255))
            m2 = cv2.inRange(hsv_above, (165, 40, 100), (180, 255, 255))
            red_pixels = cv2.countNonZero(m1 | m2)
            if red_pixels < total_pixels * 0.20:
                continue

            # Tầng 3: Kiểm tra nền trắng/kem (thẻ Nhà Tí Tách có > 30% trắng, thẻ thương đội < 2%)
            white_mask = cv2.inRange(hsv_above, (0, 0, 180), (180, 40, 255))
            if cv2.countNonZero(white_mask) > total_pixels * self.max_body_white_ratio:
                continue

            # Tầng 4: Kiểm tra dải tiêu đề ở đỉnh thẻ (nếu nằm trong ROI)
            if by >= int(bh * 4.5):
                hy1 = max(0, by - int(bh * 5.8))
                hy2 = max(0, by - int(bh * 4.2))
                header_region = roi_bgr[hy1:hy2, x_left:x_right]
                if header_region.size > 0:
                    hsv_hdr = cv2.cvtColor(header_region, cv2.COLOR_BGR2HSV)
                    blue_mask = cv2.inRange(hsv_hdr, (95, 80, 80), (125, 255, 255))
                    hdr_total = header_region.shape[0] * header_region.shape[1]
                    if cv2.countNonZero(blue_mask) > hdr_total * self.max_header_blue_ratio:
                        continue

            cx = bx + bw // 2
            cy = by + bh // 2
            caravan_type = self._classify_caravan_type(roi_bgr, bx, by, bw, bh)
            return cx, cy, caravan_type

        return None


class TopHeroesLuckyBagRunner:
    """Bộ điều phối chu trình theo dõi, giật túi lộc và tự động gia nhập thương đội."""

    def __init__(
        self,
        config_path: Path,
        window_rect: Tuple[int, int, int, int],
        hwnd: Optional[int] = None,
        target_bags: int = 0,
        enable_bag_snatch: bool = True,
        enable_caravan_join: bool = True,
        enable_caravan_regular: bool = True,
        enable_caravan_season: bool = True,
    ):
        with open(config_path, "r", encoding="utf-8") as f:
            self.cfg = json.load(f)

        self.hwnd = hwnd
        self.target_dir = config_path.parent / "targets"
        self.win_left, self.win_top, self.win_width, self.win_height = self._resolve_client_rect(
            hwnd, window_rect
        )

        self.capture = FastCapture()
        self.input = FastInput(hwnd)
        self.bag_detector = BagDetector(self.target_dir, self.cfg)
        self.caravan_detector = CaravanDetector(self.cfg, self.target_dir)
        self.close_detector = CloseModalDetector(self.target_dir, self.cfg)

        self.target_bags = target_bags
        self.bags_collected = 0
        self.caravans_joined = 0
        self.enable_bag_snatch = enable_bag_snatch
        self.enable_caravan_join = enable_caravan_join
        self.enable_caravan_regular = enable_caravan_regular
        self.enable_caravan_season = enable_caravan_season

        # Bộ nhớ các thương đội gia nhập không thành công cần bỏ qua: {(click_x, click_y): timestamp}
        self.ignored_caravans: Dict[Tuple[int, int], float] = {}
        c_settings = self.cfg.get("caravan_settings", {})
        self.caravan_verify_wait_sec = float(c_settings.get("verify_wait_ms", 250)) / 1000.0
        self.caravan_ignore_duration_sec = float(c_settings.get("failed_ignore_duration_s", 60.0))

        self.last_grab_time = 0.0
        self.last_caravan_time = 0.0
        self.last_guild_check_time = time.time()
        self.guild_routine_enabled = self.cfg.get("guild_routine", {}).get("enabled", True)
        self.guild_interval_sec = float(self.cfg.get("guild_routine", {}).get("interval_sec", 30.0))
        self.guild_render_wait_sec = float(self.cfg.get("guild_routine", {}).get("render_wait_sec", 0.20))

        self.cooldown_sec = self.cfg.get("input", {}).get("post_claim_cooldown_ms", 300) / 1000.0
        self.modal_timeout = self.cfg.get("input", {}).get("modal_wait_timeout_s", 2.0)
        self.click_hold_sec = self.cfg.get("input", {}).get("click_hold_ms", 35) / 1000.0

    @staticmethod
    def _resolve_client_rect(
        hwnd: Optional[int], fallback_rect: Tuple[int, int, int, int]
    ) -> Tuple[int, int, int, int]:
        if hwnd and _HAS_WIN32:
            try:
                pt = win32gui.ClientToScreen(hwnd, (0, 0))
                cr = win32gui.GetClientRect(hwnd)
                w = cr[2] - cr[0]
                h = cr[3] - cr[1]
                if w > 100 and h > 100:
                    return pt[0], pt[1], w, h
            except Exception:
                pass
        return fallback_rect

    def is_quota_reached(self) -> bool:
        if self.target_bags <= 0:
            return False
        return self.bags_collected >= self.target_bags

    def reset_counter(self):
        self.bags_collected = 0
        self.caravans_joined = 0
        self.ignored_caravans.clear()

    def is_caravan_ignored(self, click_x: int, click_y: int) -> bool:
        """Kiểm tra xem tọa độ nút thương đội này có vừa thất bại và cần bỏ qua không."""
        now = time.time()
        self.ignored_caravans = {
            pos: t for pos, t in self.ignored_caravans.items()
            if now - t < self.caravan_ignore_duration_sec
        }
        for (ix, iy), _ in self.ignored_caravans.items():
            if abs(click_x - ix) <= 15 and abs(click_y - iy) <= 15:
                return True
        return False

    def _attempt_join_caravan(
        self,
        c_top: int,
        c_left: int,
        c_w: int,
        c_h: int,
        cx: int,
        cy: int,
        c_type: str,
        source: str = "world",
    ) -> Optional[dict]:
        """
        Thực hiện chu trình gia nhập thương đội và xác thực kết quả:
          1. Kiểm tra tọa độ có bị blacklist/ignore không.
          2. Kiểm tra tùy chọn loại thương đội (đỏ thường vs mùa giải).
          3. Click gia nhập.
          4. Xác thực phản hồi: Nếu nút vẫn còn HOẶC có modal lỗi -> Coi như thất bại, bỏ qua luôn!
        """
        click_x = c_left + cx
        click_y = c_top + cy

        # Bỏ qua nếu tọa độ này vừa thất bại trước đó
        if self.is_caravan_ignored(click_x, click_y):
            return None

        # Kiểm tra tùy chọn loại thương đội của người dùng
        if c_type == "regular" and not self.enable_caravan_regular:
            return None
        if c_type == "season" and not self.enable_caravan_season:
            return None

        # Gửi lệnh click gia nhập
        self.input.click_screen(click_x, click_y, hold_sec=self.click_hold_sec)
        if self.hwnd:
            self.input.click_window(click_x - self.win_left, click_y - self.win_top, hold_sec=self.click_hold_sec)
        self.last_caravan_time = time.time()

        # Chờ game cập nhật trạng thái
        time.sleep(self.caravan_verify_wait_sec)

        # Đóng popup nếu có (modal cảnh báo "Thương đội đã đầy" hoặc tương tự)
        modal_dismissed = self.handle_modal_dismissal()

        # Kiểm tra lại xem nút 'Gia Nhập' còn tại vị trí đó hay không
        verify_frame = self.capture.grab_roi(c_top, c_left, c_w, c_h)
        post_match = self.caravan_detector.detect_join_button(verify_frame)

        is_still_there = False
        if post_match:
            pcx, pcy, _ = post_match
            if abs(pcx - cx) <= 15 and abs(pcy - cy) <= 15:
                is_still_there = True

        if is_still_there or modal_dismissed:
            # Gia nhập không thành công -> Ghi nhớ bỏ qua hoàn toàn vị trí này
            self.ignored_caravans[(click_x, click_y)] = time.time()
            logger.info(
                "[%s.Caravan] Gia nhập thất bại tại (%d, %d) [%s] (Thương đội đã đầy hoặc không khả dụng). Bỏ qua luôn!",
                source.capitalize(), click_x, click_y, c_type.upper()
            )
            return {"action": "caravan_failed", "pos": (click_x, click_y), "type": c_type, "source": source}

        # Gia nhập thành công
        self.caravans_joined += 1
        logger.info(
            "[%s.Caravan] Gia nhập thành công Thương Đội [%s] tại (%d, %d)! Tổng số: %d",
            source.capitalize(), c_type.upper(), click_x, click_y, self.caravans_joined
        )
        return {"action": "caravan", "pos": (click_x, click_y), "total": self.caravans_joined, "type": c_type, "source": source}

    def _calc_roi_rect(self, roi_key: str) -> Tuple[int, int, int, int]:
        """Tính toán tọa độ pixel tuyệt đối từ tỷ lệ phần trăm cấu hình."""
        active_prof = self.cfg.get("active_profile", "pc")
        profiles = self.cfg.get("profiles", {})
        roi_info = None

        if active_prof in profiles and roi_key in profiles[active_prof]:
            roi_info = profiles[active_prof][roi_key]
        elif roi_key in self.cfg.get("roi_config", {}):
            roi_info = self.cfg["roi_config"][roi_key]
        elif "chat_bag_roi" in profiles.get(active_prof, {}):
            roi_info = profiles[active_prof]["chat_bag_roi"]
        else:
            roi_info = self.cfg["roi_config"]["chat_bag_roi"]

        x_min = int(self.win_left + roi_info["x_min_pct"] * self.win_width)
        x_max = int(self.win_left + roi_info["x_max_pct"] * self.win_width)
        y_min = int(self.win_top + roi_info["y_min_pct"] * self.win_height)
        y_max = int(self.win_top + roi_info["y_max_pct"] * self.win_height)
        return y_min, x_min, x_max - x_min, y_max - y_min

    def handle_modal_dismissal(self) -> bool:
        """Chờ và click nút X màu đỏ đóng modal kết quả trong thời gian ngắn nhất."""
        c_top, c_left, c_w, c_h = self._calc_roi_rect("close_btn_roi")
        start_t = time.time()

        while time.time() - start_t < self.modal_timeout:
            frame = self.capture.grab_roi(c_top, c_left, c_w, c_h)
            pos = self.close_detector.locate_close_button(frame)
            if pos:
                cx, cy = pos
                screen_x = c_left + cx
                screen_y = c_top + cy
                self.input.click_screen(screen_x, screen_y, hold_sec=self.click_hold_sec)
                if self.hwnd:
                    self.input.click_window(screen_x - self.win_left, screen_y - self.win_top, hold_sec=self.click_hold_sec)
                if self.cfg.get("input", {}).get("double_click_close", True):
                    time.sleep(0.04)
                    self.input.click_screen(screen_x, screen_y, hold_sec=self.click_hold_sec)
                return True
            time.sleep(0.01)

        return False

    def switch_to_tab(self, tab_name: str):
        """Chuyển đổi giữa các tab kênh chat (world / guild / activity / personal)."""
        active_prof = self.cfg.get("active_profile", "pc")
        profiles = self.cfg.get("profiles", {})
        tabs_cfg = profiles.get(active_prof, {}).get("tabs", {})
        if tab_name not in tabs_cfg:
            return

        tab_info = tabs_cfg[tab_name]
        click_x = int(self.win_left + tab_info["x_pct"] * self.win_width)
        click_y = int(self.win_top + tab_info["y_pct"] * self.win_height)

        self.input.click_screen(click_x, click_y, hold_sec=self.click_hold_sec)
        if self.hwnd:
            self.input.click_window(click_x - self.win_left, click_y - self.win_top, hold_sec=self.click_hold_sec)
        time.sleep(self.guild_render_wait_sec)

    def perform_guild_routine_check(self) -> Optional[dict]:
        """
        Quy trình mặc định định kỳ (mỗi 30s):
          1. Đảo sang kênh Hội.
          2. Quét Túi Lộc và Thương Đội trong Hội.
          3. Nếu có thì giật / gia nhập ngay lập tức.
          4. Đảo ngược lại về kênh Thế Giới để tiếp tục chu kỳ quét chính.
        """
        logger.info("[Guild.Routine] 30s interval reached: Checking Guild Chat tab...")
        self.switch_to_tab("guild")
        snatched_result = None

        # 1. Quét tìm Thương Đội trong kênh Hội
        if self.enable_caravan_join and (self.enable_caravan_regular or self.enable_caravan_season):
            c_top, c_left, c_w, c_h = self._calc_roi_rect("chat_caravan_roi")
            caravan_frame = self.capture.grab_roi(c_top, c_left, c_w, c_h)
            pos_info = self.caravan_detector.detect_join_button(caravan_frame)
            if pos_info:
                cx, cy, c_type = pos_info
                join_res = self._attempt_join_caravan(c_top, c_left, c_w, c_h, cx, cy, c_type, source="guild")
                if join_res and join_res.get("action") == "caravan":
                    snatched_result = join_res
                    time.sleep(0.15)

        # 2. Quét tìm Túi Lộc trong kênh Hội
        if self.enable_bag_snatch and not self.is_quota_reached():
            b_top, b_left, b_w, b_h = self._calc_roi_rect("chat_bag_roi")
            roi_frame = self.capture.grab_roi(b_top, b_left, b_w, b_h)
            match = self.bag_detector.detect_bag(roi_frame)
            if match:
                cx, cy, score = match
                click_x = b_left + cx
                click_y = b_top + cy
                self.input.click_screen(click_x, click_y, hold_sec=self.click_hold_sec)
                if self.hwnd:
                    self.input.click_window(click_x - self.win_left, click_y - self.win_top, hold_sec=self.click_hold_sec)
                self.last_grab_time = time.time()
                self.bags_collected += 1
                target_str = str(self.target_bags) if self.target_bags > 0 else "unlimited"
                logger.info(
                    "[Guild.Snatch] Captured lucky bag in Guild Chat! (score=%.2f). Dispatched click at (%d, %d). Progress: %d/%s",
                    score, click_x, click_y, self.bags_collected, target_str
                )
                self.handle_modal_dismissal()
                snatched_result = {"action": "bag", "pos": (click_x, click_y), "total": self.bags_collected, "score": score, "source": "guild"}
                time.sleep(0.15)

        # 3. Luôn đảo ngược lại về kênh Thế Giới
        self.switch_to_tab("world")
        self.last_guild_check_time = time.time()
        logger.info("[Guild.Routine] Returned to World Chat tab. Continuing real-time stream.")
        return snatched_result

    def scan_and_snatch_once(self) -> Optional[dict]:
        """
        Một chu kỳ quét đa nhiệm:
          0. Kiểm tra định kỳ kênh chat Hội (Mặc định mỗi 30s).
          1. Tự động gia nhập Thương Đội khi thấy tin nhắn đỏ có nút Gia Nhập xanh.
          2. Tự động giật Túi Lộc và đóng popup kết quả.
        """
        now = time.time()

        # 0. Kiểm tra định kỳ kênh chat Hội (Mặc định mỗi 30s)
        if self.guild_routine_enabled and (now - self.last_guild_check_time >= self.guild_interval_sec):
            guild_result = self.perform_guild_routine_check()
            if guild_result:
                return guild_result

        # 1. Quét Thương Đội (Caravan Auto-Join)
        if self.enable_caravan_join and (self.enable_caravan_regular or self.enable_caravan_season) and (now - self.last_caravan_time >= 0.5):
            c_top, c_left, c_w, c_h = self._calc_roi_rect("chat_caravan_roi")
            caravan_frame = self.capture.grab_roi(c_top, c_left, c_w, c_h)
            pos_info = self.caravan_detector.detect_join_button(caravan_frame)
            if pos_info:
                cx, cy, c_type = pos_info
                join_res = self._attempt_join_caravan(c_top, c_left, c_w, c_h, cx, cy, c_type, source="world")
                if join_res:
                    return join_res

        # 2. Quét Túi Lộc (Lucky Bag Snatcher)
        if self.enable_bag_snatch and not self.is_quota_reached():
            if now - self.last_grab_time >= self.cooldown_sec:
                b_top, b_left, b_w, b_h = self._calc_roi_rect("chat_bag_roi")
                roi_frame = self.capture.grab_roi(b_top, b_left, b_w, b_h)
                match = self.bag_detector.detect_bag(roi_frame)
                if match:
                    cx, cy, score = match
                    click_x = b_left + cx
                    click_y = b_top + cy
                    self.input.click_screen(click_x, click_y, hold_sec=self.click_hold_sec)
                    if self.hwnd:
                        self.input.click_window(click_x - self.win_left, click_y - self.win_top, hold_sec=self.click_hold_sec)
                    self.last_grab_time = time.time()
                    self.bags_collected += 1
                    target_str = str(self.target_bags) if self.target_bags > 0 else "unlimited"
                    logger.info(
                        "[Snatch.Action] Bag verified (score=%.2f). Dispatched click at (%d, %d). Progress: %d/%s",
                        score, click_x, click_y, self.bags_collected, target_str
                    )
                    dismissed = self.handle_modal_dismissal()
                    if dismissed:
                        logger.info("[Modal.Dismiss] Result modal close button triggered successfully.")
                    return {"action": "bag", "pos": (click_x, click_y), "total": self.bags_collected, "score": score}

        return None

    def close(self):
        self.capture.close()
