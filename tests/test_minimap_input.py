"""표시용 미니맵 위의 마우스 입력이 월드 사격으로 새지 않는다."""
import os
import unittest
from collections import defaultdict
from types import SimpleNamespace
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
import pygame
from config import GameConfig
from game_core import GameCore
from main import GameApplication

class MinimapInputTests(unittest.TestCase):
    def application(self, progression=True):
        cfg = GameConfig(num_enemies=0, num_shapes=0, progression_enabled=progression)
        cfg.terrain.enabled = False
        game = GameCore(cfg, seed=8)
        renderer = SimpleNamespace(size=(1280, 800),
            minimap_rect=lambda: pygame.Rect(1070, 620, 196, 166),
            _update_camera=lambda player: None,
            screen_to_world=lambda x, y: (game.player.x+500, game.player.y))
        app = GameApplication(game, renderer, seed=8)
        app.activate("start")
        app.suppress_fire = False
        return game, app

    def test_click_and_hold_on_minimap_never_spends_ammo(self):
        for progression in (False, True):
            with self.subTest(progression=progression):
                game, app = self.application(progression)
                pos = (1150, 700)
                app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=pos))
                app.update(1/60, defaultdict(bool), pos, (True, False, False))
                self.assertEqual(game.player.ammo, 120)
                self.assertFalse(game.bullets)
                self.assertFalse(app.click_requested)

    def test_firing_continues_when_cursor_sweeps_over_the_minimap_mid_hold(self):
        """다른 곳을 눌러서 이미 발사 중이면, 조준하다 커서가 미니맵 위를 지나가도
        발사가 끊기면 안 된다(미니맵은 버튼 없는 표시용이라 클릭 시작 때만 막는다)."""
        game, app = self.application()
        pos = (640, 400)
        app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=pos))
        app.update(1/60, defaultdict(bool), pos, (True, False, False))
        self.assertEqual(game.player.ammo, 119)
        self.assertEqual(len(game.bullets), 1)
        # 쿨다운이 돌 때까지 월드 쪽을 계속 조준하다, 다 되는 순간 커서가 미니맵 위에 있어도
        # 발사가 막히면 안 된다.
        for _ in range(game.player.fire_cooldown_max + 5):
            app.update(1/60, defaultdict(bool), (1150, 700), (True, False, False))
        self.assertLess(game.player.ammo, 119)
        self.assertGreater(len(game.bullets), 1)

    def test_pointer_over_rewards_ignores_the_minimap(self):
        game, app = self.application()
        self.assertTrue(app.pointer_over_minimap((1150, 700)))
        self.assertFalse(app.pointer_over_rewards((1150, 700)))

if __name__ == "__main__":
    unittest.main()
