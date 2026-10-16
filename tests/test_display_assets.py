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
from progression import FAMILIES, SHIPS, STAT_UPGRADES, stat_rows, special_cards
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
        self.assertEqual((self.cfg.world_width, self.cfg.world_height), (4800, 3600))

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
            self.assertTrue({card.asset for card in FAMILIES}.issubset(paths))
        self.app.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_F5))
        self.assertEqual(self.game.player.job, "guardian")
        self.game._add_score(7980 - self.game.score)
        self.assertEqual([c.key for c in self.game.reward_choices], ["bastion", "aegis"])
        with patch.object(self.renderer.assets, "image", wraps=self.renderer.assets.image) as image:
            self.app.draw(ObsConfig())
            paths = {call.args[0] for call in image.call_args_list}
            self.assertTrue({SHIPS["bastion"].asset, SHIPS["aegis"].asset}.issubset(paths))
        for coords in special_cards(*self.renderer.size):
            self.assertEqual(pygame.Rect(coords).size, (90, 90))

    def test_stats_always_show_five_fixed_choices_and_all_number_keys_work(self):
        choices = self.game.stat_choices
        self.assertEqual(choices, STAT_UPGRADES)
        self.assertEqual([c.title for c in choices], ["체력", "공격력", "사거리 및 탄속도", "발사속도", "이동속도"])
        self.app.draw(ObsConfig())
        self.game._add_score(1000)
        points = self.game.upgrade_points
        for i, key in enumerate((pygame.K_1, pygame.K_2, pygame.K_3, pygame.K_4, pygame.K_5)):
            self.app.handle_event(pygame.event.Event(pygame.KEYDOWN, key=key))
            self.assertEqual(self.game.stat_levels[choices[i].key], 1)
        self.assertEqual(self.game.upgrade_points, points - 5)
        self.assertEqual(self.game.stat_choices, choices)
        self.app.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE))
        self.app.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE))
        self.assertEqual(self.game.stat_choices, choices)
        for coords in (row[1] for row in stat_rows(960, 640)):
            self.assertTrue(pygame.Rect(0, 0, 960, 640).contains(pygame.Rect(coords)))

    def test_all_ship_sprites_render_and_transform_cache_reuses_images(self):
        for key in SHIPS:
            with self.subTest(ship=key):
                self.game.player.job = key
                self.renderer.draw(self.game)
                image = self.renderer.assets.image(SHIPS[key].asset, 62)
                self.assertIs(image, self.renderer.assets.image(SHIPS[key].asset, 62))
        self.renderer.resize((4000, 2400))
        self.assertLessEqual(self.renderer.view_width, self.cfg.world_width)
        self.assertLessEqual(self.renderer.view_height, self.cfg.world_height)

    def test_player_sprite_faces_right_and_enemy_keeps_original_orientation(self):
        import math
        self.game.player.angle = math.pi / 2
        with patch.object(self.renderer.assets, "ship_image", wraps=self.renderer.assets.ship_image) as image:
            self.renderer._draw_ship(self.game.player, 100, is_player=True)
            self.assertEqual(image.call_args.args[0], SHIPS["rookie"].asset)
            self.assertAlmostEqual(image.call_args.args[2], -90)
        self.cfg.num_enemies = 1
        try:
            self.game.reset(7)
            enemy = self.game.enemies[0]
            enemy.angle = math.pi / 2
            # 적도 같은 진화 그림(일반은 붉은색, 엘리트는 금색)을 쓰므로 플레이어와 같은 방향 규칙을 따른다.
            for elite, suffix in ((False, "@enemy"), (True, "@elite")):
                enemy.elite = elite
                with patch.object(self.renderer.assets, "ship_image", wraps=self.renderer.assets.ship_image) as image:
                    self.renderer._draw_ship(enemy, 100)
                    self.assertEqual(image.call_args.args[0], SHIPS[enemy.job].asset + suffix)
                    self.assertAlmostEqual(image.call_args.args[2], -90)
        finally:
            self.cfg.num_enemies = 0

    def test_21_original_transparent_sprites_fit_body_collision_diameter(self):
        import numpy as np
        self.assertEqual(len(SHIPS), 21)
        for spec in SHIPS.values():
            with self.subTest(ship=spec.key):
                source = self.renderer.assets._source(spec.asset)
                self.assertEqual(source.get_size(), (512, 512))
                self.assertEqual(int(pygame.surfarray.array_alpha(source).min()), 0)
                image = self.renderer.assets.ship_image(spec.asset, 60)
                rgb = pygame.surfarray.array3d(image).astype(np.int16)
                alpha = pygame.surfarray.array_alpha(image)
                xs, ys = np.where((alpha > 100) & (rgb[:, :, 1] > rgb[:, :, 0] + 30)
                                  & (rgb[:, :, 2] > rgb[:, :, 0] + 30))
                self.assertAlmostEqual(max(xs.max() - xs.min() + 1, ys.max() - ys.min() + 1), 60, delta=3)
                self.assertAlmostEqual((xs.max() + xs.min()) / 2, image.get_width() / 2, delta=2)
                self.assertAlmostEqual((ys.max() + ys.min()) / 2, image.get_height() / 2, delta=2)

    def test_projectile_core_width_matches_physical_diameter_and_cache_reuses_images(self):
        assets = self.renderer.assets
        for path in ("projectiles/player_plasma", "projectiles/enemy_plasma", "projectiles/cannon_shell"):
            with self.subTest(path=path):
                source = assets._source(path)
                self.assertEqual(source.get_size(), (1254, 1254))
                base = assets._projectile_base(path)
                core = assets._projectile_geometry(path)
                self.assertLessEqual(base.get_width(), core.width * 2.5)
                for diameter in (4, 12, 24):
                    image = assets.projectile_image(path, diameter)
                    visible = image.get_bounding_rect(min_alpha=100)
                    self.assertAlmostEqual(visible.width, diameter, delta=2)
                    self.assertAlmostEqual(visible.centerx, image.get_width() / 2, delta=1.5)
                    self.assertAlmostEqual(visible.centery, image.get_height() / 2, delta=1.5)
                    self.assertLessEqual(image.get_width(), diameter * 2.5 + 2)
                    self.assertIs(image, assets.projectile_image(path, diameter))
                    turned = assets.projectile_image(path, diameter, -90)
                    self.assertAlmostEqual(turned.get_bounding_rect(min_alpha=100).height, diameter, delta=2)
                    self.assertIs(turned, assets.projectile_image(path, diameter, -90))

    def test_world_ship_render_size_tracks_doubled_radius_without_growing_cards(self):
        p = self.game.player
        self.assertEqual(p.radius, 44)
        with patch.object(self.renderer.assets, "ship_image", wraps=self.renderer.assets.ship_image) as image:
            self.renderer._draw_ship(p, 100, is_player=True)
            self.assertEqual(image.call_args.args[1], 88)
        self.assertEqual(self.renderer.assets.image(SHIPS["rookie"].asset, 62).get_size(), (62, 62))


if __name__ == "__main__":
    unittest.main()
