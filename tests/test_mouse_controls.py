"""마우스 입력, 유한 탄약, 일시정지, 줌 변환 검증."""
import math
import os
import unittest
from collections import defaultdict
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import pygame

from config import GameConfig
from env import TankEnv
from game_core import GameCore, Tank, decode_action
from main import read_player_input
from progression import REWARD_CARDS
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
        p.projectiles = 3
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

    def test_supply_card_caps_ammo_and_restart_restores_ammo(self):
        game = self.game
        card = next(c for c in REWARD_CARDS if c.key == "ammo")
        game.player.ammo = 110
        game.pending_rewards = 1
        game.reward_choices = (card,)
        self.assertTrue(game.choose_reward(0))
        self.assertEqual(game.player.ammo, 120)
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

    def test_pause_focus_loss_and_reward_menu_block_fire_and_motion(self):
        import main
        pygame.init()
        pygame.display.set_mode((960, 720))
        game = self.game
        game._add_score(60)
        frames = []
        positions = []
        clock = Mock()
        clock.tick.return_value = 17
        def capture(g, lines, paused, **kwargs):
            frames.append((g.frame, g.player.ammo, paused, kwargs["rewards_open"]))
            positions.append((g.player.x, g.player.y))
        fake = SimpleNamespace(clock=clock, draw=capture,
                               _update_camera=self.renderer._update_camera,
                               screen_to_world=self.renderer.screen_to_world)
        key = lambda k: [pygame.event.Event(pygame.KEYDOWN, key=k)]
        batches = [key(pygame.K_p), [], key(pygame.K_ESCAPE),
                   [pygame.event.Event(pygame.WINDOWFOCUSLOST)], [],
                   key(pygame.K_l), key(pygame.K_ESCAPE), [],
                   key(pygame.K_p), [pygame.event.Event(pygame.QUIT)]]
        with patch("sys.argv", ["main.py"]), patch("main.GameCore", return_value=game), \
                patch("renderer.Renderer", return_value=fake), \
                patch("pygame.event.get", side_effect=batches), \
                patch("pygame.mouse.get_pos", return_value=(800, 360)), \
                patch("pygame.key.get_pressed", return_value=key_state(pygame.K_d)), \
                patch("pygame.mouse.get_pressed", return_value=(True, False, True)):
            main.main()
        self.assertEqual(frames[:2], [(0, 120, True, False)] * 2)
        self.assertEqual(frames[2][:2], (1, 119))
        self.assertEqual(frames[3:5], [(1, 119, True, False)] * 2)
        self.assertEqual(frames[5], (1, 119, True, True))
        self.assertEqual(frames[6:8], [(1, 119, True, False)] * 2)
        self.assertEqual(frames[8][0], 2)
        self.assertEqual(positions[0], positions[1])
        self.assertGreater(positions[2][0], positions[1][0])
        self.assertTrue(all(pos == positions[2] for pos in positions[3:8]))
        self.assertGreater(positions[8][0], positions[7][0])

    def test_quick_click_survives_a_frame_without_a_simulation_tick(self):
        import main
        pygame.init()
        pygame.display.set_mode((960, 720))
        clock = Mock()
        clock.tick.side_effect = (5, 15, 17)
        frames = []
        fake = SimpleNamespace(clock=clock,
                               draw=lambda g, *a, **kw: frames.append((g.frame, g.player.ammo)),
                               _update_camera=self.renderer._update_camera,
                               screen_to_world=self.renderer.screen_to_world)
        batches = [[pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1),
                    pygame.event.Event(pygame.MOUSEBUTTONUP, button=1)],
                   [], [], [pygame.event.Event(pygame.QUIT)]]
        with patch("sys.argv", ["main.py"]), patch("main.GameCore", return_value=self.game), \
                patch("renderer.Renderer", return_value=fake), \
                patch("pygame.event.get", side_effect=batches), \
                patch("pygame.mouse.get_pos", return_value=(800, 360)), \
                patch("pygame.mouse.get_pressed", return_value=(False, False, False)):
            main.main()
        self.assertEqual(frames, [(0, 120), (1, 119), (2, 119)])


if __name__ == "__main__":
    unittest.main()
