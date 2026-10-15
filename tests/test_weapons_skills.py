"""전직 트리의 선택 순서, 무기, 8개 고유 스킬과 충돌 검증."""
import math
import os
import unittest
from collections import defaultdict

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import pygame

from config import GameConfig
from game_core import Bullet, GameCore, Shape, Tank
from main import GameApplication
from progression import SHIPS, SKILLS, stat_rows, special_cards
from renderer import Renderer
from terrain import TileMap, EMPTY, WALL, BREAKABLE


class WeaponsSkillsTests(unittest.TestCase):
    def setUp(self):
        cfg = GameConfig(num_enemies=0, num_shapes=0)
        cfg.terrain.enabled = False
        self.game = GameCore(cfg, seed=7)
        self.game.player.x, self.game.player.y, self.game.player.angle = 100, 100, 0
        self.game._enemy_ai = lambda enemy: None

    def evolve(self, job, unlock=False):
        game = self.game
        family = SHIPS[job].parent or job
        game._add_score(1980 - game.score)
        game.choose_reward(next(i for i, card in enumerate(game.reward_choices) if card.key == family))
        if SHIPS[job].parent:
            game._add_score(7980 - game.score)
            game.choose_reward(next(i for i, card in enumerate(game.reward_choices) if card.key == job))
        if unlock:
            game._add_score(17980 - game.score)

    def enemy(self, x, y, hp=100):
        enemy = Tank(len(self.game.enemies) + 20, "enemy", x, y, hp, hp, 22, 36)
        self.game.enemies.append(enemy)
        return enemy

    def wall_map(self, kind=WALL):
        tc = self.game.cfg.terrain
        tc.breakable_enabled = True
        tiles = [[EMPTY] * 60 for _ in range(45)]
        for row in range(45):
            tiles[row][4] = kind
        self.game.terrain = TileMap(tiles, 48, (2, 2), [], "test", tc)

    def app(self):
        renderer = object.__new__(Renderer)
        renderer.cfg = self.game.cfg
        renderer.screen = pygame.Surface((960, 720))
        renderer.view_width, renderer.view_height = 1600, 1200
        renderer._update_camera(self.game.player)
        app = GameApplication(self.game, renderer)
        app.mode, app.suppress_fire = "playing", False
        return app

    def test_bulk_xp_preserves_order_and_unlocks_only_matching_skill(self):
        game = self.game
        game._add_score(31980)
        self.assertEqual(game.special_reward_levels, [10, 20, 30, 40])
        self.assertEqual([card.key for card in game.reward_choices], ["twin", "sniper", "gatling", "guardian"])
        game.choose_reward(1)
        self.assertEqual([card.key for card in game.reward_choices], ["railgun", "minelayer"])
        self.assertIsNone(game.active_skill)
        points = game.upgrade_points
        game.upgrade_stat("damage")
        game.choose_reward(1)
        self.assertEqual(game.player.job, "minelayer")
        self.assertEqual(game.active_skill.key, "detonate")
        self.assertEqual(game.special_reward_levels, [40])
        self.assertEqual([card.key for card in game.reward_choices], ["minelayer"])
        game.choose_reward(0)
        self.assertEqual(game.special_levels["minelayer"], 2)
        self.assertEqual(game.upgrade_points, points - 1)
        self.assertEqual(game.player.damage_scale, 1.25)
        self.assertFalse(game.choose_reward(0))
        game.reset(7)
        self.assertEqual((game.family, game.player.job, game.active_skill), ("", "rookie", None))

    def test_all_evolutions_follow_their_family_and_unlock_at_30(self):
        for job in SKILLS:
            with self.subTest(job=job):
                self.setUp()
                self.evolve(job)
                self.assertEqual(self.game.player.job, job)
                self.assertEqual(self.game.family, SHIPS[job].parent)
                self.assertIsNone(self.game.active_skill)
                self.game._add_score(17980 - self.game.score)
                self.assertEqual(self.game.active_skill, SKILLS[job])
                self.assertEqual(self.game.special_reward_levels, [])

    def test_multishot_patterns_and_partial_magazine(self):
        for job, count in (("twin", 2), ("triple", 3), ("cross", 4), ("shotgun", 6)):
            with self.subTest(job=job):
                self.setUp()
                self.evolve(job)
                self.game._fire(self.game.player, True)
                self.assertEqual(len(self.game.bullets), count)
                self.assertEqual(self.game.player.ammo, 120 - count)
                if job == "twin":
                    self.assertEqual(self.game.bullets[0].vx, self.game.bullets[1].vx)
                    self.assertNotEqual(self.game.bullets[0].y, self.game.bullets[1].y)
                if job == "cross":
                    self.assertEqual({(round(b.vx), round(b.vy)) for b in self.game.bullets},
                                     {(9, 0), (0, 9), (-9, 0), (0, -9)})
                self.game.player.cooldown = 0
                self.game.player.ammo = 2
                self.game.bullets.clear()
                self.game._fire(self.game.player, True)
                self.assertEqual((len(self.game.bullets), self.game.player.ammo), (2, 0))

    def test_sniper_damage_speed_and_gatling_fire_rate(self):
        self.evolve("sniper")
        self.game._fire(self.game.player, True)
        self.assertEqual(self.game.bullets[0].damage, 17.5)
        self.assertAlmostEqual(self.game.bullets[0].vx, 16.2)
        self.assertEqual(self.game.player.cooldown, 34)
        self.setUp()
        self.evolve("gatling")
        self.game._fire(self.game.player, True)
        self.assertEqual(self.game.player.cooldown, 7)

    def test_railgun_pierces_all_targets_but_stops_at_wall(self):
        self.evolve("railgun")
        near, far = self.enemy(150, 100), self.enemy(350, 100)
        self.game._fire(self.game.player, True)
        self.assertEqual((near.hp, far.hp), (75.5, 75.5))
        self.assertEqual(self.game.player.ammo, 119)
        self.assertEqual(len(self.game.beams), 1)
        self.wall_map(BREAKABLE)
        self.game.player.cooldown = 0
        self.game._fire(self.game.player, True)
        self.assertEqual((near.hp, far.hp), (51, 75.5))
        self.assertAlmostEqual(self.game.beams[-1].end_x, 192)
        self.assertLess(self.game.terrain.hp[(4, 2)], 40)

    def test_mines_stop_then_detonate_once_without_spending_ammo(self):
        self.evolve("minelayer", unlock=True)
        game = self.game
        game._fire(game.player, True)
        for _ in range(20):
            game._move_bullets()
        mine = game.bullets[0]
        self.assertEqual((mine.vx, mine.vy, mine.arming_frames), (0, 0, 0))
        target = self.enemy(mine.x + 30, mine.y)
        ammo = game.player.ammo
        self.assertTrue(game.request_skill())
        self.assertFalse(game.request_skill())
        self.assertEqual(game.bullets, [])
        self.assertLess(target.hp, 100)
        self.assertEqual(len(game.explosions), 1)
        self.assertEqual(game.player.ammo, ammo)

    def test_homing_missile_turns_toward_enemy(self):
        self.evolve("homing")
        target = self.enemy(300, 240)
        self.game._fire(self.game.player, True)
        bullet = self.game.bullets[0]
        self.assertTrue(bullet.homing)
        speed = math.hypot(bullet.vx, bullet.vy)
        self.game._move_bullets()
        self.assertGreater(bullet.vy, 0)
        self.assertAlmostEqual(math.hypot(bullet.vx, bullet.vy), speed)
        target.alive = False
        self.game._move_bullets()

    def test_guardian_resists_damage_booster_recoils_ram_has_no_gun(self):
        self.evolve("booster")
        game = self.game
        self.assertEqual(game.player.max_hp, 150)
        game._damage_tank(game.player, 10, False)
        self.assertEqual(game.player.hp, 143.5)
        game._fire(game.player, True)
        self.assertEqual(len(game.bullets), 3)
        self.assertGreater(game.player.vx, 0)
        self.setUp()
        self.evolve("ram")
        game = self.game
        target = self.enemy(130, 100)
        game._fire(game.player, True)
        self.assertEqual(game.bullets, [])
        self.assertEqual(game.player.ammo, 120)
        game._collide_bodies()
        self.assertAlmostEqual(target.hp, 95.2)
        self.assertAlmostEqual(game.player.hp, 150 - 0.6 * 0.35)

    def test_barrage_turret_and_salvo_actually_fire(self):
        for job, minimum in (("triple", 20), ("cross", 4), ("homing", 8)):
            with self.subTest(job=job):
                self.setUp()
                self.evolve(job, unlock=True)
                self.assertTrue(self.game.request_skill())
                if job == "cross":
                    self.game._tick_skill()
                self.assertGreaterEqual(len(self.game.bullets), minimum)
                self.assertEqual(self.game.player.ammo, 120)
                self.assertFalse(self.game.request_skill())

    def test_charge_waits_before_beam_and_overload_expires(self):
        self.evolve("railgun", unlock=True)
        target = self.enemy(300, 100, hp=500)
        self.game.request_skill()
        for _ in range(44):
            self.game.step(0, want_fire=False)
        self.assertEqual(target.hp, 500)
        self.game.step(0, want_fire=False)
        self.assertAlmostEqual(target.hp, 500 - 24.5 * 5)
        self.setUp()
        self.evolve("shotgun", unlock=True)
        normal = self.game.weapon_values(self.game.player)
        self.game.request_skill()
        boosted = self.game.weapon_values(self.game.player)
        self.assertGreater(boosted[1], normal[1])
        self.assertLess(boosted[2], normal[2])
        for _ in range(300):
            self.game._tick_skill()
        self.assertEqual(self.game.weapon_values(self.game.player), normal)

    def test_dash_skills_are_invulnerable_and_cannot_cross_walls(self):
        for job in ("booster", "ram"):
            with self.subTest(job=job):
                self.setUp()
                self.evolve(job, unlock=True)
                self.wall_map()
                self.game.player.x = 150
                self.assertTrue(self.game.request_skill(3))
                hp = self.game.player.hp
                self.game._damage_tank(self.game.player, 20, False)
                self.assertEqual(self.game.player.hp, hp)
                for _ in range(30):
                    self.game.step(9, want_fire=False)
                self.assertLessEqual(self.game.player.x, 192 - self.game.player.radius)
                self.assertEqual(self.game.dash_frames_left, 0)

    def test_fast_bullet_hits_nearest_target_before_wall(self):
        self.wall_map()
        near, far = self.enemy(145, 100), self.enemy(175, 100)
        self.game.bullets = [Bullet(100, 100, 250, 0, 70, self.game.player.id, "player", 7, 6)]
        self.game._move_bullets()
        self.assertEqual((near.hp, far.hp), (93, 100))
        self.assertEqual(self.game.bullets, [])

    def test_live_clicks_select_displayed_stat_and_fourth_ship_without_firing(self):
        game = self.game
        game._add_score(1980)
        app = self.app()
        key = game.stat_choices[0].key
        rect = pygame.Rect(stat_rows(960, 720, game.stat_choices)[0][1])
        points = game.upgrade_points
        app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=rect.center))
        app.update(1 / 60, defaultdict(bool), rect.center, (True, False, False))
        self.assertEqual(game.stat_levels[key], 1)
        self.assertEqual(game.upgrade_points, points - 1)
        rect = pygame.Rect(special_cards(960, 720)[3])
        app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=rect.center))
        app.update(1 / 60, defaultdict(bool), rect.center, (True, False, False))
        self.assertEqual(game.player.job, "guardian")
        self.assertEqual(game.player.ammo, 120)
        self.assertEqual(game.bullets, [])

    def test_pause_freezes_active_skill_charge_and_reload(self):
        self.evolve("railgun", unlock=True)
        game = self.game
        game.player.ammo = 0
        game.request_reload()
        game.request_skill()
        app = self.app()
        app.mode = "pause"
        state = (game.skill_cooldown, game.charge_frames_left, game.reload_frames_left)
        app.update(100, defaultdict(bool), (800, 360), (False, False, False))
        self.assertEqual((game.skill_cooldown, game.charge_frames_left, game.reload_frames_left), state)
        app.mode = "playing"
        app.update(1 / 60, defaultdict(bool), (800, 360), (False, False, False))
        self.assertEqual(game.reload_frames_left, 149)
        self.assertEqual(game.charge_frames_left, 44)

    def test_q_and_space_activate_matching_skill(self):
        for job, key in (("triple", pygame.K_q), ("booster", pygame.K_SPACE)):
            with self.subTest(job=job):
                self.setUp()
                self.evolve(job, unlock=True)
                app = self.app()
                app.handle_event(pygame.event.Event(pygame.KEYDOWN, key=key))
                app.update(1 / 60, defaultdict(bool), (800, 360), (False, False, False))
                self.assertGreater(self.game.skill_cooldown, 0)


if __name__ == "__main__":
    unittest.main()
