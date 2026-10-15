"""월드/레벨업/카메라 회귀 검증. GUI 없이 실행 가능.

    python -m unittest discover -s tests -v
"""
import math
import os
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import numpy as np
import pygame

from config import GameConfig, ObsConfig
from env import TankEnv, build_vector
from game_core import Bullet, GameCore, encode_action
from progression import STAT_MAX_LEVEL, STAT_UPGRADES, SPECIAL_REWARDS, special_cards, stat_rows
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
        self.assertEqual(game.open_rewards(), ())
        game._add_score(1790)
        self.assertEqual((game.level, game.upgrade_points, game.special_reward_levels), (10, 8, [10]))
        cards = game.open_rewards()
        self.assertEqual(len({card.key for card in cards}), 4)
        self.assertEqual(game.open_rewards(), cards)
        self.assertFalse(game.choose_reward(-1))
        self.assertFalse(game.choose_reward(4))
        self.assertEqual(game.pending_rewards, 9)
        self.assertTrue(game.choose_reward(0))
        self.assertEqual(game.pending_rewards, 8)
        self.assertFalse(game.choose_reward(0))
        self.assertEqual(game.open_rewards(), ())

    def test_every_tenth_level_queues_special_rewards_without_losing_stat_points(self):
        game = empty_game()
        game._add_score(7980)
        self.assertEqual((game.level, game.xp, game.upgrade_points, game.special_reward_levels), (20, 0, 17, [10, 20]))
        first = game.reward_choices
        self.assertTrue(game.upgrade_stat("hull"))
        self.assertEqual(game.reward_choices, first)
        self.assertTrue(game.choose_reward(0))
        self.assertEqual(game.special_reward_levels, [20])
        self.assertEqual(len(game.reward_choices), 2)
        self.assertEqual(game.upgrade_points, 16)
        self.assertTrue(game.choose_reward(0))
        self.assertEqual(game.special_reward_levels, [])

    def test_every_card_changes_the_advertised_stat(self):
        for card in STAT_UPGRADES:
            with self.subTest(card=card.key):
                game = empty_game()
                game.level, game.upgrade_points = 3, 1
                p = game.player
                p.hp = 20
                p.ammo = 20
                self.assertTrue(game.upgrade_stat(card.key))
                self.assertEqual(game.pending_rewards, 0)
                self.assertEqual(game.last_reward, card.title)
                if card.key == "damage":
                    game._fire(p, True)
                    self.assertEqual(game.bullets[0].damage, game.cfg.bullet_damage * 1.25)
                elif card.key == "rapid":
                    self.assertEqual(p.fire_cooldown_max, 27)
                elif card.key == "speed":
                    game._apply_tank_control(p, 3, 0, p.accel_scale, 1)
                    self.assertAlmostEqual(p.vx, game.cfg.accel * 1.07)
                elif card.key == "hull":
                    self.assertEqual((p.max_hp, p.hp), (125, 45))
                elif card.key == "range":
                    game._fire(p, True)
                    bullet = game.bullets[0]
                    self.assertAlmostEqual(math.hypot(bullet.vx, bullet.vy), game.cfg.bullet_speed * 1.2)
                    self.assertEqual(bullet.life, int(game.cfg.bullet_life * 1.15))

    def test_health_and_fire_rate_limits(self):
        game = empty_game()
        game.upgrade_points = 100
        for _ in range(40):
            game.upgrade_stat("rapid")
        self.assertEqual(game.player.hp, game.player.max_hp)
        # 능력치마다 최대 7단계: 28 → 27 → 26 → 25 → 24 → 23 → 22 → 21
        self.assertEqual(game.stat_levels["rapid"], STAT_MAX_LEVEL)
        self.assertEqual(game.player.fire_cooldown_max, 21)
        self.assertEqual(game.reload_frames_total, 150)
        points = game.upgrade_points
        self.assertFalse(game.upgrade_stat("rapid"))
        self.assertFalse(game.upgrade_stat("reload"))
        self.assertFalse(game.upgrade_stat("bogus"))
        self.assertEqual(game.upgrade_points, points)

    def test_five_stats_and_unspent_points_survive_later_levels_and_evolution(self):
        game = empty_game()
        keys = ("hull", "damage", "range", "rapid", "speed")
        self.assertEqual(tuple(card.key for card in game.open_stat_upgrades()), keys)
        self.assertEqual(game.upgrade_points, 0)
        game._add_score(1980)
        self.assertEqual(game.upgrade_points, 8)
        game.choose_reward(0)
        game._add_score(7980 - game.score)
        self.assertEqual(game.upgrade_points, 17)
        self.assertEqual(tuple(card.key for card in game.open_stat_upgrades()), keys)
        game.choose_reward(1)
        self.assertEqual(game.upgrade_points, 17)
        self.assertTrue(game.upgrade_stat("speed"))
        self.assertEqual(game.upgrade_points, 16)
        self.assertEqual(tuple(card.key for card in game.open_stat_upgrades()), keys)
        for removed in ("regen", "magazine", "reload"):
            self.assertFalse(game.upgrade_stat(removed))
        game.reset(7)
        self.assertEqual(game.upgrade_points, 0)
        self.assertTrue(all(count == 0 for count in game.stat_levels.values()))

    def test_seed_reset_and_reward_rng_do_not_change_combat_rng(self):
        a, b = empty_game(), empty_game()
        a._add_score(1980)
        b._add_score(1980)
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
        a.special_reward_levels = [10]
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
        self.assertEqual(obs.shape, (241,))
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
        cls.game.cfg.window_width, cls.game.cfg.window_height = 960, 720
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
        self.assertEqual((renderer.camera_x, renderer.camera_y), (1280, 960))
        game._add_score(190)
        game.open_rewards()
        renderer.draw(game)

    def test_rewards_are_selected_in_hud_without_pausing_combat(self):
        from main import GameApplication
        from collections import defaultdict
        game = empty_game()
        app = GameApplication(game, self.renderer, seed=7)
        app.activate("start")
        game._add_score(1980)
        key = lambda k: app.handle_event(pygame.event.Event(pygame.KEYDOWN, key=k))
        cards = game.reward_choices
        choice = game.stat_choices[0].key
        key(pygame.K_1)
        self.assertEqual(game.stat_levels[choice], 1)
        app.update(0.1, defaultdict(bool), (480, 360), (False, False, False))
        self.assertGreater(game.frame, 0)
        key(pygame.K_ESCAPE)
        self.assertEqual(app.mode, "pause")
        key(pygame.K_ESCAPE)
        self.assertEqual(game.reward_choices, cards)
        key(pygame.K_F2)
        self.assertEqual(game.special_reward_levels, [])
        self.assertEqual(game.upgrade_points, 7)

    def test_hud_rows_and_cards_fit_without_overlapping_health_panel(self):
        game = self.game
        game.reset(7)
        game._add_score(1980)
        screen = pygame.Rect(0, 0, 960, 720)
        hp_panel = pygame.Rect(314, 620, 332, 84)
        for _, rect in stat_rows(960, 720):
            self.assertTrue(screen.contains(pygame.Rect(rect)))
            self.assertFalse(hp_panel.colliderect(pygame.Rect(rect)))
        for rect in special_cards(960, 720):
            self.assertTrue(screen.contains(pygame.Rect(rect)))
        self.renderer.draw(game)

    def test_wounded_enemies_render_without_removed_stealth_api(self):
        cfg = GameConfig(num_enemies=1, num_shapes=0)
        cfg.terrain.enabled = False
        game = GameCore(cfg, seed=7)
        enemy = game.enemies[0]
        enemy.hp -= 1
        enemy.x, enemy.y = game.player.x + 80, game.player.y
        health = enemy.hp
        self.renderer.draw(game)
        self.assertEqual(enemy.hp, health)
        self.assertTrue(enemy.alive)

    def test_zoom_setting_rebuilds_view_and_keeps_hud_resolution(self):
        renderer = self.renderer
        try:
            renderer.set_zoom(0.75)
            renderer._update_camera(self.game.player)
            self.assertEqual(renderer._view.get_size(), (1280, 960))
            self.assertAlmostEqual(renderer.effective_zoom, 0.75)
            self.assertEqual(renderer.screen.get_size(), (960, 720))
            pos = renderer.screen_to_world(480, 360)
            self.assertEqual(renderer.world_to_screen(*pos), (480, 360))
            renderer.draw(self.game, show_controls=False)
        finally:
            renderer.set_zoom(0.6)


if __name__ == "__main__":
    unittest.main()
