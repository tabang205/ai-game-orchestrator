"""
Test FSM Ark Re-Code offline: phát lại ảnh chụp thật thay cho màn hình, ghi lại click thay cho chuột.
Chạy: python -X utf8 -m unittest tests/test_ark_fsm.py -v
"""

import importlib.util
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / 'src'))

from core_vision import GameVision  # noqa: E402

TEMPLATE_DIR = PROJECT_ROOT / 'games' / 'ark_recode' / 'templates'
CLICK_TOLERANCE_PX = 40


def load_states_module():
    spec = importlib.util.spec_from_file_location('ark_states', PROJECT_ROOT / 'games/ark_recode/states.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


STATES = load_states_module()


def screen(name: str) -> np.ndarray:
    return cv2.imread(str(TEMPLATE_DIR / f'{name}.png'))


class RecordingActions:
    def __init__(self):
        self.clicks: list[tuple[int, int]] = []
        self.keys: list[str] = []

    def click(self, x: int, y: int, button: str = 'left') -> None:
        self.clicks.append((x, y))

    def press_key(self, key: str) -> None:
        self.keys.append(key)

    def stage_wait(self) -> None:
        return None

    def act_from_gemini(self, result: dict, width: int, height: int) -> None:
        return None


class ScriptedVision(GameVision):
    """GameVision thật (matcher + OCR) nhưng dùng chung OCR/Matcher cache để test nhanh."""

    _shared_ocr = None
    _shared_matcher = None

    def __init__(self, cfg: dict, frames: list[str]):
        super().__init__(cfg)
        if ScriptedVision._shared_ocr is None:
            ScriptedVision._shared_ocr = self.ocr
            ScriptedVision._shared_matcher = self.matcher
        else:
            self.ocr = ScriptedVision._shared_ocr
            self.matcher = ScriptedVision._shared_matcher
        self._frames = [screen(name) for name in frames]

    def grab_frame(self) -> np.ndarray:
        frame = self._frames.pop(0) if len(self._frames) > 1 else self._frames[0]
        self._last_frame = frame
        return frame


class ArkFsmTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.sleep_patcher = patch.object(STATES.time, 'sleep', lambda _s: None)
        self.sleep_patcher.start()
        cfg = json.loads((PROJECT_ROOT / 'games/ark_recode/config.json').read_text(encoding='utf-8'))
        cfg['click_coords']['daily_open_btn'] = [470, 300]
        cfg['action_delays']['battle_wait_s'] = [0, 0]
        self.game_cfg = cfg

    def tearDown(self) -> None:
        self.sleep_patcher.stop()

    def assert_clicked_near(self, click: tuple[int, int], expected: tuple[int, int]) -> None:
        self.assertLessEqual(abs(click[0] - expected[0]), CLICK_TOLERANCE_PX, f"{click} vs {expected}")
        self.assertLessEqual(abs(click[1] - expected[1]), CLICK_TOLERANCE_PX, f"{click} vs {expected}")

    def test_classify_each_screen(self) -> None:
        cases = [
            ('lobby', 'lobby'),
            ('daily', 'daily'),
            ('victory', 'victory_pve'),
            ('pop_up', 'popup'),
            ('try_again_tasks', 'task_complete'),
            ('victory_in_pvp_or_pve', 'victory_pvp'),
            ('battle_pass', 'battle_pass'),
        ]
        vision = ScriptedVision(self.game_cfg, ['lobby'])
        agent = STATES.create_agent(vision, RecordingActions(), self.game_cfg, {})
        for name, expected in cases:
            with self.subTest(screen=name):
                self.assertEqual(agent._classify(screen(name)), expected)
        vision.close()

    def test_full_loop_with_retry_and_popup(self) -> None:
        frames = [
            'lobby', 'lobby', 'daily', 'daily', 'daily', 'victory_in_pvp_or_pve',
            'try_again_tasks', 'try_again_tasks', 'victory', 'victory', 'pop_up', 'pop_up', 'lobby',
        ]
        actions = RecordingActions()
        bot_cfg = {'max_mana_to_spend': 300, 'keep_mana_minimum': 0}
        vision = ScriptedVision(self.game_cfg, frames)
        agent = STATES.create_agent(vision, actions, self.game_cfg, bot_cfg)

        visited = []
        for _ in range(14):
            visited.append(agent.state)
            agent.tick()

        self.assertEqual(visited[:12], [
            'SYNC', 'OPEN_DAILY', 'SYNC', 'CHECK_DAILY_LIST', 'NAVIGATE_TO_TASK', 'IN_BATTLE_WAITING',
            'HANDLE_VICTORY_PVP', 'SYNC', 'HANDLE_TASK_COMPLETE', 'IN_BATTLE_WAITING',
            'HANDLE_VICTORY_PVE', 'SYNC',
        ])
        self.assertIn('HANDLE_POPUP', visited)
        self.assertEqual(actions.keys, ['escape'])
        self.assertEqual(agent.energy_start, 207)
        self.assertEqual(agent.energy_spent, 72)

        expected_clicks = [(470, 300), (1497, 455), (1700, 862), (1374, 772), (1662, 847)]
        for click, expected in zip(actions.clicks, expected_clicks):
            self.assert_clicked_near(click, expected)
        vision.close()

    def test_stops_when_budget_would_be_exceeded(self) -> None:
        actions = RecordingActions()
        bot_cfg = {'max_mana_to_spend': 50, 'keep_mana_minimum': 0}
        vision = ScriptedVision(self.game_cfg, ['lobby', 'lobby', 'daily', 'daily', 'daily'])
        agent = STATES.create_agent(vision, actions, self.game_cfg, bot_cfg)
        visited = []
        for _ in range(5):
            visited.append(agent.state)
            agent.tick()

        self.assertIn('COLLECT_REWARDS', visited)
        self.assertEqual(agent.state, 'DONE')
        # Kiểm tra đã click nút mở daily và click nhận rương quà
        self.assertGreaterEqual(len(actions.clicks), 1)
        self.assert_clicked_near(actions.clicks[0], (470, 300))
        vision.close()

    def test_skips_task_that_never_reaches_battle(self) -> None:
        vision = ScriptedVision(self.game_cfg, ['daily'])
        agent = STATES.create_agent(vision, RecordingActions(), self.game_cfg, {})
        first = agent._pick_go_button(screen('daily'))
        self.assertIsNotNone(first)
        agent._current_go_row = first[1]
        agent._mark_current_task_failed()
        second = agent._pick_go_button(screen('daily'))

        self.assertIsNotNone(second)
        self.assertGreater(second[1], first[1])
        vision.close()


if __name__ == '__main__':
    unittest.main()
