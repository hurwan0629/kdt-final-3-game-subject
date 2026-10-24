"""메뉴 전환, 설정, 2.5초 재장전의 동작 검증."""

import os
import unittest
from collections import defaultdict
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import pygame

from space_z.config import GameConfig
from space_z.game.game_core import GameCore
from space_z.app import GameApplication
from space_z.config.progression_definitions import REWARD_CARDS
from space_z.rendering.progression_panel import build_stat_upgrade_rows


class MenusReloadTests(unittest.TestCase):
    def setUp(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        config = GameConfig(num_shapes=0, num_enemies=0)
        config.terrain.enabled = False
        self.game = GameCore(config, seed=2)
        self.renderer = SimpleNamespace(
            add_score_popups=Mock(),
            reset_score_popups=Mock(),
            _update_camera=Mock(),
            screen_to_world=lambda x, y: (2000, 1100),
            set_zoom=Mock(
                side_effect=lambda zoom: setattr(config, "camera_zoom", zoom)
            ),
        )
        self.application = GameApplication(self.game, self.renderer, seed=2)

    def key(self, key):
        self.application.handle_event(pygame.event.Event(pygame.KEYDOWN, key=key))

    def click(self, name):
        button = next(
            button
            for button in self.application.get_menu_buttons()
            if button.key == name
        )
        self.application.handle_event(
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=button.rect.center)
        )

    def update(self, elapsed=1 / 60, fire=False):
        self.application.update(
            elapsed, defaultdict(bool), (480, 360), (fire, False, False)
        )

    def test_main_menu_difficulty_choices_start_quit_and_keyboard_navigation(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        buttons = self.application.get_menu_buttons()

        # 메뉴 버튼과 키보드 탐색·시작·종료 동작을 확인한다.
        self.assertEqual(
            [button.key for button in buttons],
            [
                "difficulty_easy",
                "difficulty_normal",
                "difficulty_hard",
                "start",
                "quit",
            ],
        )
        self.assertEqual(buttons[3].rect.top, 354)
        self.assertEqual(buttons[4].rect.top, buttons[3].rect.top + 78)
        self.assertTrue(all(button.enabled for button in buttons))
        self.assertEqual(self.application.selected_button_index, 3)
        self.update(100)
        self.assertEqual(self.game.frame, 0)
        self.key(pygame.K_DOWN)
        self.assertEqual(self.application.selected_button_index, 4)
        self.key(pygame.K_UP)
        self.assertEqual(self.application.selected_button_index, 3)
        self.key(pygame.K_RETURN)
        self.assertEqual(self.application.mode, "playing")

    def test_start_and_resume_menu_clicks_do_not_fire(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        self.click("start")
        self.update(fire=True)

        # 시작·계속하기 버튼의 클릭이 게임 발사로 이어지지 않는지 확인한다.
        self.assertEqual(self.game.player.ammo, 120)
        self.update(fire=False)
        self.update(fire=True)
        self.assertEqual(self.game.player.ammo, 119)
        self.key(pygame.K_ESCAPE)
        self.click("resume")
        self.update(fire=True)
        self.assertEqual(self.game.player.ammo, 119)

    def test_settings_change_without_reset_and_survive_main_menu(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        self.click("start")
        self.game.progression._add_score(190)
        self.key(pygame.K_ESCAPE)
        self.click("zoom")

        # 설정 변경이 진행을 초기화하지 않고 메인 메뉴에서도 유지되는지 확인한다.
        self.assertEqual(self.game.config.camera_zoom, 0.75)
        self.renderer.set_zoom.assert_called_once_with(0.75)
        self.click("controls")
        self.click("debug")
        self.click("auto_pause")
        self.assertFalse(self.application.show_controls)
        self.assertTrue(self.application.show_debug)
        self.assertFalse(self.application.auto_pause)
        self.assertEqual(self.game.progression.score, 190)
        self.click("main")
        self.assertEqual(self.application.mode, "main")
        self.click("start")
        self.assertEqual(self.game.progression.score, 0)
        self.assertFalse(self.application.show_controls)
        self.assertEqual(self.game.config.camera_zoom, 0.75)
        self.application.handle_event(pygame.event.Event(pygame.WINDOWFOCUSLOST))
        self.assertEqual(self.application.mode, "playing")

    def test_quit_from_both_menus_and_restart_from_pause(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        self.click("quit")

        # 두 메뉴에서 종료할 수 있고 일시정지에서 새 판을 시작할 수 있는지 확인한다.
        self.assertFalse(self.application.running)
        self.application.running = True
        self.application.activate_menu_action("start")
        self.game.progression._add_score(190)
        self.key(pygame.K_ESCAPE)
        self.click("restart")
        self.assertEqual(
            (
                self.application.mode,
                self.game.progression.score,
                self.game.progression.level,
            ),
            ("playing", 0, 1),
        )
        self.key(pygame.K_ESCAPE)
        self.click("quit")
        self.assertFalse(self.application.running)

    def test_reload_takes_exactly_150_frames_and_blocks_fire_but_allows_movement(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        game = self.game
        player = game.player
        player.ammo = 0

        # 정해진 재장전 시간 동안 발사는 막히고 이동은 가능한지 확인한다.
        self.assertTrue(game.combat.request_reload())
        self.assertFalse(game.combat.request_reload())
        self.assertEqual(game.combat.reload_frames_left, 150)
        before_x = player.x
        for _ in range(149):
            game.step(9, want_fire=True)
        self.assertGreater(player.x, before_x)
        self.assertEqual(
            (player.ammo, game.combat.reload_frames_left, len(game.combat.bullets)),
            (0, 1, 0),
        )
        game.step(0, want_fire=True)
        self.assertEqual(
            (player.ammo, game.combat.reload_frames_left, len(game.combat.bullets)),
            (120, 0, 0),
        )
        game.step(0, want_fire=True)
        self.assertEqual((player.ammo, len(game.combat.bullets)), (119, 1))
        self.assertTrue(game.combat.request_reload())

    def test_r_reloads_without_reset_and_menus_freeze_reload_timer(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        self.click("start")
        self.game.progression._add_score(190)
        self.game.player.ammo = 10
        self.key(pygame.K_r)

        # 재장전이 진행 상태를 초기화하지 않고 메뉴에서는 타이머가 멈추는지 확인한다.
        self.assertEqual(
            (
                self.game.combat.reload_frames_left,
                self.game.progression.score,
                self.game.progression.level,
            ),
            (150, 190, 3),
        )
        self.update()
        self.assertEqual(self.game.combat.reload_frames_left, 149)
        self.key(pygame.K_ESCAPE)
        self.update(100)
        self.key(pygame.K_r)
        self.assertEqual(
            (self.game.combat.reload_frames_left, self.game.progression.score),
            (149, 190),
        )
        self.key(pygame.K_ESCAPE)
        choice = self.game.progression.stat_choices[0].key
        self.key(pygame.K_1)
        self.update(100)
        self.assertEqual(self.game.combat.reload_frames_left, 144)
        self.assertEqual(self.game.progression.stat_levels[choice], 1)
        self.update()
        self.assertEqual(self.game.combat.reload_frames_left, 143)

    def test_reload_rejects_full_magazine_death_and_unlimited_mode(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        game = self.game

        # 가득 찬 탄창·사망·무제한 탄약 상태에서 재장전을 거부하는지 확인한다.
        self.assertFalse(game.combat.request_reload())
        game.player.ammo = 0
        game.config.limited_ammo = False
        self.assertFalse(game.combat.request_reload())
        game.config.limited_ammo = True
        game.game_over = True
        self.assertFalse(game.combat.request_reload())
        game.reset(2)
        self.assertEqual((game.player.ammo, game.combat.reload_frames_left), (120, 0))
        self.assertNotIn("ammo", {config.key for config in REWARD_CARDS})

    def test_pause_events_clear_pending_time_and_fire(self):
        """포커스 상실과 일시정지 키가 이전 클릭·누적 시간을 비우고 게임은 진행하지 않는다."""
        events = (
            pygame.event.Event(pygame.WINDOWFOCUSLOST),
            pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE),
            pygame.event.Event(pygame.KEYDOWN, key=pygame.K_p),
        )
        for event in events:
            with self.subTest(event=event):
                # 진행 중인 게임에 아직 처리하지 않은 시간과 클릭이 있는 상황을 만든다.
                self.application.activate_menu_action("start")
                self.application.accumulated_time = 0.04
                self.application.click_requested = True
                self.application.suppress_fire = False

                self.application.handle_event(event)

                # 계속하기에 포커스를 두고 이전 발사 입력을 버리며 게임 프레임은 유지한다.
                self.assertEqual(self.application.mode, "pause")
                selected = self.application.get_menu_buttons()[
                    self.application.selected_button_index
                ]
                self.assertEqual(selected.key, "resume")
                self.assertEqual(self.application.accumulated_time, 0.0)
                self.assertFalse(self.application.click_requested)
                self.assertTrue(self.application.suppress_fire)
                self.assertEqual(self.game.frame, 0)

    def test_focus_loss_preserves_input_when_auto_pause_is_disabled(self):
        """자동 일시정지가 꺼져 있으면 포커스 상실이 플레이와 대기 입력을 바꾸지 않는다."""
        self.application.activate_menu_action("start")
        self.application.auto_pause = False
        self.application.accumulated_time = 0.04
        self.application.click_requested = True
        self.application.suppress_fire = False

        self.application.handle_event(pygame.event.Event(pygame.WINDOWFOCUSLOST))

        self.assertEqual(self.application.mode, "playing")
        self.assertEqual(self.application.accumulated_time, 0.04)
        self.assertTrue(self.application.click_requested)
        self.assertFalse(self.application.suppress_fire)

    def test_ui_clicks_are_consumed_until_mouse_release_before_world_fire(self):
        """메뉴·강화 클릭은 발사로 이어지지 않고 버튼 해제 뒤의 월드 클릭만 대기한다."""
        # 시작 메뉴 클릭은 게임을 시작하되 같은 클릭으로 발사를 요청하지 않는다.
        self.click("start")
        self.assertEqual(self.application.mode, "playing")
        self.assertFalse(self.application.click_requested)
        self.assertTrue(self.application.suppress_fire)
        self.update(elapsed=0, fire=False)

        # 포인트가 없어 강화에 실패해도 스탯 행의 클릭은 UI가 소비한다.
        position = pygame.Rect(
            build_stat_upgrade_rows(*self.application.size)[0][1]
        ).center
        self.application.handle_event(
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=position)
        )
        self.assertEqual(self.game.progression.upgrade_points, 0)
        self.assertEqual(self.game.progression.stat_levels["health"], 0)
        self.assertFalse(self.application.click_requested)
        self.assertTrue(self.application.suppress_fire)

        # 발사 억제 중인 월드 클릭은 버리고, 버튼을 놓은 뒤의 클릭은 다음 프레임까지 보관한다.
        world_click = pygame.event.Event(
            pygame.MOUSEBUTTONDOWN, button=1, pos=(480, 360)
        )
        self.application.handle_event(world_click)
        self.assertFalse(self.application.click_requested)
        self.update(elapsed=0, fire=False)
        self.application.handle_event(world_click)
        self.assertTrue(self.application.click_requested)
        self.assertEqual(self.game.frame, 0)

    def test_real_main_loop_starts_on_main_menu_and_handles_exit(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        from space_z import main

        pygame.init()
        pygame.display.set_mode((960, 720))
        renderer = SimpleNamespace(clock=Mock(), draw_main_menu=Mock(), draw=Mock())
        renderer.clock.tick.return_value = 17
        with (
            patch("sys.argv", ["main.py"]),
            patch("space_z.main.GameCore", return_value=self.game),
            patch("space_z.rendering.renderer.Renderer", return_value=renderer),
            patch(
                "pygame.event.get", side_effect=[[], [pygame.event.Event(pygame.QUIT)]]
            ),
        ):
            main.main()

        # 실제 메인 루프가 시작 메뉴에서 출발해 종료 요청을 처리하는지 확인한다.
        renderer.draw_main_menu.assert_called_once()
        renderer.draw.assert_not_called()
        self.assertEqual(self.game.frame, 0)


if __name__ == "__main__":
    unittest.main()
