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
