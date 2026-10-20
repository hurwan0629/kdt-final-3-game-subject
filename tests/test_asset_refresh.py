"""새 아트의 연결·보관 무결성과 렌더링의 게임 상태 독립성을 검증한다."""
import copy
import hashlib
import json
import os
from collections import defaultdict
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import pygame

from space_z.config import GameConfig
from space_z.game.game_core import GameCore
from space_z.app import GameApplication
from space_z.rl.environment import TankEnv
from space_z.rendering.menu_layout import build_menu_buttons
from space_z.rendering.renderer import DEATH_FRAMES, SCORE_POPUP_FRAMES, Renderer
from space_z.resource_paths import resource_path
from space_z.game.terrain import BREAKABLE, EMPTY, MUD, WALL, TileMap


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

    def setUp(self):
        # 서로 다른 테스트의 TileMap 객체 번호가 재사용되어 캐시가 섞이지 않도록 격리한다.
        self.renderer._terrain_key = None

    def test_resource_paths_work_outside_project_directory(self):
        project_root = Path(__file__).resolve().parents[1]
        previous_directory = Path.cwd()
        with tempfile.TemporaryDirectory() as directory:
            try:
                os.chdir(directory)
                for relative in ("maps/belt.txt", "assets/backgrounds/main.png"):
                    with self.subTest(relative=relative):
                        resolved = Path(resource_path(relative))
                        self.assertEqual(resolved, project_root / relative)
                        self.assertTrue(resolved.is_file())
            finally:
                os.chdir(previous_directory)

    def test_resource_paths_use_pyinstaller_bundle_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch("space_z.resource_paths.sys._MEIPASS", directory, create=True):
                self.assertEqual(Path(resource_path("maps/belt.txt")), Path(directory) / "maps/belt.txt")

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
                buttons = build_menu_buttons(mode, self.cfg, size=self.renderer.size)
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

    def test_confirmed_difficulty_is_dimmed_without_dimming_focus_or_cached_images(self):
        buttons = build_menu_buttons("main", self.cfg, size=self.renderer.size)
        easy, normal = buttons[:2]
        colors = {"etc/home_selected": (220, 160, 40), "etc/home_selected_normal": (40, 100, 140)}
        cached_images = {}

        def menu_image(path, size):
            key = (path, size)
            if key not in cached_images:
                cached_images[key] = pygame.Surface(size, pygame.SRCALPHA)
                cached_images[key].fill((*colors[path], 255))
            return cached_images[key]

        def sample(button):
            return tuple(self.renderer.screen.get_at((button.rect.left + 8, button.rect.top + 8)))[:3]

        for pointer, focus, easy_active in [(easy.rect.center, 1, True),
                                           (normal.rect.center, 0, False),
                                           ((-1, -1), 0, True), ((-1, -1), 1, False)]:
            with self.subTest(pointer=pointer, focus=focus):
                self.renderer.screen.fill((0, 0, 0))
                with patch("pygame.mouse.get_pos", return_value=pointer), \
                        patch.object(self.renderer.assets, "image", side_effect=menu_image):
                    self.renderer._draw_menu(buttons, "TEST", focus, main=True)
                if easy_active:
                    self.assertEqual(sample(easy), colors["etc/home_selected"])
                    self.assertLess(sample(normal)[0], sample(easy)[0])
                    self.assertGreater(sample(normal)[0], colors["etc/home_selected_normal"][0])
                else:
                    self.assertEqual(sample(normal), colors["etc/home_selected"])
                    self.assertEqual(sample(easy), colors["etc/home_selected_normal"])
                self.assertEqual([button.key for button in buttons if button.checked], ["difficulty_normal"])
        for (path, _), image in cached_images.items():
            self.assertEqual(image.get_alpha(), 255)
            self.assertEqual(tuple(image.get_at((8, 8)))[:3], colors[path])

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

    def score_popup_game(self):
        self.renderer.reset_score_popups()
        self.renderer._last_frame = -1
        game = GameCore(self.cfg, seed=17)
        self.renderer._update_camera(game.player)
        return game

    def test_score_popups_do_not_mutate_core_or_repeat_sparks_and_expire_by_game_frame(self):
        game = self.score_popup_game()
        game.record_score_award(game.player.x, game.player.y, 10, "square")
        self.renderer.add_score_popups(game.pop_score_award_events())
        self.assertEqual(self.renderer.score_popups,
                         [(1, 0, game.player.x, game.player.y, 10, "square")])
        before = copy.deepcopy((game.frame, game.events, game.score_award_events,
                                game.progression.score, game.rng.bit_generator.state))
        for _ in range(2):
            self.renderer._track(game)
            self.renderer._draw_score_text(game)
        self.assertEqual(len(self.renderer._sparks), 10)
        self.assertEqual(self.renderer._popups_seen, {1})
        self.assertEqual((game.frame, game.events, game.score_award_events,
                          game.progression.score, game.rng.bit_generator.state), before)
        game.frame = SCORE_POPUP_FRAMES
        self.renderer._track(game)
        self.assertEqual(len(self.renderer.score_popups), 1)
        game.frame += 1
        self.renderer._track(game)
        self.assertEqual(self.renderer.score_popups, [])

    def test_application_delivers_all_score_awards_before_drawing(self):
        game = self.score_popup_game()
        application = GameApplication(game, self.renderer, seed=17)
        application.activate_menu_action("start")
        original_step = game.step

        def step_with_score_award(*args, **kwargs):
            game.record_score_award(game.player.x, game.player.y, 10, "square")
            original_step(*args, **kwargs)

        with patch.object(game, "step", side_effect=step_with_score_award):
            application.update(3.5 / game.cfg.fps, defaultdict(bool), (0, 0), (False, False, False))
        self.assertEqual(game.frame, 3)
        self.assertEqual([popup[1] for popup in self.renderer.score_popups], [0, 1, 2])
        self.assertEqual(game.score_award_events, [])

    def test_restart_clears_popups_and_effects_even_when_frame_is_unchanged(self):
        game = self.score_popup_game()
        application = GameApplication(game, self.renderer, seed=17)
        application.activate_menu_action("start")
        game.record_score_award(100, 200, 10, "square")
        self.renderer.add_score_popups(game.pop_score_award_events())
        self.renderer._track(game)
        self.assertTrue(self.renderer._sparks)
        game.record_score_award(300, 400, 20, "enemy")
        application.activate_menu_action("restart")
        self.assertEqual((game.frame, self.renderer._last_frame), (0, 0))
        self.assertEqual(game.score_award_events, [])
        self.assertEqual(self.renderer.score_popups, [])
        self.assertEqual(self.renderer._popup_id, 0)
        self.assertEqual(self.renderer._popups_seen, set())
        self.assertEqual(self.renderer._sparks, [])
        self.assertEqual(self.renderer._xp_flash_frame, -999)
        game.record_score_award(100, 200, 10, "square")
        self.renderer.add_score_popups(game.pop_score_award_events())
        self.renderer._track(game)
        self.assertEqual(len(self.renderer._sparks), 10)

    def test_human_environment_delivers_frame_skip_awards_once_and_clears_on_reset(self):
        self.score_popup_game()
        environment = TankEnv(game_config=self.cfg, render_mode="human")
        with patch("space_z.rendering.renderer.Renderer", return_value=self.renderer) as create_renderer:
            environment.reset(seed=17)
            original_step = environment.game.step

            def step_with_score_award(action):
                environment.game.record_score_award(100, 200, 10, "square")
                original_step(action)

            with patch.object(environment.game, "step", side_effect=step_with_score_award):
                environment.step(0)
            self.assertEqual([popup[1] for popup in self.renderer.score_popups],
                             list(range(environment.env_cfg.frame_skip)))
            self.assertEqual(environment.game.score_award_events, [])
            environment.render()
            self.assertEqual(len(self.renderer.score_popups), environment.env_cfg.frame_skip)
            environment.reset(seed=17)
            self.assertEqual(self.renderer.score_popups, [])
            self.assertEqual(self.renderer._popups_seen, set())
            create_renderer.assert_called_once_with(self.cfg)


if __name__ == "__main__":
    unittest.main()
