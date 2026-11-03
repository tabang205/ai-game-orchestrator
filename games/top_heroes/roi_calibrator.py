"""
roi_calibrator.py — Công cụ hỗ trợ người dùng căn chỉnh trực quan vùng ROI (Top Heroes).
Hỗ trợ cả 2 profile: PC (16:9 Landscape - Cột chat ở giữa) và Mobile (Portrait).
Tự động xuất ảnh trực quan ra đĩa để người dùng kiểm tra độ khớp khung hình.
"""

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Optional, Tuple

import cv2
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from window_manager import find_game_window

logger = logging.getLogger(__name__)


def capture_window_client_rect(hwnd: int) -> Optional[Tuple[np.ndarray, Tuple[int, int, int, int]]]:
    """Chụp toàn bộ vùng hiển thị của cửa sổ game theo HWND."""
    import win32gui
    import win32ui

    rect = win32gui.GetClientRect(hwnd)
    w = rect[2] - rect[0]
    h = rect[3] - rect[1]
    if w <= 0 or h <= 0:
        return None

    pt_left_top = win32gui.ClientToScreen(hwnd, (0, 0))
    screen_rect = (pt_left_top[0], pt_left_top[1], w, h)

    hwnd_dc = win32gui.GetWindowDC(hwnd)
    mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
    save_dc = mfc_dc.CreateCompatibleDC()
    save_bitmap = win32ui.CreateBitmap()
    save_bitmap.CreateCompatibleBitmap(mfc_dc, w, h)
    save_dc.SelectObject(save_bitmap)

    import ctypes
    ctypes.windll.user32.PrintWindow(hwnd, save_dc.GetSafeHdc(), 2)

    bmp_info = save_bitmap.GetInfo()
    bmp_str = save_bitmap.GetBitmapBits(True)
    img = np.frombuffer(bmp_str, dtype="uint8").reshape((bmp_info["bmHeight"], bmp_info["bmWidth"], 4))
    bgr = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)

    win32gui.DeleteObject(save_bitmap.GetHandle())
    save_dc.DeleteDC()
    mfc_dc.DeleteDC()
    win32gui.ReleaseDC(hwnd, hwnd_dc)

    return bgr, screen_rect


def calibrate_and_visualize(
    config_path: Path,
    output_image_path: Path,
    sample_image_path: Optional[Path] = None,
    profile: Optional[str] = None
):
    """Vẽ bounding box của các vùng ROI lên khung hình và lưu ảnh kiểm chứng."""
    with open(config_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    prof_name = profile or cfg.get("active_profile", "pc")
    if "profiles" in cfg and prof_name in cfg["profiles"]:
        rois = cfg["profiles"][prof_name]
    else:
        rois = cfg["roi_config"]

    frame = None
    if sample_image_path and sample_image_path.exists():
        frame = cv2.imread(str(sample_image_path))
    else:
        target_win = find_game_window(tuple(cfg.get("window_keywords", [])))
        if target_win:
            hwnd, _, _ = target_win
            res = capture_window_client_rect(hwnd)
            if res:
                frame, _ = res

    if frame is None:
        logger.warning("Không tìm thấy cửa sổ game đang chạy hoặc ảnh mẫu để hiệu chuẩn!")
        return

    h, w = frame.shape[:2]
    vis = frame.copy()

    # 1. Vẽ ROI Chat Bag (Xanh lá)
    bag_cfg = rois["chat_bag_roi"]
    bx1 = int(bag_cfg["x_min_pct"] * w)
    bx2 = int(bag_cfg["x_max_pct"] * w)
    by1 = int(bag_cfg["y_min_pct"] * h)
    by2 = int(bag_cfg["y_max_pct"] * h)
    cv2.rectangle(vis, (bx1, by1), (bx2, by2), (0, 255, 0), 2)
    cv2.putText(vis, f"[{prof_name.upper()}] ROI: Tin Nhan Tui Loc", (bx1, max(20, by1 - 8)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 0), 1)

    # 2. Vẽ ROI Close Button (Đỏ)
    close_cfg = rois["close_btn_roi"]
    cx1 = int(close_cfg["x_min_pct"] * w)
    cx2 = int(close_cfg["x_max_pct"] * w)
    cy1 = int(close_cfg["y_min_pct"] * h)
    cy2 = int(close_cfg["y_max_pct"] * h)
    cv2.rectangle(vis, (cx1, cy1), (cx2, cy2), (0, 0, 255), 2)
    cv2.putText(vis, f"[{prof_name.upper()}] ROI: Nut X Do", (cx1 - 20, max(20, cy1 - 8)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 255), 1)

    cv2.imwrite(str(output_image_path), vis)
    logger.info("Đã xuất ảnh hiệu chuẩn ROI (%s) tại: %s", prof_name, output_image_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Top Heroes ROI Calibrator")
    parser.add_argument("--profile", choices=["pc", "mobile"], default="pc", help="Chọn profile kiểm tra")
    parser.add_argument("--sample", type=str, default=None, help="Đường dẫn ảnh mẫu tùy chọn")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    cfg_file = Path(__file__).resolve().parent / "config.json"
    out_file = Path(__file__).resolve().parent / "targets" / f"roi_{args.profile}_preview.jpg"
    
    sample_path = None
    if args.sample:
        sample_path = Path(args.sample)
    elif args.profile == "pc":
        sample_path = Path(__file__).resolve().parent / "pc_screenshot_chat.png"
    else:
        sample_path = Path(__file__).resolve().parent / "Screenshot_2026-10-28-10-50-07-90_c676d701da7838bc38d2514af32b80b7.jpg"

    calibrate_and_visualize(cfg_file, out_file, sample_path, args.profile)
