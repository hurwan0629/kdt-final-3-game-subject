"""월드/레벨업/카메라 회귀 검증. GUI 없이 실행 가능.

    python -m unittest discover -s tests -v
"""
import math
import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import numpy as np
import pygame

from config import GameConfig, ObsConfig
from env import TankEnv, build_vector
from game_core import Bullet, GameCore, encode_action
from progression import REWARD_CARDS
from renderer import Renderer
from terrain import list_maps


def empty_game(seed=7):
    cfg = GameConfig(num_enemies=0, num_shapes=0)
    cfg.terrain.enabled = False
    return GameCore(cfg, seed=seed)


class ProgressionTests(unittest.TestCase):
    def test_score_sources_and_multiple_levels(self):
        game = GameCore(seed=4)
        shape = game.shapes[0]
        score = shape.score
        game._damage_shape(shape, shape.hp, by_player=True)
        game._damage_tank(game.enemies[0], 1000, by_player=True)
        self.assertEqual(game.score, score + game.cfg.enemy_kill_score)
        expected_xp, expected_level = game.score, 1
        while expected_xp >= 60 + (expected_level - 1) * 40:
            expected_xp -= 60 + (expected_level - 1) * 40
            expected_level += 1
        self.assertEqual((game.level, game.xp, game.pending_rewards),
                         (expected_level, expected_xp, expected_level - 1))

    def test_cards_are_unique_persistent_and_consumed_once(self):
        game = empty_game()
        self.assertEqual(game.open_rewards(), ())
        game._add_score(190)
        self.assertEqual((game.level, game.xp, game.pending_rewards), (3, 30, 2))
        cards = game.open_rewards()
        self.assertEqual(len({card.key for card in cards}), 3)
        self.assertEqual(game.open_rewards(), cards)
        self.assertFalse(game.choose_reward(-1))
        self.assertFalse(game.choose_reward(3))
        self.assertEqual(game.pending_rewards, 2)
        self.assertTrue(game.choose_reward(0))
        self.assertEqual(game.pending_rewards, 1)
        self.assertFalse(game.choose_reward(0))
        self.assertEqual(len(game.open_rewards()), 3)

    def test_class_cards_unlock_at_level_three_and_only_once(self):
        seen_classes = set()
        for seed in range(30):
            game = empty_game(seed)
            game._add_score(60)
            self.assertTrue(all(c.category != "전직" for c in game.open_rewards()))
            game.reward_choices = ()
            game._add_score(100)
            seen_classes.update(c.key for c in game.open_rewards() if c.category == "전직")
            game.reward_choices = ()
            game.player.job = "scout"
            self.assertTrue(all(c.category != "전직" for c in game.open_rewards()))
        self.assertEqual(seen_classes, {"scout", "gunner", "guardian"})

    def test_every_card_changes_the_advertised_stat(self):
        for card in REWARD_CARDS:
            with self.subTest(card=card.key):
                game = empty_game()
                game.level, game.pending_rewards = 3, 1
                game.reward_choices = (card,)
                p = game.player
                p.hp = 20
                self.assertTrue(game.choose_reward(0))
                self.assertEqual(game.pending_rewards, 0)
                self.assertEqual(game.last_reward, card.title)
                if card.key == "damage":
                    game._fire(p, True)
                    self.assertEqual(game.bullets[0].damage, game.cfg.bullet_damage * 1.25)
                elif card.key == "rapid":
                    self.assertEqual(p.fire_cooldown_max, 17)
                elif card.key == "speed":
                    game._apply_tank_control(p, 3, 0, p.accel_scale, 1)
                    self.assertAlmostEqual(p.vx, game.cfg.accel * 1.15)
                elif card.key == "hull":
                    self.assertEqual((p.max_hp, p.hp), (125, 45))
                elif card.key == "heal":
                    self.assertEqual(p.hp, 80)
                elif card.key == "regen":
                    game._regen_player()
                    self.assertAlmostEqual(p.hp, 20 + game.cfg.regen_rate + 1.5 / game.cfg.fps)
                elif card.key == "range":
                    game._fire(p, True)
                    bullet = game.bullets[0]
                    self.assertAlmostEqual(math.hypot(bullet.vx, bullet.vy), game.cfg.bullet_speed * 1.2)
                    self.assertEqual(bullet.life, int(game.cfg.bullet_life * 1.15))
                elif card.key == "scout":
                    self.assertEqual(p.job, "scout")
                    self.assertEqual((p.accel_scale, p.bullet_speed_scale), (1.35, 1.2))
                elif card.key == "gunner":
                    game._fire(p, True)
                    self.assertEqual(p.job, "gunner")
                    self.assertEqual(len(game.bullets), 3)
                    self.assertTrue(all(b.damage == game.cfg.bullet_damage * 0.8 for b in game.bullets))
                elif card.key == "guardian":
                    self.assertEqual(p.job, "guardian")
                    self.assertEqual((p.max_hp, p.hp), (160, 160))
                    self.assertAlmostEqual(p.regen_bonus, 1.5 / game.cfg.fps)

    def test_health_and_fire_rate_limits(self):
        game = empty_game()
        for key in ("heal",) + ("rapid",) * 40:
            game.pending_rewards = 1
            game.reward_choices = (next(c for c in REWARD_CARDS if c.key == key),)
            game.choose_reward(0)
        self.assertEqual(game.player.hp, game.player.max_hp)
        self.assertEqual(game.player.fire_cooldown_max, 4)

    def test_seed_reset_and_reward_rng_do_not_change_combat_rng(self):
        a, b = empty_game(), empty_game()
        a._add_score(190)
        b._add_score(190)
        cards = a.open_rewards()
        self.assertEqual(cards, b.open_rewards())
        a.reward_choices = ()
        a.open_rewards()
        np.testing.assert_array_equal(a.rng.random(10), b.rng.random(10))
        a.choose_reward(0)
        a.reset(7)
        self.assertEqual((a.level, a.xp, a.pending_rewards, a.reward_choices), (1, 0, 0, ()))
        self.assertEqual(a.player.job, "rookie")
        self.assertEqual(a.player.damage_scale, 1)
        self.assertEqual(a.cfg.player_hp, 100)
        a.game_over = True
        a.pending_rewards = 1
        self.assertEqual(a.open_rewards(), ())
        self.assertFalse(a.choose_reward(0))


class WorldTests(unittest.TestCase):
    def test_all_expanded_maps_connected_in_both_terrain_modes(self):
        for name in list_maps():
            for stage2 in (False, True):
                cfg = GameConfig(num_shapes=0, num_enemies=0)
                cfg.terrain.map_name = name
                cfg.terrain.mud_enabled = cfg.terrain.breakable_enabled = stage2
                game = GameCore(cfg, seed=1)
                with self.subTest(map=name, stage2=stage2):
                    self.assertEqual((game.terrain.cols, game.terrain.rows), (60, 45))
                    self.assertTrue(game.terrain.is_connected())
                    self.assertFalse(game.terrain.is_solid_at(game.player.x, game.player.y))
        cfg.world_scale = 1
        self.assertEqual(GameCore(cfg).terrain.cols, 20)

    def test_world_boundary_and_bullets_beyond_the_viewport(self):
        game = empty_game()
        p = game.player
        p.x, p.y = 1800, 1400
        game.step(encode_action(3, 0))
        self.assertGreater(p.x, 1800)
        bullet = Bullet(1800, 1400, 9, 0, 70, p.id, "player", 7, 6)
        game.bullets = [bullet]
        game._move_bullets()
        self.assertEqual(game.bullets, [bullet])
        p.x, p.y = game.cfg.world_width + 10, game.cfg.world_height + 10
        game._clamp_to_arena(p)
        self.assertEqual(p.x, game.cfg.world_width - p.radius)
        self.assertEqual(p.y, game.cfg.world_height - p.radius)

    def test_rl_default_progression_and_world_normalization(self):
        env = TankEnv()
        self.assertFalse(env.game_cfg.progression_enabled)
        obs, _ = env.reset(seed=1)
        self.assertEqual(obs.shape, (363,))
        env.game._add_score(1000)
        self.assertEqual(env.game.level, 1)
        env.game.player.x = env.game_cfg.world_width / 2
        env.game.player.y = env.game_cfg.world_height / 2
        vector = build_vector(env.game, ObsConfig())
        self.assertAlmostEqual(vector[0], 0.5)
        self.assertAlmostEqual(vector[1], 0.5)
        _, _, _, _, info = env.step(0)
        self.assertEqual(info["pending_rewards"], 0)


class RendererTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()
        cls.game = empty_game()
        cls.renderer = Renderer(cls.game.cfg)

    @classmethod
    def tearDownClass(cls):
        pygame.quit()

    def test_camera_center_boundary_and_render_without_state_mutation(self):
        game, renderer = self.game, self.renderer
        p = game.player
        p.x, p.y = 1500, 1200
        renderer._update_camera(p)
        self.assertEqual(renderer.world_to_screen(p.x, p.y), (480, 360))
        state = (game.frame, p.x, p.y, p.hp, game.score)
        renderer.draw(game, show_ai=True)
        self.assertEqual((game.frame, p.x, p.y, p.hp, game.score), state)
        self.assertEqual(renderer.screen.get_size(), (960, 720))
        p.x, p.y = p.radius, p.radius
        renderer._update_camera(p)
        self.assertEqual((renderer.camera_x, renderer.camera_y), (0, 0))
        p.x = game.cfg.world_width - p.radius
        p.y = game.cfg.world_height - p.radius
        renderer._update_camera(p)
        self.assertEqual((renderer.camera_x, renderer.camera_y), (1920, 1440))
        game._add_score(190)
        game.open_rewards()
        renderer.draw(game, rewards_open=True)

    def test_main_reward_input_pauses_combat_and_keeps_cards(self):
        import main
        game = empty_game()
        game._add_score(190)
        clock = Mock()
        clock.tick.return_value = 17
        frames = []
        fake_renderer = SimpleNamespace(clock=clock, draw=Mock(
            side_effect=lambda g, *args, **kwargs: frames.append((g.frame, kwargs["rewards_open"]))))
        key = lambda k: [pygame.event.Event(pygame.KEYDOWN, key=k)]
        batches = [key(pygame.K_l), key(pygame.K_4), key(pygame.K_ESCAPE),
                   key(pygame.K_l), key(pygame.K_1), [pygame.event.Event(pygame.QUIT)]]
        with patch("sys.argv", ["main.py"]), patch("main.GameCore", return_value=game), \
                patch("renderer.Renderer", return_value=fake_renderer), \
                patch("pygame.event.get", side_effect=batches):
            main.main()
        self.assertEqual(frames[:2], [(0, True), (0, True)])
        self.assertEqual(frames[2][1], False)
        self.assertEqual(frames[3], (frames[2][0], True))
        self.assertEqual(frames[4][1], False)
        self.assertEqual(game.pending_rewards, 1)


if __name__ == "__main__":
    unittest.main()
