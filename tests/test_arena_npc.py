"""
test_arena_npc.py — Unit test cho bộ điều phối Thử thách Đấu trường NPC (ArenaNPCRunner).
Chạy: python -X utf8 -m unittest tests/test_arena_npc.py -v
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

import cv2
import numpy as np

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / 'src'))
sys.path.insert(0, str(PROJECT_ROOT))

from core_vision import GameVision
from games.ark_recode.arena_npc import ArenaNPCRunner


class ArenaNPCTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixtures_dir = PROJECT_ROOT / 'ark_recode_data' / 'test_fixtures'
        cls.tab2_fixture = cv2.imread(str(fixtures_dir / 'arena_fixture_tab2.png'))
        cls.modal_fixture = cv2.imread(str(fixtures_dir / 'flag_modal_fixture.png'))
        cls.vision = MagicMock(spec=GameVision)
        from core_vision import OCRReader
        cls.ocr = OCRReader()
        cls.vision.ocr = cls.ocr

    def setUp(self):
        self.actions = MagicMock()
        self.runner = ArenaNPCRunner(self.vision, self.actions, max_gem_purchases=2)

    def test_find_visible_challenge_buttons(self):
        """Kiểm tra tìm chính xác 3 nút Thử thách trên fixture tab 2, không nhầm tiêu đề."""
        buttons = self.runner.find_visible_challenge_buttons(self.tab2_fixture)
        self.assertEqual(len(buttons), 3)
        for cx, cy in buttons:
            self.assertGreaterEqual(cx, 980)
            self.assertLessEqual(cx, 1100)
            self.assertGreater(cy, 200)

    def test_read_arena_flags(self):
        """Kiểm tra đọc chính xác số cờ 3/5 từ HUD."""
        flags = self.runner.read_arena_flags(self.tab2_fixture)
        self.assertIsNotNone(flags)
        self.assertEqual(flags, (3, 5))

    def test_handle_flag_purchase_modal(self):
        """Kiểm tra nhận diện popup mua cờ, chọn gói Pink Token và bấm Mua (không dùng kim cương)."""
        if self.modal_fixture is not None:
            orig = (1, 38)
            handled = self.runner.handle_flag_purchase_modal(self.modal_fixture, orig)
            self.assertTrue(handled)
            self.assertEqual(self.runner.purchases_made, 1)
            self.assertEqual(self.actions.click.call_count, 2)
            self.actions.click.assert_any_call(561, 418)
            self.actions.click.assert_any_call(919, 628)

    def test_client_to_screen(self):
        """Kiểm tra ánh xạ tọa độ client sang screen theo gốc cửa sổ."""
        pt = self.runner._client_to_screen((100, 200), (1, 38))
        self.assertEqual(pt, (101, 238))


if __name__ == '__main__':
    unittest.main()
