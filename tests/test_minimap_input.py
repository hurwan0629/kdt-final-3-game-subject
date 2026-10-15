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

    def test_hover_blocks_held_fire_but_world_fire_still_works(self):
        game, app = self.application()
        app.update(1/60, defaultdict(bool), (1150, 700), (True, False, False))
        self.assertEqual(game.player.ammo, 120)
        app.update(1/60, defaultdict(bool), (640, 400), (True, False, False))
        self.assertEqual(game.player.ammo, 119)
        self.assertEqual(len(game.bullets), 1)

if __name__ == "__main__":
    unittest.main()
