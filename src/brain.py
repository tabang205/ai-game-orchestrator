import json
import logging
import os
from dotenv import load_dotenv

from ai_client import UnifiedAIClient

load_dotenv()
logger = logging.getLogger("brain")

_ai_client = UnifiedAIClient()


def load_settings():
    """
    Đọc cấu hình theo thứ tự ưu tiên:
    1. Biến môi trường / .env  (an toàn hơn, ưu tiên)
    2. config/settings.json    (fallback nếu .env không tồn tại)
    """
    api_key = os.getenv('GEMINI_API_KEY')
    ocr_language = os.getenv('OCR_LANGUAGE', 'vi')

    if api_key:
        return {
            'gemini_api_key': api_key,
            'ocr_language': ocr_language,
        }

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config_path = os.path.join(base_dir, 'config', 'settings.json')

    with open(config_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def parse_user_prompt(user_prompt: str) -> dict:
    """Nhận câu lệnh tiếng Việt từ người dùng và gọi AI (Gemini -> Fallback Qwen2.5) để dịch ra JSON cấu hình."""
    if not user_prompt.strip():
        return {"error": "Câu lệnh nhập vào không được để trống"}

    system_instruction = (
        "Bạn là bộ não tối cao của hệ thống AI Game Agent. Nhiệm vụ của bạn là đọc yêu cầu bằng tiếng Việt của chủ nhân, "
        "sau đó phân tích ngữ cảnh để trả về một cấu trúc dữ liệu JSON duy nhất bao gồm các thông số điều khiển máy.\n\n"
        "Các trường JSON bắt buộc phải trả về:\n"
        "- 'game_target': Chuỗi chữ thường viết liền, là tên thư mục game được chỉ định trong câu lệnh (Ví dụ: 'ark_recode', 'top_heroes'). Nếu không nhắc tới game nào, mặc định là 'ark_recode'.\n"
        "- 'max_mana_to_spend': Số nguyên, lượng mana tối đa cho phép Agent tiêu trong ngày. Nếu không nhắc tới hoặc dùng từ 'xài sạch/hết', mặc định là -1.\n"
        "- 'keep_mana_minimum': Số nguyên, lượng mana tối thiểu phải giữ lại không được chạm vào cho chủ nhân tự chơi. Nếu không nhắc tới, mặc định là 0.\n"
        "- 'do_daily_quest': Giá trị Boolean (true/false), chủ nhân có muốn làm nhiệm vụ ngày hay không."
    )

    prompt = f"Yêu cầu của chủ nhân: \"{user_prompt}\""
    return _ai_client.generate_json_text(prompt, system_instruction)


def get_daily_command() -> dict:
    """Nhập lệnh trực tiếp từ bàn phím khi chạy interactive (hỗ trợ Enter để nạp prompt.txt)."""
    print("=" * 60)
    print(" TRÌNH ĐIỀU PHỐI AI GAME AGENT KHỞI ĐỘNG ".center(60, "="))
    print("=" * 60)

    prompt_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "prompt.txt")
    default_prompt = ""
    if os.path.exists(prompt_file):
        with open(prompt_file, "r", encoding="utf-8") as f:
            default_prompt = f.read().strip()

    prompt_hint = f" [Enter để dùng '{default_prompt}']" if default_prompt else ""
    user_input = input(f"\nNhập yêu cầu cày game của bạn hôm nay{prompt_hint}: ").strip()

    if not user_input and default_prompt:
        user_input = default_prompt
        print(f"-> Tự động nạp lệnh từ prompt.txt: \"{user_input}\"")

    print("\nĐang gửi câu lệnh cho AI phân tích ngữ cảnh...")
    return parse_user_prompt(user_input)


if __name__ == "__main__":
    result = get_daily_command()
    print("\n[CẤU TRÚC ĐIỀU KHIỂN SAU KHI AI DỊCH THÀNH CÔNG]:")
    print(json.dumps(result, indent=2, ensure_ascii=False))
