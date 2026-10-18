"""새 아트의 연결·보관 무결성과 렌더링의 게임 상태 독립성을 검증한다."""
import copy
import hashlib
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import pygame

from config import GameConfig
from game_core import GameCore
from menus import menu_buttons
from renderer import DEATH_FRAMES, Renderer
from terrain import BREAKABLE, EMPTY, MUD, WALL, TileMap


class AssetRefreshTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()
        cls.cfg = GameConfig(num_enemies=0, num_shapes=0, world_scale=1, world_area_scale=1)
        cls.cfg.terrain.enabled = False
        cls.renderer = Renderer(cls.cfg)

    @classmethod
    def tearDownClass(cls):
        pygame.quit()

    def test_catalog_and_archive_preserve_every_listed_file(self):
        root = Path(__file__).resolve().parents[1] / "assets"
        catalog = json.loads((root / "catalog.json").read_text(encoding="utf-8"))
        records = json.loads((root / "pre/v2/manifest.json").read_text(encoding="utf-8-sig"))
        for entry in catalog["assets"] + records:
            path = root / entry.get("archived_path", entry.get("path"))
            with self.subTest(path=path):
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), entry["sha256"])
        self.assertEqual(len(records), 29)
        active = {p.relative_to(root).as_posix() for p in root.rglob("*.png")
                  if p.relative_to(root).parts[0] not in {"pre", "new-images"}}
        self.assertEqual(active, {entry["path"] for entry in catalog["assets"]})

    def test_wall_art_preserves_collision_damage_and_game_random_state(self):
        cfg = self.cfg.terrain
        old_flags = cfg.mud_enabled, cfg.breakable_enabled
        cfg.mud_enabled = cfg.breakable_enabled = True
        try:
            terrain = TileMap([[WALL] * 4, [MUD, BREAKABLE, EMPTY, EMPTY], [EMPTY] * 4],
                              cfg.tile_size, (1, 2), [], "art-test", cfg)
            terrain.damage_tile(1, 1, 5)
            before = copy.deepcopy((terrain.tiles, terrain.hp, terrain.version))
            game = GameCore(self.cfg, seed=8)
            random_state = copy.deepcopy(game.rng.bit_generator.state)
            with patch.object(self.renderer.assets, "image", wraps=self.renderer.assets.image) as image:
                self.renderer._ensure_terrain(terrain)
            paths = {call.args[0] for call in image.call_args_list}
            self.assertTrue({f"etc/guard_{i:02d}" for i in range(1, 5)} <= paths)
            self.assertIn("objects/gravity_field", paths)
            self.assertEqual((terrain.tiles, terrain.hp, terrain.version), before)
            self.assertEqual(game.rng.bit_generator.state, random_state)
        finally:
            cfg.mud_enabled, cfg.breakable_enabled = old_flags

    def test_menu_art_preserves_button_rects_and_cached_normal_image(self):
        for mode in ("main", "pause"):
            with self.subTest(menu=mode):
                buttons = menu_buttons(mode, self.cfg, size=self.renderer.size)
                rects = [button.rect.copy() for button in buttons]
                normal = self.renderer.assets.image("etc/home_selected_normal", buttons[-1].rect.size)
                before = pygame.image.tobytes(normal, "RGBA")
                with patch.object(self.renderer.assets, "image", wraps=self.renderer.assets.image) as image:
                    self.renderer._draw_menu(buttons, "TEST", 3 if mode == "main" else 0,
                                             main=mode == "main")
                self.assertEqual([button.rect for button in buttons], rects)
                paths = {call.args[0] for call in image.call_args_list}
                self.assertTrue({"etc/home_selected", "etc/home_selected_normal"} <= paths)
                self.assertEqual(pygame.image.tobytes(normal, "RGBA"), before)

    def test_only_fully_solid_8x8_regions_use_one_large_image(self):
        tiles = [[WALL] * 16 for _ in range(8)]
        tiles[0][8] = EMPTY  # 오른쪽 블록에 빈칸 하나: 남은 63칸은 작은 이미지로 처리한다.
        terrain = TileMap(tiles, self.cfg.terrain.tile_size, (8, 0), [], "blocks", self.cfg.terrain)
        before = copy.deepcopy((terrain.tiles, terrain.hp, terrain.version))
        with patch.object(self.renderer.assets, "image", wraps=self.renderer.assets.image) as image:
            self.renderer._ensure_terrain(terrain)
        sizes = [call.args[1] for call in image.call_args_list if call.args[0].startswith("etc/guard_")]
        self.assertEqual(sizes.count(8 * terrain.tile), 1)
        self.assertEqual(sizes.count(terrain.tile), 63)
        self.assertEqual((terrain.tiles, terrain.hp, terrain.version), before)

    def test_large_blocks_follow_random_map_center_offset(self):
        tiles = [[EMPTY] * 19 for _ in range(13)]
        # 생성기와 동일한 가운데 정렬: (19 % 8) // 2, (13 % 8) // 2 = (1, 2).
        for row in range(2, 10):
            for col in range(1, 9):
                tiles[row][col] = WALL
        terrain = TileMap(tiles, self.cfg.terrain.tile_size, (0, 0), [], "random", self.cfg.terrain)
        with patch.object(self.renderer.assets, "image", wraps=self.renderer.assets.image) as image:
            self.renderer._ensure_terrain(terrain)
        sizes = [call.args[1] for call in image.call_args_list if call.args[0].startswith("etc/guard_")]
        self.assertEqual(sizes, [8 * terrain.tile])

    def test_destroying_one_tile_switches_the_whole_block_to_small_images(self):
        cfg = self.cfg.terrain
        old_flag = cfg.breakable_enabled
        cfg.breakable_enabled = True
        try:
            tiles = [[BREAKABLE] * 8 for _ in range(8)]
            tiles[0][0] = WALL  # 두 벽 종류가 섞여도 빈칸이 없으면 큰 이미지 하나를 사용한다.
            terrain = TileMap(tiles, cfg.tile_size, (0, 0), [], "breakable-block", cfg)
            for destroyed in (False, True):
                if destroyed:
                    self.assertTrue(terrain.damage_tile(3, 3, cfg.breakable_hp))
                with patch.object(self.renderer.assets, "image", wraps=self.renderer.assets.image) as image:
                    self.renderer._ensure_terrain(terrain)
                sizes = [call.args[1] for call in image.call_args_list if call.args[0].startswith("etc/guard_")]
                self.assertEqual(sizes.count(8 * terrain.tile), 0 if destroyed else 1)
                self.assertEqual(sizes.count(terrain.tile), 63 if destroyed else 0)
        finally:
            cfg.breakable_enabled = old_flag

    def test_other_block_sizes_keep_small_images(self):
        cfg = self.cfg.terrain
        old_size = cfg.block_tiles
        cfg.block_tiles = 5
        try:
            terrain = TileMap([[WALL] * 8 for _ in range(8)], cfg.tile_size, (0, 0), [], "other", cfg)
            with patch.object(self.renderer.assets, "image", wraps=self.renderer.assets.image) as image:
                self.renderer._ensure_terrain(terrain)
            sizes = [call.args[1] for call in image.call_args_list if call.args[0].startswith("etc/guard_")]
            self.assertEqual(sizes, [terrain.tile] * 64)
        finally:
            cfg.block_tiles = old_size

    def test_explosion_finishes_after_game_over_without_advancing_simulation(self):
        game = GameCore(self.cfg, seed=17)
        self.renderer._last_frame = -1
        self.renderer._prev_alive.clear()
        self.renderer._ghosts.clear()
        self.renderer.draw(game)
        game.player.alive = False
        game.game_over = True
        self.renderer.draw(game)
        self.assertTrue(self.renderer._ghosts)
        before = copy.deepcopy((game.frame, game.rng.bit_generator.state, game.player, game.events))
        for _ in range(DEATH_FRAMES):
            self.renderer.draw(game)
        self.assertFalse(self.renderer._ghosts)
        self.assertEqual((game.frame, game.rng.bit_generator.state, game.player, game.events), before)
        self.assertEqual(len(self.renderer._explosion_frames), 8)
        self.assertEqual(len({frame.get_size() for frame in self.renderer._explosion_frames}), 1)


if __name__ == "__main__":
    unittest.main()
