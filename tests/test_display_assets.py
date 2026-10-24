"""에셋 연결, 작은 보상 UI, 창 크기와 전체화면 전환 검증."""

import os
import unittest
from collections import defaultdict
from unittest.mock import patch

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import pygame

from space_z.config import GameConfig, ObsConfig
from space_z.game.game_core import Bullet, GameCore
from space_z.app import GameApplication
from space_z.config.progression_definitions import FAMILIES, SHIPS, STAT_UPGRADES
from space_z.rendering.progression_panel import (
    build_stat_upgrade_rows,
    get_evolution_card_rects,
)
from space_z.rendering.renderer import Renderer


class DisplayAssetsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        pygame.init()
        cls.config = GameConfig(num_enemies=0, num_shapes=0)
        cls.renderer = Renderer(cls.config)

    @classmethod
    def tearDownClass(cls):
        pygame.quit()

    def setUp(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        self.renderer.set_fullscreen(False)
        self.renderer.resize((1280, 800))
        self.game = GameCore(self.config, seed=7)
        self.application = GameApplication(self.game, self.renderer)
        self.application.mode = "playing"

    def test_default_window_is_larger_and_resizable(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        self.assertEqual(self.renderer.size, (1280, 800))

        # 기본 창 크기와 창 크기 변경 지원 여부를 확인한다.
        self.assertTrue(self.renderer.screen.get_flags() & pygame.RESIZABLE)
        self.assertEqual(
            (self.config.world_width, self.config.world_height), (6432, 4848)
        )

    def test_fullscreen_menu_round_trip_preserves_world_and_game_state(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        self.game.progression._add_score(1980)
        self.game.player.ammo = 3
        self.game.combat.request_reload()
        self.application.handle_event(
            pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE)
        )

        # 전체화면 전환 전후에 월드와 게임 진행 상태가 유지되는지 확인한다.
        self.assertEqual(self.application.mode, "pause")
        state = (
            self.game.frame,
            self.game.progression.score,
            self.game.player.x,
            self.game.player.hp,
            self.game.player.ammo,
            self.game.combat.reload_frames_left,
            self.game.progression.reward_choices,
            self.game.progression.stat_choices,
            id(self.game.terrain),
        )
        for expected in (True, False):
            button = next(
                bullet
                for bullet in self.application.get_menu_buttons()
                if bullet.key == "fullscreen"
            )
            self.application.handle_event(
                pygame.event.Event(
                    pygame.MOUSEBUTTONDOWN, button=1, pos=button.rect.center
                )
            )
            self.assertEqual(self.renderer.fullscreen, expected)
            self.assertEqual(
                bool(self.renderer.screen.get_flags() & pygame.FULLSCREEN), expected
            )
            self.application.update(
                100, defaultdict(bool), (0, 0), (False, False, False)
            )
            self.application.draw(ObsConfig())
            self.assertEqual(
                (
                    self.game.frame,
                    self.game.progression.score,
                    self.game.player.x,
                    self.game.player.hp,
                    self.game.player.ammo,
                    self.game.combat.reload_frames_left,
                    self.game.progression.reward_choices,
                    self.game.progression.stat_choices,
                    id(self.game.terrain),
                ),
                state,
            )
            self.assertTrue(
                pygame.Rect((0, 0), self.renderer.size).contains(
                    self.application.get_menu_buttons()[-1].rect
                )
            )
        self.assertEqual(self.renderer.size, (1280, 800))
        self.assertEqual((self.config.width, self.config.height), (960, 720))

    def test_resize_rebuilds_camera_and_click_regions(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        self.game.progression._add_score(1980)
        self.application.handle_event(
            pygame.event.Event(pygame.VIDEORESIZE, size=(1440, 900), w=1440, h=900)
        )

        # 창 크기 변경에 맞춰 카메라와 클릭 영역이 다시 계산되는지 확인한다.
        self.assertEqual(self.renderer.size, (1440, 900))
        self.renderer._update_camera(self.game.player)
        for point in ((0, 0), (720, 450), (1440, 900)):
            self.assertEqual(
                self.renderer.world_to_screen(*self.renderer.screen_to_world(*point)),
                point,
            )
        choice = self.game.progression.stat_choices[0].key
        row = pygame.Rect(
            build_stat_upgrade_rows(
                *self.renderer.size, self.game.progression.stat_choices
            )[0][1]
        )
        self.assertTrue(self.application.pointer_over_rewards(row.center))
        self.application.handle_event(
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=row.center)
        )
        self.assertEqual(self.game.progression.stat_levels[choice], 1)
        self.application.draw(ObsConfig())

    def test_l10_and_l20_use_matching_ship_images_in_compact_cards(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        self.game.progression._add_score(1980)

        # 진화 카드에 해당 단계의 우주선 이미지가 표시되는지 확인한다.
        with patch.object(
            self.renderer.assets, "image", wraps=self.renderer.assets.image
        ) as image:
            self.application.draw(ObsConfig())
            paths = {call.args[0] for call in image.call_args_list}
            self.assertTrue({card.asset for card in FAMILIES}.issubset(paths))
        self.application.handle_event(
            pygame.event.Event(pygame.KEYDOWN, key=pygame.K_F5)
        )
        self.assertEqual(self.game.player.job, "guardian")
        self.game.progression._add_score(7980 - self.game.progression.score)
        self.assertEqual(
            [card.key for card in self.game.progression.reward_choices],
            ["bastion", "aegis"],
        )
        with patch.object(
            self.renderer.assets, "image", wraps=self.renderer.assets.image
        ) as image:
            self.application.draw(ObsConfig())
            paths = {call.args[0] for call in image.call_args_list}
            self.assertTrue(
                {SHIPS["bastion"].asset, SHIPS["aegis"].asset}.issubset(paths)
            )
        for coords in get_evolution_card_rects(*self.renderer.size):
            self.assertEqual(pygame.Rect(coords).size, (90, 90))

    def test_stats_always_show_five_fixed_choices_and_all_number_keys_work(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        choices = self.game.progression.stat_choices

        # 다섯 스탯의 표시 순서와 숫자 단축키 동작을 확인한다.
        self.assertEqual(choices, STAT_UPGRADES)
        self.assertEqual(
            [card.title for card in choices],
            ["체력", "공격력", "사거리 및 탄속도", "발사속도", "이동속도"],
        )
        self.application.draw(ObsConfig())
        self.game.progression._add_score(1000)
        points = self.game.progression.upgrade_points
        for choice_index, key in enumerate(
            (pygame.K_1, pygame.K_2, pygame.K_3, pygame.K_4, pygame.K_5)
        ):
            self.application.handle_event(pygame.event.Event(pygame.KEYDOWN, key=key))
            self.assertEqual(
                self.game.progression.stat_levels[choices[choice_index].key], 1
            )
        self.assertEqual(self.game.progression.upgrade_points, points - 5)
        self.assertEqual(self.game.progression.stat_choices, choices)
        self.application.handle_event(
            pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE)
        )
        self.application.handle_event(
            pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE)
        )
        self.assertEqual(self.game.progression.stat_choices, choices)
        for coords in (row[1] for row in build_stat_upgrade_rows(960, 640)):
            self.assertTrue(pygame.Rect(0, 0, 960, 640).contains(pygame.Rect(coords)))

    def test_all_ship_sprites_render_and_transform_cache_reuses_images(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        for key in SHIPS:
            with self.subTest(ship=key):
                self.game.player.job = key
                self.renderer.draw(self.game)
                image = self.renderer.assets.image(SHIPS[key].asset, 62)
                self.assertIs(image, self.renderer.assets.image(SHIPS[key].asset, 62))
        selected_zoom = self.config.camera_zoom
        self.renderer.resize((4000, 2400))

        # 모든 우주선이 그려지고 변환된 이미지는 캐시에서 재사용되는지 확인한다.
        self.assertAlmostEqual(self.renderer.effective_zoom, selected_zoom)
        self.renderer._update_camera(self.game.player)
        screen_x, screen_y = self.renderer.world_to_screen(
            self.game.player.x, self.game.player.y
        )
        self.assertAlmostEqual(screen_x, 2000)
        self.assertAlmostEqual(screen_y, 1200)

    def test_player_sprite_faces_right_and_enemy_keeps_original_orientation(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        import math

        self.game.player.angle = math.pi / 2

        # 플레이어와 적 우주선 그림의 방향을 확인한다.
        with patch.object(
            self.renderer.assets, "ship_image", wraps=self.renderer.assets.ship_image
        ) as image:
            self.renderer._draw_ship(self.game.player, 100, is_player=True)
            self.assertEqual(image.call_args.args[0], SHIPS["rookie"].asset)
            self.assertAlmostEqual(image.call_args.args[2], -90)
        self.config.num_enemies = 1
        try:
            self.game.reset(7)
            enemy = self.game.enemies[0]
            enemy.angle = math.pi / 2
            # 적도 같은 진화 그림(일반은 붉은색, 엘리트는 금색)을 쓰므로 플레이어와 같은 방향 규칙을 따른다.
            for elite, suffix in ((False, "@enemy"), (True, "@elite")):
                enemy.elite = elite
                with patch.object(
                    self.renderer.assets,
                    "ship_image",
                    wraps=self.renderer.assets.ship_image,
                ) as image:
                    self.renderer._draw_ship(enemy, 100)
                    self.assertEqual(
                        image.call_args.args[0], SHIPS[enemy.job].asset + suffix
                    )
                    self.assertAlmostEqual(image.call_args.args[2], -90)
        finally:
            self.config.num_enemies = 0

    def test_21_original_transparent_sprites_fit_body_collision_diameter(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        import numpy as np

        # 원본의 투명 여백과 관계없이 실제 선체 지름이 충돌 크기에 맞는지 확인한다.
        self.assertEqual(len(SHIPS), 21)
        for spec in SHIPS.values():
            with self.subTest(ship=spec.key):
                source = self.renderer.assets._source(spec.asset)
                self.assertEqual(source.get_size(), (512, 512))
                self.assertEqual(int(pygame.surfarray.array_alpha(source).min()), 0)
                image = self.renderer.assets.ship_image(spec.asset, 60)
                rgb_pixels = pygame.surfarray.array3d(image).astype(np.int16)
                alpha = pygame.surfarray.array_alpha(image)
                health_x_pixels, health_y_pixels = np.where(
                    (alpha > 100)
                    & (rgb_pixels[:, :, 1] > rgb_pixels[:, :, 0] + 30)
                    & (rgb_pixels[:, :, 2] > rgb_pixels[:, :, 0] + 30)
                )
                self.assertAlmostEqual(
                    max(
                        health_x_pixels.max() - health_x_pixels.min() + 1,
                        health_y_pixels.max() - health_y_pixels.min() + 1,
                    ),
                    60,
                    delta=3,
                )
                self.assertAlmostEqual(
                    (health_x_pixels.max() + health_x_pixels.min()) / 2,
                    image.get_width() / 2,
                    delta=2,
                )
                self.assertAlmostEqual(
                    (health_y_pixels.max() + health_y_pixels.min()) / 2,
                    image.get_height() / 2,
                    delta=2,
                )

    def test_projectile_core_width_matches_physical_diameter_and_cache_reuses_images(
        self,
    ):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        assets = self.renderer.assets

        # 탄체 폭이 물리 지름과 맞고 변환 이미지가 재사용되는지 확인한다.
        for path in (
            "projectiles/player_plasma",
            "projectiles/enemy_plasma",
            "projectiles/cannon_shell",
        ):
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
                    self.assertAlmostEqual(
                        visible.centerx, image.get_width() / 2, delta=1.5
                    )
                    self.assertAlmostEqual(
                        visible.centery, image.get_height() / 2, delta=1.5
                    )
                    self.assertLessEqual(image.get_width(), diameter * 2.5 + 2)
                    self.assertIs(image, assets.projectile_image(path, diameter))
                    turned = assets.projectile_image(path, diameter, -90)
                    self.assertAlmostEqual(
                        turned.get_bounding_rect(min_alpha=100).height,
                        diameter,
                        delta=2,
                    )
                    self.assertIs(turned, assets.projectile_image(path, diameter, -90))

    def test_world_ship_render_size_tracks_doubled_radius_without_growing_cards(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        player = self.game.player

        # 월드 선체 크기는 충돌 반지름을 따르고 카드 그림 크기는 유지되는지 확인한다.
        self.assertEqual(player.radius, 44)
        with patch.object(
            self.renderer.assets, "ship_image", wraps=self.renderer.assets.ship_image
        ) as image:
            self.renderer._draw_ship(player, 100, is_player=True)
            self.assertEqual(image.call_args.args[1], 88)
        self.assertEqual(
            self.renderer.assets.image(SHIPS["rookie"].asset, 62).get_size(), (62, 62)
        )

    def test_tiny_projectiles_remain_visible_at_every_zoom_without_changing_collision(
        self,
    ):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        renderer = self.renderer
        old_zoom = renderer.config.camera_zoom

        # 줌이 달라도 탄환이 식별되고 충돌 크기는 유지되는지 확인한다.
        try:
            for zoom in (0.45, 0.6, 0.75, 1.0):
                renderer.set_zoom(zoom)
                for team, kind in (
                    ("player", "plasma"),
                    ("enemy", "plasma"),
                    ("player", "shell"),
                ):
                    with self.subTest(zoom=zoom, team=team, kind=kind):
                        bullet = Bullet(
                            500,
                            500,
                            9,
                            0,
                            70,
                            1,
                            team,
                            10,
                            0.25,
                            kind=kind,
                        )
                        before = vars(bullet).copy()
                        with patch.object(
                            renderer.assets,
                            "projectile_image",
                            wraps=renderer.assets.projectile_image,
                        ) as draw:
                            renderer._draw_bullet(bullet)
                        image = renderer.assets.projectile_image(*draw.call_args.args)
                        screen_image = pygame.transform.smoothscale(
                            image,
                            (
                                max(1, round(image.get_width() * zoom)),
                                max(1, round(image.get_height() * zoom)),
                            ),
                        )
                        core = screen_image.get_bounding_rect(min_alpha=100)
                        self.assertGreaterEqual(min(core.width, core.height), 3)
                        self.assertEqual(vars(bullet), before)

                large = Bullet(
                    500,
                    500,
                    9,
                    0,
                    70,
                    1,
                    "player",
                    10,
                    12,
                )
                with patch.object(
                    renderer.assets,
                    "projectile_image",
                    wraps=renderer.assets.projectile_image,
                ) as draw:
                    renderer._draw_bullet(large)
                self.assertEqual(draw.call_args.args[1], 24)
        finally:
            renderer.set_zoom(old_zoom)


if __name__ == "__main__":
    unittest.main()
