"""
side_story_event.py — Tự động quét chiến đấu nhanh Sự kiện Phụ (Khoảng Lặng Chốn Xa Bồ / Event Hard).
Áp dụng cơ chế Phản xạ cơ bắp (Muscle Memory) với tọa độ Client chuẩn 1440x810.
Zero-Print, Clean Code, Logging có cấu trúc.
"""

import logging
import time
from typing import Tuple

logger = logging.getLogger(__name__)

# ── TỌA ĐỘ PHẢN XẠ CƠ BẮP (CLIENT COORDINATES 1440x810) ──────────────────────
COORD_EVENT_BANNER = (240, 500)       # Banner "Khoảng Lặng Chốn Xa Bồ" trong menu F8
COORD_START_STORY = (1212, 733)       # Nút "Bắt đầu câu chuyện"
COORD_HARD_STAGE = (525, 605)         # Ải độ khó "Hard"
COORD_SELECT_TEAM = (1224, 748)       # Nút "Chọn đội"
COORD_QUICK_BATTLE = (1366, 757)      # Nút "Chiến đấu nhanh"
COORD_BACK_BTN = (90, 45)             # Nút "Quay lại"


class SideStoryEventRunner:
    """Điều phối tự động thực thi chuỗi phản xạ cơ bắp cho Sự kiện Phụ."""

    def __init__(self, vision, actions):
        self.vision = vision
        self.actions = actions

    def _client_to_screen(self, pt: Tuple[int, int], orig: Tuple[int, int]) -> Tuple[int, int]:
        return (orig[0] + pt[0], orig[1] + pt[1])

    def run_quick_battle_flow(self, wait_completion_s: int = 40) -> bool:
        """
        Thực thi toàn bộ chuỗi phản xạ:
        F8 -> Khoảng lặng chốn xa bồ -> Bắt đầu câu chuyện -> Ải Hard -> Chọn đội -> Chiến đấu nhanh.
        """
        logger.info("[EVENT] 🎯 Bắt đầu chuỗi phản xạ cơ bắp Sự kiện Phụ...")

        # 1. Bấm F8 mở Menu Chiến đấu
        logger.info("[EVENT] B1: Bấm F8 mở menu Chiến đấu...")
        self.actions.press_key('f8')
        time.sleep(2.0)

        cf, orig = self.vision.grab_game_frame()

        # 2. Click Khoảng lặng chốn xa bồ
        banner_pt = self._client_to_screen(COORD_EVENT_BANNER, orig)
        logger.info("[EVENT] B2: Click Banner Sự kiện tại %s...", COORD_EVENT_BANNER)
        self.actions.click(*banner_pt)
        time.sleep(2.5)

        # 3. Click Bắt đầu câu chuyện
        start_pt = self._client_to_screen(COORD_START_STORY, orig)
        logger.info("[EVENT] B3: Click Bắt đầu câu chuyện tại %s...", COORD_START_STORY)
        self.actions.click(*start_pt)
        time.sleep(2.5)

        # 4. Click ải Hard
        hard_pt = self._client_to_screen(COORD_HARD_STAGE, orig)
        logger.info("[EVENT] B4: Click ải Hard tại %s...", COORD_HARD_STAGE)
        self.actions.click(*hard_pt)
        time.sleep(2.0)

        # 5. Click Chọn đội
        team_pt = self._client_to_screen(COORD_SELECT_TEAM, orig)
        logger.info("[EVENT] B5: Click Chọn đội tại %s...", COORD_SELECT_TEAM)
        self.actions.click(*team_pt)
        time.sleep(2.5)

        # 6. Click Chiến đấu nhanh
        quick_pt = self._client_to_screen(COORD_QUICK_BATTLE, orig)
        logger.info("[EVENT] B6: Click Chiến đấu nhanh tại %s...", COORD_QUICK_BATTLE)
        self.actions.click(*quick_pt)
        time.sleep(3.0)

        # 7. Chờ hoàn tất chuỗi càn quét
        logger.info("[EVENT] ⏳ Đang càn quét Chiến đấu nhanh, chờ hoàn tất (%ds)...", wait_completion_s)
        time.sleep(wait_completion_s)

        # Đóng màn hình tổng kết bằng Escape
        self.actions.press_key('escape')
        time.sleep(1.0)
        logger.info("[EVENT] ✅ Đã hoàn tất chuỗi Chiến đấu nhanh Sự kiện Phụ!")
        return True
