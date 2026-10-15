"""에셋 연결, 작은 보상 UI, 창 크기와 전체화면 전환 검증."""
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
from progression import FAMILIES, SHIPS, stat_rows, special_cards
from renderer import Renderer


class DisplayAssetsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()
        cls.cfg = GameConfig(num_enemies=0, num_shapes=0)
        cls.renderer = Renderer(cls.cfg)

    @classmethod
    def tearDownClass(cls):
        pygame.quit()

    def setUp(self):
        self.renderer.set_fullscreen(False)
        self.renderer.resize((1280, 800))
        self.game = GameCore(self.cfg, seed=7)
        self.app = GameApplication(self.game, self.renderer)
        self.app.mode = "playing"

    def test_default_window_is_larger_and_resizable(self):
        self.assertEqual(self.renderer.size, (1280, 800))
        self.assertTrue(self.renderer.screen.get_flags() & pygame.RESIZABLE)
        self.assertEqual((self.cfg.world_width, self.cfg.world_height), (2880, 2160))

    def test_fullscreen_menu_round_trip_preserves_world_and_game_state(self):
        self.game._add_score(1980)
        self.game.player.ammo = 3
        self.game.request_reload()
        self.app.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE))
        self.assertEqual(self.app.mode, "pause")
        state = (self.game.frame, self.game.score, self.game.player.x, self.game.player.hp,
                 self.game.player.ammo, self.game.reload_frames_left, self.game.reward_choices,
                 self.game.stat_choices, id(self.game.terrain))
        for expected in (True, False):
            button = next(b for b in self.app.buttons() if b.key == "fullscreen")
            self.app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=button.rect.center))
            self.assertEqual(self.renderer.fullscreen, expected)
            self.assertEqual(bool(self.renderer.screen.get_flags() & pygame.FULLSCREEN), expected)
            self.app.update(100, defaultdict(bool), (0, 0), (False, False, False))
            self.app.draw(ObsConfig())
            self.assertEqual((self.game.frame, self.game.score, self.game.player.x, self.game.player.hp,
                              self.game.player.ammo, self.game.reload_frames_left, self.game.reward_choices,
                              self.game.stat_choices, id(self.game.terrain)), state)
            self.assertTrue(pygame.Rect((0, 0), self.renderer.size).contains(self.app.buttons()[-1].rect))
        self.assertEqual(self.renderer.size, (1280, 800))
        self.assertEqual((self.cfg.width, self.cfg.height), (960, 720))

    def test_resize_rebuilds_camera_and_click_regions(self):
        self.game._add_score(1980)
        self.app.handle_event(pygame.event.Event(pygame.VIDEORESIZE, size=(1440, 900), w=1440, h=900))
        self.assertEqual(self.renderer.size, (1440, 900))
        self.renderer._update_camera(self.game.player)
        for point in ((0, 0), (720, 450), (1440, 900)):
            self.assertEqual(self.renderer.world_to_screen(*self.renderer.screen_to_world(*point)), point)
        choice = self.game.stat_choices[0].key
        row = pygame.Rect(stat_rows(*self.renderer.size, self.game.stat_choices)[0][1])
        self.assertTrue(self.app.pointer_over_rewards(row.center))
        self.app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=row.center))
        self.assertEqual(self.game.stat_levels[choice], 1)
        self.app.draw(ObsConfig())

    def test_l10_and_l20_use_matching_ship_images_in_compact_cards(self):
        self.game._add_score(1980)
        with patch.object(self.renderer.assets, "image", wraps=self.renderer.assets.image) as image:
            self.app.draw(ObsConfig())
            paths = {call.args[0] for call in image.call_args_list}
            self.assertTrue({"ships/" + card.key for card in FAMILIES}.issubset(paths))
        self.app.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_F5))
        self.assertEqual(self.game.player.job, "guardian")
        self.game._add_score(7980 - self.game.score)
        self.assertEqual([c.key for c in self.game.reward_choices], ["booster", "ram"])
        with patch.object(self.renderer.assets, "image", wraps=self.renderer.assets.image) as image:
            self.app.draw(ObsConfig())
            paths = {call.args[0] for call in image.call_args_list}
            self.assertTrue({"ships/booster", "ships/ram"}.issubset(paths))
        for coords in special_cards(*self.renderer.size):
            self.assertEqual(pygame.Rect(coords).size, (90, 90))

    def test_stats_show_three_unique_choices_and_keep_them_until_spent(self):
        self.game._add_score(190)
        choices = self.game.stat_choices
        self.assertEqual(len({c.key for c in choices}), 3)
        self.app.draw(ObsConfig())
        self.app.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE))
        self.app.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE))
        self.assertEqual(self.game.stat_choices, choices)
        self.app.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_2))
        self.assertEqual(self.game.stat_levels[choices[1].key], 1)
        self.assertEqual(self.game.upgrade_points, 1)
        self.assertEqual(len(self.game.stat_choices), 3)
        self.app.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_1))
        self.assertEqual(self.game.stat_choices, ())

    def test_all_ship_sprites_render_and_transform_cache_reuses_images(self):
        for key in SHIPS:
            with self.subTest(ship=key):
                self.game.player.job = key
                self.renderer.draw(self.game)
                image = self.renderer.assets.image("ships/" + key, 62)
                self.assertIs(image, self.renderer.assets.image("ships/" + key, 62))
        self.renderer.resize((4000, 2400))
        self.assertLessEqual(self.renderer.view_width, self.cfg.world_width)
        self.assertLessEqual(self.renderer.view_height, self.cfg.world_height)

    def test_no_empty_skill_panel_before_unlock_and_hidden_enemies_are_not_drawn(self):
        with patch.object(self.renderer, "_panel", wraps=self.renderer._panel) as panel:
            self.renderer._draw_skills(self.game)
            panel.assert_not_called()
        self.cfg.num_enemies = 1
        try:
            self.game.reset(7)
            enemy = self.game.enemies[0]
            enemy.x, enemy.y = self.game.player.x + 100, self.game.player.y
            original = self.game.is_hidden
            with patch.object(self.game, "is_hidden", side_effect=lambda tank: tank is enemy or original(tank)), \
                    patch.object(self.renderer, "_draw_ship", wraps=self.renderer._draw_ship) as ship:
                self.renderer.draw(self.game)
                self.assertFalse(any(call.args[0] is enemy for call in ship.call_args_list))
        finally:
            self.cfg.num_enemies = 0


if __name__ == "__main__":
    unittest.main()
