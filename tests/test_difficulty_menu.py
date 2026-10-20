"""메인 메뉴 전용 난이도 선택과 실제 적 성장 연동 검증."""
import os
import unittest
from collections import defaultdict
from dataclasses import asdict
from types import SimpleNamespace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import pygame

from space_z.config import GameConfig
from space_z.game.game_core import GameCore
from space_z.app import GameApplication
from space_z.rendering.menu_layout import DIFFICULTY_OPTIONS
from space_z.config.progression_definitions import STAT_UPGRADES


class DifficultyMenuTests(unittest.TestCase):
    def application(self, enemies=0):
        cfg = GameConfig(num_enemies=enemies, num_shapes=0)
        cfg.terrain.enabled = False
        game = GameCore(cfg, seed=22)
        renderer = SimpleNamespace(size=(1280, 800), _update_camera=lambda player: None,
                                   screen_to_world=lambda x, y: (game.player.x + 500, game.player.y))
        return game, GameApplication(game, renderer, seed=22)

    def click(self, app, key):
        button = next(button for button in app.get_menu_buttons() if button.key == key)
        app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1,
                                           pos=button.rect.center))

    def key(self, app, key):
        app.handle_event(pygame.event.Event(pygame.KEYDOWN, key=key))

    def test_every_launch_defaults_to_normal_with_start_focused(self):
        game, app = self.application()
        choices = [button for button in app.get_menu_buttons() if button.key.startswith("difficulty_")]
        self.assertEqual([button.label for button in choices], ["쉬움", "보통", "어려움"])
        self.assertEqual([button.key for button in choices if button.checked], ["difficulty_normal"])
        self.assertEqual(app.get_menu_buttons()[app.selected_button_index].key, "start")
        self.click(app, "difficulty_hard")
        self.click(app, "start")
        self.assertEqual(game.cfg.enemy_ai.stat_mirror_ratio, .6)
        fresh = GameApplication(game, app.renderer, seed=22)
        self.assertEqual(fresh.difficulty_ratio, .5)
        self.click(fresh, "start")
        self.assertEqual(game.cfg.enemy_ai.stat_mirror_ratio, .5)

    def test_click_selects_without_starting_and_start_applies_only_mirror_ratio(self):
        for key, _, ratio in DIFFICULTY_OPTIONS:
            with self.subTest(choice=key):
                game, app = self.application()
                old_ai = asdict(game.cfg.enemy_ai)
                self.click(app, key)
                self.assertEqual(app.mode, "main")
                self.assertEqual(game.frame, 0)
                self.assertEqual(app.difficulty_ratio, ratio)
                self.assertEqual(asdict(game.cfg.enemy_ai), old_ai)
                self.assertEqual([button.key for button in app.get_menu_buttons() if button.checked], [key])
                app.update(100, defaultdict(bool), (0, 0), (False, False, False))
                self.assertEqual(game.frame, 0)
                self.click(app, "start")
                self.assertEqual(app.mode, "playing")
                self.assertEqual(game.cfg.enemy_ai.stat_mirror_ratio, ratio)
                expected = dict(old_ai, stat_mirror_ratio=ratio)
                self.assertEqual(asdict(game.cfg.enemy_ai), expected)

    def test_keyboard_selects_choices_without_losing_selection_on_start(self):
        game, app = self.application()
        for expected in ("difficulty_hard", "difficulty_normal", "difficulty_easy"):
            self.key(app, pygame.K_UP)
            self.assertEqual(app.get_menu_buttons()[app.selected_button_index].key, expected)
        self.key(app, pygame.K_RETURN)
        self.assertEqual((app.mode, app.difficulty_ratio), ("main", .4))
        self.key(app, pygame.K_TAB)
        self.key(app, pygame.K_SPACE)
        self.assertEqual((app.mode, app.difficulty_ratio), ("main", .5))
        self.key(app, pygame.K_DOWN)
        self.key(app, pygame.K_RETURN)
        self.assertEqual((app.mode, app.difficulty_ratio), ("main", .6))
        self.key(app, pygame.K_DOWN)
        self.assertEqual(app.get_menu_buttons()[app.selected_button_index].key, "start")
        self.assertTrue(next(button for button in app.get_menu_buttons()
                             if button.key == "difficulty_hard").checked)
        self.key(app, pygame.K_RETURN)
        self.assertEqual((app.mode, game.cfg.enemy_ai.stat_mirror_ratio), ("playing", .6))

    def test_play_pause_and_restart_cannot_change_difficulty(self):
        game, app = self.application()
        self.click(app, "difficulty_easy")
        self.click(app, "start")
        for mode in ("playing", "pause"):
            app.mode = mode
            self.assertFalse(any(button.key.startswith("difficulty_") for button in app.get_menu_buttons()))
            for key, _, _ in DIFFICULTY_OPTIONS:
                app.activate_menu_action(key)
                self.assertEqual((app.mode, app.difficulty_ratio,
                                  game.cfg.enemy_ai.stat_mirror_ratio), (mode, .4, .4))
        self.click(app, "restart")
        self.assertEqual((app.mode, game.cfg.enemy_ai.stat_mirror_ratio), ("playing", .4))

    def test_return_to_main_can_select_a_new_value_for_the_next_game(self):
        game, app = self.application()
        self.click(app, "difficulty_easy")
        self.click(app, "start")
        self.key(app, pygame.K_ESCAPE)
        self.click(app, "main")
        self.assertEqual(app.mode, "main")
        self.assertEqual(app.get_menu_buttons()[app.selected_button_index].key, "start")
        self.assertEqual(app.difficulty_ratio, .4)
        self.click(app, "difficulty_hard")
        self.assertEqual(game.cfg.enemy_ai.stat_mirror_ratio, .4)
        self.click(app, "start")
        self.assertEqual(game.cfg.enemy_ai.stat_mirror_ratio, .6)

    def test_selected_value_changes_live_and_respawned_enemy_stat_budgets(self):
        for key, _, ratio in DIFFICULTY_OPTIONS:
            with self.subTest(choice=key):
                game, app = self.application(enemies=2)
                self.click(app, key)
                self.click(app, "start")
                game.progression.upgrade_points = 35
                for card in STAT_UPGRADES:
                    for _ in range(7):
                        self.assertTrue(game.progression.upgrade_stat(card.key))
                expected = sum(int(7 * ratio) for _ in STAT_UPGRADES)
                self.assertEqual(expected, {.4: 10, .5: 15, .6: 20}[ratio])
                for enemy in game.enemies:
                    self.assertEqual(sum(enemy.stat_levels.values()), expected)
                enemy = game.enemies[0]
                enemy.hp, enemy.alive, enemy.respawn_timer = 0, False, 1
                game.step(0, want_fire=False)
                self.assertTrue(enemy.alive)
                self.assertEqual(sum(enemy.stat_levels.values()), expected)

    def test_choice_layout_fits_windows_and_pause_contains_no_difficulty(self):
        _, app = self.application()
        for size in ((960, 640), (1280, 800), (1920, 1080)):
            with self.subTest(size=size):
                app.renderer.size = size
                buttons = app.get_menu_buttons()
                viewport = pygame.Rect((0, 0), size)
                for i, button in enumerate(buttons):
                    self.assertTrue(viewport.contains(button.rect))
                    self.assertNotIn("난이도", button.label)
                    for other in buttons[i + 1:]:
                        self.assertFalse(button.rect.colliderect(other.rect))
                self.assertEqual(buttons[0].rect.left, buttons[3].rect.left)
                self.assertEqual(buttons[2].rect.right, buttons[3].rect.right)
                self.assertLess(buttons[0].rect.bottom, buttons[3].rect.top)
        app.mode = "pause"
        self.assertEqual([button.key for button in app.get_menu_buttons()],
                         ["fullscreen", "zoom", "controls", "debug", "auto_pause",
                          "resume", "restart", "main", "quit"])


if __name__ == "__main__":
    unittest.main()
