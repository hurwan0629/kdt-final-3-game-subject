"""적 성장(시간·진화 단계), 스탯 최대치, 전직별 탄 크기, 스탯 창 접힘 검증."""

import math
import os
import unittest
from collections import defaultdict

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import pygame

from space_z.config import GameConfig, ObsConfig, SHAPE_TYPES
from space_z.game.game_core import GameCore
from space_z.app import GameApplication
from space_z.config.progression_definitions import (
    SHIPS,
    SHIPS_BY_LEVEL,
    STAT_MAX_LEVEL,
    STAT_UPGRADES,
)
from space_z.rendering.progression_panel import get_collapsed_stat_panel_rect
from space_z.rendering.renderer import Renderer


def open_game(enemies=0, seed=7, mercy_seconds=None):
    config = GameConfig(num_enemies=enemies, num_shapes=0)
    config.terrain.enabled = False
    if mercy_seconds is not None:
        config.enemy_ai.mercy_seconds = mercy_seconds
    return GameCore(config, seed=seed)


def evolve(game, job):
    chain = []
    while job != "rookie":
        chain.append(job)
        job = SHIPS[job].parent or "rookie"
    for key in reversed(chain):
        level = SHIPS[key].level
        if level <= SHIPS[game.player.job].level:  # 이미 지난 단계
            continue
        score = sum(
            game.config.level_xp_base + (level_count - 1) * game.config.level_xp_growth
            for level_count in range(1, level)
        )
        game.progression._add_score(score - game.progression.score)
        game.progression.choose_reward(
            next(
                choice_index
                for choice_index, card in enumerate(game.progression.reward_choices)
                if card.key == key
            )
        )


class EnemyGrowthTests(unittest.TestCase):
    def test_enemies_get_stronger_over_time(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        game = open_game(
            enemies=3, mercy_seconds=0
        )  # 초반 봐주기 배율과 분리해서 시간 성장만 검증
        enemy_ai_config = game.config.enemy_ai
        enemy = game.enemies[0]
        base = (enemy.max_hp, enemy.damage_scale, enemy.fire_cooldown_max)
        enemy.hp = enemy.max_hp / 2
        game.frame = int(enemy_ai_config.scale_interval_seconds * game.config.fps * 4)
        game.enemy_controller._update_enemy_scaling()

        # 시간 성장에 따른 체력·공격력·발사 간격과 성장 상한을 확인한다.
        self.assertEqual(game.enemy_controller.enemy_scale_tier, 4)
        self.assertAlmostEqual(
            enemy.max_hp, base[0] * (1 + 4 * enemy_ai_config.hp_growth)
        )
        self.assertAlmostEqual(enemy.hp, enemy.max_hp / 2)
        self.assertGreater(enemy.damage_scale, base[1])
        self.assertLess(enemy.fire_cooldown_max, base[2])
        game.frame = 10**7
        game.enemy_controller._update_enemy_scaling()
        self.assertEqual(
            game.enemy_controller.enemy_scale_tier, enemy_ai_config.max_scale_tier
        )
        self.assertGreaterEqual(
            min(x.fire_cooldown_max for x in game.enemies),
            enemy_ai_config.min_fire_cooldown,
        )

    def test_enemies_get_a_random_build_from_a_budget_tied_to_player_picks(self):
        """적의 스탯 '총량'은 플레이어 픽 수 × stat_mirror_ratio로 정해지지만,
        그 포인트를 어느 항목에 쓸지는 개체마다 무작위라 build가 서로 다르다."""

        # 검사에 사용할 설정·개체·입력을 준비한다.
        game = open_game(enemies=8, seed=5, mercy_seconds=0)
        enemy_ai_config = game.config.enemy_ai
        game.progression._add_score(10**6)

        # 적별 강화 총량은 같고 스탯 배분은 서로 달라지는지 확인한다.
        for key, times in (
            ("damage", 3),
            ("health", 2),
            ("speed", 1),
            ("rapid", 1),
            ("range", 1),
        ):
            for _ in range(times):
                self.assertTrue(game.progression.upgrade_stat(key))
        budget = game.enemy_controller._enemy_stat_budget()
        self.assertEqual(
            budget,
            sum(
                int(level_count * enemy_ai_config.stat_mirror_ratio)
                for level_count in (3, 2, 1, 1, 1)
            ),
        )
        self.assertGreater(budget, 0)
        self.assertLess(
            budget, sum(game.progression.stat_levels.values())
        )  # 총량은 플레이어보다 항상 적다

        builds = []
        for enemy in game.enemies:
            self.assertEqual(
                sum(enemy.stat_levels.values()), budget
            )  # 포인트 총량은 모두 같다
            self.assertTrue(
                all(level_count >= 0 for level_count in enemy.stat_levels.values())
            )
            builds.append(
                tuple(
                    enemy.stat_levels[stat_key]
                    for stat_key in sorted(enemy.stat_levels)
                )
            )
        self.assertGreater(len(set(builds)), 1)  # 어디에 찍는지는 개체마다 다르다

        # 레벨업으로 포인트 총량이 늘면 다시 무작위로 재배분된다.
        self.assertTrue(game.progression.upgrade_stat("damage"))
        new_budget = game.enemy_controller._enemy_stat_budget()
        self.assertGreater(new_budget, budget)
        for enemy in game.enemies:
            self.assertEqual(sum(enemy.stat_levels.values()), new_budget)

    def test_enemies_respawn_away_from_player_and_other_enemies(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        game = open_game(enemies=1, seed=3, mercy_seconds=0)
        enemy = game.enemies[0]

        # 적이 플레이어·다른 적과 떨어진 유효 위치에 재등장하는지 확인한다.
        for _ in range(20):
            game.enemy_controller._respawn_enemy(enemy)
            self.assertTrue(game.terrain.circle_fits(enemy.x, enemy.y, enemy.radius))
            self.assertGreaterEqual(
                math.hypot(enemy.x - game.player.x, enemy.y - game.player.y),
                300.0 - 1e-6,
            )

    def test_respawn_waits_for_timer_and_ai_starts_on_following_frame(self):
        """재등장 대기를 프레임마다 줄이고 재등장 다음 프레임부터 적 AI를 실행한다."""
        game = open_game(enemies=1, mercy_seconds=0)
        enemy = game.enemies[0]
        enemy.alive = False
        enemy.hp = 0.0
        enemy.respawn_timer = 2

        # 대기가 남은 프레임에는 죽은 상태를 유지한다.
        game.step(0, want_fire=False)
        self.assertFalse(enemy.alive)
        self.assertEqual(enemy.respawn_timer, 1)

        # 대기가 끝난 프레임에는 재등장만 하고 조준·발사 AI의 타이머는 진행하지 않는다.
        game.step(0, want_fire=False)
        self.assertTrue(enemy.alive)
        self.assertEqual(enemy.hp, enemy.max_hp)
        self.assertEqual(enemy.ai_timer, 0)
        self.assertEqual(enemy.cooldown, enemy.fire_cooldown_max)

        # 그다음 프레임부터 목표 선택과 발사 대기 갱신을 실행한다.
        game.step(0, want_fire=False)
        self.assertEqual(enemy.ai_timer, game.config.enemy_ai.reaction_frames)
        self.assertEqual(enemy.cooldown, enemy.fire_cooldown_max - 1)

    def test_mercy_weakens_early_enemies_and_fades_out(self):
        """초반 mercy_seconds 동안 적이 약하게 시작해 서서히 정상(tier 0) 강도로 돌아온다."""

        # 검사에 사용할 설정·개체·입력을 준비한다.
        game = open_game(enemies=1, seed=11, mercy_seconds=30)
        enemy_ai_config = game.config.enemy_ai
        enemy = game.enemies[0]
        full_hp = game.config.enemy_hp + SHIPS[enemy.job].hp_bonus * 0.5
        full_cooldown = enemy_ai_config.fire_cooldown

        # 초반 약화가 적용되고 시간이 지나면 정상 능력치로 돌아오는지 확인한다.
        self.assertAlmostEqual(enemy.max_hp, full_hp * enemy_ai_config.mercy_hp_scale)
        self.assertAlmostEqual(enemy.damage_scale, enemy_ai_config.mercy_damage_scale)
        self.assertGreater(enemy.fire_cooldown_max, full_cooldown)  # 더 느리게 쏜다
        game.frame = int(enemy_ai_config.mercy_seconds * game.config.fps)
        game.enemy_controller._update_enemy_scaling()
        self.assertAlmostEqual(enemy.max_hp, full_hp)
        self.assertAlmostEqual(enemy.damage_scale, 1.0)
        self.assertEqual(enemy.fire_cooldown_max, full_cooldown)

    def test_enemies_evolve_with_player_stage(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        game = open_game(enemies=8)

        # 플레이어와 같은 단계로 적이 진화하고 재등장 뒤에도 단계가 유지되는지 확인한다.
        self.assertTrue(all(enemy.job == "rookie" for enemy in game.enemies))
        for job, level in (("flank", 10), ("twin_flank", 20), ("hexa_cruiser", 30)):
            evolve(game, job)
            self.assertEqual(game.player.job, job)
            self.assertTrue(
                all(enemy.job in SHIPS_BY_LEVEL[level] for enemy in game.enemies)
            )
            for enemy in game.enemies:
                self.assertAlmostEqual(
                    enemy.radius,
                    game.config.tank_radius * SHIPS[enemy.job].radius_scale,
                )
        enemy = game.enemies[0]
        enemy.alive = False
        game.enemy_controller._respawn_enemy(enemy)
        self.assertIn(enemy.job, SHIPS_BY_LEVEL[30])

    def test_evolved_enemy_takes_reduced_damage_like_player(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        game = open_game(enemies=1)
        enemy = game.enemies[0]
        enemy.job = "citadel"
        game.enemy_controller._apply_enemy_strength(enemy)
        hp = enemy.hp
        game.combat._damage_tank(enemy, 10, True)

        # 진화한 적에게도 우주선의 받는 피해 배율이 적용되는지 확인한다.
        self.assertAlmostEqual(enemy.hp, hp - 10 * SHIPS["citadel"].damage_taken)


class StatLimitTests(unittest.TestCase):
    def test_every_stat_stops_at_max_level(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        game = open_game()
        game.progression.upgrade_points = len(STAT_UPGRADES) * STAT_MAX_LEVEL + 3

        # 모든 스탯이 최대 단계에서 멈추고 남은 포인트가 보존되는지 확인한다.
        for card in STAT_UPGRADES:
            for _ in range(STAT_MAX_LEVEL):
                self.assertTrue(game.progression.upgrade_stat(card.key))
            self.assertFalse(game.progression.upgrade_stat(card.key))
        self.assertEqual(game.progression.upgrade_points, 3)

    def test_speed_and_fire_rate_gains_are_smaller(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        game = open_game()
        game.progression.upgrade_points = 2
        game.progression.upgrade_stat("speed")
        game.progression.upgrade_stat("rapid")

        # 이동속도와 발사속도의 단계별 증가량을 확인한다.
        self.assertAlmostEqual(game.player.accel_scale, 1.07)
        self.assertEqual(game.player.fire_cooldown_max, 27)


class ShipTweakTests(unittest.TestCase):
    def fire(self, job):
        game = open_game()
        evolve(game, job)
        game.player.x = game.player.y = 1000
        game.player.angle = 0.0
        game.combat._fire(game.player, True)
        return game, game.combat.bullets[0]

    def test_sniper_and_guardian_fire_larger_rounds(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        _, rookie = self.fire("rookie")
        _, sniper = self.fire("sniper")
        game, guardian = self.fire("guardian")

        # 저격·가디언 계열의 탄환 크기와 피해량을 비교한다.
        self.assertGreater(sniper.radius, rookie.radius)
        self.assertGreater(guardian.radius, rookie.radius)
        self.assertLess(guardian.damage, game.config.bullet_damage * 0.7)

    def test_guardian_health_is_smaller(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        game = open_game()
        evolve(game, "guardian")

        # 가디언 선체 크기가 설정된 비율에 맞는지 확인한다.
        self.assertLess(game.player.radius, game.config.tank_radius * 32 / 22)

    def test_planet_sizes_differ_clearly(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        small, medium, large = (
            SHAPE_TYPES[shape_kind]["radius"]
            for shape_kind in ("square", "triangle", "pentagon")
        )

        # 천체 종류별 충돌 반지름의 크기 차이를 확인한다.
        self.assertEqual(small, 26)
        self.assertGreaterEqual(medium / small, 1.8)
        self.assertGreaterEqual(large / medium, 1.7)


class ShapeSpawnTests(unittest.TestCase):
    def overlaps(self, shapes):
        return [
            (first_shape.id, second_shape.id)
            for shape_index, first_shape in enumerate(shapes)
            for second_shape in shapes[shape_index + 1 :]
            if math.hypot(
                first_shape.x - second_shape.x, first_shape.y - second_shape.y
            )
            < first_shape.radius + second_shape.radius
        ]

    def test_shapes_never_spawn_overlapping(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        game = GameCore(GameConfig(), seed=5)

        # 처음 생성하거나 보충한 천체가 서로 겹치지 않는지 확인한다.
        self.assertEqual(self.overlaps(game.shapes), [])
        game.frame = 100
        for _ in range(100):
            game.shapes.pop(0)
            game.shapes.append(game._make_shape())
        self.assertEqual(self.overlaps(game.shapes), [])

    def test_respawned_shapes_appear_far_from_player(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        game = GameCore(GameConfig(), seed=5)
        game.frame = 100
        player = game.player

        # 판 도중 생성된 천체가 플레이어에게서 충분히 떨어지는지 확인한다.
        for _ in range(50):
            game.shapes.pop(0)  # 천체 수는 평소처럼 유지
            shape = game._make_shape()
            game.shapes.append(shape)
            self.assertGreaterEqual(
                math.hypot(shape.x - player.x, shape.y - player.y),
                game.config.shape_respawn_dist_from_player,
            )


class ShapeSpawnAvoidsTightCornersTests(unittest.TestCase):
    def test_mostly_avoids_a_tight_corner_that_leaves_no_room_to_orbit(self):
        """적이 거리(140px)를 유지하며 돌 공간이 없는 좁은 구석엔 가능하면 스폰하지 않는다
        (그런 구석에 천체가 생기면 적들이 거리 유지를 하려다 구석에 몰려 끼기 쉽다).
        방 대부분은 넓게 트여 있고 한쪽 구석만 ㄱ자 벽으로 좁게 막아 둔 뒤, 스폰 위치
        대부분이 '적이 돌 수 있는 자리(roomy)'를 만족하는지 확인한다."""

        # 검사에 사용할 설정·개체·입력을 준비한다.
        from space_z.game.terrain import TileMap, EMPTY, WALL

        config = GameConfig(num_enemies=0, num_shapes=0)
        config.terrain.enabled = False
        game = GameCore(config, seed=3)
        size = 30
        tiles = [[EMPTY] * size for _ in range(size)]
        for edge_index in range(size):
            tiles[0][edge_index] = tiles[size - 1][edge_index] = tiles[edge_index][
                0
            ] = tiles[edge_index][size - 1] = WALL
        for row in range(1, 7):  # 왼쪽 위 구석에 ㄱ자 벽을 세워 좁은 틈을 만든다
            tiles[row][1] = tiles[row][2] = WALL
        for col in range(1, 7):
            tiles[1][col] = tiles[2][col] = WALL
        game.terrain = TileMap(
            tiles, 48, (size // 2, size // 2), [], "corner", config.terrain
        )
        game.player.x, game.player.y = game.terrain.center(size // 2, size // 2)
        game.frame = 0  # frame==0이면 player 거리 조건은 통과로 처리됨

        radius = 26
        roomy_hits = 0
        sample_index = 40
        for _ in range(sample_index):
            x, y = game._shape_spawn_pos(radius)
            if game.terrain.circle_fits(x, y, radius + 140.0):
                roomy_hits += 1

        # 천체 생성 위치가 좁은 벽 구석을 우선 피하는지 확인한다.
        self.assertGreaterEqual(
            roomy_hits, sample_index - 2
        )  # 대부분은 여유 있는 자리를 골라야 한다


class SmarterEnemyAITests(unittest.TestCase):
    """플레이어가 대각선/벽 뒤에 있어도 적이 찾아오는지."""

    def make(self, enemies, wall_col=None):
        from space_z.game.terrain import TileMap, EMPTY, WALL

        config = GameConfig(num_enemies=enemies, num_shapes=0)
        config.terrain.enabled = False
        game = GameCore(config, seed=1)
        tiles = [[EMPTY] * 60 for _ in range(45)]
        if wall_col is not None:
            for row in range(5, 40):
                for col in range(wall_col, wall_col + 2):
                    tiles[row][col] = WALL
        game.terrain = TileMap(tiles, 48, (2, 2), [], "ai", config.terrain)
        game.player.hp = game.player.max_hp = 10**6
        return game

    def place(self, tank, x, y):
        tank.x, tank.y, tank.velocity_x, tank.velocity_y = x, y, 0.0, 0.0

    def run_frames(self, game, frames, fire=False):
        for _ in range(frames):
            game.step(0, want_fire=fire)

    def test_sees_player_diagonally_at_screen_distance_instead_of_farming(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        game = self.make(1)
        enemy, player = game.enemies[0], game.player
        self.place(enemy, 1000, 800)
        self.place(player, 1000 + 450, 800 + 450)  # 대각선 약 636px
        from space_z.game.game_core import Shape

        game.shapes = [
            Shape(
                game._new_id(),
                "square",
                1060,
                800,
                0,
                0,
                10,
                10,
                26,
                10,
            )
        ]
        self.run_frames(game, 25)

        # 적이 화면 거리의 플레이어를 발견하면 천체 대신 플레이어를 추적하는지 확인한다.
        self.assertEqual(enemy.ai_target[0], "player")
        self.assertLess(math.hypot(enemy.x - player.x, enemy.y - player.y), 636)

    def test_enemy_abandons_target_immediately_when_it_was_destroyed_elsewhere(self):
        """다른 적이 쫓던 천체를 부쉈을 때, 다음 반응 주기까지 기다리지 않고
        바로 새 목표를 찾도록 풀어줘야 구석에 계속 머무르지 않는다."""

        # 검사에 사용할 설정·개체·입력을 준비한다.
        game = self.make(1)
        enemy, player = game.enemies[0], game.player
        self.place(enemy, 1000, 800)
        self.place(player, 1000 + 10**5, 800)  # 멀리 둬서 플레이어가 안 보이게 한다
        enemy.ai_target = ("shape", 999)  # 이미 사라진(다른 적이 파괴한) 천체
        enemy.ai_timer = 15
        enemy.ai_path = [(10, 10), (11, 10)]
        game.enemy_controller._enemy_ai(enemy)

        # 다른 곳에서 파괴된 목표를 적이 즉시 포기하는지 확인한다.
        self.assertIsNone(enemy.ai_target)
        self.assertEqual(enemy.ai_timer, 0)
        self.assertEqual(enemy.ai_path, [])

    def test_finds_player_hiding_behind_a_wall(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        game = self.make(1, wall_col=20)
        enemy, player = game.enemies[0], game.player
        self.place(enemy, 20 * 48 - 150, 1000)
        self.place(player, 22 * 48 + 90, 1000)  # 벽 너머 약 336px

        # 벽 뒤의 플레이어를 찾아 경로를 따라 접근하는지 확인한다.
        self.assertFalse(
            game.terrain.line_of_sight(enemy.x, enemy.y, player.x, player.y)
        )
        self.run_frames(game, 5)
        self.assertIsNotNone(enemy.ai_last_seen)
        self.assertEqual(enemy.ai_target[0], "point")
        self.assertTrue(enemy.ai_path)  # 벽을 돌아가는 경로를 찾았다
        found = False
        for _ in range(900):  # 긴 벽을 돌아 15초 안에 다시 찾아낸다
            self.run_frames(game, 1)
            found = found or enemy.ai_can_see
        self.assertTrue(found)

    def test_hears_player_gunfire_through_walls(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        game = self.make(1, wall_col=20)
        enemy, player = game.enemies[0], game.player
        self.place(enemy, 20 * 48 - 400, 1000)
        self.place(player, 22 * 48 + 300, 1000)  # 벽 너머 약 800px
        self.run_frames(game, 10)

        # 벽 너머 발사 소리를 듣고 플레이어 위치를 기억하는지 확인한다.
        self.assertIsNone(enemy.ai_last_seen)
        self.run_frames(game, 2, fire=True)
        self.assertIsNotNone(enemy.ai_last_seen)

    def test_enemy_that_sees_player_alerts_nearby_allies(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        game = self.make(2, wall_col=20)
        seer, ally, player = game.enemies[0], game.enemies[1], game.player
        self.place(player, 1600, 1000)
        self.place(seer, 1300, 1000)  # 같은 쪽에서 직접 봄
        self.place(ally, 700, 1100)  # 벽 너머, 감지 거리 밖 (동료와 약 610px)
        # 초반에는 동료를 부르지 않는다.
        self.run_frames(game, 2)

        # 적이 화면 거리의 플레이어를 발견하면 천체 대신 플레이어를 추적하는지 확인한다.
        self.assertTrue(seer.ai_can_see)
        self.assertFalse(ally.ai_can_see)
        self.assertIsNone(ally.ai_last_seen)
        # 일정 시간이 지나면 부른다.
        game.frame = int(game.config.enemy_ai.alert_start_seconds * game.config.fps)
        self.place(seer, 1300, 1000)
        self.place(ally, 700, 1100)
        self.run_frames(game, 2)
        self.assertTrue(seer.ai_can_see)
        self.assertIsNotNone(ally.ai_last_seen)


class EliteEnemyTests(unittest.TestCase):
    def test_some_enemies_spawn_as_elite_with_more_hp_and_damage(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        game = open_game(
            enemies=60, seed=3, mercy_seconds=0
        )  # 초반 봐주기로 엘리트가 사라지지 않게 분리
        elites = [enemy for enemy in game.enemies if enemy.elite]
        normals = [
            enemy for enemy in game.enemies if not enemy.elite and enemy.job == "rookie"
        ]

        # 일부 적이 강화된 체력과 공격력의 엘리트로 생성되는지 확인한다.
        self.assertTrue(0 < len(elites) < len(game.enemies))
        enemy_ai_config = game.config.enemy_ai
        self.assertAlmostEqual(
            elites[0].max_hp, normals[0].max_hp * enemy_ai_config.elite_hp_scale
        )
        self.assertAlmostEqual(
            elites[0].damage_scale,
            normals[0].damage_scale * enemy_ai_config.elite_damage_scale,
        )
        # 시간 성장과 진화 뒤에도 엘리트 배율은 유지된다.
        game.frame = int(enemy_ai_config.scale_interval_seconds * game.config.fps * 3)
        game.enemy_controller._update_enemy_scaling()
        self.assertAlmostEqual(
            elites[0].max_hp, normals[0].max_hp * enemy_ai_config.elite_hp_scale
        )

    def test_killing_elite_heals_player_and_normal_kill_does_not(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        game = open_game(enemies=2)
        player, enemy_ai_config = game.player, game.config.enemy_ai
        normal, elite = game.enemies
        normal.elite, elite.elite = False, True
        game.enemy_controller._apply_enemy_strength(elite)
        player.hp = 20
        game.combat._damage_tank(normal, 10**6, True)

        # 엘리트 처치에만 플레이어 회복 보상이 적용되는지 확인한다.
        self.assertEqual(player.hp, 20)
        game.combat._damage_tank(elite, 10**6, True)
        self.assertAlmostEqual(
            player.hp, 20 + player.max_hp * enemy_ai_config.elite_heal_ratio
        )
        self.assertEqual(
            game.progression.score,
            round(
                game.config.enemy_kill_score * (1 + enemy_ai_config.elite_score_scale)
            ),
        )
        player.hp = player.max_hp - 1
        elite.alive, elite.hp = True, elite.max_hp
        game.combat._damage_tank(elite, 10**6, True)
        self.assertEqual(player.hp, player.max_hp)  # 최대 체력을 넘지 않는다


class StatPanelCollapseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        pygame.init()
        config = GameConfig(num_enemies=0, num_shapes=0)
        config.terrain.enabled = False
        cls.renderer = Renderer(config)

    @classmethod
    def tearDownClass(cls):
        pygame.quit()

    def test_panel_collapses_when_idle_and_reopens_on_click(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        game = GameCore(self.renderer.config, seed=7)
        application = GameApplication(game, self.renderer, seed=7)
        application.mode = "playing"
        keys, far = defaultdict(bool), (700, 200)
        application.update(0, keys, far, (False, False, False))

        # 사용하지 않은 스탯 창이 접히고 클릭하면 다시 펼쳐지는지 확인한다.
        self.assertFalse(application.stat_panel_collapsed)
        for _ in range(60):  # 한 번에 최대 5프레임씩 진행
            application.update(0.1, keys, far, (False, False, False))
        self.assertTrue(application.stat_panel_collapsed)
        application.draw(ObsConfig())
        pill = pygame.Rect(get_collapsed_stat_panel_rect(*self.renderer.size))
        self.assertTrue(application.pointer_over_rewards(pill.center))
        application.handle_event(
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=pill.center)
        )
        self.assertFalse(application.stat_panel_collapsed)
        # 새 스탯 포인트가 생겨도 다시 펼쳐진다.
        for _ in range(60):
            application.update(0.1, keys, far, (False, False, False))
        self.assertTrue(application.stat_panel_collapsed)
        game.progression._add_score(100)
        application.update(0, keys, far, (False, False, False))
        self.assertFalse(application.stat_panel_collapsed)


if __name__ == "__main__":
    unittest.main()
