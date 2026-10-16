"""중앙 추적, 월드 확장, 외곽 벽띠 제거 회귀 검사."""
import os
import unittest
from unittest.mock import patch
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
import numpy as np
import pygame
import terrain
from config import GameConfig, TerrainConfig
from game_core import GameCore
from renderer import Renderer

class ExpandedWorldTests(unittest.TestCase):
    def test_default_area_and_enemy_population(self):
        cfg = GameConfig(num_shapes=0)
        self.assertEqual((cfg.world_width, cfg.world_height), (6432, 4848))
        self.assertAlmostEqual(cfg.world_width * cfg.world_height / (4800 * 3600), 1.8, delta=.01)
        game = GameCore(cfg, seed=22)
        self.assertEqual((game.terrain.cols, game.terrain.rows), (134, 101))
        self.assertEqual(len(game.enemies), 9)
        p = game.player
        p.x, p.y = -100, cfg.world_height + 100
        game._clamp_to_arena(p)
        self.assertEqual((p.x, p.y), (p.radius, cfg.world_height - p.radius))

    def test_outer_band_removal_preserves_every_interior_tile(self):
        original = terrain._clear_outer_wall_band
        calls = []
        def observe(tiles, **bands):
            before = [row[:] for row in tiles]
            original(tiles, **bands)
            rows, cols = len(tiles), len(tiles[0])
            for r, row in enumerate(tiles):
                for c, value in enumerate(row):
                    band = (c < bands["left"] or c >= cols - bands["right"]
                            or r < bands["top"] or r >= rows - bands["bottom"])
                    expected = terrain.EMPTY if band and before[r][c] in (terrain.WALL, terrain.BREAKABLE) else before[r][c]
                    self.assertEqual(value, expected)
            calls.append(bands)
        for stage2 in (False, True):
            cfg = TerrainConfig(mud_enabled=stage2, breakable_enabled=stage2)
            with patch.object(terrain, "_clear_outer_wall_band", side_effect=observe):
                maps = [terrain.generate_random_map(np.random.default_rng(3), cfg, 134, 101)]
                maps += [terrain.load_map(name, cfg, 134, 101) for name in terrain.list_maps()]
            for tm in maps:
                self.assertTrue(tm.is_connected())
                self.assertTrue(tm.is_connected(96))
                self.assertTrue(any(any(row) for row in tm.solid))
                self.assertFalse(any(tm.solid[0]))
                self.assertFalse(any(tm.solid[-1]))
                self.assertFalse(any(row[0] or row[-1] for row in tm.solid))
        self.assertGreaterEqual(len(calls), 10)

class CenteredCameraTests(unittest.TestCase):
    def test_every_zoom_and_corner_keeps_fractional_player_centered(self):
        pygame.init()
        cfg = GameConfig(num_enemies=0, num_shapes=0, world_scale=1)
        cfg.terrain.enabled = False
        game = GameCore(cfg, seed=7)
        renderer = Renderer(cfg)
        try:
            for size in ((1280, 800), (1281, 801)):
                renderer.resize(size)
                for zoom in (.45, .6, .75, 1.0):
                    renderer.set_zoom(zoom)
                    self.assertEqual(renderer.effective_zoom, zoom)
                    p = game.player
                    for x, y in ((p.radius, p.radius), (cfg.world_width-p.radius, p.radius),
                                 (p.radius, cfg.world_height-p.radius),
                                 (cfg.world_width-p.radius, cfg.world_height-p.radius), (123.25, 234.75)):
                        p.x, p.y = x, y
                        renderer._update_camera(p)
                        self.assertEqual(renderer.world_to_screen(x, y), (size[0]/2, size[1]/2))
                        vx, vy = renderer.world_to_view(x, y)
                        self.assertEqual((round(vx), round(vy)), (renderer.view_width/2, renderer.view_height/2))
                        self.assertEqual(renderer.screen_to_world(size[0]/2, size[1]/2), (x, y))
                    renderer.draw(game)
            cfg.limited_ammo = False
            with patch.object(renderer, "_panel", wraps=renderer._panel) as panel:
                renderer._draw_hud(game, False)
                self.assertFalse(any(call.args[0].x == renderer.size[0]-198 for call in panel.call_args_list))
        finally:
            pygame.quit()

if __name__ == "__main__":
    unittest.main()
