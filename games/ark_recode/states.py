"""
states.py — FSM farm nhiệm vụ ngày Ark Re-Code.

SYNC là bộ định tuyến: nhận diện màn hình hiện tại rồi chuyển sang handler phù hợp,
nên bot có thể bắt đầu ở bất kỳ màn nào và tự quay về luồng sau mỗi bước.

    SYNC ─lobby→ OPEN_DAILY ─→ SYNC
    SYNC ─daily→ CHECK_DAILY_LIST ─→ NAVIGATE_TO_TASK ─→ IN_BATTLE_WAITING
    IN_BATTLE_WAITING ─→ HANDLE_VICTORY_PVE / HANDLE_VICTORY_PVP / HANDLE_TASK_COMPLETE ─→ SYNC
    (*) ─popup→ HANDLE_POPUP,  (*) ─timeout→ HANDLE_STUCK (Gemini Vision) ─→ SYNC
"""

import logging
import random
import time
from typing import Callable, Optional, Tuple

import numpy as np
from transitions import Machine

logger = logging.getLogger(__name__)

STATES = [
    'SYNC', 'OPEN_DAILY', 'CHECK_DAILY_LIST', 'NAVIGATE_TO_TASK', 'IN_BATTLE_WAITING',
    'HANDLE_VICTORY_PVE', 'HANDLE_VICTORY_PVP', 'HANDLE_TASK_COMPLETE',
    'HANDLE_POPUP', 'HANDLE_STUCK', 'COLLECT_REWARDS', 'DONE',
]

TRANSITIONS = [
    {'trigger': 'resync',          'source': '*',                    'dest': 'SYNC'},
    {'trigger': 'popup_detected',  'source': '*',                    'dest': 'HANDLE_POPUP'},
    {'trigger': 'stuck',           'source': '*',                    'dest': 'HANDLE_STUCK'},
    {'trigger': 'collect_rewards', 'source': ['CHECK_DAILY_LIST', 'SYNC'], 'dest': 'COLLECT_REWARDS'},
    {'trigger': 'finish',          'source': '*',                    'dest': 'DONE'},
    {'trigger': 'at_lobby',        'source': 'SYNC',                 'dest': 'OPEN_DAILY'},
    {'trigger': 'at_daily',        'source': 'SYNC',                 'dest': 'CHECK_DAILY_LIST'},
    {'trigger': 'at_battle_menu',  'source': 'SYNC',                 'dest': 'NAVIGATE_TO_TASK'},
    {'trigger': 'task_found',      'source': 'CHECK_DAILY_LIST',     'dest': 'NAVIGATE_TO_TASK'},
    {'trigger': 'battle_started',  'source': 'NAVIGATE_TO_TASK',     'dest': 'IN_BATTLE_WAITING'},

    {'trigger': 'retry_started',   'source': 'HANDLE_TASK_COMPLETE', 'dest': 'IN_BATTLE_WAITING'},
    {'trigger': 'victory_pve',     'source': ['SYNC', 'IN_BATTLE_WAITING'], 'dest': 'HANDLE_VICTORY_PVE'},
    {'trigger': 'victory_pvp',     'source': ['SYNC', 'IN_BATTLE_WAITING'], 'dest': 'HANDLE_VICTORY_PVP'},
    {'trigger': 'task_completed',  'source': ['SYNC', 'IN_BATTLE_WAITING'], 'dest': 'HANDLE_TASK_COMPLETE'},
]

# Thứ tự ưu tiên: overlay (popup, kết quả) phải xét trước màn nền vì màn nền vẫn lộ phía sau
SCREEN_PRIORITY: list[Tuple[str, str]] = [
    ('task_complete', 'task_complete_title'),
    ('victory_pvp',   'victory_pvp_text'),
    ('victory_pve',   'victory_pve_loot'),
    ('daily',         'daily_title'),
    ('battle_pass',   'bp_title'),
    ('lobby',         'lobby_nav_labels'),
]

DAILY_OPEN_HINT = "nút hoặc biểu tượng mở 'Nhật ký Ark' / 'Nhiệm Vụ Hàng Ngày' trong sảnh game"
POPUP_CLOSE_HINT = "nút đóng (X, Đóng, Quay lại) của cửa sổ quảng cáo/gói mua đang hiện"
GO_BTN_ROW_TOLERANCE_PX = 25


class ArkRecodeAgent:
    """FSM chơi nhiệm vụ ngày; vision/actions được inject để dễ thay thế khi test."""

    MAX_STUCK_RETRIES = 3
    LOOP_SLEEP_S = 0.5

    def __init__(self, vision, actions, game_cfg: dict, bot_cfg: dict):
        self.vision = vision
        self.actions = actions
        self.cfg = game_cfg
        self.bot_cfg = bot_cfg

        delays = game_cfg.get('action_delays', {})
        self._watchdog_s: float = delays.get('watchdog_timeout_s', 60)
        self._battle_timeout_s: float = delays.get('battle_timeout_s', 240)
        self._battle_wait_range: list = delays.get('battle_wait_s', [8, 25])
        self._coords: dict = dict(game_cfg.get('click_coords', {}))

        self.tasks_done = 0
        self.stuck_count = 0
        self.energy_start: Optional[int] = None
        self.energy_now: Optional[int] = None
        self.energy_spent = 0
        self.last_run_cost = 0
        self._failed_go_rows: list[int] = []
        self._current_go_row: Optional[int] = None
        self._state_entry_time = time.time()

        self.machine = Machine(
            model=self, states=STATES, transitions=TRANSITIONS, initial='SYNC',
            auto_transitions=False, after_state_change=self._on_state_change,
        )

    # ── Hạ tầng ───────────────────────────────────────────────────────────

    def _on_state_change(self) -> None:
        logger.info("[FSM] ► %s", self.state)
        self._state_entry_time = time.time()

    def _time_in_state(self) -> float:
        return time.time() - self._state_entry_time

    def _find(self, frame: np.ndarray, key: str) -> Optional[Tuple[int, int]]:
        return self.vision.find_in_frame(frame, key)

    def _popup_visible(self, frame: np.ndarray) -> bool:
        return any(self._find(frame, key) for key in self.cfg.get('popup_markers', []))

    def _classify(self, frame: np.ndarray) -> str:
        if self._popup_visible(frame):
            return 'popup'
        for screen, key in SCREEN_PRIORITY:
            if self._find(frame, key):
                return screen

        # Semantic OCR classification (chỉ kích hoạt trên live game khi template không khớp)
        if hasattr(self.vision, 'ocr') and not hasattr(self.vision, '_frames'):
            items = self.vision.ocr.find_all_text(frame, min_score=0.6)
            norms = [i['norm'] for i in items]

            def has_kw(kws):
                return any(any(kw in n for kw in kws) for n in norms)

            if has_kw(['noah', 'support pack', 'khong nhac lai']):
                return 'popup'
            if has_kw(['khoang lang', 'ngoai chon', 'su kien', 'chon chuong', 'nguyen to', 'thu thach npc', 'dau truong']):
                return 'battle_menu'

            # Kiểm tra victory: bỏ qua 'chuoi chien thang' trong sảnh đấu trường
            def is_victory(text):
                if 'chuoi chien thang' in text:
                    return False
                return any(k in text for k in ['victory', 'chien thang', 'nhan bat ky', 'tap to continue'])

            if any(is_victory(n) for n in norms):
                return 'victory_pve'
            if has_kw(['thu lai', 'try again']) and not has_kw(['nhiem vu']):
                return 'task_complete'
            if has_kw(['nhat ky ark', 'nhiem vu hang ngay', 'di den']):
                return 'daily'
            if has_kw(['rank.', 'naranthir', 'battlepass', 'linh danh thue']):
                return 'lobby'


        return 'unknown'




    def _click_key(self, frame: np.ndarray, key: str) -> bool:
        """Bấm theo template; nếu không khớp thì dùng tọa độ fallback trong config."""
        target = self._find(frame, key) or self._coords.get(key)
        if not target:
            logger.warning("Không tìm thấy '%s' (template lẫn tọa độ fallback)", key)
            return False
        self.actions.click(int(target[0]), int(target[1]))
        return True

    def _click_via_gemini(self, frame: np.ndarray, hint: str) -> Optional[Tuple[int, int]]:
        located = self.vision.gemini.locate_element(frame, hint)
        if located is None:
            return None
        height, width = frame.shape[:2]
        point = (int(located[0] * width), int(located[1] * height))
        self.actions.click(*point)
        return point

    # ── Ngân sách năng lượng ──────────────────────────────────────────────

    def _refresh_energy(self, frame: np.ndarray) -> None:
        reading = self.vision.read_energy(frame)
        if reading is None:
            return
        current = reading[0]
        if self.energy_now is not None and current < self.energy_now:
            spent_delta = self.energy_now - current
            self.last_run_cost = spent_delta
            self.energy_spent += spent_delta
        if self.energy_start is None:
            self.energy_start = current
            logger.info("[ENERGY] Bắt đầu với %d/%d", current, reading[1])
        self.energy_now = current

    def _budget_allows_next_run(self) -> bool:
        max_spend = self.bot_cfg.get('max_mana_to_spend', -1)
        keep_min = self.bot_cfg.get('keep_mana_minimum', 0)
        if self.energy_now is not None and self.energy_now - self.last_run_cost < keep_min:
            logger.info("[ENERGY] Chạm mức giữ lại %d (còn %d)", keep_min, self.energy_now)
            return False
        if max_spend != -1 and self.energy_spent + self.last_run_cost > max_spend:
            logger.info("[ENERGY] Đã tiêu %d, lượt tới tốn ~%d > hạn mức %d",
                        self.energy_spent, self.last_run_cost, max_spend)
            return False
        return True

    # ── Handlers ──────────────────────────────────────────────────────────

    def _handle_sync(self, frame: np.ndarray) -> None:
        screen = self._classify(frame)
        routes: dict[str, Callable[[], None]] = {
            'popup': self.popup_detected,
            'task_complete': self.task_completed,
            'victory_pvp': self.victory_pvp,
            'victory_pve': self.victory_pve,
            'daily': self.at_daily,
            'battle_menu': self.at_battle_menu,
            'lobby': self.at_lobby,
        }
        if screen in ('lobby', 'daily'):
            self._refresh_energy(frame)
        if screen in routes:
            routes[screen]()
            return
        back_target = self._find(frame, 'back_btn')
        if not back_target and hasattr(self.vision, 'find_text_on_game'):
            back_target = self.vision.find_text_on_game(['Quay lai', 'Tro ve'])
        if back_target:
            logger.info("[SYNC] Màn '%s' không thuộc luồng → bấm Quay lại tại %s", screen, back_target)
            self.actions.click(*back_target)
            self.actions.stage_wait()
            return
        time.sleep(1.5)


    def _handle_open_daily(self, frame: np.ndarray) -> None:
        target = self._coords.get('daily_open_btn')
        if not target and hasattr(self.vision, 'ocr'):
            target = self.vision.ocr.find_keyword(frame, ['Nhat ky', 'Nhiem vu', 'Con duong'])

        if target:
            self.actions.click(int(target[0]), int(target[1]))
        else:
            point = self._click_via_gemini(frame, DAILY_OPEN_HINT)
            if point is None:
                logger.warning("[OPEN_DAILY] Gemini không tìm được nút mở Nhật ký Ark")
                self.stuck()
                return
            self._coords['daily_open_btn'] = list(point)

        self.actions.stage_wait()
        self.resync()

    def _pick_go_button(self, frame: np.ndarray) -> Optional[Tuple[int, int]]:
        # 1. Thử template matcher trước (cực nhanh và chính xác nếu có template)
        path = self.cfg.get('templates', {}).get('daily_go_btn')
        if path and hasattr(self.vision, 'matcher'):
            for center in self.vision.matcher.find_all_centers(frame, path):
                if all(abs(center[1] - row) > GO_BTN_ROW_TOLERANCE_PX for row in self._failed_go_rows):
                    return center

        # 2. Fallback sang Semantic OCR nếu template không khớp
        if hasattr(self.vision, 'ocr'):
            matches = self.vision.ocr.find_keywords(frame, ['Di den', 'Di'])
            for m in matches:
                pt = m['center']
                if all(abs(pt[1] - row) > GO_BTN_ROW_TOLERANCE_PX for row in self._failed_go_rows):
                    logger.info("[DAILY] Tìm thấy nút 'Đi đến' qua OCR tại %s", pt)
                    return pt
        return None


    def _handle_check_daily_list(self, frame: np.ndarray) -> None:
        self.stuck_count = 0
        self._refresh_energy(frame)
        if not self._budget_allows_next_run():
            logger.info("[DAILY] Hạn mức năng lượng đã chạm giới hạn → chuyển sang nhận thưởng")
            self.collect_rewards()
            return
        target = self._pick_go_button(frame)
        if target is None:
            # Kiểm tra xem có nút 'Nhận' nhiệm vụ đã hoàn thành không
            if hasattr(self.vision, 'find_text_on_game'):
                claim_btn = self.vision.find_text_on_game(['Nhan', 'Nhan tat ca'])
                if claim_btn:
                    logger.info("[DAILY] Bấm nút nhận thưởng nhiệm vụ tại %s", claim_btn)
                    self.actions.click(*claim_btn)
                    time.sleep(1.0)
                    self.resync()
                    return

            logger.info("[DAILY] Không còn nút 'Đi đến' khả dụng → tiến hành nhận thưởng")
            self.collect_rewards()
            return

        self._current_go_row = target[1]
        self.actions.click(*target)
        self.task_found()

    def _handle_navigate_to_task(self, frame: np.ndarray) -> None:
        logger.info("[NAVIGATE] Đang điều hướng từ nhiệm vụ vào ải chiến đấu...")
        wait_s = random.uniform(*self._battle_wait_range)
        time.sleep(wait_s)

        if not hasattr(self.vision, '_frames') and hasattr(self.vision, 'find_text_on_game'):
            # 1. Nếu đang ở màn chọn chế độ chiến đấu / sự kiện:
            event_btn = self.vision.find_text_on_game(['Khoang Lang', 'Ngoai Chon', 'Nguyen To', 'Chon Chuong'])
            if event_btn:
                logger.info("[NAVIGATE] Tìm thấy chế độ chiến đấu tại %s -> Click...", event_btn)
                self.actions.click(*event_btn)
                time.sleep(1.8)

            # 2. Nếu đang ở màn chọn ải hoặc chuẩn bị đội hình:
            start_btn = self.vision.find_text_on_game(['Chien dau', 'Bat dau', 'Start'])
            if start_btn:
                logger.info("[NAVIGATE] Tìm thấy nút bắt đầu tại %s -> Click...", start_btn)
                self.actions.click(*start_btn)
                time.sleep(2.0)

        self.battle_started()

    def _handle_in_battle(self, frame: np.ndarray) -> None:
        screen = self._classify(frame)
        routes = {'task_complete': self.task_completed, 'victory_pvp': self.victory_pvp,
                  'victory_pve': self.victory_pve, 'popup': self.popup_detected}
        if screen in routes:
            routes[screen]()
            return

        if self._time_in_state() > self._battle_timeout_s:
            self._mark_current_task_failed()
            self.stuck()
            return
        if random.random() < 0.25 and hasattr(self.actions, 'idle_drift'):
            self.actions.idle_drift(max_offset_px=10)
        time.sleep(2.0)

    def _mark_current_task_failed(self) -> None:
        """Task không dẫn tới trận (vd nâng cấp thành viên) → bỏ qua dòng này ở lượt sau."""
        if self._current_go_row is not None:
            logger.warning("[BATTLE] Quá %ss không thấy kết quả → bỏ qua task ở y=%d",
                            self._battle_timeout_s, self._current_go_row)
            self._failed_go_rows.append(self._current_go_row)
            self._current_go_row = None

    def _handle_victory(self, frame: np.ndarray, button_key: str) -> None:
        if not self._click_key(frame, button_key):
            if hasattr(self.vision, 'find_text_on_game'):
                confirm_pt = self.vision.find_text_on_game(['Xac nhan', 'Tiep tuc', 'Nhan', 'Ket thuc'])
                if confirm_pt:
                    logger.info("[VICTORY] Click nút xác nhận qua OCR tại %s", confirm_pt)
                    self.actions.click(*confirm_pt)


        self.actions.stage_wait()
        self.resync()

    def _handle_task_complete(self, frame: np.ndarray) -> None:
        self.tasks_done += 1
        logger.info("[TASK] Đã xong %d lượt (năng lượng đã tiêu: %d)",
                    self.tasks_done, self.energy_spent)

        if self._budget_allows_next_run() and self._click_key(frame, 'task_retry_btn'):
            logger.info("[TASK] Bấm 'Thử lại'")
            self.actions.stage_wait()
            self.retry_started()
            return

        if not self._click_key(frame, 'task_close_btn'):
            if hasattr(self.vision, 'find_text_on_game'):
                close_pt = self.vision.find_text_on_game(['Dong', 'Close', 'Xac nhan'])
                if close_pt:
                    self.actions.click(*close_pt)

        self.actions.stage_wait()
        self.resync()



    def _handle_collect_rewards(self, frame: np.ndarray) -> None:
        logger.info("[REWARDS] 🎁 Bắt đầu thu thập toàn bộ phần thưởng ngày & quà hoàn thành...")
        # 1. Bấm lần lượt qua các mốc rương nhiệm vụ ngày (10, 20, 30, 50, 80, 100)
        chests = self.cfg.get('daily_chests', [])
        for chest_pt in chests:
            logger.info("[REWARDS] Bấm rương quà tại (%d, %d)", chest_pt[0], chest_pt[1])
            self.actions.click(chest_pt[0], chest_pt[1])
            time.sleep(0.4)
            # Nhấn Space / Esc để đóng dialog nhận quà
            self.actions.press_key('space')
            time.sleep(0.2)

        # 2. Nếu có nút Battle Pass ("Nhận tất cả phần thưởng") thì bấm nhận
        bp_btn = self._find(frame, 'bp_collect_btn')
        if bp_btn:
            logger.info("[REWARDS] 🏆 Tìm thấy nút Battle Pass 'Nhận tất cả phần thưởng' tại %s", bp_btn)
            self.actions.click(*bp_btn)
            self.actions.stage_wait()
            self.actions.press_key('space')

        logger.info("[REWARDS] ✅ Đã hoàn tất toàn bộ tiến trình thu thập phần thưởng!")
        self.finish()

    def _handle_popup(self, frame: np.ndarray) -> None:
        self.actions.press_key('escape')
        self.actions.stage_wait()
        if not self._popup_visible(self.vision.grab_frame()):
            self.resync()
            return
        if self._click_via_gemini(self.vision.last_frame, POPUP_CLOSE_HINT) is None:
            self.stuck()
            return
        self.actions.stage_wait()
        self.resync()

    def _handle_stuck(self, frame: np.ndarray) -> None:
        self.stuck_count += 1
        if self.stuck_count > self.MAX_STUCK_RETRIES:
            logger.error("[STUCK] Kẹt quá %d lần → dừng bot", self.MAX_STUCK_RETRIES)
            self.finish()
            return
        logger.warning("[STUCK] Lần %d/%d — nhờ Gemini Vision", self.stuck_count, self.MAX_STUCK_RETRIES)
        result = self.vision.gemini.analyze_screen(frame)
        height, width = frame.shape[:2]
        self.actions.act_from_gemini(result, width, height)
        self.actions.stage_wait()
        self.resync()

    # ── Vòng lặp chính ────────────────────────────────────────────────────

    def _handlers(self) -> dict[str, Callable[[np.ndarray], None]]:
        return {
            'SYNC': self._handle_sync,
            'OPEN_DAILY': self._handle_open_daily,
            'CHECK_DAILY_LIST': self._handle_check_daily_list,
            'NAVIGATE_TO_TASK': self._handle_navigate_to_task,
            'IN_BATTLE_WAITING': self._handle_in_battle,
            'HANDLE_VICTORY_PVE': lambda f: self._handle_victory(f, 'victory_pve_confirm'),
            'HANDLE_VICTORY_PVP': lambda f: self._handle_victory(f, 'victory_pvp_end'),
            'HANDLE_TASK_COMPLETE': self._handle_task_complete,
            'HANDLE_POPUP': self._handle_popup,
            'HANDLE_STUCK': self._handle_stuck,
            'COLLECT_REWARDS': self._handle_collect_rewards,
        }

    def _watchdog_tripped(self) -> bool:
        exempt = ('IN_BATTLE_WAITING', 'NAVIGATE_TO_TASK', 'HANDLE_STUCK')
        return self.state not in exempt and self._time_in_state() > self._watchdog_s

    def tick(self) -> None:
        """Một bước FSM: chụp 1 frame và giao cho handler của state hiện tại."""
        if self._watchdog_tripped():
            logger.warning("[WATCHDOG] '%s' kẹt quá %ss", self.state, self._watchdog_s)
            self.stuck()
            return
        frame = self.vision.grab_frame()
        try:
            self._handlers()[self.state](frame)
        except Exception:
            logger.exception("[FSM] Lỗi trong state %s", self.state)
            time.sleep(2.0)

    def run(self) -> dict:
        logger.info("Bắt đầu — hạn mức %s, giữ lại %s",
                    self.bot_cfg.get('max_mana_to_spend', -1), self.bot_cfg.get('keep_mana_minimum', 0))
        try:
            while self.state != 'DONE':
                self.tick()
                time.sleep(self.LOOP_SLEEP_S)
        finally:
            self.vision.close()
        summary = {'status': 'DONE', 'tasks_done': self.tasks_done,
                   'energy_spent': self.energy_spent, 'stuck_count': self.stuck_count}
        logger.info("Kết thúc: %s", summary)
        return summary


def create_agent(vision, actions, game_cfg: dict, bot_cfg: dict) -> ArkRecodeAgent:
    return ArkRecodeAgent(vision, actions, game_cfg, bot_cfg)
