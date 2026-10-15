"""적 유형·시간 난이도·안전한 생성과 실제 추적 동작의 회귀 검증."""
import math
import unittest
from unittest.mock import Mock, patch

from config import GameConfig
from enemies import ENEMY_TYPES
from game_core import GameCore, Shape
from terrain import TileMap, EMPTY, WALL, list_maps


class EnemyManagementTests(unittest.TestCase):
    def game(self, **kwargs):
        cfg = GameConfig(num_shapes=0, progression_enabled=False, **kwargs)
        cfg.terrain.enabled = False
        return GameCore(cfg, seed=7)

    def assert_safe_spawn(self, game, enemy):
        self.assertTrue(enemy.alive)
        self.assertTrue(game.terrain.circle_fits(enemy.x, enemy.y, enemy.radius))
        distance = math.hypot(enemy.x - game.player.x, enemy.y - game.player.y)
        self.assertGreaterEqual(distance, 500)
        self.assertLess(distance, 1500)
        x, y, w, h = game.camera_rect()
        self.assertTrue(enemy.x + enemy.radius <= x or enemy.x - enemy.radius >= x + w
                        or enemy.y + enemy.radius <= y or enemy.y - enemy.radius >= y + h)
        for other in [game.player] + game.shapes + [e for e in game.enemies if e is not enemy and e.alive]:
            self.assertGreaterEqual(math.hypot(enemy.x - other.x, enemy.y - other.y), enemy.radius + other.radius)

    def test_default_ships_are_30_percent_smaller_including_evolution(self):
        game = self.game(num_enemies=1)
        self.assertAlmostEqual(game.player.radius, 44 * 0.7)
        self.assertAlmostEqual(game.enemies[0].radius, 44 * 0.7)
        game.cfg.progression_enabled = True
        game._add_score(1980)
        self.assertTrue(game.choose_reward(3))
        self.assertAlmostEqual(game.player.radius, 64 * 0.7)

    def test_initial_enemies_are_basic_and_spawn_safely_on_every_map(self):
        for name in list_maps():
            with self.subTest(map=name):
                cfg = GameConfig()
                cfg.terrain.map_name = name
                game = GameCore(cfg, seed=7)
                self.assertEqual(len(game.enemies), 9)
                for enemy in game.enemies:
                    self.assertEqual(enemy.enemy_kind, "basic")
                    self.assert_safe_spawn(game, enemy)

    def test_difficulty_boundaries_caps_and_existing_enemy_stats(self):
        game = self.game()
        enemy = game.enemies[0]
        before = enemy.max_hp, enemy.damage_scale, enemy.fire_cooldown_max
        game.frame = 120 * 60 - 1
        self.assertEqual((game.difficulty_stage, game.enemy_limit), (0, 9))
        for minutes, stage, count, hp, damage in ((2, 1, 10, 1.05, 1.03), (4, 2, 11, 1.1, 1.06),
                                                 (6, 3, 12, 1.15, 1.09), (20, 10, 18, 1.5, 1.3),
                                                 (100, 50, 18, 1.5, 1.3)):
            game.frame = minutes * 60 * game.cfg.fps
            self.assertEqual((game.difficulty_stage, game.enemy_limit), (stage, count))
            self.assertAlmostEqual(game.enemy_time_scales[0], hp)
            self.assertAlmostEqual(game.enemy_time_scales[1], damage)
            game._update_enemy_population()
            self.assertEqual(len(game.enemies), count)
        self.assertEqual((enemy.max_hp, enemy.damage_scale, enemy.fire_cooldown_max), before)

    def test_unlocks_and_type_stats_apply_on_spawn_and_rewards_stay_fixed(self):
        game = self.game(num_enemies=1)
        enemy = game.enemies[0]
        game.rng = Mock(wraps=game.rng)
        for stage, key in enumerate(ENEMY_TYPES):
            game.frame = stage * 120 * game.cfg.fps
            game.rng.choice.return_value = stage
            with patch.object(game, "_enemy_spawn_position", return_value=(800, 800)):
                self.assertTrue(game._respawn_enemy(enemy))
            role = ENEMY_TYPES[key]
            self.assertEqual(enemy.enemy_kind, key)
            self.assertAlmostEqual(enemy.max_hp, role.hp * (1 + 0.05 * stage))
            self.assertAlmostEqual(game.weapon_values(enemy)[1], role.damage * (1 + 0.03 * stage))
            self.assertAlmostEqual(enemy.accel_scale, role.move_speed)
            self.assertEqual(enemy.fire_cooldown_max, role.cooldown)
            self.assertEqual(enemy.kill_score, role.score)
            self.assertEqual(len(game.rng.choice.call_args.kwargs['p']), stage + 1)
            before = game.score
            game._damage_tank(enemy, enemy.hp, True)
            self.assertEqual(game.score - before, role.score)

    def test_no_safe_offscreen_position_defers_spawn_then_retries(self):
        game = self.game(num_enemies=1)
        game.viewport_size = (game.cfg.world_width, game.cfg.world_height)
        enemy = game.enemies[0]
        self.assertFalse(game._respawn_enemy(enemy))
        self.assertFalse(enemy.alive)
        self.assertEqual(enemy.respawn_timer, game.cfg.enemy_spawn_retry_frames)
        game.step(0, want_fire=False)
        self.assertFalse(enemy.alive)
        game.viewport_size = (960, 640)
        for _ in range(game.cfg.enemy_spawn_retry_frames - 1):
            game.step(0, want_fire=False)
        self.assert_safe_spawn(game, enemy)

    def test_death_waits_five_seconds_and_far_relocation_grants_no_score(self):
        game = self.game(num_enemies=1)
        enemy = game.enemies[0]
        game._damage_tank(enemy, enemy.hp, True)
        self.assertEqual(enemy.respawn_timer, 300)
        for _ in range(299):
            game.step(0, want_fire=False)
        self.assertFalse(enemy.alive)
        game.step(0, want_fire=False)
        self.assert_safe_spawn(game, enemy)
        enemy.x, enemy.y = game.player.x + 1600, game.player.y
        before = game.score, game.kills
        game.step(0, want_fire=False)
        self.assertEqual((game.score, game.kills), before)
        self.assert_safe_spawn(game, enemy)

    def test_visible_player_always_wins_and_memory_expires_after_two_seconds(self):
        game = self.game(num_enemies=1)
        enemy = game.enemies[0]
        enemy.x, enemy.y = 700, 700
        game.player.x, game.player.y = 1000, 700
        game.shapes = [Shape(999, "square", 800, 700, 0, 0, 10, 10, 14, 10)]
        game._enemy_ai(enemy)
        self.assertEqual(enemy.ai_target, ("player", game.player.id))
        self.assertEqual(enemy.ai_last_seen, (1000, 700))
        game.player.x = 2000
        game.frame = 119
        game._enemy_ai(enemy)
        self.assertEqual(enemy.ai_target, ("point", (1000, 700)))
        game.frame = 120
        game._enemy_ai(enemy)
        self.assertEqual(enemy.ai_target, ("shape", 999))
        self.assertIsNone(enemy.ai_last_seen)

    def test_assault_approaches_and_sniper_retreats_at_same_distance(self):
        for key, expected_sign in (("assault", 1), ("sniper", -1)):
            game = self.game(num_enemies=1)
            enemy = game.enemies[0]
            enemy.enemy_kind = key
            enemy.accel_scale = ENEMY_TYPES[key].move_speed
            enemy.x, enemy.y, enemy.vx, enemy.vy = 700, 700, 0, 0
            game.player.x, game.player.y = 900, 700
            game._enemy_ai(enemy)
            self.assertGreater(enemy.vx * expected_sign, 0)

    def test_wall_edge_position_connects_to_safe_astar_start_and_moves(self):
        game = self.game(num_enemies=1)
        tiles = [[EMPTY] * 60 for _ in range(45)]
        for row in range(13):
            tiles[row][10] = WALL
        tm = game.terrain = TileMap(tiles, 48, (2, 2), [], "wall-edge", game.cfg.terrain)
        enemy = game.enemies[0]
        enemy.x, enemy.y, enemy.vx, enemy.vy = 480 - enemy.radius, 400, 0, 0
        game.player.x, game.player.y = 600, 400
        enemy.ai_target = ("player", game.player.id)
        enemy.ai_last_seen, enemy.ai_last_seen_frame = (600, 400), 0
        self.assertTrue(tm.circle_fits(enemy.x, enemy.y, enemy.radius))
        self.assertFalse(tm.circle_fits(*tm.center(*tm.tile_of(enemy.x, enemy.y)), enemy.radius))
        origin = enemy.x, enemy.y
        self.assertTrue(game._enemy_path(enemy, 600, 400))
        for _ in range(60):
            game._enemy_ai(enemy)
            game.frame += 1
            self.assertTrue(tm.circle_fits(enemy.x, enemy.y, enemy.radius))
        self.assertGreater(math.hypot(enemy.x - origin[0], enemy.y - origin[1]), 30)

    def test_stuck_path_retries_and_changes_fallback_target(self):
        game = self.game(num_enemies=1)
        enemy = game.enemies[0]
        enemy.x, enemy.y = 700, 700
        game.player.x, game.player.y = 2000, 700
        game.shapes = [Shape(999, "square", 950, 700, 0, 0, 10, 10, 14, 10)]
        with patch.object(game, "_apply_tank_control"):
            for _ in range(30):
                game._enemy_ai(enemy)
                game.frame += 1
        self.assertEqual(enemy.ai_avoid_shape, 999)
        self.assertIsNone(enemy.ai_target)
        self.assertIsNotNone(enemy.ai_recovery)
        self.assertEqual(enemy.ai_path_timer, 0)

    def test_enemy_cannot_fire_beyond_weapon_range_or_through_wall(self):
        game = self.game(num_enemies=1)
        enemy = game.enemies[0]
        enemy.x, enemy.y, enemy.cooldown = 700, 700, 0
        game.player.x, game.player.y = 1100, 700
        enemy.bullet_life_scale = 0.1
        game.cfg.enemy_ai.aim_noise_deg = 0
        game._enemy_ai(enemy)
        self.assertTrue(enemy.ai_can_see)
        self.assertEqual(game.bullets, [])
        tiles = [[EMPTY] * 60 for _ in range(45)]
        for row in range(45):
            tiles[row][18] = WALL
        game.terrain = TileMap(tiles, 48, (2, 2), [], "wall", game.cfg.terrain)
        enemy.bullet_life_scale = 1
        game._enemy_ai(enemy)
        self.assertFalse(enemy.ai_can_see)
        self.assertEqual(game.bullets, [])


if __name__ == "__main__":
    unittest.main()
