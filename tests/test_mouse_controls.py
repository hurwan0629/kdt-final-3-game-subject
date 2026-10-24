"""마우스 입력, 유한 탄약, 일시정지, 줌 변환 검증."""

import math
import os
import unittest
from collections import defaultdict
from unittest.mock import patch

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import pygame

from space_z.config import GameConfig
from space_z.rl.environment import TankEnv
from space_z.game.game_core import GameCore, Tank, decode_action, encode_action
from space_z.app import GameApplication, read_player_input
from space_z.rendering.renderer import Renderer


def key_state(*pressed):
    return defaultdict(bool, {key: True for key in pressed})


class MouseControlTests(unittest.TestCase):
    def setUp(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        config = GameConfig(num_shapes=0, num_enemies=0)
        config.terrain.enabled = False
        self.game = GameCore(config, seed=1)
        # 좌표 변환 검사는 실제 창/이미지 캐시 없이 실행한다.
        self.renderer = object.__new__(Renderer)
        self.renderer.reset_score_popups()
        self.renderer.config = config
        self.renderer.screen = pygame.Surface((960, 720))
        self.renderer.view_width, self.renderer.view_height = 1600, 1200
        self.renderer._update_camera(self.game.player)

    def test_wasd_movement_is_independent_of_mouse_aim_and_fire(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        game, renderer = self.game, self.renderer
        screen_x, screen_y = renderer.world_to_screen(game.player.x, game.player.y)
        action, target, fire = read_player_input(
            key_state(pygame.K_d),
            renderer,
            (screen_x, screen_y + 100),
            (False, False, False),
        )

        # WASD 이동이 마우스 조준·발사와 독립적으로 적용되는지 확인한다.
        self.assertEqual(decode_action(action), (3, 0))
        self.assertFalse(fire)
        before = game.player.x
        game.step(action, want_fire=fire, aim_position=target)
        self.assertGreater(game.player.x, before)
        self.assertEqual(game.combat.bullets, [])
        action, target, fire = read_player_input(
            key_state(pygame.K_w),
            renderer,
            (screen_x, screen_y + 100),
            (True, False, False),
        )
        self.assertEqual(decode_action(action), (1, 0))
        before_y = game.player.y
        game.step(action, want_fire=fire, aim_position=target)
        self.assertLess(game.player.y, before_y)
        self.assertEqual(len(game.combat.bullets), 1)
        bullet = game.combat.bullets[0]
        self.assertAlmostEqual(
            math.atan2(bullet.velocity_y, bullet.velocity_x), game.player.angle
        )
        self.assertGreater(bullet.velocity_y, 0)  # 위로 이동하면서 아래로 조준/발사
        self.assertEqual(game.player.ammo, 119)

    def test_moving_player_aims_from_new_position_and_keeps_keyboard_rotation(self):
        """목표가 있으면 이동 후 재조준하고, 없으면 회전 입력을 그대로 적용한다."""
        player = self.game.player
        for target in ((560.0, 600.0), None):
            with self.subTest(aim_position=target):
                # 이동과 회전 입력이 동시에 들어오는 상황을 준비한다.
                player.x, player.y, player.angle = 500.0, 500.0, 1.0
                player.velocity_x = player.velocity_y = 0.0

                self.game.step(
                    encode_action(3, 1), want_fire=False, aim_position=target
                )

                # 조준 좌표가 있으면 이동 후 좌표를, 없으면 원래 각도와 회전 입력을 기준으로 삼는다.
                self.assertGreater(player.x, 500.0)
                expected_angle = (
                    math.atan2(target[1] - player.y, target[0] - player.x)
                    if target is not None
                    else 1.0 - self.game.config.turn_speed
                )
                self.assertAlmostEqual(player.angle, expected_angle)

    def test_movement_reaching_aim_point_keeps_angle_after_rotation(self):
        """이동 후 조준점과 겹치면 영벡터로 각도를 다시 설정하지 않는다."""
        player = self.game.player
        player.x, player.y = 500.0, 500.0
        player.velocity_x = player.velocity_y = 0.0
        target = (player.x + self.game.config.accel * player.accel_scale, player.y)

        self.game.step(encode_action(3, 2), want_fire=False, aim_position=target)

        self.assertEqual((player.x, player.y), target)
        self.assertAlmostEqual(player.angle, self.game.config.turn_speed)

    def test_right_click_does_not_move_and_wasd_supports_diagonals(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        mouse = (800, 360)
        action, _, _ = read_player_input(
            key_state(), self.renderer, mouse, (False, False, True)
        )

        # 우클릭은 이동시키지 않고 WASD 조합은 대각선 이동을 만드는지 확인한다.
        self.assertEqual(decode_action(action), (0, 0))
        for pressed, expected in (
            ((pygame.K_w, pygame.K_a), 8),
            ((pygame.K_s, pygame.K_d), 4),
            ((pygame.K_w, pygame.K_s), 0),
            ((pygame.K_a, pygame.K_d), 0),
        ):
            action, _, _ = read_player_input(
                key_state(*pressed), self.renderer, mouse, (False, False, False)
            )
            self.assertEqual(decode_action(action), (expected, 0))

    def test_ammo_exhaustion_cooldown_and_three_shot_partial_volley(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        game, player = self.game, self.game.player
        player.ammo = 2
        player.job, player.projectiles = "triple_wing", 3
        game.combat._fire(player, True)

        # 남은 탄약과 발사 대기가 부분 발사 묶음에 정확히 적용되는지 확인한다.
        self.assertEqual(len(game.combat.bullets), 2)
        self.assertEqual(player.ammo, 0)
        player.cooldown = 0
        game.combat._fire(player, True)
        self.assertEqual(len(game.combat.bullets), 2)
        player.ammo, player.cooldown = 5, 4
        game.combat._fire(player, True)
        self.assertEqual((player.ammo, player.cooldown), (5, 3))
        player.cooldown = 0
        game.combat._fire(player, False)
        self.assertEqual(player.ammo, 5)
        enemy = Tank(
            99,
            "enemy",
            player.x + 100,
            player.y,
            60,
            60,
            22,
            36,
        )
        game.combat._fire(enemy, True)
        self.assertEqual(len(game.combat.bullets), 3)

    def test_restart_restores_ammo_and_training_remains_unlimited(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        game = self.game
        game.player.ammo = 0
        game.reset(1)

        # 새 판은 탄약을 복구하고 학습 환경은 무제한 탄약을 사용하는지 확인한다.
        self.assertEqual(game.player.ammo, 120)
        environment = TankEnv()
        self.assertFalse(environment.game_config.limited_ammo)
        environment.game.combat._fire(environment.game.player, True)
        self.assertEqual(environment.game.player.ammo, environment.game.player.max_ammo)
        self.assertIsNone(environment.reset(seed=1)[1]["ammo"])

    def test_zoom_coordinate_round_trip_and_small_world_centering(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        renderer = self.renderer

        # 화면·월드 좌표의 왕복 변환과 작은 월드의 중앙 정렬을 확인한다.
        self.assertGreater(renderer.view_width, renderer.config.width)
        for position in ((0, 0), (480, 360), (960, 720)):
            world = renderer.screen_to_world(*position)
            screen = renderer.world_to_screen(*world)
            self.assertAlmostEqual(screen[0], position[0])
            self.assertAlmostEqual(screen[1], position[1])
        renderer.config.world_scale = 1
        player = self.game.player
        player.x, player.y = player.radius + 0.25, player.radius + 0.75
        renderer._update_camera(player)
        self.assertLess(renderer.camera_x, 0)
        self.assertLess(renderer.camera_y, 0)
        screen_x, screen_y = renderer.world_to_screen(player.x, player.y)
        self.assertAlmostEqual(screen_x, renderer.size[0] / 2)
        self.assertAlmostEqual(screen_y, renderer.size[1] / 2)
        world_x, world_y = renderer.screen_to_world(
            renderer.size[0] / 2, renderer.size[1] / 2
        )
        self.assertAlmostEqual(world_x, player.x)
        self.assertAlmostEqual(world_y, player.y)

    def test_pause_focus_loss_freeze_but_stat_selection_keeps_game_running(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        game = self.game
        application = GameApplication(game, self.renderer, seed=1)
        application.activate_menu_action("start")
        game.progression._add_score(60)
        key = lambda key_code: application.handle_event(
            pygame.event.Event(pygame.KEYDOWN, key=key_code)
        )
        key(pygame.K_p)
        state = (game.frame, game.player.x, game.player.ammo)
        application.update(0.1, key_state(pygame.K_d), (800, 360), (True, False, False))

        # 일시정지는 시간을 멈추고 스탯 선택은 전투를 멈추지 않는지 확인한다.
        self.assertEqual((game.frame, game.player.x, game.player.ammo), state)
        key(pygame.K_ESCAPE)
        application.update(
            1 / 60, key_state(pygame.K_d), (800, 360), (False, False, False)
        )
        self.assertGreater(game.player.x, state[1])
        application.handle_event(pygame.event.Event(pygame.WINDOWFOCUSLOST))
        self.assertEqual(application.mode, "pause")
        key(pygame.K_p)
        key(pygame.K_1)
        state = (game.frame, game.player.x, game.player.ammo)
        application.update(0.1, key_state(pygame.K_d), (800, 360), (True, False, False))
        self.assertGreater(game.frame, state[0])
        self.assertGreater(game.player.x, state[1])
        self.assertEqual(sum(game.progression.stat_levels.values()), 1)

    def test_quick_click_survives_a_frame_without_a_simulation_tick(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        application = GameApplication(self.game, self.renderer, seed=1)
        application.activate_menu_action("start")
        application.update(0, key_state(), (800, 360), (False, False, False))
        application.handle_event(
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=(800, 360))
        )
        application.handle_event(
            pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=(800, 360))
        )
        frames = []
        for elapsed in (0.005, 0.015, 0.017):
            application.update(elapsed, key_state(), (800, 360), (False, False, False))
            frames.append((self.game.frame, self.game.player.ammo))

        # 게임 프레임이 진행되지 않은 화면의 짧은 클릭도 다음 프레임에 적용되는지 확인한다.
        self.assertEqual(frames, [(0, 120), (1, 119), (2, 119)])

    def test_q_and_space_do_not_activate_combat_actions(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        application = GameApplication(self.game, self.renderer, seed=1)
        application.activate_menu_action("start")

        # 제거된 Q·Space 전투 동작이 실행되지 않는지 확인한다.
        with patch.object(
            self.game.combat, "request_skill", wraps=self.game.combat.request_skill
        ) as skill:
            for key in (pygame.K_q, pygame.K_SPACE):
                application.handle_event(pygame.event.Event(pygame.KEYDOWN, key=key))
            application.update(
                1 / 60,
                key_state(pygame.K_q, pygame.K_SPACE),
                (800, 360),
                (False, False, False),
            )
            skill.assert_not_called()
        self.assertEqual(self.game.combat.bullets, [])
        self.assertEqual(self.game.frame, 1)

    def test_n_uses_8x8_random_blocks_without_loading_named_maps(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        application = GameApplication(self.game, self.renderer, seed=7)
        application.mode = "playing"
        config = self.game.config.terrain
        config.map_name = "belt"
        config.random_map = False
        config.block_tiles = 5
        self.game.progression._add_score(190)
        with patch(
            "space_z.game.game_core.load_map",
            side_effect=AssertionError("N must not load a named map"),
        ):
            application.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_n))

        # 새 맵 입력이 파일 맵 대신 8×8 블록 랜덤 지형을 만드는지 확인한다.
        self.assertTrue(config.enabled)
        self.assertTrue(config.random_map)
        self.assertEqual(config.block_tiles, 8)
        self.assertEqual(config.map_name, "belt")
        self.assertEqual(self.game.terrain.name, "random")
        self.assertTrue(self.game.terrain.is_connected(96))
        self.assertEqual((self.game.frame, self.game.progression.score), (0, 0))

        # 가장자리의 남는 영역을 제외하면 8×8 블록마다 바닥 또는 벽으로 채워진다.
        terrain = self.game.terrain
        off_c, off_r = (terrain.cols % 8) // 2, (terrain.rows % 8) // 2
        for row in range(off_r, terrain.rows - 7, 8):
            for col in range(off_c, terrain.cols - 7, 8):
                kinds = {
                    terrain.solid[tile_row][tile_col]
                    for tile_row in range(row, row + 8)
                    for tile_col in range(col, col + 8)
                }
                self.assertEqual(len(kinds), 1)

    def test_n_changes_seeded_maps_and_restart_replays_current_map(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        application = GameApplication(self.game, self.renderer, seed=7)
        application.mode = "playing"
        key = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_n)
        application.handle_event(key)
        first = [row[:] for row in self.game.terrain.tiles]
        application.handle_event(key)
        second = [row[:] for row in self.game.terrain.tiles]

        # 새 맵은 시드를 바꾸고 재시작은 현재 시드의 맵을 재현하는지 확인한다.
        self.assertNotEqual(first, second)
        self.assertEqual(application.seed, 9)
        application.activate_menu_action("restart")
        self.assertEqual(self.game.terrain.tiles, second)
        self.game.reset(8)
        self.assertEqual(self.game.terrain.tiles, first)


if __name__ == "__main__":
    unittest.main()
