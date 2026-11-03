"""
run_arena_npc.py — Script thực thi quét toàn bộ Đấu trường Thử thách NPC Cấp Địa Ngục (Ark Re-Code).
Tự động khóa tab Cấp Địa Ngục, tham chiến mọi ải khả dụng, nạp cờ bằng 100 Huy hiệu Hồng khi hết lượt.
"""

import ctypes
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

import json
import logging
import sys
import time
from pathlib import Path

# Đảm bảo UTF-8 cho Windows console
sys.stdout.reconfigure(encoding='utf-8')

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT / 'src'))
sys.path.insert(0, str(PROJECT_ROOT))

from core_actions import create_actions
from core_vision import create_vision
from games.ark_recode.arena_npc import ArenaNPCRunner, BTN_NPC_TAB_RIGHT, BTN_TAB_DIA_NGUC
from window_manager import focus_game_window

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(PROJECT_ROOT / 'ark_recode_data' / 'arena_bot.log', encoding='utf-8'),
    ]
)
logger = logging.getLogger('ArenaBot')


def ensure_arena_screen(vision, actions, orig) -> bool:
    """Đảm bảo đang ở màn hình Thử thách NPC và chọn thẳng Cấp Địa Ngục."""
    cf, _ = vision.grab_game_frame()
    items = vision.ocr.find_all_text(cf, min_score=0.6)
    norms = [i['norm'] for i in items]

    if not any('thu thach npc' in n for n in norms):
        logger.info("[NAV] Chưa ở màn hình Thử thách NPC. Bắt đầu điều hướng...")
        # Nếu ở sảnh chính
        if any(k in n for k in ['rank', 'battlepass', 'nhat ky ark'] for n in norms):
            logger.info("[NAV] Phát hiện đang ở Sảnh chính. Bấm F8 mở menu Chiến đấu...")
            actions.press_key('f8')
            time.sleep(2.0)
            cf, _ = vision.grab_game_frame()
            items = vision.ocr.find_all_text(cf, min_score=0.6)

        # Tìm và click Đấu trường
        arena_btn = vision.find_text_on_game(['Dau truong', 'Arena'])
        if arena_btn:
            logger.info("[NAV] Tìm thấy nút Đấu trường tại %s. Đang click...", arena_btn)
            actions.click(*arena_btn)
            time.sleep(2.5)

        # Click tab Thử thách NPC bên phải
        cf_arena, orig_arena = vision.grab_game_frame()
        npc_tab = (orig_arena[0] + BTN_NPC_TAB_RIGHT[0], orig_arena[1] + BTN_NPC_TAB_RIGHT[1])
        logger.info("[NAV] Click tab Thử thách NPC tại %s...", npc_tab)
        actions.click(*npc_tab)
        time.sleep(2.0)

    # Luôn chủ động chọn tab Cấp Địa Ngục
    cf_cur, orig_cur = vision.grab_game_frame()
    dia_nguc_pt = (orig_cur[0] + BTN_TAB_DIA_NGUC[0], orig_cur[1] + BTN_TAB_DIA_NGUC[1])
    logger.info("[NAV] 🎯 Tự động chọn Cấp Địa Ngục tại %s...", BTN_TAB_DIA_NGUC)
    actions.click(*dia_nguc_pt)
    time.sleep(1.5)

    cf_final, _ = vision.grab_game_frame()
    final_items = vision.ocr.find_all_text(cf_final, min_score=0.6)
    return any('thu thach npc' in i['norm'] for i in final_items)


def main():
    logger.info("=== KHỞI ĐỘNG BOT TỰ ĐỘNG THỬ THÁCH NPC ĐẤU TRƯỜNG ===")
    if not focus_game_window():
        logger.error("Không tìm thấy cửa sổ game 'Ark ReCode'!")
        return

    time.sleep(0.5)

    with open(PROJECT_ROOT / 'games/ark_recode/config.json', 'r', encoding='utf-8') as f:
        game_cfg = json.load(f)

    vision = create_vision('ark_recode')
    actions = create_actions(game_cfg)

    cf, orig = vision.grab_game_frame()
    if not ensure_arena_screen(vision, actions, orig):
        logger.error("Không thể điều hướng vào màn hình Thử thách NPC!")
        vision.close()
        return

    runner = ArenaNPCRunner(vision, actions, max_gem_purchases=10)
    summary = runner.run_hell_mode()

    logger.info("=== BÁO CÁO TỔNG KẾT CHIẾN DỊCH CẤP ĐỊA NGỤC ===")
    logger.info("Tổng số trận thắng Cấp Địa Ngục: %d", summary.get('battles_won', 0))
    logger.info("Số lần nạp cờ (bằng 100 Huy hiệu Hồng, không chạm kim cương 310): %d", summary.get('purchases_made', 0))

    vision.close()


if __name__ == '__main__':
    main()
