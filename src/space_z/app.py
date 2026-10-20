"""사람 플레이의 입력·메뉴·시간 누적과 코어·화면 연결."""
import pygame

from space_z.rl.environment import build_vector
from space_z.game.game_core import encode_action, move_from_vector
from space_z.rendering.menu_layout import DIFFICULTY_OPTIONS, build_menu_buttons
from space_z.rendering.progression_panel import build_stat_upgrade_rows, get_evolution_card_rects, can_show_stat_upgrades, get_expanded_stat_panel_rect, get_collapsed_stat_panel_rect, STAT_PANEL_IDLE_SECONDS

MAX_FRAMES_PER_TICK = 5  # 느린 PC에서 밀린 업데이트를 제한한다.


def read_player_input(keys, renderer, mouse_pos, buttons):
    target = renderer.screen_to_world(*mouse_pos)
    dx = keys[pygame.K_d] - keys[pygame.K_a]
    dy = keys[pygame.K_s] - keys[pygame.K_w]
    move = move_from_vector(dx, dy)
    return encode_action(move, 0), target, bool(buttons[0])


def debug_lines(game, obs_cfg, action):
    obs = build_vector(game, obs_cfg)
    f = lambda v: f"{v:+.2f}"
    lines = [f"vector obs {obs.size} (+ terrain grid)   action {action}   frame {game.frame}",
             "self x,y " + f(obs[0]) + " " + f(obs[1]) + "  v " + f(obs[2]) + " " + f(obs[3]),
             "self hp " + f(obs[4]) + "  sin/cos " + f(obs[5]) + " " + f(obs[6]) + "  rl " + f(obs[7]),
             f"map {game.terrain.name}   enemies seeing you: {sum(e.alive and e.ai_can_see for e in game.enemies)}"]
    i = obs_cfg.SELF_DIM
    for n in range(obs_cfg.n_enemies):
        e = obs[i:i + obs_cfg.ENEMY_DIM]
        lines.append(f"enemy{n} ex{e[0]:.0f} d({f(e[1])},{f(e[2])}) hp{e[5]:.2f}")
        i += obs_cfg.ENEMY_DIM
    for n in range(min(3, obs_cfg.n_shapes)):
        s = obs[i:i + obs_cfg.SHAPE_DIM]
        lines.append(f"shape{n} ex{s[0]:.0f} d({f(s[1])},{f(s[2])}) hp{s[3]:.2f} sc{s[4]:.2f}")
        i += obs_cfg.SHAPE_DIM
    i = obs_cfg.vector_size - obs_cfg.n_rays - obs_cfg.n_bullets * obs_cfg.BULLET_DIM
    nb = int(sum(obs[i + k * obs_cfg.BULLET_DIM] for k in range(obs_cfg.n_bullets)))
    lines.append(f"enemy bullets in obs: {nb}/{obs_cfg.n_bullets}")
    lines.append("(lines: green = enemy sees you, yellow = A* path)")
    return lines


class GameApplication:
    """메뉴와 사람 입력을 관리한다. 열린 메뉴에서는 게임 시간을 진행하지 않는다."""
    def __init__(self, game, renderer, seed=None):
        self.game, self.renderer, self.seed = game, renderer, seed
        self.cfg = game.cfg
        self.mode = "main"
        self.running = True
        self.show_debug = False
        self.show_controls = True
        self.show_stats = False
        self.auto_pause = True
        self.difficulty_ratio = 0.5
        self.selected_button_index = next(i for i, button in enumerate(self.get_menu_buttons()) if button.key == "start")
        self.accumulated_time = 0.0
        self.action = 0
        self.click_requested = False
        self.suppress_fire = True
        self.stat_panel_last_used_frame = 0      # 스탯 창을 마지막으로 건드린 게임 프레임
        self.previous_upgrade_points = 0

    def get_menu_buttons(self):
        return build_menu_buttons(self.mode, self.cfg, self.show_debug, self.show_controls, self.auto_pause,
                            getattr(self.renderer, "fullscreen", False), self.size, self.difficulty_ratio)

    @property
    def size(self):
        return getattr(self.renderer, "size", (self.cfg.width, self.cfg.height))

    def mark_stat_panel_used(self):
        self.stat_panel_last_used_frame = self.game.frame

    @property
    def stat_panel_collapsed(self):
        idle = self.game.frame - self.stat_panel_last_used_frame
        return can_show_stat_upgrades(self.game) and idle >= STAT_PANEL_IDLE_SECONDS * self.cfg.fps

    def activate_menu_action(self, key):
        for option_key, _, ratio in DIFFICULTY_OPTIONS:
            if key == option_key:
                if self.mode == "main":
                    self.difficulty_ratio = ratio
                return
        self.show_stats = False
        self.click_requested = False
        self.suppress_fire = True
        self.accumulated_time = 0.0
        if key in ("start", "restart"):
            if key == "start":
                self.cfg.enemy_ai.stat_mirror_ratio = self.difficulty_ratio
            self.game.reset(self.seed)
            self.stat_panel_last_used_frame = self.previous_upgrade_points = 0
            self.mode, self.selected_button_index = "playing", 0
        elif key == "resume":
            self.mode = "playing"
        elif key == "main":
            self.mode = "main"
            self.selected_button_index = next(i for i, button in enumerate(self.get_menu_buttons()) if button.key == "start")
        elif key == "quit":
            self.running = False
        elif key == "zoom":
            zooms = (0.45, 0.6, 0.75, 1.0)
            current = min(range(len(zooms)), key=lambda i: abs(zooms[i] - self.cfg.camera_zoom))
            self.renderer.set_zoom(zooms[(current + 1) % len(zooms)])
        elif key == "fullscreen":
            self.renderer.set_fullscreen(not self.renderer.fullscreen)
        elif key == "controls":
            self.show_controls = not self.show_controls
        elif key == "debug":
            self.show_debug = not self.show_debug
        elif key == "auto_pause":
            self.auto_pause = not self.auto_pause

    def handle_event(self, ev):
        if ev.type == pygame.VIDEORESIZE:
            self.renderer.resize(ev.size)
            self.accumulated_time = 0.0
            return
        if ev.type == pygame.QUIT:
            self.running = False
            return
        if ev.type == pygame.WINDOWFOCUSLOST and self.auto_pause and self.mode == "playing":
            self.mode = "pause"
            self.selected_button_index = next(i for i, b in enumerate(self.get_menu_buttons()) if b.key == "resume")
            self.accumulated_time = 0.0
            self.click_requested = False
            self.suppress_fire = True
            return
        if ev.type == pygame.KEYDOWN and ev.key in (pygame.K_ESCAPE, pygame.K_p):
            if self.mode == "playing":
                self.mode = "pause"
                self.selected_button_index = next(i for i, b in enumerate(self.get_menu_buttons()) if b.key == "resume")
                self.accumulated_time = 0.0
                self.click_requested = False
                self.suppress_fire = True
            elif self.mode == "pause":
                self.activate_menu_action("resume")
            return
        if self.mode in ("main", "pause"):
            buttons = self.get_menu_buttons()
            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                for i, button in enumerate(buttons):
                    if button.enabled and button.rect.collidepoint(ev.pos):
                        self.selected_button_index = i
                        self.activate_menu_action(button.key)
                        break
            elif ev.type == pygame.KEYDOWN:
                enabled = [i for i, button in enumerate(buttons) if button.enabled]
                if ev.key in (pygame.K_UP, pygame.K_DOWN, pygame.K_LEFT, pygame.K_RIGHT, pygame.K_TAB):
                    direction = -1 if ev.key in (pygame.K_UP, pygame.K_LEFT) else 1
                    targets = enabled
                    if self.mode == "main":
                        difficulties = [i for i in enabled if buttons[i].key.startswith("difficulty_")]
                        if ev.key in (pygame.K_LEFT, pygame.K_RIGHT):
                            # 좌우는 난이도 행 안에서만 순환한다.
                            targets = difficulties if self.selected_button_index in difficulties else [self.selected_button_index]
                        elif ev.key in (pygame.K_UP, pygame.K_DOWN) and difficulties:
                            # 상하는 난이도 행을 하나로 묶고, 다시 들어오면 확정한 난이도에 둔다.
                            focus = self.selected_button_index if self.selected_button_index in difficulties else next(
                                (i for i in difficulties if buttons[i].checked), difficulties[0])
                            targets = [i for i in enabled if i not in difficulties or i == focus]
                    elif ev.key in (pygame.K_LEFT, pygame.K_RIGHT):
                        targets = [self.selected_button_index]
                    index = targets.index(self.selected_button_index) if self.selected_button_index in targets else 0
                    self.selected_button_index = targets[(index + direction) % len(targets)]
                elif ev.key in (pygame.K_RETURN, pygame.K_SPACE):
                    self.activate_menu_action(buttons[self.selected_button_index].key)
                elif ev.key == pygame.K_q and self.mode == "pause":
                    self.activate_menu_action("quit")
            return
        if ev.type == pygame.KEYDOWN:
            stats = (pygame.K_1, pygame.K_2, pygame.K_3, pygame.K_4, pygame.K_5)
            specials = (pygame.K_F2, pygame.K_F3, pygame.K_F4, pygame.K_F5)
            if ev.key in stats:
                self.mark_stat_panel_used()
                choices = self.game.progression.open_stat_upgrades()
                if stats.index(ev.key) < len(choices):
                    self.game.progression.upgrade_stat(choices[stats.index(ev.key)].key)
                return
            if ev.key in specials:
                self.game.progression.choose_reward(specials.index(ev.key))
                return
            if ev.key == pygame.K_r:
                self.game.combat.request_reload()
            elif ev.key == pygame.K_RETURN and self.game.game_over:
                self.activate_menu_action("restart")
            elif ev.key == pygame.K_F1:
                self.show_debug = not self.show_debug
            elif ev.key == pygame.K_n:
                tc = self.cfg.terrain
                # N은 파일 맵 순환 대신 8×8 블록 지형으로 새 판을 만든다.
                tc.enabled = tc.random_map = True
                tc.block_tiles = 8
                if self.seed is not None:
                    self.seed += 1  # 고정 시드도 다음 맵으로 이동하고, 재시작은 현재 맵을 유지한다.
                self.activate_menu_action("restart")
        elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            if self.cfg.progression_enabled:
                if self.stat_panel_collapsed and pygame.Rect(get_collapsed_stat_panel_rect(*self.size)).collidepoint(ev.pos):
                    self.mark_stat_panel_used()
                    self.suppress_fire, self.click_requested = True, False
                    return
                rows = (build_stat_upgrade_rows(*self.size, self.game.progression.open_stat_upgrades())
                        if can_show_stat_upgrades(self.game) and not self.stat_panel_collapsed else [])
                for card, rect in rows:
                    if pygame.Rect(rect).collidepoint(ev.pos):
                        self.mark_stat_panel_used()
                        self.game.progression.upgrade_stat(card.key)
                        self.suppress_fire, self.click_requested = True, False
                        return
                if self.game.progression.reward_choices:
                    for index, rect in enumerate(get_evolution_card_rects(*self.size, len(self.game.progression.reward_choices))):
                        if pygame.Rect(rect).collidepoint(ev.pos):
                            self.game.progression.choose_reward(index)
                            self.suppress_fire, self.click_requested = True, False
                            return
            if not self.suppress_fire:
                self.click_requested = True

    def pointer_over_minimap(self, pos):
        get_rect = getattr(self.renderer, "minimap_rect", None)
        return bool(get_rect is not None and get_rect().collidepoint(pos))

    def pointer_over_rewards(self, pos):
        # 미니맵은 표시용이며 클릭과 드래그 모두 일반 월드 사격으로 처리한다.
        if not self.cfg.progression_enabled:
            return False
        if not can_show_stat_upgrades(self.game):
            rects = []
        elif self.stat_panel_collapsed:
            rects = [get_collapsed_stat_panel_rect(*self.size)]
        else:
            rects = [rect for card, rect in build_stat_upgrade_rows(*self.size, self.game.progression.open_stat_upgrades())]
        if self.game.progression.reward_choices:
            rects += get_evolution_card_rects(*self.size, len(self.game.progression.reward_choices))
        return any(pygame.Rect(rect).collidepoint(pos) for rect in rects)

    def update(self, elapsed, keys, mouse_pos, buttons):
        self.show_stats = (self.mode == "playing" and not self.game.game_over
                           and bool(keys[pygame.K_TAB]))
        if not buttons[0]:
            self.suppress_fire = False
        # 새 스탯 포인트가 생기거나 마우스를 창 위에 두면 스탯 창을 다시 펼친다.
        if self.game.progression.upgrade_points > self.previous_upgrade_points:
            self.mark_stat_panel_used()
        self.previous_upgrade_points = self.game.progression.upgrade_points
        if can_show_stat_upgrades(self.game):
            panel = get_collapsed_stat_panel_rect(*self.size) if self.stat_panel_collapsed else get_expanded_stat_panel_rect(*self.size)
            if pygame.Rect(panel).collidepoint(mouse_pos):
                self.mark_stat_panel_used()
        if self.mode != "playing" or self.game.game_over:
            self.accumulated_time = 0.0
            self.click_requested = False
            return
        dt = 1.0 / self.cfg.fps
        self.accumulated_time = min(self.accumulated_time + elapsed, dt * MAX_FRAMES_PER_TICK)
        while self.accumulated_time >= dt:
            self.renderer._update_camera(self.game.player)
            self.action, target, want_fire = read_player_input(keys, self.renderer, mouse_pos, buttons)
            fire = (want_fire or self.click_requested) and not self.suppress_fire and not self.pointer_over_rewards(mouse_pos)
            self.game.step(self.action, want_fire=fire, aim_position=target)
            self.click_requested = False
            self.game.pop_events()
            self.accumulated_time -= dt
            if self.game.game_over:
                self.accumulated_time = 0.0
                break

    def draw(self, obs_cfg):
        if self.mode == "main":
            self.renderer.draw_main_menu(self.get_menu_buttons(), self.selected_button_index)
            return
        lines = debug_lines(self.game, obs_cfg, self.action) if self.show_debug else None
        self.renderer.draw(self.game, lines, self.mode == "pause", show_ai=self.show_debug,
                           show_controls=self.show_controls,
                           menu=self.get_menu_buttons() if self.mode == "pause" else None, selected_button_index=self.selected_button_index,
                           show_stats=self.show_stats, stat_panel_collapsed=self.stat_panel_collapsed)
