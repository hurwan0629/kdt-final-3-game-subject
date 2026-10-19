"""게임 규칙과 상태. pygame에 의존하지 않는다.

- step(action)을 한 번 부르면 정확히 1프레임(1/fps 초)이 진행된다.
- 전투와 카드 추첨은 별도 난수열을 사용하며, 같은 seed + 같은 행동/카드 선택 → 같은 결과.
- 보상은 여기서 계산하지 않고, 플레이어 관점의 이벤트만 self.events에 누적한다
  (env.py가 pop_events()로 꺼내서 보상으로 변환).
"""
import math

import numpy as np

from config import GameConfig, SHAPE_TYPES, SHAPE_KINDS
from terrain import TileMap, load_map, empty_map, generate_random_map, MUD
from gameplay.actions import (MOVE_VECTORS, N_MOVES, N_ROTS, N_ACTIONS, ROT_DIR,
                              encode_action, decode_action, move_from_vector, wrap_angle)
from gameplay.entities import Tank, Shape, Bullet, Beam, Explosion
from gameplay.progression import Progression
from gameplay.combat import Combat
from gameplay.enemies import EnemyController


def empty_events():
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
    def __init__(self, config: GameConfig = None, seed: int = None):
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
        self.cfg = config or GameConfig()  # 게임 규칙·지형·적 AI의 기본 설정
        if not isinstance(self.cfg.world_scale, int) or self.cfg.world_scale < 1:
            raise ValueError("world_scale은 1 이상의 정수여야 합니다.")
        if not math.isfinite(self.cfg.world_area_scale) or self.cfg.world_area_scale <= 0:
            raise ValueError("world_area_scale은 유한한 양수여야 합니다.")
        if self.cfg.level_xp_base <= 0 or self.cfg.level_xp_growth < 0:
            raise ValueError("레벨 경험치는 양수, 증가량은 0 이상이어야 합니다.")
        if not isinstance(self.cfg.player_ammo, int) or self.cfg.player_ammo < 0:
            raise ValueError("player_ammo는 0 이상의 정수여야 합니다.")
        if self.cfg.reload_seconds <= 0 or self.cfg.fps <= 0:
            raise ValueError("reload_seconds와 fps는 양수여야 합니다.")
        # 2) reset(seed)을 호출해 지형과 개체를 포함한 게임 상태를 초기화한다.
        self.progression = Progression(self)  # 점수·레벨·강화·진화 상태와 적용 규칙을 관리한다.
        self.combat = Combat(self)  # 무장·탄환·피해·회복·충돌과 전투 연출 상태를 관리한다.
        self.enemy_controller = EnemyController(self)  # 적의 재등장·능력치·성장·감지·추적·조준을 관리한다.
        self.reset(seed)

    # ---------------- 새 판의 상태 초기화 ----------------
    def reset(self, seed: int = None):
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
        self.rng = np.random.default_rng(seed)  # 맵 생성·전투·적 스탯 추첨에 쓰는 난수 생성기
        self.progression.reset(seed)
        self.frame = 0  # 이번 판에서 진행한 게임 프레임 수
        self.game_over = False  # 플레이어 사망으로 게임이 끝났는지 여부
        self._next_id = 0  # 선체·천체의 고유 번호 발급용 카운터
        self.events = empty_events()  # pop_events()로 꺼내기 전까지 누적하는 전투 이벤트
        self.combat.reset()
        self.shapes = []  # 현재 월드에 남아 있는 천체 목록
        self.enemies = []  # 적 목록 (생성 위치 계산에 이전 판의 적이 섞이지 않도록 먼저 비움)
        self.enemy_controller.reset()

        # 2) 지형을 만들고 시작 위치에 플레이어를 생성한다.
        c = self.cfg
        self.terrain = self._make_terrain()  # 이번 판의 타일 지형과 시작 위치 정보
        px, py = self.terrain.center(*self.terrain.player_start)
        self.player = Tank(  # 플레이어 선체의 위치·체력·무장·이동 상태
            id=self._new_id(), team="player", x=px, y=py,
            hp=c.player_hp, max_hp=c.player_hp, radius=c.tank_radius,
            fire_cooldown_max=c.player_fire_cooldown,
            ammo=c.player_ammo, max_ammo=c.player_ammo,
            angle=float(self.rng.uniform(-math.pi, math.pi)),
        )
        # 3) 설정된 수만큼 적과 천체를 생성한다.
        for _ in range(c.num_enemies):
            e = Tank(id=self._new_id(), team="enemy", x=0.0, y=0.0,
                     hp=c.enemy_hp, max_hp=c.enemy_hp, radius=c.tank_radius,
                     fire_cooldown_max=c.enemy_ai.fire_cooldown)
            self.enemy_controller._respawn_enemy(e)
            self.enemies.append(e)
        for _ in range(c.num_shapes):
            self.shapes.append(self._make_shape())

    # ---------------- 한 프레임의 전체 진행 순서 ----------------
    def step(self, action: int, *, want_fire: bool = True, aim_position=None,
             want_skill: bool = False, want_dash: bool = False):
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
            4) 천체 수를 보충하고 프레임·점수 연출·재장전 타이머·사망 상태를 갱신한다.

        반환:
            None: 게임 상태와 전투 이벤트를 갱신한다. 이벤트는 pop_events()로 별도 조회한다.

        예외:
            ValueError 또는 TypeError: 진행 중인 게임에서 행동의 정수 변환이나 범위 검사에 실패한 경우.
        """
        # 1) 게임 종료 상태면 중단하고, 아니면 행동 해석·연출 수명·적 성장을 갱신한다.
        if self.game_over:
            return
        move, rot = decode_action(action)
        self.combat._tick_effects()
        self.enemy_controller._update_enemy_scaling()
        # 2) 플레이어 이동·조준과 살아 있는 적의 AI 또는 죽은 적의 재등장을 처리한다.
        if aim_position is not None:
            self.player.angle = math.atan2(aim_position[1] - self.player.y, aim_position[0] - self.player.x)
        self._apply_tank_control(self.player, move, rot, self.player.accel_scale, 1.0)
        if aim_position is not None:
            dx, dy = aim_position[0] - self.player.x, aim_position[1] - self.player.y
            if dx * dx + dy * dy > 1e-6:
                self.player.angle = math.atan2(dy, dx)

        for e in self.enemies:
            if e.alive:
                self.enemy_controller._enemy_ai(e)
            else:
                e.respawn_timer -= 1
                if e.respawn_timer <= 0:
                    self.enemy_controller._respawn_enemy(e)

        # 3) 발사·천체 이동·탄환 이동·몸체 충돌·체력 회복을 처리한다.
        self.combat._fire(self.player, want_fire)
        self._move_shapes()
        self.combat._move_bullets()
        self.combat._collide_bodies()
        self.combat._regen_player()

        # 도형 개수 유지
        # 4) 천체 수를 보충하고 프레임·점수 연출·재장전 타이머·사망 상태를 갱신한다.
        while len(self.shapes) < self.cfg.num_shapes:
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
        c = self.cfg
        tc = c.terrain
        cols, rows = c.width // tc.tile_size, c.height // tc.tile_size
        if cols * tc.tile_size != c.width or rows * tc.tile_size != c.height:
            raise ValueError(f"화면 크기 {c.width}x{c.height}가 타일 크기 {tc.tile_size}로 나누어떨어지지 않습니다.")
        # 2) 지형 비활성화·랜덤 맵·파일 맵 설정에 따라 지형을 선택한다. 맵 풀이 있으면 그중 하나를 추첨한다.
        if not tc.enabled:
            return empty_map(tc, c.world_cols, c.world_rows)
        if tc.random_map:
            return generate_random_map(self.rng, tc, c.world_cols, c.world_rows)
        name = tc.map_name
        if tc.map_pool:
            name = tc.map_pool[int(self.rng.integers(len(tc.map_pool)))]
        return load_map(name, tc, c.world_cols, c.world_rows)

    def _random_free_pos(self, radius: float, min_dist: float, tiles=None):
        """원형 개체가 벽과 겹치지 않으면서 선체와 떨어진 생성 위치를 고른다.

        인자:
            radius: 생성할 개체의 충돌 반지름(px).
            min_dist: 살아 있는 선체 중심과 유지하려는 최소 거리(px).
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
        tm = self.terrain
        if tiles is None:
            tiles = tm.navigation_tiles(radius)
        else:
            tiles = tuple(tile for tile in tiles if tm.circle_fits(*tm.center(*tile), radius))
        if not tiles:
            raise ValueError(f"반지름 {radius:g}의 개체가 들어갈 공간이 없습니다.")
        # 2) 최대 80회 위치를 추첨해 선체와의 거리 조건을 확인한다.
        tanks = [self.player] + [e for e in getattr(self, "enemies", []) if e.alive]
        jitter = max(0.0, tm.tile / 2 - radius)
        best = None
        for _ in range(80):
            col, row = tiles[int(self.rng.integers(len(tiles)))]
            cx, cy = tm.center(col, row)
            x = cx + float(self.rng.uniform(-jitter, jitter))
            y = cy + float(self.rng.uniform(-jitter, jitter))
            if not tm.circle_fits(x, y, radius):
                x, y = cx, cy
            clearance = min((math.hypot(t.x - x, t.y - y) - radius - t.radius for t in tanks), default=math.inf)
            if best is None or clearance > best[0]:
                best = clearance, x, y
            if all(math.hypot(t.x - x, t.y - y) >= max(min_dist, radius + t.radius) for t in tanks):
                return x, y
        # 3) 조건을 만족하면 즉시 선택하고, 없으면 선체와의 여유가 가장 큰 후보를 선택한다.
        return best[1], best[2]

    def _fit_player_after_evolution(self):
        """진화 후 커진 플레이어 선체가 지형 안에 들어가도록 위치를 보정한다.

        인자:
            없음(self는 현재 게임 상태를 참조한다).

        처리:
            _fit_tank에 현재 플레이어를 전달해 벽 겹침을 해소한다.

        반환:
            None: 필요하면 플레이어 위치와 속도를 변경한다.
        """
        self._fit_tank(self.player)

    def _fit_tank(self, p):
        """원형 개체가 벽과 겹치면 가장 가까운 이동 가능 타일로 옮긴다.

        인자:
            p: x·y·radius·vx·vy 속성을 가진 선체 또는 천체.

        처리:
            1) 현재 위치에 개체가 들어가면 그대로 둔다.
            2) 겹친 경우 가장 가까운 유효 타일 중심으로 옮기고 속도를 0으로 만든다.

        반환:
            None: 전달받은 개체의 위치와 속도를 직접 보정한다.

        예외:
            ValueError: 개체 반지름에 맞는 이동 가능 타일이 없는 경우.
        """
        # 1) 현재 위치에 개체가 들어가면 그대로 둔다.
        tm = self.terrain
        if tm.circle_fits(p.x, p.y, p.radius):
            return
        # 2) 겹친 경우 가장 가까운 유효 타일 중심으로 옮기고 속도를 0으로 만든다.
        candidates = tm.navigation_tiles(p.radius)
        if not candidates:
            raise ValueError("진화한 선체가 들어갈 공간이 없습니다.")
        col, row = min(candidates, key=lambda tile: (tm.center(*tile)[0] - p.x) ** 2 + (tm.center(*tile)[1] - p.y) ** 2)
        p.x, p.y = tm.center(col, row)
        p.vx = p.vy = 0.0

    def _shape_spawn_pos(self, radius):
        """여러 생성 후보를 비교해 천체가 덜 뭉치는 위치를 고른다.

        인자:
            radius: 새 천체의 충돌 반지름(px).

        처리:
            1) 반지름과 선체 최소 거리에 맞는 위치를 반복 추첨한다.
            2) 다른 천체와의 간격·플레이어와의 거리·벽 주위 여유로 후보를 평가한다.
            3) 충분한 유효 후보를 모으거나 시도 횟수를 소진하면 가장 높은 평가의 위치를 선택한다.

        반환:
            tuple[float, float]: 생성 월드 좌표(x, y). 공간이 부족하면 거리·여유 조건을 완화한 최선의 후보를 반환한다.
        """
        # 1) 반지름과 선체 최소 거리에 맞는 위치를 반복 추첨한다.
        c, p = self.cfg, self.player
        orbit_clearance = radius + 140.0
        best, valid = None, 0
        for _ in range(c.shape_spawn_candidates * 6):
            x, y = self._random_free_pos(radius, c.spawn_min_dist_from_tanks)
            # 2) 다른 천체와의 간격·플레이어와의 거리·벽 주위 여유로 후보를 평가한다.
            clearance = min((math.hypot(s.x - x, s.y - y) - s.radius - radius for s in self.shapes), default=math.inf)
            far = self.frame == 0 or math.hypot(x - p.x, y - p.y) >= c.shape_respawn_dist_from_player
            roomy = self.terrain.circle_fits(x, y, orbit_clearance)
            ok = far and clearance >= c.shape_spawn_gap and roomy
            valid += ok
            # 우선순위: 조건 모두 만족 > 겹치지 않음 > 플레이어와 멂 > 벽에서 여유 있음 > 다른 천체와 멂
            score = (ok, clearance >= 0, far, roomy, clearance)
            if best is None or score > best[0]:
                best = score, x, y
            if valid >= c.shape_spawn_candidates:
                break
        # 3) 충분한 유효 후보를 모으거나 시도 횟수를 소진하면 가장 높은 평가의 위치를 선택한다.
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
        c = self.cfg
        weights = np.array([SHAPE_TYPES[k]["weight"] for k in SHAPE_KINDS])
        kind = SHAPE_KINDS[int(self.rng.choice(len(SHAPE_KINDS), p=weights / weights.sum()))]
        t = SHAPE_TYPES[kind]
        x, y = self._shape_spawn_pos(t["radius"])
        # 2) 표류 방향·속도·회전 상태를 추첨하고 종류별 능력치로 개체를 구성한다.
        ang = float(self.rng.uniform(-math.pi, math.pi))
        spd = float(self.rng.uniform(0, c.shape_drift))
        return Shape(id=self._new_id(), kind=kind, x=x, y=y,
                     vx=math.cos(ang) * spd, vy=math.sin(ang) * spd,
                     hp=t["hp"], max_hp=t["hp"], radius=t["radius"], score=t["score"],
                     angle=float(self.rng.uniform(0, 2 * math.pi)),
                     spin=float(self.rng.uniform(-0.01, 0.01)))

    def pop_events(self) -> dict:
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
        ev = self.events
        # 2) 새 빈 이벤트 딕셔너리로 교체한다.
        self.events = empty_events()
        return ev

    def _apply_tank_control(self, t: Tank, move: int, rot: int, accel_scale: float, turn_scale: float):
        """선체의 이동·벽 충돌·포신 회전을 한 프레임 처리한다.

        인자:
            t: 제어할 Tank.
            move: 이동 번호(0~8).
            rot: 회전 번호(0=유지, 1=반시계, 2=시계).
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
        c = self.cfg
        if self.terrain.tile_at(t.x, t.y) == MUD:
            accel_scale *= c.terrain.mud_accel_scale
        mx, my = MOVE_VECTORS[move]
        t.vx = t.vx * c.friction + mx * c.accel * accel_scale
        t.vy = t.vy * c.friction + my * c.accel * accel_scale
        # 대시와 누적 속도 강화도 얇은 벽을 건너뛰지 않도록 나눠 이동한다.
        # 2) 이동을 짧은 구간으로 나눠 벽 충돌과 월드 경계를 보정한다.
        count = max(1, math.ceil(math.hypot(t.vx, t.vy) / max(1, t.radius * 0.5)))
        for _ in range(count):
            t.x += t.vx / count
            t.y += t.vy / count
            self.terrain.resolve_circle(t)
            self._clamp_to_arena(t)
        # 3) 회전 입력을 적용하고 포신 각도를 표준 범위로 감싼다.
        t.angle = wrap_angle(t.angle + ROT_DIR[rot] * c.turn_speed * turn_scale)

    def _clamp_to_arena(self, obj):
        """원형 개체가 월드 경계를 벗어나지 않도록 위치와 속도를 보정한다.

        인자:
            obj: x·y·radius·vx·vy 속성을 가진 선체 또는 천체.

        처리:
            1) 가로 경계를 벗어나면 위치를 경계 안으로 옮기고 바깥 방향 속도를 제거한다.
            2) 세로 경계에도 같은 보정을 적용한다.

        반환:
            None: 전달받은 개체의 위치와 속도를 직접 변경한다.
        """
        c = self.cfg
        r = obj.radius
        # 1) 가로 경계를 벗어나면 위치를 경계 안으로 옮기고 바깥 방향 속도를 제거한다.
        if obj.x < r:
            obj.x, obj.vx = r, max(0.0, obj.vx)
        elif obj.x > c.world_width - r:
            obj.x, obj.vx = c.world_width - r, min(0.0, obj.vx)
        # 2) 세로 경계에도 같은 보정을 적용한다.
        if obj.y < r:
            obj.y, obj.vy = r, max(0.0, obj.vy)
        elif obj.y > c.world_height - r:
            obj.y, obj.vy = c.world_height - r, min(0.0, obj.vy)

    def _move_shapes(self):
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
        c = self.cfg
        for s in self.shapes:
            # 1) 속도와 회전량으로 천체 위치·각도를 갱신한다.
            s.x += s.vx
            s.y += s.vy
            s.angle += s.spin
            # 2) 월드 경계와 지형 충돌을 보정하고 반사시킨다.
            if s.x < s.radius or s.x > c.world_width - s.radius:
                s.vx = -s.vx
            if s.y < s.radius or s.y > c.world_height - s.radius:
                s.vy = -s.vy
            self.terrain.resolve_circle(s, bounce=True)
            self._clamp_to_arena(s)
            # 밀려난 속도는 서서히 표류 속도로 감쇠
            # 3) 표류 상한보다 빠르면 충돌로 얻은 속도를 서서히 줄인다.
            spd = math.hypot(s.vx, s.vy)
            if spd > c.shape_drift:
                s.vx *= 0.95
                s.vy *= 0.95
