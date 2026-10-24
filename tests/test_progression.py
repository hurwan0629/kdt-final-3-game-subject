"""월드/레벨업/카메라 회귀 검증. GUI 없이 실행 가능.

python -m unittest discover -shape tests -v
"""

import math
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import numpy as np
import pygame

from space_z.config import GameConfig, ObsConfig
from space_z.rl.environment import TankEnv, build_vector
from space_z.game.game_core import Bullet, GameCore, encode_action
from space_z.config.progression_definitions import (
    STAT_MAX_LEVEL,
    STAT_UPGRADES,
    SPECIAL_REWARDS,
)
from space_z.rendering.progression_panel import (
    get_evolution_card_rects,
    build_stat_upgrade_rows,
)
from space_z.rendering.renderer import Renderer
from space_z.game.terrain import list_maps


def empty_game(seed=7):
    config = GameConfig(num_enemies=0, num_shapes=0)
    config.terrain.enabled = False
    return GameCore(config, seed=seed)


class ProgressionTests(unittest.TestCase):
    def test_score_sources_and_multiple_levels(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        game = GameCore(seed=4)
        shape = game.shapes[0]
        score = shape.score
        game.combat._damage_shape(shape, shape.hp, by_player=True)
        game.combat._damage_tank(game.enemies[0], 1000, by_player=True)

        # 점수 출처별 보상과 한 번에 여러 단계의 레벨업을 확인한다.
        self.assertEqual(game.progression.score, score + game.config.enemy_kill_score)
        expected_xp, expected_level = game.progression.score, 1
        while expected_xp >= 60 + (expected_level - 1) * 40:
            expected_xp -= 60 + (expected_level - 1) * 40
            expected_level += 1
        self.assertEqual(
            (
                game.progression.level,
                game.progression.xp,
                game.progression.pending_rewards,
            ),
            (expected_level, expected_xp, expected_level - 1),
        )

    def test_cards_are_unique_persistent_and_consumed_once(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        game = empty_game()

        # 보상 카드가 중복되지 않고 선택 전까지 유지되며 한 번만 소비되는지 확인한다.
        self.assertEqual(game.progression.open_rewards(), ())
        game.progression._add_score(190)
        self.assertEqual(
            (
                game.progression.level,
                game.progression.xp,
                game.progression.pending_rewards,
            ),
            (3, 30, 2),
        )
        self.assertEqual(game.progression.open_rewards(), ())
        game.progression._add_score(1790)
        self.assertEqual(
            (
                game.progression.level,
                game.progression.upgrade_points,
                game.progression.special_reward_levels,
            ),
            (10, 8, [10]),
        )
        cards = game.progression.open_rewards()
        self.assertEqual(len({card.key for card in cards}), 4)
        self.assertEqual(game.progression.open_rewards(), cards)
        self.assertFalse(game.progression.choose_reward(-1))
        self.assertFalse(game.progression.choose_reward(4))
        self.assertEqual(game.progression.pending_rewards, 9)
        self.assertTrue(game.progression.choose_reward(0))
        self.assertEqual(game.progression.pending_rewards, 8)
        self.assertFalse(game.progression.choose_reward(0))
        self.assertEqual(game.progression.open_rewards(), ())

    def test_every_tenth_level_queues_special_rewards_without_losing_stat_points(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        game = empty_game()
        game.progression._add_score(7980)

        # 10레벨마다 진화 보상이 쌓이고 일반 강화 포인트도 보존되는지 확인한다.
        self.assertEqual(
            (
                game.progression.level,
                game.progression.xp,
                game.progression.upgrade_points,
                game.progression.special_reward_levels,
            ),
            (20, 0, 17, [10, 20]),
        )
        first = game.progression.reward_choices
        self.assertTrue(game.progression.upgrade_stat("hull"))
        self.assertEqual(game.progression.reward_choices, first)
        self.assertTrue(game.progression.choose_reward(0))
        self.assertEqual(game.progression.special_reward_levels, [20])
        self.assertEqual(len(game.progression.reward_choices), 2)
        self.assertEqual(game.progression.upgrade_points, 16)
        self.assertTrue(game.progression.choose_reward(0))
        self.assertEqual(game.progression.special_reward_levels, [])

    def test_regen_rate_scales_with_max_hp_from_hull_upgrades(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        game = empty_game()
        config, player = game.config, game.player
        game.progression.level, game.progression.upgrade_points = 2, 2
        player.hp = 1.0
        player.last_hit_frame = -(10**9)  # 회복 대기 시간 지남
        game.combat._regen_player()
        base_regen = player.hp - 1.0

        # 최대 체력 증가 비율에 맞춰 프레임당 회복량이 증가하는지 확인한다.
        self.assertAlmostEqual(base_regen, config.regen_rate)
        self.assertTrue(game.progression.upgrade_stat("hull"))
        self.assertTrue(game.progression.upgrade_stat("hull"))
        self.assertEqual(player.max_hp, config.player_hp + 50)
        player.hp = 1.0
        game.combat._regen_player()
        boosted_regen = player.hp - 1.0
        # 최대 체력이 늘어난 비율만큼 회복량도 같이 커진다 (최대 체력 대비 %는 그대로 유지).
        self.assertAlmostEqual(
            boosted_regen, base_regen * (player.max_hp / config.player_hp)
        )
        self.assertGreater(boosted_regen, base_regen)

    def test_every_card_changes_the_advertised_stat(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        for card in STAT_UPGRADES:
            with self.subTest(card=card.key):
                game = empty_game()
                game.progression.level, game.progression.upgrade_points = 3, 1
                player = game.player
                player.hp = 20
                player.ammo = 20
                self.assertTrue(game.progression.upgrade_stat(card.key))
                self.assertEqual(game.progression.pending_rewards, 0)
                self.assertEqual(game.progression.last_reward, card.title)
                if card.key == "damage":
                    game.combat._fire(player, True)
                    self.assertEqual(
                        game.combat.bullets[0].damage, game.config.bullet_damage * 1.25
                    )
                elif card.key == "rapid":
                    self.assertEqual(player.fire_cooldown_max, 27)
                elif card.key == "speed":
                    game._apply_tank_control(player, 3, 0, player.accel_scale, 1)
                    self.assertAlmostEqual(player.velocity_x, game.config.accel * 1.07)
                elif card.key == "hull":
                    self.assertEqual((player.max_hp, player.hp), (125, 45))
                elif card.key == "range":
                    game.combat._fire(player, True)
                    bullet = game.combat.bullets[0]
                    self.assertAlmostEqual(
                        math.hypot(bullet.velocity_x, bullet.velocity_y),
                        game.config.bullet_speed * 1.2,
                    )
                    self.assertEqual(bullet.life, int(game.config.bullet_life * 1.15))

    def test_health_and_fire_rate_limits(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        game = empty_game()
        game.progression.upgrade_points = 100
        for _ in range(40):
            game.progression.upgrade_stat("rapid")

        # 체력 회복과 발사속도 강화가 설정한 한도를 지키는지 확인한다.
        self.assertEqual(game.player.hp, game.player.max_hp)
        # 능력치마다 최대 7단계: 28 → 27 → 26 → 25 → 24 → 23 → 22 → 21
        self.assertEqual(game.progression.stat_levels["rapid"], STAT_MAX_LEVEL)
        self.assertEqual(game.player.fire_cooldown_max, 21)
        self.assertEqual(game.combat.reload_frames_total, 150)
        points = game.progression.upgrade_points
        self.assertFalse(game.progression.upgrade_stat("rapid"))
        self.assertFalse(game.progression.upgrade_stat("reload"))
        self.assertFalse(game.progression.upgrade_stat("bogus"))
        self.assertEqual(game.progression.upgrade_points, points)

    def test_five_stats_and_unspent_points_survive_later_levels_and_evolution(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        game = empty_game()
        keys = ("hull", "damage", "range", "rapid", "speed")

        # 레벨업과 진화 뒤에도 스탯 단계와 미사용 포인트가 유지되는지 확인한다.
        self.assertEqual(
            tuple(card.key for card in game.progression.open_stat_upgrades()), keys
        )
        self.assertEqual(game.progression.upgrade_points, 0)
        game.progression._add_score(1980)
        self.assertEqual(game.progression.upgrade_points, 8)
        game.progression.choose_reward(0)
        game.progression._add_score(7980 - game.progression.score)
        self.assertEqual(game.progression.upgrade_points, 17)
        self.assertEqual(
            tuple(card.key for card in game.progression.open_stat_upgrades()), keys
        )
        game.progression.choose_reward(1)
        self.assertEqual(game.progression.upgrade_points, 17)
        self.assertTrue(game.progression.upgrade_stat("speed"))
        self.assertEqual(game.progression.upgrade_points, 16)
        self.assertEqual(
            tuple(card.key for card in game.progression.open_stat_upgrades()), keys
        )
        for removed in ("regen", "magazine", "reload"):
            self.assertFalse(game.progression.upgrade_stat(removed))
        game.reset(7)
        self.assertEqual(game.progression.upgrade_points, 0)
        self.assertTrue(
            all(count == 0 for count in game.progression.stat_levels.values())
        )

    def test_seed_reset_and_reward_rng_do_not_change_combat_rng(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        first_game, second_game = empty_game(), empty_game()
        first_game.progression._add_score(1980)
        second_game.progression._add_score(1980)
        cards = first_game.progression.open_rewards()

        # 보상 선택과 새 판 초기화가 전투 난수의 재현성을 바꾸지 않는지 확인한다.
        self.assertEqual(cards, second_game.progression.open_rewards())
        first_game.progression.reward_choices = ()
        first_game.progression.open_rewards()
        np.testing.assert_array_equal(
            first_game.rng.random(10), second_game.rng.random(10)
        )
        first_game.progression.choose_reward(0)
        first_game.reset(7)
        self.assertEqual(
            (
                first_game.progression.level,
                first_game.progression.xp,
                first_game.progression.pending_rewards,
                first_game.progression.reward_choices,
            ),
            (1, 0, 0, ()),
        )
        self.assertEqual(first_game.player.job, "rookie")
        self.assertEqual(first_game.player.damage_scale, 1)
        self.assertEqual(first_game.config.player_hp, 100)
        first_game.game_over = True
        first_game.progression.special_reward_levels = [10]
        self.assertEqual(first_game.progression.open_rewards(), ())
        self.assertFalse(first_game.progression.choose_reward(0))


class OwnershipTests(unittest.TestCase):
    def test_reset_keeps_controllers_and_clears_previous_round(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        game = empty_game()
        owners = (game.progression, game.combat, game.enemy_controller)
        old_player, old_terrain = game.player, game.terrain
        game.progression._add_score(1980)
        game.progression.record_kill()
        game.combat._fire(game.player, True)
        game.combat.reload_frames_left = 20
        game.enemy_controller.enemy_scale_tier = 5

        # 담당 객체는 재사용하고 이전 판의 진행 상태는 비우는지 확인한다.
        self.assertTrue(game.combat.bullets)
        self.assertTrue(game.progression.reward_choices)

        game.reset(7)

        self.assertEqual(owners, (game.progression, game.combat, game.enemy_controller))
        self.assertTrue(all(owner.game is game for owner in owners))
        self.assertIsNot(game.player, old_player)
        self.assertIsNot(game.terrain, old_terrain)
        self.assertEqual(
            (
                game.progression.score,
                game.progression.kills,
                game.progression.level,
                game.progression.xp,
                game.progression.upgrade_points,
            ),
            (0, 0, 1, 0, 0),
        )
        self.assertEqual(game.progression.reward_choices, ())
        self.assertEqual(game.combat.bullets, [])
        self.assertEqual(game.combat.reload_frames_left, 0)
        self.assertEqual(game.enemy_controller.enemy_scale_tier, 0)

        game.player.x, game.player.y, game.player.angle = 500, 500, 0
        game.combat._fire(game.player, True)
        self.assertEqual(game.combat.bullets[0].owner_id, game.player.id)
        self.assertGreater(game.combat.bullets[0].x, game.player.x)
        self.assertEqual(game.combat.bullets[0].y, game.player.y)
        game.progression.upgrade_points = 1
        self.assertTrue(game.progression.upgrade_stat("hull"))
        self.assertEqual(game.player.max_hp, game.config.player_hp + 25)
        self.assertEqual(old_player.max_hp, game.config.player_hp)

    def test_damage_records_kill_through_progression_once(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        config = GameConfig(num_enemies=1, num_shapes=0)
        config.terrain.enabled = False
        game = GameCore(config, seed=7)
        enemy = game.enemies[0]
        enemy.elite = False
        with patch.object(
            game.progression, "record_kill", wraps=game.progression.record_kill
        ) as record:
            game.combat._damage_tank(enemy, 100000, True)
            game.combat._damage_tank(enemy, 100000, True)

        # 피해 처리로 발생한 처치가 성장 상태에 한 번만 반영되는지 확인한다.
        record.assert_called_once_with()
        self.assertEqual(game.progression.kills, 1)
        self.assertEqual(game.progression.score, config.enemy_kill_score)
        self.assertEqual(
            game.score_award_events,
            [(0, enemy.x, enemy.y, config.enemy_kill_score, "enemy")],
        )
        self.assertFalse(hasattr(game.combat, "score_popups"))

    def test_score_award_events_are_independent_consumed_once_and_reset(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        game = empty_game()
        random_state = game.rng.bit_generator.state
        game.record_score_award(100, 200, 10, "square")
        game.frame = 3
        game.record_score_award(300, 400, 200, "enemy")
        reward_events = game.pop_events()

        # 점수 이벤트가 학습 이벤트와 독립적이며 한 번만 소비되는지 확인한다.
        self.assertNotIn("score_award_events", reward_events)
        self.assertEqual(
            game.pop_score_award_events(),
            [(0, 100, 200, 10, "square"), (3, 300, 400, 200, "enemy")],
        )
        self.assertEqual(game.pop_score_award_events(), [])
        self.assertEqual(game.progression.score, 0)
        self.assertEqual(game.rng.bit_generator.state, random_state)
        game.record_score_award(0, 0, 10, "triangle")
        game.reset(7)
        self.assertEqual(game.score_award_events, [])

    def test_shape_destruction_records_its_position_and_score_once(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        game = empty_game()
        shape = game._make_shape()
        game.combat._damage_shape(shape, shape.hp, True)
        game.combat._damage_shape(shape, shape.max_hp, True)

        # 천체 파괴 시 원래 위치와 점수가 한 번만 기록되는지 확인한다.
        self.assertEqual(
            game.pop_score_award_events(),
            [(0, shape.x, shape.y, shape.score, shape.kind)],
        )
        self.assertEqual(game.progression.score, shape.score)

    def test_headless_environment_discards_score_awards_without_changing_results(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        game_config = GameConfig(num_enemies=0, num_shapes=0)
        game_config.terrain.enabled = False
        environment = TankEnv(game_config=game_config)
        reference = TankEnv(game_config=game_config)
        environment.reset(seed=7)
        reference.reset(seed=7)
        original_step = environment.game.step

        # 화면 없는 학습이 점수 연출 이벤트를 버려도 게임 결과는 유지되는지 확인한다.
        def step_with_score_award(action):
            self.assertEqual(environment.game.score_award_events, [])
            original_step(action)
            environment.game.record_score_award(10, 20, 10, "square")

        with patch.object(environment.game, "step", side_effect=step_with_score_award):
            for action in (0, 1, 2):
                actual = environment.step(action)
                expected = reference.step(action)
                np.testing.assert_array_equal(actual[0], expected[0])
                self.assertEqual(actual[1:], expected[1:])
                self.assertEqual(environment.game.score_award_events, [])
        self.assertIsNone(environment._renderer)

    def test_reload_finishes_after_frame_increment_before_death_check(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        game = empty_game()
        game.player.ammo = 0
        game.combat.reload_frames_left = 1
        frames = []
        original_finish = game.combat._finish_frame

        def finish_frame():
            frames.append(game.frame)
            original_finish()

        with patch.object(
            game.combat, "_finish_frame", side_effect=finish_frame
        ) as finish:
            game.step(0, want_fire=False)

        # 프레임 증가 뒤 사망 판정 전에 재장전 완료가 처리되는지 확인한다.
        finish.assert_called_once_with()
        self.assertEqual(frames, [1])
        self.assertEqual((game.frame, game.player.ammo), (1, game.player.max_ammo))
        game.player.hp = 0
        game.player.ammo = 0
        game.combat.reload_frames_left = 1
        game.step(0, want_fire=False)
        self.assertEqual(game.player.ammo, 0)
        self.assertTrue(game.game_over)

    def test_controller_resets_do_not_consume_combat_rng(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        game = empty_game()
        before = game.rng.bit_generator.state
        game.progression.reset(123)
        game.combat.reset()
        game.enemy_controller.reset()

        # 담당 객체 초기화가 전투 난수를 소비하지 않는지 확인한다.
        self.assertEqual(game.rng.bit_generator.state, before)


class WorldTests(unittest.TestCase):
    def test_all_expanded_maps_connected_in_both_terrain_modes(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        for name in list_maps():
            for stage2 in (False, True):
                config = GameConfig(num_shapes=0, num_enemies=0)
                config.terrain.map_name = name
                config.terrain.mud_enabled = config.terrain.breakable_enabled = stage2
                game = GameCore(config, seed=1)
                with self.subTest(map=name, stage2=stage2):
                    self.assertEqual((game.terrain.cols, game.terrain.rows), (134, 101))
                    self.assertTrue(game.terrain.is_connected())
                    self.assertFalse(
                        game.terrain.is_solid_at(game.player.x, game.player.y)
                    )
        config.world_scale = 1

        # 모든 확장 맵에서 지형 옵션별 연결성을 확인한다.
        self.assertEqual(GameCore(config).terrain.cols, 27)

    def test_world_boundary_and_bullets_beyond_the_viewport(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        game = empty_game()
        player = game.player
        player.x, player.y = 1800, 1400
        game.step(encode_action(3, 0))

        # 화면 밖 월드에서도 개체와 탄환이 유효하게 진행되는지 확인한다.
        self.assertGreater(player.x, 1800)
        bullet = Bullet(
            1800,
            1400,
            9,
            0,
            70,
            player.id,
            "player",
            7,
            6,
        )
        game.combat.bullets = [bullet]
        game.combat._move_bullets()
        self.assertEqual(game.combat.bullets, [bullet])
        player.x, player.y = game.config.world_width + 10, game.config.world_height + 10
        game._clamp_to_arena(player)
        self.assertEqual(player.x, game.config.world_width - player.radius)
        self.assertEqual(player.y, game.config.world_height - player.radius)

    def test_rl_default_progression_and_world_normalization(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        environment = TankEnv()

        # 학습 기본 설정과 월드 크기 기준의 관측 정규화를 확인한다.
        self.assertFalse(environment.game_config.progression_enabled)
        observation, _ = environment.reset(seed=1)
        self.assertEqual(observation.shape, (241,))
        environment.game.progression._add_score(1000)
        self.assertEqual(environment.game.progression.level, 1)
        environment.game.player.x = environment.game_config.world_width / 2
        environment.game.player.y = environment.game_config.world_height / 2
        vector = build_vector(environment.game, ObsConfig())
        self.assertAlmostEqual(vector[0], 0.5)
        self.assertAlmostEqual(vector[1], 0.5)
        _, _, _, _, info = environment.step(0)
        self.assertEqual(info["pending_rewards"], 0)


class RendererTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        pygame.init()
        cls.game = empty_game()
        cls.game.config.window_width, cls.game.config.window_height = 960, 720
        cls.renderer = Renderer(cls.game.config)

    @classmethod
    def tearDownClass(cls):
        pygame.quit()

    def test_camera_center_boundary_and_render_without_state_mutation(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        game, renderer = self.game, self.renderer
        player = game.player
        player.x, player.y = 1500, 1200
        renderer._update_camera(player)

        # 카메라가 플레이어를 따르고 렌더링은 게임 상태를 바꾸지 않는지 확인한다.
        self.assertEqual(renderer.world_to_screen(player.x, player.y), (480, 360))
        state = (game.frame, player.x, player.y, player.hp, game.progression.score)
        renderer.draw(game, show_ai=True)
        self.assertEqual(
            (game.frame, player.x, player.y, player.hp, game.progression.score), state
        )
        self.assertEqual(renderer.screen.get_size(), (960, 720))
        player.x, player.y = player.radius, player.radius
        renderer._update_camera(player)
        self.assertEqual(
            renderer.world_to_screen(player.x, player.y),
            (renderer.size[0] / 2, renderer.size[1] / 2),
        )
        self.assertLess(renderer.camera_x, 0)
        self.assertLess(renderer.camera_y, 0)
        player.x = game.config.world_width - player.radius
        player.y = game.config.world_height - player.radius
        renderer._update_camera(player)
        self.assertEqual(
            renderer.world_to_screen(player.x, player.y),
            (renderer.size[0] / 2, renderer.size[1] / 2),
        )
        self.assertGreater(
            renderer.camera_x + renderer.view_width, game.config.world_width
        )
        self.assertGreater(
            renderer.camera_y + renderer.view_height, game.config.world_height
        )
        game.progression._add_score(190)
        game.progression.open_rewards()
        renderer.draw(game)

    def test_rewards_are_selected_in_hud_without_pausing_combat(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        from space_z.app import GameApplication
        from collections import defaultdict

        game = empty_game()
        application = GameApplication(game, self.renderer, seed=7)
        application.activate_menu_action("start")
        game.progression._add_score(1980)
        key = lambda stat_key: application.handle_event(
            pygame.event.Event(pygame.KEYDOWN, key=stat_key)
        )
        cards = game.progression.reward_choices
        choice = game.progression.stat_choices[0].key
        key(pygame.K_1)

        # HUD에서 보상을 선택하는 동안에도 전투가 계속되는지 확인한다.
        self.assertEqual(game.progression.stat_levels[choice], 1)
        application.update(0.1, defaultdict(bool), (480, 360), (False, False, False))
        self.assertGreater(game.frame, 0)
        key(pygame.K_ESCAPE)
        self.assertEqual(application.mode, "pause")
        key(pygame.K_ESCAPE)
        self.assertEqual(game.progression.reward_choices, cards)
        key(pygame.K_F2)
        self.assertEqual(game.progression.special_reward_levels, [])
        self.assertEqual(game.progression.upgrade_points, 7)

    def test_hud_rows_and_cards_fit_without_overlapping_health_panel(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        game = self.game
        game.reset(7)
        game.progression._add_score(1980)
        screen = pygame.Rect(0, 0, 960, 720)
        hp_panel = pygame.Rect(314, 620, 332, 84)

        # HUD와 진화 카드가 체력 패널과 겹치지 않는지 확인한다.
        for _, rect in build_stat_upgrade_rows(960, 720):
            self.assertTrue(screen.contains(pygame.Rect(rect)))
            self.assertFalse(hp_panel.colliderect(pygame.Rect(rect)))
        for rect in get_evolution_card_rects(960, 720):
            self.assertTrue(screen.contains(pygame.Rect(rect)))
        self.renderer.draw(game)

    def test_wounded_enemies_render_without_removed_stealth_api(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        config = GameConfig(num_enemies=1, num_shapes=0)
        config.terrain.enabled = False
        game = GameCore(config, seed=7)
        enemy = game.enemies[0]
        enemy.hp -= 1
        enemy.x, enemy.y = game.player.x + 80, game.player.y
        health = enemy.hp
        self.renderer.draw(game)

        # 제거된 은신 기능 없이도 피격한 적을 정상적으로 그리는지 확인한다.
        self.assertEqual(enemy.hp, health)
        self.assertTrue(enemy.alive)

    def test_zoom_setting_rebuilds_view_and_keeps_hud_resolution(self):
        # 검사에 사용할 설정·개체·입력을 준비한다.
        renderer = self.renderer

        # 줌 변경은 월드 표시 영역만 바꾸고 HUD 해상도는 유지하는지 확인한다.
        try:
            renderer.set_zoom(0.75)
            renderer._update_camera(self.game.player)
            self.assertEqual(renderer._view.get_size(), (1280, 960))
            self.assertAlmostEqual(renderer.effective_zoom, 0.75)
            self.assertEqual(renderer.screen.get_size(), (960, 720))
            position = renderer.screen_to_world(480, 360)
            self.assertEqual(renderer.world_to_screen(*position), (480, 360))
            renderer.draw(self.game, show_controls=False)
        finally:
            renderer.set_zoom(0.6)


if __name__ == "__main__":
    unittest.main()
