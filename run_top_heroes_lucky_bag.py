"""
run_top_heroes_lucky_bag.py — Script thực thi theo dõi và giật Túi Lộc siêu tốc (Top Heroes).
Hỗ trợ cả 2 profile: PC (16:9 Landscape - Cột chat ở giữa) và Mobile (Portrait).
"""

import argparse
import ctypes
import json
import logging
import sys
import time
from pathlib import Path

# Đảm bảo UTF-8 cho Windows console
sys.stdout.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT))

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

import cv2
from games.top_heroes.fast_snatcher import (
    BagDetector,
    CaravanDetector,
    CloseModalDetector,
    FastCapture,
    FastInput,
    TopHeroesLuckyBagRunner,
)
from games.top_heroes.roi_calibrator import calibrate_and_visualize
from window_manager import find_game_window, focus_game_window

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s.%(msecs)03d [%(levelname)-5s] [%(name)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(PROJECT_ROOT / "games/top_heroes/snatcher.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("TopHeroesSnatcher")


def run_test_images(profile_to_test: str = "all"):
    """Kiểm thử thuật toán và tọa độ khung hình trên cả ảnh PC và ảnh Mobile."""
    game_dir = PROJECT_ROOT / "games/top_heroes"
    cfg_path = game_dir / "config.json"
    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    target_dir = game_dir / "targets"
    bag_detector = BagDetector(target_dir, cfg)
    close_detector = CloseModalDetector(target_dir, cfg)

    # 1. Kiểm tra Bản PC (nếu yêu cầu)
    if profile_to_test in ("all", "pc"):
        logger.info("=== KIỂM THỬ KHUNG TỌA ĐỘ TRÊN BẢN PC (16:9 LANDSCAPE) ===")
        pc_chat_path = game_dir / "pc_screenshot_chat.png"
        pc_modal_path = game_dir / "pc_screenshot_modal.png"
        if pc_chat_path.exists() and pc_modal_path.exists():
            img_pc1 = cv2.imread(str(pc_chat_path))
            img_pc2 = cv2.imread(str(pc_modal_path))
            h, w = img_pc1.shape[:2]
            rois = cfg["profiles"]["pc"]

            # Vùng ROI Túi Lộc trên PC
            b_cfg = rois["chat_bag_roi"]
            by1, by2 = int(b_cfg["y_min_pct"] * h), int(b_cfg["y_max_pct"] * h)
            bx1, bx2 = int(b_cfg["x_min_pct"] * w), int(b_cfg["x_max_pct"] * w)
            roi_pc_bag = img_pc1[by1:by2, bx1:bx2]

            logger.info("[PC ROI Túi Lộc] X: [%d, %d] (%.1f%% - %.1f%%), Y: [%d, %d] (%.1f%% - %.1f%%)",
                        bx1, bx2, b_cfg["x_min_pct"]*100, b_cfg["x_max_pct"]*100,
                        by1, by2, b_cfg["y_min_pct"]*100, b_cfg["y_max_pct"]*100)

            # Vùng ROI Nút X Đỏ trên PC
            c_cfg = rois["close_btn_roi"]
            cy1, cy2 = int(c_cfg["y_min_pct"] * h), int(c_cfg["y_max_pct"] * h)
            cx1, cx2 = int(c_cfg["x_min_pct"] * w), int(c_cfg["x_max_pct"] * w)
            roi_pc_close = img_pc2[cy1:cy2, cx1:cx2]

            close_pos = close_detector.locate_close_button(roi_pc_close)
            if close_pos:
                clx, cly = close_pos
                logger.info("[PC Nút X Đỏ] ✅ BẮT TRÚNG CHÍNH XÁC NÚT X ĐỎ! Tọa độ PC: (%d, %d)",
                            cx1 + clx, cy1 + cly)
            else:
                logger.error("[PC Nút X Đỏ] ❌ Thất bại: Không tìm thấy nút X đỏ trong ROI PC!")

        # Kiểm tra phát hiện nút Gia Nhập Thương Đội (Caravan Sample)
        caravan_sample = game_dir / "pc_caravan_sample.png"
        if caravan_sample.exists():
            img_caravan = cv2.imread(str(caravan_sample))
            h, w = img_caravan.shape[:2]
            c_cfg = cfg["profiles"]["pc"].get("chat_caravan_roi", cfg["profiles"]["pc"]["chat_bag_roi"])
            cy1, cy2 = int(c_cfg["y_min_pct"] * h), int(c_cfg["y_max_pct"] * h)
            cx1, cx2 = int(c_cfg["x_min_pct"] * w), int(c_cfg["x_max_pct"] * w)
            roi_c = img_caravan[cy1:cy2, cx1:cx2]
            caravan_det = CaravanDetector(cfg, target_dir)
            c_pos = caravan_det.detect_join_button(roi_c)
            if c_pos:
                cx, cy, c_type = c_pos
                type_name = "Thương Đội Đỏ Thường (Ngựa đỏ)" if c_type == "regular" else "Thương Đội Mùa Giải (Không ngựa đỏ)"
                logger.info("[PC Thương Đội] ✅ BẮT TRÚNG NÚT GIA NHẬP! Loại: %s, Tọa độ PC: (%d, %d)",
                            type_name, cx1 + cx, cy1 + cy)
            else:
                logger.error("[PC Thương Đội] ❌ Thất bại: Không tìm thấy nút Gia Nhập!")

        # Kiểm tra loại trừ thẻ Nhà Tí Tách (Anti-False-Positive)
        fp_sample = game_dir / "false_positive_nha_ti_tach.png"
        if fp_sample.exists():
            img_fp = cv2.imread(str(fp_sample))
            caravan_det = CaravanDetector(cfg, target_dir)
            fp_pos = caravan_det.detect_join_button(img_fp)
            if fp_pos is None:
                logger.info("[Anti-False-Positive] ✅ CHẶN THÀNH CÔNG: Thẻ 'Nhà Tí Tách' bị từ chối 100%%, không nhận nhầm!")
            else:
                logger.error("[Anti-False-Positive] ❌ Thất bại: Thẻ 'Nhà Tí Tách' vẫn bị nhận nhầm thành %s!", fp_pos[2])

    # 2. Kiểm tra Bản Mobile (nếu yêu cầu)
    if profile_to_test in ("all", "mobile"):
        logger.info("=== KIỂM THỬ KHUNG TỌA ĐỘ TRÊN BẢN MOBILE (PORTRAIT) ===")
        m_chat_path = game_dir / "Screenshot_2026-10-28-10-50-07-90_c676d701da7838bc38d2514af32b80b7.jpg"
        m_modal_path = game_dir / "Screenshot_2026-10-28-10-50-13-64_c676d701da7838bc38d2514af32b80b7.jpg"
        if m_chat_path.exists() and m_modal_path.exists():
            img_m1 = cv2.imread(str(m_chat_path))
            img_m2 = cv2.imread(str(m_modal_path))
            h, w = img_m1.shape[:2]
            rois = cfg["profiles"]["mobile"]

            b_cfg = rois["chat_bag_roi"]
            by1, by2 = int(b_cfg["y_min_pct"] * h), int(b_cfg["y_max_pct"] * h)
            bx1, bx2 = int(b_cfg["x_min_pct"] * w), int(b_cfg["x_max_pct"] * w)
            roi_m_bag = img_m1[by1:by2, bx1:bx2]

            res_m = bag_detector.detect_bag(roi_m_bag)
            if res_m:
                cx, cy, score = res_m
                logger.info("[Mobile Túi Lộc] ✅ PHÁT HIỆN TÚI LỘC! Tọa độ: (%d, %d), Điểm: %.4f",
                            bx1 + cx, by1 + cy, score)

            c_cfg = rois["close_btn_roi"]
            cy1, cy2 = int(c_cfg["y_min_pct"] * h), int(c_cfg["y_max_pct"] * h)
            cx1, cx2 = int(c_cfg["x_min_pct"] * w), int(c_cfg["x_max_pct"] * w)
            roi_m_close = img_m2[cy1:cy2, cx1:cx2]

            close_pos_m = close_detector.locate_close_button(roi_m_close)
            if close_pos_m:
                clx, cly = close_pos_m
                logger.info("[Mobile Nút X Đỏ] ✅ BẮT TRÚNG NÚT X ĐỎ! Tọa độ: (%d, %d)",
                            cx1 + clx, cy1 + cly)


def run_benchmark():
    """Đo lường tốc độ khung hình và độ trễ nhận diện."""
    logger.info("=== BENCHMARK HIỆU NĂNG NHẬN DIỆN VÀ MÔ PHỎNG CHẠM ===")
    game_dir = PROJECT_ROOT / "games/top_heroes"
    cfg_path = game_dir / "config.json"
    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    target_dir = game_dir / "targets"
    bag_detector = BagDetector(target_dir, cfg)
    close_detector = CloseModalDetector(target_dir, cfg)
    fast_input = FastInput()

    img_pc2 = cv2.imread(str(game_dir / "pc_screenshot_modal.png"))
    h, w = img_pc2.shape[:2]
    c_cfg = cfg["profiles"]["pc"]["close_btn_roi"]
    close_roi = img_pc2[int(c_cfg["y_min_pct"]*h):int(c_cfg["y_max_pct"]*h),
                        int(c_cfg["x_min_pct"]*w):int(c_cfg["x_max_pct"]*w)]

    iters = 1000
    t0 = time.perf_counter()
    for _ in range(iters):
        close_detector.locate_close_button(close_roi)
    t1 = time.perf_counter()
    avg_close_ms = (t1 - t0) / iters * 1000
    logger.info("[BENCHMARK PC] Độ trễ nhận diện Nút X Đỏ: %.3f ms (Tương đương %.0f FPS)",
                avg_close_ms, 1000 / avg_close_ms)

    t0 = time.perf_counter()
    for _ in range(iters):
        fast_input.click_screen(500, 500)
    t1 = time.perf_counter()
    avg_click_ms = (t1 - t0) / iters * 1000
    logger.info("[BENCHMARK PC] Độ trễ thực thi lệnh click Windows API: %.4f ms", avg_click_ms)


def run_live(
    profile: str = "pc",
    target_bags: int = 0,
    enable_caravan_regular: bool = True,
    enable_caravan_season: bool = True,
):
    """Khởi động vòng lặp theo dõi trực tiếp trên cửa sổ game."""
    target_str = str(target_bags) if target_bags > 0 else "Không giới hạn"
    logger.info("=== KHỞI ĐỘNG BOT THEO DÕI TÚI LỘC SIÊU TỐC TOP HEROES (Profile: %s, Chỉ tiêu: %s) ===",
                profile.upper(), target_str)
    game_dir = PROJECT_ROOT / "games/top_heroes"
    cfg_path = game_dir / "config.json"
    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    cfg["active_profile"] = profile
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)

    keywords = tuple(cfg.get("window_keywords", ["Top Heroes", "LDPlayer", "BlueStacks"]))
    target = find_game_window(keywords)
    if not target:
        logger.error("Không tìm thấy cửa sổ game/giả lập với từ khóa: %s", keywords)
        logger.info("Gợi ý: Mở cửa sổ game Top Heroes trước khi chạy bot.")
        return

    hwnd, title, rect = target
    logger.info("Đã kết nối cửa sổ game: '%s' (HWND: %s) tại tọa độ %s", title, hwnd, rect)
    focus_game_window(keywords)
    time.sleep(0.5)

    w = rect[2] - rect[0]
    h = rect[3] - rect[1]
    window_rect = (rect[0], rect[1], w, h)

    runner = TopHeroesLuckyBagRunner(
        cfg_path,
        window_rect,
        hwnd,
        target_bags=target_bags,
        enable_caravan_regular=enable_caravan_regular,
        enable_caravan_season=enable_caravan_season,
    )
    logger.info("🟢 BOT ĐANG THEO DÕI VÙNG TIN NHẮN MỚI NHẤT LIÊN TỤC...")
    logger.info("Nhấn Ctrl + C để dừng bot.")

    total_snatches = 0
    try:
        while True:
            snatched = runner.scan_and_snatch_once()
            if snatched:
                total_snatches += 1
                logger.info("🎉 Đã giật thành công: %d/%s túi", total_snatches, target_str)
                if target_bags > 0 and total_snatches >= target_bags:
                    logger.info("🎉 ĐÃ HOÀN THÀNH CHỈ TIÊU %d TÚI LỘC! Tự động dừng an toàn.", target_bags)
                    break
            time.sleep(0.002)
    except KeyboardInterrupt:
        logger.info("Người dùng yêu cầu dừng bot. Tổng kết: %d túi đã giật.", total_snatches)
    finally:
        runner.close()


def main():
    parser = argparse.ArgumentParser(description="Top Heroes Lucky Bag Fast Snatcher")
    parser.add_argument("--gui", action="store_true", help="Mở giao diện Tkinter theo dõi thời gian thực")
    parser.add_argument("--live", action="store_true", help="Chạy bot trực tiếp trên terminal")
    parser.add_argument("--profile", choices=["pc", "mobile"], default="pc", help="Chọn profile (pc hoặc mobile)")
    parser.add_argument("--target-bags", "-n", type=int, default=0, help="Chỉ tiêu số túi muốn nhận (0 = không giới hạn)")
    parser.add_argument("--test-images", action="store_true", help="Chạy test trên ảnh mẫu")
    parser.add_argument("--benchmark", action="store_true", help="Đo lường benchmark độ trễ")
    parser.add_argument("--calibrate", action="store_true", help="Xuất ảnh hiệu chuẩn ROI")
    parser.add_argument("--no-caravan-regular", action="store_true", help="Không tự gia nhập thương đội đỏ thường (ngựa đỏ)")
    parser.add_argument("--no-caravan-season", action="store_true", help="Không tự gia nhập thương đội mùa giải")

    args = parser.parse_args()

    if args.gui:
        from games.top_heroes.gui_monitor import main as run_gui
        run_gui()
    elif args.benchmark:
        run_benchmark()
    elif args.test_images:
        run_test_images(args.profile)
    elif args.calibrate:
        cfg_file = PROJECT_ROOT / "games/top_heroes/config.json"
        out_file = PROJECT_ROOT / "games/top_heroes/targets" / f"roi_{args.profile}_preview.jpg"
        calibrate_and_visualize(cfg_file, out_file, profile=args.profile)
    elif args.live:
        run_live(
            args.profile,
            target_bags=args.target_bags,
            enable_caravan_regular=not args.no_caravan_regular,
            enable_caravan_season=not args.no_caravan_season,
        )
    else:
        # Nếu không có tham số nào, mặc định mở giao diện GUI Tkinter tiện dụng
        from games.top_heroes.gui_monitor import main as run_gui
        run_gui()


if __name__ == "__main__":
    main()
