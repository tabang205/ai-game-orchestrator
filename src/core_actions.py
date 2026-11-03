"""
core_actions.py — Tầng điều khiển input của AI Game Agent
==========================================================
Nền tảng: PC (Windows, game DirectX/client)
Thư viện: pydirectinput (gửi ScanCode chuẩn DirectX, không bị block như pyautogui)

Yêu cầu cài đặt:
    pip install pydirectinput

Đặc điểm kỹ thuật:
  - Tất cả click/key đều có Gaussian jitter ± vài pixel để tránh pattern cố định
  - Delay ngẫu nhiên (uniform / gauss) sau mỗi hành động để mô phỏng con người
  - Hỗ trợ scale tọa độ từ % màn hình sang pixel tuyệt đối
"""

import time
import math
import random
import ctypes
import logging
from typing import Optional, Tuple

import pydirectinput

# pydirectinput mặc định tạm dừng 0.1s sau mỗi lệnh — có thể tắt để tự quản lý
pydirectinput.PAUSE = 0.0
pydirectinput.FAILSAFE = False
logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# GameActions — class chính
# ══════════════════════════════════════════════════════════════════════════════

class GameActions:
    """
    Wrapper điều khiển chuột và bàn phím cho PC game.
    Mọi hành động đều được humanize (jitter + random delay).
    """

    def __init__(self, action_delays: Optional[dict] = None, enable_bezier: bool = True):
        """
        Args:
            action_delays: dict từ config.json với keys:
                - after_click_ms: [min_ms, max_ms]  — delay sau click
                - between_stages_ms: [min_ms, max_ms] — delay giữa các giai đoạn lớn
            enable_bezier: bật/tắt di chuyển chuột theo đường cong Bézier (chống anti-cheat)
        """
        delays = action_delays or {}
        self._click_delay_range = [v / 1000 for v in delays.get('after_click_ms', [500, 900])]
        self._stage_delay_range  = [v / 1000 for v in delays.get('between_stages_ms', [1200, 2000])]
        self._jitter_px = 4  # độ lệch chuẩn tọa độ click tính bằng pixel
        self.enable_bezier = enable_bezier

    # ── Private helpers ────────────────────────────────────────────────────

    @staticmethod
    def _get_current_cursor() -> Tuple[int, int]:
        class POINT(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
        pt = POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
        return int(pt.x), int(pt.y)

    def _jitter(self, x: int, y: int) -> Tuple[int, int]:
        """Thêm Gaussian noise vào tọa độ click."""
        jx = int(random.gauss(0, self._jitter_px))
        jy = int(random.gauss(0, self._jitter_px))
        return (x + jx, y + jy)

    def _random_sleep(self, range_sec: list):
        """Sleep ngẫu nhiên trong khoảng [min, max] giây."""
        t = random.uniform(range_sec[0], range_sec[1])
        time.sleep(t)

    def move_to_human(self, target_x: int, target_y: int):
        """
        Di chuyển chuột mượt mà đến (target_x, target_y) mô phỏng chính xác bàn tay người:
          - Quỹ đạo Cubic Bézier cong tự nhiên với độ lệch kiểm soát sinh học.
          - Gia tốc Asymmetric (Fitts's Law): tăng tốc nhanh ở 1/3 đầu, giảm tốc tỉ mỉ ở đoạn cuối.
          - Biological Tremor: vi rung sinh lý (±0.8-1.5px) trên đường đi.
          - Overshoot & Correction: xác suất 35% di chuyển vượt quá đích một chút rồi chỉnh lại.
        """
        start_x, start_y = self._get_current_cursor()
        dist = math.hypot(target_x - start_x, target_y - start_y)

        # Nếu chuột đã ở quá gần (dưới 8px), chỉ cần vi chỉnh nhẹ
        if dist < 8 or not self.enable_bezier:
            pydirectinput.moveTo(target_x, target_y)
            return

        # Xác định xem lần này có hiện tượng overshoot (vượt đích rồi kéo lại) hay không
        do_overshoot = dist > 70 and random.random() < 0.35
        actual_dest_x, actual_dest_y = target_x, target_y

        if do_overshoot:
            # Điểm vượt đích lố về phía trước 3 - 8 px
            angle = math.atan2(target_y - start_y, target_x - start_x)
            over_dist = random.uniform(3.0, 7.5)
            inter_x = int(target_x + math.cos(angle) * over_dist)
            inter_y = int(target_y + math.sin(angle) * over_dist)
        else:
            inter_x, inter_y = target_x, target_y

        # Tính 2 control points cho đường cong Bézier bậc 3
        ctrl_offset = dist * random.uniform(0.18, 0.38)
        angle = math.atan2(inter_y - start_y, inter_x - start_x)
        normal_angle = angle + random.choice([-1, 1]) * (math.pi / 2)

        p1_x = int(start_x + (inter_x - start_x) * 0.30 + math.cos(normal_angle) * ctrl_offset)
        p1_y = int(start_y + (inter_y - start_y) * 0.30 + math.sin(normal_angle) * ctrl_offset)

        p2_x = int(start_x + (inter_x - start_x) * 0.68 + math.cos(normal_angle) * (ctrl_offset * 0.55))
        p2_y = int(start_y + (inter_y - start_y) * 0.68 + math.sin(normal_angle) * (ctrl_offset * 0.55))

        # Số bước nội suy tỉ lệ theo khoảng cách, tối thiểu 16 bước để cực mượt
        steps = max(int(dist / 18), 16)
        steps = min(steps, 45)

        for i in range(1, steps + 1):
            t = i / steps
            # Asymmetric ease-out curve (Fitts's Law: dốc mạnh lúc đầu, lài dần lúc cuối)
            eased_t = math.sin((t * math.pi) / 2) ** 1.6
            u = 1.0 - eased_t

            # Cubic Bézier formula
            bx = (u**3) * start_x + 3 * (u**2) * eased_t * p1_x + 3 * u * (eased_t**2) * p2_x + (eased_t**3) * inter_x
            by = (u**3) * start_y + 3 * (u**2) * eased_t * p1_y + 3 * u * (eased_t**2) * p2_y + (eased_t**3) * inter_y

            # Biological Tremor: vi rung tự nhiên của cổ tay/ngón tay (không áp dụng ở 3 bước cuối)
            if i < steps - 3:
                tremor_x = random.gauss(0, 0.65)
                tremor_y = random.gauss(0, 0.65)
                bx += tremor_x
                by += tremor_y

            pydirectinput.moveTo(int(bx), int(by))
            time.sleep(random.uniform(0.006, 0.014))

        # Nếu có overshoot: thực hiện bước vi chỉnh (micro-correction) kéo về đúng đích
        if do_overshoot:
            time.sleep(random.uniform(0.03, 0.08))  # phản xạ nhận thức mắt nhận ra đã lố
            corr_steps = random.randint(4, 7)
            cur_x, cur_y = self._get_current_cursor()
            for ci in range(1, corr_steps + 1):
                ct = ci / corr_steps
                cx = cur_x + (actual_dest_x - cur_x) * ct
                cy = cur_y + (actual_dest_y - cur_y) * ct
                pydirectinput.moveTo(int(cx), int(cy))
                time.sleep(random.uniform(0.008, 0.015))

        # Đảm bảo điểm kết thúc chính xác
        pydirectinput.moveTo(actual_dest_x, actual_dest_y)

    # ── Click actions ──────────────────────────────────────────────────────

    def click(self, x: int, y: int, button: str = 'left'):
        """
        Click chuột tại (x, y) với đầy đủ đặc tính sinh trắc học người thật:
          - Gaussian jitter ± vài pixel (không bao giờ click đúng 1 pixel cố định).
          - Đường cong Bézier + gia tốc sinh học + overshoot correction.
          - Pre-click hesitation: dừng nhẹ 50-140ms trước khi ấn nút.
          - Human click hold: thời gian giữ nút chuột tuân theo phân phối Gauss (60-110ms).
          - Post-click micro-drift: ngón tay đè nhẹ gây dịch chuyển 0-1px.
          - Phục hồi delay ngẫu nhiên sau click.
        """
        cx, cy = self._jitter(x, y)
        self.move_to_human(cx, cy)
        
        # Pre-click hesitation (do dự tự nhiên)
        time.sleep(random.gauss(0.08, 0.02))

        # Click down
        pydirectinput.mouseDown(button=button)
        
        # Thời gian ngón tay ấn giữ phím chuột (human click duration: 60-110ms)
        click_hold_time = max(0.045, min(0.130, random.gauss(0.075, 0.015)))
        time.sleep(click_hold_time)

        # Post-click micro drift (xác suất 30% tay ấn làm nhích nhẹ 1px)
        if random.random() < 0.3:
            pydirectinput.moveTo(cx + random.choice([-1, 0, 1]), cy + random.choice([-1, 0, 1]))

        pydirectinput.mouseUp(button=button)
        self._random_sleep(self._click_delay_range)

    def idle_drift(self, max_offset_px: int = 15):
        """
        Mô phỏng chuyển động chuột tự nhiên của người chơi khi đang rảnh tay/chờ trận/loading.
        Chuột nhích nhẹ hoặc lượn một khoảng ngắn để tránh dấu hiệu bot bất động.
        """
        cur_x, cur_y = self._get_current_cursor()
        dx = random.randint(-max_offset_px, max_offset_px)
        dy = random.randint(-max_offset_px, max_offset_px)
        self.move_to_human(cur_x + dx, cur_y + dy)

    def click_pct(self, x_pct: float, y_pct: float, screen_w: int, screen_h: int, button: str = 'left'):
        """
        Click theo tọa độ phần trăm màn hình (từ Gemini Vision).

        Args:
            x_pct, y_pct: 0.0 ~ 1.0
            screen_w, screen_h: Kích thước màn hình hoặc vùng game
        """
        x = int(x_pct * screen_w)
        y = int(y_pct * screen_h)
        self.click(x, y, button)

    def double_click(self, x: int, y: int):
        """Double click tại (x, y)."""
        cx, cy = self._jitter(x, y)
        pydirectinput.moveTo(cx, cy)
        time.sleep(random.uniform(0.05, 0.10))
        pydirectinput.click(cx, cy)
        time.sleep(random.uniform(0.08, 0.15))
        pydirectinput.click(cx, cy)
        self._random_sleep(self._click_delay_range)

    def drag(self, start_x: int, start_y: int, end_x: int, end_y: int, steps: int = 20):
        """Kéo thả chuột mô phỏng vuốt cảm ứng/cuộn danh sách."""
        pydirectinput.moveTo(start_x, start_y)
        time.sleep(0.08)
        pydirectinput.mouseDown(button='left')
        time.sleep(0.08)
        for s in range(1, steps + 1):
            t = s / steps
            curr_x = int(start_x + (end_x - start_x) * t)
            curr_y = int(start_y + (end_y - start_y) * t)
            pydirectinput.moveTo(curr_x, curr_y)
            time.sleep(0.015)
        time.sleep(0.08)
        pydirectinput.mouseUp(button='left')
        self._random_sleep(self._click_delay_range)

    def scroll_wheel(self, clicks: int, x: Optional[int] = None, y: Optional[int] = None):
        """Cuộn chuột thông qua Windows mouse_event (clicks > 0: lên, clicks < 0: xuống)."""
        if x is not None and y is not None:
            pydirectinput.moveTo(x, y)
            time.sleep(0.05)
        dw_data = int(clicks * 120)
        ctypes.windll.user32.mouse_event(0x0800, 0, 0, dw_data, 0)
        time.sleep(0.3)

    # ── Keyboard actions ───────────────────────────────────────────────────

    def press_key(self, key: str):
        """
        Nhấn và thả một phím.
        key: chuỗi phím theo pydirectinput (vd: 'f', 'space', 'enter', 'escape')
        """
        pydirectinput.keyDown(key)
        time.sleep(random.uniform(0.04, 0.10))
        pydirectinput.keyUp(key)
        time.sleep(random.uniform(0.1, 0.3))

    def press_key_n(self, key: str, n: int):
        """Nhấn phím n lần với delay ngẫu nhiên giữa các lần."""
        for _ in range(n):
            self.press_key(key)

    # ── Wait / Pause helpers ───────────────────────────────────────────────

    def short_wait(self):
        """Chờ ngắn sau click thường (dùng click delay range)."""
        self._random_sleep(self._click_delay_range)

    def stage_wait(self):
        """Chờ dài giữa các giai đoạn lớn (loading, transition)."""
        self._random_sleep(self._stage_delay_range)

    def human_pause(self, min_s: float = 3.0, max_s: float = 8.0):
        """Chèn khoảng nghỉ ngẫu nhiên dài hơn để mô phỏng người dùng AFK."""
        t = random.uniform(min_s, max_s)
        logger.info("[ACTION] 💤 Nghỉ ngẫu nhiên %.1fs...", t)
        time.sleep(t)

    # ── Gemini Vision–guided click ─────────────────────────────────────────

    def act_from_gemini(self, gemini_result: dict, screen_w: int, screen_h: int):
        """
        Thực thi hành động dựa trên kết quả phân tích của Gemini Vision.

        Args:
            gemini_result: dict từ GeminiVision.analyze_screen()
            screen_w, screen_h: kích thước frame để tính tọa độ tuyệt đối
        """
        action = gemini_result.get('action', 'none')
        screen_type = gemini_result.get('screen_type', 'unknown')
        desc = gemini_result.get('description', '')

        print(f"[ACTION] Gemini gợi ý — screen: {screen_type}, action: {action}")
        if desc:
            print(f"[ACTION]   → {desc}")

        if action == 'click':
            x_pct = gemini_result.get('click_x_pct', 0.5)
            y_pct = gemini_result.get('click_y_pct', 0.5)
            print(f"[ACTION] Click tại ({x_pct:.1%}, {y_pct:.1%})")
            self.click_pct(x_pct, y_pct, screen_w, screen_h)

        elif action == 'wait':
            print("[ACTION] Chờ thêm 2s theo gợi ý Gemini...")
            time.sleep(2.0)

        else:  # 'none' hoặc unknown
            print("[ACTION] Không có hành động — tiếp tục vòng lặp FSM.")


# ══════════════════════════════════════════════════════════════════════════════
# Factory function
# ══════════════════════════════════════════════════════════════════════════════

def create_actions(game_config: dict) -> GameActions:
    """Tạo GameActions instance từ dict config của game."""
    return GameActions(action_delays=game_config.get('action_delays'))


# ══════════════════════════════════════════════════════════════════════════════
# Test thủ công
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=== Test core_actions.py ===")
    print("Test sẽ di chuyển chuột sau 3 giây — hãy đảm bảo không dùng chuột!")
    time.sleep(3)

    actions = GameActions()

    # Lấy kích thước màn hình hiện tại
    import ctypes
    screen_w = ctypes.windll.user32.GetSystemMetrics(0)
    screen_h = ctypes.windll.user32.GetSystemMetrics(1)
    print(f"Màn hình: {screen_w}x{screen_h}")

    print("\n[1] Di chuyển chuột ra giữa màn hình...")
    cx, cy = screen_w // 2, screen_h // 2
    pydirectinput.moveTo(cx, cy)
    time.sleep(0.5)
    print(f"    Đã di chuyển đến ({cx}, {cy})")

    print("\n[2] Test press key 'f' x3...")
    # actions.press_key_n('f', 3)
    print("    (bỏ qua để tránh ảnh hưởng cửa sổ hiện tại)")

    print("\n✅ Test xong!")
