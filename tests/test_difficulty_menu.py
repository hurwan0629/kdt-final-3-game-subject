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
        config = GameConfig(num_enemies=enemies, num_shapes=0)
        config.terrain.enabled = False
        game = GameCore(config, seed=22)
        renderer = SimpleNamespace(
            size=(1280, 800),
            _update_camera=lambda player: None,
            add_score_popups=lambda events: None,
            reset_score_popups=lambda: None,
            screen_to_world=lambda x, y: (game.player.x + 500, game.player.y),
        )
        return game, GameApplication(game, renderer, seed=22)

    def click(self, application, key):
        button = next(
            button for button in application.get_menu_buttons() if button.key == key
        )
        application.handle_event(
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=button.rect.center)
        )

    def key(self, application, key):
        application.handle_event(pygame.event.Event(pygame.KEYDOWN, key=key))

    def test_every_launch_defaults_to_normal_with_start_focused(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        game, application = self.application()
        choices = [
            button
            for button in application.get_menu_buttons()
            if button.key.startswith("difficulty_")
        ]

        # 시작 메뉴의 기본 난이도와 선택된 버튼을 확인한다.
        self.assertEqual(
            [button.label for button in choices], ["쉬움", "보통", "어려움"]
        )
        self.assertEqual(
            [button.key for button in choices if button.checked], ["difficulty_normal"]
        )
        self.assertEqual(
            application.get_menu_buttons()[application.selected_button_index].key,
            "start",
        )
        self.click(application, "difficulty_hard")
        self.click(application, "start")
        self.assertEqual(game.config.enemy_ai.stat_mirror_ratio, 0.6)
        fresh = GameApplication(game, application.renderer, seed=22)
        self.assertEqual(fresh.difficulty_ratio, 0.5)
        self.click(fresh, "start")
        self.assertEqual(game.config.enemy_ai.stat_mirror_ratio, 0.5)

    def test_click_selects_without_starting_and_start_applies_only_mirror_ratio(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        for key, _, ratio in DIFFICULTY_OPTIONS:
            with self.subTest(choice=key):
                game, application = self.application()
                old_ai = asdict(game.config.enemy_ai)
                self.click(application, key)
                self.assertEqual(application.mode, "main")
                self.assertEqual(game.frame, 0)
                self.assertEqual(application.difficulty_ratio, ratio)
                self.assertEqual(asdict(game.config.enemy_ai), old_ai)
                self.assertEqual(
                    [
                        button.key
                        for button in application.get_menu_buttons()
                        if button.checked
                    ],
                    [key],
                )
                application.update(
                    100, defaultdict(bool), (0, 0), (False, False, False)
                )
                self.assertEqual(game.frame, 0)
                self.click(application, "start")
                self.assertEqual(application.mode, "playing")
                self.assertEqual(game.config.enemy_ai.stat_mirror_ratio, ratio)
                expected = dict(old_ai, stat_mirror_ratio=ratio)
                self.assertEqual(asdict(game.config.enemy_ai), expected)

    def test_keyboard_selects_choices_without_losing_selection_on_start(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        game, application = self.application()

        # 키보드로 고른 난이도가 게임 시작 뒤에도 유지되는지 확인한다.
        for expected in ("difficulty_hard", "difficulty_normal", "difficulty_easy"):
            self.key(application, pygame.K_UP)
            self.assertEqual(
                application.get_menu_buttons()[application.selected_button_index].key,
                expected,
            )
        self.key(application, pygame.K_RETURN)
        self.assertEqual(
            (application.mode, application.difficulty_ratio), ("main", 0.4)
        )
        self.key(application, pygame.K_TAB)
        self.key(application, pygame.K_SPACE)
        self.assertEqual(
            (application.mode, application.difficulty_ratio), ("main", 0.5)
        )
        self.key(application, pygame.K_DOWN)
        self.key(application, pygame.K_RETURN)
        self.assertEqual(
            (application.mode, application.difficulty_ratio), ("main", 0.6)
        )
        self.key(application, pygame.K_DOWN)
        self.assertEqual(
            application.get_menu_buttons()[application.selected_button_index].key,
            "start",
        )
        self.assertTrue(
            next(
                button
                for button in application.get_menu_buttons()
                if button.key == "difficulty_hard"
            ).checked
        )
        self.key(application, pygame.K_RETURN)
        self.assertEqual(
            (application.mode, game.config.enemy_ai.stat_mirror_ratio), ("playing", 0.6)
        )

    def test_play_pause_and_restart_cannot_change_difficulty(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        game, application = self.application()
        self.click(application, "difficulty_easy")
        self.click(application, "start")

        # 플레이·일시정지·재시작 과정에서 난이도가 유지되는지 확인한다.
        for mode in ("playing", "pause"):
            application.mode = mode
            self.assertFalse(
                any(
                    button.key.startswith("difficulty_")
                    for button in application.get_menu_buttons()
                )
            )
            for key, _, _ in DIFFICULTY_OPTIONS:
                application.activate_menu_action(key)
                self.assertEqual(
                    (
                        application.mode,
                        application.difficulty_ratio,
                        game.config.enemy_ai.stat_mirror_ratio,
                    ),
                    (mode, 0.4, 0.4),
                )
        self.click(application, "restart")
        self.assertEqual(
            (application.mode, game.config.enemy_ai.stat_mirror_ratio), ("playing", 0.4)
        )

    def test_return_to_main_can_select_a_new_value_for_the_next_game(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        game, application = self.application()
        self.click(application, "difficulty_easy")
        self.click(application, "start")
        self.key(application, pygame.K_ESCAPE)
        self.click(application, "main")

        # 메인 메뉴에서 다시 고른 난이도가 다음 판에 적용되는지 확인한다.
        self.assertEqual(application.mode, "main")
        self.assertEqual(
            application.get_menu_buttons()[application.selected_button_index].key,
            "start",
        )
        self.assertEqual(application.difficulty_ratio, 0.4)
        self.click(application, "difficulty_hard")
        self.assertEqual(game.config.enemy_ai.stat_mirror_ratio, 0.4)
        self.click(application, "start")
        self.assertEqual(game.config.enemy_ai.stat_mirror_ratio, 0.6)

    def test_selected_value_changes_live_and_respawned_enemy_stat_budgets(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        for key, _, ratio in DIFFICULTY_OPTIONS:
            with self.subTest(choice=key):
                game, application = self.application(enemies=2)
                self.click(application, key)
                self.click(application, "start")
                game.progression.upgrade_points = 35
                for card in STAT_UPGRADES:
                    for _ in range(7):
                        self.assertTrue(game.progression.upgrade_stat(card.key))
                expected = sum(int(7 * ratio) for _ in STAT_UPGRADES)
                self.assertEqual(expected, {0.4: 10, 0.5: 15, 0.6: 20}[ratio])
                for enemy in game.enemies:
                    self.assertEqual(sum(enemy.stat_levels.values()), expected)
                enemy = game.enemies[0]
                enemy.hp, enemy.alive, enemy.respawn_timer = 0, False, 1
                game.step(0, want_fire=False)
                self.assertTrue(enemy.alive)
                self.assertEqual(sum(enemy.stat_levels.values()), expected)

    def test_choice_layout_fits_windows_and_pause_contains_no_difficulty(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        _, application = self.application()

        # 작은 창에서도 난이도 버튼이 들어가고 일시정지 메뉴에는 나타나지 않는지 확인한다.
        for size in ((960, 640), (1280, 800), (1920, 1080)):
            with self.subTest(size=size):
                application.renderer.size = size
                buttons = application.get_menu_buttons()
                viewport = pygame.Rect((0, 0), size)
                for button_index, button in enumerate(buttons):
                    self.assertTrue(viewport.contains(button.rect))
                    self.assertNotIn("난이도", button.label)
                    for other in buttons[button_index + 1 :]:
                        self.assertFalse(button.rect.colliderect(other.rect))
                self.assertEqual(buttons[0].rect.left, buttons[3].rect.left)
                self.assertEqual(buttons[2].rect.right, buttons[3].rect.right)
                self.assertLess(buttons[0].rect.bottom, buttons[3].rect.top)
        application.mode = "pause"
        self.assertEqual(
            [button.key for button in application.get_menu_buttons()],
            [
                "fullscreen",
                "zoom",
                "controls",
                "debug",
                "auto_pause",
                "resume",
                "restart",
                "main",
                "quit",
            ],
        )


if __name__ == "__main__":
    unittest.main()
