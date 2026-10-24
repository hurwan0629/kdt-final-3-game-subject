"""사람 플레이의 입력·메뉴·시간 누적과 코어·화면 연결."""

import pygame

from space_z.game.game_core import GameCore
from space_z.rl.environment import build_vector
from space_z.game.game_core import encode_action, move_from_vector
from space_z.rendering.menu_layout import DIFFICULTY_OPTIONS, build_menu_buttons
from space_z.rendering.progression_panel import (
    build_stat_upgrade_rows,
    get_evolution_card_rects,
    can_show_stat_upgrades,
    get_expanded_stat_panel_rect,
    get_collapsed_stat_panel_rect,
    STAT_PANEL_IDLE_SECONDS,
)

MAX_FRAMES_PER_TICK = 5  # 느린 PC에서 밀린 업데이트를 제한한다.


def read_player_input(keys, renderer, mouse_pos, buttons):
    """현재 키·마우스 상태를 게임 행동과 월드 조준 좌표로 변환한다.

    인자:
        keys: pygame.key.get_pressed()처럼 키 코드로 누름 여부를 조회할 수 있는 객체.
        renderer: screen_to_world()로 화면 좌표를 월드 좌표로 변환하는 렌더러.
        mouse_pos: 마우스의 화면 좌표 (x, y). 단위는 화면 px이다.
        buttons: pygame.mouse.get_pressed()처럼 버튼별 누름 여부를 담은 시퀀스.
            첫 항목은 마우스 왼쪽 버튼이다.

    처리:
        마우스 위치를 월드 좌표로 바꾸고 WASD 조합을 정지 또는 8방향 이동 번호로 만든다.
        회전 번호는 0으로 고정한다. 마우스 조준은 반환한 목표 좌표로 별도 처리한다.

    반환:
        tuple[int, tuple[float, float], bool]: (행동 번호, 조준 월드 좌표, 발사 누름 여부).
        입력 객체와 게임 상태는 변경하지 않는다.
    """
    # 마우스 위치를 월드 조준 좌표로 바꾸고 WASD 이동 입력을 읽는다.
    target = renderer.screen_to_world(*mouse_pos)
    move_x = keys[pygame.K_d] - keys[pygame.K_a]
    move_y = keys[pygame.K_s] - keys[pygame.K_w]
    move = move_from_vector(move_x, move_y)
    return encode_action(move, 0), target, bool(buttons[0])


def debug_lines(game, observation_config, action):
    """현재 관측값과 AI 감지 상태를 디버그 화면용 문장 목록으로 만든다.

    인자:
        game: 관측을 만들 GameCore. 플레이어·적·천체·탄환·지형 상태를 조회한다.
        observation_config: 관측 슬롯 수와 각 항목의 벡터 길이를 정의하는 ObsConfig.
        action: 디버그 화면에 표시할 현재 행동 번호.

    처리:
        1) 관측 벡터를 만들고 정규화된 플레이어 상태와 플레이어를 보는 적 수를 표시한다.
        2) 적 관측 슬롯 전체와 천체 관측 슬롯 최대 세 개의 존재 여부·상대 위치 등을 표시한다.
        3) 관측에 포함된 적 탄환 수와 AI 감지·경로 선의 색상 안내를 덧붙인다.

    반환:
        list[str]: 렌더러가 위에서 아래로 그릴 디버그 문장 목록.
        위치·속도·체력 등은 원래 게임 단위가 아닌 관측 벡터의 정규화된 값이다.
        게임 상태는 변경하지 않는다.
    """
    # 플레이어 관측값을 위치·속도·체력·방향·발사 준비도로 나눈다.
    observation = build_vector(game, observation_config)
    (
        player_x,
        player_y,
        velocity_x,
        velocity_y,
        health_ratio,
        direction_sine,
        direction_cosine,
        fire_readiness,
    ) = observation[: observation_config.SELF_DIM]
    seeing_enemy_count = sum(enemy.alive and enemy.ai_can_see for enemy in game.enemies)

    # 관측 크기와 플레이어 상태를 디버그 화면에 표시할 문장으로 만든다.
    lines = [
        f"vector obs {observation.size} (+ terrain grid)   action {action}   frame {game.frame}",
        f"self x,y {player_x:+.2f} {player_y:+.2f}"
        f"  v {velocity_x:+.2f} {velocity_y:+.2f}",
        f"self hp {health_ratio:+.2f}"
        f"  sin/cos {direction_sine:+.2f} {direction_cosine:+.2f}"
        f"  rl {fire_readiness:+.2f}",
        f"map {game.terrain.name}   enemies seeing you: {seeing_enemy_count}",
    ]

    # 적 관측 슬롯별로 존재 여부·상대 위치·체력 비율을 표시한다.
    observation_offset = observation_config.SELF_DIM
    for slot_index in range(observation_config.n_enemies):
        enemy_observation = observation[
            observation_offset : observation_offset + observation_config.ENEMY_DIM
        ]
        exists, relative_x, relative_y, _, _, health_ratio, _, _ = enemy_observation
        lines.append(
            f"enemy{slot_index} ex{exists:.0f}"
            f" d({relative_x:+.2f},{relative_y:+.2f}) hp{health_ratio:.2f}"
        )
        observation_offset += observation_config.ENEMY_DIM

    # 천체는 앞의 세 슬롯까지 상대 위치·체력·점수 비율을 표시한다.
    for slot_index in range(min(3, observation_config.n_shapes)):
        shape_observation = observation[
            observation_offset : observation_offset + observation_config.SHAPE_DIM
        ]
        exists, relative_x, relative_y, health_ratio, score_ratio, _ = shape_observation
        lines.append(
            f"shape{slot_index} ex{exists:.0f}"
            f" d({relative_x:+.2f},{relative_y:+.2f})"
            f" hp{health_ratio:.2f} sc{score_ratio:.2f}"
        )
        observation_offset += observation_config.SHAPE_DIM

    # 적 탄환 구간의 시작 위치를 구하고 실제 탄환이 들어 있는 슬롯을 센다.
    observation_offset = (
        observation_config.vector_size
        - observation_config.n_rays
        - observation_config.n_bullets * observation_config.BULLET_DIM
    )
    visible_bullet_count = int(
        sum(
            observation[
                observation_offset + bullet_index * observation_config.BULLET_DIM
            ]
            for bullet_index in range(observation_config.n_bullets)
        )
    )

    # 탄환 수와 AI 경로 표시의 색상 안내를 덧붙인다.
    lines.append(
        f"enemy bullets in obs: {visible_bullet_count}/{observation_config.n_bullets}"
    )
    lines.append("(lines: green = enemy sees you, yellow = A* path)")
    return lines


class GameApplication:
    """메뉴와 사람 입력을 관리한다. 열린 메뉴에서는 게임 시간을 진행하지 않는다."""

    def __init__(self, game: GameCore, renderer, seed=None):
        """게임·렌더러를 연결하고 시작 메뉴와 입력 처리 상태를 초기화한다.

        인자:
            game: 사람 입력을 적용할 GameCore. 설정 객체도 이 게임과 공유한다.
            renderer: 화면·카메라·메뉴·점수 연출을 관리하는 렌더러.
            seed: 새 판과 재시작에 전달할 정수 시드 또는 None.

        처리:
            시작 메뉴와 기본 난이도·화면 옵션을 설정하고 시작 버튼에 키보드 포커스를 둔다.
            고정 프레임용 누적 시간, 발사 억제, 클릭 보관, 스탯 패널 사용 기록을 초기화한다.
            전달받은 게임을 여기서 새로 만들거나 재시작하지는 않는다.

        반환:
            None: 현재 GameApplication 인스턴스의 상태를 초기화한다.
        """
        # 게임·화면 참조와 새 판을 재현할 시드를 보관한다.
        self.game = game
        self.renderer = renderer
        self.seed = seed
        self.config = game.config

        # 시작 메뉴와 화면에 표시할 안내·디버그 옵션을 초기화한다.
        self.mode = "main"
        self.running = True
        self.show_debug = False
        self.show_controls = True
        self.show_stats = False
        self.auto_pause = True
        self.difficulty_ratio = 0.5
        self.selected_button_index = next(
            button_index
            for button_index, button in enumerate(self.get_menu_buttons())
            if button.key == "start"
        )

        # 고정 프레임 진행과 클릭·스탯 패널 입력에 사용할 상태를 초기화한다.
        self.accumulated_time = 0.0
        self.action = 0
        self.click_requested = False
        self.suppress_fire = True
        self.stat_panel_last_used_frame = 0  # 스탯 창을 마지막으로 건드린 게임 프레임
        self.previous_upgrade_points = 0

    def get_menu_buttons(self):
        """현재 메뉴 모드와 설정값에 맞는 버튼 목록을 만든다.

        인자:
            없음. 현재 모드·화면 옵션·난이도·창 크기를 인스턴스에서 조회한다.

        처리:
            build_menu_buttons()에 표시 상태를 전달해 버튼 문구·클릭 영역·선택 상태를 계산한다.
            렌더러에 fullscreen 속성이 없으면 창 모드로 취급한다.

        반환:
            list[MenuButton]: 화면 표시와 입력 판정이 함께 사용하는 순서 있는 버튼 목록.
        """
        return build_menu_buttons(
            self.mode,
            self.config,
            self.show_debug,
            self.show_controls,
            self.auto_pause,
            getattr(self.renderer, "fullscreen", False),
            self.size,
            self.difficulty_ratio,
        )

    @property
    def size(self):
        """입력 영역과 패널 배치에 사용할 현재 화면 크기를 조회한다.

        인자:
            없음.

        처리:
            렌더러의 size 속성을 사용한다. 없으면 게임 설정의 기준 가로·세로 길이를 사용한다.

        반환:
            tuple[int, int]: (가로, 세로) 크기. 단위는 화면 px이다.
        """
        return getattr(self.renderer, "size", (self.config.width, self.config.height))

    def mark_stat_panel_used(self):
        """스탯 패널을 사용한 시점을 현재 게임 프레임으로 기록한다.

        인자:
            없음.

        처리:
            마지막 사용 프레임을 갱신해 스탯 패널이 자동으로 접힐 때까지의 대기를 다시 시작한다.

        반환:
            None: stat_panel_last_used_frame을 변경한다.
        """
        self.stat_panel_last_used_frame = self.game.frame

    @property
    def stat_panel_collapsed(self):
        """스탯 패널을 접힌 상태로 표시할지 판단한다.

        인자:
            없음.

        처리:
            스탯 표시가 가능한 상태인지 확인하고 마지막 사용 뒤 지난 게임 프레임 수를 비교한다.
            접힘 대기 시간은 STAT_PANEL_IDLE_SECONDS와 게임 fps로 정한다.
            실제 시계 대신 게임 프레임을 쓰므로 게임 진행이 멈추면 대기 시간도 늘지 않는다.

        반환:
            bool: 스탯 표시가 가능하고 대기 시간이 지났으면 True, 아니면 False.
        """
        idle_frames = self.game.frame - self.stat_panel_last_used_frame
        return (
            can_show_stat_upgrades(self.game)
            and idle_frames >= STAT_PANEL_IDLE_SECONDS * self.config.fps
        )

    def activate_menu_action(self, key):
        """메뉴 항목의 키에 대응하는 게임 전환 또는 설정 변경을 적용한다.

        인자:
            key: MenuButton.key 문자열. 난이도 키 또는 start, restart, resume,
                main, quit, zoom, fullscreen, controls, debug, auto_pause를 사용한다.

        처리:
            1) 난이도 키는 시작 메뉴에서 선택값만 바꾸고 즉시 반환한다.
            2) 나머지 키는 능력치 창·대기 클릭·누적 시간을 비우고 발사를 일시 억제한다.
            3) 시작·재시작은 게임과 점수 연출을 초기화한다. 난이도 반영은 start에서만 수행한다.
            4) 다른 항목은 메뉴 모드·종료 여부·줌·전체화면·안내 옵션 중 해당 상태를 변경한다.

        반환:
            None: 앱 상태와 필요한 게임·렌더러 설정을 변경한다.
        """
        # 난이도 선택은 시작 전 메뉴에서만 반영한다.
        for option_key, _, ratio in DIFFICULTY_OPTIONS:
            if key == option_key:
                if self.mode == "main":
                    self.difficulty_ratio = ratio
                return

        # 메뉴 전환 전에 누적 시간과 발사 입력을 정리한다.
        self.show_stats = False
        self.click_requested = False
        self.suppress_fire = True
        self.accumulated_time = 0.0

        # 선택한 메뉴 항목에 따라 게임 진행 상태나 화면 옵션을 바꾼다.
        if key in ("start", "restart"):
            if key == "start":
                self.config.enemy_ai.stat_mirror_ratio = self.difficulty_ratio
            self.game.reset(self.seed)
            self.renderer.reset_score_popups()
            self.stat_panel_last_used_frame = self.previous_upgrade_points = 0
            self.mode, self.selected_button_index = "playing", 0
        elif key == "resume":
            self.mode = "playing"
        elif key == "main":
            self.mode = "main"
            self.selected_button_index = next(
                button_index
                for button_index, button in enumerate(self.get_menu_buttons())
                if button.key == "start"
            )
        elif key == "quit":
            self.running = False
        elif key == "zoom":
            zooms = (0.45, 0.6, 0.75, 1.0)
            current = min(
                range(len(zooms)),
                key=lambda button_index: abs(
                    zooms[button_index] - self.config.camera_zoom
                ),
            )
            self.renderer.set_zoom(zooms[(current + 1) % len(zooms)])
        elif key == "fullscreen":
            self.renderer.set_fullscreen(not self.renderer.fullscreen)
        elif key == "controls":
            self.show_controls = not self.show_controls
        elif key == "debug":
            self.show_debug = not self.show_debug
        elif key == "auto_pause":
            self.auto_pause = not self.auto_pause

    def handle_event(self, event):
        """이벤트 우선순위에 따라 창·일시정지·메뉴·플레이 담당 메서드로 전달한다.

        인자:
            event: pygame 이벤트. 세부 속성은 이벤트를 담당하는 내부 메서드가 조회한다.

        처리:
            창·일시정지 이벤트를 먼저 처리하고 소비됐다면 반환한다.
            메뉴가 열려 있으면 메뉴 입력으로만 전달하고, 그 외에는 키 입력과 왼쪽 클릭을 분리한다.
            지속적인 이동·조준·버튼 누름 상태는 update()에서 별도로 처리한다.

        반환:
            None: 전달한 담당 메서드가 필요한 앱·게임·렌더러 상태를 변경한다.
        """
        if self._handle_window_event(event):
            return

        if self._handle_pause_event(event):
            return

        if self.mode in ("main", "pause"):
            self._handle_menu_event(event)
            return

        if event.type == pygame.KEYDOWN:
            self._handle_play_keydown(event.key)
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            self._handle_play_click(event.pos)

    def pointer_over_minimap(self, position):
        """화면 좌표가 미니맵 안에 있는지 조회한다.

        인자:
            position: 검사할 화면 좌표 (x, y). 단위는 화면 px이다.

        처리:
            렌더러가 minimap_rect()를 제공하면 현재 미니맵 영역과 좌표를 비교한다.
            이 조회 자체는 발사를 차단하거나 입력 상태를 변경하지 않는다.

        반환:
            bool: 좌표가 미니맵 안이면 True. 영역 조회 메서드가 없거나 바깥이면 False.
        """
        get_minimap_rect = getattr(self.renderer, "minimap_rect", None)
        return bool(
            get_minimap_rect is not None and get_minimap_rect().collidepoint(position)
        )

    def pointer_over_rewards(self, position):
        """화면 좌표가 월드 발사를 차단할 스탯·진화 UI 영역에 속하는지 판단한다.

        인자:
            position: 마우스의 화면 좌표 (x, y). 단위는 화면 px이다.

        처리:
            성장 기능이 꺼져 있으면 즉시 False를 반환한다.
            스탯 표시 상태에 따라 접힌 패널 또는 펼친 스탯 행의 영역을 수집하고,
            대기 중인 진화 카드 영역을 추가해 좌표를 검사한다. 미니맵은 포함하지 않는다.
            펼친 스탯 목록 조회 과정에서 성장 담당 객체의 표시용 선택지가 갱신될 수 있다.

        반환:
            bool: 수집한 UI 영역 중 하나에 좌표가 들어가면 True, 아니면 False.
            강화 가능 여부와 관계없이 표시된 스탯 행은 발사 차단 영역에 포함한다.
        """
        # 미니맵은 표시용이며 클릭과 드래그 모두 일반 월드 사격으로 처리한다.
        if not self.config.progression_enabled:
            return False
        if not can_show_stat_upgrades(self.game):
            rects = []
        elif self.stat_panel_collapsed:
            rects = [get_collapsed_stat_panel_rect(*self.size)]
        else:
            rects = [
                rect
                for card, rect in build_stat_upgrade_rows(
                    *self.size, self.game.progression.open_stat_upgrades()
                )
            ]
        if self.game.progression.reward_choices:
            rects += get_evolution_card_rects(
                *self.size, len(self.game.progression.reward_choices)
            )
        return any(pygame.Rect(rect).collidepoint(position) for rect in rects)

    def update(self, elapsed, keys, mouse_pos, buttons):
        """입력 표시 상태를 갱신하고 누적 시간만큼 고정 프레임으로 게임을 진행한다.

        인자:
            elapsed: 이전 화면 갱신 뒤 경과한 시간(초). 밀리초 값은 초로 변환해 전달한다.
            keys: 키 코드별 누름 여부를 조회할 수 있는 객체. WASD와 Tab 상태를 읽는다.
            mouse_pos: 마우스 화면 좌표 (x, y), 화면 px 단위.
            buttons: 마우스 버튼별 누름 여부. 첫 항목은 왼쪽 버튼이다.

        처리:
            1) Tab 능력치 창, 버튼 해제에 따른 발사 억제 해제, 스탯 패널 사용 기록을 갱신한다.
            2) 메뉴가 열려 있거나 게임이 끝났으면 누적 시간·대기 클릭을 비우고 진행을 멈춘다.
            3) 경과 시간을 누적하되 한 번에 MAX_FRAMES_PER_TICK개 프레임까지만 진행한다.
            4) 각 프레임에서 카메라·이동·조준·UI 발사 차단을 반영해 game.step()을 호출한다.
            5) 점수 연출 이벤트는 렌더러로 전달하고 처리한 클릭과 전투 이벤트를 비운다.

        반환:
            None: 게임·입력·시간 누적·점수 연출 상태를 변경한다. 화면 그리기는 draw()가 맡는다.
            진행할 프레임이 아직 없으면 보관한 짧은 클릭을 다음 갱신까지 유지한다.
        """
        # 현재 입력으로 능력치 창 표시와 발사 억제 상태를 갱신한다.
        self.show_stats = (
            self.mode == "playing"
            and not self.game.game_over
            and bool(keys[pygame.K_TAB])
        )
        if not buttons[0]:
            self.suppress_fire = False
        # 새 스탯 포인트가 생기거나 마우스를 창 위에 두면 스탯 창을 다시 펼친다.
        if self.game.progression.upgrade_points > self.previous_upgrade_points:
            self.mark_stat_panel_used()
        self.previous_upgrade_points = self.game.progression.upgrade_points
        if can_show_stat_upgrades(self.game):
            panel = (
                get_collapsed_stat_panel_rect(*self.size)
                if self.stat_panel_collapsed
                else get_expanded_stat_panel_rect(*self.size)
            )
            if pygame.Rect(panel).collidepoint(mouse_pos):
                self.mark_stat_panel_used()

        # 메뉴 또는 게임 종료 상태에서는 누적 시간을 비우고 진행을 멈춘다.
        if self.mode != "playing" or self.game.game_over:
            self.accumulated_time = 0.0
            self.click_requested = False
            return

        # 경과 시간을 누적하고 이번 화면 갱신에서 진행할 게임 프레임 수를 제한한다.
        seconds_per_frame = 1.0 / self.config.fps
        self.accumulated_time = min(
            self.accumulated_time + elapsed, seconds_per_frame * MAX_FRAMES_PER_TICK
        )

        # 고정 프레임마다 조준·이동·발사를 적용하고 발생한 화면 연출을 전달한다.
        while self.accumulated_time >= seconds_per_frame:
            self.renderer._update_camera(self.game.player)
            self.action, target, want_fire = read_player_input(
                keys, self.renderer, mouse_pos, buttons
            )
            fire = (
                (want_fire or self.click_requested)
                and not self.suppress_fire
                and not self.pointer_over_rewards(mouse_pos)
            )
            self.game.step(self.action, want_fire=fire, aim_position=target)
            self.renderer.add_score_popups(self.game.pop_score_award_events())
            self.click_requested = False
            self.game.pop_events()
            self.accumulated_time -= seconds_per_frame
            if self.game.game_over:
                self.accumulated_time = 0.0
                break

    def draw(self, observation_config):
        """현재 메뉴·플레이·패널 표시 상태에 맞는 화면을 렌더러에 요청한다.

        인자:
            observation_config: 디버그 문장을 만들 때 사용할 ObsConfig.

        처리:
            시작 메뉴에서는 메뉴 화면만 그린다.
            그 외에는 필요한 디버그 문장을 만들고 일시정지·조작 안내·능력치·스탯 패널 상태를
            렌더러에 전달한다. 게임 프레임은 진행하지 않으며 화면 버퍼 전환은 호출자가 수행한다.

        반환:
            None: 렌더러의 화면과 표시용 기록을 갱신한다.
        """
        # 시작 메뉴이면 메뉴 화면을 그리고 나머지 처리를 끝낸다.
        if self.mode == "main":
            self.renderer.draw_main_menu(
                self.get_menu_buttons(), self.selected_button_index
            )
            return

        # 디버그 옵션과 현재 메뉴·패널 상태를 렌더러에 전달한다.
        lines = (
            debug_lines(self.game, observation_config, self.action)
            if self.show_debug
            else None
        )
        self.renderer.draw(
            self.game,
            lines,
            self.mode == "pause",
            show_ai=self.show_debug,
            show_controls=self.show_controls,
            menu=self.get_menu_buttons() if self.mode == "pause" else None,
            selected_button_index=self.selected_button_index,
            show_stats=self.show_stats,
            stat_panel_collapsed=self.stat_panel_collapsed,
        )

    def _handle_window_event(self, event) -> bool:
        """창 크기 변경과 종료 이벤트를 처리하고 소비 여부를 반환한다.

        인자:
            event: pygame 이벤트. 크기 변경 이벤트에서는 size 속성(화면 px)을 조회한다.

        처리:
            창 크기가 바뀌면 렌더러를 갱신하고 누적 시간을 비운다.
            종료 요청이면 메인 루프의 실행 플래그를 내린다.

        반환:
            bool: 크기 변경 또는 종료 이벤트를 소비했으면 True, 다른 이벤트면 False.
        """
        # 창 크기 변경: 화면을 다시 만들고 이전 크기에서 쌓인 업데이트 대기를 비운다.
        if event.type == pygame.VIDEORESIZE:
            self.renderer.resize(event.size)
            self.accumulated_time = 0.0
            return True

        # 종료 요청: 메인 루프가 다음 검사에서 끝나도록 실행 플래그를 내린다.
        if event.type == pygame.QUIT:
            self.running = False
            return True
        return False

    def _handle_pause_event(self, event) -> bool:
        """포커스 상실과 ESC/P에 따른 일시정지 전환을 처리한다.

        인자:
            event: pygame 이벤트. 키 입력 이벤트에서는 key 속성을 조회한다.

        처리:
            자동 일시정지가 켜진 플레이 상태에서 포커스를 잃으면 일시정지한다.
            ESC/P는 플레이와 일시정지를 전환하며, 시작 메뉴에서는 상태를 유지하고 소비한다.
            일시정지 진입 시 계속하기 버튼에 포커스를 두고 누적 시간과 발사 입력을 정리한다.

        반환:
            bool: 일시정지를 적용했거나 ESC/P 키를 소비했으면 True, 아니면 False.
            True인 이벤트는 메뉴·플레이 입력으로 다시 전달하지 않는다.
        """

        # 포커스 상실: 자동 일시정지가 켜진 플레이 상태에서만 메뉴를 연다.
        if (
            event.type == pygame.WINDOWFOCUSLOST
            and self.auto_pause
            and self.mode == "playing"
        ):
            self.mode = "pause"
            # 메뉴를 연 뒤 Enter를 누르면 바로 이어 할 수 있도록 '계속하기'에 포커스를 둔다.
            self.selected_button_index = next(
                button_index
                for button_index, button in enumerate(self.get_menu_buttons())
                if button.key == "resume"
            )

            # 복귀 직후 밀린 프레임이나 이전 클릭이 발사로 이어지지 않도록 입력을 비운다.
            self.accumulated_time = 0.0
            self.click_requested = False
            self.suppress_fire = True
            return True

        # ESC/P: 플레이와 일시정지를 전환하고 같은 키를 메뉴 조작에 다시 쓰지 않는다.
        if event.type == pygame.KEYDOWN and event.key in (pygame.K_ESCAPE, pygame.K_p):
            if self.mode == "playing":
                # 일시정지 메뉴를 열고 기본 포커스·시간·발사 입력을 정리한다.
                self.mode = "pause"
                self.selected_button_index = next(
                    button_index
                    for button_index, button in enumerate(self.get_menu_buttons())
                    if button.key == "resume"
                )
                self.accumulated_time = 0.0
                self.click_requested = False
                self.suppress_fire = True
            elif self.mode == "pause":
                # 재개할 때의 공통 입력 정리는 메뉴 동작 처리에 맡긴다.
                self.activate_menu_action("resume")
            return True
        return False

    def _handle_menu_event(self, event) -> None:
        """시작·일시정지 메뉴의 마우스 선택과 키보드 탐색을 처리한다.

        인자:
            event: 메뉴에 전달할 pygame 이벤트. 종류에 따라 button, pos, key를 조회한다.
                pos는 화면 좌표(px)이며 button의 1은 왼쪽 버튼이다.

        처리:
            1) 현재 버튼 목록으로 활성 버튼의 클릭과 키보드 포커스를 판정한다.
            2) 방향키·Tab으로 탐색하고 Enter/Space로 선택한 항목을 실행한다.
               시작 메뉴의 좌우는 난이도 행 안에서 순환하고 상하는 난이도 행을 한 항목처럼 다룬다.
            3) 일시정지 메뉴에서 Q를 누르면 종료한다.
            호출자는 main 또는 pause 모드에서만 이 메서드에 이벤트를 전달한다.

        반환:
            None: 선택 포커스와 해당 메뉴 동작의 상태를 갱신한다.
            메뉴에서 받은 이벤트는 처리 여부에 관계없이 플레이 입력으로 넘기지 않는다.
        """
        buttons = self.get_menu_buttons()

        # 활성 버튼 안의 왼쪽 클릭만 선택·실행한다. 첫 일치 항목에서 탐색을 끝낸다.
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            for button_index, button in enumerate(buttons):
                if button.enabled and button.rect.collidepoint(event.pos):
                    self.selected_button_index = button_index
                    self.activate_menu_action(button.key)
                    break
        elif event.type == pygame.KEYDOWN:
            # 키보드로 이동할 수 있는 활성 버튼의 인덱스만 모은다.
            enabled = [
                button_index
                for button_index, button in enumerate(buttons)
                if button.enabled
            ]
            if event.key in (
                pygame.K_UP,
                pygame.K_DOWN,
                pygame.K_LEFT,
                pygame.K_RIGHT,
                pygame.K_TAB,
            ):
                # 위·왼쪽은 이전 항목, 아래·오른쪽·Tab은 다음 항목으로 이동한다.
                direction = -1 if event.key in (pygame.K_UP, pygame.K_LEFT) else 1
                targets = enabled
                if self.mode == "main":
                    # 시작 메뉴에서 난이도 버튼 행을 별도의 탐색 대상으로 구분한다.
                    difficulties = [
                        button_index
                        for button_index in enabled
                        if buttons[button_index].key.startswith("difficulty_")
                    ]
                    if event.key in (pygame.K_LEFT, pygame.K_RIGHT):
                        # 좌우는 난이도 행 안에서만 순환한다. 다른 행에서는 포커스를 유지한다.
                        targets = (
                            difficulties
                            if self.selected_button_index in difficulties
                            else [self.selected_button_index]
                        )
                    elif event.key in (pygame.K_UP, pygame.K_DOWN) and difficulties:
                        # 상하는 난이도 행을 한 항목처럼 넘나든다.
                        # 행 밖에서 돌아올 때는 확정한 난이도 버튼을 진입 지점으로 쓴다.
                        focus = (
                            self.selected_button_index
                            if self.selected_button_index in difficulties
                            else next(
                                (
                                    button_index
                                    for button_index in difficulties
                                    if buttons[button_index].checked
                                ),
                                difficulties[0],
                            )
                        )
                        targets = [
                            button_index
                            for button_index in enabled
                            if button_index not in difficulties or button_index == focus
                        ]
                elif event.key in (pygame.K_LEFT, pygame.K_RIGHT):
                    # 일시정지 메뉴의 세로 목록에서는 좌우로 포커스를 옮기지 않는다.
                    targets = [self.selected_button_index]

                # 현재 포커스의 위치에서 한 칸 이동하고 목록 끝에서는 반대쪽으로 순환한다.
                index = (
                    targets.index(self.selected_button_index)
                    if self.selected_button_index in targets
                    else 0
                )
                self.selected_button_index = targets[(index + direction) % len(targets)]
            elif event.key in (pygame.K_RETURN, pygame.K_SPACE):
                # Enter/Space는 현재 포커스의 버튼을 실행한다. 포커스 이동만으로는 확정하지 않는다.
                self.activate_menu_action(buttons[self.selected_button_index].key)
            elif event.key == pygame.K_q and self.mode == "pause":
                # 일시정지 메뉴에서만 Q를 종료 단축키로 사용한다.
                self.activate_menu_action("quit")

    def _handle_play_keydown(self, key: int) -> None:
        """메뉴 밖에서 누른 키를 강화·전투·새 판 명령으로 전달한다.

        인자:
            key: pygame.KEYDOWN 이벤트의 정수 키 코드.

        처리:
            숫자 1~5는 스탯 강화, F2~F5는 진화 선택, R은 재장전을 요청한다.
            게임 종료 뒤 Enter는 재시작, F1은 디버그 전환, N은 새 랜덤 맵 시작을 처리한다.
            강화·진화·재장전의 유효성 검사는 각 담당 객체에 맡긴다.

        반환:
            None: 해당 명령의 게임·입력·표시 상태를 변경한다. 그 외의 키는 무시한다.
        """
        stats = (pygame.K_1, pygame.K_2, pygame.K_3, pygame.K_4, pygame.K_5)
        specials = (pygame.K_F2, pygame.K_F3, pygame.K_F4, pygame.K_F5)

        # 숫자 1~5는 고정 순서의 스탯 행에 대응한다. 강화 가능 여부는 성장 담당 객체가 검사한다.
        if key in stats:
            self.mark_stat_panel_used()
            choices = self.game.progression.open_stat_upgrades()
            if stats.index(key) < len(choices):
                self.game.progression.upgrade_stat(choices[stats.index(key)].key)
            return

        # F2~F5는 현재 진화 선택지의 0~3번 항목에 대응한다.
        if key in specials:
            self.game.progression.choose_reward(specials.index(key))
            return

        # R은 재장전을 요청한다. 탄약 제한·탄창·생존 조건은 전투 담당 객체가 검사한다.
        if key == pygame.K_r:
            self.game.combat.request_reload()
        elif key == pygame.K_RETURN and self.game.game_over:
            # 게임이 끝난 뒤 Enter를 누르면 현재 시드로 새 판을 시작한다.
            self.activate_menu_action("restart")
        elif key == pygame.K_F1:
            # F1은 디버그 문장과 AI 감지·경로 표시를 함께 켜거나 끈다.
            self.show_debug = not self.show_debug
        elif key == pygame.K_n:
            terrain_config = self.config.terrain
            # N은 8×8 블록 랜덤 지형을 활성화하고 새 판을 시작한다.
            terrain_config.enabled = terrain_config.random_map = True
            terrain_config.block_tiles = 8
            if self.seed is not None:
                # 고정 시드도 다음 맵으로 이동하고, 재시작은 현재 맵을 유지한다.
                self.seed += 1
            self.activate_menu_action("restart")

    def _handle_play_click(self, position: tuple[int, int]) -> None:
        """메뉴 밖의 왼쪽 클릭을 UI 선택 또는 대기 발사 요청으로 처리한다.

        인자:
            position: pygame 마우스 클릭 이벤트의 화면 좌표 (x, y). 단위는 화면 px이다.

        처리:
            1) 접힌 스탯 창 펼치기, 표시된 스탯 행 강화, 진화 카드 선택 순으로 검사한다.
            2) UI가 클릭을 소비하면 대기 클릭을 비우고 버튼을 놓을 때까지 발사를 억제한다.
               스탯 강화가 실패하더라도 해당 행의 클릭은 소비한다.
            3) UI 밖의 클릭은 발사 억제 중이 아닐 때만 다음 update()를 위해 기록한다.
            호출자는 메뉴 밖의 왼쪽 버튼 누름 이벤트만 전달한다.

        반환:
            None: UI·성장·발사 입력 상태를 갱신한다. 여기서 게임 프레임을 진행하지 않는다.
        """
        if self.config.progression_enabled:
            # 접힌 스탯 창을 클릭하면 펼친다. 창을 여는 클릭은 강화나 발사로 넘기지 않는다.
            if self.stat_panel_collapsed and pygame.Rect(
                get_collapsed_stat_panel_rect(*self.size)
            ).collidepoint(position):
                self.mark_stat_panel_used()
                self.suppress_fire, self.click_requested = True, False
                return

            # 생존·성장·펼침 상태에서 실제로 표시되는 스탯 행의 클릭 영역만 만든다.
            rows = (
                build_stat_upgrade_rows(
                    *self.size, self.game.progression.open_stat_upgrades()
                )
                if can_show_stat_upgrades(self.game) and not self.stat_panel_collapsed
                else []
            )

            # 스탯 행을 클릭하면 강화를 시도한다. 포인트 부족 등으로 실패해도 UI 클릭은 소비한다.
            for card, rect in rows:
                if pygame.Rect(rect).collidepoint(position):
                    self.mark_stat_panel_used()
                    self.game.progression.upgrade_stat(card.key)
                    self.suppress_fire, self.click_requested = True, False
                    return

            # 진화 카드 영역을 클릭하면 해당 선택지를 적용하고 발사 입력을 차단한다.
            if self.game.progression.reward_choices:
                for index, rect in enumerate(
                    get_evolution_card_rects(
                        *self.size, len(self.game.progression.reward_choices)
                    )
                ):
                    if pygame.Rect(rect).collidepoint(position):
                        self.game.progression.choose_reward(index)
                        self.suppress_fire, self.click_requested = True, False
                        return

        # UI 밖의 짧은 클릭을 보관해, 이번 화면에서 게임 프레임이 없어도 다음 update에 전달한다.
        # 메뉴·UI 클릭 뒤 발사 억제 중이라면 왼쪽 버튼을 놓을 때까지 새 발사를 요청하지 않는다.
        if not self.suppress_fire:
            self.click_requested = True
