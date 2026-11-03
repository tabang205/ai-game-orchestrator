"""
crop_templates.py — Sinh template nhỏ từ ảnh full-screen 1920x1080 và tự kiểm tra độ phân biệt.

Mọi tọa độ (x, y, w, h) là tọa độ tuyệt đối trên ảnh desktop 1920x1080, với cửa sổ
"Ark ReCode" nằm tại vùng nội dung ~(410,127)→(1848,937). Chỉ crop chữ/nút UI cố định,
tránh HUD (số vàng/năng lượng thay đổi) và tranh nhân vật (đổi theo đội hình).

Chạy:
    python -X utf8 tools/crop_templates.py
"""

import logging
import sys
from pathlib import Path

import cv2
import numpy as np

PROJECT_ROOT = Path(__file__).parent.parent
TPL_DIR = PROJECT_ROOT / "games" / "ark_recode" / "templates"
SOURCE_SCREENS = ("lobby", "daily", "victory", "pop_up", "try_again_tasks",
                  "victory_in_pvp_or_pve", "battle_pass")
UNIQUENESS_THRESHOLD = 0.82

CROPS: dict[str, tuple[str, int, int, int, int]] = {
    "lobby_nav_labels":    ("lobby",                 470, 914, 1000, 32),
    "back_btn":            ("daily",                 418, 145, 175, 55),
    "daily_title":         ("daily",                 950, 188, 225, 48),
    "daily_go_btn":        ("daily",                 1420, 425, 155, 60),
    "victory_pve_loot":    ("victory",               1236, 503, 200, 36),
    "victory_pve_confirm": ("victory",               1575, 815, 175, 65),
    "victory_pvp_text":    ("victory_in_pvp_or_pve", 940, 395, 380, 72),
    "victory_pvp_end":     ("victory_in_pvp_or_pve", 1600, 830, 200, 65),
    "task_complete_title": ("try_again_tasks",       905, 275, 530, 45),
    "task_close_btn":      ("try_again_tasks",       900, 738, 185, 62),
    "task_retry_btn":      ("try_again_tasks",       1318, 750, 112, 44),
    "bp_title":            ("battle_pass",           818, 218, 240, 42),
    "bp_collect_btn":      ("battle_pass",           968, 842, 240, 72),
    "popup_pack_banner":   ("pop_up",                785, 732, 250, 40),
    "popup_noah_tab":      ("pop_up",                808, 232, 218, 68),
    "energy_icon":         ("lobby",                 1182, 146, 26, 32),
}

# Phần tử UI xuất hiện ở nhiều màn theo thiết kế (nút Quay lại, icon năng lượng trên HUD)
SHARED_TEMPLATES = {"back_btn", "energy_icon"}

logger = logging.getLogger("crop_templates")


def load_sources() -> dict[str, np.ndarray]:
    sources = {}
    for name in SOURCE_SCREENS:
        img = cv2.imread(str(TPL_DIR / f"{name}.png"))
        if img is None:
            raise FileNotFoundError(f"Thiếu ảnh nguồn: {TPL_DIR / name}.png")
        sources[name] = img
    return sources


def best_score(screen: np.ndarray, template: np.ndarray) -> float:
    return float(cv2.minMaxLoc(cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED))[1])


def crop_and_validate() -> int:
    sources = load_sources()
    collisions = 0
    for name, (src, x, y, w, h) in CROPS.items():
        template = sources[src][y:y + h, x:x + w]
        cv2.imwrite(str(TPL_DIR / f"{name}.png"), template)
        if name in SHARED_TEMPLATES:
            logger.info("%-20s %-22s center=(%d,%d)  SHARED", name, src, x + w // 2, y + h // 2)
            continue
        foreign_hits = {
            screen: score for screen, img in sources.items()
            if screen != src and (score := best_score(img, template)) >= UNIQUENESS_THRESHOLD
        }
        status = "OK" if not foreign_hits else f"KHỚP NHẦM {foreign_hits}"
        collisions += bool(foreign_hits)
        logger.info("%-20s %-22s center=(%d,%d)  %s", name, src, x + w // 2, y + h // 2, status)
    return collisions


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
    sys.exit(1 if crop_and_validate() else 0)
