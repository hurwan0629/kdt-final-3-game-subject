"""표시용 미니맵 위에서도 일반 월드 사격을 유지한다."""

import os
import unittest
from collections import defaultdict
from types import SimpleNamespace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
import pygame
from space_z.config import GameConfig
from space_z.game.game_core import GameCore
from space_z.app import GameApplication


class MinimapInputTests(unittest.TestCase):
    def application(self, progression=True):
        config = GameConfig(
            num_enemies=0,
            num_shapes=0,
            progression_enabled=progression,
        )
        config.terrain.enabled = False
        game = GameCore(config, seed=8)
        renderer = SimpleNamespace(
            size=(1280, 800),
            add_score_popups=lambda events: None,
            reset_score_popups=lambda: None,
            minimap_rect=lambda: pygame.Rect(1070, 620, 196, 166),
            _update_camera=lambda player: None,
            screen_to_world=lambda x, y: (game.player.x + 500, game.player.y),
        )
        application = GameApplication(game, renderer, seed=8)
        application.activate_menu_action("start")
        application.suppress_fire = False
        return game, application

    def test_click_and_hold_on_minimap_fires_normally(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        for progression in (False, True):
            with self.subTest(progression=progression):
                game, application = self.application(progression)
                position = (1150, 700)
                application.handle_event(
                    pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=position)
                )
                application.update(
                    1 / 60, defaultdict(bool), position, (True, False, False)
                )
                self.assertEqual(game.player.ammo, 119)
                self.assertEqual(len(game.combat.bullets), 1)
                self.assertFalse(application.suppress_fire)
                self.assertFalse(application.click_requested)
                for _ in range(game.player.fire_cooldown_max + 5):
                    application.update(
                        1 / 60, defaultdict(bool), position, (True, False, False)
                    )
                self.assertLess(game.player.ammo, 119)
                self.assertGreater(len(game.combat.bullets), 1)

    def test_firing_continues_when_cursor_sweeps_over_the_minimap_mid_hold(self):
        """발사 중 커서가 미니맵 위를 지나가도 사격을 계속한다."""

        # 검사에 사용할 설정·개체·입력을 준비한다.
        game, application = self.application()
        position = (640, 400)
        application.handle_event(
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=position)
        )
        application.update(1 / 60, defaultdict(bool), position, (True, False, False))

        # 발사 중 커서가 미니맵 위를 지나도 발사가 유지되는지 확인한다.
        self.assertEqual(game.player.ammo, 119)
        self.assertEqual(len(game.combat.bullets), 1)
        # 쿨다운이 돌 때까지 월드 쪽을 계속 조준하다, 다 되는 순간 커서가 미니맵 위에 있어도
        # 발사가 막히면 안 된다.
        for _ in range(game.player.fire_cooldown_max + 5):
            application.update(
                1 / 60, defaultdict(bool), (1150, 700), (True, False, False)
            )
        self.assertLess(game.player.ammo, 119)
        self.assertGreater(len(game.combat.bullets), 1)

    def test_pointer_over_rewards_ignores_the_minimap(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        game, application = self.application()

        # 미니맵을 강화·보상 패널의 입력 영역으로 취급하지 않는지 확인한다.
        self.assertTrue(application.pointer_over_minimap((1150, 700)))
        self.assertFalse(application.pointer_over_rewards((1150, 700)))


if __name__ == "__main__":
    unittest.main()
