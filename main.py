"""
main.py — Điểm khởi động AI Game Agent
=======================================
Cách dùng:
    python main.py
    python main.py --prompt "Vào game Ark Re-Code làm hết nhiệm vụ ngày đi, xài tầm 300 mana thôi nha."
    python main.py --dry-run   (test parse brain, không thực sự chơi)
"""

import argparse
import json
import logging
import sys
from pathlib import Path

# ── Thêm src/ vào Python path ─────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT / 'src'))

from dotenv import load_dotenv
load_dotenv()


def enable_dpi_awareness() -> None:
    """mss chụp pixel vật lý; không bật DPI-aware thì click bị lệch khi Windows scale ≠ 100%."""
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        ctypes.windll.user32.SetProcessDPIAware()


enable_dpi_awareness()
(PROJECT_ROOT / 'ark_recode_data').mkdir(exist_ok=True)


# ══════════════════════════════════════════════════════════════════════════════
# Logging setup
# ══════════════════════════════════════════════════════════════════════════════

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(PROJECT_ROOT / 'ark_recode_data' / 'bot.log', encoding='utf-8'),
    ]
)
logger = logging.getLogger('main')


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════

def load_game_config(game_target: str) -> dict:
    """Đọc config.json của game."""
    config_path = PROJECT_ROOT / 'games' / game_target / 'config.json'
    if not config_path.exists():
        raise FileNotFoundError(f"Không tìm thấy config game: {config_path}")
    with open(config_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def get_game_agent_module(game_target: str):
    """
    Import động module states của game được chọn.
    Tránh import cứng để dễ mở rộng thêm game sau này.
    """
    import importlib.util
    states_path = PROJECT_ROOT / 'games' / game_target / 'states.py'
    if not states_path.exists():
        raise FileNotFoundError(f"Không tìm thấy states.py: {states_path}")

    spec = importlib.util.spec_from_file_location(f"{game_target}.states", states_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ══════════════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description='AI Game Agent — Ark Re-Code Daily Quest Bot')
    parser.add_argument(
        '--prompt', '-p',
        type=str,
        default=None,
        help='Câu lệnh tiếng Việt cho bot (nếu không truyền, sẽ hỏi thủ công)'
    )
    parser.add_argument(
        '--dry-run', '-d',
        action='store_true',
        help='Chỉ parse brain, hiển thị cấu hình rồi thoát (không thực sự click)'
    )
    parser.add_argument(
        '--game', '-g',
        type=str,
        default=None,
        help='Tên game target (override giá trị từ brain). Ví dụ: ark_recode'
    )
    parser.add_argument(
        '--max-mana', '-m',
        type=int,
        default=None,
        help='Giới hạn năng lượng tối đa tiêu trong phiên (-1 = không giới hạn). Truyền cờ này sẽ chạy thẳng không cần chờ Gemini NLP.'
    )
    parser.add_argument(
        '--keep-mana', '-k',
        type=int,
        default=0,
        help='Năng lượng tối thiểu giữ lại (mặc định: 0)'
    )
    args = parser.parse_args()

    # ── Bước 1: Lấy lệnh từ CLI hoặc Brain (Gemini NLP) ───────────────────
    from brain import parse_user_prompt, get_daily_command

    if args.max_mana is not None:
        bot_cfg = {
            'game_target': args.game or 'ark_recode',
            'max_mana_to_spend': args.max_mana,
            'keep_mana_minimum': args.keep_mana,
            'do_daily_quest': True,
        }
    elif args.prompt:
        user_prompt = args.prompt
        print(f"\n📝 Câu lệnh: {user_prompt}")
        print("🧠 Đang phân tích với Gemini...")
        bot_cfg = parse_user_prompt(user_prompt)
    else:
        bot_cfg = get_daily_command()

    # Kiểm tra lỗi từ brain
    if 'error' in bot_cfg:
        print(f"\n❌ Lỗi từ Brain: {bot_cfg['error']}")
        sys.exit(1)

    # Override game target nếu truyền qua CLI
    if args.game:
        bot_cfg['game_target'] = args.game

    print("\n📋 Cấu hình Bot sau khi Gemini phân tích:")
    print(json.dumps(bot_cfg, indent=2, ensure_ascii=False))

    # ── Bước 2: Xác định game target ──────────────────────────────────────
    game_target = bot_cfg.get('game_target', 'ark_recode')
    logger.info(f"Game target: {game_target}")

    # Chỉ hỗ trợ ark_recode hiện tại
    if game_target not in ('ark_recode',):
        print(f"\n⚠️  Game '{game_target}' chưa được hỗ trợ. Chỉ có: ark_recode")
        sys.exit(1)

    # ── Bước 3: Dry run → thoát sớm ───────────────────────────────────────
    if args.dry_run:
        print("\n[DRY RUN] ✅ Parse thành công. Bot sẽ KHÔNG thực sự chạy.")
        sys.exit(0)

    # ── Bước 4: Khởi tạo Vision + Actions ─────────────────────────────────
    from core_vision import create_vision
    from core_actions import create_actions

    print(f"\n🎮 Khởi tạo GameVision cho '{game_target}'...")
    game_cfg = load_game_config(game_target)
    vision  = create_vision(game_target)
    actions = create_actions(game_cfg)

    # ── Bước 5: Load FSM agent của game ───────────────────────────────────
    game_module = get_game_agent_module(game_target)
    agent = game_module.create_agent(vision, actions, game_cfg, bot_cfg)

    # ── Bước 6: Chạy FSM ──────────────────────────────────────────────────
    from window_manager import focus_game_window

    print(f"\n🔍 Đang kiểm tra và kích hoạt cửa sổ game...")
    focused = focus_game_window()
    if not focused:
        print("💡 Lưu ý: Hãy đảm bảo cửa sổ game Ark Re-Code đang hiển thị trên màn hình!")

    print(f"\n🚀 Bot bắt đầu chạy! Nhấn Ctrl+C để dừng thủ công.\n")
    logger.info("Bot started.")

    try:
        summary = agent.run()
        logger.info(f"Bot finished: {summary}")
        print("\n✅ Bot kết thúc bình thường.")

    except KeyboardInterrupt:
        print("\n\n⛔ Người dùng nhấn Ctrl+C — Bot dừng lại.")
        vision.close()
        sys.exit(0)

    except Exception as e:
        logger.exception(f"Bot crashed: {e}")
        print(f"\n❌ Bot bị lỗi nghiêm trọng: {e}")
        vision.close()
        sys.exit(1)


if __name__ == '__main__':
    main()
