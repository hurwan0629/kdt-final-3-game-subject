"""능력치 목록 표시 조건과 Tab 유지 입력, 실제 전직 수치 검증."""

import os
import unittest
from collections import defaultdict
from unittest.mock import patch

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import pygame

from space_z.config import GameConfig, ObsConfig
from space_z.game.game_core import GameCore
from space_z.app import GameApplication
from space_z.rendering.progression_panel import (
    build_player_stat_summary,
    build_stat_upgrade_rows,
    can_show_stat_upgrades,
)
from space_z.rendering.renderer import Renderer


class StatsPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        pygame.init()
        config = GameConfig(num_enemies=0, num_shapes=0)
        config.window_width, config.window_height = 960, 720
        config.terrain.enabled = False
        cls.renderer = Renderer(config)

    @classmethod
    def tearDownClass(cls):
        pygame.quit()

    def setUp(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        self.game = GameCore(self.renderer.config, seed=7)
        self.application = GameApplication(self.game, self.renderer, seed=7)
        self.application.activate_menu_action("start")
        self.keys = defaultdict(bool)

    def update(self, elapsed=0, buttons=(False, False, False), position=(800, 360)):
        self.application.update(elapsed, self.keys, position, buttons)

    def test_tab_hold_release_without_simulation_tick_and_no_pause(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        with patch.object(
            self.renderer, "_draw_stats_panel", wraps=self.renderer._draw_stats_panel
        ) as panel:
            self.update()
            self.application.draw(ObsConfig())
            panel.assert_not_called()
            self.keys[pygame.K_TAB] = True
            self.keys[pygame.K_d] = True
            x = self.game.player.x
            self.update(1 / 60, (True, False, False))
            self.application.draw(ObsConfig())
            panel.assert_called_once_with(self.game)
            self.assertEqual(self.game.frame, 1)
            self.assertGreater(self.game.player.x, x)
            self.assertEqual(self.game.player.ammo, 119)
            self.keys[pygame.K_TAB] = False
            self.update()
            self.application.draw(ObsConfig())
            self.assertFalse(self.application.show_stats)
            self.assertEqual(panel.call_count, 1)

    def test_five_upgrade_rows_remain_visible_without_points_and_points_accumulate(
        self,
    ):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        with patch.object(
            self.renderer,
            "_draw_stat_upgrades",
            wraps=self.renderer._draw_stat_upgrades,
        ) as rows:
            self.assertTrue(can_show_stat_upgrades(self.game))
            self.assertEqual(len(self.game.progression.stat_choices), 5)
            self.assertFalse(
                any(
                    self.game.progression.can_upgrade_stat(card.key)
                    for card in self.game.progression.stat_choices
                )
            )
            self.renderer.draw(self.game)
            rows.assert_called_once_with(self.game)
            self.game.progression._add_score(190)
            self.assertEqual(self.game.progression.upgrade_points, 2)
            self.assertTrue(self.game.progression.upgrade_stat("health"))
            self.assertEqual(self.game.progression.upgrade_points, 1)
            self.assertTrue(self.game.progression.upgrade_stat("damage"))
            self.assertEqual(self.game.progression.upgrade_points, 0)
            self.renderer.draw(self.game)
            self.assertEqual(rows.call_count, 2)
            self.assertEqual(len(self.game.progression.stat_choices), 5)
            self.assertFalse(self.game.progression.upgrade_stat("speed"))

    def test_inactive_stat_rows_block_firing_and_clicks_spend_one_point(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        position = pygame.Rect(build_stat_upgrade_rows(960, 720)[0][1]).center
        self.update()

        # 강화 불가 행도 발사를 막고 유효한 클릭은 포인트 하나만 소비하는지 확인한다.
        self.assertTrue(self.application.pointer_over_rewards(position))
        self.application.handle_event(
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=position)
        )
        self.update(1 / 60, (True, False, False), position)
        self.assertEqual(self.game.player.ammo, 120)
        self.assertEqual(self.game.progression.stat_levels["health"], 0)
        self.game.progression._add_score(60)
        self.application.handle_event(
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=position)
        )
        self.update(1 / 60, (True, False, False), position)
        self.assertEqual(self.game.progression.stat_levels["health"], 1)
        self.assertEqual(self.game.progression.upgrade_points, 0)
        self.assertEqual(self.game.player.ammo, 120)
        self.assertTrue(self.application.pointer_over_rewards(position))
        self.update(0, (False, False, False))
        self.update(1 / 60, (True, False, False))
        self.assertEqual(self.game.player.ammo, 119)

    def test_tab_in_menus_still_navigates_and_never_shows_panel(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        self.keys[pygame.K_TAB] = True
        self.update()

        # 메뉴의 Tab은 항목 이동에만 쓰이고 능력치 패널을 열지 않는지 확인한다.
        self.assertTrue(self.application.show_stats)
        self.application.handle_event(
            pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE)
        )
        selected_button_index = self.application.selected_button_index
        self.application.handle_event(
            pygame.event.Event(pygame.KEYDOWN, key=pygame.K_TAB)
        )
        self.assertNotEqual(
            self.application.selected_button_index, selected_button_index
        )
        self.update()
        self.assertFalse(self.application.show_stats)
        self.application.activate_menu_action("main")
        self.update()
        self.assertFalse(self.application.show_stats)
        self.application.activate_menu_action("start")
        self.game.game_over = True
        self.update()
        self.assertFalse(self.application.show_stats)

    def test_displayed_stats_match_five_upgrades_and_actual_weapon_shots(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        game = self.game
        game.progression.upgrade_points = 5
        for key in game.progression.stat_levels:
            game.progression.upgrade_stat(key)
        stats = dict(build_player_stat_summary(game))

        # 화면 능력치가 강화 결과와 실제 무기 발사 값에 맞는지 확인한다.
        self.assertEqual(stats["체력"], "125 / 125")
        self.assertEqual(
            stats["자가 수리"], "3.8 / 초"
        )  # 체력 125/100배만큼 회복도 비례해서 커짐
        self.assertEqual(stats["탄창"], "120 / 120")
        self.assertEqual(stats["재장전 시간"], "2.50초")
        for weapon in (
            "rookie",
            "triple_wing",
            "penta_wing",
            "railgunner",
            "hyper_railgun",
        ):
            with self.subTest(weapon=weapon):
                game.player.job = weapon
                game.progression.special_levels[weapon] = 2
                game.player.cooldown = 0
                game.combat.bullets.clear()
                stats = dict(build_player_stat_summary(game))
                game.combat._fire(game.player, True)
                bullet = game.combat.bullets[0]
                self.assertEqual(stats["주무기 피해 · 1발"], f"{bullet.damage:.2f}")
                self.assertEqual(
                    stats["발사 간격"],
                    f"{(game.player.cooldown + 1) / game.config.fps:.2f}초",
                )
                speed = (bullet.velocity_x**2 + bullet.velocity_y**2) ** 0.5
                self.assertEqual(
                    stats["탄속"], f"{speed * game.config.fps:.0f} px / 초"
                )
                self.assertEqual(stats["사거리"], f"{speed * bullet.life:.0f} px")


if __name__ == "__main__":
    unittest.main()
