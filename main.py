"""WASD 이동과 마우스 조준/발사로 플레이하는 진입점.

WASD 이동 + 커서 조준 + 좌클릭 발사. ESC 메뉴, R 재장전.
게임은 1/60초 고정 간격으로 업데이트되고, 화면 그리기는 그와 별개로 돈다.

    python main.py                 # 랜덤 seed, 랜덤 지형 (흩어진 벽 덩어리)
    python main.py --seed 42       # 고정 seed
    python main.py --map belt      # maps/belt.txt 미로
    python main.py --no-terrain    # 빈 경기장
    python main.py --stage2        # 진흙/부서지는 벽 켜기
"""
import argparse
import sys

import pygame

from config import GameConfig, ObsConfig
from env import build_vector
from game_core import GameCore, encode_action, move_from_vector
from terrain import list_maps
from menus import DIFFICULTY_OPTIONS, menu_buttons
from progression import (stat_rows, special_cards, stat_upgrades_visible, stat_panel_rect,
                         stat_collapsed_rect, STAT_PANEL_IDLE_SECONDS)

MAX_FRAMES_PER_TICK = 5  # 느린 PC에서 업데이트가 밀려 멈추는 것 방지


# 읽는 순서: main()에서 실행 준비 → GameApplication.handle_event() → update() → draw().
# 실제 규칙은 GameCore.step(), 화면 표현은 Renderer에서 처리한다.
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--map", default=None, help=f"맵 이름 ({', '.join(list_maps())})")
    parser.add_argument("--random-map", action="store_true", help="랜덤 지형 (기본값)")
    parser.add_argument("--no-terrain", action="store_true", help="벽 없는 빈 경기장")
    parser.add_argument("--stage2", action="store_true", help="진흙/부서지는 벽 켜기")
    parser.add_argument("--limited-ammo", action="store_true", help="탄약 제한 켜기 (기본은 무제한)")
    args = parser.parse_args()

    pygame.init()
    cfg = GameConfig(limited_ammo=args.limited_ammo)
    tc = cfg.terrain
    tc.enabled = not args.no_terrain
    tc.random_map = args.random_map or not args.map   # --map을 주지 않으면 랜덤 지형
    tc.mud_enabled = tc.breakable_enabled = args.stage2
    if args.map:
        tc.map_name = args.map
    obs_cfg = ObsConfig()
    from renderer import Renderer
    renderer = Renderer(cfg)
    game = GameCore(cfg, seed=args.seed)
    app = GameApplication(game, renderer, args.seed)
    while app.running:
        for ev in pygame.event.get():
            app.handle_event(ev)
            if not app.running:
                break
        if not app.running:
            break
        app.update(renderer.clock.tick(cfg.fps) / 1000.0, pygame.key.get_pressed(),
                   pygame.mouse.get_pos(), pygame.mouse.get_pressed())
        app.draw(obs_cfg)
        pygame.display.flip()
    pygame.quit()


# 사람 입력을 코어의 행동으로 바꾸거나 디버그 표시용 값으로 읽는 보조 함수.
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


# 실행 중 상태: 메뉴 선택·입력·시간 누적을 관리하고 코어와 렌더러를 연결한다.
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
        self.selected = next(i for i, button in enumerate(self.buttons()) if button.key == "start")
        self.acc = 0.0
        self.action = 0
        self.click_requested = False
        self.suppress_fire = True
        self.stat_touch_frame = 0      # 스탯 창을 마지막으로 건드린 게임 프레임
        self.stat_points_seen = 0

    def buttons(self):
        return menu_buttons(self.mode, self.cfg, self.show_debug, self.show_controls, self.auto_pause,
                            getattr(self.renderer, "fullscreen", False), self.size, self.difficulty_ratio)

    @property
    def size(self):
        return getattr(self.renderer, "size", (self.cfg.width, self.cfg.height))

    def touch_stat_panel(self):
        self.stat_touch_frame = self.game.frame

    @property
    def stats_collapsed(self):
        idle = self.game.frame - self.stat_touch_frame
        return stat_upgrades_visible(self.game) and idle >= STAT_PANEL_IDLE_SECONDS * self.cfg.fps

    def activate(self, key):
        for option_key, _, ratio in DIFFICULTY_OPTIONS:
            if key == option_key:
                if self.mode == "main":
                    self.difficulty_ratio = ratio
                return
        self.show_stats = False
        self.click_requested = False
        self.suppress_fire = True
        self.acc = 0.0
        if key in ("start", "restart"):
            if key == "start":
                self.cfg.enemy_ai.stat_mirror_ratio = self.difficulty_ratio
            self.game.reset(self.seed)
            self.stat_touch_frame = self.stat_points_seen = 0
            self.mode, self.selected = "playing", 0
        elif key == "resume":
            self.mode = "playing"
        elif key == "main":
            self.mode = "main"
            self.selected = next(i for i, button in enumerate(self.buttons()) if button.key == "start")
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
            self.acc = 0.0
            return
        if ev.type == pygame.QUIT:
            self.running = False
            return
        if ev.type == pygame.WINDOWFOCUSLOST and self.auto_pause and self.mode == "playing":
            self.mode = "pause"
            self.selected = next(i for i, b in enumerate(self.buttons()) if b.key == "resume")
            self.acc = 0.0
            self.click_requested = False
            self.suppress_fire = True
            return
        if ev.type == pygame.KEYDOWN and ev.key in (pygame.K_ESCAPE, pygame.K_p):
            if self.mode == "playing":
                self.mode = "pause"
                self.selected = next(i for i, b in enumerate(self.buttons()) if b.key == "resume")
                self.acc = 0.0
                self.click_requested = False
                self.suppress_fire = True
            elif self.mode == "pause":
                self.activate("resume")
            return
        if self.mode in ("main", "pause"):
            buttons = self.buttons()
            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                for i, button in enumerate(buttons):
                    if button.enabled and button.rect.collidepoint(ev.pos):
                        self.selected = i
                        self.activate(button.key)
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
                            targets = difficulties if self.selected in difficulties else [self.selected]
                        elif ev.key in (pygame.K_UP, pygame.K_DOWN) and difficulties:
                            # 상하는 난이도 행을 하나로 묶고, 다시 들어오면 확정한 난이도에 둔다.
                            focus = self.selected if self.selected in difficulties else next(
                                (i for i in difficulties if buttons[i].checked), difficulties[0])
                            targets = [i for i in enabled if i not in difficulties or i == focus]
                    elif ev.key in (pygame.K_LEFT, pygame.K_RIGHT):
                        targets = [self.selected]
                    index = targets.index(self.selected) if self.selected in targets else 0
                    self.selected = targets[(index + direction) % len(targets)]
                elif ev.key in (pygame.K_RETURN, pygame.K_SPACE):
                    self.activate(buttons[self.selected].key)
                elif ev.key == pygame.K_q and self.mode == "pause":
                    self.activate("quit")
            return
        if ev.type == pygame.KEYDOWN:
            stats = (pygame.K_1, pygame.K_2, pygame.K_3, pygame.K_4, pygame.K_5)
            specials = (pygame.K_F2, pygame.K_F3, pygame.K_F4, pygame.K_F5)
            if ev.key in stats:
                self.touch_stat_panel()
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
                self.activate("restart")
            elif ev.key == pygame.K_F1:
                self.show_debug = not self.show_debug
            elif ev.key == pygame.K_n:
                tc = self.cfg.terrain
                # N은 파일 맵 순환 대신 8×8 블록 지형으로 새 판을 만든다.
                tc.enabled = tc.random_map = True
                tc.block_tiles = 8
                if self.seed is not None:
                    self.seed += 1  # 고정 시드도 다음 맵으로 이동하고, 재시작은 현재 맵을 유지한다.
                self.activate("restart")
        elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            if self.cfg.progression_enabled:
                if self.stats_collapsed and pygame.Rect(stat_collapsed_rect(*self.size)).collidepoint(ev.pos):
                    self.touch_stat_panel()
                    self.suppress_fire, self.click_requested = True, False
                    return
                rows = (stat_rows(*self.size, self.game.progression.open_stat_upgrades())
                        if stat_upgrades_visible(self.game) and not self.stats_collapsed else [])
                for card, rect in rows:
                    if pygame.Rect(rect).collidepoint(ev.pos):
                        self.touch_stat_panel()
                        self.game.progression.upgrade_stat(card.key)
                        self.suppress_fire, self.click_requested = True, False
                        return
                if self.game.progression.reward_choices:
                    for index, rect in enumerate(special_cards(*self.size, len(self.game.progression.reward_choices))):
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
        if not stat_upgrades_visible(self.game):
            rects = []
        elif self.stats_collapsed:
            rects = [stat_collapsed_rect(*self.size)]
        else:
            rects = [rect for card, rect in stat_rows(*self.size, self.game.progression.open_stat_upgrades())]
        if self.game.progression.reward_choices:
            rects += special_cards(*self.size, len(self.game.progression.reward_choices))
        return any(pygame.Rect(rect).collidepoint(pos) for rect in rects)

    def update(self, elapsed, keys, mouse_pos, buttons):
        self.show_stats = (self.mode == "playing" and not self.game.game_over
                           and bool(keys[pygame.K_TAB]))
        if not buttons[0]:
            self.suppress_fire = False
        # 새 스탯 포인트가 생기거나 마우스를 창 위에 두면 스탯 창을 다시 펼친다.
        if self.game.progression.upgrade_points > self.stat_points_seen:
            self.touch_stat_panel()
        self.stat_points_seen = self.game.progression.upgrade_points
        if stat_upgrades_visible(self.game):
            panel = stat_collapsed_rect(*self.size) if self.stats_collapsed else stat_panel_rect(*self.size)
            if pygame.Rect(panel).collidepoint(mouse_pos):
                self.touch_stat_panel()
        if self.mode != "playing" or self.game.game_over:
            self.acc = 0.0
            self.click_requested = False
            return
        dt = 1.0 / self.cfg.fps
        self.acc = min(self.acc + elapsed, dt * MAX_FRAMES_PER_TICK)
        while self.acc >= dt:
            self.renderer._update_camera(self.game.player)
            self.action, target, want_fire = read_player_input(keys, self.renderer, mouse_pos, buttons)
            fire = (want_fire or self.click_requested) and not self.suppress_fire and not self.pointer_over_rewards(mouse_pos)
            self.game.step(self.action, want_fire=fire, aim_position=target)
            self.click_requested = False
            self.game.pop_events()
            self.acc -= dt
            if self.game.game_over:
                self.acc = 0.0
                break

    def draw(self, obs_cfg):
        if self.mode == "main":
            self.renderer.draw_main_menu(self.buttons(), self.selected)
            return
        lines = debug_lines(self.game, obs_cfg, self.action) if self.show_debug else None
        self.renderer.draw(self.game, lines, self.mode == "pause", show_ai=self.show_debug,
                           show_controls=self.show_controls,
                           menu=self.buttons() if self.mode == "pause" else None, selected=self.selected,
                           show_stats=self.show_stats, stats_collapsed=self.stats_collapsed)


if __name__ == "__main__":
    main()
    sys.exit(0)
