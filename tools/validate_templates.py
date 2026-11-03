"""
tools/validate_templates.py — Kiểm tra độ chính xác của từng template
======================================================================
Chạy khi game đang mở ở đúng màn hình cần test.

Dùng:
    python tools/validate_templates.py --screen lobby
    python tools/validate_templates.py --screen daily
    python tools/validate_templates.py --all
    python tools/validate_templates.py --calibrate   (tìm window bounds tự động)

Output:
    - In score từng template ra console
    - Lưu ảnh debug overlay vào ark_recode_data/debug_<timestamp>.png
"""

import sys
import os
import json
import time
import argparse
from pathlib import Path
from datetime import datetime

# Thêm src/ vào path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / 'src'))

import cv2
import numpy as np
import mss

# ── Load config ──────────────────────────────────────────────────────────────

def load_config():
    cfg_path = PROJECT_ROOT / 'games' / 'ark_recode' / 'config.json'
    with open(cfg_path, 'r', encoding='utf-8') as f:
        return json.load(f)

# ── Screen capture ────────────────────────────────────────────────────────────

def grab_fullscreen() -> np.ndarray:
    try:
        import ctypes
        user32 = ctypes.windll.user32
        hdesk = user32.OpenInputDesktop(0, False, 0x01FF)
        if hdesk:
            user32.SetThreadDesktop(hdesk)
    except Exception:
        pass
    with mss.mss() as sct:
        monitor = sct.monitors[1]
        shot = sct.grab(monitor)
        frame = np.array(shot)
        return cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)

# ── Template match với score ──────────────────────────────────────────────────

def match_template(frame: np.ndarray, tpl_path: Path):
    """Trả về (score, top_left_x, top_left_y, w, h) hoặc None nếu không load được."""
    if not tpl_path.exists():
        return None

    tpl = cv2.imread(str(tpl_path), cv2.IMREAD_COLOR)
    if tpl is None:
        return None

    result = cv2.matchTemplate(frame, tpl, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(result)
    h, w = tpl.shape[:2]
    return (max_val, max_loc[0], max_loc[1], w, h)

# ── Calibrate: tự phát hiện vị trí cửa sổ game ──────────────────────────────

def calibrate_window():
    """
    Tìm vị trí cửa sổ game Ark Re-Code bằng cách:
    1. Dùng win32gui để tìm window theo title
    2. Fallback: scan pixel để tìm viền
    """
    print("\n[CALIBRATE] Đang tìm cửa sổ Ark Re-Code...")

    try:
        import win32gui, win32con

        def enum_windows_callback(hwnd, result):
            if win32gui.IsWindowVisible(hwnd):
                title = win32gui.GetWindowText(hwnd)
                if title and ('ark' in title.lower() or 'recode' in title.lower()
                              or 'arc' in title.lower()):
                    rect = win32gui.GetWindowRect(hwnd)
                    result.append({'title': title, 'rect': rect, 'hwnd': hwnd})

        windows = []
        win32gui.EnumWindows(enum_windows_callback, windows)

        if windows:
            for w in windows:
                left, top, right, bottom = w['rect']
                width  = right - left
                height = bottom - top
                print(f"  ✅ Tìm thấy: '{w['title']}' @ ({left},{top}) size={width}x{height}")

            # Lấy cửa sổ đầu tiên tìm được
            best = windows[0]
            left, top, right, bottom = best['rect']
            # Bỏ qua title bar (~32px) và border (~8px)
            content_top  = top + 32
            content_left = left + 8
            content_w    = (right - left) - 16
            content_h    = (bottom - top) - 40

            print(f"\n[CALIBRATE] ➡️  Đề xuất screen_region:")
            print(f'  "screen_region": {{')
            print(f'    "top": {content_top},')
            print(f'    "left": {content_left},')
            print(f'    "width": {content_w},')
            print(f'    "height": {content_h}')
            print(f'  }}')
            return {'top': content_top, 'left': content_left, 'width': content_w, 'height': content_h}
        else:
            print("  ⚠️  Không tìm thấy cửa sổ có tên 'ark/recode'. Đang dùng toàn màn hình.")

    except ImportError:
        print("  ⚠️  win32gui chưa cài (pip install pywin32). Thử cách thủ công...")
        print("  → Gợi ý: chạy với --calibrate sau khi cài: pip install pywin32")

    return None

# ── Vẽ overlay lên ảnh debug ─────────────────────────────────────────────────

def draw_overlay(frame: np.ndarray, key: str, score: float, x: int, y: int, w: int, h: int, threshold: float):
    """Vẽ rectangle + text lên frame."""
    color = (0, 255, 0) if score >= threshold else (0, 100, 255)
    cv2.rectangle(frame, (x, y), (x + w, y + h), color, 2)
    label = f"{key}: {score:.3f}"
    cv2.putText(frame, label, (x, max(y - 6, 15)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2, cv2.LINE_AA)

# ── Main validate logic ───────────────────────────────────────────────────────

def run_validate(args):
    cfg     = load_config()
    tpls    = cfg.get('templates', {})
    thresh  = cfg.get('match_threshold', 0.82)

    # Lọc template cần test
    if args.screen:
        screen_map = {
            'lobby':    ['lobby_nav_labels', 'energy_icon'],
            'daily':    ['daily_title', 'daily_go_btn', 'back_btn', 'energy_icon'],
            'victory':  ['victory_pve_loot', 'victory_pve_confirm', 'victory_pvp_text', 'victory_pvp_end'],
            'task':     ['task_complete_title', 'task_retry_btn', 'task_close_btn'],
            'popup':    ['popup_pack_banner', 'popup_noah_tab'],
            'bp':       ['bp_title', 'bp_collect_btn', 'back_btn'],
        }
        keys_to_test = screen_map.get(args.screen, list(tpls.keys()))
    else:
        keys_to_test = [k for k in tpls.keys() if k != 'comment']

    print(f"\n[VALIDATE] Chụp màn hình... (game phải đang mở đúng màn hình cần test!)")
    time.sleep(0.5)
    frame = grab_fullscreen()
    debug_frame = frame.copy()

    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    print(f"[VALIDATE] Frame size: {frame.shape[1]}x{frame.shape[0]}")
    print(f"\n{'─'*65}")
    print(f"{'Template Key':<28} {'Score':>7}  {'Status':<12}  {'Location'}")
    print(f"{'─'*65}")

    passed = 0
    failed = 0
    missing = 0

    for key in keys_to_test:
        if key == 'comment':
            continue
        rel_path = tpls.get(key)
        if not rel_path:
            print(f"  {'⚠️ ':2} {key:<26} {'N/A':>7}  key không có trong config")
            missing += 1
            continue

        tpl_path = PROJECT_ROOT / rel_path
        res = match_template(frame, tpl_path)

        if res is None:
            print(f"  {'❌':2} {key:<26} {'FILE':>7}  ← File không tồn tại: {rel_path}")
            missing += 1
            continue

        score, x, y, w, h = res
        cx, cy = x + w // 2, y + h // 2

        if score >= thresh:
            status = '✅ PASS'
            passed += 1
            draw_overlay(debug_frame, key, score, x, y, w, h, thresh)
        else:
            status = f'❌ FAIL (need ≥{thresh})'
            failed += 1
            draw_overlay(debug_frame, key, score, x, y, w, h, thresh)

        print(f"  {status:<12} {key:<26} {score:>7.4f}   @ ({cx},{cy})")

    print(f"{'─'*65}")
    print(f"\n  ✅ PASS: {passed}  |  ❌ FAIL: {failed}  |  ⚠️  MISSING: {missing}")
    print(f"  Threshold hiện tại: {thresh}")

    # Lưu ảnh debug
    out_dir = PROJECT_ROOT / 'ark_recode_data'
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / f'debug_validate_{ts}.png'
    cv2.imwrite(str(out_path), debug_frame)
    print(f"\n  📸 Ảnh debug đã lưu: {out_path}")

    if failed > 0:
        print("\n  💡 Gợi ý khi FAIL:")
        print("     1. Đảm bảo game đang mở đúng màn hình cần test")
        print("     2. Giảm threshold trong config.json (ví dụ: 0.75)")
        print("     3. Chạy tools/crop_templates.py để crop lại template từ screenshot mới")
        print("     4. Kiểm tra độ phân giải/scale DPI Windows có thay đổi không")


def run_calibrate(args):
    calibrate_window()


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Template Validator — Ark Re-Code Bot')
    parser.add_argument('--screen', '-s',
                        choices=['lobby', 'daily', 'victory', 'task', 'popup', 'bp'],
                        help='Chỉ test templates của màn hình này')
    parser.add_argument('--all', '-a', action='store_true',
                        help='Test tất cả templates')
    parser.add_argument('--calibrate', '-c', action='store_true',
                        help='Tự động phát hiện vị trí cửa sổ game')
    args = parser.parse_args()

    if args.calibrate:
        run_calibrate(args)
    else:
        run_validate(args)
