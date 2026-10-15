"""전체 맵, 방향 마커, 지형 캐시와 창 크기에 따른 미니맵 검증."""
import math
import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import pygame

from config import GameConfig
from game_core import GameCore, Tank
from renderer import Renderer, COLORS
from terrain import TileMap, EMPTY, WALL, BREAKABLE


class MinimapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()
        cls.cfg = GameConfig(num_enemies=0, num_shapes=0, world_scale=1)
        cls.cfg.terrain.enabled = False
        cls.cfg.terrain.breakable_enabled = True
        cls.renderer = Renderer(cls.cfg)

    @classmethod
    def tearDownClass(cls):
        pygame.quit()

    def setUp(self):
        self.renderer.resize((1280, 800))
        self.game = GameCore(self.cfg, seed=3)
        self.game.player.x, self.game.player.y, self.game.player.angle = 100, 100, 0
        tiles = [[EMPTY] * 20 for _ in range(15)]
        tiles[0][0] = tiles[-1][-1] = WALL
        tiles[6][10] = BREAKABLE
        self.game.terrain = TileMap(tiles, 48, (2, 2), [], "minimap-test", self.cfg.terrain)

    def test_full_world_walls_are_drawn_on_light_background(self):
        r = self.renderer
        r._draw_minimap(self.game)
        area = r.minimap_rect().inflate(-12, -12)
        self.assertEqual(r.screen.get_at((area.left + 1, area.top + 1))[:3], COLORS["minimap_wall"])
        self.assertEqual(r.screen.get_at((area.right - 2, area.bottom - 2))[:3], COLORS["minimap_wall"])
        self.assertEqual(r.screen.get_at(area.center)[:3], COLORS["minimap_floor"])

    def test_marker_position_and_direction_ignore_camera_and_zoom(self):
        r, p = self.renderer, self.game.player
        p.x, p.y = 720, 180
        for zoom in (0.45, 0.6, 0.75, 1.0):
            r.set_zoom(zoom)
            r.camera_x, r.camera_y = 5000, -2000
            area = r.minimap_rect().inflate(-12, -12)
            center = (area.left + area.width * 0.75, area.top + area.height * 0.25)
            for angle, offset in ((0, (6, 0)), (math.pi / 2, (0, 6)),
                                  (math.pi, (-6, 0)), (-math.pi / 2, (0, -6))):
                p.angle = angle
                tip = r._minimap_marker(self.game, area)[0]
                self.assertAlmostEqual(tip[0], center[0] + offset[0])
                self.assertAlmostEqual(tip[1], center[1] + offset[1])

    def test_moving_and_turning_player_reuses_static_map_but_wall_destruction_refreshes_it(self):
        r, tm = self.renderer, self.game.terrain
        r._draw_minimap(self.game)
        original = r._minimap_floor
        self.game.player.x, self.game.player.angle = 600, 1.2
        r._draw_minimap(self.game)
        self.assertIs(r._minimap_floor, original)
        tm.damage_tile(10, 6, tm.breakable_hp_max)
        r._draw_minimap(self.game)
        self.assertIsNot(r._minimap_floor, original)
        area = r.minimap_rect().inflate(-12, -12)
        point = (round(10.5 * area.width / 20), round(6.5 * area.height / 15))
        self.assertEqual(r._minimap_floor.get_at(point)[:3], COLORS["minimap_floor"])
        previous = r._minimap_floor
        self.game.terrain = TileMap([[EMPTY] * 20 for _ in range(15)], 48, (2, 2), [], "new", self.cfg.terrain)
        r._draw_minimap(self.game)
        self.assertIsNot(r._minimap_floor, previous)

    def test_enemies_and_experience_objects_do_not_appear(self):
        r = self.renderer
        r._draw_minimap(self.game)
        area = r.minimap_rect()
        before = pygame.image.tobytes(r.screen.subsurface(area), "RGB")
        self.game.enemies = [Tank(100, "enemy", 800, 600, 60, 60, 44, 36)]
        self.game.shapes = [SimpleNamespace(x=600, y=500, radius=26)]
        r._draw_minimap(self.game)
        self.assertEqual(pygame.image.tobytes(r.screen.subsurface(area), "RGB"), before)

    def test_resize_keeps_map_aspect_bottom_right_margin_and_hud_separation(self):
        r = self.renderer
        for size in ((960, 640), (1280, 800), (1920, 1080), (4000, 2400)):
            with self.subTest(size=size):
                r.resize(size)
                r._draw_minimap(self.game)
                rect = r.minimap_rect()
                area = rect.inflate(-12, -12)
                self.assertEqual(rect.right, size[0] - 14)
                self.assertEqual(rect.bottom, size[1] - 14)
                self.assertTrue(pygame.Rect((0, 0), size).contains(rect))
                self.assertAlmostEqual(area.width / area.height, 4 / 3, delta=0.02)
                self.assertFalse(rect.colliderect(pygame.Rect(size[0] // 2 - 166, size[1] - 100, 332, 84)))
                self.assertFalse(rect.colliderect(pygame.Rect(14, size[1] - 180, 272, 164)))
                self.assertEqual(r._minimap_floor.get_size(), area.size)


if __name__ == "__main__":
    unittest.main()
