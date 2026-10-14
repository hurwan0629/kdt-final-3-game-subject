"""능력치 목록 표시 조건과 Tab 유지 입력, 실제 전직 수치 검증."""
import os
import unittest
from collections import defaultdict
from unittest.mock import patch

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import pygame

from config import GameConfig, ObsConfig
from game_core import GameCore
from main import GameApplication
from progression import player_stat_summary, stat_rows, stat_upgrades_visible
from renderer import Renderer


class StatsPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()
        cfg = GameConfig(num_enemies=0, num_shapes=0)
        cfg.terrain.enabled = False
        cls.renderer = Renderer(cfg)

    @classmethod
    def tearDownClass(cls):
        pygame.quit()

    def setUp(self):
        self.game = GameCore(self.renderer.cfg, seed=7)
        self.app = GameApplication(self.game, self.renderer)
        self.app.activate("start")
        self.keys = defaultdict(bool)

    def update(self, elapsed=0, buttons=(False, False, False), pos=(800, 360)):
        self.app.update(elapsed, self.keys, pos, buttons)

    def test_tab_hold_release_without_simulation_tick_and_no_pause(self):
        with patch.object(self.renderer, "_draw_stats_panel", wraps=self.renderer._draw_stats_panel) as panel:
            self.update()
            self.app.draw(ObsConfig())
            panel.assert_not_called()
            self.keys[pygame.K_TAB] = True
            self.keys[pygame.K_d] = True
            x = self.game.player.x
            self.update(1 / 60, (True, False, False))
            self.app.draw(ObsConfig())
            panel.assert_called_once_with(self.game)
            self.assertEqual(self.game.frame, 1)
            self.assertGreater(self.game.player.x, x)
            self.assertEqual(self.game.player.ammo, 119)
            self.keys[pygame.K_TAB] = False
            self.update()
            self.app.draw(ObsConfig())
            self.assertFalse(self.app.show_stats)
            self.assertEqual(panel.call_count, 1)

    def test_upgrade_list_only_while_points_remain(self):
        with patch.object(self.renderer, "_draw_stat_upgrades", wraps=self.renderer._draw_stat_upgrades) as rows:
            self.renderer.draw(self.game)
            rows.assert_not_called()
            self.game._add_score(60)
            self.assertTrue(stat_upgrades_visible(self.game))
            self.renderer.draw(self.game)
            rows.assert_called_once_with(self.game)
            self.game.upgrade_stat("hull")
            self.assertFalse(stat_upgrades_visible(self.game))
            self.renderer.draw(self.game)
            self.assertEqual(rows.call_count, 1)
            self.game._add_score(100)
            self.renderer.draw(self.game)
            self.assertEqual(rows.call_count, 2)

    def test_hidden_upgrade_rows_allow_mouse_firing(self):
        pos = pygame.Rect(stat_rows(960, 720)[0][1]).center
        self.update()
        self.assertFalse(self.app.pointer_over_rewards(pos))
        self.app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=pos))
        self.update(1 / 60, (True, False, False), pos)
        self.assertEqual(self.game.player.ammo, 119)
        self.game._add_score(60)
        self.assertTrue(self.app.pointer_over_rewards(pos))
        self.app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=pos))
        self.update(1 / 60, (True, False, False), pos)
        self.assertEqual(self.game.stat_levels["regen"], 1)
        self.assertEqual(self.game.player.ammo, 119)
        self.assertFalse(self.app.pointer_over_rewards(pos))

    def test_tab_in_menus_still_navigates_and_never_shows_panel(self):
        self.keys[pygame.K_TAB] = True
        self.update()
        self.assertTrue(self.app.show_stats)
        self.app.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE))
        selected = self.app.selected
        self.app.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_TAB))
        self.assertNotEqual(self.app.selected, selected)
        self.update()
        self.assertFalse(self.app.show_stats)
        self.app.activate("main")
        self.update()
        self.assertFalse(self.app.show_stats)
        self.app.activate("start")
        self.game.game_over = True
        self.update()
        self.assertFalse(self.app.show_stats)

    def test_displayed_stats_match_upgrades_and_actual_weapon_shots(self):
        game = self.game
        game.upgrade_points = 8
        for key in game.stat_levels:
            game.upgrade_stat(key)
        stats = dict(player_stat_summary(game))
        self.assertEqual(stats["선체 내구도"], "125 / 125")
        self.assertEqual(stats["자가 수리"], "4.5 / 초")
        self.assertEqual(stats["탄창"], "140 / 140")
        self.assertEqual(stats["재장전 시간"], "2.25초")
        for weapon in ("rookie", "gunner", "cannon", "laser"):
            with self.subTest(weapon=weapon):
                game.player.job = weapon
                game.player.projectiles = 3 if weapon == "gunner" else 1
                game.special_levels[weapon] = 2
                game.player.cooldown = 0
                game.bullets.clear()
                stats = dict(player_stat_summary(game))
                with patch.object(game, "_fire_laser") as laser:
                    game._fire(game.player, True)
                damage = laser.call_args.args[1] if weapon == "laser" else game.bullets[0].damage
                self.assertEqual(stats["주무기 피해 · 1발"], f"{damage:.2f}")
                self.assertEqual(stats["발사 간격"], f"{(game.player.cooldown + 1) / game.cfg.fps:.2f}초")
                if weapon == "laser":
                    self.assertEqual(stats["탄속"], "즉시 명중")
                else:
                    bullet = game.bullets[0]
                    speed = (bullet.vx ** 2 + bullet.vy ** 2) ** 0.5
                    self.assertEqual(stats["탄속"], f"{speed * game.cfg.fps:.0f} px / 초")
                    self.assertEqual(stats["사거리"], f"{speed * bullet.life:.0f} px")


if __name__ == "__main__":
    unittest.main()
