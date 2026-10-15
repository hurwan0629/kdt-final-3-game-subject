"""큰 벽/넓은 통로와 선체 크기를 고려한 길 찾기 회귀 검사."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from pathlib import Path
from collections import deque

import terrain

import numpy as np

from config import TerrainConfig, GameConfig, ObsConfig
from terrain import (TileMap, EMPTY, WALL, BREAKABLE, MapError, grid_channels,
                     list_maps, load_map, parse_map, expand_map, generate_random_map, map_to_text)


class LargeWallLayoutTests(unittest.TestCase):
    def assert_thick_walls(self, tm, minimum=4):
        for row in range(tm.rows):
            for col in range(tm.cols):
                if not tm.solid[row][col]:
                    continue
                self.assertTrue(any(
                    all(0 <= c < tm.cols and 0 <= r < tm.rows and tm.solid[r][c]
                        for r in range(r0, r0 + minimum) for c in range(c0, c0 + minimum))
                    for r0 in range(row - minimum + 1, row + 1)
                    for c0 in range(col - minimum + 1, col + 1)),
                    f"thin wall at {tm.name}: {(col, row)}")

    def assert_connected_walls(self, tm):
        solid = {(c, r) for r in range(tm.rows) for c in range(tm.cols) if tm.solid[r][c]}
        self.assertTrue(solid)
        start = next(iter(solid))
        seen, queue = {start}, deque([start])
        while queue:
            c, r = queue.popleft()
            for dc, dr in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nxt = (c + dc, r + dr)
                if nxt in solid and nxt not in seen:
                    seen.add(nxt)
                    queue.append(nxt)
        self.assertEqual(seen, solid, "walls should form a connected maze network")

    def test_whole_world_maps_and_custom_sizes_fit_doubled_guardian(self):
        for stage2 in (False, True):
            cfg = TerrainConfig(mud_enabled=stage2, breakable_enabled=stage2)
            for name in list_maps():
                for cols, rows in ((60, 45), (20, 15)):
                    with self.subTest(map=name, size=(cols, rows), stage2=stage2):
                        tm = load_map(name, cfg, cols, rows)
                        self.assertEqual((tm.cols, tm.rows), (cols, rows))
                        self.assertNotIn("*", map_to_text(tm))
                        self.assertTrue(tm.is_connected())
                        self.assertTrue(tm.is_connected(96))
                        self.assert_thick_walls(tm, 4 if cols == 60 else 2)
                        self.assert_connected_walls(tm)
                        for goal in tm.enemy_starts:
                            self.assertTrue(tm.circle_fits(*tm.center(*goal), 96))
                            path = tm.astar(tm.player_start, goal, radius=96)
                            self.assertTrue(path)
                            previous = tm.player_start
                            for step in path:
                                self.assertTrue(tm.segment_fits(*tm.center(*previous), *tm.center(*step), 96))
                                previous = step

    def test_default_maps_load_the_authored_full_world_without_generation(self):
        cfg = TerrainConfig(mud_enabled=True, breakable_enabled=True)
        layouts = []
        for name in list_maps():
            path = Path(terrain.resource_path("maps")) / (name + ".txt")
            expected = parse_map(path.read_text(encoding="utf-8"), name, cfg, 60, 45)
            with patch.object(terrain, "_generate_maze", side_effect=AssertionError("do not generate default map")):
                actual = load_map(name, cfg, 60, 45)
            self.assertEqual(actual.tiles, expected.tiles)
            self.assertEqual(actual.player_start, expected.player_start)
            self.assertEqual(actual.enemy_starts, expected.enemy_starts)
            self.assertTrue(any(actual.tiles[r][c] != actual.tiles[r % 15][c % 20]
                                for r in range(45) for c in range(60)))
            layouts.append(tuple(tuple(row) for row in actual.tiles))
        self.assertEqual(len(set(layouts)), 4)

    def test_custom_size_generation_cannot_hide_damaged_builtin_files(self):
        cfg = TerrainConfig()
        valid = Path(terrain.resource_path("maps/drift.txt")).read_text(encoding="utf-8")
        data = [line for line in valid.splitlines() if line and not line.startswith(";")]
        cases = ("\n".join(data[:-1]),
                 "\n".join([data[0][:-1]] + data[1:]),
                 "\n".join(["?" + data[0][1:]] + data[1:]))
        for damaged in cases:
            with self.subTest(damage=damaged[:10]), patch.dict(terrain._MAP_TEXT_CACHE, {"drift": damaged}):
                with self.assertRaises(MapError):
                    load_map("drift", cfg, 20, 15)

    def test_random_maps_are_open_block_mazes(self):
        # 기본 랜덤 지형은 diep.io 미로 모드처럼 큰 블록 미로에 통로를 더 뚫은 형태다.
        cfg = TerrainConfig(mud_enabled=True, breakable_enabled=True)
        for cols, rows, seeds in ((20, 15, range(50)), (60, 45, range(10))):
            for seed in seeds:
                with self.subTest(size=(cols, rows), seed=seed):
                    tm = generate_random_map(np.random.default_rng(seed), cfg, cols, rows)
                    self.assertTrue(tm.is_connected())
                    self.assertTrue(tm.is_connected(96))
                    self.assertTrue(tm.circle_fits(*tm.center(*tm.player_start), 96))
                    self.assert_thick_walls(tm, 4 if cols == 60 else 2)
                    self.assertNotIn("*", map_to_text(tm))
                    solid = sum(tm.solid[r][c] for r in range(rows) for c in range(cols))
                    self.assertLess(solid / (cols * rows), 0.35)      # 너무 갑갑하지 않게
                    if cols == 60:
                        self.assertGreater(solid / (cols * rows), 0.1)  # 벽이 아예 없지는 않게
                        self.assertGreaterEqual(len(tm.enemy_starts), 8)
        a = generate_random_map(np.random.default_rng(12), cfg, 60, 45)
        b = generate_random_map(np.random.default_rng(12), cfg, 60, 45)
        self.assertEqual(map_to_text(a), map_to_text(b))
        self.assertEqual(a.enemy_starts, b.enemy_starts)

    def test_removed_stealth_marker_is_rejected(self):
        lines = ["......."] * 7
        lines[3] = "...P..."
        lines[2] = "..*...."
        with self.assertRaisesRegex(MapError, "알 수 없는 지형"):
            parse_map("\n".join(lines), "stealth", TerrainConfig(), 7, 7)
        self.assertEqual(grid_channels(TerrainConfig()), ["wall"])
        self.assertEqual(grid_channels(TerrainConfig(mud_enabled=True, breakable_enabled=True)),
                         ["wall", "mud", "breakable"])

    def test_astar_accounts_for_doubled_hull_and_five_tile_opening(self):
        for opening in ((5, 6, 7), (4, 5, 6, 7, 8)):
            grid = [[EMPTY] * 13 for _ in range(13)]
            grid[6] = [EMPTY if col in opening else WALL for col in range(13)]
            tm = TileMap(grid, 48, (6, 2), [], "passage", TerrainConfig())
            self.assertTrue(tm.astar((6, 2), (6, 10), radius=44))
            self.assertEqual(bool(tm.astar((6, 2), (6, 10), radius=96)), len(opening) == 5)

    def test_clear_view_can_still_be_too_narrow_for_a_hull(self):
        grid = [[EMPTY] * 9 for _ in range(9)]
        grid[4][4] = WALL
        tm = TileMap(grid, 48, (2, 2), [], "corner", TerrainConfig())
        self.assertTrue(tm.line_of_sight(100, 160, 300, 160))
        self.assertFalse(tm.segment_fits(100, 160, 300, 160, 48))
        self.assertTrue(tm.segment_fits(100, 140, 300, 140, 48))
        self.assertTrue(tm.segment_fits(100, 160, 152, 160, 48))
        self.assertFalse(tm.circle_fits(24, 100, 48))
        self.assertTrue(tm.circle_fits(48, 100, 48))

    def test_breaking_a_wall_refreshes_navigation_cache(self):
        grid = [[EMPTY] * 9 for _ in range(9)]
        grid[4] = [WALL] * 9
        grid[4][4] = BREAKABLE
        cfg = TerrainConfig(breakable_enabled=True)
        tm = TileMap(grid, 48, (4, 1), [], "breakable", cfg)
        self.assertFalse(tm.astar((4, 1), (4, 7), radius=22))
        self.assertTrue(tm.damage_tile(4, 4, cfg.breakable_hp))
        self.assertTrue(tm.astar((4, 1), (4, 7), radius=22))

    def test_doubled_guardian_collision_slides_without_leaving_overlap(self):
        grid = [[EMPTY] * 9 for _ in range(9)]
        for row in range(2, 7):
            grid[row][4] = WALL
        tm = TileMap(grid, 48, (2, 2), [], "slide", TerrainConfig())
        ship = SimpleNamespace(x=97.0, y=216.0, radius=96.0, vx=3.0, vy=2.0)
        self.assertTrue(tm.resolve_circle(ship))
        self.assertTrue(tm.circle_fits(ship.x, ship.y, ship.radius))
        self.assertEqual(ship.vx, 0)
        self.assertEqual(ship.vy, 2)


class SweptCircleTests(unittest.TestCase):
    def setUp(self):
        grid = [[EMPTY] * 20 for _ in range(15)]
        grid[10][10] = WALL
        self.tm = TileMap(grid, 48, (2, 2), [], "swept", TerrainConfig())

    def test_diagonal_round_overlaps_wall_even_when_center_ray_misses(self):
        diagonal = 2 ** -0.5
        distance = (28.8 ** 2 + 28.8 ** 2) ** 0.5
        self.assertTrue(self.tm.line_of_sight(450, 502, 478.8, 530.8))
        hit, cell = self.tm.sweep_circle(450, 502, diagonal, diagonal, distance, 6)
        self.assertEqual(cell, (10, 10))
        self.assertAlmostEqual(hit, 24 / diagonal)
        self.assertLess(hit, distance)

    def test_rounded_corner_is_exact_and_does_not_use_square_padding(self):
        diagonal = 2 ** -0.5
        # 왼쪽 아래 둥근 모서리만 스치는 경로.
        hit, cell = self.tm.sweep_circle(450, 506, diagonal, diagonal, 41, 6)
        self.assertEqual(cell, (10, 10))
        self.assertAlmostEqual(hit, 52 / (2 ** 0.5) - 2)
        # 사각형으로 넓히면 가짜 충돌이 생기지만 실제 원은 모서리 밖을 통과한다.
        self.assertEqual(self.tm.sweep_circle(450, 510, diagonal, diagonal, 41, 6), (41, None))

    def test_long_sweep_hits_only_the_first_breakable_tile(self):
        grid = [[EMPTY] * 12 for _ in range(10)]
        grid[5][5], grid[5][7] = BREAKABLE, WALL
        cfg = TerrainConfig(breakable_enabled=True)
        tm = TileMap(grid, 48, (2, 2), [], "first-hit", cfg)
        self.assertEqual(tm.sweep_circle(100, 264, 1, 0, 350, 6), (134, (5, 5)))
        tm.damage_tile(5, 5, cfg.breakable_hp)
        self.assertEqual(tm.sweep_circle(100, 264, 1, 0, 350, 6), (230, (7, 5)))
        self.assertEqual(tm.sweep_circle(100, 264, 1, 0, 350, 0), (236, (7, 5)))

    def test_world_boundary_and_starting_overlap(self):
        self.assertEqual(self.tm.sweep_circle(945, 120, 1, 0, 20, 6), (9, (20, 2)))
        self.assertEqual(self.tm.sweep_circle(15, 120, -1, 0, 20, 6), (9, (-1, 2)))
        self.assertEqual(self.tm.sweep_circle(477, 500, -1, 0, 50, 6), (0, (10, 10)))
        self.assertEqual(self.tm.sweep_circle(100, 100, 1, 0, 10, 6), (10, None))
        with self.assertRaises(ValueError):
            self.tm.sweep_circle(100, 100, 1, 0, -1, 6)


class RemovedStealthObservationTests(unittest.TestCase):
    def test_flat_and_dict_observations_use_only_current_terrain(self):
        from env import TankEnv
        for mode in ("flat", "dict"):
            for stage2 in (False, True):
                cfg = GameConfig(num_enemies=1, num_shapes=2)
                cfg.terrain.mud_enabled = cfg.terrain.breakable_enabled = stage2
                env = TankEnv(cfg, ObsConfig(obs_mode=mode))
                try:
                    obs, info = env.reset(seed=3)
                    channels = 3 if stage2 else 1
                    if mode == "dict":
                        self.assertEqual(obs["vector"].shape, (120,))
                        self.assertEqual(obs["grid"].shape, (channels, 11, 11))
                    else:
                        self.assertEqual(obs.shape, (120 + channels * 121,))
                    self.assertNotIn("active_skill", info)
                    self.assertNotIn("skill_cooldown_seconds", info)
                    self.assertEqual(env.action_space.n, 27)
                    self.assertEqual(len(env.game.shapes), 2)
                    obs, reward, _, _, _ = env.step(0)
                    self.assertTrue(np.isfinite(reward))
                finally:
                    env.close()


if __name__ == "__main__":
    unittest.main()
