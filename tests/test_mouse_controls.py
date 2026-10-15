"""마우스 입력, 유한 탄약, 일시정지, 줌 변환 검증."""
import math
import os
import unittest
from collections import defaultdict
from unittest.mock import patch

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import pygame

from config import GameConfig
from env import TankEnv
from game_core import GameCore, Tank, decode_action
from main import GameApplication, read_player_input
from renderer import Renderer


def key_state(*pressed):
    return defaultdict(bool, {key: True for key in pressed})


class MouseControlTests(unittest.TestCase):
    def setUp(self):
        cfg = GameConfig(num_shapes=0, num_enemies=0)
        cfg.terrain.enabled = False
        self.game = GameCore(cfg, seed=1)
        # 좌표 변환 검사는 실제 창/이미지 캐시 없이 실행한다.
        self.renderer = object.__new__(Renderer)
        self.renderer.cfg = cfg
        self.renderer.screen = pygame.Surface((960, 720))
        self.renderer.view_width, self.renderer.view_height = 1600, 1200
        self.renderer._update_camera(self.game.player)

    def test_wasd_movement_is_independent_of_mouse_aim_and_fire(self):
        game, renderer = self.game, self.renderer
        sx, sy = renderer.world_to_screen(game.player.x, game.player.y)
        action, target, fire = read_player_input(key_state(pygame.K_d), renderer, (sx, sy + 100), (False, False, False))
        self.assertEqual(decode_action(action), (3, 0))
        self.assertFalse(fire)
        before = game.player.x
        game.step(action, want_fire=fire, aim_position=target)
        self.assertGreater(game.player.x, before)
        self.assertEqual(game.bullets, [])
        action, target, fire = read_player_input(key_state(pygame.K_w), renderer, (sx, sy + 100), (True, False, False))
        self.assertEqual(decode_action(action), (1, 0))
        before_y = game.player.y
        game.step(action, want_fire=fire, aim_position=target)
        self.assertLess(game.player.y, before_y)
        self.assertEqual(len(game.bullets), 1)
        bullet = game.bullets[0]
        self.assertAlmostEqual(math.atan2(bullet.vy, bullet.vx), game.player.angle)
        self.assertGreater(bullet.vy, 0)  # 위로 이동하면서 아래로 조준/발사
        self.assertEqual(game.player.ammo, 119)

    def test_right_click_does_not_move_and_wasd_supports_diagonals(self):
        mouse = (800, 360)
        action, _, _ = read_player_input(key_state(), self.renderer, mouse, (False, False, True))
        self.assertEqual(decode_action(action), (0, 0))
        for pressed, expected in (((pygame.K_w, pygame.K_a), 8),
                                  ((pygame.K_s, pygame.K_d), 4),
                                  ((pygame.K_w, pygame.K_s), 0),
                                  ((pygame.K_a, pygame.K_d), 0)):
            action, _, _ = read_player_input(key_state(*pressed), self.renderer, mouse, (False, False, False))
            self.assertEqual(decode_action(action), (expected, 0))

    def test_ammo_exhaustion_cooldown_and_three_shot_partial_volley(self):
        game, p = self.game, self.game.player
        p.ammo = 2
        p.job, p.projectiles = "triple_wing", 3
        game._fire(p, True)
        self.assertEqual(len(game.bullets), 2)
        self.assertEqual(p.ammo, 0)
        p.cooldown = 0
        game._fire(p, True)
        self.assertEqual(len(game.bullets), 2)
        p.ammo, p.cooldown = 5, 4
        game._fire(p, True)
        self.assertEqual((p.ammo, p.cooldown), (5, 3))
        p.cooldown = 0
        game._fire(p, False)
        self.assertEqual(p.ammo, 5)
        enemy = Tank(99, "enemy", p.x + 100, p.y, 60, 60, 22, 36)
        game._fire(enemy, True)
        self.assertEqual(len(game.bullets), 3)

    def test_restart_restores_ammo_and_training_remains_unlimited(self):
        game = self.game
        game.player.ammo = 0
        game.reset(1)
        self.assertEqual(game.player.ammo, 120)
        env = TankEnv()
        self.assertFalse(env.game_cfg.limited_ammo)
        env.game._fire(env.game.player, True)
        self.assertEqual(env.game.player.ammo, env.game.player.max_ammo)
        self.assertIsNone(env.reset(seed=1)[1]["ammo"])

    def test_zoom_coordinate_round_trip_and_small_world_centering(self):
        renderer = self.renderer
        self.assertGreater(renderer.view_width, renderer.cfg.width)
        for pos in ((0, 0), (480, 360), (960, 720)):
            world = renderer.screen_to_world(*pos)
            screen = renderer.world_to_screen(*world)
            self.assertAlmostEqual(screen[0], pos[0])
            self.assertAlmostEqual(screen[1], pos[1])
        renderer.cfg.world_scale = 1
        renderer._update_camera(self.game.player)
        self.assertEqual((renderer.camera_x, renderer.camera_y), (-320, -240))

    def test_pause_focus_loss_freeze_but_stat_selection_keeps_game_running(self):
        game = self.game
        app = GameApplication(game, self.renderer, seed=1)
        app.activate("start")
        game._add_score(60)
        key = lambda k: app.handle_event(pygame.event.Event(pygame.KEYDOWN, key=k))
        key(pygame.K_p)
        state = (game.frame, game.player.x, game.player.ammo)
        app.update(0.1, key_state(pygame.K_d), (800, 360), (True, False, False))
        self.assertEqual((game.frame, game.player.x, game.player.ammo), state)
        key(pygame.K_ESCAPE)
        app.update(1 / 60, key_state(pygame.K_d), (800, 360), (False, False, False))
        self.assertGreater(game.player.x, state[1])
        app.handle_event(pygame.event.Event(pygame.WINDOWFOCUSLOST))
        self.assertEqual(app.mode, "pause")
        key(pygame.K_p)
        key(pygame.K_1)
        state = (game.frame, game.player.x, game.player.ammo)
        app.update(0.1, key_state(pygame.K_d), (800, 360), (True, False, False))
        self.assertGreater(game.frame, state[0])
        self.assertGreater(game.player.x, state[1])
        self.assertEqual(sum(game.stat_levels.values()), 1)

    def test_quick_click_survives_a_frame_without_a_simulation_tick(self):
        app = GameApplication(self.game, self.renderer, seed=1)
        app.activate("start")
        app.update(0, key_state(), (800, 360), (False, False, False))
        app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=(800, 360)))
        app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=(800, 360)))
        frames = []
        for elapsed in (0.005, 0.015, 0.017):
            app.update(elapsed, key_state(), (800, 360), (False, False, False))
            frames.append((self.game.frame, self.game.player.ammo))
        self.assertEqual(frames, [(0, 120), (1, 119), (2, 119)])

    def test_q_and_space_do_not_activate_combat_actions(self):
        app = GameApplication(self.game, self.renderer, seed=1)
        app.activate("start")
        with patch.object(self.game, "request_skill", wraps=self.game.request_skill) as skill:
            for key in (pygame.K_q, pygame.K_SPACE):
                app.handle_event(pygame.event.Event(pygame.KEYDOWN, key=key))
            app.update(1 / 60, key_state(pygame.K_q, pygame.K_SPACE), (800, 360), (False, False, False))
            skill.assert_not_called()
        self.assertEqual(self.game.bullets, [])
        self.assertEqual(self.game.frame, 1)


if __name__ == "__main__":
    unittest.main()
