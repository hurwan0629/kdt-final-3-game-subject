"""월드/레벨업/카메라 회귀 검증. GUI 없이 실행 가능.

    python -m unittest discover -s tests -v
"""
import math
import os
import unittest
from unittest.mock import patch

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
        game.combat._damage_shape(shape, shape.hp, by_player=True)
        game.combat._damage_tank(game.enemies[0], 1000, by_player=True)
        self.assertEqual(game.progression.score, score + game.cfg.enemy_kill_score)
        expected_xp, expected_level = game.progression.score, 1
        while expected_xp >= 60 + (expected_level - 1) * 40:
            expected_xp -= 60 + (expected_level - 1) * 40
            expected_level += 1
        self.assertEqual((game.progression.level, game.progression.xp, game.progression.pending_rewards),
                         (expected_level, expected_xp, expected_level - 1))

    def test_cards_are_unique_persistent_and_consumed_once(self):
        game = empty_game()
        self.assertEqual(game.progression.open_rewards(), ())
        game.progression._add_score(190)
        self.assertEqual((game.progression.level, game.progression.xp, game.progression.pending_rewards), (3, 30, 2))
        self.assertEqual(game.progression.open_rewards(), ())
        game.progression._add_score(1790)
        self.assertEqual((game.progression.level, game.progression.upgrade_points, game.progression.special_reward_levels), (10, 8, [10]))
        cards = game.progression.open_rewards()
        self.assertEqual(len({card.key for card in cards}), 4)
        self.assertEqual(game.progression.open_rewards(), cards)
        self.assertFalse(game.progression.choose_reward(-1))
        self.assertFalse(game.progression.choose_reward(4))
        self.assertEqual(game.progression.pending_rewards, 9)
        self.assertTrue(game.progression.choose_reward(0))
        self.assertEqual(game.progression.pending_rewards, 8)
        self.assertFalse(game.progression.choose_reward(0))
        self.assertEqual(game.progression.open_rewards(), ())

    def test_every_tenth_level_queues_special_rewards_without_losing_stat_points(self):
        game = empty_game()
        game.progression._add_score(7980)
        self.assertEqual((game.progression.level, game.progression.xp, game.progression.upgrade_points, game.progression.special_reward_levels), (20, 0, 17, [10, 20]))
        first = game.progression.reward_choices
        self.assertTrue(game.progression.upgrade_stat("hull"))
        self.assertEqual(game.progression.reward_choices, first)
        self.assertTrue(game.progression.choose_reward(0))
        self.assertEqual(game.progression.special_reward_levels, [20])
        self.assertEqual(len(game.progression.reward_choices), 2)
        self.assertEqual(game.progression.upgrade_points, 16)
        self.assertTrue(game.progression.choose_reward(0))
        self.assertEqual(game.progression.special_reward_levels, [])

    def test_regen_rate_scales_with_max_hp_from_hull_upgrades(self):
        game = empty_game()
        c, p = game.cfg, game.player
        game.progression.level, game.progression.upgrade_points = 2, 2
        p.hp = 1.0
        p.last_hit_frame = -10 ** 9   # 회복 대기 시간 지남
        game.combat._regen_player()
        base_regen = p.hp - 1.0
        self.assertAlmostEqual(base_regen, c.regen_rate)
        self.assertTrue(game.progression.upgrade_stat("hull"))
        self.assertTrue(game.progression.upgrade_stat("hull"))
        self.assertEqual(p.max_hp, c.player_hp + 50)
        p.hp = 1.0
        game.combat._regen_player()
        boosted_regen = p.hp - 1.0
        # 최대 체력이 늘어난 비율만큼 회복량도 같이 커진다 (최대 체력 대비 %는 그대로 유지).
        self.assertAlmostEqual(boosted_regen, base_regen * (p.max_hp / c.player_hp))
        self.assertGreater(boosted_regen, base_regen)

    def test_every_card_changes_the_advertised_stat(self):
        for card in STAT_UPGRADES:
            with self.subTest(card=card.key):
                game = empty_game()
                game.progression.level, game.progression.upgrade_points = 3, 1
                p = game.player
                p.hp = 20
                p.ammo = 20
                self.assertTrue(game.progression.upgrade_stat(card.key))
                self.assertEqual(game.progression.pending_rewards, 0)
                self.assertEqual(game.progression.last_reward, card.title)
                if card.key == "damage":
                    game.combat._fire(p, True)
                    self.assertEqual(game.combat.bullets[0].damage, game.cfg.bullet_damage * 1.25)
                elif card.key == "rapid":
                    self.assertEqual(p.fire_cooldown_max, 27)
                elif card.key == "speed":
                    game._apply_tank_control(p, 3, 0, p.accel_scale, 1)
                    self.assertAlmostEqual(p.vx, game.cfg.accel * 1.07)
                elif card.key == "hull":
                    self.assertEqual((p.max_hp, p.hp), (125, 45))
                elif card.key == "range":
                    game.combat._fire(p, True)
                    bullet = game.combat.bullets[0]
                    self.assertAlmostEqual(math.hypot(bullet.vx, bullet.vy), game.cfg.bullet_speed * 1.2)
                    self.assertEqual(bullet.life, int(game.cfg.bullet_life * 1.15))

    def test_health_and_fire_rate_limits(self):
        game = empty_game()
        game.progression.upgrade_points = 100
        for _ in range(40):
            game.progression.upgrade_stat("rapid")
        self.assertEqual(game.player.hp, game.player.max_hp)
        # 능력치마다 최대 7단계: 28 → 27 → 26 → 25 → 24 → 23 → 22 → 21
        self.assertEqual(game.progression.stat_levels["rapid"], STAT_MAX_LEVEL)
        self.assertEqual(game.player.fire_cooldown_max, 21)
        self.assertEqual(game.combat.reload_frames_total, 150)
        points = game.progression.upgrade_points
        self.assertFalse(game.progression.upgrade_stat("rapid"))
        self.assertFalse(game.progression.upgrade_stat("reload"))
        self.assertFalse(game.progression.upgrade_stat("bogus"))
        self.assertEqual(game.progression.upgrade_points, points)

    def test_five_stats_and_unspent_points_survive_later_levels_and_evolution(self):
        game = empty_game()
        keys = ("hull", "damage", "range", "rapid", "speed")
        self.assertEqual(tuple(card.key for card in game.progression.open_stat_upgrades()), keys)
        self.assertEqual(game.progression.upgrade_points, 0)
        game.progression._add_score(1980)
        self.assertEqual(game.progression.upgrade_points, 8)
        game.progression.choose_reward(0)
        game.progression._add_score(7980 - game.progression.score)
        self.assertEqual(game.progression.upgrade_points, 17)
        self.assertEqual(tuple(card.key for card in game.progression.open_stat_upgrades()), keys)
        game.progression.choose_reward(1)
        self.assertEqual(game.progression.upgrade_points, 17)
        self.assertTrue(game.progression.upgrade_stat("speed"))
        self.assertEqual(game.progression.upgrade_points, 16)
        self.assertEqual(tuple(card.key for card in game.progression.open_stat_upgrades()), keys)
        for removed in ("regen", "magazine", "reload"):
            self.assertFalse(game.progression.upgrade_stat(removed))
        game.reset(7)
        self.assertEqual(game.progression.upgrade_points, 0)
        self.assertTrue(all(count == 0 for count in game.progression.stat_levels.values()))

    def test_seed_reset_and_reward_rng_do_not_change_combat_rng(self):
        a, b = empty_game(), empty_game()
        a.progression._add_score(1980)
        b.progression._add_score(1980)
        cards = a.progression.open_rewards()
        self.assertEqual(cards, b.progression.open_rewards())
        a.progression.reward_choices = ()
        a.progression.open_rewards()
        np.testing.assert_array_equal(a.rng.random(10), b.rng.random(10))
        a.progression.choose_reward(0)
        a.reset(7)
        self.assertEqual((a.progression.level, a.progression.xp, a.progression.pending_rewards, a.progression.reward_choices), (1, 0, 0, ()))
        self.assertEqual(a.player.job, "rookie")
        self.assertEqual(a.player.damage_scale, 1)
        self.assertEqual(a.cfg.player_hp, 100)
        a.game_over = True
        a.progression.special_reward_levels = [10]
        self.assertEqual(a.progression.open_rewards(), ())
        self.assertFalse(a.progression.choose_reward(0))


class OwnershipTests(unittest.TestCase):
    def test_reset_keeps_controllers_and_clears_previous_round(self):
        game = empty_game()
        owners = (game.progression, game.combat, game.enemy_controller)
        old_player, old_terrain = game.player, game.terrain
        game.progression._add_score(1980)
        game.progression.record_kill()
        game.combat._fire(game.player, True)
        game.combat.reload_frames_left = 20
        game.enemy_controller.enemy_scale_tier = 5
        self.assertTrue(game.combat.bullets)
        self.assertTrue(game.progression.reward_choices)

        game.reset(7)

        self.assertEqual(owners, (game.progression, game.combat, game.enemy_controller))
        self.assertTrue(all(owner.game is game for owner in owners))
        self.assertIsNot(game.player, old_player)
        self.assertIsNot(game.terrain, old_terrain)
        self.assertEqual((game.progression.score, game.progression.kills, game.progression.level,
                          game.progression.xp, game.progression.upgrade_points), (0, 0, 1, 0, 0))
        self.assertEqual(game.progression.reward_choices, ())
        self.assertEqual(game.combat.bullets, [])
        self.assertEqual(game.combat.reload_frames_left, 0)
        self.assertEqual(game.enemy_controller.enemy_scale_tier, 0)

        game.player.x, game.player.y, game.player.angle = 500, 500, 0
        game.combat._fire(game.player, True)
        self.assertEqual(game.combat.bullets[0].owner_id, game.player.id)
        self.assertGreater(game.combat.bullets[0].x, game.player.x)
        self.assertEqual(game.combat.bullets[0].y, game.player.y)
        game.progression.upgrade_points = 1
        self.assertTrue(game.progression.upgrade_stat("hull"))
        self.assertEqual(game.player.max_hp, game.cfg.player_hp + 25)
        self.assertEqual(old_player.max_hp, game.cfg.player_hp)

    def test_damage_records_kill_through_progression_once(self):
        cfg = GameConfig(num_enemies=1, num_shapes=0)
        cfg.terrain.enabled = False
        game = GameCore(cfg, seed=7)
        enemy = game.enemies[0]
        enemy.elite = False
        with patch.object(game.progression, "record_kill", wraps=game.progression.record_kill) as record:
            game.combat._damage_tank(enemy, 100000, True)
            game.combat._damage_tank(enemy, 100000, True)
        record.assert_called_once_with()
        self.assertEqual(game.progression.kills, 1)
        self.assertEqual(game.progression.score, cfg.enemy_kill_score)

    def test_reload_finishes_after_frame_increment_before_death_check(self):
        game = empty_game()
        game.player.ammo = 0
        game.combat.reload_frames_left = 1
        frames = []
        original_finish = game.combat._finish_frame

        def finish_frame():
            frames.append(game.frame)
            original_finish()

        with patch.object(game.combat, "_finish_frame", side_effect=finish_frame) as finish:
            game.step(0, want_fire=False)
        finish.assert_called_once_with()
        self.assertEqual(frames, [1])
        self.assertEqual((game.frame, game.player.ammo), (1, game.player.max_ammo))
        game.player.hp = 0
        game.player.ammo = 0
        game.combat.reload_frames_left = 1
        game.step(0, want_fire=False)
        self.assertEqual(game.player.ammo, 0)
        self.assertTrue(game.game_over)

    def test_controller_resets_do_not_consume_combat_rng(self):
        game = empty_game()
        before = game.rng.bit_generator.state
        game.progression.reset(123)
        game.combat.reset()
        game.enemy_controller.reset()
        self.assertEqual(game.rng.bit_generator.state, before)


class WorldTests(unittest.TestCase):
    def test_all_expanded_maps_connected_in_both_terrain_modes(self):
        for name in list_maps():
            for stage2 in (False, True):
                cfg = GameConfig(num_shapes=0, num_enemies=0)
                cfg.terrain.map_name = name
                cfg.terrain.mud_enabled = cfg.terrain.breakable_enabled = stage2
                game = GameCore(cfg, seed=1)
                with self.subTest(map=name, stage2=stage2):
                    self.assertEqual((game.terrain.cols, game.terrain.rows), (134, 101))
                    self.assertTrue(game.terrain.is_connected())
                    self.assertFalse(game.terrain.is_solid_at(game.player.x, game.player.y))
        cfg.world_scale = 1
        self.assertEqual(GameCore(cfg).terrain.cols, 27)

    def test_world_boundary_and_bullets_beyond_the_viewport(self):
        game = empty_game()
        p = game.player
        p.x, p.y = 1800, 1400
        game.step(encode_action(3, 0))
        self.assertGreater(p.x, 1800)
        bullet = Bullet(1800, 1400, 9, 0, 70, p.id, "player", 7, 6)
        game.combat.bullets = [bullet]
        game.combat._move_bullets()
        self.assertEqual(game.combat.bullets, [bullet])
        p.x, p.y = game.cfg.world_width + 10, game.cfg.world_height + 10
        game._clamp_to_arena(p)
        self.assertEqual(p.x, game.cfg.world_width - p.radius)
        self.assertEqual(p.y, game.cfg.world_height - p.radius)

    def test_rl_default_progression_and_world_normalization(self):
        env = TankEnv()
        self.assertFalse(env.game_cfg.progression_enabled)
        obs, _ = env.reset(seed=1)
        self.assertEqual(obs.shape, (241,))
        env.game.progression._add_score(1000)
        self.assertEqual(env.game.progression.level, 1)
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
        state = (game.frame, p.x, p.y, p.hp, game.progression.score)
        renderer.draw(game, show_ai=True)
        self.assertEqual((game.frame, p.x, p.y, p.hp, game.progression.score), state)
        self.assertEqual(renderer.screen.get_size(), (960, 720))
        p.x, p.y = p.radius, p.radius
        renderer._update_camera(p)
        self.assertEqual(renderer.world_to_screen(p.x, p.y),
                         (renderer.size[0] / 2, renderer.size[1] / 2))
        self.assertLess(renderer.camera_x, 0)
        self.assertLess(renderer.camera_y, 0)
        p.x = game.cfg.world_width - p.radius
        p.y = game.cfg.world_height - p.radius
        renderer._update_camera(p)
        self.assertEqual(renderer.world_to_screen(p.x, p.y),
                         (renderer.size[0] / 2, renderer.size[1] / 2))
        self.assertGreater(renderer.camera_x + renderer.view_width, game.cfg.world_width)
        self.assertGreater(renderer.camera_y + renderer.view_height, game.cfg.world_height)
        game.progression._add_score(190)
        game.progression.open_rewards()
        renderer.draw(game)

    def test_rewards_are_selected_in_hud_without_pausing_combat(self):
        from main import GameApplication
        from collections import defaultdict
        game = empty_game()
        app = GameApplication(game, self.renderer, seed=7)
        app.activate("start")
        game.progression._add_score(1980)
        key = lambda k: app.handle_event(pygame.event.Event(pygame.KEYDOWN, key=k))
        cards = game.progression.reward_choices
        choice = game.progression.stat_choices[0].key
        key(pygame.K_1)
        self.assertEqual(game.progression.stat_levels[choice], 1)
        app.update(0.1, defaultdict(bool), (480, 360), (False, False, False))
        self.assertGreater(game.frame, 0)
        key(pygame.K_ESCAPE)
        self.assertEqual(app.mode, "pause")
        key(pygame.K_ESCAPE)
        self.assertEqual(game.progression.reward_choices, cards)
        key(pygame.K_F2)
        self.assertEqual(game.progression.special_reward_levels, [])
        self.assertEqual(game.progression.upgrade_points, 7)

    def test_hud_rows_and_cards_fit_without_overlapping_health_panel(self):
        game = self.game
        game.reset(7)
        game.progression._add_score(1980)
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
