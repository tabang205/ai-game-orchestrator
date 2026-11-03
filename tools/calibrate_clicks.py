"""
tools/calibrate_clicks.py — Đo tọa độ click thực tế khi game đang mở
======================================================================
Cách dùng:
    python tools/calibrate_clicks.py

Hướng dẫn:
    1. Mở game Ark Re-Code lên màn hình cần đo tọa độ
    2. Chạy script này
    3. Di chuột đến nút cần đo, nhấn SPACE để ghi tọa độ
    4. Nhấn Q để thoát, script tự cập nhật config.json

Phím tắt:
    SPACE  → ghi lại tọa độ chuột hiện tại
    Q      → thoát và lưu
    R      → chụp ảnh màn hình mới (refresh)
    C      → chạy auto-calibrate window (cần pywin32)
"""

import sys
import json
import time
from pathlib import Path
from datetime import datetime

import cv2
import numpy as np
import mss

try:
    import pydirectinput
    _HAS_PDI = True
except ImportError:
    _HAS_PDI = False

# ── Paths ─────────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent.parent
CONFIG_PATH  = PROJECT_ROOT / 'games' / 'ark_recode' / 'config.json'

# ── Mapping tên thân thiện → config key ──────────────────────────────────────
COORD_LABELS = {
    '1': ('daily_open_btn',      'Nút mở Nhật ký Ark / Nhiệm Vụ Hàng Ngày (từ Lobby)'),
    '2': ('back_btn',            'Nút "Quay lại" (góc trên trái các màn con)'),
    '3': ('daily_go_btn',        'Nút "Đi đến" (task đầu tiên chưa làm)'),
    '4': ('victory_pve_confirm', 'Nút "Xác nhận" màn Victory PvE'),
    '5': ('victory_pvp_end',     'Nút "Kết thúc" màn Victory PvP'),
    '6': ('task_retry_btn',      'Nút "Thử lại" màn Task Complete'),
    '7': ('task_close_btn',      'Nút "Đóng" màn Task Complete'),
    'q': ('__quit__',            'Thoát'),
}

def load_config():
    with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_config(cfg: dict):
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    print(f"  ✅ Đã lưu config: {CONFIG_PATH}")

def grab_frame() -> np.ndarray:
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

def get_mouse_pos():
    """Lấy tọa độ chuột hiện tại bằng ctypes (đã bật DPI-aware để khớp với mss)."""
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        ctypes.windll.user32.SetProcessDPIAware()
    class POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
    pt = POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y

def wait_for_key():
    """Đợi nhấn phím Enter trong console."""
    return input().strip().lower()

def main():
    print("="*60)
    print(" CALIBRATE CLICK COORDINATES ".center(60, "="))
    print("="*60)
    print("\nHướng dẫn:")
    print("  - Di chuột đến nút cần đo trong game")
    print("  - Nhập số tương ứng và nhấn Enter để ghi tọa độ")
    print("  - Nhập Q để thoát và lưu")
    print()

    cfg = load_config()
    if 'click_coords' not in cfg:
        cfg['click_coords'] = {}

    recorded = {}

    while True:
        print("\nChọn nút cần ghi tọa độ:")
        for key, (cfg_key, label) in COORD_LABELS.items():
            current = cfg.get('click_coords', {}).get(cfg_key, 'chưa có')
            marker = '✅' if cfg_key in recorded else '  '
            print(f"  [{key}] {marker} {label}")
            if current != 'chưa có':
                print(f"       Hiện tại: {current}")

        print()
        print(">> Di chuột đến nút cần đo, nhập số và nhấn Enter: ", end='', flush=True)
        choice = wait_for_key()

        if choice == 'q' or choice == '__quit__':
            break

        if choice == 'r':
            print("  📸 Chụp màn hình mới...")
            frame = grab_frame()
            ts = datetime.now().strftime('%Y%m%d_%H%M%S')
            out = PROJECT_ROOT / 'ark_recode_data' / f'calibrate_{ts}.png'
            cv2.imwrite(str(out), frame)
            print(f"  Đã lưu: {out}")
            continue

        if choice == 'c':
            try:
                import win32gui
                def cb(hwnd, res):
                    if win32gui.IsWindowVisible(hwnd):
                        t = win32gui.GetWindowText(hwnd)
                        if t and ('ark' in t.lower() or 'recode' in t.lower()):
                            res.append((t, win32gui.GetWindowRect(hwnd)))
                wins = []
                win32gui.EnumWindows(cb, wins)
                for title, rect in wins:
                    left, top, right, bottom = rect
                    print(f"  Window: '{title}' @ left={left} top={top} w={right-left} h={bottom-top}")
                    print(f"  Content area (trừ title bar): top={top+32} left={left+8} w={right-left-16} h={bottom-top-40}")
            except Exception as e:
                print(f"  ⚠️  {e} — thử cài: pip install pywin32")
            continue

        if choice not in COORD_LABELS:
            print(f"  ⚠️  Phím '{choice}' không hợp lệ.")
            continue

        cfg_key, label = COORD_LABELS[choice]

        # Đếm ngược 3 giây để user đặt chuột
        print(f"  → Ghi tọa độ cho: {label}")
        print("  Di chuột đến NÚT ĐÓ trong game, đếm ngược...")
        for i in range(3, 0, -1):
            print(f"  {i}...", end=' ', flush=True)
            time.sleep(1)
        print()

        x, y = get_mouse_pos()
        print(f"  📍 Tọa độ ghi được: ({x}, {y})")

        # Lưu vào dict và config
        cfg['click_coords'][cfg_key] = [x, y]
        recorded[cfg_key] = True
        print(f"  ✅ Đã ghi: {cfg_key} = [{x}, {y}]")

    # Lưu config
    save_config(cfg)

    print("\n" + "="*60)
    print("KẾT QUẢ CALIBRATE:")
    for cfg_key in recorded:
        coord = cfg['click_coords'][cfg_key]
        print(f"  {cfg_key}: {coord}")
    print("="*60)
    print("\n✅ Xong! Chạy validate_templates.py để kiểm tra lại.")


if __name__ == '__main__':
    main()
