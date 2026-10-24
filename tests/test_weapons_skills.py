"""21종 진화, 포신별 점사·전방위 사격과 일반 고속탄 회귀 검증."""

import math
import os
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

from space_z.config import GameConfig
from space_z.game.game_core import Bullet, GameCore, Shape, Tank
from space_z.config.progression_definitions import SHIPS, SKILLS, STAT_UPGRADES
from space_z.rendering.progression_panel import (
    build_stat_upgrade_rows,
    can_show_stat_upgrades,
)
from space_z.game.terrain import TileMap, EMPTY, WALL, BREAKABLE


class WeaponsSkillsTests(unittest.TestCase):
    def setUp(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        config = GameConfig(
            num_enemies=0,
            num_shapes=0,
            tank_radius=44,
        )
        config.terrain.enabled = False
        self.game = GameCore(config, seed=7)
        self.game.player.x, self.game.player.y, self.game.player.angle = 500, 500, 0
        self.game.enemy_controller._enemy_ai = lambda enemy: None

    def evolve(self, job):
        chain = []
        while job != "rookie":
            chain.append(job)
            job = SHIPS[job].parent or "rookie"
        for key in reversed(chain):
            level = SHIPS[key].level
            score = sum(
                self.game.config.level_xp_base
                + (level_number - 1) * self.game.config.level_xp_growth
                for level_number in range(1, level)
            )
            self.game.progression._add_score(score - self.game.progression.score)
            self.assertTrue(
                self.game.progression.choose_reward(
                    next(
                        choice_index
                        for choice_index, card in enumerate(
                            self.game.progression.reward_choices
                        )
                        if card.key == key
                    )
                )
            )

    def enemy(self, x, y, hp=100):
        enemy = Tank(
            self.game._new_id(),
            "enemy",
            x,
            y,
            hp,
            hp,
            self.game.config.tank_radius,
            36,
        )
        self.game.enemies.append(enemy)
        return enemy

    def wall_map(self, kind=WALL):
        terrain_config = self.game.config.terrain
        terrain_config.breakable_enabled = True
        tiles = [[EMPTY] * 60 for _ in range(45)]
        for row in range(45):
            tiles[row][14] = kind
        self.game.terrain = TileMap(tiles, 48, (2, 2), [], "test", terrain_config)

    def burst(self, frames, hold=False):
        emitted = []
        for frame in range(frames):
            start = len(self.game.combat.bullets)
            self.game.combat._fire(self.game.player, hold or frame == 0)
            emitted.extend(
                (frame, bullet) for bullet in self.game.combat.bullets[start:]
            )
            self.game.frame += 1
        return emitted

    def test_exact_three_stage_tree_has_21_ships(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        expected = {
            "rookie": {"twin", "sniper", "flank", "guardian"},
            "twin": {"dual_striker", "triple_wing"},
            "sniper": {"railgunner", "hunter"},
            "flank": {"quad_wing", "twin_flank"},
            "guardian": {"bastion", "aegis"},
            "dual_striker": {"gatling_storm"},
            "triple_wing": {"penta_wing"},
            "railgunner": {"hyper_railgun"},
            "hunter": {"predator"},
            "quad_wing": {"octa_star"},
            "twin_flank": {"hexa_cruiser"},
            "bastion": {"colossus"},
            "aegis": {"citadel"},
        }

        # 우주선 21종의 세 단계 진화 관계를 확인한다.
        self.assertEqual(len(SHIPS), 21)
        for parent, children in expected.items():
            actual = {
                ship.key
                for ship in SHIPS.values()
                if (ship.parent or "rookie") == parent and ship.key != "rookie"
            }
            self.assertEqual(actual, children)
        for key in (
            "gatling_storm",
            "penta_wing",
            "hyper_railgun",
            "predator",
            "octa_star",
            "hexa_cruiser",
            "colossus",
            "citadel",
        ):
            with self.subTest(key=key):
                self.setUp()
                self.evolve(key)
                self.assertEqual(
                    (self.game.progression.level, self.game.player.job), (30, key)
                )
                self.assertEqual(self.game.progression.special_reward_levels, [])
                self.assertIsNone(self.game.combat.active_skill)

    def test_bulk_xp_keeps_evolution_order_and_l40_mastery(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        game = self.game
        game.progression._add_score(31980)

        # 대량 경험치 지급 뒤에도 진화 순서와 40레벨 숙련 보상이 유지되는지 확인한다.
        self.assertEqual(game.progression.special_reward_levels, [10, 20, 30, 40])
        self.assertEqual(
            [card.key for card in game.progression.reward_choices],
            ["twin", "sniper", "flank", "guardian"],
        )
        self.assertTrue(game.progression.choose_reward(3))
        self.assertEqual(
            [card.key for card in game.progression.reward_choices], ["bastion", "aegis"]
        )
        self.assertTrue(game.progression.choose_reward(1))
        self.assertEqual(
            [card.key for card in game.progression.reward_choices], ["citadel"]
        )
        self.assertTrue(game.progression.choose_reward(0))
        self.assertEqual(game.progression.special_reward_levels, [40])
        hp, radius = game.player.max_hp, game.player.radius
        game.progression.choose_reward(0)
        self.assertEqual(game.progression.special_levels["citadel"], 2)
        self.assertEqual((game.player.max_hp, game.player.radius), (hp, radius))
        self.assertEqual(game.progression.special_reward_levels, [])
        self.assertFalse(game.progression.choose_reward(0))
        self.assertAlmostEqual(
            game.combat.weapon_values(game.player)[1],
            game.config.bullet_damage * 0.5 * 1.2,
        )

    def test_five_fixed_stats_show_at_zero_and_points_accumulate(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        game = self.game

        # 고정 스탯 목록과 강화 포인트 누적을 확인한다.
        self.assertEqual(
            [stat_upgrade.title for stat_upgrade in STAT_UPGRADES],
            ["체력", "공격력", "사거리 및 탄속도", "발사속도", "이동속도"],
        )
        self.assertTrue(can_show_stat_upgrades(game))
        self.assertEqual(game.progression.stat_choices, STAT_UPGRADES)
        self.assertTrue(
            all(
                not game.progression.can_upgrade_stat(stat_upgrade.key)
                for stat_upgrade in STAT_UPGRADES
            )
        )
        game.progression._add_score(190)
        for _ in range(40):
            game.step(0, want_fire=False)
        self.assertEqual(game.progression.upgrade_points, 2)
        self.assertEqual(game.progression.stat_choices, STAT_UPGRADES)
        game.progression._add_score(1790)
        self.assertEqual(
            (game.progression.upgrade_points, game.progression.special_reward_levels),
            (8, [10]),
        )
        self.assertTrue(game.progression.upgrade_stat("hull"))
        self.assertEqual(game.progression.upgrade_points, 7)
        self.assertEqual(game.progression.stat_choices, STAT_UPGRADES)
        rows = [rect for _, rect in build_stat_upgrade_rows(960, 720)]
        self.assertEqual(len(rows), 5)
        self.assertTrue(
            all(y >= 0 and y + height <= 720 for x, y, width, height in rows)
        )

    def test_twin_alternates_parallel_muzzles_after_trigger_release(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        self.evolve("twin")
        shots = self.burst(4)

        # 방아쇠를 놓아도 평행 쌍포의 예약 발사가 순서대로 끝나는지 확인한다.
        self.assertEqual([frame for frame, bullet in shots], [0, 3])
        first, second = [bullet for _, bullet in shots]
        self.assertEqual(
            (first.velocity_x, first.velocity_y), (second.velocity_x, second.velocity_y)
        )
        self.assertLess(first.y, 500)
        self.assertGreater(second.y, 500)
        self.assertEqual(self.game.player.ammo, 118)

    def test_dual_striker_uses_four_muzzles_in_sequence(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        self.evolve("dual_striker")
        shots = self.burst(7)

        # 네 포구의 발사 시점·위치·탄약 소비를 확인한다.
        self.assertEqual([frame for frame, bullet in shots], [0, 2, 4, 6])
        self.assertEqual(len({round(bullet.y, 3) for _, bullet in shots}), 4)
        self.assertTrue(
            all(bullet.velocity_x > 0 and bullet.velocity_y == 0 for _, bullet in shots)
        )
        self.assertEqual(self.game.player.ammo, 116)

    def test_gatling_six_round_bursts_keep_firing_without_long_gaps(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        self.evolve("gatling_storm")
        shots = self.burst(33, hold=True)
        frames = [frame for frame, bullet in shots]

        # 6연사 묶음의 발사 시점과 다음 묶음까지의 간격을 확인한다.
        self.assertEqual(frames[:6], [0, 2, 4, 6, 8, 10])
        # 묶음 안은 2프레임 간격, 묶음 사이에는 낮춘 발사 속도만큼 짧게 쉰다.
        self.assertGreaterEqual(len(frames), 12)
        self.assertLessEqual(
            max(
                next_frame - previous_frame
                for previous_frame, next_frame in zip(frames, frames[1:])
            ),
            6,
        )
        self.assertTrue(
            all(bullet.velocity_y == 0 and bullet.velocity_x > 0 for _, bullet in shots)
        )

    def test_fire_rate_upgrade_also_accelerates_gatling_burst(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        self.evolve("gatling_storm")
        baseline = len(self.burst(33, hold=True))
        self.setUp()
        self.evolve("gatling_storm")

        # 발사속도 강화가 연사 묶음 내부의 발사 간격도 줄이는지 확인한다.
        for _ in range(4):  # 1단계당 -5%라 몇 단계 올려야 차이가 보인다
            self.assertTrue(self.game.progression.upgrade_stat("rapid"))
        boosted = len(self.burst(33, hold=True))
        self.assertGreater(boosted, baseline)

    def test_spread_ships_fire_three_and_five_simultaneous_directions(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        for job, count in (("triple_wing", 3), ("penta_wing", 5)):
            with self.subTest(job=job):
                self.setUp()
                self.evolve(job)
                shots = self.burst(1)
                self.assertEqual(len(shots), count)
                angles = [
                    math.atan2(bullet.velocity_y, bullet.velocity_x)
                    for _, bullet in shots
                ]
                self.assertEqual(len(set(angles)), count)
                self.assertAlmostEqual(sum(angles), 0.0)
                self.assertTrue(all(bullet.velocity_x > 0 for _, bullet in shots))

    def test_flank_family_directions_and_parallel_pairs(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        expected = {
            "flank": 2,
            "quad_wing": 4,
            "octa_star": 8,
            "twin_flank": 4,
            "hexa_cruiser": 6,
        }

        # 전후·측면 발사 방향과 평행 포구 쌍의 위치를 확인한다.
        for job, count in expected.items():
            with self.subTest(job=job):
                self.setUp()
                self.evolve(job)
                shots = self.burst(6)  # 헥사 크루저는 2프레임 간격 3쌍 순차 사격
                self.assertEqual(len(shots), count)
                vectors = [
                    (round(bullet.velocity_x, 4), round(bullet.velocity_y, 4))
                    for _, bullet in shots
                ]
                self.assertTrue(
                    any(
                        direction_x > 0 and direction_y == 0
                        for direction_x, direction_y in vectors
                    )
                )
                self.assertTrue(
                    any(
                        direction_x < 0 and direction_y == 0
                        for direction_x, direction_y in vectors
                    )
                )
                if job in ("quad_wing", "octa_star"):
                    self.assertTrue(
                        any(
                            direction_x == 0 and direction_y > 0
                            for direction_x, direction_y in vectors
                        )
                    )
                    self.assertTrue(
                        any(
                            direction_x == 0 and direction_y < 0
                            for direction_x, direction_y in vectors
                        )
                    )
                if job == "octa_star":
                    self.assertEqual(len(set(vectors)), 8)
                if job in ("twin_flank", "hexa_cruiser"):
                    front = [
                        bullet
                        for _, bullet in shots
                        if bullet.velocity_x > 0 and abs(bullet.velocity_y) < 1e-7
                    ]
                    back = [
                        bullet
                        for _, bullet in shots
                        if bullet.velocity_x < 0 and abs(bullet.velocity_y) < 1e-7
                    ]
                    barrels = 3 if job == "hexa_cruiser" else 2
                    self.assertEqual(
                        len({round(bullet.y, 3) for bullet in front}), barrels
                    )
                    self.assertEqual(
                        len({round(bullet.y, 3) for bullet in back}), barrels
                    )
                if (
                    job == "hexa_cruiser"
                ):  # 이미지에 측면 포신이 없으므로 앞/뒤로만 쏜다
                    self.assertTrue(
                        all(abs(bullet.velocity_y) < 1e-7 for _, bullet in shots)
                    )

    def test_hunter_and_predator_are_single_shot_snipers(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        values = []

        # 헌터·프레데터가 예약 점사 없이 장거리 단발만 발사하는지 확인한다.
        for job in ("hunter", "predator"):
            with self.subTest(job=job):
                self.setUp()
                self.evolve(job)
                shots = self.burst(12)
                self.assertEqual(len(shots), 1)
                self.assertEqual(shots[0][0], 0)
                self.assertEqual(self.game.player.pending_shots, [])
                self.assertEqual(self.game.player.ammo, 119)
                bullet = shots[0][1]
                self.assertGreater(bullet.radius, 0)
                values.append(
                    (bullet.damage, bullet.velocity_x, bullet.velocity_x * bullet.life)
                )
        self.assertTrue(
            all(
                previous_value < next_value
                for previous_value, next_value in zip(values[0], values[1])
            )
        )

    def test_sniper_line_gains_damage_speed_and_range(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        values = []

        # 저격 계열 진화에 따라 피해량·탄속·사거리가 증가하는지 확인한다.
        for job in ("sniper", "railgunner", "hyper_railgun"):
            self.setUp()
            self.evolve(job)
            self.game.combat._fire(self.game.player, True)
            bullet = self.game.combat.bullets[0]
            values.append(
                (bullet.damage, bullet.velocity_x, bullet.velocity_x * bullet.life)
            )
            self.assertEqual(self.game.combat.beams, [])
        self.assertTrue(
            all(
                all(
                    previous_value[stat_index] < next_value[stat_index]
                    for stat_index in range(3)
                )
                for previous_value, next_value in zip(values, values[1:])
            )
        )

    def test_partial_magazine_never_creates_free_delayed_rounds(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        self.evolve("gatling_storm")
        self.game.player.ammo = 3
        shots = self.burst(20)

        # 탄약이 부족할 때 예약된 탄환이 무료로 발사되지 않는지 확인한다.
        self.assertEqual(len(shots), 3)
        self.assertEqual(self.game.player.ammo, 0)
        self.assertEqual(self.game.player.pending_shots, [])

    def test_reload_and_evolution_cancel_pending_rounds(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        self.evolve("twin")
        self.game.combat._fire(self.game.player, True)

        # 재장전과 진화가 남은 예약 점사를 취소하는지 확인한다.
        self.assertEqual(len(self.game.player.pending_shots), 1)
        self.assertTrue(self.game.combat.request_reload())
        self.assertEqual(self.game.player.pending_shots, [])
        self.burst(10)
        self.assertEqual(len(self.game.combat.bullets), 1)
        self.setUp()
        self.evolve("twin")
        self.game.combat._fire(self.game.player, True)
        self.game.progression._add_score(7980 - self.game.progression.score)
        self.game.progression.choose_reward(0)
        self.assertEqual(self.game.player.pending_shots, [])

    def test_dead_player_and_reset_cancel_pending_rounds(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        self.evolve("gatling_storm")
        self.game.combat._fire(self.game.player, True)

        # 사망과 새 판 초기화가 남은 예약 점사를 취소하는지 확인한다.
        self.assertTrue(self.game.player.pending_shots)
        self.game.player.hp = 0
        self.game.step(0, want_fire=False)
        self.assertTrue(self.game.game_over)
        self.assertEqual(self.game.player.pending_shots, [])
        self.game.reset(7)
        self.assertEqual(self.game.player.pending_shots, [])
        self.assertEqual(self.game.player.job, "rookie")

    def test_all_sniper_ships_pierce_exactly_one_extra_target(self):
        """다수 상대 약점을 보완하는 관통 1회: 첫 번째와 두 번째 대상은 맞지만
        세 번째는 맞지 않고, 같은 대상을 두 번 맞히지도 않는다."""

        # 검사에 사용할 설정·개체·입력을 준비한다.
        for job in ("sniper", "railgunner", "hyper_railgun", "hunter", "predator"):
            with self.subTest(job=job):
                self.setUp()
                self.evolve(job)
                first, second, third = (
                    self.enemy(600, 500),
                    self.enemy(720, 500),
                    self.enemy(840, 500),
                )
                self.game.combat._fire(self.game.player, True)
                for _ in range(20):
                    self.game.combat._move_bullets()
                self.assertLess(first.hp, 100)
                self.assertLess(second.hp, 100)
                self.assertEqual(third.hp, 100)
                self.assertEqual(self.game.combat.bullets, [])

    def test_non_sniper_ships_still_hit_only_one_target(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        for job in ("rookie", "twin", "flank", "guardian"):
            with self.subTest(job=job):
                self.setUp()
                self.evolve(job)
                first, second = self.enemy(600, 500), self.enemy(720, 500)
                self.game.combat._fire(self.game.player, True)
                for _ in range(20):
                    self.game.combat._move_bullets()
                self.assertLess(first.hp, 100)
                self.assertEqual(second.hp, 100)
                # 전후방으로 쏘는 전직(플랭크 등)은 뒤로 날아간 탄이 아직 살아있을 수 있으니,
                # 첫 대상을 맞힌 탄 자체가 관통 없이 사라졌는지만 확인한다.
                self.assertFalse(
                    any(bullet.hit_ids for bullet in self.game.combat.bullets)
                )

    def test_fast_bullet_stops_at_breakable_wall(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        self.wall_map(BREAKABLE)
        far = self.enemy(800, 500)
        self.game.combat.bullets = [
            Bullet(
                500,
                500,
                300,
                0,
                70,
                self.game.player.id,
                "player",
                20,
                5,
            )
        ]
        self.game.combat._move_bullets()

        # 빠른 탄환이 벽을 통과하지 않고 파괴 가능 벽에 피해를 주는지 확인한다.
        self.assertEqual(far.hp, 100)
        self.assertEqual(self.game.combat.bullets, [])
        self.assertEqual(self.game.terrain.hp[(14, 10)], 20)

    def test_fast_bullet_hits_only_nearest_target(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        near, far = self.enemy(560, 500), self.enemy(620, 500)
        self.game.combat.bullets = [
            Bullet(
                500,
                500,
                300,
                0,
                70,
                self.game.player.id,
                "player",
                7,
                6,
            )
        ]
        self.game.combat._move_bullets()

        # 빠른 탄환이 이동 구간의 가장 가까운 대상만 맞히는지 확인한다.
        self.assertEqual((near.hp, far.hp), (93, 100))
        self.assertEqual(self.game.combat.bullets, [])

    def test_last_projectile_step_still_hits_before_world_boundary(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        edge = self.game.config.world_width
        enemy = self.enemy(edge - 60, 500)
        self.game.combat.bullets = [
            Bullet(
                edge - 100,
                500,
                300,
                0,
                1,
                self.game.player.id,
                "player",
                7,
                6,
            )
        ]
        self.game.combat._move_bullets()

        # 수명 마지막 프레임에도 월드 경계 앞의 대상을 맞히는지 확인한다.
        self.assertEqual(enemy.hp, 93)
        self.assertEqual(self.game.combat.bullets, [])

    def test_large_guardians_have_real_radius_health_and_small_guns(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        for job, radius, hp, count in (
            ("guardian", 52, 200, 1),
            ("bastion", 80, 320, 2),
            ("aegis", 80, 300, 2),
            ("colossus", 92, 500, 3),
            ("citadel", 96, 540, 4),
        ):
            with self.subTest(job=job):
                self.setUp()
                self.evolve(job)
                player = self.game.player
                self.assertAlmostEqual(player.radius, radius)
                self.assertEqual((player.hp, player.max_hp), (hp, hp))
                self.game.combat._damage_tank(player, 10, False)
                self.assertAlmostEqual(player.hp, hp - 10 * SHIPS[job].damage_taken)
                self.game.combat._fire(player, True)
                self.assertEqual(len(self.game.combat.bullets), count)
                self.assertTrue(
                    all(
                        bullet.damage < self.game.config.bullet_damage
                        for bullet in self.game.combat.bullets
                    )
                )
                if job not in ("guardian", "bastion", "aegis"):  # 이 셋은 포신을 키웠다
                    self.assertTrue(
                        all(
                            bullet.radius < self.game.config.bullet_radius
                            for bullet in self.game.combat.bullets
                        )
                    )
                self.assertTrue(
                    all(
                        math.hypot(bullet.x - player.x, bullet.y - player.y)
                        > player.radius
                        for bullet in self.game.combat.bullets
                    )
                )

    def test_guardian_growth_preserves_hull_upgrades_and_damage(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        game = self.game
        game.progression._add_score(190)
        game.progression.upgrade_stat("hull")
        game.player.hp -= 30
        self.evolve("citadel")

        # 가디언 진화 뒤 기존 체력 강화와 받은 피해가 보존되는지 확인한다.
        self.assertEqual((game.player.max_hp, game.player.hp), (565, 535))

    def test_evolving_next_to_wall_moves_large_ship_to_safe_space(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        self.wall_map()
        self.game.player.x, self.game.player.y = 627, 504

        # 큰 우주선으로 진화할 때 벽과 겹치지 않는 위치로 이동하는지 확인한다.
        self.assertTrue(self.game.terrain.circle_fits(627, 504, 44))
        self.evolve("guardian")
        player = self.game.player
        self.assertTrue(
            self.game.terrain.circle_fits(player.x, player.y, player.radius)
        )
        self.assertNotEqual((player.x, player.y), (627, 504))

    def test_long_barrel_cannot_spawn_a_projectile_beyond_wall(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        self.evolve("hyper_railgun")
        self.wall_map()
        self.game.player.x, self.game.player.y = 627, 504
        far = self.enemy(800, 504)
        self.game.combat._fire(self.game.player, True)

        # 긴 포신이 벽 뒤에 탄환을 생성하지 않는지 확인한다.
        self.assertLess(self.game.combat.bullets[0].x, 672)
        for _ in range(5):
            self.game.combat._move_bullets()
        self.assertEqual(far.hp, 100)
        self.assertEqual(self.game.combat.bullets, [])

    def single_corner_wall(self):
        tiles = [[EMPTY] * 60 for _ in range(45)]
        tiles[10][10] = WALL
        self.game.terrain = TileMap(
            tiles, 48, (2, 2), [], "corner", self.game.config.terrain
        )

    def test_bullet_radius_blocks_diagonal_corner_at_normal_and_high_speed(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        self.single_corner_wall()

        # 일반·고속 탄환 모두 반지름을 반영해 벽 모서리에서 막히는지 확인한다.
        for speed in (28.8, 100.0):
            with self.subTest(speed=speed):
                far = self.enemy(560, 612)
                self.game.combat.bullets = [
                    Bullet(
                        450,
                        502,
                        speed,
                        speed,
                        70,
                        self.game.player.id,
                        "player",
                        7,
                        6,
                    )
                ]
                self.game.combat._move_bullets()
                self.assertEqual(self.game.combat.bullets, [])
                self.assertEqual(far.hp, 100)

    def test_round_bullet_can_clear_corner_when_circle_does_not_touch(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        self.single_corner_wall()
        bullet = Bullet(
            450,
            510,
            100,
            100,
            70,
            self.game.player.id,
            "player",
            7,
            6,
        )
        self.game.combat.bullets = [bullet]
        self.game.combat._move_bullets()

        # 원형 탄체가 닿지 않는 모서리는 지나갈 수 있는지 확인한다.
        self.assertEqual(self.game.combat.bullets, [bullet])
        self.assertEqual((bullet.x, bullet.y), (550, 610))

    def test_long_muzzle_respects_bullet_radius_near_wall_corner(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        self.evolve("hyper_railgun")
        self.single_corner_wall()
        self.game.player.x, self.game.player.y, self.game.player.angle = (
            430,
            482,
            math.pi / 4,
        )
        self.game.combat._fire(self.game.player, True)
        bullet = self.game.combat.bullets[0]

        # 긴 포구도 벽 모서리에서 탄환 반지름만큼 여유를 두는지 확인한다.
        self.assertTrue(
            self.game.terrain.circle_fits(bullet.x, bullet.y, bullet.radius)
        )
        self.game.combat._move_bullets()
        self.assertEqual(self.game.combat.bullets, [])

    def test_measured_long_muzzle_does_not_skip_nearby_experience_object(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        self.evolve("hyper_railgun")
        shape = Shape(
            self.game._new_id(),
            "square",
            558,
            500,
            0,
            0,
            100,
            100,
            14,
            10,
        )
        self.game.shapes = [shape]
        self.game.combat._fire(self.game.player, True)

        # 포신 중간에 겹친 경험치 천체를 건너뛰지 않고 타격하는지 확인한다.
        self.assertEqual(shape.hp, 77.6)
        # 하이퍼 레일건은 관통 1회가 있어 맞힐 대상이 더 없어도 탄환 자체는 계속 날아간다.
        self.assertEqual(len(self.game.combat.bullets), 1)
        self.assertEqual(self.game.combat.bullets[0].pierce, 0)
        self.assertIn(shape.id, self.game.combat.bullets[0].hit_ids)
        self.assertEqual(self.game.player.ammo, 119)
        self.game.combat._move_bullets()
        self.assertEqual(shape.hp, 77.6)

    def test_projectile_collision_width_matches_measured_gun_opening(self):
        # 원본 512px PNG 포신 안쪽의 밝은 회색 부분을 실측한 픽셀 폭이다.
        for job, hull, opening in (
            ("rookie", 139, 26),
            ("twin", 136, 22),
            ("hunter", 174, 19),
            ("citadel", 290, 10),
        ):
            with self.subTest(job=job):
                self.setUp()
                self.evolve(job)
                self.game.combat._fire(self.game.player, True)
                bullet = self.game.combat.bullets[0]
                gun_width = 2 * self.game.player.radius * opening / hull
                self.assertAlmostEqual(2 * bullet.radius, gun_width * 0.9)
                self.assertLess(2 * bullet.radius, gun_width)

    def test_basic_and_all_enemy_collision_radii_are_doubled(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        config = GameConfig(
            num_shapes=0,
            num_enemies=3,
            tank_radius=44,
        )
        config.terrain.enabled = False
        game = GameCore(config, seed=7)

        # 기본 선체와 모든 적의 충돌 반지름 배율을 확인한다.
        self.assertEqual(game.player.radius, 44)
        self.assertEqual([enemy.radius for enemy in game.enemies], [44, 44, 44])
        for enemy in game.enemies:
            self.assertTrue(game.terrain.circle_fits(enemy.x, enemy.y, enemy.radius))

    def test_enemy_rounds_match_their_ship_guns(self):
        # 적도 플레이어와 같은 진화 우주선을 쓰므로 그 우주선의 포구에서 탄이 나간다.
        for job in ("rookie", "sniper", "triple_wing", "hexa_cruiser"):
            with self.subTest(job=job):
                self.setUp()
                enemy = self.enemy(800, 800)
                enemy.job = job
                spec = SHIPS[job]
                for _ in range(10):
                    self.game.combat._fire(enemy, True)
                    self.game.frame += 1
                self.assertEqual(len(self.game.combat.bullets), len(spec.shots))
                for bullet in self.game.combat.bullets:
                    self.assertEqual(bullet.team, "enemy")
                    self.assertTrue(
                        any(
                            abs(bullet.radius - enemy.radius * shot.caliber) < 1e-9
                            for shot in spec.shots
                        )
                    )

    def test_q_and_space_no_longer_activate_skills_or_dash(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        self.evolve("citadel")

        # 제거된 Q·Space 전투 동작이 실행되지 않는지 확인한다.
        self.assertEqual(SKILLS, {})
        self.assertFalse(self.game.combat.request_skill(3))
        self.game.step(0, want_fire=False, want_skill=True, want_dash=True)
        self.assertEqual(
            (self.game.combat.skill_cooldown, self.game.combat.dash_frames_left), (0, 0)
        )
        self.assertEqual(self.game.combat.bullets, [])
        self.assertIsNone(self.game.combat.active_skill)


if __name__ == "__main__":
    unittest.main()
