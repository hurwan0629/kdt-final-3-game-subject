"""전직 무기·폭탄·대시·빠른 충돌 및 HUD 선택의 회귀 검증."""
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
from progression import SPECIAL_REWARDS, special_cards, stat_rows
from renderer import Renderer
from terrain import TileMap, EMPTY, WALL, BREAKABLE


class WeaponsSkillsTests(unittest.TestCase):
    def setUp(self):
        cfg = GameConfig(num_enemies=0, num_shapes=0)
        cfg.terrain.enabled = False
        self.game = GameCore(cfg, seed=7)
        self.game.player.x, self.game.player.y, self.game.player.angle = 100, 100, 0
        self.game._enemy_ai = lambda enemy: None  # 피격 대상이 움직이지 않게 해 무기만 검증

    def grant(self, key):
        game = self.game
        game.special_reward_levels = [10]
        game.reward_choices = (next(card for card in SPECIAL_REWARDS if card.key == key),)
        self.assertTrue(game.choose_reward(0))

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

    def test_laser_pierces_targets_and_consumes_one_round(self):
        self.grant("laser")
        near = self.enemy(200, 100)
        far = self.enemy(350, 100)
        shape = Shape(91, "pentagon", 450, 100, 0, 0, 100, 100, 26, 130)
        self.game.shapes.append(shape)
        self.game._fire(self.game.player, True)
        self.assertEqual(self.game.player.ammo, 119)
        self.assertEqual(len(self.game.beams), 1)
        self.assertEqual(self.game.bullets, [])
        for target in (near, far, shape):
            self.assertAlmostEqual(target.hp, 100 - 7 * 1.4)
        self.game._fire(self.game.player, True)
        self.assertEqual(self.game.player.ammo, 119)

    def test_laser_stops_at_wall_and_can_damage_breakable_wall(self):
        self.wall_map(BREAKABLE)
        self.grant("laser")
        near = self.enemy(150, 100)
        hidden = self.enemy(270, 100)
        self.game._fire(self.game.player, True)
        self.assertLess(near.hp, 100)
        self.assertEqual(hidden.hp, 100)
        self.assertAlmostEqual(self.game.beams[0].end_x, 192)
        self.assertLess(self.game.terrain.hp[(4, 2)], 40)

    def test_triple_weapon_mastery_and_weapon_switch_do_not_erase_stats_or_skills(self):
        self.grant("gunner")
        self.game._fire(self.game.player, True)
        self.assertEqual((len(self.game.bullets), self.game.player.ammo), (3, 117))
        self.assertAlmostEqual(self.game.bullets[0].damage, 5.6)
        self.grant("bomb")
        self.game.upgrade_points = 1
        self.game.upgrade_stat("damage")
        self.grant("gunner")
        self.game.player.cooldown = 0
        self.game.bullets.clear()
        self.game._fire(self.game.player, True)
        self.assertAlmostEqual(self.game.bullets[0].damage, 7 * 1.25 * 0.8 * 1.2)
        self.grant("cannon")
        self.assertEqual(self.game.player.projectiles, 1)
        self.assertEqual(self.game.player.damage_scale, 1.25)
        self.assertEqual(self.game.special_levels["bomb"], 1)

    def test_cannon_explodes_once_and_damages_nearby_targets(self):
        self.grant("cannon")
        direct = self.enemy(200, 100)
        nearby = self.enemy(215, 150)
        self.game._fire(self.game.player, True)
        bullet = self.game.bullets[0]
        self.assertEqual((bullet.damage, bullet.blast_radius, bullet.radius), (28, 90, 10))
        for _ in range(20):
            self.game._move_bullets()
            self.game._collide_bullets()
            if not self.game.bullets:
                break
        self.assertEqual(len(self.game.explosions), 1)
        self.assertGreaterEqual(direct.hp, 72)  # 직격과 범위 피해를 중복 적용하지 않음
        self.assertLess(direct.hp, 100)
        self.assertLess(nearby.hp, 100)
        self.assertEqual(self.game.player.hp, 100)

    def test_bomb_fuse_cooldown_no_ammo_and_rank_upgrade(self):
        self.assertFalse(self.game.request_bomb())
        self.grant("bomb")
        enemy = self.enemy(290, 100)
        self.assertTrue(self.game.request_bomb())
        self.assertFalse(self.game.request_bomb())
        for _ in range(59):
            self.game.step(0, want_fire=False)
        self.assertEqual(len(self.game.bombs), 1)
        self.game.step(0, want_fire=False)
        self.assertEqual(self.game.bombs, [])
        self.assertLess(enemy.hp, 100)
        self.assertEqual(self.game.player.ammo, 120)
        self.assertGreater(self.game.bomb_cooldown, 0)
        self.grant("bomb")
        self.game.bomb_cooldown = 0
        self.game.request_bomb()
        self.assertAlmostEqual(self.game.bombs[0].damage, 45 * 1.25)

    def test_dash_movement_short_invulnerability_and_cooldown(self):
        self.assertFalse(self.game.request_dash(3))
        self.grant("dash")
        self.assertTrue(self.game.request_dash(3))
        self.assertFalse(self.game.request_dash(3))
        self.game._damage_tank(self.game.player, 10, False)
        self.assertEqual(self.game.player.hp, 100)
        start = self.game.player.x
        for _ in range(12):
            self.game.step(9, want_fire=False)
        self.assertGreater(self.game.player.x - start, 100)
        self.assertEqual(self.game.dash_frames_left, 0)
        self.assertGreater(self.game.dash_cooldown, 0)
        self.game._damage_tank(self.game.player, 10, False)
        self.assertEqual(self.game.player.hp, 90)
        self.grant("dash")
        self.game.dash_cooldown = 0
        self.game.request_dash(0, (self.game.player.x, self.game.player.y - 100))
        self.assertEqual(self.game.dash_direction, (0, -1))
        self.assertEqual(self.game.dash_cooldown, 204)

    def test_dash_and_fast_bullets_cannot_cross_wall(self):
        self.wall_map()
        self.grant("dash")
        self.game.player.x = 160
        self.game.request_dash(3)
        for _ in range(12):
            self.game.step(9, want_fire=False)
        self.assertLessEqual(self.game.player.x, 192 - self.game.player.radius)
        behind = self.enemy(300, 100)
        self.game.bullets = [Bullet(100, 100, 250, 0, 70, self.game.player.id, "player", 7, 6)]
        self.game._move_bullets()
        self.assertEqual(self.game.bullets, [])
        self.assertEqual(behind.hp, 100)

    def test_fast_bullet_hits_nearest_target_before_wall(self):
        self.wall_map()
        near = self.enemy(145, 100)
        far = self.enemy(175, 100)
        self.game.bullets = [Bullet(100, 100, 250, 0, 70, self.game.player.id, "player", 7, 6)]
        self.game._move_bullets()
        self.assertEqual(near.hp, 93)
        self.assertEqual(far.hp, 100)

    def test_live_clicks_choose_stat_and_special_without_firing(self):
        renderer = object.__new__(Renderer)
        renderer.cfg = self.game.cfg
        renderer.view_width, renderer.view_height = 1600, 1200
        renderer._update_camera(self.game.player)
        app = GameApplication(self.game, renderer, seed=7)
        app.mode, app.suppress_fire = "playing", False
        self.game._add_score(1980)
        points = self.game.upgrade_points
        row = pygame.Rect(stat_rows(960, 720)[4][1])
        app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=row.center))
        app.update(1 / 60, defaultdict(bool), row.center, (True, False, False))
        self.assertEqual(self.game.upgrade_points, points - 1)
        self.assertEqual((self.game.player.max_ammo, self.game.player.ammo), (140, 140))
        self.assertEqual(self.game.bullets, [])
        choice = self.game.reward_choices[0].key
        rect = pygame.Rect(special_cards(960, 720)[0])
        app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=rect.center))
        app.update(1 / 60, defaultdict(bool), rect.center, (True, False, False))
        self.assertEqual(self.game.special_levels[choice], 1)
        self.assertEqual(self.game.special_reward_levels, [])
        self.assertEqual(self.game.player.ammo, 140)

    def test_pause_freezes_skills_and_reloading_while_live_selection_does_not(self):
        renderer = object.__new__(Renderer)
        renderer.cfg = self.game.cfg
        renderer.view_width, renderer.view_height = 1600, 1200
        renderer._update_camera(self.game.player)
        app = GameApplication(self.game, renderer)
        self.grant("bomb")
        self.grant("dash")
        self.game.player.ammo = 0
        self.game.request_reload()
        self.game.request_bomb()
        self.game.request_dash(3)
        state = (self.game.bomb_cooldown, self.game.dash_cooldown, self.game.reload_frames_left)
        app.mode = "pause"
        app.update(100, defaultdict(bool), (480, 360), (False, False, False))
        self.assertEqual((self.game.bomb_cooldown, self.game.dash_cooldown, self.game.reload_frames_left), state)
        app.mode = "playing"
        app.update(1 / 60, defaultdict(bool), (480, 360), (False, False, False))
        self.assertEqual(self.game.reload_frames_left, 149)

    def test_upgrading_active_reload_and_cannon_cooldown_preserves_progress(self):
        self.grant("cannon")
        game = self.game
        game.player.ammo = 0
        game.request_reload()
        for _ in range(50):
            game.step(0, want_fire=False)
        self.assertEqual(game.reload_frames_left, 100)
        game.player.cooldown = 40
        game.upgrade_points = 2
        game.upgrade_stat("rapid")
        self.assertEqual((game.player.fire_cooldown_max, game.player.cooldown), (17, 34))
        game.upgrade_stat("reload")
        self.assertEqual((game.reload_frames_total, game.reload_frames_left), (135, 90))
        self.assertEqual(game.upgrade_points, 0)

    def test_keyboard_q_and_space_activate_unlocked_skills(self):
        self.grant("bomb")
        self.grant("dash")
        renderer = object.__new__(Renderer)
        renderer.cfg = self.game.cfg
        renderer.view_width, renderer.view_height = 1600, 1200
        renderer._update_camera(self.game.player)
        app = GameApplication(self.game, renderer)
        app.mode = "playing"
        for key in (pygame.K_q, pygame.K_SPACE):
            app.handle_event(pygame.event.Event(pygame.KEYDOWN, key=key))
        app.update(1 / 60, defaultdict(bool), (800, 360), (False, False, False))
        self.assertEqual(len(self.game.bombs), 1)
        self.assertEqual(self.game.dash_frames_left, 11)
        self.assertEqual(self.game.player.ammo, 120)
        self.assertGreater(self.game.player.x, 100)


if __name__ == "__main__":
    unittest.main()
