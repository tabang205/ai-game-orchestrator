"""
arena_npc.py — Bộ điều phối tự động hoàn thành Thử thách Đấu trường NPC (Ark Re-Code).
Tuân thủ tiêu chuẩn Clean Code, Zero-Print và cấu trúc hướng đối tượng.
"""

import logging
import time
from typing import Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

BTN_START_BATTLE = (1348, 719)
BTN_VICTORY_END = (1242, 722)
BTN_MODAL_CONFIRM_BUY = (918, 590)
BTN_PACK_PINK_TOKENS = (560, 380)
BTN_NPC_TAB_RIGHT = (1290, 366)
BTN_TAB_DIA_NGUC = (1055, 115)
BTN_RED_ZONE_DISMISS = (70, 400)
LIST_CENTER_X = 600


class ArenaNPCRunner:
    """Tự động quét và chiến đấu toàn bộ các ải Đấu trường NPC ở Cấp Địa Ngục."""

    def __init__(self, vision, actions, max_gem_purchases: int = 2):
        self.vision = vision
        self.actions = actions
        self.max_gem_purchases = max_gem_purchases
        self.purchases_made = 0
        self.battles_won = 0

    def _client_to_screen(self, pt: Tuple[int, int], orig: Tuple[int, int]) -> Tuple[int, int]:
        return (orig[0] + pt[0], orig[1] + pt[1])

    def read_arena_flags(self, frame: np.ndarray) -> Optional[Tuple[int, int]]:
        """Đọc số cờ hiện tại / tối đa (vd: 3/5) từ thanh trạng thái HUD."""
        top_crop = frame[15:65, 600:750]
        items = self.vision.ocr.find_all_text(top_crop, min_score=0.6)
        for it in items:
            t = it['text'].replace(' ', '')
            if '/' in t:
                parts = t.split('/')
                if len(parts) >= 2 and parts[-1].isdigit():
                    max_flags = int(parts[-1])
                    cur_digits = [c for c in parts[-2] if c.isdigit()]
                    if cur_digits and max_flags in (5, 10):
                        cur_flags = int(cur_digits[-1])
                        return cur_flags, max_flags
        return None

    def find_visible_challenge_buttons(self, frame: np.ndarray) -> List[Tuple[int, int]]:
        """Tìm tất cả các nút 'Thử thách' hợp lệ trong danh sách đối thủ."""
        items = self.vision.ocr.find_all_text(frame, min_score=0.6)
        valid_buttons: List[Tuple[int, int]] = []
        for it in items:
            cx, cy = it['center']
            norm = it['norm']
            if 'thuthach' in norm and 980 < cx < 1100 and 200 < cy < 750:
                valid_buttons.append((cx, cy))
        valid_buttons.sort(key=lambda pt: pt[1])
        return valid_buttons

    def dismiss_character_card_if_open(self, frame: np.ndarray, orig: Tuple[int, int]) -> bool:
        """Nếu bấm nhầm vào thẻ nhân vật mở modal chi tiết, bấm vùng biên đỏ ngoài thẻ để đóng."""
        items = self.vision.ocr.find_all_text(frame, min_score=0.5)
        norms = [i['norm'] for i in items]
        if any(k in n for k in ['thuoc tinh quang', 'thuoc tinh', 'doi hinh phong', 'kich thuoc', 'mau sac'] for n in norms) and any('level' in n for n in norms):
            logger.info("[ARENA] ⚠️ Phát hiện mở nhầm popup thẻ nhân vật. Bấm vùng rìa đỏ %s để đóng...", BTN_RED_ZONE_DISMISS)
            dismiss_pt = self._client_to_screen(BTN_RED_ZONE_DISMISS, orig)
            self.actions.click(*dismiss_pt)
            time.sleep(1.2)
            return True
        return False

    def handle_flag_purchase_modal(self, frame: np.ndarray, orig: Tuple[int, int]) -> bool:
        """
        Xác nhận mua cờ khi xuất hiện popup thiếu cờ.
        QUY TẮC BẮT BUỘC TỪ NGƯỜI DÙNG:
        - CHỈ mua bằng Huy hiệu Hồng (gói 100 coin -> 5 cờ, Sở hữu 2000+).
        - TUYỆT ĐỐI CẤM sử dụng Kim Cương (loại tiền có số 310).
        """
        items = self.vision.ocr.find_all_text(frame, min_score=0.6)
        norms = [i['norm'] for i in items]
        has_buy_modal = any(any(k in n for k in ['mua nang luong', 'khong du']) for n in norms)
        if not has_buy_modal:
            return False

        if self.purchases_made >= self.max_gem_purchases:
            logger.warning("[ARENA] Đã đạt giới hạn số lần nạp cờ (%d/%d)",
                           self.purchases_made, self.max_gem_purchases)
            return False

        logger.info("[ARENA] 🛒 Xuất hiện popup mua cờ. Chọn gói 100 Huy hiệu Hồng (CẤM dùng Kim cương 310)...")
        # 1. Chọn gói Huy hiệu Hồng ở thẻ bên trái tại Client (560, 380)
        pack_pt = self._client_to_screen(BTN_PACK_PINK_TOKENS, orig)
        self.actions.click(*pack_pt)
        time.sleep(0.8)

        # 2. Bấm nút Mua tại Client (918, 590)
        buy_pt = self._client_to_screen(BTN_MODAL_CONFIRM_BUY, orig)
        self.actions.click(*buy_pt)
        self.purchases_made += 1
        logger.info("[ARENA] ✅ Đã bấm Mua bằng 100 Huy hiệu Hồng thành công (%d lần).", self.purchases_made)
        time.sleep(1.5)

        # 3. Đóng thông báo xác nhận thành công nếu có
        self.actions.press_key('space')
        time.sleep(1.0)
        return True

    def wait_for_battle_result(self, max_wait_s: int = 180) -> bool:
        """Lắng nghe trận đấu và bấm kết thúc khi đạt chiến thắng."""
        start_time = time.time()
        logger.info("[ARENA] ⚔️ Đang trong trận đấu, chờ phân định thắng bại...")

        while time.time() - start_time < max_wait_s:
            time.sleep(3.0)
            cf, orig = self.vision.grab_game_frame()
            items = self.vision.ocr.find_all_text(cf, min_score=0.6)
            norms = [i['norm'] for i in items]

            is_victory = any(any(k in n for k in ['victory', 'chien thang']) for n in norms)
            is_victory = is_victory and not any('chuoi chien thang' in n for n in norms)
            has_end_btn = any(any(k in n for k in ['ket thuc', 'xac nhan', 'tiep tuc', 'nhan bat ky']) for n in norms)

            if is_victory or has_end_btn:
                logger.info("[ARENA] 🏆 Trận đấu kết thúc thắng lợi!")
                end_pt = None
                for i in items:
                    if any(k in i['norm'] for k in ['ket thuc', 'tiep tuc', 'xac nhan', 'nhan bat ky']):
                        end_pt = self._client_to_screen(i['center'], orig)
                        break
                if not end_pt:
                    end_pt = self._client_to_screen(BTN_VICTORY_END, orig)

                time.sleep(1.0)
                self.actions.click(*end_pt)
                time.sleep(2.5)
                # Bấm bỏ qua animation rương phần thưởng tại góc phải an toàn (1242, 722)
                self.actions.click(orig[0] + BTN_VICTORY_END[0], orig[1] + BTN_VICTORY_END[1])
                time.sleep(0.5)
                self.actions.press_key('space')
                time.sleep(1.5)
                self.battles_won += 1
                return True

        logger.error("[ARENA] Trận đấu quá thời gian chờ %ds!", max_wait_s)
        return False

    def start_battle_and_wait(self, max_wait_s: int = 180) -> bool:
        """Đảm bảo bấm Bắt đầu trận đấu thành công và chuyển vào theo dõi kết quả."""
        start_attempt_time = time.time()
        battle_started = False

        while time.time() - start_attempt_time < 35:
            cf, orig = self.vision.grab_game_frame()
            items = self.vision.ocr.find_all_text(cf, min_score=0.6)
            norms = [i['norm'] for i in items]

            in_battle = any(any(k in n for k in ['chedoantoan', 'auto', 'turn', 'wave', 'round']) for n in norms)
            is_victory = any(any(k in n for k in ['victory', 'chien thang']) for n in norms)
            if in_battle or is_victory:
                logger.info("[ARENA] ⚔️ Đã vào trận đấu thành công!")
                battle_started = True
                break

            if self.handle_flag_purchase_modal(cf, orig):
                logger.info("[ARENA] Đã xác nhận mua cờ, chờ chuẩn bị xuất trận...")
                time.sleep(2.0)
                self.actions.press_key('space')
                time.sleep(1.0)
                continue

            start_pt = self._client_to_screen(BTN_START_BATTLE, orig)
            logger.info("[ARENA] 🚀 Bấm nút Bắt đầu trận đấu tại %s", BTN_START_BATTLE)
            self.actions.click(*start_pt)
            time.sleep(3.0)

        if not battle_started:
            logger.error("[ARENA] Không thể vào trận đấu sau 35s. Bấm Escape để thoát...")
            self.actions.press_key('escape')
            time.sleep(1.0)
            return False

        return self.wait_for_battle_result(max_wait_s=max_wait_s)

    def fight_single_match(self, button_client_pt: Tuple[int, int]) -> bool:
        """Thực hiện một trận đấu từ lúc bấm nút Thử thách đến khi quay lại danh sách."""
        cf, orig = self.vision.grab_game_frame()
        btn_screen_pt = self._client_to_screen(button_client_pt, orig)

        logger.info("[ARENA] 👉 Bấm nút Thử thách tại %s", button_client_pt)
        self.actions.click(*btn_screen_pt)
        time.sleep(2.0)

        cf2, orig2 = self.vision.grab_game_frame()
        if self.handle_flag_purchase_modal(cf2, orig2):
            time.sleep(1.5)
            self.actions.press_key('space')
            time.sleep(1.0)
            self.actions.click(*btn_screen_pt)
            time.sleep(2.0)

        return self.start_battle_and_wait()

    def wait_for_arena_screen(self, max_wait_s: int = 15) -> bool:
        """Chờ màn hình Đấu trường ổn định sau khi rời trận đấu."""
        start = time.time()
        while time.time() - start < max_wait_s:
            time.sleep(1.5)
            cf, _ = self.vision.grab_game_frame()
            items = self.vision.ocr.find_all_text(cf, min_score=0.5)
            norms = [i['norm'] for i in items]
            if any('thu thach npc' in n or 'dia nguc' in n for n in norms):
                time.sleep(1.0)
                return True
        return False

    def scroll_list_down(self, orig: Tuple[int, int]) -> None:
        """Kéo vuốt danh sách đối thủ từ dưới lên để lộ các ải tiếp theo."""
        sx = orig[0] + LIST_CENTER_X
        start_sy = orig[1] + 600
        end_sy = orig[1] + 300
        logger.info("[ARENA] 📜 Cuộn danh sách đối thủ xuống...")
        self.actions.drag(sx, start_sy, sx, end_sy, steps=25)
        time.sleep(1.8)

    def run_tab(self, tab_name: str, tab_client_pt: Tuple[int, int]) -> int:
        """Quét và đấu toàn bộ các ải khả dụng trong một tab độ khó."""
        cf, orig = self.vision.grab_game_frame()
        tab_screen_pt = self._client_to_screen(tab_client_pt, orig)

        logger.info("[ARENA] === BƯỚC VÀO TAB '%s' ===", tab_name)
        self.actions.click(*tab_screen_pt)
        time.sleep(2.0)

        tab_wins = 0
        consecutive_empty_scrolls = 0
        max_empty_scrolls = 3

        while consecutive_empty_scrolls < max_empty_scrolls:
            cf, orig = self.vision.grab_game_frame()
            if self.dismiss_character_card_if_open(cf, orig):
                cf, orig = self.vision.grab_game_frame()

            buttons = self.find_visible_challenge_buttons(cf)

            if buttons:
                consecutive_empty_scrolls = 0
                target_btn = buttons[0]
                logger.info("[ARENA] Tìm thấy %d nút Thử thách. Đấu trận tại %s",
                            len(buttons), target_btn)
                success = self.fight_single_match(target_btn)
                if success:
                    tab_wins += 1
                else:
                    logger.warning("[ARENA] Trận đấu không hoàn thành đúng hạn.")
                self.wait_for_arena_screen()
            else:
                logger.info("[ARENA] Không thấy nút Thử thách trên màn hình hiện tại -> Cuộn xuống...")
                self.scroll_list_down(orig)
                consecutive_empty_scrolls += 1

        logger.info("[ARENA] Hoàn thành tab '%s': %d trận thắng.", tab_name, tab_wins)
        return tab_wins

    def run_hell_mode(self) -> Dict[str, int]:
        """Chiến đấu quét sạch toàn bộ ải Đấu trường NPC ở Cấp Địa Ngục."""
        logger.info("[ARENA] 🔥 BẮT ĐẦU CHIẾN DỊCH: QUÉT SẠCH CẤP ĐỊA NGỤC")
        wins = self.run_tab('Dia nguc', BTN_TAB_DIA_NGUC)
        summary = {
            'mode': 'Dia nguc',
            'battles_won': self.battles_won,
            'purchases_made': self.purchases_made,
        }
        logger.info("[ARENA] HOÀN TẤT CẤP ĐỊA NGỤC: Thắng %d trận, Nạp cờ %d lần.",
                    self.battles_won, self.purchases_made)
        return summary

    run = run_hell_mode
