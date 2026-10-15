"""WASD 이동과 마우스 조준/발사로 플레이하는 진입점.

WASD 이동 + 커서 조준 + 좌클릭 발사. ESC 메뉴, R 재장전.
게임은 1/60초 고정 간격으로 업데이트되고, 화면 그리기는 그와 별개로 돈다.

    python main.py                 # 랜덤 seed, 기본 맵
    python main.py --seed 42       # 고정 seed
    python main.py --map belt      # maps/belt.txt
    python main.py --random-map    # 랜덤 맵 생성
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
from menus import menu_buttons
from progression import stat_rows, special_cards, stat_upgrades_visible

MAX_FRAMES_PER_TICK = 5  # 느린 PC에서 업데이트가 밀려 멈추는 것 방지


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
        self.selected = 0
        self.acc = 0.0
        self.action = 0
        self.click_requested = False
        self.suppress_fire = True
        self.map_cycle = [("map", m) for m in list_maps()] + [("random", None), ("empty", None)]

    def buttons(self):
        return menu_buttons(self.mode, self.cfg, self.show_debug, self.show_controls, self.auto_pause,
                            getattr(self.renderer, "fullscreen", False), self.size)

    @property
    def size(self):
        return getattr(self.renderer, "size", (self.cfg.width, self.cfg.height))

    def activate(self, key):
        self.show_stats = False
        self.click_requested = False
        self.suppress_fire = True
        self.acc = 0.0
        if key in ("start", "restart"):
            self.game.reset(self.seed)
            self.mode, self.selected = "playing", 0
        elif key == "resume":
            self.mode = "playing"
        elif key == "main":
            self.mode, self.selected = "main", 0
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
                if ev.key in (pygame.K_UP, pygame.K_DOWN, pygame.K_TAB):
                    direction = -1 if ev.key == pygame.K_UP else 1
                    index = enabled.index(self.selected) if self.selected in enabled else 0
                    self.selected = enabled[(index + direction) % len(enabled)]
                elif ev.key in (pygame.K_RETURN, pygame.K_SPACE):
                    self.activate(buttons[self.selected].key)
                elif ev.key == pygame.K_q and self.mode == "pause":
                    self.activate("quit")
            return
        if ev.type == pygame.KEYDOWN:
            stats = (pygame.K_1, pygame.K_2, pygame.K_3, pygame.K_4, pygame.K_5)
            specials = (pygame.K_F2, pygame.K_F3, pygame.K_F4, pygame.K_F5)
            if ev.key in stats:
                choices = self.game.open_stat_upgrades()
                if stats.index(ev.key) < len(choices):
                    self.game.upgrade_stat(choices[stats.index(ev.key)].key)
                return
            if ev.key in specials:
                self.game.choose_reward(specials.index(ev.key))
                return
            if ev.key == pygame.K_r:
                self.game.request_reload()
            elif ev.key == pygame.K_RETURN and self.game.game_over:
                self.activate("restart")
            elif ev.key == pygame.K_F1:
                self.show_debug = not self.show_debug
            elif ev.key == pygame.K_n:
                tc = self.cfg.terrain
                cur = ("empty", None) if not tc.enabled else ("random", None) if tc.random_map else ("map", tc.map_name)
                kind, name = self.map_cycle[(self.map_cycle.index(cur) + 1) % len(self.map_cycle)] \
                    if cur in self.map_cycle else self.map_cycle[0]
                tc.enabled, tc.random_map = kind != "empty", kind == "random"
                if name:
                    tc.map_name = name
                self.activate("restart")
        elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            if self.pointer_over_minimap(ev.pos):
                self.suppress_fire, self.click_requested = True, False
                return
            if self.cfg.progression_enabled:
                rows = stat_rows(*self.size, self.game.open_stat_upgrades()) if stat_upgrades_visible(self.game) else []
                for card, rect in rows:
                    if pygame.Rect(rect).collidepoint(ev.pos):
                        self.game.upgrade_stat(card.key)
                        self.suppress_fire, self.click_requested = True, False
                        return
                if self.game.reward_choices:
                    for index, rect in enumerate(special_cards(*self.size, len(self.game.reward_choices))):
                        if pygame.Rect(rect).collidepoint(ev.pos):
                            self.game.choose_reward(index)
                            self.suppress_fire, self.click_requested = True, False
                            return
            if not self.suppress_fire:
                self.click_requested = True

    def pointer_over_minimap(self, pos):
        get_rect = getattr(self.renderer, "minimap_rect", None)
        return bool(get_rect is not None and get_rect().collidepoint(pos))

    def pointer_over_rewards(self, pos):
        if self.pointer_over_minimap(pos):
            return True
        if not self.cfg.progression_enabled:
            return False
        rects = ([rect for card, rect in stat_rows(*self.size, self.game.open_stat_upgrades())]
                 if stat_upgrades_visible(self.game) else [])
        if self.game.reward_choices:
            rects += special_cards(*self.size, len(self.game.reward_choices))
        return any(pygame.Rect(rect).collidepoint(pos) for rect in rects)

    def update(self, elapsed, keys, mouse_pos, buttons):
        self.show_stats = (self.mode == "playing" and not self.game.game_over
                           and bool(keys[pygame.K_TAB]))
        if not buttons[0]:
            self.suppress_fire = False
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
                           show_stats=self.show_stats)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--map", default=None, help=f"맵 이름 ({', '.join(list_maps())})")
    parser.add_argument("--random-map", action="store_true", help="랜덤 맵 생성")
    parser.add_argument("--no-terrain", action="store_true", help="벽 없는 빈 경기장")
    parser.add_argument("--stage2", action="store_true", help="진흙/부서지는 벽 켜기")
    args = parser.parse_args()

    pygame.init()
    cfg = GameConfig()
    tc = cfg.terrain
    tc.enabled = not args.no_terrain
    tc.random_map = args.random_map
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


if __name__ == "__main__":
    main()
    sys.exit(0)
