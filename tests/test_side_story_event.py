import unittest
from unittest.mock import MagicMock
import numpy as np

from games.ark_recode.side_story_event import (
    SideStoryEventRunner,
    COORD_EVENT_BANNER,
    COORD_START_STORY,
    COORD_HARD_STAGE,
    COORD_SELECT_TEAM,
    COORD_QUICK_BATTLE,
)


class SideStoryEventTestCase(unittest.TestCase):
    def setUp(self):
        self.vision = MagicMock()
        self.actions = MagicMock()
        dummy_frame = np.zeros((810, 1440, 3), dtype=np.uint8)
        self.vision.grab_game_frame.return_value = (dummy_frame, (1, 38))
        self.runner = SideStoryEventRunner(self.vision, self.actions)

    def test_run_quick_battle_flow_clicks(self):
        orig = (1, 38)
        success = self.runner.run_quick_battle_flow(wait_completion_s=0)
        self.assertTrue(success)

        # Kiểm tra đã gọi F8 và Escape
        self.actions.press_key.assert_any_call('f8')
        self.actions.press_key.assert_any_call('escape')

        # Kiểm tra thứ tự và tọa độ các nút bấm
        expected_clicks = [
            (orig[0] + COORD_EVENT_BANNER[0], orig[1] + COORD_EVENT_BANNER[1]),
            (orig[0] + COORD_START_STORY[0], orig[1] + COORD_START_STORY[1]),
            (orig[0] + COORD_HARD_STAGE[0], orig[1] + COORD_HARD_STAGE[1]),
            (orig[0] + COORD_SELECT_TEAM[0], orig[1] + COORD_SELECT_TEAM[1]),
            (orig[0] + COORD_QUICK_BATTLE[0], orig[1] + COORD_QUICK_BATTLE[1]),
        ]
        self.assertEqual(self.actions.click.call_count, 5)
        for expected in expected_clicks:
            self.actions.click.assert_any_call(*expected)


if __name__ == '__main__':
    unittest.main()
