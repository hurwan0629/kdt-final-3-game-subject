"""중앙 추적, 월드 확장, 외곽 벽띠 제거 회귀 검사."""

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
import numpy as np
import pygame
from space_z.game import terrain
from space_z.config import GameConfig, TerrainConfig
from space_z.game.game_core import GameCore
from space_z.rendering.renderer import Renderer


class ExpandedWorldTests(unittest.TestCase):
    def test_default_area_and_enemy_population(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        config = GameConfig(num_shapes=0)

        # 기본 월드 면적·타일 수·적 수와 개체 경계 보정을 확인한다.
        self.assertEqual((config.world_width, config.world_height), (6432, 4848))
        self.assertAlmostEqual(
            config.world_width * config.world_height / (4800 * 3600), 1.8, delta=0.01
        )
        game = GameCore(config, seed=22)
        self.assertEqual((game.terrain.cols, game.terrain.rows), (134, 101))
        self.assertEqual(len(game.enemies), 9)
        player = game.player
        player.x, player.y = -100, config.world_height + 100
        game._clamp_to_arena(player)
        self.assertEqual(
            (player.x, player.y), (player.radius, config.world_height - player.radius)
        )

    def test_outer_band_removal_preserves_every_interior_tile(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        original = terrain._clear_outer_wall_band
        calls = []

        # 외곽 벽띠만 지워지고 모든 내부 타일은 유지되는지 확인한다.
        def observe(tiles, **bands):
            before = [row[:] for row in tiles]
            original(tiles, **bands)
            rows, cols = len(tiles), len(tiles[0])
            for row_index, row in enumerate(tiles):
                for col, value in enumerate(row):
                    band = (
                        col < bands["left"]
                        or col >= cols - bands["right"]
                        or row_index < bands["top"]
                        or row_index >= rows - bands["bottom"]
                    )
                    expected = (
                        terrain.EMPTY
                        if band
                        and before[row_index][col] in (terrain.WALL, terrain.BREAKABLE)
                        else before[row_index][col]
                    )
                    self.assertEqual(value, expected)
            calls.append(bands)

        for stage2 in (False, True):
            config = TerrainConfig(mud_enabled=stage2, breakable_enabled=stage2)
            with patch.object(terrain, "_clear_outer_wall_band", side_effect=observe):
                maps = [
                    terrain.generate_random_map(
                        np.random.default_rng(3), config, 134, 101
                    )
                ]
                maps += [
                    terrain.load_map(name, config, 134, 101)
                    for name in terrain.list_maps()
                ]
            for tile_map in maps:
                self.assertTrue(tile_map.is_connected())
                self.assertTrue(tile_map.is_connected(96))
                self.assertTrue(any(any(row) for row in tile_map.solid))
                self.assertFalse(any(tile_map.solid[0]))
                self.assertFalse(any(tile_map.solid[-1]))
                self.assertFalse(any(row[0] or row[-1] for row in tile_map.solid))
        self.assertGreaterEqual(len(calls), 10)


class CenteredCameraTests(unittest.TestCase):
    def test_every_zoom_and_corner_keeps_fractional_player_centered(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        pygame.init()
        config = GameConfig(
            num_enemies=0,
            num_shapes=0,
            world_scale=1,
        )
        config.terrain.enabled = False
        game = GameCore(config, seed=7)
        renderer = Renderer(config)

        # 줌·창 크기·월드 모서리 위치에 관계없이 플레이어가 중앙에 오는지 확인한다.
        try:
            for size in ((1280, 800), (1281, 801)):
                renderer.resize(size)
                for zoom in (0.45, 0.6, 0.75, 1.0):
                    renderer.set_zoom(zoom)
                    self.assertEqual(renderer.effective_zoom, zoom)
                    player = game.player
                    for x, y in (
                        (player.radius, player.radius),
                        (config.world_width - player.radius, player.radius),
                        (player.radius, config.world_height - player.radius),
                        (
                            config.world_width - player.radius,
                            config.world_height - player.radius,
                        ),
                        (123.25, 234.75),
                    ):
                        player.x, player.y = x, y
                        renderer._update_camera(player)
                        self.assertEqual(
                            renderer.world_to_screen(x, y), (size[0] / 2, size[1] / 2)
                        )
                        view_x, view_y = renderer.world_to_view(x, y)
                        self.assertEqual(
                            (round(view_x), round(view_y)),
                            (renderer.view_width / 2, renderer.view_height / 2),
                        )
                        self.assertEqual(
                            renderer.screen_to_world(size[0] / 2, size[1] / 2), (x, y)
                        )
                    renderer.draw(game)
            config.limited_ammo = False
            with patch.object(renderer, "_panel", wraps=renderer._panel) as panel:
                renderer._draw_hud(game, False)
                self.assertFalse(
                    any(
                        call.args[0].x == renderer.size[0] - 198
                        for call in panel.call_args_list
                    )
                )
        finally:
            pygame.quit()


if __name__ == "__main__":
    unittest.main()
