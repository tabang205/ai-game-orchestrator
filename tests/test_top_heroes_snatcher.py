"""
test_top_heroes_snatcher.py — Bộ kiểm thử đối kháng tự động cho Top Heroes Lucky Bag Snatcher.
Kiểm tra tính chính xác của tọa độ khung ROI trên cả bản PC (16:9) và bản Mobile (Portrait).
Chạy: python -X utf8 -m unittest tests/test_top_heroes_snatcher.py -v
"""

import json
import sys
import time
import unittest
from pathlib import Path

import cv2

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT))

from games.top_heroes.fast_snatcher import (
    BagDetector,
    CaravanDetector,
    CloseModalDetector,
    FastInput,
    TopHeroesLuckyBagRunner,
)


class TopHeroesSnatcherTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.game_dir = PROJECT_ROOT / "games/top_heroes"
        cls.cfg_path = cls.game_dir / "config.json"
        with open(cls.cfg_path, "r", encoding="utf-8") as f:
            cls.cfg = json.load(f)

        cls.target_dir = cls.game_dir / "targets"
        cls.bag_detector = BagDetector(cls.target_dir, cls.cfg)
        cls.caravan_detector = CaravanDetector(cls.cfg)
        cls.close_detector = CloseModalDetector(cls.target_dir, cls.cfg)

        # Mẫu Mobile
        cls.img_m1 = cv2.imread(str(cls.game_dir / "Screenshot_2026-10-28-10-50-07-90_c676d701da7838bc38d2514af32b80b7.jpg"))
        cls.img_m2 = cv2.imread(str(cls.game_dir / "Screenshot_2026-10-28-10-50-13-64_c676d701da7838bc38d2514af32b80b7.jpg"))

        # Mẫu PC
        cls.img_pc1 = cv2.imread(str(cls.game_dir / "pc_screenshot_chat.png"))
        cls.img_pc2 = cv2.imread(str(cls.game_dir / "pc_screenshot_modal.png"))

    def test_mobile_active_bag_detection(self):
        """Kiểm tra phát hiện chính xác thẻ Túi Lộc hoạt động trên mẫu Mobile (ảnh 1)."""
        h, w = self.img_m1.shape[:2]
        rois = self.cfg["profiles"]["mobile"]["chat_bag_roi"]
        by1, by2 = int(rois["y_min_pct"] * h), int(rois["y_max_pct"] * h)
        bx1, bx2 = int(rois["x_min_pct"] * w), int(rois["x_max_pct"] * w)

        roi = self.img_m1[by1:by2, bx1:bx2]
        res = self.bag_detector.detect_bag(roi)
        self.assertIsNotNone(res, "Không nhận diện được thẻ túi lộc hoạt động!")
        cx, cy, score = res
        abs_x = bx1 + cx
        abs_y = by1 + cy
        self.assertGreaterEqual(score, 0.70)
        # Tâm thẻ túi lộc nằm trong khoảng X: [500, 750], Y: [2300, 2500]
        self.assertTrue(500 <= abs_x <= 750, f"Tọa độ X lệch: {abs_x}")
        self.assertTrue(2300 <= abs_y <= 2500, f"Tọa độ Y lệch: {abs_y}")

    def test_mobile_close_button_detection(self):
        """Kiểm tra phát hiện chính xác Nút X Đỏ trên mẫu Mobile (ảnh 2)."""
        h, w = self.img_m2.shape[:2]
        rois = self.cfg["profiles"]["mobile"]["close_btn_roi"]
        cy1, cy2 = int(rois["y_min_pct"] * h), int(rois["y_max_pct"] * h)
        cx1, cx2 = int(rois["x_min_pct"] * w), int(rois["x_max_pct"] * w)

        roi_close = self.img_m2[cy1:cy2, cx1:cx2]
        pos = self.close_detector.locate_close_button(roi_close)
        self.assertIsNotNone(pos, "Không tìm thấy nút X đỏ trong ROI của mobile!")
        clx, cly = pos
        abs_x, abs_y = cx1 + clx, cy1 + cly
        self.assertTrue(600 <= abs_x <= 670)
        self.assertTrue(2530 <= abs_y <= 2600)

    def test_pc_close_button_roi_accuracy(self):
        """Kiểm tra phát hiện chính xác Nút X Đỏ trên bản PC chuẩn (16:9)."""
        if self.img_pc2 is not None:
            h, w = self.img_pc2.shape[:2]
            rois = self.cfg["profiles"]["pc"]["close_btn_roi"]
            cy1, cy2 = int(rois["y_min_pct"] * h), int(rois["y_max_pct"] * h)
            cx1, cx2 = int(rois["x_min_pct"] * w), int(rois["x_max_pct"] * w)

            roi_close = self.img_pc2[cy1:cy2, cx1:cx2]
            pos = self.close_detector.locate_close_button(roi_close)
            self.assertIsNotNone(pos, "Không tìm thấy nút X đỏ trong ROI của bản PC!")
            clx, cly = pos
            abs_x, abs_y = cx1 + clx, cy1 + cly
            # Nút X nằm ở tâm ngang x ~ 511, y ~ 499
            self.assertTrue(500 <= abs_x <= 525, f"Tọa độ X nút X PC lệch: {abs_x}")
            self.assertTrue(485 <= abs_y <= 515, f"Tọa độ Y nút X PC lệch: {abs_y}")

    def test_pc_expired_bag_rejection(self):
        """Kiểm tra túi lộc đã hết hạn trên PC bị từ chối 100% để tránh click nhầm."""
        if self.img_pc1 is not None:
            h, w = self.img_pc1.shape[:2]
            rois = self.cfg["profiles"]["pc"]["chat_bag_roi"]
            by1, by2 = int(rois["y_min_pct"] * h), int(rois["y_max_pct"] * h)
            bx1, bx2 = int(rois["x_min_pct"] * w), int(rois["x_max_pct"] * w)

            roi_exp = self.img_pc1[by1:by2, bx1:bx2]
            res = self.bag_detector.detect_bag(roi_exp)
            self.assertIsNone(res, "Bộ lọc không chặn được túi đã hết hạn trên PC!")

    def test_puffel_false_positive_rejection(self):
        """Kiểm tra loại bỏ 100% thẻ chia sẻ Puffel (Vua Lượn Mây), không bị nhận diện nhầm là túi lộc."""
        puffel_path = self.game_dir / "false_positive_puffel.png"
        if puffel_path.exists():
            img_puffel = cv2.imread(str(puffel_path))
            self.assertIsNotNone(img_puffel, "Không đọc được ảnh test false_positive_puffel.png")
            res = self.bag_detector.detect_bag(img_puffel)
            self.assertIsNone(
                res,
                "LỖI: Thẻ chia sẻ Puffel (Vua Lượn Mây) vẫn bị nhận diện nhầm là Túi Lộc!"
            )

    def test_caravan_join_button_detection(self):
        """Kiểm tra phát hiện chính xác nút Gia Nhập xanh trên thẻ Thương Đội đỏ."""
        caravan_path = self.game_dir / "pc_caravan_sample.png"
        if caravan_path.exists():
            img_c = cv2.imread(str(caravan_path))
            h, w = img_c.shape[:2]
            rois = self.cfg["profiles"]["pc"]["chat_caravan_roi"]
            cy1, cy2 = int(rois["y_min_pct"] * h), int(rois["y_max_pct"] * h)
            cx1, cx2 = int(rois["x_min_pct"] * w), int(rois["x_max_pct"] * w)
            roi_c = img_c[cy1:cy2, cx1:cx2]

            pos = self.caravan_detector.detect_join_button(roi_c)
            self.assertIsNotNone(pos, "Không tìm thấy nút Gia Nhập xanh trên thẻ Thương Đội!")
            abs_x, abs_y = cx1 + pos[0], cy1 + pos[1]
            # Tọa độ nút Gia Nhập trong ảnh chuẩn là x=496, y=475
            self.assertTrue(480 <= abs_x <= 515, f"Tọa độ X nút Gia Nhập lệch: {abs_x}")
            self.assertTrue(460 <= abs_y <= 490, f"Tọa độ Y nút Gia Nhập lệch: {abs_y}")

    def test_caravan_negative_samples(self):
        """Kiểm tra không bị nhận diện nhầm khi không có thẻ Thương Đội hoạt động."""
        for img in [self.img_pc1, self.img_pc2]:
            if img is not None:
                h, w = img.shape[:2]
                rois = self.cfg["profiles"]["pc"]["chat_caravan_roi"]
                cy1, cy2 = int(rois["y_min_pct"] * h), int(rois["y_max_pct"] * h)
                cx1, cx2 = int(rois["x_min_pct"] * w), int(rois["x_max_pct"] * w)
                roi = img[cy1:cy2, cx1:cx2]
                self.assertIsNone(self.caravan_detector.detect_join_button(roi))

    def test_target_bags_quota_limit(self):
        """Kiểm tra logic chỉ tiêu số túi muốn nhận và tự động dừng an toàn."""
        runner = TopHeroesLuckyBagRunner(
            self.cfg_path, (0, 0, 1024, 576), hwnd=None, target_bags=3
        )
        self.assertFalse(runner.is_quota_reached())
        runner.bags_collected = 2
        self.assertFalse(runner.is_quota_reached())
        runner.bags_collected = 3
        self.assertTrue(runner.is_quota_reached())
        self.assertFalse(runner.scan_and_snatch_once())

        runner.reset_counter()
        self.assertEqual(runner.bags_collected, 0)
        self.assertFalse(runner.is_quota_reached())

    def test_guild_routine_and_tabs_geometry(self):
        """Kiểm tra cấu hình chu kỳ đảo tab Hội mỗi 30s và tính hợp lệ của tọa độ các tab."""
        routine_cfg = self.cfg.get("guild_routine", {})
        self.assertTrue(routine_cfg.get("enabled", True), "Tính năng đảo tab Hội phải mặc định Bật!")
        self.assertEqual(routine_cfg.get("interval_sec", 30.0), 30.0, "Chu kỳ đảo tab phải là 30s!")

        pc_tabs = self.cfg["profiles"]["pc"].get("tabs", {})
        self.assertIn("world", pc_tabs)
        self.assertIn("guild", pc_tabs)
        self.assertTrue(0.35 <= pc_tabs["world"]["x_pct"] <= 0.42)
        self.assertTrue(0.42 <= pc_tabs["guild"]["x_pct"] <= 0.50)
        self.assertTrue(0.10 <= pc_tabs["world"]["y_pct"] <= 0.16)

        mobile_tabs = self.cfg["profiles"]["mobile"].get("tabs", {})
        self.assertIn("world", mobile_tabs)
        self.assertIn("guild", mobile_tabs)
        self.assertTrue(0.10 <= mobile_tabs["world"]["x_pct"] <= 0.20)
        self.assertTrue(0.32 <= mobile_tabs["guild"]["x_pct"] <= 0.45)
        self.assertTrue(0.10 <= mobile_tabs["world"]["y_pct"] <= 0.18)

        runner = TopHeroesLuckyBagRunner(self.cfg_path, (0, 0, 1024, 576))
        self.assertTrue(runner.guild_routine_enabled)
        self.assertEqual(runner.guild_interval_sec, 30.0)


    def test_caravan_type_classification(self):
        """Kiểm tra phân loại chính xác Thương Đội Đỏ Thường (có ngựa) và Thương Đội Mùa Giải (không ngựa)."""
        caravan_path = self.game_dir / "pc_caravan_sample.png"
        if caravan_path.exists():
            img_c = cv2.imread(str(caravan_path))
            h, w = img_c.shape[:2]
            rois = self.cfg["profiles"]["pc"]["chat_caravan_roi"]
            cy1, cy2 = int(rois["y_min_pct"] * h), int(rois["y_max_pct"] * h)
            cx1, cx2 = int(rois["x_min_pct"] * w), int(rois["x_max_pct"] * w)
            roi_c = img_c[cy1:cy2, cx1:cx2]

            # 1. Mẫu gốc có ngựa đỏ -> Phải nhận diện là 'regular'
            res_reg = self.caravan_detector.detect_join_button(roi_c)
            self.assertIsNotNone(res_reg)
            cx, cy, c_type = res_reg
            self.assertEqual(c_type, "regular", "Mẫu có ngựa đỏ phải được phân loại là 'regular'!")

            # 2. Mẫu xóa ngựa đỏ (thay bằng nền phẳng) -> Phải nhận diện là 'season'
            roi_season = roi_c.copy()
            roi_season[20:70, 40:95] = [80, 90, 180]
            res_season = self.caravan_detector.detect_join_button(roi_season)
            self.assertIsNotNone(res_season)
            _, _, s_type = res_season
            self.assertEqual(s_type, "season", "Mẫu không có ngựa đỏ phải được phân loại là 'season'!")

    def test_caravan_failure_ignore_and_toggles(self):
        """Kiểm tra cơ chế bỏ qua khi thất bại và các cờ bật/tắt loại thương đội."""
        runner = TopHeroesLuckyBagRunner(
            self.cfg_path,
            (0, 0, 1024, 576),
            hwnd=None,
            enable_caravan_regular=True,
            enable_caravan_season=False,
        )

        # Season bị tắt -> Không được phép gia nhập
        self.assertFalse(runner.enable_caravan_season)
        attempt_season = runner._attempt_join_caravan(0, 0, 100, 100, 50, 50, "season")
        self.assertIsNone(attempt_season, "Khi tắt mùa giải, _attempt_join_caravan phải trả về None!")

        # Tọa độ vừa thất bại nằm trong blacklist -> Không được spam click lại
        runner.ignored_caravans[(500, 500)] = time.time()
        self.assertTrue(runner.is_caravan_ignored(500, 500))
        attempt_ignored = runner._attempt_join_caravan(0, 0, 100, 100, 500, 500, "regular")
        self.assertIsNone(attempt_ignored, "Tọa độ đã thất bại phải bị bỏ qua hoàn toàn!")

        # Reset counter phải xóa cả danh sách ignored
        runner.reset_counter()
        self.assertEqual(len(runner.ignored_caravans), 0)

    def test_nha_ti_tach_false_positive_rejection(self):
        """Kiểm tra loại bỏ 100% thẻ 'Nhà Tí Tách' (nút Thăm), không bị nhận nhầm là thương đội."""
        nha_ti_tach_path = self.game_dir / "false_positive_nha_ti_tach.png"
        if nha_ti_tach_path.exists():
            img_fp = cv2.imread(str(nha_ti_tach_path))
            self.assertIsNotNone(img_fp, "Không đọc được ảnh test false_positive_nha_ti_tach.png")
            res = self.caravan_detector.detect_join_button(img_fp)
            self.assertIsNone(
                res,
                "LỖI: Thẻ 'Nhà Tí Tách' vẫn bị nhận diện nhầm là Thương Đội!"
            )

    def test_window_manager_anti_self_attachment(self):
        """Kiểm tra window_manager không bao giờ nhận nhầm cửa sổ Assistant/Snatcher của chính nó."""
        from window_manager import find_game_window
        fake_assistant_kws = ("Snatcher & Caravan Assistant",)
        matched = find_game_window(fake_assistant_kws)
        self.assertIsNone(
            matched,
            "LỖI: find_game_window vẫn nhận nhầm cửa sổ trợ lý/assistant của chính mình!"
        )


if __name__ == "__main__":
    unittest.main()
