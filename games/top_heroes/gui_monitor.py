"""
gui_monitor.py — Giao diện Tkinter theo dõi thời gian thực cho Top Heroes.
Tính năng:
  - Tự động bắt Túi Lộc siêu tốc (0.14ms) và tự động đóng popup kết quả.
  - Tự động gia nhập Thương Đội (Caravan Auto-Join) khi phát hiện tin nhắn đỏ có nút Gia Nhập xanh.
  - Khung ROI chuẩn xác dựa trên ClientToScreen (loại bỏ độ lệch do thanh tiêu đề/viền cửa sổ).
  - Đếm số túi đã nhận và chỉ tiêu dừng an toàn (Target Quota).
  - Đếm số Thương Đội đã gia nhập thành công.
  - Nhật ký hoạt động chỉ xuất ra Terminal và tệp snatcher.log theo chuẩn quốc tế RFC 5424 / ISO 8601.
  - Giao diện tinh gọn, không chiếm dụng không gian màn hình trò chơi.
"""

import ctypes
import json
import logging
import queue
import sys
import threading
import time
import winsound
from pathlib import Path
from typing import Optional, Tuple

import cv2
import numpy as np
from PIL import Image, ImageTk
import tkinter as tk
from tkinter import ttk, messagebox

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT))

# Cấu hình logging chuẩn quốc tế RFC 5424 / ISO 8601 xuất trực tiếp ra Terminal và file
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

try:
    import win32gui
    import win32con
    _HAS_WIN32 = True
except ImportError:
    _HAS_WIN32 = False

from games.top_heroes.fast_snatcher import (
    BagDetector,
    CaravanDetector,
    CloseModalDetector,
    FastCapture,
    FastInput,
    TopHeroesLuckyBagRunner,
)
from window_manager import find_game_window, focus_game_window

VK_F9 = 0x78

# Font mặc định của Windows theo yêu cầu người dùng
UI_FONT = "Segoe UI"


class SnatcherWorker(threading.Thread):
    """Worker chạy ngầm vòng lặp quét siêu tốc không làm đơ giao diện Tkinter."""

    def __init__(
        self,
        config_path: Path,
        window_rect: Tuple[int, int, int, int],
        hwnd: Optional[int],
        profile: str,
        target_bags: int,
        enable_bag: bool,
        enable_caravan: bool,
        enable_caravan_regular: bool,
        enable_caravan_season: bool,
        update_queue: queue.Queue,
        frame_queue: queue.Queue,
    ):
        super().__init__(daemon=True)
        self.config_path = config_path
        self.window_rect = window_rect
        self.hwnd = hwnd
        self.profile = profile
        self.target_bags = target_bags
        self.enable_bag = enable_bag
        self.enable_caravan = enable_caravan
        self.enable_caravan_regular = enable_caravan_regular
        self.enable_caravan_season = enable_caravan_season
        self.update_queue = update_queue
        self.frame_queue = frame_queue

        self.running_event = threading.Event()
        self.stop_event = threading.Event()
        self.total_snatched = 0
        self.total_caravans = 0
        self.runner: Optional[TopHeroesLuckyBagRunner] = None

    def start_monitoring(self):
        self.running_event.set()

    def pause_monitoring(self):
        self.running_event.clear()

    def stop_worker(self):
        self.running_event.clear()
        self.stop_event.set()

    def is_active(self) -> bool:
        return self.running_event.is_set()

    def set_target_bags(self, target: int):
        self.target_bags = target
        if self.runner:
            self.runner.target_bags = target

    def set_features(
        self,
        enable_bag: bool,
        enable_caravan: bool,
        enable_caravan_regular: bool = True,
        enable_caravan_season: bool = True,
    ):
        self.enable_bag = enable_bag
        self.enable_caravan = enable_caravan
        self.enable_caravan_regular = enable_caravan_regular
        self.enable_caravan_season = enable_caravan_season
        if self.runner:
            self.runner.enable_bag_snatch = enable_bag
            self.runner.enable_caravan_join = enable_caravan
            self.runner.enable_caravan_regular = enable_caravan_regular
            self.runner.enable_caravan_season = enable_caravan_season

    def reset_counter(self):
        self.total_snatched = 0
        self.total_caravans = 0
        if self.runner:
            self.runner.reset_counter()

    def run(self):
        try:
            self.runner = TopHeroesLuckyBagRunner(
                self.config_path,
                self.window_rect,
                self.hwnd,
                target_bags=self.target_bags,
                enable_bag_snatch=self.enable_bag,
                enable_caravan_join=self.enable_caravan,
                enable_caravan_regular=self.enable_caravan_regular,
                enable_caravan_season=self.enable_caravan_season,
            )
        except Exception as e:
            logger.error("[Worker] Khởi tạo TopHeroesLuckyBagRunner thất bại: %s", e)
            self.update_queue.put({"type": "error", "message": f"Khởi tạo Runner lỗi: {e}"})
            return

        last_frame_ui_time = 0.0
        frame_count = 0
        fps_start_time = time.perf_counter()
        current_fps = 0.0

        while not self.stop_event.is_set():
            if not self.running_event.is_set():
                time.sleep(0.05)
                continue

            try:
                t0 = time.perf_counter()
                action_result = self.runner.scan_and_snatch_once()
                t1 = time.perf_counter()
                cycle_ms = (t1 - t0) * 1000
            except Exception as e:
                logger.error("[Worker] Lỗi chu kỳ quét: %s", e)
                time.sleep(0.1)
                continue

            frame_count += 1
            if time.perf_counter() - fps_start_time >= 0.5:
                current_fps = frame_count / (time.perf_counter() - fps_start_time)
                frame_count = 0
                fps_start_time = time.perf_counter()

            if action_result:
                act = action_result.get("action")
                if act == "caravan":
                    self.total_caravans = action_result.get("total", self.total_caravans + 1)
                    self.update_queue.put({
                        "type": "caravan",
                        "total": self.total_caravans,
                        "caravan_type": action_result.get("type", "regular"),
                        "cycle_ms": cycle_ms,
                        "fps": current_fps,
                    })
                elif act == "caravan_failed":
                    self.update_queue.put({
                        "type": "caravan_failed",
                        "caravan_type": action_result.get("type", "unknown"),
                        "cycle_ms": cycle_ms,
                        "fps": current_fps,
                    })
                elif act == "bag":
                    self.total_snatched = action_result.get("total", self.total_snatched + 1)
                    is_quota_done = self.target_bags > 0 and self.total_snatched >= self.target_bags

                    self.update_queue.put({
                        "type": "snatch",
                        "total": self.total_snatched,
                        "target": self.target_bags,
                        "cycle_ms": cycle_ms,
                        "fps": current_fps,
                    })

                    if is_quota_done:
                        self.pause_monitoring()
                        self.update_queue.put({
                            "type": "quota_reached",
                            "total": self.total_snatched,
                            "target": self.target_bags,
                        })
            else:
                self.update_queue.put({
                    "type": "tick",
                    "cycle_ms": cycle_ms,
                    "fps": current_fps,
                })

            now = time.perf_counter()
            if now - last_frame_ui_time >= 0.04:
                last_frame_ui_time = now
                try:
                    b_top, b_left, b_w, b_h = self.runner._calc_roi_rect("chat_bag_roi")
                    preview_frame = self.runner.capture.grab_roi(b_top, b_left, b_w, b_h)
                    h_p, w_p = preview_frame.shape[:2]
                    target_w = 480
                    target_h = int(h_p * (target_w / max(1, w_p)))
                    small_preview = cv2.resize(preview_frame, (target_w, target_h))
                    self.frame_queue.put(small_preview)
                except Exception:
                    pass

            time.sleep(0.002)

        if self.runner:
            self.runner.close()


class HotkeyListener(threading.Thread):
    """Thread lắng nghe phím tắt toàn cục F9 để Bật/Tắt tức thì."""

    def __init__(self, callback):
        super().__init__(daemon=True)
        self.callback = callback
        self.stop_event = threading.Event()
        self._user32 = ctypes.windll.user32

    def run(self):
        last_press_time = 0.0
        while not self.stop_event.is_set():
            state = self._user32.GetAsyncKeyState(VK_F9)
            if state & 0x8000:
                now = time.time()
                if now - last_press_time > 0.35:
                    last_press_time = now
                    self.callback()
            time.sleep(0.05)

    def stop(self):
        self.stop_event.set()


class TopHeroesMonitorApp:
    """Giao diện điều khiển Tkinter tinh gọn cho Top Heroes."""

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Top Heroes — Snatcher & Caravan Assistant")
        self.root.geometry("600x950+0+0")
        self.root.minsize(600, 950)
        self.root.configure(bg="#1e1e24")

        self.game_dir = PROJECT_ROOT / "games/top_heroes"
        self.config_path = self.game_dir / "config.json"
        with open(self.config_path, "r", encoding="utf-8") as f:
            self.cfg = json.load(f)

        self.update_queue = queue.Queue()
        self.frame_queue = queue.Queue()
        self.worker: Optional[SnatcherWorker] = None
        self.window_info: Optional[Tuple[int, str, Tuple[int, int, int, int]]] = None
        self.client_rect: Optional[Tuple[int, int, int, int]] = None
        self.is_running = False
        self.total_collected = 0
        self.total_caravans = 0

        logger.info("[System] Initialized Top Heroes Monitor. Ready for attachment.")
        self._build_ui()
        self._detect_window()

        self.hotkey_thread = HotkeyListener(self._toggle_from_hotkey)
        self.hotkey_thread.start()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(50, self._process_queues)

    def _build_ui(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("TCombobox", font=(UI_FONT, 13))

        # ── 1. Header: Trạng thái cửa sổ game ────────────────────────────────
        hdr_frame = tk.Frame(self.root, bg="#2b2b36", padx=12, pady=10)
        hdr_frame.pack(fill=tk.X, padx=12, pady=(12, 4))

        self.lbl_win_status = tk.Label(
            hdr_frame, text="Đang dò tìm cửa sổ game...", fg="#ffc107", bg="#2b2b36",
            font=(UI_FONT, 13, "bold")
        )
        self.lbl_win_status.pack(side=tk.LEFT)

        btn_refresh = tk.Button(
            hdr_frame, text="Quét lại", bg="#444455", fg="white", relief=tk.FLAT,
            font=(UI_FONT, 12), command=self._detect_window, padx=10
        )
        btn_refresh.pack(side=tk.RIGHT)

        # ── 2. Settings Bar: Profile & Luôn ở trên cùng ────────────────────────
        opt_frame = tk.Frame(self.root, bg="#1e1e24", padx=12)
        opt_frame.pack(fill=tk.X, padx=12, pady=4)

        tk.Label(opt_frame, text="Profile:", fg="#aaaaaa", bg="#1e1e24", font=(UI_FONT, 13)).pack(side=tk.LEFT)
        self.profile_var = tk.StringVar(value=self.cfg.get("active_profile", "pc"))
        cb_profile = ttk.Combobox(
            opt_frame, textvariable=self.profile_var, values=["pc", "mobile"],
            state="readonly", width=9
        )
        cb_profile.pack(side=tk.LEFT, padx=(6, 20))
        cb_profile.bind("<<ComboboxSelected>>", self._on_profile_change)

        self.topmost_var = tk.BooleanVar(value=True)
        self.root.attributes("-topmost", True)
        chk_top = tk.Checkbutton(
            opt_frame, text="Luôn ở trên cùng", variable=self.topmost_var,
            bg="#1e1e24", fg="white", selectcolor="#2b2b36", activebackground="#1e1e24",
            activeforeground="white", font=(UI_FONT, 13), command=self._toggle_topmost
        )
        chk_top.pack(side=tk.RIGHT)

        # ── 3. Bật / Tắt Tính Năng (Feature Toggles) ───────────────────────────
        feat_frame = tk.Frame(self.root, bg="#2b2b36", padx=12, pady=8)
        feat_frame.pack(fill=tk.X, padx=12, pady=4)

        c_cfg = self.cfg.get("caravan_settings", {})
        self.enable_bag_var = tk.BooleanVar(value=True)
        self.enable_caravan_regular_var = tk.BooleanVar(value=c_cfg.get("enable_regular", True))
        self.enable_caravan_season_var = tk.BooleanVar(value=c_cfg.get("enable_season", True))

        chk_bag = tk.Checkbutton(
            feat_frame, text="Túi Lộc", variable=self.enable_bag_var,
            bg="#2b2b36", fg="#00e676", selectcolor="#1e1e24", activebackground="#2b2b36",
            activeforeground="#00e676", font=(UI_FONT, 13, "bold"), command=self._on_feature_toggle
        )
        chk_bag.pack(anchor=tk.W, pady=(0, 2))

        chk_caravan_reg = tk.Checkbutton(
            feat_frame, text="Thương Đội Đỏ", variable=self.enable_caravan_regular_var,
            bg="#2b2b36", fg="#ff7043", selectcolor="#1e1e24", activebackground="#2b2b36",
            activeforeground="#ff7043", font=(UI_FONT, 13, "bold"), command=self._on_feature_toggle
        )
        chk_caravan_reg.pack(anchor=tk.W, pady=2)

        chk_caravan_sea = tk.Checkbutton(
            feat_frame, text="Thương Đội Mùa Giải Đỏ", variable=self.enable_caravan_season_var,
            bg="#2b2b36", fg="#ff7043", selectcolor="#1e1e24", activebackground="#2b2b36",
            activeforeground="#ff7043", font=(UI_FONT, 13, "bold"), command=self._on_feature_toggle
        )
        chk_caravan_sea.pack(anchor=tk.W, pady=(2, 0))

        # ── 4. Chỉ Tiêu Số Túi & Tiến Độ ─────────────────────────────────────
        quota_box = tk.LabelFrame(
            self.root, text=" Chỉ tiêu Túi Lộc ",
            fg="#00e676", bg="#2b2b36", font=(UI_FONT, 13, "bold"), padx=12, pady=8
        )
        quota_box.pack(fill=tk.X, padx=12, pady=4)

        q_top = tk.Frame(quota_box, bg="#2b2b36")
        q_top.pack(fill=tk.X)

        tk.Label(q_top, text="Số lượng:", fg="#dddddd", bg="#2b2b36", font=(UI_FONT, 13)).pack(side=tk.LEFT)
        self.target_var = tk.StringVar(value="10")
        self.cb_target = ttk.Combobox(
            q_top, textvariable=self.target_var,
            values=["1", "3", "5", "10"],
            width=10
        )
        self.cb_target.pack(side=tk.LEFT, padx=(8, 12))
        self.cb_target.bind("<<ComboboxSelected>>", self._on_target_changed)
        self.cb_target.bind("<KeyRelease>", self._on_target_changed)

        btn_reset = tk.Button(
            q_top, text="Đặt lại", bg="#555566", fg="white", relief=tk.FLAT,
            font=(UI_FONT, 12), command=self._reset_counter, padx=10
        )
        btn_reset.pack(side=tk.RIGHT)

        self.progress_bar = ttk.Progressbar(quota_box, orient=tk.HORIZONTAL, mode="determinate")
        self.progress_bar.pack(fill=tk.X, pady=(6, 3))

        self.lbl_progress_text = tk.Label(
            quota_box, text="Tiến độ: 0 / 10 túi (0%)", fg="#4fc3f7", bg="#2b2b36",
            font=(UI_FONT, 12, "bold")
        )
        self.lbl_progress_text.pack(anchor=tk.W)

        # ── 5. Nút Kích Hoạt Lớn & Thử Nghiệm Click ───────────────────────────
        btn_frame = tk.Frame(self.root, bg="#1e1e24", padx=12, pady=4)
        btn_frame.pack(fill=tk.X, padx=12)

        self.btn_toggle = tk.Button(
            btn_frame, text="BẬT THEO DÕI", bg="#28a745", fg="white",
            activebackground="#218838", activeforeground="white", relief=tk.FLAT,
            font=(UI_FONT, 14, "bold"), pady=8, command=self._toggle_monitoring
        )
        self.btn_toggle.pack(fill=tk.X)

        lbl_hint = tk.Label(
            btn_frame, text="Phím tắt F9: Bật/Tắt | Tự động đảo tab Hội mỗi 30s",
            fg="#888899", bg="#1e1e24", font=(UI_FONT, 11), pady=4
        )
        lbl_hint.pack(fill=tk.X)

        sub_btn_frame = tk.Frame(btn_frame, bg="#1e1e24")
        sub_btn_frame.pack(fill=tk.X, pady=(3, 0))

        btn_test_bag = tk.Button(
            sub_btn_frame, text="Thử Túi Lộc", bg="#283a2c", fg="#00e676",
            relief=tk.FLAT, font=(UI_FONT, 12, "bold"), command=self._test_click_bag, pady=6
        )
        btn_test_bag.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))

        btn_test_caravan = tk.Button(
            sub_btn_frame, text="Thử Gia Nhập", bg="#4a2e28", fg="#ff7043",
            relief=tk.FLAT, font=(UI_FONT, 12, "bold"), command=self._test_click_caravan, pady=6
        )
        btn_test_caravan.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)

        btn_test_tab = tk.Button(
            sub_btn_frame, text="Thử Tab Hội", bg="#33334c", fg="#4fc3f7",
            relief=tk.FLAT, font=(UI_FONT, 12, "bold"), command=self._test_tab_switch, pady=6
        )
        btn_test_tab.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 0))

        # ── 6. Bảng Đo Lường Hiệu Năng Thời Gian Thực ─────────────────────────
        met_frame = tk.Frame(self.root, bg="#2b2b36", padx=12, pady=6)
        met_frame.pack(fill=tk.X, padx=12, pady=4)

        top_met = tk.Frame(met_frame, bg="#2b2b36")
        top_met.pack(fill=tk.X)

        self.lbl_state = tk.Label(
            top_met, text="TẠM DỪNG", fg="#888888", bg="#2b2b36", font=(UI_FONT, 13, "bold")
        )
        self.lbl_state.pack(side=tk.LEFT)

        self.lbl_caravan_count = tk.Label(
            top_met, text="Thương đội: 0", fg="#ff7043", bg="#2b2b36", font=(UI_FONT, 13, "bold")
        )
        self.lbl_caravan_count.pack(side=tk.RIGHT, padx=(10, 0))

        self.lbl_snatch_count = tk.Label(
            top_met, text="Túi lộc: 0", fg="#00e676", bg="#2b2b36", font=(UI_FONT, 13, "bold")
        )
        self.lbl_snatch_count.pack(side=tk.RIGHT)

        bot_met = tk.Frame(met_frame, bg="#2b2b36")
        bot_met.pack(fill=tk.X, pady=(3, 0))

        self.lbl_fps = tk.Label(
            bot_met, text="-- FPS", fg="#4fc3f7", bg="#2b2b36", font=(UI_FONT, 12)
        )
        self.lbl_fps.pack(side=tk.LEFT)

        self.lbl_cycle = tk.Label(
            bot_met, text="-- ms", fg="#b0bec5", bg="#2b2b36", font=(UI_FONT, 12)
        )
        self.lbl_cycle.pack(side=tk.RIGHT)

        # ── 7. Luồng Hình Ảnh ROI Thời Gian Thực (Camera View) ─────────────────
        cam_frame = tk.LabelFrame(
            self.root, text=" Vùng quan sát ",
            fg="#cccccc", bg="#1e1e24", font=(UI_FONT, 13)
        )
        cam_frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=(3, 10))

        self.preview_canvas = tk.Label(cam_frame, bg="#111115")
        self.preview_canvas.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        self._update_progress_ui()

    def _test_click_bag(self):
        """Thử nghiệm click thực tế vào vị trí túi lộc để kiểm chứng phản hồi game."""
        if not self._ensure_window_focused():
            return
        cx, cy, cw, ch = self.client_rect
        target_x = int(cx + 0.50 * cw)
        target_y = int(cy + 0.835 * ch)
        hwnd, _, _ = self.window_info

        fast_input = FastInput(hwnd)
        fast_input.click_screen(target_x, target_y, hold_sec=0.035)
        fast_input.click_window(target_x - cx, target_y - cy, hold_sec=0.035)
        logger.info("[Input.Test] Dispatched test click to Bag target at (%d, %d)", target_x, target_y)

    def _test_click_caravan(self):
        """Thử nghiệm click thực tế vào vị trí nút Gia Nhập Thương Đội."""
        if not self._ensure_window_focused():
            return
        cx, cy, cw, ch = self.client_rect
        target_x = int(cx + 0.484 * cw)
        target_y = int(cy + 0.825 * ch)
        hwnd, _, _ = self.window_info

        fast_input = FastInput(hwnd)
        fast_input.click_screen(target_x, target_y, hold_sec=0.035)
        fast_input.click_window(target_x - cx, target_y - cy, hold_sec=0.035)
        logger.info("[Input.Test] Dispatched test click to Caravan 'Gia Nhập' at (%d, %d)", target_x, target_y)

    def _test_tab_switch(self):
        """Thử nghiệm click đảo sang tab Hội rồi tự động quay lại tab Thế Giới sau 1s."""
        if not self._ensure_window_focused():
            return
        cx, cy, cw, ch = self.client_rect
        active_prof = self.profile_var.get()
        tabs = self.cfg.get("profiles", {}).get(active_prof, {}).get("tabs", {})
        guild_info = tabs.get("guild", {"x_pct": 0.464, "y_pct": 0.127})
        world_info = tabs.get("world", {"x_pct": 0.394, "y_pct": 0.127})

        hwnd, _, _ = self.window_info
        fast_input = FastInput(hwnd)

        gx = int(cx + guild_info["x_pct"] * cw)
        gy = int(cy + guild_info["y_pct"] * ch)
        fast_input.click_screen(gx, gy, hold_sec=0.035)
        fast_input.click_window(gx - cx, gy - cy, hold_sec=0.035)
        logger.info("[Input.Test] Dispatched test click to Guild Tab at (%d, %d)", gx, gy)

        def return_to_world():
            time.sleep(1.0)
            wx = int(cx + world_info["x_pct"] * cw)
            wy = int(cy + world_info["y_pct"] * ch)
            fast_input.click_screen(wx, wy, hold_sec=0.035)
            fast_input.click_window(wx - cx, wy - cy, hold_sec=0.035)
            logger.info("[Input.Test] Returned to World Tab at (%d, %d)", wx, wy)

        threading.Thread(target=return_to_world, daemon=True).start()

    def _ensure_window_focused(self) -> bool:
        if not self.window_info or not self.client_rect:
            self._detect_window()
            if not self.window_info:
                messagebox.showwarning("Cảnh báo", "Chưa kết nối được cửa sổ game Top Heroes!")
                return False
        keywords = tuple(self.cfg.get("window_keywords", ["Top Heroes"]))
        focus_game_window(keywords)
        time.sleep(0.08)
        return True

    def _parse_target_bags(self) -> int:
        val = self.target_var.get().strip()
        if "không" in val.lower() or "∞" in val or val == "0":
            return 0
        digits = "".join(c for c in val if c.isdigit())
        return int(digits) if digits else 0

    def _update_progress_ui(self):
        target = self._parse_target_bags()
        if target > 0:
            pct = min(100.0, (self.total_collected / target) * 100)
            self.progress_bar.config(maximum=target, value=self.total_collected)
            self.lbl_progress_text.config(
                text=f"Tiến độ: {self.total_collected} / {target} túi ({pct:.0f}%)",
                fg="#00e676" if self.total_collected >= target else "#4fc3f7"
            )
        else:
            self.progress_bar.config(maximum=100, value=100)
            self.lbl_progress_text.config(
                text=f"Tiến độ: {self.total_collected} túi (Không giới hạn chỉ tiêu)",
                fg="#b0bec5"
            )

    def _on_feature_toggle(self):
        en_bag = self.enable_bag_var.get()
        en_reg = self.enable_caravan_regular_var.get()
        en_sea = self.enable_caravan_season_var.get()
        en_caravan = en_reg or en_sea
        if self.worker:
            self.worker.set_features(en_bag, en_caravan, en_reg, en_sea)
        logger.info(
            "[Config.Feature] Updated modes -> Bag: %s, Caravan Regular: %s, Caravan Season: %s",
            en_bag, en_reg, en_sea
        )

    def _on_target_changed(self, event=None):
        target = self._parse_target_bags()
        self._update_progress_ui()
        if self.worker:
            self.worker.set_target_bags(target)
        logger.info("[Config.Quota] Updated bag target quota: %s", target if target > 0 else "unlimited")

    def _reset_counter(self):
        self.total_collected = 0
        self.total_caravans = 0
        if self.worker:
            self.worker.reset_counter()
        self.lbl_snatch_count.config(text="Túi lộc: 0")
        self.lbl_caravan_count.config(text="Thương đội: 0")
        self._update_progress_ui()
        logger.info("[Quota] Counters reset to 0.")

    def _detect_window(self):
        keywords = tuple(self.cfg.get("window_keywords", ["Top Heroes", "LDPlayer", "BlueStacks"]))
        target = find_game_window(keywords)
        if target:
            self.window_info = target
            hwnd, title, rect = target

            if _HAS_WIN32:
                try:
                    pt = win32gui.ClientToScreen(hwnd, (0, 0))
                    cr = win32gui.GetClientRect(hwnd)
                    cw = cr[2] - cr[0]
                    ch = cr[3] - cr[1]
                    self.client_rect = (pt[0], pt[1], cw, ch)
                except Exception:
                    self.client_rect = (rect[0], rect[1], rect[2] - rect[0], rect[3] - rect[1])
            else:
                self.client_rect = (rect[0], rect[1], rect[2] - rect[0], rect[3] - rect[1])

            cx, cy, cw, ch = self.client_rect
            self.lbl_win_status.config(
                text=f"Đã kết nối: '{title[:20]}' ({cw}x{ch})", fg="#00e676"
            )
            logger.info(
                "[Window.Attach] Connected: '%s' (HWND: 0x%08X, ClientArea: %dx%d at (%d, %d))",
                title, hwnd, cw, ch, cx, cy
            )
            self._init_or_restart_worker()
        else:
            self.window_info = None
            self.client_rect = None
            self.lbl_win_status.config(
                text="Chưa tìm thấy game Top Heroes!", fg="#ff5252"
            )
            logger.warning("[Window.Missing] Game window not detected. Ensure game is launched.")

    def _init_or_restart_worker(self):
        if not self.window_info or not self.client_rect:
            return
        if self.worker:
            self.worker.stop_worker()
            self.worker.join(timeout=0.5)

        hwnd, _, _ = self.window_info
        en_bag = self.enable_bag_var.get()
        en_reg = self.enable_caravan_regular_var.get()
        en_sea = self.enable_caravan_season_var.get()
        self.worker = SnatcherWorker(
            self.config_path,
            self.client_rect,
            hwnd,
            profile=self.profile_var.get(),
            target_bags=self._parse_target_bags(),
            enable_bag=en_bag,
            enable_caravan=en_reg or en_sea,
            enable_caravan_regular=en_reg,
            enable_caravan_season=en_sea,
            update_queue=self.update_queue,
            frame_queue=self.frame_queue,
        )
        self.worker.total_snatched = self.total_collected
        self.worker.total_caravans = self.total_caravans
        self.worker.start()
        if self.is_running:
            self.worker.start_monitoring()

    def _toggle_topmost(self):
        self.root.attributes("-topmost", self.topmost_var.get())

    def _on_profile_change(self, event=None):
        new_prof = self.profile_var.get()
        self.cfg["active_profile"] = new_prof
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(self.cfg, f, indent=2)
        logger.info("[Config.Profile] Switched profile to: %s", new_prof.upper())
        self._init_or_restart_worker()

    def _toggle_from_hotkey(self):
        self.root.after(0, self._toggle_monitoring)

    def _toggle_monitoring(self):
        if not self.window_info:
            self._detect_window()
            if not self.window_info:
                messagebox.showwarning("Cảnh báo", "Không tìm thấy cửa sổ game Top Heroes để theo dõi!")
                return

        target = self._parse_target_bags()
        if target > 0 and self.total_collected >= target and self.enable_bag_var.get():
            if messagebox.askyesno("Chỉ tiêu đã đạt", f"Bạn đã nhận đủ {target} túi!\nBạn có muốn đặt lại bộ đếm về 0 để tiếp tục không?"):
                self._reset_counter()
            else:
                return

        self.is_running = not self.is_running
        if self.is_running:
            if not self.worker or not self.worker.is_alive():
                self._init_or_restart_worker()
            if self.worker:
                self.worker.start_monitoring()
            self.btn_toggle.config(
                text="DỪNG THEO DÕI", bg="#dc3545", activebackground="#c82333"
            )
            self.lbl_state.config(text="ĐANG THEO DÕI", fg="#00e676")
            logger.info("[Monitor.Start] Real-time loop active. Profile: %s", self.profile_var.get().upper())
        else:
            if self.worker:
                self.worker.pause_monitoring()
            self.btn_toggle.config(
                text="BẬT THEO DÕI", bg="#28a745", activebackground="#218838"
            )
            self.lbl_state.config(text="ĐÃ TẠM DỪNG", fg="#888888")
            logger.info("[Monitor.Pause] Real-time loop paused.")

    def _process_queues(self):
        while not self.update_queue.empty():
            try:
                item = self.update_queue.get_nowait()
                if item["type"] == "caravan":
                    self.total_caravans = item["total"]
                    self.lbl_caravan_count.config(text=f"Thương đội: {self.total_caravans}")
                    try:
                        winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
                    except Exception:
                        pass
                elif item["type"] == "caravan_failed":
                    # Không tăng bộ đếm, gia nhập thất bại đã tự động bỏ qua
                    pass
                elif item["type"] == "snatch":
                    self.total_collected = item["total"]
                    self.lbl_snatch_count.config(text=f"Túi lộc: {self.total_collected}")
                    self._update_progress_ui()
                elif item["type"] == "quota_reached":
                    self.is_running = False
                    self.btn_toggle.config(
                        text="TIẾP TỤC THEO DÕI", bg="#28a745", activebackground="#218838"
                    )
                    self.lbl_state.config(
                        text=f"ĐÃ ĐẠT CHỈ TIÊU ({item['total']}/{item['target']})",
                        fg="#ffd700"
                    )
                    logger.info("[Quota.Done] Reached bag quota %d/%d. Auto-stopped.", item["total"], item["target"])
                    try:
                        winsound.MessageBeep(winsound.MB_ICONASTERISK)
                    except Exception:
                        pass
                elif item["type"] == "tick":
                    self.lbl_fps.config(text=f"{item['fps']:.0f} FPS")
                    self.lbl_cycle.config(text=f"{item['cycle_ms']:.2f} ms")
            except queue.Empty:
                break

        latest_frame = None
        while not self.frame_queue.empty():
            try:
                latest_frame = self.frame_queue.get_nowait()
            except queue.Empty:
                break

        if latest_frame is not None:
            rgb_frame = cv2.cvtColor(latest_frame, cv2.COLOR_BGR2RGB)
            pil_img = Image.fromarray(rgb_frame)
            tk_img = ImageTk.PhotoImage(pil_img)
            self.preview_canvas.config(image=tk_img)
            self.preview_canvas.image = tk_img

        self.root.after(40, self._process_queues)

    def _on_close(self):
        self.hotkey_thread.stop()
        if self.worker:
            self.worker.stop_worker()
        self.root.destroy()


def main():
    root = tk.Tk()
    app = TopHeroesMonitorApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
