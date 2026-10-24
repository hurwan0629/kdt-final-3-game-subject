"""적의 재등장·능력치·성장·감지·추적·조준을 관리한다."""
from __future__ import annotations
from space_z.game.types import AITarget, WorldPoint

import math
from typing import TYPE_CHECKING

from space_z.config.progression_definitions import STAT_UPGRADES, SHIPS, SHIPS_BY_LEVEL
from space_z.game.actions import N_MOVES, move_from_vector, wrap_angle
from space_z.game.entities import Tank

if TYPE_CHECKING:
    from space_z.game.game_core import GameCore


class EnemyController:
    """적의 재등장·능력치·성장·감지·추적·조준을 관리한다. 공통 월드는 game을 통해 조회한다."""

    def __init__(self, game: "GameCore") -> None:
        """코어 참조를 보관한다. 이번 판의 상태는 reset()에서 초기화한다."""
        self.game = game  # 현재 월드·설정·프레임과 다른 담당 객체에 접근하는 코어

    def reset(self) -> None:
        """새 판의 담당 상태를 초기화한다. 전투 난수는 소비하지 않는다."""
        self.enemy_scale_tier = 0  # 경과 시간에 따른 적 성장 단계

    def _respawn_enemy(self, enemy: Tank) -> None:
        """적의 종류·능력치를 다시 정하고 재등장 상태로 초기화한다.

        인자:
            enemy: 생성 또는 재등장시킬 적 Tank.

        처리:
            1) 플레이어 진화 단계에 맞는 종류·엘리트 여부·스탯을 추첨하고 능력치를 적용한다.
            2) 플레이어와 멀고 다른 적과 겹치지 않는 시작 위치를 우선 선택한다.
            3) 체력·속도·발사 대기·조준·AI 목표·경로를 초기화한다.

        반환:
            None: 전달받은 적 개체를 살아 있는 재등장 상태로 변경한다.
        """

        # 1) 플레이어 진화 단계에 맞는 종류·엘리트 여부·스탯을 추첨하고 능력치를 적용한다.
        terrain = self.game.terrain
        player = self.game.player
        enemy.job = self._random_enemy_job()
        enemy_ai_config = self.game.config.enemy_ai
        mercy_progress = self._mercy_factor()
        elite_chance = enemy_ai_config.elite_chance * (
            enemy_ai_config.mercy_elite_chance_scale
            + (1 - enemy_ai_config.mercy_elite_chance_scale) * mercy_progress
        )
        enemy.elite = bool(self.game.rng.random() < elite_chance)
        self._roll_enemy_stats(enemy)
        self._apply_enemy_strength(enemy)
        # 맵의 E 위치 중 플레이어와 멀고 다른 적과 겹치지 않는 곳 우선 (화면 안이든 밖이든 상관없음).
        # 2) 플레이어와 멀고 다른 적과 겹치지 않는 시작 위치를 우선 선택한다.
        others = [
            other_enemy
            for other_enemy in getattr(self.game, "enemies", [])
            if other_enemy.alive and other_enemy is not enemy
        ]
        starts = []
        for start_tile in terrain.enemy_starts:
            spawn_x, spawn_y = terrain.center(*start_tile)
            if not terrain.circle_fits(spawn_x, spawn_y, enemy.radius):
                continue
            if (spawn_x - player.x) ** 2 + (
                spawn_y - player.y
            ) ** 2 >= 300.0**2 and all(
                (spawn_x - other_enemy.x) ** 2 + (spawn_y - other_enemy.y) ** 2
                >= (2 * enemy.radius) ** 2
                for other_enemy in others
            ):
                starts.append((spawn_x, spawn_y))
        if starts:
            enemy.x, enemy.y = starts[int(self.game.rng.integers(len(starts)))]
        else:
            enemy.x, enemy.y = self.game._random_free_pos(enemy.radius, 300.0)

        # 3) 체력·속도·발사 대기·조준·AI 목표·경로를 초기화한다.
        enemy.velocity_x = enemy.velocity_y = 0.0
        enemy.hp = enemy.max_hp
        enemy.alive = True
        enemy.cooldown = enemy.fire_cooldown_max
        enemy.pending_shots.clear()
        enemy.angle = float(self.game.rng.uniform(-math.pi, math.pi))
        enemy.ai_timer = 0
        enemy.ai_target = None
        enemy.ai_can_see = False
        enemy.ai_last_seen = None
        enemy.ai_path = []
        enemy.ai_path_timer = 0
        enemy.ai_goal = None

    def _random_enemy_job(self) -> str:
        """플레이어와 같은 진화 단계의 적 우주선 종류를 추첨한다.

        인자:
            없음(self는 현재 게임 상태를 참조한다).

        처리:
            1) 플레이어 우주선과 같은 진화 단계의 후보 목록을 조회한다.
            2) 후보 중 하나를 균등 확률로 추첨한다.

        반환:
            str: SHIPS에서 사용하는 우주선 종류 키.
        """

        # 1) 플레이어 우주선과 같은 진화 단계의 후보 목록을 조회한다.
        jobs = SHIPS_BY_LEVEL[SHIPS[self.game.player.job].level]

        # 2) 후보 중 하나를 균등 확률로 추첨한다.
        return jobs[int(self.game.rng.integers(len(jobs)))]

    def _mercy_factor(self) -> float:
        """초반 적 약화가 정상 난이도로 돌아오는 진행도를 계산한다.

        인자:
            없음(self는 현재 게임 상태를 참조한다).

        처리:
            현재 프레임과 약화 지속 시간으로 진행도를 계산한다. 지속 시간이 0 이하면 즉시 완료로 처리한다.

        반환:
            float: 시작 시 0.0, 약화 종료 후 1.0인 진행도.
        """
        enemy_ai_config = self.game.config.enemy_ai
        if enemy_ai_config.mercy_seconds <= 0:
            return 1.0
        return min(
            1.0,
            self.game.frame / (enemy_ai_config.mercy_seconds * self.game.config.fps),
        )

    def _enemy_stat_budget(self) -> int:
        """플레이어 스탯 투자량을 기준으로 적의 강화 포인트 총량을 계산한다.

        인자:
            없음(self는 현재 게임 상태를 참조한다).

        처리:
            플레이어의 각 스탯 레벨에 반영 비율을 곱하고 항목별 정수 절삭값을 합산한다.

        반환:
            int: 적 한 개체에 배분할 스탯 포인트 수.
        """
        ratio = self.game.config.enemy_ai.stat_mirror_ratio
        return sum(
            int(self.game.progression.stat_levels.get(card.key, 0) * ratio)
            for card in STAT_UPGRADES
        )

    def _roll_enemy_stats(self, enemy: Tank) -> None:
        """적 강화 포인트를 스탯 항목에 무작위로 배분한다.

        인자:
            enemy: 스탯 배분을 갱신할 적 Tank.

        처리:
            1) 강화 항목과 포인트 총량을 구한다.
            2) 포인트가 없으면 모든 항목을 0으로 두고, 있으면 균등 확률의 다항분포로 배분한다.

        반환:
            None: enemy.stat_levels를 새 배분 결과로 교체한다.
        """

        # 1) 강화 항목과 포인트 총량을 구한다.
        keys = [card.key for card in STAT_UPGRADES]
        budget = self._enemy_stat_budget()

        # 2) 포인트가 없으면 모든 항목을 0으로 두고, 있으면 균등 확률의 다항분포로 배분한다.
        if budget <= 0:
            enemy.stat_levels = dict.fromkeys(keys, 0)
            return
        counts = self.game.rng.multinomial(budget, [1.0 / len(keys)] * len(keys))
        enemy.stat_levels = {
            key: int(level_count) for key, level_count in zip(keys, counts)
        }

    def _apply_enemy_strength(self, enemy: Tank) -> None:
        """성장 단계·초반 약화·엘리트·우주선·스탯을 합쳐 적 능력치를 갱신한다.

        인자:
            enemy: 능력치를 갱신할 적 Tank.

        처리:
            1) 성장 배율과 초반 약화·엘리트 배율, 기존 체력 비율을 계산한다.
            2) 스탯 배분이 없으면 추첨하고 항목별 레벨을 읽는다.
            3) 최대 체력·반지름·공격력·연사·이동·탄환 능력치를 갱신하되 현재 체력 비율은 유지한다.

        반환:
            None: 전달받은 적의 전투 능력치를 직접 변경한다.
        """

        # 1) 성장 배율과 초반 약화·엘리트 배율, 기존 체력 비율을 계산한다.
        config, enemy_ai_config, ship_spec = (
            self.game.config,
            self.game.config.enemy_ai,
            SHIPS[enemy.job],
        )
        tier = self.enemy_scale_tier
        mercy_progress = self._mercy_factor()
        hp_mercy = (
            enemy_ai_config.mercy_hp_scale
            + (1 - enemy_ai_config.mercy_hp_scale) * mercy_progress
        )
        damage_mercy = (
            enemy_ai_config.mercy_damage_scale
            + (1 - enemy_ai_config.mercy_damage_scale) * mercy_progress
        )
        fire_rate_mercy = (
            enemy_ai_config.mercy_fire_rate_scale
            + (1 - enemy_ai_config.mercy_fire_rate_scale) * mercy_progress
        )
        health_ratio = enemy.hp / enemy.max_hp if enemy.max_hp > 0 else 1.0
        # 대형 선체의 체력 보너스는 플레이어의 절반만 받는다.
        elite_hp, elite_damage = (
            (enemy_ai_config.elite_hp_scale, enemy_ai_config.elite_damage_scale)
            if enemy.elite
            else (1.0, 1.0)
        )
        # 플레이어의 upgrade_stat()과 같은 배율을 적용한다(health은 +25, 나머지는 레벨당 배율).
        # 어느 항목에 얼마나 찍혔는지는 개체마다 무작위로 다르다(_roll_enemy_stats).
        # 2) 스탯 배분이 없으면 추첨하고 항목별 레벨을 읽는다.
        if not enemy.stat_levels:
            self._roll_enemy_stats(enemy)
        levels = enemy.stat_levels
        health_level = levels.get("health", 0)
        damage_level = levels.get("damage", 0)
        rapid_level = levels.get("rapid", 0)
        speed_level = levels.get("speed", 0)
        range_level = levels.get("range", 0)

        # 3) 최대 체력·반지름·공격력·연사·이동·탄환 능력치를 갱신하되 현재 체력 비율은 유지한다.
        enemy.max_hp = (
            (config.enemy_hp + ship_spec.hp_bonus * 0.5 + 25 * health_level)
            * (1 + enemy_ai_config.hp_growth * tier)
            * elite_hp
            * hp_mercy
        )
        enemy.hp = enemy.max_hp * health_ratio
        enemy.radius = config.tank_radius * ship_spec.radius_scale
        enemy.damage_scale = (
            (1 + enemy_ai_config.damage_growth * tier)
            * elite_damage
            * damage_mercy
            * (1.25**damage_level)
        )
        rapid_factor = (
            (1 + enemy_ai_config.fire_rate_growth * tier)
            * fire_rate_mercy
            * ((1 / 0.95) ** rapid_level)
        )
        enemy.fire_cooldown_max = max(
            enemy_ai_config.min_fire_cooldown,
            round(enemy_ai_config.fire_cooldown / rapid_factor),
        )
        enemy.accel_scale = (1 + enemy_ai_config.speed_growth * tier) * (
            1.07**speed_level
        )
        enemy.bullet_speed_scale = 1.2**range_level
        enemy.bullet_life_scale = 1.15**range_level
        enemy.projectiles = len(ship_spec.shots)

    def _refresh_stats(self) -> None:
        """플레이어 강화에 맞춰 적 스탯을 재배분하고 능력치를 갱신한다.

        인자:
            없음(self.game은 현재 적 목록과 플레이어 강화 상태를 참조한다).

        처리:
            1) 적 목록 순서대로 스탯을 추첨하고 능력치를 다시 적용한다.
            2) 기존 발사 대기가 새 기본 발사 대기를 넘지 않도록 보정한다.

        반환:
            None: 적별 스탯·능력치·발사 대기를 갱신한다.
        """
        for enemy in self.game.enemies:
            # 1) 늘어난 포인트 총량을 다시 무작위로 재배분한다.
            self._roll_enemy_stats(enemy)
            self._apply_enemy_strength(enemy)

            # 2) 새 발사 대기에 맞춰 남은 대기를 보정한다.
            enemy.cooldown = min(enemy.cooldown, enemy.fire_cooldown_max)

    def _update_enemy_scaling(self) -> None:
        """경과 시간에 맞춰 적 성장 단계와 능력치를 갱신한다.

        인자:
            없음(self는 현재 게임 상태를 참조한다).

        처리:
            1) 현재 프레임으로 성장 단계를 계산하고 상한을 적용한다.
            2) 단계가 바뀌었거나 초반 약화 기간이면 모든 적의 능력치를 다시 적용한다.

        반환:
            None: 성장 단계와 필요한 적 능력치를 갱신한다.
        """

        # 1) 현재 프레임으로 성장 단계를 계산하고 상한을 적용한다.
        enemy_ai_config = self.game.config.enemy_ai
        tier = min(
            enemy_ai_config.max_scale_tier,
            int(
                self.game.frame
                / (enemy_ai_config.scale_interval_seconds * self.game.config.fps)
            ),
        )
        tier_changed = tier != self.enemy_scale_tier
        if tier_changed:
            self.enemy_scale_tier = tier

        # 2) 단계가 바뀌었거나 초반 약화 기간이면 모든 적의 능력치를 다시 적용한다.
        if (
            tier_changed
            or self.game.frame <= enemy_ai_config.mercy_seconds * self.game.config.fps
        ):
            for enemy in self.game.enemies:
                self._apply_enemy_strength(enemy)

    def _promote_enemies(self) -> None:
        """플레이어 진화에 맞춰 모든 적을 같은 단계의 우주선으로 진화시킨다.

        인자:
            없음(self는 현재 게임 상태를 참조한다).

        처리:
            1) 적마다 새 종류를 추첨하고 능력치를 다시 계산한다.
            2) 예약 점사를 취소하고 발사 대기를 제한하며 살아 있는 적의 지형 겹침을 보정한다.

        반환:
            None: 모든 적의 종류·능력치·발사 상태와 필요한 위치를 변경한다.
        """
        for enemy in self.game.enemies:
            # 1) 적마다 새 종류를 추첨하고 능력치를 다시 계산한다.
            enemy.job = self._random_enemy_job()
            self._apply_enemy_strength(enemy)

            # 2) 예약 점사를 취소하고 발사 대기를 제한하며 살아 있는 적의 지형 겹침을 보정한다.
            enemy.pending_shots.clear()
            enemy.cooldown = min(enemy.cooldown, enemy.fire_cooldown_max)
            if enemy.alive:
                self.game._fit_tank(enemy)

    def _enemy_ai(self, enemy: Tank) -> None:
        """적 하나의 감지·목표 선택·추적 이동·조준·발사를 처리한다.

        인자:
            enemy: 이번 프레임 행동을 결정할 살아 있는 적 Tank.

        처리:
            1) 시야·근거리 감지·발사 소리로 플레이어 위치를 기억하고 조건에 따라 동료에게 공유한다.
            2) 반응 주기에 맞춰 플레이어·마지막 위치·천체 중 목표와 조준 오차를 정한다.
            3) 직접 접근 가능한 경우 거리를 유지하고, 막히면 A* 경로를 따라 이동 방향을 정한다.
            4) 예측 조준과 발사 각도 조건을 계산해 이동·회전·발사를 실행한다.

        반환:
            None: 적과 동료의 AI 상태, 적 위치·무장 상태, 발사 탄환을 갱신한다.
        """
        config = self.game.config
        enemy_ai_config = config.enemy_ai
        player = self.game.player
        terrain = self.game.terrain

        # 1) 감지: 시야선이 트였으면 멀리서도 보고, 가까우면 벽 너머도 알아채고,
        #    플레이어가 쏘면 소리로 위치를 안다. 알게 된 위치는 항상 기억한다.
        dist = math.hypot(player.x - enemy.x, player.y - enemy.y)
        enemy.ai_can_see = (
            player.alive
            and dist <= enemy_ai_config.sight_range
            and terrain.line_of_sight(enemy.x, enemy.y, player.x, player.y)
        )
        heard = (
            self.game.frame - self.game.combat.player_shot_frame
            <= enemy_ai_config.hearing_frames
            and dist <= enemy_ai_config.hearing_range
        )
        sensed = player.alive and (dist <= enemy_ai_config.sense_range or heard)
        knew = enemy.ai_last_seen is not None
        if enemy.ai_can_see or sensed:
            enemy.ai_last_seen = (player.x, player.y)
            enemy.ai_last_seen_frame = self.game.frame
        elif (
            knew
            and self.game.frame - enemy.ai_last_seen_frame
            > enemy_ai_config.memory_frames
        ):
            # 벽을 돌아 마지막 위치로 가는 중이면 도착할 때까지 잊지 않는다 (도착하면 포기).
            following = (
                enemy.ai_target is not None
                and enemy.ai_target[0] == "point"
                and enemy.ai_path
            )
            if not following:
                enemy.ai_last_seen = None
        # 본 적이 근처 동료에게 위치를 알린다. 초반에는 혼자 싸우고 일정 시간 뒤부터 부른다.
        if (
            enemy.ai_can_see
            and self.game.frame >= enemy_ai_config.alert_start_seconds * config.fps
        ):
            for ally in self.game.enemies:
                if (
                    ally is not enemy
                    and ally.alive
                    and not ally.ai_can_see
                    and math.hypot(ally.x - enemy.x, ally.y - enemy.y)
                    <= enemy_ai_config.alert_range
                ):
                    ally.ai_last_seen = (player.x, player.y)
                    ally.ai_last_seen_frame = self.game.frame
        # 플레이어를 새로 알아챘거나 눈앞에 보이는데 다른 걸 쫓고 있으면 바로 목표를 바꾼다.
        hunting = enemy.ai_target is not None and enemy.ai_target[0] in (
            "player",
            "point",
        )
        if (enemy.ai_last_seen is not None and not hunting) or (
            enemy.ai_can_see and (enemy.ai_target or ("",))[0] != "player"
        ):
            enemy.ai_timer = 0

        # 2) 목표 선택 (reaction_frames마다): 플레이어를 알고 있으면 무조건 사냥, 모를 때만 천체를 깬다
        enemy.ai_timer -= 1
        if enemy.ai_timer <= 0:
            enemy.ai_timer = enemy_ai_config.reaction_frames
            target: AITarget | None
            if enemy.ai_can_see:
                target = ("player", player.id)
            elif enemy.ai_last_seen is not None:
                target = ("point", enemy.ai_last_seen)
            else:
                target, nearest_distance = None, float("inf")
                for shape in self.game.shapes:
                    distance = math.hypot(shape.x - enemy.x, shape.y - enemy.y)
                    if distance < nearest_distance:
                        target, nearest_distance = ("shape", shape.id), distance
            if target != enemy.ai_target:
                enemy.ai_path_timer = 0  # 목표가 바뀌면 경로 즉시 재계산
            enemy.ai_target = target
            aim_noise_degrees = enemy_ai_config.aim_noise_deg * max(
                0.4, 1 - enemy_ai_config.aim_noise_decay * self.enemy_scale_tier
            )
            enemy.ai_aim_offset = float(
                self.game.rng.normal(0.0, math.radians(aim_noise_degrees))
            )
            enemy.ai_strafe = 1.0 if self.game.rng.random() < 0.5 else -1.0
            if target is None:
                enemy.ai_move = int(self.game.rng.integers(0, N_MOVES))

        target_position = self._target_pos(enemy)
        if (
            target_position is None
            and enemy.ai_target is not None
            and enemy.ai_target[0] != "player"
        ):
            # 쫓던 천체가 (다른 적에게) 부서져 사라졌을 수 있다. 다음 반응 주기까지
            # 기다리지 않고 바로 새 목표를 고르게 해서 구석에 계속 머무르지 않게 한다.
            enemy.ai_target = None
            enemy.ai_path = []
            enemy.ai_timer = 0

        # 3) 목표까지 직접 이동하거나 A* 경로를 따라 이동 방향을 결정한다.
        can_move_directly = False
        move = enemy.ai_move if enemy.ai_target is None else 0
        enemy.ai_goal = target_position
        if target_position is not None:
            assert enemy.ai_target is not None  # _target_pos()의 유효한 반환 조건
            target_x, target_y = target_position
            kind = enemy.ai_target[0]
            can_move_directly = kind != "point" and terrain.segment_fits(
                enemy.x, enemy.y, target_x, target_y, enemy.radius
            )
            if can_move_directly:
                # 직접 보이면: 적정 거리 유지 + 옆으로 돌기
                enemy.ai_path = []
                delta_x, delta_y = target_x - enemy.x, target_y - enemy.y
                distance = math.hypot(delta_x, delta_y) + 1e-6
                preferred_distance = (
                    enemy_ai_config.keep_distance if kind == "player" else 140.0
                )
                if distance > preferred_distance + 40:
                    move_direction_x, move_direction_y = (
                        delta_x / distance,
                        delta_y / distance,
                    )
                elif distance < preferred_distance - 40:
                    move_direction_x, move_direction_y = (
                        -delta_x / distance,
                        -delta_y / distance,
                    )
                else:
                    move_direction_x, move_direction_y = (
                        -delta_y / distance * enemy.ai_strafe,
                        delta_x / distance * enemy.ai_strafe,
                    )
            else:
                # 안 보이면: A* 경로를 따라감
                enemy.ai_path_timer -= 1
                if enemy.ai_path_timer <= 0:
                    enemy.ai_path_timer = enemy_ai_config.path_recompute_frames
                    target_tile = terrain.tile_of(target_x, target_y)
                    if not terrain.circle_fits(
                        *terrain.center(*target_tile), enemy.radius
                    ):
                        safe = terrain.navigation_tiles(enemy.radius)
                        target_tile = (
                            min(
                                safe,
                                key=lambda tile: (
                                    (terrain.center(*tile)[0] - target_x) ** 2
                                    + (terrain.center(*tile)[1] - target_y) ** 2
                                ),
                            )
                            if safe
                            else target_tile
                        )
                    enemy.ai_path = terrain.astar(
                        terrain.tile_of(enemy.x, enemy.y),
                        target_tile,
                        radius=enemy.radius,
                    )
                while enemy.ai_path:
                    waypoint_x, waypoint_y = terrain.center(*enemy.ai_path[0])
                    if (waypoint_x - enemy.x) ** 2 + (
                        waypoint_y - enemy.y
                    ) ** 2 < enemy_ai_config.waypoint_reach**2:
                        enemy.ai_path.pop(0)
                    else:
                        break
                if enemy.ai_path:
                    waypoint_x, waypoint_y = terrain.center(*enemy.ai_path[0])
                    move_direction_x, move_direction_y = (
                        waypoint_x - enemy.x,
                        waypoint_y - enemy.y,
                    )
                else:
                    move_direction_x, move_direction_y = 0.0, 0.0
                    if (
                        kind == "point"
                        and (target_x - enemy.x) ** 2 + (target_y - enemy.y) ** 2
                        < (terrain.tile * 0.5) ** 2
                    ):
                        enemy.ai_last_seen = None  # 마지막 위치에 왔는데 없음 → 포기
                        enemy.ai_timer = 0
            move = move_from_vector(move_direction_x, move_direction_y)

        # 4) 조준/발사: 목표가 시야에 있을 때만 쏜다
        rotation = 0
        aligned = False
        if target_position is not None:
            assert enemy.ai_target is not None
            aim_x, aim_y = target_position
            if (
                enemy.ai_target[0] == "player"
                and enemy.ai_can_see
                and enemy_ai_config.lead_aim
            ):
                # 탄이 날아가는 동안 플레이어가 움직일 위치를 예측해 쏜다.
                speed = (
                    self.game.combat.weapon_values(enemy)[3]
                    * SHIPS[enemy.job].shots[0].speed
                )
                lead_frames = (
                    min(
                        60.0,
                        math.hypot(player.x - enemy.x, player.y - enemy.y)
                        / max(1e-6, speed),
                    )
                    * enemy_ai_config.lead_aim
                )
                aim_x, aim_y = (
                    player.x + player.velocity_x * lead_frames,
                    player.y + player.velocity_y * lead_frames,
                )
            desired_angle_radians = (
                math.atan2(aim_y - enemy.y, aim_x - enemy.x) + enemy.ai_aim_offset
            )
            angle_difference = wrap_angle(desired_angle_radians - enemy.angle)
            rotation_per_frame = config.turn_speed * enemy_ai_config.turn_speed_scale
            if angle_difference > rotation_per_frame:
                rotation = 2
            elif angle_difference < -rotation_per_frame:
                rotation = 1
            aligned = abs(angle_difference) <= math.radians(
                enemy_ai_config.fire_angle_tol_deg
            )
        fire_target_kind = enemy.ai_target[0] if enemy.ai_target else None
        can_fire = (fire_target_kind == "player" and enemy.ai_can_see) or (
            fire_target_kind == "shape" and can_move_directly
        )

        self.game._apply_tank_control(
            enemy,
            move,
            rotation,
            enemy_ai_config.move_speed_scale * enemy.accel_scale,
            enemy_ai_config.turn_speed_scale,
        )
        self.game.combat._fire(enemy, aligned and can_fire)

    def _target_pos(self, enemy: Tank) -> WorldPoint | None:
        """적 AI가 현재 추적해야 할 목표 좌표를 조회한다.

        인자:
            enemy: 목표 정보와 마지막 플레이어 위치를 가진 적 Tank.

        처리:
            1) 목표가 없거나 사라졌는지 확인한다.
            2) 목표 종류에 따라 보이는 플레이어·기억한 위치·지정 지점·천체의 좌표를 선택한다.

        반환:
            tuple[float, float] 또는 None: 목표 월드 좌표(x, y). 유효한 목표 위치가 없으면 None.
        """

        # 1) 목표가 없거나 사라졌는지 확인한다.
        target = enemy.ai_target
        if target is None:
            return None

        # 2) 목표 종류에 따라 보이는 플레이어·기억한 위치·지정 지점·천체의 좌표를 선택한다.
        kind, target_value = target
        if kind == "player":
            if not self.game.player.alive:
                return None
            return (
                (self.game.player.x, self.game.player.y)
                if enemy.ai_can_see
                else enemy.ai_last_seen
            )
        if target[0] == "point":
            return enemy.ai_last_seen or target[1]
        for shape in self.game.shapes:
            if shape.id == target_value:
                return (shape.x, shape.y)
        return None
