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

from config import GameConfig
from game_core import GameCore
from main import GameApplication
from progression import REWARD_CARDS


class MenusReloadTests(unittest.TestCase):
    def setUp(self):
        cfg = GameConfig(num_shapes=0, num_enemies=0)
        cfg.terrain.enabled = False
        self.game = GameCore(cfg, seed=2)
        self.renderer = SimpleNamespace(
            _update_camera=Mock(), screen_to_world=lambda x, y: (2000, 1100),
            set_zoom=Mock(side_effect=lambda zoom: setattr(cfg, "camera_zoom", zoom)))
        self.app = GameApplication(self.game, self.renderer, seed=2)

    def key(self, key):
        self.app.handle_event(pygame.event.Event(pygame.KEYDOWN, key=key))

    def click(self, name):
        button = next(b for b in self.app.buttons() if b.key == name)
        self.app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=button.rect.center))

    def update(self, elapsed=1 / 60, fire=False):
        self.app.update(elapsed, defaultdict(bool), (480, 360), (fire, False, False))

    def test_main_menu_three_buttons_disabled_story_and_keyboard_navigation(self):
        buttons = self.app.buttons()
        self.assertEqual([b.key for b in buttons], ["start", "story", "quit"])
        self.assertEqual((buttons[0].rect.top + buttons[-1].rect.bottom) / 2, 360)
        self.assertFalse(buttons[1].enabled)
        self.click("story")
        self.assertEqual(self.app.mode, "main")
        self.update(100)
        self.assertEqual(self.game.frame, 0)
        self.key(pygame.K_DOWN)
        self.assertEqual(self.app.selected, 2)
        self.key(pygame.K_UP)
        self.assertEqual(self.app.selected, 0)
        self.key(pygame.K_RETURN)
        self.assertEqual(self.app.mode, "playing")

    def test_start_and_resume_menu_clicks_do_not_fire(self):
        self.click("start")
        self.update(fire=True)
        self.assertEqual(self.game.player.ammo, 120)
        self.update(fire=False)
        self.update(fire=True)
        self.assertEqual(self.game.player.ammo, 119)
        self.key(pygame.K_ESCAPE)
        self.click("resume")
        self.update(fire=True)
        self.assertEqual(self.game.player.ammo, 119)

    def test_settings_change_without_reset_and_survive_main_menu(self):
        self.click("start")
        self.game._add_score(190)
        self.key(pygame.K_ESCAPE)
        self.click("zoom")
        self.assertEqual(self.game.cfg.camera_zoom, 0.75)
        self.renderer.set_zoom.assert_called_once_with(0.75)
        self.click("controls")
        self.click("debug")
        self.click("auto_pause")
        self.assertFalse(self.app.show_controls)
        self.assertTrue(self.app.show_debug)
        self.assertFalse(self.app.auto_pause)
        self.assertEqual(self.game.score, 190)
        self.click("main")
        self.assertEqual(self.app.mode, "main")
        self.click("start")
        self.assertEqual(self.game.score, 0)
        self.assertFalse(self.app.show_controls)
        self.assertEqual(self.game.cfg.camera_zoom, 0.75)
        self.app.handle_event(pygame.event.Event(pygame.WINDOWFOCUSLOST))
        self.assertEqual(self.app.mode, "playing")

    def test_quit_from_both_menus_and_restart_from_pause(self):
        self.click("quit")
        self.assertFalse(self.app.running)
        self.app.running = True
        self.app.activate("start")
        self.game._add_score(190)
        self.key(pygame.K_ESCAPE)
        self.click("restart")
        self.assertEqual((self.app.mode, self.game.score, self.game.level), ("playing", 0, 1))
        self.key(pygame.K_ESCAPE)
        self.click("quit")
        self.assertFalse(self.app.running)

    def test_reload_takes_exactly_150_frames_and_blocks_fire_but_allows_movement(self):
        game = self.game
        p = game.player
        p.ammo = 0
        self.assertTrue(game.request_reload())
        self.assertFalse(game.request_reload())
        self.assertEqual(game.reload_frames_left, 150)
        before_x = p.x
        for _ in range(149):
            game.step(9, want_fire=True)
        self.assertGreater(p.x, before_x)
        self.assertEqual((p.ammo, game.reload_frames_left, len(game.bullets)), (0, 1, 0))
        game.step(0, want_fire=True)
        self.assertEqual((p.ammo, game.reload_frames_left, len(game.bullets)), (120, 0, 0))
        game.step(0, want_fire=True)
        self.assertEqual((p.ammo, len(game.bullets)), (119, 1))
        self.assertTrue(game.request_reload())

    def test_r_reloads_without_reset_and_menus_freeze_reload_timer(self):
        self.click("start")
        self.game._add_score(190)
        self.game.player.ammo = 10
        self.key(pygame.K_r)
        self.assertEqual((self.game.reload_frames_left, self.game.score, self.game.level), (150, 190, 3))
        self.update()
        self.assertEqual(self.game.reload_frames_left, 149)
        self.key(pygame.K_ESCAPE)
        self.update(100)
        self.key(pygame.K_r)
        self.assertEqual((self.game.reload_frames_left, self.game.score), (149, 190))
        self.key(pygame.K_ESCAPE)
        choice = self.game.stat_choices[0].key
        self.key(pygame.K_1)
        self.update(100)
        self.assertEqual(self.game.reload_frames_left, 144)
        self.assertEqual(self.game.stat_levels[choice], 1)
        self.update()
        self.assertEqual(self.game.reload_frames_left, 143)

    def test_empty_magazine_auto_reloads_and_firing_resumes(self):
        game = self.game
        game.player.ammo = 1
        game._fire(game.player, True)
        self.assertEqual((game.player.ammo, game.reload_frames_left, len(game.bullets)), (0, 150, 1))
        for _ in range(149):
            game.step(0, want_fire=False)
        self.assertEqual((game.player.ammo, game.reload_frames_left), (0, 1))
        game.step(0, want_fire=False)
        self.assertEqual((game.player.ammo, game.reload_frames_left), (120, 0))
        game.step(0, want_fire=True)
        self.assertEqual(game.player.ammo, 119)

    def test_delayed_last_bullet_and_empty_idle_magazine_auto_reload(self):
        game = self.game
        game.player.job, game.player.ammo = "twin", 2
        game._fire(game.player, True)
        self.assertEqual(game.reload_frames_left, 0)
        for frame in range(1, 4):
            game.frame = frame
            game._fire(game.player, False)
        self.assertEqual((game.player.ammo, game.reload_frames_left), (0, 150))
        self.assertEqual(game.player.pending_shots, [])
        game.reset(2)
        game.player.ammo = 0
        game.step(0, want_fire=False)
        self.assertEqual(game.reload_frames_left, 149)

    def test_pause_freezes_time_difficulty(self):
        self.click("start")
        self.game.frame = 120 * 60 - 1
        self.key(pygame.K_ESCAPE)
        self.update(100)
        self.assertEqual((self.game.frame, self.game.difficulty_stage), (7199, 0))
        self.key(pygame.K_ESCAPE)
        self.update()
        self.assertEqual((self.game.frame, self.game.difficulty_stage), (7200, 1))

    def test_reload_rejects_full_magazine_death_and_unlimited_mode(self):
        game = self.game
        self.assertFalse(game.request_reload())
        game.player.ammo = 0
        game.cfg.limited_ammo = False
        self.assertFalse(game.request_reload())
        game.cfg.limited_ammo = True
        game.game_over = True
        self.assertFalse(game.request_reload())
        game.reset(2)
        self.assertEqual((game.player.ammo, game.reload_frames_left), (120, 0))
        self.assertNotIn("ammo", {c.key for c in REWARD_CARDS})

    def test_real_main_loop_starts_on_main_menu_and_handles_exit(self):
        import main
        pygame.init()
        pygame.display.set_mode((960, 720))
        renderer = SimpleNamespace(clock=Mock(), draw_main_menu=Mock(), draw=Mock())
        renderer.clock.tick.return_value = 17
        with patch("sys.argv", ["main.py"]), patch("main.GameCore", return_value=self.game), \
                patch("renderer.Renderer", return_value=renderer), \
                patch("pygame.event.get", side_effect=[[], [pygame.event.Event(pygame.QUIT)]]):
            main.main()
        renderer.draw_main_menu.assert_called_once()
        renderer.draw.assert_not_called()
        self.assertEqual(self.game.frame, 0)


if __name__ == "__main__":
    unittest.main()
