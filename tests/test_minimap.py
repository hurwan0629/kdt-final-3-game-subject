"""전체 맵, 방향 마커, 지형 캐시와 창 크기에 따른 미니맵 검증."""

import math
import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import pygame

from space_z.config import GameConfig
from space_z.game.game_core import GameCore, Tank
from space_z.rendering.renderer import Renderer, COLORS, MINIMAP_ALPHA
from space_z.game.terrain import TileMap, EMPTY, WALL, BREAKABLE


class MinimapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        pygame.init()
        cls.config = GameConfig(
            num_enemies=0,
            num_shapes=0,
            world_scale=1,
            world_area_scale=1,
        )
        cls.config.terrain.enabled = False
        cls.config.terrain.breakable_enabled = True
        cls.renderer = Renderer(cls.config)

    @classmethod
    def tearDownClass(cls):
        pygame.quit()

    def setUp(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        self.renderer.resize((1280, 800))
        self.game = GameCore(self.config, seed=3)
        self.game.player.x, self.game.player.y, self.game.player.angle = 100, 100, 0
        tiles = [[EMPTY] * 20 for _ in range(15)]
        tiles[0][0] = tiles[-1][-1] = WALL
        tiles[6][10] = BREAKABLE
        self.game.terrain = TileMap(
            tiles, 48, (2, 2), [], "minimap-test", self.config.terrain
        )

    @staticmethod
    def _blended(color, background=(0, 0, 0)):
        """미니맵이 지금은 반투명이라, 같은 방식으로 합성한 값과 비교해야 한다."""
        base = pygame.Surface((1, 1))
        base.fill(background)
        layer = pygame.Surface((1, 1), pygame.SRCALPHA)
        layer.fill(color)
        layer.set_alpha(MINIMAP_ALPHA)
        base.blit(layer, (0, 0))
        return base.get_at((0, 0))[:3]

    def test_full_world_walls_are_drawn_on_light_background(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        renderer = self.renderer
        renderer.screen.fill((0, 0, 0))
        renderer._draw_minimap(self.game)
        area = renderer.minimap_rect().inflate(-12, -12)

        # 미니맵의 바닥과 벽 색상이 전체 월드 지형과 맞는지 확인한다.
        self.assertEqual(
            renderer.screen.get_at((area.left + 1, area.top + 1))[:3],
            self._blended(COLORS["minimap_wall"]),
        )
        self.assertEqual(
            renderer.screen.get_at((area.right - 2, area.bottom - 2))[:3],
            self._blended(COLORS["minimap_wall"]),
        )
        self.assertEqual(
            renderer.screen.get_at(area.center)[:3],
            self._blended(COLORS["minimap_floor"]),
        )

    def test_marker_position_and_direction_ignore_camera_and_zoom(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        renderer, player = self.renderer, self.game.player
        player.x, player.y = 720, 180

        # 플레이어 표시 위치·방향이 카메라와 줌에 영향을 받지 않는지 확인한다.
        for zoom in (0.45, 0.6, 0.75, 1.0):
            renderer.set_zoom(zoom)
            renderer.camera_x, renderer.camera_y = 5000, -2000
            area = renderer.minimap_rect().inflate(-12, -12)
            center = (area.left + area.width * 0.75, area.top + area.height * 0.25)
            for angle, offset in (
                (0, (6, 0)),
                (math.pi / 2, (0, 6)),
                (math.pi, (-6, 0)),
                (-math.pi / 2, (0, -6)),
            ):
                player.angle = angle
                tip = renderer._minimap_marker(self.game, area)[0]
                self.assertAlmostEqual(tip[0], center[0] + offset[0])
                self.assertAlmostEqual(tip[1], center[1] + offset[1])

    def test_moving_and_turning_player_reuses_static_map_but_wall_destruction_refreshes_it(
        self,
    ):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        renderer, terrain = self.renderer, self.game.terrain
        renderer._draw_minimap(self.game)
        original = renderer._minimap_floor
        self.game.player.x, self.game.player.angle = 600, 1.2
        renderer._draw_minimap(self.game)

        # 플레이어 이동은 지형 캐시를 유지하고 벽 파괴는 갱신하는지 확인한다.
        self.assertIs(renderer._minimap_floor, original)
        terrain.damage_tile(10, 6, terrain.breakable_hp_max)
        renderer._draw_minimap(self.game)
        self.assertIsNot(renderer._minimap_floor, original)
        area = renderer.minimap_rect().inflate(-12, -12)
        point = (round(10.5 * area.width / 20), round(6.5 * area.height / 15))
        self.assertEqual(
            renderer._minimap_floor.get_at(point)[:3], COLORS["minimap_floor"]
        )
        previous = renderer._minimap_floor
        self.game.terrain = TileMap(
            [[EMPTY] * 20 for _ in range(15)],
            48,
            (2, 2),
            [],
            "new",
            self.config.terrain,
        )
        renderer._draw_minimap(self.game)
        self.assertIsNot(renderer._minimap_floor, previous)

    def test_enemies_and_experience_objects_do_not_appear(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        renderer = self.renderer
        renderer.screen.fill((0, 0, 0))
        renderer._draw_minimap(self.game)
        area = renderer.minimap_rect()
        before = pygame.image.tobytes(renderer.screen.subsurface(area), "RGB")
        # 미니맵이 반투명해지면서 매 프레임 바탕을 다시 채우지 않으면 이전 합성 결과 위에
        # 또 겹쳐 그려져 색이 누적된다. 실제 게임은 매 프레임 화면을 새로 채우므로 여기서도
        # 같은 조건으로 다시 채운 뒤 비교한다.
        renderer.screen.fill((0, 0, 0))
        self.game.enemies = [
            Tank(
                100,
                "enemy",
                800,
                600,
                60,
                60,
                44,
                36,
            )
        ]
        self.game.shapes = [SimpleNamespace(x=600, y=500, radius=26)]
        renderer._draw_minimap(self.game)

        # 미니맵에 적과 경험치 천체가 표시되지 않는지 확인한다.
        self.assertEqual(
            pygame.image.tobytes(renderer.screen.subsurface(area), "RGB"), before
        )

    def test_resize_keeps_map_aspect_bottom_right_margin_and_hud_separation(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        renderer = self.renderer

        # 창 크기가 달라져도 미니맵 비율과 우하단 여백을 유지하는지 확인한다.
        for size in ((960, 640), (1280, 800), (1920, 1080), (4000, 2400)):
            with self.subTest(size=size):
                renderer.resize(size)
                renderer._draw_minimap(self.game)
                rect = renderer.minimap_rect()
                area = rect.inflate(-12, -12)
                self.assertEqual(rect.right, size[0] - 14)
                self.assertEqual(rect.bottom, size[1] - 14)
                self.assertTrue(pygame.Rect((0, 0), size).contains(rect))
                self.assertAlmostEqual(area.width / area.height, 4 / 3, delta=0.02)
                self.assertFalse(
                    rect.colliderect(
                        pygame.Rect(size[0] // 2 - 166, size[1] - 100, 332, 84)
                    )
                )
                self.assertFalse(
                    rect.colliderect(pygame.Rect(14, size[1] - 180, 272, 164))
                )
                self.assertEqual(renderer._minimap_floor.get_size(), area.size)


if __name__ == "__main__":
    unittest.main()
