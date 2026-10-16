"""21종 진화, 포신별 점사·전방위 사격과 일반 고속탄 회귀 검증."""
import math
import os
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

from config import GameConfig
from game_core import Bullet, GameCore, Shape, Tank
from progression import SHIPS, SKILLS, STAT_UPGRADES, stat_rows, stat_upgrades_visible
from terrain import TileMap, EMPTY, WALL, BREAKABLE


class WeaponsSkillsTests(unittest.TestCase):
    def setUp(self):
        cfg = GameConfig(num_enemies=0, num_shapes=0, tank_radius=44)
        cfg.terrain.enabled = False
        self.game = GameCore(cfg, seed=7)
        self.game.player.x, self.game.player.y, self.game.player.angle = 500, 500, 0
        self.game._enemy_ai = lambda enemy: None

    def evolve(self, job):
        chain = []
        while job != "rookie":
            chain.append(job)
            job = SHIPS[job].parent or "rookie"
        for key in reversed(chain):
            level = SHIPS[key].level
            score = sum(self.game.cfg.level_xp_base + (n - 1) * self.game.cfg.level_xp_growth
                        for n in range(1, level))
            self.game._add_score(score - self.game.score)
            self.assertTrue(self.game.choose_reward(next(i for i, card in enumerate(self.game.reward_choices) if card.key == key)))

    def enemy(self, x, y, hp=100):
        enemy = Tank(self.game._new_id(), "enemy", x, y, hp, hp, self.game.cfg.tank_radius, 36)
        self.game.enemies.append(enemy)
        return enemy

    def wall_map(self, kind=WALL):
        tc = self.game.cfg.terrain
        tc.breakable_enabled = True
        tiles = [[EMPTY] * 60 for _ in range(45)]
        for row in range(45):
            tiles[row][14] = kind
        self.game.terrain = TileMap(tiles, 48, (2, 2), [], "test", tc)

    def burst(self, frames, hold=False):
        emitted = []
        for frame in range(frames):
            start = len(self.game.bullets)
            self.game._fire(self.game.player, hold or frame == 0)
            emitted.extend((frame, b) for b in self.game.bullets[start:])
            self.game.frame += 1
        return emitted

    def test_exact_three_stage_tree_has_21_ships(self):
        expected = {
            "rookie": {"twin", "sniper", "flank", "guardian"},
            "twin": {"dual_striker", "triple_wing"},
            "sniper": {"railgunner", "hunter"},
            "flank": {"quad_wing", "twin_flank"},
            "guardian": {"bastion", "aegis"},
            "dual_striker": {"gatling_storm"}, "triple_wing": {"penta_wing"},
            "railgunner": {"hyper_railgun"}, "hunter": {"predator"},
            "quad_wing": {"octa_star"}, "twin_flank": {"hexa_cruiser"},
            "bastion": {"colossus"}, "aegis": {"citadel"},
        }
        self.assertEqual(len(SHIPS), 21)
        for parent, children in expected.items():
            actual = {s.key for s in SHIPS.values() if (s.parent or "rookie") == parent and s.key != "rookie"}
            self.assertEqual(actual, children)
        for key in ("gatling_storm", "penta_wing", "hyper_railgun", "predator", "octa_star", "hexa_cruiser", "colossus", "citadel"):
            with self.subTest(key=key):
                self.setUp()
                self.evolve(key)
                self.assertEqual((self.game.level, self.game.player.job), (30, key))
                self.assertEqual(self.game.special_reward_levels, [])
                self.assertIsNone(self.game.active_skill)

    def test_bulk_xp_keeps_evolution_order_and_l40_mastery(self):
        game = self.game
        game._add_score(31980)
        self.assertEqual(game.special_reward_levels, [10, 20, 30, 40])
        self.assertEqual([card.key for card in game.reward_choices], ["twin", "sniper", "flank", "guardian"])
        self.assertTrue(game.choose_reward(3))
        self.assertEqual([card.key for card in game.reward_choices], ["bastion", "aegis"])
        self.assertTrue(game.choose_reward(1))
        self.assertEqual([card.key for card in game.reward_choices], ["citadel"])
        self.assertTrue(game.choose_reward(0))
        self.assertEqual(game.special_reward_levels, [40])
        hp, radius = game.player.max_hp, game.player.radius
        game.choose_reward(0)
        self.assertEqual(game.special_levels["citadel"], 2)
        self.assertEqual((game.player.max_hp, game.player.radius), (hp, radius))
        self.assertEqual(game.special_reward_levels, [])
        self.assertFalse(game.choose_reward(0))
        self.assertAlmostEqual(game.weapon_values(game.player)[1], game.cfg.bullet_damage * 0.5 * 1.2)

    def test_five_fixed_stats_show_at_zero_and_points_accumulate(self):
        game = self.game
        self.assertEqual([s.title for s in STAT_UPGRADES], ["체력", "공격력", "사거리 및 탄속도", "발사속도", "이동속도"])
        self.assertTrue(stat_upgrades_visible(game))
        self.assertEqual(game.stat_choices, STAT_UPGRADES)
        self.assertTrue(all(not game.can_upgrade_stat(s.key) for s in STAT_UPGRADES))
        game._add_score(190)
        for _ in range(40):
            game.step(0, want_fire=False)
        self.assertEqual(game.upgrade_points, 2)
        self.assertEqual(game.stat_choices, STAT_UPGRADES)
        game._add_score(1790)
        self.assertEqual((game.upgrade_points, game.special_reward_levels), (8, [10]))
        self.assertTrue(game.upgrade_stat("hull"))
        self.assertEqual(game.upgrade_points, 7)
        self.assertEqual(game.stat_choices, STAT_UPGRADES)
        rows = [rect for _, rect in stat_rows(960, 720)]
        self.assertEqual(len(rows), 5)
        self.assertTrue(all(y >= 0 and y + h <= 720 for x, y, w, h in rows))

    def test_twin_alternates_parallel_muzzles_after_trigger_release(self):
        self.evolve("twin")
        shots = self.burst(4)
        self.assertEqual([frame for frame, b in shots], [0, 3])
        first, second = [b for _, b in shots]
        self.assertEqual((first.vx, first.vy), (second.vx, second.vy))
        self.assertLess(first.y, 500)
        self.assertGreater(second.y, 500)
        self.assertEqual(self.game.player.ammo, 118)

    def test_dual_striker_uses_four_muzzles_in_sequence(self):
        self.evolve("dual_striker")
        shots = self.burst(7)
        self.assertEqual([frame for frame, b in shots], [0, 2, 4, 6])
        self.assertEqual(len({round(b.y, 3) for _, b in shots}), 4)
        self.assertTrue(all(b.vx > 0 and b.vy == 0 for _, b in shots))
        self.assertEqual(self.game.player.ammo, 116)

    def test_gatling_six_round_bursts_keep_firing_without_long_gaps(self):
        self.evolve("gatling_storm")
        shots = self.burst(33, hold=True)
        frames = [frame for frame, b in shots]
        self.assertEqual(frames[:6], [0, 2, 4, 6, 8, 10])
        # 묶음 안은 2프레임 간격, 묶음 사이에는 낮춘 발사 속도만큼 짧게 쉰다.
        self.assertGreaterEqual(len(frames), 12)
        self.assertLessEqual(max(b - a for a, b in zip(frames, frames[1:])), 6)
        self.assertTrue(all(b.vy == 0 and b.vx > 0 for _, b in shots))

    def test_fire_rate_upgrade_also_accelerates_gatling_burst(self):
        self.evolve("gatling_storm")
        baseline = len(self.burst(33, hold=True))
        self.setUp()
        self.evolve("gatling_storm")
        for _ in range(4):   # 1단계당 -5%라 몇 단계 올려야 차이가 보인다
            self.assertTrue(self.game.upgrade_stat("rapid"))
        boosted = len(self.burst(33, hold=True))
        self.assertGreater(boosted, baseline)

    def test_spread_ships_fire_three_and_five_simultaneous_directions(self):
        for job, count in (("triple_wing", 3), ("penta_wing", 5)):
            with self.subTest(job=job):
                self.setUp()
                self.evolve(job)
                shots = self.burst(1)
                self.assertEqual(len(shots), count)
                angles = [math.atan2(b.vy, b.vx) for _, b in shots]
                self.assertEqual(len(set(angles)), count)
                self.assertAlmostEqual(sum(angles), 0.0)
                self.assertTrue(all(b.vx > 0 for _, b in shots))

    def test_flank_family_directions_and_parallel_pairs(self):
        expected = {"flank": 2, "quad_wing": 4, "octa_star": 8, "twin_flank": 4, "hexa_cruiser": 6}
        for job, count in expected.items():
            with self.subTest(job=job):
                self.setUp()
                self.evolve(job)
                shots = self.burst(6)   # 헥사 크루저는 2프레임 간격 3쌍 순차 사격
                self.assertEqual(len(shots), count)
                vectors = [(round(b.vx, 4), round(b.vy, 4)) for _, b in shots]
                self.assertTrue(any(vx > 0 and vy == 0 for vx, vy in vectors))
                self.assertTrue(any(vx < 0 and vy == 0 for vx, vy in vectors))
                if job in ("quad_wing", "octa_star"):
                    self.assertTrue(any(vx == 0 and vy > 0 for vx, vy in vectors))
                    self.assertTrue(any(vx == 0 and vy < 0 for vx, vy in vectors))
                if job == "octa_star":
                    self.assertEqual(len(set(vectors)), 8)
                if job in ("twin_flank", "hexa_cruiser"):
                    front = [b for _, b in shots if b.vx > 0 and abs(b.vy) < 1e-7]
                    back = [b for _, b in shots if b.vx < 0 and abs(b.vy) < 1e-7]
                    barrels = 3 if job == "hexa_cruiser" else 2
                    self.assertEqual(len({round(b.y, 3) for b in front}), barrels)
                    self.assertEqual(len({round(b.y, 3) for b in back}), barrels)
                if job == "hexa_cruiser":  # 이미지에 측면 포신이 없으므로 앞/뒤로만 쏜다
                    self.assertTrue(all(abs(b.vy) < 1e-7 for _, b in shots))

    def test_hunter_and_predator_are_single_shot_snipers(self):
        values = []
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
                values.append((bullet.damage, bullet.vx, bullet.vx * bullet.life))
        self.assertTrue(all(a < b for a, b in zip(values[0], values[1])))

    def test_sniper_line_gains_damage_speed_and_range(self):
        values = []
        for job in ("sniper", "railgunner", "hyper_railgun"):
            self.setUp()
            self.evolve(job)
            self.game._fire(self.game.player, True)
            bullet = self.game.bullets[0]
            values.append((bullet.damage, bullet.vx, bullet.vx * bullet.life))
            self.assertEqual(self.game.beams, [])
        self.assertTrue(all(all(a[i] < b[i] for i in range(3)) for a, b in zip(values, values[1:])))

    def test_partial_magazine_never_creates_free_delayed_rounds(self):
        self.evolve("gatling_storm")
        self.game.player.ammo = 3
        shots = self.burst(20)
        self.assertEqual(len(shots), 3)
        self.assertEqual(self.game.player.ammo, 0)
        self.assertEqual(self.game.player.pending_shots, [])

    def test_reload_and_evolution_cancel_pending_rounds(self):
        self.evolve("twin")
        self.game._fire(self.game.player, True)
        self.assertEqual(len(self.game.player.pending_shots), 1)
        self.assertTrue(self.game.request_reload())
        self.assertEqual(self.game.player.pending_shots, [])
        self.burst(10)
        self.assertEqual(len(self.game.bullets), 1)
        self.setUp()
        self.evolve("twin")
        self.game._fire(self.game.player, True)
        self.game._add_score(7980 - self.game.score)
        self.game.choose_reward(0)
        self.assertEqual(self.game.player.pending_shots, [])

    def test_dead_player_and_reset_cancel_pending_rounds(self):
        self.evolve("gatling_storm")
        self.game._fire(self.game.player, True)
        self.assertTrue(self.game.player.pending_shots)
        self.game.player.hp = 0
        self.game.step(0, want_fire=False)
        self.assertTrue(self.game.game_over)
        self.assertEqual(self.game.player.pending_shots, [])
        self.game.reset(7)
        self.assertEqual(self.game.player.pending_shots, [])
        self.assertEqual(self.game.player.job, "rookie")

    def test_all_sniper_ships_hit_only_first_target(self):
        for job in ("sniper", "railgunner", "hyper_railgun", "hunter", "predator"):
            with self.subTest(job=job):
                self.setUp()
                self.evolve(job)
                first, second = self.enemy(600, 500), self.enemy(720, 500)
                self.game._fire(self.game.player, True)
                for _ in range(12):
                    self.game._move_bullets()
                self.assertLess(first.hp, 100)
                self.assertEqual(second.hp, 100)
                self.assertEqual(self.game.bullets, [])

    def test_fast_bullet_stops_at_breakable_wall(self):
        self.wall_map(BREAKABLE)
        far = self.enemy(800, 500)
        self.game.bullets = [Bullet(500, 500, 300, 0, 70, self.game.player.id, "player", 20, 5)]
        self.game._move_bullets()
        self.assertEqual(far.hp, 100)
        self.assertEqual(self.game.bullets, [])
        self.assertEqual(self.game.terrain.hp[(14, 10)], 20)

    def test_fast_bullet_hits_only_nearest_target(self):
        near, far = self.enemy(560, 500), self.enemy(620, 500)
        self.game.bullets = [Bullet(500, 500, 300, 0, 70, self.game.player.id, "player", 7, 6)]
        self.game._move_bullets()
        self.assertEqual((near.hp, far.hp), (93, 100))
        self.assertEqual(self.game.bullets, [])

    def test_last_projectile_step_still_hits_before_world_boundary(self):
        edge = self.game.cfg.world_width
        enemy = self.enemy(edge - 60, 500)
        self.game.bullets = [Bullet(edge - 100, 500, 300, 0, 1, self.game.player.id, "player", 7, 6)]
        self.game._move_bullets()
        self.assertEqual(enemy.hp, 93)
        self.assertEqual(self.game.bullets, [])

    def test_large_guardians_have_real_radius_health_and_small_guns(self):
        for job, radius, hp, count in (("guardian", 52, 200, 1), ("bastion", 80, 320, 2),
                                      ("aegis", 80, 300, 2), ("colossus", 92, 500, 3), ("citadel", 96, 540, 4)):
            with self.subTest(job=job):
                self.setUp()
                self.evolve(job)
                p = self.game.player
                self.assertAlmostEqual(p.radius, radius)
                self.assertEqual((p.hp, p.max_hp), (hp, hp))
                self.game._damage_tank(p, 10, False)
                self.assertAlmostEqual(p.hp, hp - 10 * SHIPS[job].damage_taken)
                self.game._fire(p, True)
                self.assertEqual(len(self.game.bullets), count)
                self.assertTrue(all(b.damage < self.game.cfg.bullet_damage for b in self.game.bullets))
                if job not in ("guardian", "bastion", "aegis"):  # 이 셋은 포신을 키웠다
                    self.assertTrue(all(b.radius < self.game.cfg.bullet_radius for b in self.game.bullets))
                self.assertTrue(all(math.hypot(b.x - p.x, b.y - p.y) > p.radius for b in self.game.bullets))

    def test_guardian_growth_preserves_hull_upgrades_and_damage(self):
        game = self.game
        game._add_score(190)
        game.upgrade_stat("hull")
        game.player.hp -= 30
        self.evolve("citadel")
        self.assertEqual((game.player.max_hp, game.player.hp), (565, 535))

    def test_evolving_next_to_wall_moves_large_ship_to_safe_space(self):
        self.wall_map()
        self.game.player.x, self.game.player.y = 627, 504
        self.assertTrue(self.game.terrain.circle_fits(627, 504, 44))
        self.evolve("guardian")
        p = self.game.player
        self.assertTrue(self.game.terrain.circle_fits(p.x, p.y, p.radius))
        self.assertNotEqual((p.x, p.y), (627, 504))

    def test_long_barrel_cannot_spawn_a_projectile_beyond_wall(self):
        self.evolve("hyper_railgun")
        self.wall_map()
        self.game.player.x, self.game.player.y = 627, 504
        far = self.enemy(800, 504)
        self.game._fire(self.game.player, True)
        self.assertLess(self.game.bullets[0].x, 672)
        for _ in range(5):
            self.game._move_bullets()
        self.assertEqual(far.hp, 100)
        self.assertEqual(self.game.bullets, [])

    def single_corner_wall(self):
        tiles = [[EMPTY] * 60 for _ in range(45)]
        tiles[10][10] = WALL
        self.game.terrain = TileMap(tiles, 48, (2, 2), [], "corner", self.game.cfg.terrain)

    def test_bullet_radius_blocks_diagonal_corner_at_normal_and_high_speed(self):
        self.single_corner_wall()
        for speed in (28.8, 100.0):
            with self.subTest(speed=speed):
                far = self.enemy(560, 612)
                self.game.bullets = [Bullet(450, 502, speed, speed, 70, self.game.player.id, "player", 7, 6)]
                self.game._move_bullets()
                self.assertEqual(self.game.bullets, [])
                self.assertEqual(far.hp, 100)

    def test_round_bullet_can_clear_corner_when_circle_does_not_touch(self):
        self.single_corner_wall()
        bullet = Bullet(450, 510, 100, 100, 70, self.game.player.id, "player", 7, 6)
        self.game.bullets = [bullet]
        self.game._move_bullets()
        self.assertEqual(self.game.bullets, [bullet])
        self.assertEqual((bullet.x, bullet.y), (550, 610))

    def test_long_muzzle_respects_bullet_radius_near_wall_corner(self):
        self.evolve("hyper_railgun")
        self.single_corner_wall()
        self.game.player.x, self.game.player.y, self.game.player.angle = 430, 482, math.pi/4
        self.game._fire(self.game.player, True)
        bullet = self.game.bullets[0]
        self.assertTrue(self.game.terrain.circle_fits(bullet.x, bullet.y, bullet.radius))
        self.game._move_bullets()
        self.assertEqual(self.game.bullets, [])

    def test_measured_long_muzzle_does_not_skip_nearby_experience_object(self):
        self.evolve("hyper_railgun")
        shape = Shape(self.game._new_id(), "square", 558, 500, 0, 0, 100, 100, 14, 10)
        self.game.shapes = [shape]
        self.game._fire(self.game.player, True)
        self.assertEqual(shape.hp, 70.25)
        self.assertEqual(self.game.bullets, [])
        self.assertEqual(self.game.player.ammo, 119)
        self.game._move_bullets()
        self.assertEqual(shape.hp, 70.25)

    def test_projectile_collision_width_matches_measured_gun_opening(self):
        # 원본 512px PNG 포신 안쪽의 밝은 회색 부분을 실측한 픽셀 폭이다.
        for job, hull, opening in (("rookie", 139, 26), ("twin", 136, 22),
                                   ("hunter", 174, 19), ("citadel", 290, 10)):
            with self.subTest(job=job):
                self.setUp()
                self.evolve(job)
                self.game._fire(self.game.player, True)
                bullet = self.game.bullets[0]
                gun_width = 2 * self.game.player.radius * opening / hull
                self.assertAlmostEqual(2 * bullet.radius, gun_width * 0.9)
                self.assertLess(2 * bullet.radius, gun_width)

    def test_basic_and_all_enemy_collision_radii_are_doubled(self):
        cfg = GameConfig(num_shapes=0, num_enemies=3, tank_radius=44)
        cfg.terrain.enabled = False
        game = GameCore(cfg, seed=7)
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
                    self.game._fire(enemy, True)
                    self.game.frame += 1
                self.assertEqual(len(self.game.bullets), len(spec.shots))
                for bullet in self.game.bullets:
                    self.assertEqual(bullet.team, "enemy")
                    self.assertTrue(any(abs(bullet.radius - enemy.radius * shot.caliber) < 1e-9 for shot in spec.shots))

    def test_q_and_space_no_longer_activate_skills_or_dash(self):
        self.evolve("citadel")
        self.assertEqual(SKILLS, {})
        self.assertFalse(self.game.request_skill(3))
        self.game.step(0, want_fire=False, want_skill=True, want_dash=True)
        self.assertEqual((self.game.skill_cooldown, self.game.dash_frames_left), (0, 0))
        self.assertEqual(self.game.bullets, [])
        self.assertIsNone(self.game.active_skill)


if __name__ == "__main__":
    unittest.main()
