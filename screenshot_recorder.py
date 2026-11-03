"""
Screenshot Recorder - Tự động chụp màn hình theo chu kỳ, có nút Start/Stop.
Mục đích: chụp lại quá trình chơi game để lấy ngữ cảnh gửi cho Gemini phân tích.

Yêu cầu cài đặt (chạy 1 lần trong CMD/PowerShell):
    pip install pillow pyautogui

Cách chạy:
    python screenshot_recorder.py
"""

import os
import time
import threading
from datetime import datetime
import tkinter as tk
from tkinter import ttk, messagebox

import pyautogui


# ====== CẤU HÌNH ======
SAVE_DIR = r"D:\ảnh, video\ark_recode_data"
INTERVAL_SECONDS = 1.0          # tốc độ chụp: 1 ảnh / giây
IMAGE_FORMAT = "png"            # có thể đổi thành "jpg" để nhẹ hơn (giảm dung lượng)
JPEG_QUALITY = 85                # chỉ áp dụng nếu IMAGE_FORMAT = "jpg"
# =======================


class ScreenshotRecorder:
    def __init__(self):
        self.is_running = False
        self.thread = None
        self.count = 0

        os.makedirs(SAVE_DIR, exist_ok=True)

        # ---- GUI ----
        self.root = tk.Tk()
        self.root.title("Screenshot Recorder - Ark Recode")
        self.root.geometry("360x220")
        self.root.resizable(False, False)

        # Luôn nổi trên cùng để dễ bấm khi đang chơi game
        self.root.attributes("-topmost", True)

        title_label = tk.Label(
            self.root, text="Ghi hình quá trình chơi game",
            font=("Segoe UI", 12, "bold")
        )
        title_label.pack(pady=(15, 5))

        self.status_label = tk.Label(
            self.root, text="Trạng thái: Đang dừng",
            font=("Segoe UI", 10), fg="red"
        )
        self.status_label.pack(pady=5)

        self.count_label = tk.Label(
            self.root, text="Số ảnh đã chụp: 0",
            font=("Segoe UI", 10)
        )
        self.count_label.pack(pady=5)

        btn_frame = tk.Frame(self.root)
        btn_frame.pack(pady=15)

        self.start_btn = tk.Button(
            btn_frame, text="▶ START (F9)", width=14, height=2,
            bg="#4CAF50", fg="white", font=("Segoe UI", 10, "bold"),
            command=self.start
        )
        self.start_btn.grid(row=0, column=0, padx=5)

        self.stop_btn = tk.Button(
            btn_frame, text="■ STOP (F10)", width=14, height=2,
            bg="#f44336", fg="white", font=("Segoe UI", 10, "bold"),
            command=self.stop, state=tk.DISABLED
        )
        self.stop_btn.grid(row=0, column=1, padx=5)

        path_label = tk.Label(
            self.root, text=f"Lưu tại:\n{SAVE_DIR}",
            font=("Segoe UI", 8), fg="gray", justify="center"
        )
        path_label.pack(pady=(5, 0))

        # Phím tắt toàn cục trong app (chỉ hoạt động khi cửa sổ được focus)
        self.root.bind("<F9>", lambda e: self.start())
        self.root.bind("<F10>", lambda e: self.stop())

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def start(self):
        if self.is_running:
            return
        self.is_running = True
        self.status_label.config(text="Trạng thái: Đang chụp...", fg="green")
        self.start_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)

        self.thread = threading.Thread(target=self._capture_loop, daemon=True)
        self.thread.start()

    def stop(self):
        if not self.is_running:
            return
        self.is_running = False
        self.status_label.config(text="Trạng thái: Đang dừng", fg="red")
        self.start_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)

    def _capture_loop(self):
        while self.is_running:
            start_time = time.time()
            try:
                self._take_screenshot()
            except Exception as e:
                print(f"Lỗi khi chụp ảnh: {e}")

            elapsed = time.time() - start_time
            sleep_time = max(0.0, INTERVAL_SECONDS - elapsed)
            time.sleep(sleep_time)

    def _take_screenshot(self):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        filename = f"screenshot_{timestamp}.{IMAGE_FORMAT}"
        filepath = os.path.join(SAVE_DIR, filename)

        img = pyautogui.screenshot()

        if IMAGE_FORMAT.lower() in ("jpg", "jpeg"):
            img = img.convert("RGB")
            img.save(filepath, quality=JPEG_QUALITY)
        else:
            img.save(filepath)

        self.count += 1
        # Cập nhật label từ thread phụ -> dùng after() để an toàn với Tkinter
        self.root.after(0, self._update_count_label)

    def _update_count_label(self):
        self.count_label.config(text=f"Số ảnh đã chụp: {self.count}")

    def on_close(self):
        if self.is_running:
            if not messagebox.askyesno("Xác nhận", "Đang chụp ảnh, bạn có chắc muốn thoát?"):
                return
            self.stop()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    app = ScreenshotRecorder()
    app.run()
