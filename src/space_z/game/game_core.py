"""게임 규칙과 상태. pygame에 의존하지 않는다.

- step(action)을 한 번 부르면 정확히 1프레임(1/fps 초)이 진행된다.
- 전투와 카드 추첨은 별도 난수열을 사용하며, 같은 seed + 같은 행동/카드 선택 → 같은 결과.
- 보상은 여기서 계산하지 않고, 플레이어 관점의 이벤트만 self.events에 누적한다
  (rl/environment.py가 pop_events()로 꺼내서 보상으로 변환).
"""
from __future__ import annotations
from collections.abc import Sequence
from space_z.game.types import CombatEvents, ScoreAward, TilePosition, WorldPoint

import math

import numpy as np

from space_z.config import GameConfig, SHAPE_TYPES, SHAPE_KINDS
from space_z.game.terrain import TileMap, load_map, empty_map, generate_random_map, MUD
from space_z.game.actions import (
    MOVE_VECTORS,
    N_MOVES,
    N_ROTS,
    N_ACTIONS,
    ROT_DIR,
    encode_action,
    decode_action,
    move_from_vector,
    wrap_angle,
)
from space_z.game.entities import Tank, Shape, Bullet, Beam, Explosion
from space_z.game.player_progression import PlayerProgression
from space_z.game.combat import Combat
from space_z.game.enemy_controller import EnemyController


def empty_events() -> CombatEvents:
    """플레이어 관점의 전투 이벤트 누적용 딕셔너리를 새로 만든다.

    인자:
        없음.

    처리:
        피해·파괴·처치 수치는 0, 사망 여부는 False로 초기화한다.

    반환:
        dict: 천체 가중 피해·파괴 점수·파괴 수, 적 피해·처치 수, 피격 피해, 사망 여부를 담은 새 딕셔너리.
    """
    return {
        "shape_damage_weighted": 0.0,  # Σ 데미지 × (점수/최대체력)
        "shape_destroyed_score": 0.0,  # Σ 파괴한 도형 점수
        "shapes_destroyed": 0,
        "enemy_damage": 0.0,
        "enemies_killed": 0,
        "damage_taken": 0.0,
        "died": False,
    }


class GameCore:
    """공통 월드와 게임 한 프레임의 실행 순서를 관리한다."""

    # 읽는 순서: __init__() → reset() → step() → 각 담당 객체의 세부 규칙.
    def __init__(self, config: GameConfig | None = None, seed: int | None = None) -> None:
        """게임 설정을 검증하고 첫 게임 상태를 생성한다.

        인자:
            config: 게임 설정. None이면 기본 GameConfig를 사용한다.
            seed: 난수 시드. None이면 비결정적 난수열을 사용한다.

        처리:
            1) 월드 배율·경험치·탄약·재장전 시간·FPS 설정을 검증한다.
            2) reset(seed)을 호출해 지형과 개체를 포함한 게임 상태를 초기화한다.

        반환:
            None: 생성된 인스턴스에 설정과 초기 게임 상태를 저장한다.

        예외:
            ValueError: 월드 배율·경험치·탄약·재장전 시간·FPS가 허용 조건을 위반한 경우. 지형 생성 오류도 전달한다.
        """

        # 1) 월드 배율·경험치·탄약·재장전 시간·FPS 설정을 검증한다.
        self.config = config or GameConfig()  # 게임 규칙·지형·적 AI의 기본 설정
        if not isinstance(self.config.world_scale, int) or self.config.world_scale < 1:
            raise ValueError("world_scale은 1 이상의 정수여야 합니다.")
        if (
            not math.isfinite(self.config.world_area_scale)
            or self.config.world_area_scale <= 0
        ):
            raise ValueError("world_area_scale은 유한한 양수여야 합니다.")
        if self.config.level_xp_base <= 0 or self.config.level_xp_growth < 0:
            raise ValueError("레벨 경험치는 양수, 증가량은 0 이상이어야 합니다.")
        if not isinstance(self.config.player_ammo, int) or self.config.player_ammo < 0:
            raise ValueError("player_ammo는 0 이상의 정수여야 합니다.")
        if self.config.reload_seconds <= 0 or self.config.fps <= 0:
            raise ValueError("reload_seconds와 fps는 양수여야 합니다.")

        # 2) reset(seed)을 호출해 지형과 개체를 포함한 게임 상태를 초기화한다.
        self.progression = PlayerProgression(
            self
        )  # 점수·레벨·강화·진화 상태와 적용 규칙을 관리한다.
        self.combat = Combat(
            self
        )  # 무장·탄환·피해·회복·충돌과 전투 연출 상태를 관리한다.
        self.enemy_controller = EnemyController(
            self
        )  # 적의 재등장·능력치·성장·감지·추적·조준을 관리한다.
        self.reset(seed)

    # ---------------- 새 판의 상태 초기화 ----------------
    def reset(self, seed: int | None = None) -> None:
        """새 판을 시작할 수 있도록 게임 상태를 모두 초기화한다.

        인자:
            seed: 전투·맵 생성 난수열과 별도 보상 난수열에 사용할 시드.

        처리:
            1) 난수 생성기와 점수·성장·보상·타이머·이벤트·연출 목록을 초기화한다.
            2) 지형을 만들고 시작 위치에 플레이어를 생성한다.
            3) 설정된 수만큼 적과 천체를 생성한다.

        반환:
            None: 현재 인스턴스의 게임 상태를 새 판으로 교체한다.
        """

        # 1) 난수 생성기와 점수·성장·보상·타이머·이벤트·연출 목록을 초기화한다.
        self.rng = np.random.default_rng(
            seed
        )  # 맵 생성·전투·적 스탯 추첨에 쓰는 난수 생성기
        self.progression.reset(seed)
        self.frame = 0  # 이번 판에서 진행한 게임 프레임 수
        self.game_over = False  # 플레이어 사망으로 게임이 끝났는지 여부
        self._next_id = 0  # 선체·천체의 고유 번호 발급용 카운터
        self.events = (
            empty_events()
        )  # pop_events()로 꺼내기 전까지 누적하는 전투 이벤트
        self.score_award_events: list[ScoreAward] = []  # 전달 대기 중인 점수 획득 사실 (프레임, x, y, 점수, 대상 종류)
        self.combat.reset()
        self.shapes: list[Shape] = []  # 현재 월드에 남아 있는 천체 목록
        self.enemies: list[Tank] = []  # 적 목록 (생성 위치 계산에 이전 판의 적이 섞이지 않도록 먼저 비움)
        self.enemy_controller.reset()

        # 2) 지형을 만들고 시작 위치에 플레이어를 생성한다.
        config = self.config
        self.terrain = self._make_terrain()  # 이번 판의 타일 지형과 시작 위치 정보
        player_x, player_y = self.terrain.center(*self.terrain.player_start)
        self.player = Tank(  # 플레이어 선체의 위치·체력·무장·이동 상태
            id=self._new_id(),
            team="player",
            x=player_x,
            y=player_y,
            hp=config.player_hp,
            max_hp=config.player_hp,
            radius=config.tank_radius,
            fire_cooldown_max=config.player_fire_cooldown,
            ammo=config.player_ammo,
            max_ammo=config.player_ammo,
            angle=float(self.rng.uniform(-math.pi, math.pi)),
        )

        # 3) 설정된 수만큼 적과 천체를 생성한다.
        for _ in range(config.num_enemies):
            enemy = Tank(
                id=self._new_id(),
                team="enemy",
                x=0.0,
                y=0.0,
                hp=config.enemy_hp,
                max_hp=config.enemy_hp,
                radius=config.tank_radius,
                fire_cooldown_max=config.enemy_ai.fire_cooldown,
            )
            self.enemy_controller._respawn_enemy(enemy)
            self.enemies.append(enemy)
        for _ in range(config.num_shapes):
            self.shapes.append(self._make_shape())

    # ---------------- 한 프레임의 전체 진행 순서 ----------------
    def step(
        self,
        action: int,
        *,
        want_fire: bool = True,
        aim_position: WorldPoint | None=None,
        want_skill: bool = False,
        want_dash: bool = False,
    ) -> None:
        """행동과 선택 입력을 적용해 게임을 정확히 한 프레임 진행한다.

        인자:
            action: 이동·회전을 결합한 행동 번호(0~26).
            want_fire: 새 발사 묶음을 시작할지 여부. 이미 예약된 점사는 별도로 진행된다.
            aim_position: 조준할 월드 좌표(x, y). None이면 행동의 회전 입력만 사용한다.
            want_skill: 이전 호출 형식과의 호환용 인자. 현재는 사용하지 않는다.
            want_dash: 이전 호출 형식과의 호환용 인자. 현재는 사용하지 않는다.

        처리:
            1) 게임 종료 상태면 중단하고, 아니면 행동 해석·연출 수명·적 성장을 갱신한다.
            2) 플레이어 이동·조준과 살아 있는 적의 AI 또는 죽은 적의 재등장을 처리한다.
            3) 발사·천체 이동·탄환 이동·몸체 충돌·체력 회복을 처리한다.
            4) 천체 수를 보충하고 프레임·재장전 타이머·사망 상태를 갱신한다.

        반환:
            None: 게임 상태와 이벤트를 갱신한다. 전투 결과는 pop_events(),
                점수 획득 기록은 pop_score_award_events()로 각각 꺼낸다.

        예외:
            ValueError 또는 TypeError: 진행 중인 게임에서 행동의 정수 변환이나 범위 검사에 실패한 경우.
        """

        # 1) 게임 종료 상태면 중단하고, 아니면 행동 해석·연출 수명·적 성장을 갱신한다.
        if self.game_over:
            return
        move, rotation = decode_action(action)
        self.combat._tick_effects()
        self.enemy_controller._update_enemy_scaling()

        # 2) 플레이어 이동·조준과 살아 있는 적의 AI 또는 죽은 적의 재등장을 처리한다.
        self._move_player(move, rotation, aim_position)
        self._update_enemies()

        # 3) 발사·천체 이동·탄환 이동·몸체 충돌·체력 회복을 처리한다.
        self.combat._fire(self.player, want_fire)
        self._move_shapes()
        self.combat._move_bullets()
        self.combat._collide_bodies()
        self.combat._regen_player()

        # 도형 개수 유지
        # 4) 천체 수를 보충하고 프레임·재장전 타이머·사망 상태를 갱신한다.
        while len(self.shapes) < self.config.num_shapes:
            self.shapes.append(self._make_shape())

        self.frame += 1
        self.combat._finish_frame()
        if self.player.hp <= 0:
            self.player.hp = 0.0
            self.player.alive = False
            self.player.pending_shots.clear()
            self.game_over = True
            self.events["died"] = True

    # ---------------- 공통 월드·개체 생성과 위치 보정 ----------------
    def _new_id(self) -> int:
        """게임 개체에 사용할 다음 고유 번호를 발급한다.

        인자:
            없음(self는 현재 게임 상태를 참조한다).

        처리:
            내부 번호 카운터를 1 증가시켜 그 값을 사용한다.

        반환:
            int: 이번 판에서 새로 발급한 개체 번호.
        """
        self._next_id += 1
        return self._next_id

    def _make_terrain(self) -> TileMap:
        """설정에 맞는 전체 월드 지형을 생성하거나 맵 파일에서 불러온다.

        인자:
            없음(self는 현재 게임 상태를 참조한다).

        처리:
            1) 기준 가로·세로 길이가 타일 크기로 나누어떨어지는지 검사한다.
            2) 지형 비활성화·랜덤 맵·파일 맵 설정에 따라 지형을 선택한다. 맵 풀이 있으면 그중 하나를 추첨한다.

        반환:
            TileMap: 실제 월드 타일 수에 맞춘 지형.

        예외:
            ValueError: 기준 크기가 타일 크기로 나누어떨어지지 않는 경우. 맵 로딩·생성 오류도 전달한다.
        """

        # 1) 기준 가로·세로 길이가 타일 크기로 나누어떨어지는지 검사한다.
        config: GameConfig = self.config
        terrain_config = config.terrain
        cols, rows = (
            config.width // terrain_config.tile_size,
            config.height // terrain_config.tile_size,
        )
        if (
            cols * terrain_config.tile_size != config.width
            or rows * terrain_config.tile_size != config.height
        ):
            raise ValueError(
                f"화면 크기 {config.width}x{config.height}가 타일 크기 {terrain_config.tile_size}로 나누어떨어지지 않습니다."
            )

        # 2) 지형 비활성화·랜덤 맵·파일 맵 설정에 따라 지형을 선택한다. 맵 풀이 있으면 그중 하나를 추첨한다.
        if not terrain_config.enabled:
            return empty_map(terrain_config, config.world_cols, config.world_rows)
        if terrain_config.random_map:
            return generate_random_map(
                self.rng, terrain_config, config.world_cols, config.world_rows
            )
        name = terrain_config.map_name
        if terrain_config.map_pool:
            name = terrain_config.map_pool[
                int(self.rng.integers(len(terrain_config.map_pool)))
            ]
        return load_map(name, terrain_config, config.world_cols, config.world_rows)

    def _random_free_pos(self, radius: float, min_dist: float, tiles: Sequence[TilePosition] | None=None) -> WorldPoint:
        """원형 개체가 벽과 겹치지 않으면서 선체와 떨어진 생성 위치를 고른다.

        인자:
            radius: 생성할 개체의 충돌 반지름(player_x).
            min_dist: 살아 있는 선체 중심과 유지하려는 최소 거리(player_x).
            tiles: 후보 타일 좌표 목록. None이면 반지름에 맞는 이동 가능 타일을 사용한다.

        처리:
            1) 개체 전체가 들어갈 후보 타일을 준비하고 빈 목록인지 검사한다.
            2) 최대 80회 위치를 추첨해 선체와의 거리 조건을 확인한다.
            3) 조건을 만족하면 즉시 선택하고, 없으면 선체와의 여유가 가장 큰 후보를 선택한다.

        반환:
            tuple[float, float]: 선택한 월드 좌표(x, y). 공간이 부족하면 최소 거리 조건을 충족하지 못할 수 있다.

        예외:
            ValueError: 주어진 반지름의 개체가 들어갈 후보 타일이 없는 경우.
        """

        # 1) 개체 전체가 들어갈 후보 타일을 준비하고 빈 목록인지 검사한다.
        terrain = self.terrain
        if tiles is None:
            tiles = terrain.navigation_tiles(radius)
        else:
            tiles = tuple(
                tile
                for tile in tiles
                if terrain.circle_fits(*terrain.center(*tile), radius)
            )
        if not tiles:
            raise ValueError(f"반지름 {radius:g}의 개체가 들어갈 공간이 없습니다.")

        # 2) 최대 80회 위치를 추첨해 선체와의 거리 조건을 확인한다.
        tanks = [self.player] + [
            enemy for enemy in getattr(self, "enemies", []) if enemy.alive
        ]
        jitter = max(0.0, terrain.tile / 2 - radius)
        best = None
        for _ in range(80):
            col, row = tiles[int(self.rng.integers(len(tiles)))]
            center_x, center_y = terrain.center(col, row)
            x = center_x + float(self.rng.uniform(-jitter, jitter))
            y = center_y + float(self.rng.uniform(-jitter, jitter))
            if not terrain.circle_fits(x, y, radius):
                x, y = center_x, center_y
            clearance = min(
                (
                    math.hypot(tank.x - x, tank.y - y) - radius - tank.radius
                    for tank in tanks
                ),
                default=math.inf,
            )
            if best is None or clearance > best[0]:
                best = clearance, x, y
            if all(
                math.hypot(tank.x - x, tank.y - y)
                >= max(min_dist, radius + tank.radius)
                for tank in tanks
            ):
                return x, y

        # 3) 조건을 만족하면 즉시 선택하고, 없으면 선체와의 여유가 가장 큰 후보를 선택한다.
        assert best is not None  # 후보가 있으면 위의 80회 시도 중 적어도 한 번 저장한다.
        return best[1], best[2]

    def _fit_player_after_evolution(self) -> None:
        """진화 후 커진 플레이어 선체가 지형 안에 들어가도록 위치를 보정한다.

        인자:
            없음(self는 현재 게임 상태를 참조한다).

        처리:
            _fit_tank에 현재 플레이어를 전달해 벽 겹침을 해소한다.

        반환:
            None: 필요하면 플레이어 위치와 속도를 변경한다.
        """
        self._fit_tank(self.player)

    def _fit_tank(self, entity: Tank | Shape) -> None:
        """원형 개체가 벽과 겹치면 가장 가까운 이동 가능 타일로 옮긴다.

        인자:
            entity: x·y·radius·velocity_x·velocity_y 속성을 가진 선체 또는 천체.

        처리:
            1) 현재 위치에 개체가 들어가면 그대로 둔다.
            2) 겹친 경우 가장 가까운 유효 타일 중심으로 옮기고 속도를 0으로 만든다.

        반환:
            None: 전달받은 개체의 위치와 속도를 직접 보정한다.

        예외:
            ValueError: 개체 반지름에 맞는 이동 가능 타일이 없는 경우.
        """

        # 1) 현재 위치에 개체가 들어가면 그대로 둔다.
        terrain = self.terrain
        if terrain.circle_fits(entity.x, entity.y, entity.radius):
            return

        # 2) 겹친 경우 가장 가까운 유효 타일 중심으로 옮기고 속도를 0으로 만든다.
        candidates = terrain.navigation_tiles(entity.radius)
        if not candidates:
            raise ValueError("진화한 선체가 들어갈 공간이 없습니다.")
        col, row = min(
            candidates,
            key=lambda tile: (
                (terrain.center(*tile)[0] - entity.x) ** 2
                + (terrain.center(*tile)[1] - entity.y) ** 2
            ),
        )
        entity.x, entity.y = terrain.center(col, row)
        entity.velocity_x = entity.velocity_y = 0.0

    def _shape_spawn_pos(self, radius: float) -> WorldPoint:
        """여러 생성 후보를 비교해 천체가 덜 뭉치는 위치를 고른다.

        인자:
            radius: 새 천체의 충돌 반지름(player_x).

        처리:
            1) 반지름과 선체 최소 거리에 맞는 위치를 반복 추첨한다.
            2) 다른 천체와의 간격·플레이어와의 거리·벽 주위 여유로 후보를 평가한다.
            3) 충분한 유효 후보를 모으거나 시도 횟수를 소진하면 가장 높은 평가의 위치를 선택한다.

        반환:
            tuple[float, float]: 생성 월드 좌표(x, y). 공간이 부족하면 거리·여유 조건을 완화한 최선의 후보를 반환한다.
        """

        # 1) 반지름과 선체 최소 거리에 맞는 위치를 반복 추첨한다.
        config, player = self.config, self.player
        orbit_clearance = radius + 140.0
        best, valid_candidate_count = None, 0
        for _ in range(config.shape_spawn_candidates * 6):
            x, y = self._random_free_pos(radius, config.spawn_min_dist_from_tanks)

            # 2) 다른 천체와의 간격·플레이어와의 거리·벽 주위 여유로 후보를 평가한다.
            clearance = min(
                (
                    math.hypot(shape.x - x, shape.y - y) - shape.radius - radius
                    for shape in self.shapes
                ),
                default=math.inf,
            )
            far_from_player = (
                self.frame == 0
                or math.hypot(x - player.x, y - player.y)
                >= config.shape_respawn_dist_from_player
            )
            has_orbit_clearance = self.terrain.circle_fits(x, y, orbit_clearance)
            valid_position = (
                far_from_player
                and clearance >= config.shape_spawn_gap
                and has_orbit_clearance
            )
            valid_candidate_count += valid_position
            # 우선순위: 조건 모두 만족 > 겹치지 않음 > 플레이어와 멂 > 벽에서 여유 있음 > 다른 천체와 멂
            score = (
                valid_position,
                clearance >= 0,
                far_from_player,
                has_orbit_clearance,
                clearance,
            )
            if best is None or score > best[0]:
                best = score, x, y
            if valid_candidate_count >= config.shape_spawn_candidates:
                break

        # 3) 충분한 유효 후보를 모으거나 시도 횟수를 소진하면 가장 높은 평가의 위치를 선택한다.
        assert best is not None
        return best[1], best[2]

    def _make_shape(self) -> Shape:
        """종류와 표류 상태를 추첨해 새 천체를 만든다.

        인자:
            없음(self는 현재 게임 상태를 참조한다).

        처리:
            1) 종류별 상대 가중치로 천체 종류와 생성 위치를 선택한다.
            2) 표류 방향·속도·회전 상태를 추첨하고 종류별 능력치로 개체를 구성한다.

        반환:
            Shape: 아직 self.shapes에 추가하지 않은 새 천체.
        """

        # 1) 종류별 상대 가중치로 천체 종류와 생성 위치를 선택한다.
        config = self.config
        weights = np.array(
            [SHAPE_TYPES[shape_kind]["weight"] for shape_kind in SHAPE_KINDS]
        )
        kind = SHAPE_KINDS[
            int(self.rng.choice(len(SHAPE_KINDS), p=weights / weights.sum()))
        ]
        shape_stats = SHAPE_TYPES[kind]
        spawn_x, spawn_y = self._shape_spawn_pos(shape_stats["radius"])

        # 천체가 표류할 방향과 속력을 무작위로 정한다.
        drift_angle_radians = float(self.rng.uniform(-math.pi, math.pi))
        drift_speed = float(self.rng.uniform(0, config.shape_drift))

        # 표류 방향과 속력을 가로·세로 속도로 변환한다.
        velocity_x = math.cos(drift_angle_radians) * drift_speed
        velocity_y = math.sin(drift_angle_radians) * drift_speed

        # 위치·이동·능력치·회전 상태를 담아 새 천체를 만든다.
        return Shape(
            id=self._new_id(),
            kind=kind,
            x=spawn_x,
            y=spawn_y,
            velocity_x=velocity_x,
            velocity_y=velocity_y,
            hp=shape_stats["hp"],
            max_hp=shape_stats["hp"],
            radius=shape_stats["radius"],
            score=shape_stats["score"],
            angle=float(self.rng.uniform(0, 2 * math.pi)),
            spin=float(self.rng.uniform(-0.01, 0.01)),
        )

    def record_score_award(self, x: float, y: float, amount: int, kind: str) -> None:
        """점수를 획득한 시점과 위치를 기록한다. 실제 점수나 화면 상태는 바꾸지 않는다.

        인자:
            x, y: 획득 위치의 월드 좌표(player_x).
            amount: 획득한 점수.
            kind: 점수 출처(enemy, elite 또는 천체 종류 키).

        처리:
            현재 게임 프레임과 인자를 전달 대기 목록에 추가한다.

        반환:
            None: score_award_events만 변경한다.
        """
        self.score_award_events.append((self.frame, x, y, amount, kind))

    def pop_score_award_events(self) -> list[ScoreAward]:
        """전달 대기 중인 점수 획득 이벤트를 꺼내고 코어의 목록을 비운다.

        인자:
            없음.

        처리:
            1) 현재 이벤트 목록을 보관한다.
            2) 다음 기록을 받을 새 빈 목록으로 교체한다.

        반환:
            list: (게임 프레임, 월드 x, 월드 y, 획득 점수, 대상 종류) 목록.
                호출자는 렌더러에 전달하거나 화면이 없으면 소비하고 버린다.
                학습 보상용 pop_events()와는 별도로 소비한다.
        """

        # 1) 현재 이벤트 목록을 보관한다.
        events = self.score_award_events

        # 2) 다음 기록을 받을 새 빈 목록으로 교체한다.
        self.score_award_events = []
        return events

    def pop_events(self) -> CombatEvents:
        """누적된 전투 이벤트를 꺼내고 다음 누적용 저장소를 비운다.

        인자:
            없음(self는 현재 게임 상태를 참조한다).

        처리:
            1) 현재 이벤트 딕셔너리를 보관한다.
            2) 새 빈 이벤트 딕셔너리로 교체한다.

        반환:
            dict: 교체 전 누적 이벤트. 복사본이 아니라 기존 딕셔너리 자체를 반환한다.
        """

        # 1) 현재 이벤트 딕셔너리를 보관한다.
        events = self.events

        # 2) 새 빈 이벤트 딕셔너리로 교체한다.
        self.events = empty_events()
        return events

    def _apply_tank_control(
        self,
        tank: Tank,
        move: int,
        rotation: int,
        accel_scale: float,
        turn_scale: float,
    ) -> None:
        """선체의 이동·벽 충돌·포신 회전을 한 프레임 처리한다.

        인자:
            tank: 제어할 Tank.
            move: 이동 번호(0~8).
            rotation: 회전 번호(0=유지, 1=반시계, 2=시계).
            accel_scale: 기본 이동 가속도에 적용할 배율.
            turn_scale: 기본 포신 회전 속도에 적용할 배율.

        처리:
            1) 중력장 감속과 마찰·방향 가속도를 적용해 속도를 갱신한다.
            2) 이동을 짧은 구간으로 나눠 벽 충돌과 월드 경계를 보정한다.
            3) 회전 입력을 적용하고 포신 각도를 표준 범위로 감싼다.

        반환:
            None: 전달받은 선체의 위치·속도·각도를 직접 변경한다.
        """

        # 1) 중력장 감속과 마찰·방향 가속도를 적용해 속도를 갱신한다.
        config = self.config
        if self.terrain.tile_at(tank.x, tank.y) == MUD:
            accel_scale *= config.terrain.mud_accel_scale
        move_x, move_y = MOVE_VECTORS[move]
        tank.velocity_x = (
            tank.velocity_x * config.friction + move_x * config.accel * accel_scale
        )
        tank.velocity_y = (
            tank.velocity_y * config.friction + move_y * config.accel * accel_scale
        )
        # 대시와 누적 속도 강화도 얇은 벽을 건너뛰지 않도록 나눠 이동한다.
        # 2) 이동을 짧은 구간으로 나눠 벽 충돌과 월드 경계를 보정한다.
        substep_count = max(
            1,
            math.ceil(
                math.hypot(tank.velocity_x, tank.velocity_y) / max(1, tank.radius * 0.5)
            ),
        )
        for _ in range(substep_count):
            tank.x += tank.velocity_x / substep_count
            tank.y += tank.velocity_y / substep_count
            self.terrain.resolve_circle(tank)
            self._clamp_to_arena(tank)

        # 3) 회전 입력을 적용하고 포신 각도를 표준 범위로 감싼다.
        tank.angle = wrap_angle(
            tank.angle + ROT_DIR[rotation] * config.turn_speed * turn_scale
        )

    def _clamp_to_arena(self, entity: Tank | Shape) -> None:
        """원형 개체가 월드 경계를 벗어나지 않도록 위치와 속도를 보정한다.

        인자:
            entity: x·y·radius·velocity_x·velocity_y 속성을 가진 선체 또는 천체.

        처리:
            1) 가로 경계를 벗어나면 위치를 경계 안으로 옮기고 바깥 방향 속도를 제거한다.
            2) 세로 경계에도 같은 보정을 적용한다.

        반환:
            None: 전달받은 개체의 위치와 속도를 직접 변경한다.
        """
        config = self.config
        radius = entity.radius

        # 1) 가로 경계를 벗어나면 위치를 경계 안으로 옮기고 바깥 방향 속도를 제거한다.
        if entity.x < radius:
            entity.x, entity.velocity_x = radius, max(0.0, entity.velocity_x)
        elif entity.x > config.world_width - radius:
            entity.x, entity.velocity_x = (
                config.world_width - radius,
                min(0.0, entity.velocity_x),
            )

        # 2) 세로 경계에도 같은 보정을 적용한다.
        if entity.y < radius:
            entity.y, entity.velocity_y = radius, max(0.0, entity.velocity_y)
        elif entity.y > config.world_height - radius:
            entity.y, entity.velocity_y = (
                config.world_height - radius,
                min(0.0, entity.velocity_y),
            )

    def _move_shapes(self) -> None:
        """모든 천체의 표류·회전·벽 반사·속도 감쇠를 처리한다.

        인자:
            없음(self는 현재 게임 상태를 참조한다).

        처리:
            1) 속도와 회전량으로 천체 위치·각도를 갱신한다.
            2) 월드 경계와 지형 충돌을 보정하고 반사시킨다.
            3) 표류 상한보다 빠르면 충돌로 얻은 속도를 서서히 줄인다.

        반환:
            None: 각 천체의 위치·각도·속도를 직접 변경한다.
        """
        config = self.config
        for shape in self.shapes:
            # 1) 속도와 회전량으로 천체 위치·각도를 갱신한다.
            shape.x += shape.velocity_x
            shape.y += shape.velocity_y
            shape.angle += shape.spin

            # 2) 월드 경계와 지형 충돌을 보정하고 반사시킨다.
            if shape.x < shape.radius or shape.x > config.world_width - shape.radius:
                shape.velocity_x = -shape.velocity_x
            if shape.y < shape.radius or shape.y > config.world_height - shape.radius:
                shape.velocity_y = -shape.velocity_y
            self.terrain.resolve_circle(shape, bounce=True)
            self._clamp_to_arena(shape)
            # 밀려난 속도는 서서히 표류 속도로 감쇠
            # 3) 표류 상한보다 빠르면 충돌로 얻은 속도를 서서히 줄인다.
            speed = math.hypot(shape.velocity_x, shape.velocity_y)
            if speed > config.shape_drift:
                shape.velocity_x *= 0.95
                shape.velocity_y *= 0.95

    def _move_player(
        self,
        move: int,
        rotation: int,
        aim_position: tuple[float, float] | None = None,
    ) -> None:
        """플레이어의 한 프레임 이동과 목표 좌표 조준을 처리한다.

        인자:
            move: 정지 또는 8방향 이동 번호(0~8). step()에서 해석한 값을 전달한다.
            rotation: 회전 번호(0=유지, 1=반시계, 2=시계).
            aim_position: 조준할 월드 좌표 (x, y), 단위는 px. None이면 회전 입력만 사용한다.

        처리:
            1) 목표 좌표가 있으면 이동 전 위치에서 목표를 향하도록 각도를 맞춘다.
            2) 플레이어의 가속도 배율로 이동·충돌 보정·회전 입력을 적용한다.
            3) 이동 뒤 위치를 기준으로 다시 조준한다. 목표와 거의 같은 위치이면 재조준을 생략한다.

        반환:
            None: 플레이어의 위치·속도·각도를 변경한다. 발사와 게임 프레임 증가는 step()에서 처리한다.
        """
        # 이동 전 조준 방향을 정하고 공통 선체 제어에 이동·회전 입력을 전달한다.
        if aim_position is not None:
            self.player.angle = math.atan2(
                aim_position[1] - self.player.y, aim_position[0] - self.player.x
            )
        self._apply_tank_control(
            self.player, move, rotation, self.player.accel_scale, 1.0
        )

        # 이동으로 달라진 위치에서도 같은 월드 지점을 향하도록 조준을 보정한다.
        if aim_position is not None:
            delta_x, delta_y = (
                aim_position[0] - self.player.x,
                aim_position[1] - self.player.y,
            )
            if delta_x * delta_x + delta_y * delta_y > 1e-6:
                self.player.angle = math.atan2(delta_y, delta_x)

    def _update_enemies(self) -> None:
        """살아 있는 적의 행동과 죽은 적의 재등장 대기를 한 프레임 처리한다.

        인자:
            없음. 현재 적 목록과 EnemyController를 사용한다.

        처리:
            적 목록 순서대로 살아 있는 적은 감지·추적·조준·발사 AI를 실행한다.
            죽은 적은 재등장 타이머를 1 줄이고 0 이하가 되면 재등장시킨다.
            이번 호출에서 재등장한 적의 AI는 다음 프레임부터 실행한다.

        반환:
            None: 적의 AI·이동·발사 또는 재등장 상태를 변경한다.
            적 성장 갱신과 게임 프레임 증가는 step()에서 별도로 처리한다.
        """
        for enemy in self.enemies:
            # 살아 있는 적의 현재 프레임 행동은 적 AI 담당 객체에 맡긴다.
            if enemy.alive:
                self.enemy_controller._enemy_ai(enemy)
            else:
                # 대기 시간이 끝난 적을 재등장시키고 이번 프레임에는 AI를 추가 실행하지 않는다.
                enemy.respawn_timer -= 1
                if enemy.respawn_timer <= 0:
                    self.enemy_controller._respawn_enemy(enemy)
