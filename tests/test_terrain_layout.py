"""큰 벽/넓은 통로와 선체 크기를 고려한 길 찾기 회귀 검사."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch
from pathlib import Path
from collections import deque

from space_z.game import terrain

import numpy as np

from space_z.config import TerrainConfig, GameConfig, ObsConfig
from space_z.game.terrain import (
    TileMap,
    EMPTY,
    WALL,
    BREAKABLE,
    MapError,
    grid_channels,
    list_maps,
    load_map,
    parse_map,
    expand_map,
    generate_random_map,
    map_to_text,
)


class LargeWallLayoutTests(unittest.TestCase):
    def assert_thick_walls(self, terrain, minimum=4):
        for row in range(terrain.rows):
            for col in range(terrain.cols):
                if not terrain.solid[row][col]:
                    continue
                self.assertTrue(
                    any(
                        all(
                            0 <= tile_col < terrain.cols
                            and 0 <= tile_row < terrain.rows
                            and terrain.solid[tile_row][tile_col]
                            for tile_row in range(first_row, first_row + minimum)
                            for tile_col in range(first_col, first_col + minimum)
                        )
                        for first_row in range(row - minimum + 1, row + 1)
                        for first_col in range(col - minimum + 1, col + 1)
                    ),
                    f"thin wall at {terrain.name}: {(col, row)}",
                )

    def assert_connected_walls(self, terrain):
        solid = {
            (col, row)
            for row in range(terrain.rows)
            for col in range(terrain.cols)
            if terrain.solid[row][col]
        }
        self.assertTrue(solid)
        start = next(iter(solid))
        seen, queue = {start}, deque([start])
        while queue:
            col, row = queue.popleft()
            for delta_col, delta_row in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                next_tile = (col + delta_col, row + delta_row)
                if next_tile in solid and next_tile not in seen:
                    seen.add(next_tile)
                    queue.append(next_tile)
        self.assertEqual(seen, solid, "walls should form a connected maze network")

    def test_whole_world_maps_and_custom_sizes_fit_doubled_guardian(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        for stage2 in (False, True):
            config = TerrainConfig(mud_enabled=stage2, breakable_enabled=stage2)
            for name in list_maps():
                for cols, rows in ((60, 45), (20, 15)):
                    with self.subTest(map=name, size=(cols, rows), stage2=stage2):
                        terrain = load_map(name, config, cols, rows)
                        self.assertEqual((terrain.cols, terrain.rows), (cols, rows))
                        self.assertNotIn("*", map_to_text(terrain))
                        self.assertTrue(terrain.is_connected())
                        self.assertTrue(terrain.is_connected(96))
                        self.assert_thick_walls(terrain, 2)
                        for goal in terrain.enemy_starts:
                            self.assertTrue(
                                terrain.circle_fits(*terrain.center(*goal), 96)
                            )
                            path = terrain.astar(terrain.player_start, goal, radius=96)
                            self.assertTrue(path)
                            previous = terrain.player_start
                            for step in path:
                                self.assertTrue(
                                    terrain.segment_fits(
                                        *terrain.center(*previous),
                                        *terrain.center(*step),
                                        96,
                                    )
                                )
                                previous = step

    def test_default_maps_load_the_authored_full_world_without_generation(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        config = TerrainConfig(mud_enabled=True, breakable_enabled=True)
        layouts = []

        # 기본 크기 맵은 생성기 대신 작성된 파일 지형을 사용하는지 확인한다.
        for name in list_maps():
            path = Path(terrain.resource_path("maps")) / (name + ".txt")
            expected = parse_map(path.read_text(encoding="utf-8"), name, config, 60, 45)
            with patch.object(
                terrain,
                "_generate_maze",
                side_effect=AssertionError("do not generate default map"),
            ):
                actual = load_map(name, config, 60, 45)
            self.assertEqual(actual.tiles, expected.tiles)
            self.assertEqual(actual.player_start, expected.player_start)
            self.assertEqual(actual.enemy_starts, expected.enemy_starts)
            self.assertTrue(
                any(
                    actual.tiles[row_index][col]
                    != actual.tiles[row_index % 15][col % 20]
                    for row_index in range(45)
                    for col in range(60)
                )
            )
            layouts.append(tuple(tuple(row) for row in actual.tiles))
        self.assertEqual(len(set(layouts)), 4)

    def test_custom_size_generation_cannot_hide_damaged_builtin_files(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        config = TerrainConfig()
        valid = Path(terrain.resource_path("maps/drift.txt")).read_text(
            encoding="utf-8"
        )
        data = [
            line for line in valid.splitlines() if line and not line.startswith(";")
        ]
        cases = (
            "\n".join(data[:-1]),
            "\n".join([data[0][:-1]] + data[1:]),
            "\n".join(["?" + data[0][1:]] + data[1:]),
        )

        # 다른 크기의 맵 요청으로 손상된 원본 파일이 숨겨지지 않는지 확인한다.
        for damaged in cases:
            with (
                self.subTest(damage=damaged[:10]),
                patch.dict(terrain._MAP_TEXT_CACHE, {"drift": damaged}),
            ):
                with self.assertRaises(MapError):
                    load_map("drift", config, 20, 15)

    def test_random_maps_are_open_block_mazes(self):
        # 기본 랜덤 지형은 diep.io 미로 모드처럼 큰 블록 미로에 통로를 더 뚫은 형태다.
        # 실제 게임은 world_scale=3이라 항상 60x45로만 생성한다(_make_terrain).
        # 20x15는 작은 캔버스에서도 생성기 자체가 안전한지 보는 용도라, 기본
        # block_tiles(8, 60x45 기준으로 고른 값)를 그대로 쓰면 블록 하나가 캔버스의
        # 절반 가까이 되어 답답해진다 — 그 경우에는 예전 기본값(5)으로 돌려 확인한다.
        large_map_config = TerrainConfig(mud_enabled=True, breakable_enabled=True)
        small_map_config = TerrainConfig(
            mud_enabled=True, breakable_enabled=True, block_tiles=5
        )

        # 랜덤 블록 맵의 연결성·벽 두께·빈 공간 비율과 시드 재현성을 확인한다.
        for cols, rows, seeds, config in (
            (20, 15, range(50), small_map_config),
            (60, 45, range(10), large_map_config),
        ):
            for seed in seeds:
                with self.subTest(size=(cols, rows), seed=seed):
                    terrain = generate_random_map(
                        np.random.default_rng(seed), config, cols, rows
                    )
                    self.assertTrue(terrain.is_connected())
                    self.assertTrue(terrain.is_connected(96))
                    self.assertTrue(
                        terrain.circle_fits(*terrain.center(*terrain.player_start), 96)
                    )
                    # block_tiles=8은 60/45와 나누어떨어지지 않아 테두리가 2칸으로 얇아질 수
                    # 있다(안쪽 벽은 여전히 8칸). is_connected(96)/A* 등 실제 통과 가능성은
                    # 위에서 이미 검증하므로 두께 자체는 2칸 이상이면 충분하다.
                    self.assert_thick_walls(terrain, 2)
                    self.assertNotIn("*", map_to_text(terrain))
                    solid = sum(
                        terrain.solid[row][col]
                        for row in range(rows)
                        for col in range(cols)
                    )
                    self.assertLess(solid / (cols * rows), 0.4)  # 너무 갑갑하지 않게
                    if cols == 60:
                        self.assertGreater(
                            solid, 0
                        )  # 외곽 벽띠를 빼도 내부 장애물은 유지
                        self.assertGreaterEqual(len(terrain.enemy_starts), 8)
        first_map = generate_random_map(np.random.default_rng(12), config, 60, 45)
        replayed_map = generate_random_map(np.random.default_rng(12), config, 60, 45)
        self.assertEqual(map_to_text(first_map), map_to_text(replayed_map))
        self.assertEqual(first_map.enemy_starts, replayed_map.enemy_starts)

    def test_removed_stealth_marker_is_rejected(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        lines = ["......."] * 7
        lines[3] = "...P..."
        lines[2] = "..*...."

        # 제거된 은신 지형 문자가 잘못된 맵으로 거부되는지 확인한다.
        with self.assertRaisesRegex(MapError, "알 수 없는 지형"):
            parse_map("\n".join(lines), "stealth", TerrainConfig(), 7, 7)
        self.assertEqual(grid_channels(TerrainConfig()), ["wall"])
        self.assertEqual(
            grid_channels(TerrainConfig(mud_enabled=True, breakable_enabled=True)),
            ["wall", "mud", "breakable"],
        )

    def test_astar_accounts_for_doubled_hull_and_five_tile_opening(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        for opening in ((5, 6, 7), (4, 5, 6, 7, 8)):
            grid = [[EMPTY] * 13 for _ in range(13)]
            grid[6] = [EMPTY if col in opening else WALL for col in range(13)]
            terrain = TileMap(grid, 48, (6, 2), [], "passage", TerrainConfig())
            self.assertTrue(terrain.astar((6, 2), (6, 10), radius=44))
            self.assertEqual(
                bool(terrain.astar((6, 2), (6, 10), radius=96)), len(opening) == 5
            )

    def test_clear_view_can_still_be_too_narrow_for_a_hull(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        grid = [[EMPTY] * 9 for _ in range(9)]
        grid[4][4] = WALL
        terrain = TileMap(grid, 48, (2, 2), [], "corner", TerrainConfig())

        # 시야선이 열려 있어도 큰 선체가 못 지나는 좁은 통로를 구분하는지 확인한다.
        self.assertTrue(terrain.line_of_sight(100, 160, 300, 160))
        self.assertFalse(terrain.segment_fits(100, 160, 300, 160, 48))
        self.assertTrue(terrain.segment_fits(100, 140, 300, 140, 48))
        self.assertTrue(terrain.segment_fits(100, 160, 152, 160, 48))
        self.assertFalse(terrain.circle_fits(24, 100, 48))
        self.assertTrue(terrain.circle_fits(48, 100, 48))

    def test_breaking_a_wall_refreshes_navigation_cache(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        grid = [[EMPTY] * 9 for _ in range(9)]
        grid[4] = [WALL] * 9
        grid[4][4] = BREAKABLE
        config = TerrainConfig(breakable_enabled=True)
        terrain = TileMap(grid, 48, (4, 1), [], "breakable", config)

        # 벽 파괴 뒤 이동 가능 타일과 경로 캐시가 갱신되는지 확인한다.
        self.assertFalse(terrain.astar((4, 1), (4, 7), radius=22))
        self.assertTrue(terrain.damage_tile(4, 4, config.breakable_hp))
        self.assertTrue(terrain.astar((4, 1), (4, 7), radius=22))

    def test_doubled_guardian_collision_slides_without_leaving_overlap(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        grid = [[EMPTY] * 9 for _ in range(9)]
        for row in range(2, 7):
            grid[row][4] = WALL
        terrain = TileMap(grid, 48, (2, 2), [], "slide", TerrainConfig())
        ship = SimpleNamespace(
            x=97.0, y=216.0, radius=96.0, velocity_x=3.0, velocity_y=2.0
        )

        # 큰 선체가 벽에 겹치지 않으면서 벽을 따라 미끄러지는지 확인한다.
        self.assertTrue(terrain.resolve_circle(ship))
        self.assertTrue(terrain.circle_fits(ship.x, ship.y, ship.radius))
        self.assertEqual(ship.velocity_x, 0)
        self.assertEqual(ship.velocity_y, 2)


class SweptCircleTests(unittest.TestCase):
    def setUp(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        grid = [[EMPTY] * 20 for _ in range(15)]
        grid[10][10] = WALL
        self.terrain = TileMap(grid, 48, (2, 2), [], "swept", TerrainConfig())

    def test_diagonal_round_overlaps_wall_even_when_center_ray_misses(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        diagonal = 2**-0.5
        distance = (28.8**2 + 28.8**2) ** 0.5

        # 중심 광선이 벽을 비껴가도 탄체 반지름의 충돌을 감지하는지 확인한다.
        self.assertTrue(self.terrain.line_of_sight(450, 502, 478.8, 530.8))
        hit, cell = self.terrain.sweep_circle(450, 502, diagonal, diagonal, distance, 6)
        self.assertEqual(cell, (10, 10))
        self.assertAlmostEqual(hit, 24 / diagonal)
        self.assertLess(hit, distance)

    def test_rounded_corner_is_exact_and_does_not_use_square_padding(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        diagonal = 2**-0.5
        # 왼쪽 아래 둥근 모서리만 스치는 경로.
        hit, cell = self.terrain.sweep_circle(450, 506, diagonal, diagonal, 41, 6)

        # 벽 모서리에서 사각 여백 대신 실제 원형 탄체의 충돌을 계산하는지 확인한다.
        self.assertEqual(cell, (10, 10))
        self.assertAlmostEqual(hit, 52 / (2**0.5) - 2)
        # 사각형으로 넓히면 가짜 충돌이 생기지만 실제 원은 모서리 밖을 통과한다.
        self.assertEqual(
            self.terrain.sweep_circle(450, 510, diagonal, diagonal, 41, 6), (41, None)
        )

    def test_long_sweep_hits_only_the_first_breakable_tile(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        grid = [[EMPTY] * 12 for _ in range(10)]
        grid[5][5], grid[5][7] = BREAKABLE, WALL
        config = TerrainConfig(breakable_enabled=True)
        terrain = TileMap(grid, 48, (2, 2), [], "first-hit", config)

        # 빠른 탄환이 처음 만난 파괴 가능 벽만 맞히는지 확인한다.
        self.assertEqual(terrain.sweep_circle(100, 264, 1, 0, 350, 6), (134, (5, 5)))
        terrain.damage_tile(5, 5, config.breakable_hp)
        self.assertEqual(terrain.sweep_circle(100, 264, 1, 0, 350, 6), (230, (7, 5)))
        self.assertEqual(terrain.sweep_circle(100, 264, 1, 0, 350, 0), (236, (7, 5)))

    def test_world_boundary_and_starting_overlap(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        self.assertEqual(self.terrain.sweep_circle(945, 120, 1, 0, 20, 6), (9, (20, 2)))

        # 월드 경계와 처음부터 겹친 위치에서의 충돌 결과를 확인한다.
        self.assertEqual(self.terrain.sweep_circle(15, 120, -1, 0, 20, 6), (9, (-1, 2)))
        self.assertEqual(
            self.terrain.sweep_circle(477, 500, -1, 0, 50, 6), (0, (10, 10))
        )
        self.assertEqual(self.terrain.sweep_circle(100, 100, 1, 0, 10, 6), (10, None))
        with self.assertRaises(ValueError):
            self.terrain.sweep_circle(100, 100, 1, 0, -1, 6)


class RemovedStealthObservationTests(unittest.TestCase):
    def test_flat_and_dict_observations_use_only_current_terrain(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        from space_z.rl.environment import TankEnv

        # 평탄화·사전 관측 모두 현재 지형만 반영하는지 확인한다.
        for mode in ("flat", "dict"):
            for stage2 in (False, True):
                config = GameConfig(num_enemies=1, num_shapes=2)
                config.terrain.mud_enabled = config.terrain.breakable_enabled = stage2
                environment = TankEnv(config, ObsConfig(obs_mode=mode))
                try:
                    observation, info = environment.reset(seed=3)
                    channels = 3 if stage2 else 1
                    if mode == "dict":
                        self.assertEqual(observation["vector"].shape, (120,))
                        self.assertEqual(observation["grid"].shape, (channels, 11, 11))
                    else:
                        self.assertEqual(observation.shape, (120 + channels * 121,))
                    self.assertNotIn("active_skill", info)
                    self.assertNotIn("skill_cooldown_seconds", info)
                    self.assertEqual(environment.action_space.n, 27)
                    self.assertEqual(len(environment.game.shapes), 2)
                    observation, reward, _, _, _ = environment.step(0)
                    self.assertTrue(np.isfinite(reward))
                finally:
                    environment.close()


if __name__ == "__main__":
    unittest.main()
