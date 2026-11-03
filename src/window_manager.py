"""
src/window_manager.py — Tự động tìm kiếm và focus cửa sổ game Ark Re-Code
========================================================================
Hỗ trợ kích hoạt cửa sổ game lên Foreground trước khi bot bắt đầu thực thi.
"""

import logging
import os
import time
from typing import Optional, Tuple
import ctypes

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except (AttributeError, OSError):
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


logger = logging.getLogger("window_manager")

try:
    import win32gui
    import win32con
    import win32process
    _HAS_WIN32 = True
except ImportError:
    _HAS_WIN32 = False

DEFAULT_EXCLUDE_KEYWORDS = (
    "snatcher",
    "assistant",
    "orchestrator",
    "ai_game_orchestrator",
    "visual studio code",
    "windows powershell",
    "cmd.exe",
)


def find_game_window(
    keywords: tuple = ("Ark ReCode", "Ark", "ReCode"),
    exclude_keywords: tuple = DEFAULT_EXCLUDE_KEYWORDS,
) -> Optional[Tuple[int, str, Tuple[int, int, int, int]]]:
    """
    Tìm kiếm cửa sổ game theo danh sách từ khóa tiêu đề.
    Tự động loại trừ cửa sổ của chính tiến trình bot và các cửa sổ công cụ/trợ lý.
    """
    try:
        user32 = ctypes.windll.user32
        hdesk = user32.OpenInputDesktop(0, False, 0x01FF)
        if hdesk:
            user32.SetThreadDesktop(hdesk)
    except Exception:
        pass

    if not _HAS_WIN32:
        logger.warning("[WINDOW] pywin32 chưa được cài đặt. Bỏ qua tìm kiếm cửa sổ.")
        return None

    current_pid = os.getpid()
    matches = []

    def enum_cb(hwnd: int, extra) -> bool:
        if not win32gui.IsWindowVisible(hwnd):
            return True

        title = win32gui.GetWindowText(hwnd).strip()
        if not title:
            return True

        # Tránh gắn nhầm vào chính giao diện GUI của bot
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            if pid == current_pid:
                return True
        except Exception:
            pass

        title_lower = title.lower()
        if any(ex in title_lower for ex in exclude_keywords):
            return True

        for kw in keywords:
            if kw.lower() in title_lower:
                rect = win32gui.GetWindowRect(hwnd)
                w = rect[2] - rect[0]
                h = rect[3] - rect[1]
                is_iconic = win32gui.IsIconic(hwnd)
                if (w > 300 and h > 200) or is_iconic:
                    matches.append((hwnd, title, rect))
                    break
        return True

    try:
        win32gui.EnumWindows(enum_cb, None)
    except Exception as e:
        logger.debug("EnumWindows exception: %s", e)

    if not matches:
        return None

    # Ưu tiên cửa sổ đang hiển thị bình thường trước cửa sổ iconic
    matches.sort(
        key=lambda m: (
            not win32gui.IsIconic(m[0]),
            (m[2][2] - m[2][0]) * (m[2][3] - m[2][1]),
        ),
        reverse=True,
    )
    return matches[0]


def focus_game_window(
    keywords: tuple = ("Ark ReCode", "Ark", "ReCode"),
    exclude_keywords: tuple = DEFAULT_EXCLUDE_KEYWORDS,
) -> bool:
    """
    Tìm và đưa cửa sổ game lên Foreground.
    Sử dụng kỹ thuật Alt-key bypass để đảm bảo Windows luôn cấp quyền Foreground.
    """
    if not _HAS_WIN32:
        return False

    target = find_game_window(keywords, exclude_keywords=exclude_keywords)
    if not target:
        logger.warning("[WINDOW] ⚠️ Không tìm thấy cửa sổ game '%s' đang chạy.", keywords[0])
        return False

    hwnd, title, rect = target
    logger.info("[WINDOW] ✅ Tìm thấy cửa sổ: '%s' (HWND: %s) @ %s", title, hwnd, rect)

    try:
        import ctypes
        user32 = ctypes.windll.user32
        
        # Nhấn phím ALT ảo để Windows cấp quyền chuyển Foreground
        user32.keybd_event(0x12, 0, 0, 0)
        time.sleep(0.03)

        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            time.sleep(0.2)

        win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
        # Ép cửa sổ nổi lên trên cùng (Topmost) để vượt qua các ứng dụng fullscreen/maximize
        win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0,
                              win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_SHOWWINDOW)
        time.sleep(0.08)
        win32gui.SetWindowPos(hwnd, win32con.HWND_NOTOPMOST, 0, 0, 0, 0,
                              win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_SHOWWINDOW)
        win32gui.SetForegroundWindow(hwnd)
        time.sleep(0.05)
        
        # Thả phím ALT
        user32.keybd_event(0x12, 0, 2, 0)
        time.sleep(0.3)
        logger.info("[WINDOW] 🎯 Đã kích hoạt cửa sổ game lên Foreground.")
        return True
    except Exception as e:
        logger.warning("[WINDOW] ⚠️ Không thể SetForegroundWindow: %s", e)
        return False


def get_game_client_geometry(keywords: tuple = ("Ark ReCode", "Ark", "ReCode")) -> Optional[Tuple[int, int, int, int]]:
    """
    Trả về (screen_x, screen_y, width, height) của vùng Client (khu vực render game thực tế,
    không bao gồm thanh tiêu đề và viền cửa sổ).
    """
    if not _HAS_WIN32:
        return None
    target = find_game_window(keywords)
    if not target:
        return None
    hwnd = target[0]
    try:
        origin = win32gui.ClientToScreen(hwnd, (0, 0))
        cr = win32gui.GetClientRect(hwnd)
        w = cr[2] - cr[0]
        h = cr[3] - cr[1]
        if w > 0 and h > 0:
            return (origin[0], origin[1], w, h)
    except Exception as e:
        logger.debug("Lỗi lấy ClientGeometry: %s", e)
    return None

