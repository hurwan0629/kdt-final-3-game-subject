"""게임 규칙과 상태. pygame에 의존하지 않는다.

- step(action)을 한 번 부르면 정확히 1프레임(1/fps 초)이 진행된다.
- 전투와 카드 추첨은 별도 난수열을 사용하며, 같은 seed + 같은 행동/카드 선택 → 같은 결과.
- 보상은 여기서 계산하지 않고, 플레이어 관점의 이벤트만 self.events에 누적한다
  (env.py가 pop_events()로 꺼내서 보상으로 변환).
"""
import math
from dataclasses import dataclass, field

import numpy as np

from config import GameConfig, SHAPE_TYPES, SHAPE_KINDS
from terrain import TileMap, load_map, empty_map, generate_random_map, MUD, BREAKABLE
from progression import STAT_UPGRADES, STAT_MAX_LEVEL, SHIPS, SHIPS_BY_LEVEL, FAMILIES

# --------------------------------------------------------------------------
# 행동 정의: 이동 9 × 회전 3 = 27
# --------------------------------------------------------------------------
# move: 0=정지, 1=↑, 2=↗, 3=→, 4=↘, 5=↓, 6=↙, 7=←, 8=↖   (화면 좌표: y가 아래로 증가)
_S = 1.0 / math.sqrt(2.0)
MOVE_VECTORS = [
    (0.0, 0.0), (0.0, -1.0), (_S, -_S), (1.0, 0.0), (_S, _S),
    (0.0, 1.0), (-_S, _S), (-1.0, 0.0), (-_S, -_S),
]
N_MOVES = 9
N_ROTS = 3          # 0=유지, 1=왼쪽(반시계), 2=오른쪽(시계)
N_ACTIONS = N_MOVES * N_ROTS
ROT_DIR = (0.0, -1.0, 1.0)

# 스나이퍼 계열(단발 장거리): 포탄 그림을 쓰고, 다수 상대 약점을 보완하는 관통을 1회 받는다.
SNIPER_LINE_JOBS = ("sniper", "railgunner", "hyper_railgun", "hunter", "predator")
SNIPER_PIERCE = 1


def encode_action(move: int, rot: int) -> int:
    """이동 번호와 회전 번호를 하나의 행동 번호로 인코딩한다.

    인자:
        move: 이동 번호(0=정지, 1~8=8방향).
        rot: 회전 번호(0=유지, 1=반시계, 2=시계).

    처리:
        이동 번호에 회전 경우의 수를 곱하고 회전 번호를 더한다. 입력 범위는 검사하지 않는다.

    반환:
        int: 결합된 행동 번호. 유효한 입력이면 0~26이다.
    """
    return move * N_ROTS + rot


def decode_action(action: int):
    """행동 번호를 검증하고 이동 번호와 회전 번호로 분리한다.

    인자:
        action: 정수로 변환 가능한 행동 번호(0~26).

    처리:
        1) 입력을 정수로 변환하고 행동 범위를 검사한다.
        2) 나눗셈의 몫과 나머지로 이동·회전 번호를 분리한다.

    반환:
        tuple[int, int]: (이동 번호, 회전 번호).

    예외:
        ValueError: 정수 변환 실패 또는 행동 범위(0~26) 위반.
        TypeError: 정수로 변환할 수 없는 자료형을 받은 경우.
    """
    # 1) 입력을 정수로 변환하고 행동 범위를 검사한다.
    action = int(action)
    if not 0 <= action < N_ACTIONS:
        raise ValueError(f"action must be in [0, {N_ACTIONS}), got {action}")
    # 2) 나눗셈의 몫과 나머지로 이동·회전 번호를 분리한다.
    return divmod(action, N_ROTS)


def move_from_vector(dx: float, dy: float) -> int:
    """방향 벡터를 정지 또는 가장 가까운 8방향 이동 번호로 바꾼다.

    인자:
        dx: 가로 방향 성분(오른쪽이 양수).
        dy: 세로 방향 성분(아래쪽이 양수).

    처리:
        1) 벡터 길이가 거의 0이면 정지로 처리한다.
        2) 벡터 각도를 45도 간격으로 양자화해 이동 번호로 변환한다.

    반환:
        int: 정지는 0, 이동 방향은 1~8.
    """
    # 1) 벡터 길이가 거의 0이면 정지로 처리한다.
    if dx * dx + dy * dy < 1e-6:
        return 0
    # 2) 벡터 각도를 45도 간격으로 양자화해 이동 번호로 변환한다.
    ang = math.atan2(dy, dx)                       # 0=→, +π/2=↓
    sector = int(round(ang / (math.pi / 4))) % 8   # 0=→,1=↘,2=↓,3=↙,4=←,5=↖,6=↑,7=↗
    return (3, 4, 5, 6, 7, 8, 1, 2)[sector]


SCORE_POPUP_FRAMES = 60   # 점수 연출을 기억하는 시간 (1초)


def wrap_angle(a: float) -> float:
    """라디안 각도를 표준 범위로 감싼다.

    인자:
        a: 변환할 각도(라디안).

    처리:
        주기 2π의 나머지 연산으로 각도를 정규화한다.

    반환:
        float: -π 이상 π 미만의 각도.
    """
    return (a + math.pi) % (2 * math.pi) - math.pi


# --------------------------------------------------------------------------
# 엔티티
# --------------------------------------------------------------------------
@dataclass
class Tank:  # 플레이어·적 선체의 이동·전투·AI 상태
    id: int                          # 이번 판에서 선체를 식별하는 고유 번호
    team: str                        # 소속 진영 ("player" / "enemy")
    x: float                         # 선체 중심의 월드 가로 좌표 (px)
    y: float                         # 선체 중심의 월드 세로 좌표 (px, 아래쪽이 양수)
    hp: float                        # 현재 체력
    max_hp: float                    # 최대 체력
    radius: float                    # 선체 충돌 반지름 (px)
    fire_cooldown_max: int            # 우주선 종류별 간격 배율 적용 전 기본 발사 대기 (프레임)
    vx: float = 0.0                  # 가로 이동 속도 (px/frame)
    vy: float = 0.0                  # 세로 이동 속도 (px/frame)
    angle: float = 0.0               # 포신 각도 (rad, 0=오른쪽, 시계방향이 양수)
    cooldown: int = 0                # 다음 발사 묶음까지 남은 대기 프레임
    alive: bool = True               # 선체 생존 여부
    respawn_timer: int = 0           # 죽은 적이 재등장하기까지 남은 프레임
    last_hit_frame: int = -10**9      # 마지막 피격 프레임 (회복 지연 계산용)
    damage_scale: float = 1.0        # 기본 탄환 피해에 곱할 개체별 공격력 배율
    accel_scale: float = 1.0         # 기본 이동 가속도에 곱할 개체별 배율
    bullet_speed_scale: float = 1.0  # 기본 탄속에 곱할 개체별 배율
    bullet_life_scale: float = 1.0   # 기본 탄환 수명에 곱할 개체별 배율
    regen_bonus: float = 0.0         # 플레이어의 프레임당 추가 체력 회복량
    projectiles: int = 1             # 현재 우주선의 발사 패턴 수 (실제 발사는 ShipClass.shots 사용)
    job: str = "rookie"              # 현재 우주선 종류 키
    ammo: int = 0                    # 플레이어 탄창의 남은 탄약 수
    max_ammo: int = 0                # 플레이어 탄창 용량
    reload_scale: float = 1.0        # 플레이어 기본 재장전 시간에 곱할 배율
    pending_shots: list = field(default_factory=list)  # 예약 점사 (발사 프레임, 패턴, 피해, 탄속, 수명) 목록
    elite: bool = False              # 엘리트 적 여부 (능력치·처치 점수 강화, 처치 시 플레이어 회복)
    stat_levels: dict = field(default_factory=dict)  # 적 개체에 무작위 배분한 스탯 키별 강화 단계
    # 적 AI 상태
    ai_timer: int = 0                # 목표·조준 오차·옆돌기 방향을 다시 정하기까지 남은 프레임
    ai_target: tuple = None          # 목표 ("player", id) / ("shape", id) / ("point", (x, y)) / None
    ai_aim_offset: float = 0.0        # 목표 방향에 더할 조준 오차 (rad)
    ai_move: int = 0                 # 목표가 없을 때 사용할 이동 번호 (0=정지, 1~8=8방향)
    ai_can_see: bool = False         # 이번 프레임에 시야 거리·시야선 조건으로 플레이어가 보이는지
    ai_last_seen: tuple = None       # 감지하거나 동료에게 전달받은 마지막 플레이어 위치 (월드 x, y)
    ai_last_seen_frame: int = -10**9  # 마지막 플레이어 위치를 확인·전달받은 프레임
    ai_path: list = field(default_factory=list)  # A* 탐색 후 남은 이동 경로 (타일 열·행 좌표 목록)
    ai_path_timer: int = 0           # A* 경로를 다시 계산하기까지 남은 프레임
    ai_goal: tuple = None            # 현재 이동 목표의 월드 좌표 (디버그 표시용)
    ai_strafe: float = 1.0           # 목표 주위를 옆으로 도는 방향 (1 또는 -1)


@dataclass
class Shape:  # 파괴 가능한 천체의 이동·체력·점수 상태
    id: int                       # 이번 판에서 천체를 식별하는 고유 번호
    kind: str                     # 천체 종류 키 (square / triangle / pentagon)
    x: float                      # 천체 중심의 월드 가로 좌표 (px)
    y: float                      # 천체 중심의 월드 세로 좌표 (px)
    vx: float                     # 가로 표류 속도 (px/frame)
    vy: float                     # 세로 표류 속도 (px/frame)
    hp: float                     # 현재 체력
    max_hp: float                 # 최대 체력 (관찰·피해 보상 정규화 기준)
    radius: float                 # 천체 충돌 반지름 (px)
    score: int                    # 플레이어가 파괴했을 때 획득할 점수
    angle: float = 0.0            # 현재 회전 각도 (rad)
    spin: float = 0.0             # 프레임당 회전량 (rad/frame)


@dataclass
class Bullet:  # 탄환의 이동·피해·충돌·관통 상태
    x: float                         # 탄환 중심의 현재 월드 가로 좌표 (px)
    y: float                         # 탄환 중심의 현재 월드 세로 좌표 (px)
    vx: float                        # 가로 이동 속도 (px/frame)
    vy: float                        # 세로 이동 속도 (px/frame)
    life: int                        # 소멸하기까지 남은 수명 (프레임)
    owner_id: int                    # 탄환을 발사한 선체의 고유 번호
    team: str                        # 공격 진영 ("player" / "enemy")
    damage: float                    # 명중 시 적용할 피해량 (대상 선체의 받는 피해 배율 적용 전)
    radius: float                    # 탄환 충돌 반지름 (px)
    blast_radius: float = 0.0        # 명중 시 폭발 반지름 (px, 0이면 직접 피해)
    prev_x: float = None             # 이동 구간 충돌 판정의 시작 가로 좌표 (None이면 현재 위치 사용)
    prev_y: float = None             # 이동 구간 충돌 판정의 시작 세로 좌표
    kind: str = "plasma"             # 표시할 탄환 종류 (plasma / shell / mine / missile)
    arming_frames: int = 0           # 이전 지뢰의 무장 대기 프레임 (현재 미사용)
    homing: bool = False             # 이전 유도탄의 추적 여부 (현재 미사용)
    pierce: int = 0                  # 명중 후 탄환을 유지할 수 있는 남은 관통 횟수
    hit_ids: set = field(default_factory=set)  # 이미 맞힌 대상 번호 집합 (관통 중 중복 피해 방지)


@dataclass
class Beam:  # 빔 연출의 시작점·끝점·수명
    x: float          # 빔 시작점의 월드 가로 좌표 (px)
    y: float          # 빔 시작점의 월드 세로 좌표 (px)
    end_x: float      # 빔 끝점의 월드 가로 좌표 (px)
    end_y: float      # 빔 끝점의 월드 세로 좌표 (px)
    life: int = 6     # 연출이 사라지기까지 남은 프레임


@dataclass
class Explosion:  # 폭발 연출의 중심·크기·수명
    x: float          # 폭발 중심의 월드 가로 좌표 (px)
    y: float          # 폭발 중심의 월드 세로 좌표 (px)
    radius: float     # 폭발 연출의 기준 반지름 (px)
    life: int = 18    # 연출이 사라지기까지 남은 프레임


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


# --------------------------------------------------------------------------
# 게임
# --------------------------------------------------------------------------
class GameCore:
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
        self.reset(seed)

    # ---------------- 초기화 ----------------
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
        # 카드 열기/선택이 맵 생성과 전투 난수열을 바꾸지 않도록 분리한다.
        self.reward_rng = np.random.default_rng(seed)  # 보상 추첨용 별도 난수 생성기 (현재 미사용)
        self.frame = 0  # 이번 판에서 진행한 게임 프레임 수
        self.score = 0  # 플레이어 누적 점수
        self.kills = 0  # 플레이어가 처치한 적 수
        self.game_over = False  # 플레이어 사망으로 게임이 끝났는지 여부
        self._next_id = 0  # 선체·천체의 고유 번호 발급용 카운터
        self.events = empty_events()  # pop_events()로 꺼내기 전까지 누적하는 전투 이벤트
        self.level = 1  # 플레이어의 현재 레벨
        self.xp = 0  # 다음 레벨업을 위해 쌓인 경험치
        self.upgrade_points = 0  # 아직 사용하지 않은 일반 스탯 강화 포인트
        self.special_reward_levels = []  # 진화·숙련 보상을 아직 선택하지 않은 레벨 목록
        self.stat_levels = {card.key: 0 for card in STAT_UPGRADES}  # 스탯 키별 플레이어 강화 단계
        self.stat_choices = STAT_UPGRADES  # 화면에 표시할 스탯 강화 선택지
        self.special_levels = {key: 0 for key in SHIPS}  # 우주선 키별 보상 선택 횟수 (숙련 배율 계산용)
        self.family = ""  # 10레벨에 선택한 첫 진화 계열 키
        self.active_skill = None  # 이전 액티브 스킬 상태 (현재 미사용)
        self.skill_cooldown = 0  # 이전 액티브 스킬의 남은 대기 프레임 (현재 미사용)
        self.reward_portrait = None  # 마지막으로 선택한 진화·숙련 보상의 우주선 키
        self.reward_choices = ()  # 현재 선택을 기다리는 진화·숙련 보상 목록
        self.last_reward = ""  # 마지막으로 적용한 보상의 알림 문구
        self.reward_message_until = 0  # 보상 알림 표시를 끝낼 게임 프레임
        self.reload_frames_left = 0  # 플레이어 재장전 완료까지 남은 프레임
        self.dash_frames_left = 0  # 이전 돌진 동작의 남은 프레임 (현재 미사용)
        self.beams = []  # 수명이 남은 빔 연출 목록
        self.explosions = []  # 수명이 남은 폭발 연출 목록
        # 화면 연출용: 플레이어가 얻은 점수 (id, frame, x, y, 점수, 종류). 게임 규칙에는 쓰지 않는다.
        self.score_popups = []  # 획득 점수 연출 기록 (번호, 프레임, x, y, 점수, 종류)
        self._popup_id = 0  # 점수 연출의 고유 번호 발급용 카운터
        self.player_shot_frame = -10**9  # 적의 청각 감지에 쓰는 마지막 플레이어 발사 프레임
        self.bullets = []  # 현재 비행 중인 탄환 목록
        self.shapes = []  # 현재 월드에 남아 있는 천체 목록
        self.enemies = []  # 적 목록 (생성 위치 계산에 이전 판의 적이 섞이지 않도록 먼저 비움)
        self.enemy_scale_tier = 0  # 경과 시간에 따른 적 성장 단계

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
            self._respawn_enemy(e)
            self.enemies.append(e)
        for _ in range(c.num_shapes):
            self.shapes.append(self._make_shape())

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

    def _respawn_enemy(self, e: Tank):
        """적의 종류·능력치를 다시 정하고 재등장 상태로 초기화한다.

        인자:
            e: 생성 또는 재등장시킬 적 Tank.

        처리:
            1) 플레이어 진화 단계에 맞는 종류·엘리트 여부·스탯을 추첨하고 능력치를 적용한다.
            2) 플레이어와 멀고 다른 적과 겹치지 않는 시작 위치를 우선 선택한다.
            3) 체력·속도·발사 대기·조준·AI 목표·경로를 초기화한다.

        반환:
            None: 전달받은 적 개체를 살아 있는 재등장 상태로 변경한다.
        """
        # 1) 플레이어 진화 단계에 맞는 종류·엘리트 여부·스탯을 추첨하고 능력치를 적용한다.
        tm = self.terrain
        p = self.player
        e.job = self._random_enemy_job()
        ai = self.cfg.enemy_ai
        mercy = self._mercy_factor()
        elite_chance = ai.elite_chance * (ai.mercy_elite_chance_scale + (1 - ai.mercy_elite_chance_scale) * mercy)
        e.elite = bool(self.rng.random() < elite_chance)
        self._roll_enemy_stats(e)
        self._apply_enemy_strength(e)
        # 맵의 E 위치 중 플레이어와 멀고 다른 적과 겹치지 않는 곳 우선 (화면 안이든 밖이든 상관없음).
        # 2) 플레이어와 멀고 다른 적과 겹치지 않는 시작 위치를 우선 선택한다.
        others = [o for o in getattr(self, "enemies", []) if o.alive and o is not e]
        starts = []
        for s in tm.enemy_starts:
            sx, sy = tm.center(*s)
            if not tm.circle_fits(sx, sy, e.radius):
                continue
            if (sx - p.x) ** 2 + (sy - p.y) ** 2 >= 300.0 ** 2 and \
                    all((sx - o.x) ** 2 + (sy - o.y) ** 2 >= (2 * e.radius) ** 2 for o in others):
                starts.append((sx, sy))
        if starts:
            e.x, e.y = starts[int(self.rng.integers(len(starts)))]
        else:
            e.x, e.y = self._random_free_pos(e.radius, 300.0)
        # 3) 체력·속도·발사 대기·조준·AI 목표·경로를 초기화한다.
        e.vx = e.vy = 0.0
        e.hp = e.max_hp
        e.alive = True
        e.cooldown = e.fire_cooldown_max
        e.pending_shots.clear()
        e.angle = float(self.rng.uniform(-math.pi, math.pi))
        e.ai_timer = 0
        e.ai_target = None
        e.ai_can_see = False
        e.ai_last_seen = None
        e.ai_path = []
        e.ai_path_timer = 0
        e.ai_goal = None

    # ---------------- 적 성장 ----------------
    def _random_enemy_job(self):
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
        jobs = SHIPS_BY_LEVEL[SHIPS[self.player.job].level]
        # 2) 후보 중 하나를 균등 확률로 추첨한다.
        return jobs[int(self.rng.integers(len(jobs)))]

    def _mercy_factor(self):
        """초반 적 약화가 정상 난이도로 돌아오는 진행도를 계산한다.

        인자:
            없음(self는 현재 게임 상태를 참조한다).

        처리:
            현재 프레임과 약화 지속 시간으로 진행도를 계산한다. 지속 시간이 0 이하면 즉시 완료로 처리한다.

        반환:
            float: 시작 시 0.0, 약화 종료 후 1.0인 진행도.
        """
        ai = self.cfg.enemy_ai
        if ai.mercy_seconds <= 0:
            return 1.0
        return min(1.0, self.frame / (ai.mercy_seconds * self.cfg.fps))

    def _enemy_stat_budget(self):
        """플레이어 스탯 투자량을 기준으로 적의 강화 포인트 총량을 계산한다.

        인자:
            없음(self는 현재 게임 상태를 참조한다).

        처리:
            플레이어의 각 스탯 레벨에 반영 비율을 곱하고 항목별 정수 절삭값을 합산한다.

        반환:
            int: 적 한 개체에 배분할 스탯 포인트 수.
        """
        ratio = self.cfg.enemy_ai.stat_mirror_ratio
        return sum(int(self.stat_levels.get(card.key, 0) * ratio) for card in STAT_UPGRADES)

    def _roll_enemy_stats(self, e: Tank):
        """적 강화 포인트를 스탯 항목에 무작위로 배분한다.

        인자:
            e: 스탯 배분을 갱신할 적 Tank.

        처리:
            1) 강화 항목과 포인트 총량을 구한다.
            2) 포인트가 없으면 모든 항목을 0으로 두고, 있으면 균등 확률의 다항분포로 배분한다.

        반환:
            None: e.stat_levels를 새 배분 결과로 교체한다.
        """
        # 1) 강화 항목과 포인트 총량을 구한다.
        keys = [card.key for card in STAT_UPGRADES]
        budget = self._enemy_stat_budget()
        # 2) 포인트가 없으면 모든 항목을 0으로 두고, 있으면 균등 확률의 다항분포로 배분한다.
        if budget <= 0:
            e.stat_levels = dict.fromkeys(keys, 0)
            return
        counts = self.rng.multinomial(budget, [1.0 / len(keys)] * len(keys))
        e.stat_levels = {key: int(n) for key, n in zip(keys, counts)}

    def _apply_enemy_strength(self, e: Tank):
        """성장 단계·초반 약화·엘리트·우주선·스탯을 합쳐 적 능력치를 갱신한다.

        인자:
            e: 능력치를 갱신할 적 Tank.

        처리:
            1) 성장 배율과 초반 약화·엘리트 배율, 기존 체력 비율을 계산한다.
            2) 스탯 배분이 없으면 추첨하고 항목별 레벨을 읽는다.
            3) 최대 체력·반지름·공격력·연사·이동·탄환 능력치를 갱신하되 현재 체력 비율은 유지한다.

        반환:
            None: 전달받은 적의 전투 능력치를 직접 변경한다.
        """
        # 1) 성장 배율과 초반 약화·엘리트 배율, 기존 체력 비율을 계산한다.
        c, ai, spec = self.cfg, self.cfg.enemy_ai, SHIPS[e.job]
        tier = self.enemy_scale_tier
        mercy = self._mercy_factor()
        hp_mercy = ai.mercy_hp_scale + (1 - ai.mercy_hp_scale) * mercy
        damage_mercy = ai.mercy_damage_scale + (1 - ai.mercy_damage_scale) * mercy
        fire_rate_mercy = ai.mercy_fire_rate_scale + (1 - ai.mercy_fire_rate_scale) * mercy
        ratio = e.hp / e.max_hp if e.max_hp > 0 else 1.0
        # 대형 선체의 체력 보너스는 플레이어의 절반만 받는다.
        elite_hp, elite_damage = (ai.elite_hp_scale, ai.elite_damage_scale) if e.elite else (1.0, 1.0)
        # 플레이어의 upgrade_stat()과 같은 배율을 적용한다(hull은 +25, 나머지는 레벨당 배율).
        # 어느 항목에 얼마나 찍혔는지는 개체마다 무작위로 다르다(_roll_enemy_stats).
        # 2) 스탯 배분이 없으면 추첨하고 항목별 레벨을 읽는다.
        if not e.stat_levels:
            self._roll_enemy_stats(e)
        levels = e.stat_levels
        hull_lv = levels.get("hull", 0)
        damage_lv = levels.get("damage", 0)
        rapid_lv = levels.get("rapid", 0)
        speed_lv = levels.get("speed", 0)
        range_lv = levels.get("range", 0)
        # 3) 최대 체력·반지름·공격력·연사·이동·탄환 능력치를 갱신하되 현재 체력 비율은 유지한다.
        e.max_hp = ((c.enemy_hp + spec.hp_bonus * 0.5 + 25 * hull_lv)
                    * (1 + ai.hp_growth * tier) * elite_hp * hp_mercy)
        e.hp = e.max_hp * ratio
        e.radius = c.tank_radius * spec.radius_scale
        e.damage_scale = (1 + ai.damage_growth * tier) * elite_damage * damage_mercy * (1.25 ** damage_lv)
        rapid_factor = (1 + ai.fire_rate_growth * tier) * fire_rate_mercy * ((1 / 0.95) ** rapid_lv)
        e.fire_cooldown_max = max(ai.min_fire_cooldown, round(ai.fire_cooldown / rapid_factor))
        e.accel_scale = (1 + ai.speed_growth * tier) * (1.07 ** speed_lv)
        e.bullet_speed_scale = 1.2 ** range_lv
        e.bullet_life_scale = 1.15 ** range_lv
        e.projectiles = len(spec.shots)

    def _update_enemy_scaling(self):
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
        ai = self.cfg.enemy_ai
        tier = min(ai.max_scale_tier, int(self.frame / (ai.scale_interval_seconds * self.cfg.fps)))
        tier_changed = tier != self.enemy_scale_tier
        if tier_changed:
            self.enemy_scale_tier = tier
        # 2) 단계가 바뀌었거나 초반 약화 기간이면 모든 적의 능력치를 다시 적용한다.
        if tier_changed or self.frame <= ai.mercy_seconds * self.cfg.fps:
            for e in self.enemies:
                self._apply_enemy_strength(e)

    def _promote_enemies(self):
        """플레이어 진화에 맞춰 모든 적을 같은 단계의 우주선으로 진화시킨다.

        인자:
            없음(self는 현재 게임 상태를 참조한다).

        처리:
            1) 적마다 새 종류를 추첨하고 능력치를 다시 계산한다.
            2) 예약 점사를 취소하고 발사 대기를 제한하며 살아 있는 적의 지형 겹침을 보정한다.

        반환:
            None: 모든 적의 종류·능력치·발사 상태와 필요한 위치를 변경한다.
        """
        for e in self.enemies:
            # 1) 적마다 새 종류를 추첨하고 능력치를 다시 계산한다.
            e.job = self._random_enemy_job()
            self._apply_enemy_strength(e)
            # 2) 예약 점사를 취소하고 발사 대기를 제한하며 살아 있는 적의 지형 겹침을 보정한다.
            e.pending_shots.clear()
            e.cooldown = min(e.cooldown, e.fire_cooldown_max)
            if e.alive:
                self._fit_tank(e)

    # ---------------- 외부 API ----------------
    @property
    def xp_to_next_level(self):
        """현재 레벨에서 다음 레벨로 오르는 데 필요한 경험치를 계산한다.

        인자:
            없음(self는 현재 게임 상태를 참조한다).

        처리:
            기본 필요 경험치에 현재 레벨에 따른 증가량을 더한다.

        반환:
            int: 다음 레벨업의 전체 필요 경험치(남은 경험치가 아님).
        """
        return self.cfg.level_xp_base + (self.level - 1) * self.cfg.level_xp_growth

    @property
    def pending_rewards(self):
        """아직 사용하지 않은 강화·진화 보상의 총수를 계산한다.

        인자:
            없음(self는 현재 게임 상태를 참조한다).

        처리:
            일반 강화 포인트와 대기 중인 특수 보상 레벨 수를 합산한다.

        반환:
            int: 미사용 보상 수.
        """
        return self.upgrade_points + len(self.special_reward_levels)

    def _add_score(self, amount):
        """점수를 누적하고 성장 설정에 따라 경험치·레벨·보상을 갱신한다.

        인자:
            amount: 추가할 점수. 성장 활성화 시 같은 양을 경험치에도 더한다.

        처리:
            1) 점수를 더하고 성장 비활성화 상태면 종료한다.
            2) 경험치를 더해 가능한 만큼 레벨업하고 10레벨마다 진화 보상, 나머지는 강화 포인트를 쌓는다.
            3) 진화 선택지와 스탯 강화 목록을 준비한다.

        반환:
            None: 점수와 성장 관련 상태를 갱신한다.
        """
        # 1) 점수를 더하고 성장 비활성화 상태면 종료한다.
        self.score += amount
        if not self.cfg.progression_enabled:
            return
        # 2) 경험치를 더해 가능한 만큼 레벨업하고 10레벨마다 진화 보상, 나머지는 강화 포인트를 쌓는다.
        self.xp += amount
        while self.xp >= self.xp_to_next_level:
            self.xp -= self.xp_to_next_level
            self.level += 1
            if self.level % 10 == 0:
                self.special_reward_levels.append(self.level)
            else:
                self.upgrade_points += 1
        # 3) 진화 선택지와 스탯 강화 목록을 준비한다.
        self.open_rewards()
        self.open_stat_upgrades()

    def open_rewards(self):
        """가장 먼저 대기 중인 진화 보상의 선택지를 준비한다.

        인자:
            없음(self는 현재 게임 상태를 참조한다).

        처리:
            1) 게임 종료·플레이어 생존·대기 보상을 확인하고 이미 열린 선택지는 재사용한다.
            2) 10레벨은 계열, 20·30레벨은 현재 종류의 다음 진화, 이후는 현재 종류의 숙련 보상을 준비한다.

        반환:
            tuple: 선택 가능한 계열 또는 우주선 정의. 보상을 열 수 없으면 빈 튜플.
        """
        # 1) 게임 종료·플레이어 생존·대기 보상을 확인하고 이미 열린 선택지는 재사용한다.
        if self.game_over or not self.player.alive or not self.special_reward_levels:
            return ()
        if self.reward_choices:
            return self.reward_choices
        # 2) 10레벨은 계열, 20·30레벨은 현재 종류의 다음 진화, 이후는 현재 종류의 숙련 보상을 준비한다.
        level = self.special_reward_levels[0]
        if level == 10:
            self.reward_choices = FAMILIES
        elif level in (20, 30):
            self.reward_choices = tuple(ship for ship in SHIPS.values()
                                        if ship.parent == self.player.job and ship.level == level)
        else:
            self.reward_choices = (SHIPS[self.player.job],)
        return self.reward_choices

    def choose_reward(self, index):
        """선택한 진화·숙련 보상을 적용하고 다음 보상을 준비한다.

        인자:
            index: 현재 reward_choices에서 고를 0부터 시작하는 정수 인덱스.

        처리:
            1) 플레이어 상태·대기 보상·인덱스를 검증한다.
            2) 선택한 종류의 체력·반지름·무장을 적용하고 실제 진화 시 적들도 진화시킨다.
            3) 보상을 소모하고 숙련 횟수·알림·초상화를 갱신한 뒤 다음 선택지를 준비한다.

        반환:
            bool: 적용에 성공하면 True, 선택할 수 없는 상태나 인덱스면 False.
        """
        # 1) 플레이어 상태·대기 보상·인덱스를 검증한다.
        if self.game_over or not self.player.alive or not self.reward_choices or not self.special_reward_levels:
            return False
        if not isinstance(index, int) or not 0 <= index < len(self.reward_choices):
            return False
        # 2) 선택한 종류의 체력·반지름·무장을 적용하고 실제 진화 시 적들도 진화시킨다.
        card = self.reward_choices[index]
        p = self.player
        level = self.special_reward_levels[0]
        previous = SHIPS[p.job]
        if level == 10:
            self.family = card.key
        hp_delta = card.hp_bonus - previous.hp_bonus
        p.max_hp += hp_delta
        p.hp = min(p.max_hp, p.hp + hp_delta)
        p.radius = self.cfg.tank_radius * card.radius_scale
        promoted = card.level != previous.level
        p.job = card.key
        p.projectiles = len(card.shots)
        p.cooldown = 0
        p.pending_shots.clear()
        self._fit_player_after_evolution()
        if promoted:
            self._promote_enemies()
        # 3) 보상을 소모하고 숙련 횟수·알림·초상화를 갱신한 뒤 다음 선택지를 준비한다.
        self.special_levels[card.key] += 1
        self.special_reward_levels.pop(0)
        self.reward_choices = ()
        self.reward_portrait = card.key
        self._reward_notice(card.title if level <= 30 else f"{card.title} 숙련 +1")
        self.open_rewards()
        return True

    def open_stat_upgrades(self):
        # 숫자 1~5와 각 능력치 위치는 포인트 유무나 강화 한도와 관계없이 고정한다.
        """고정 순서의 스탯 강화 목록을 표시용으로 준비한다.

        인자:
            없음(self는 현재 게임 상태를 참조한다).

        처리:
            포인트 수나 강화 상한과 관계없이 전체 강화 정의를 고정 순서로 설정한다.

        반환:
            tuple: STAT_UPGRADES와 같은 강화 정의 목록. 선택 가능 여부는 별도로 검사한다.
        """
        self.stat_choices = STAT_UPGRADES
        return self.stat_choices

    def can_upgrade_stat(self, key):
        """지정한 스탯을 지금 강화할 수 있는지 확인한다.

        인자:
            key: 강화할 스탯 키(damage, rapid, speed, hull, range).

        처리:
            키·포인트·게임 종료·생존·스탯 상한·최소 발사 간격 조건을 함께 검사한다.

        반환:
            bool: 모든 강화 조건을 만족하면 True, 아니면 False.
        """
        return (key in self.stat_levels and self.upgrade_points > 0 and not self.game_over
                and self.player.alive and self.stat_levels[key] < STAT_MAX_LEVEL
                and not (key == "rapid" and self.player.fire_cooldown_max <= 4))

    def upgrade_stat(self, key):
        """강화 포인트 하나로 플레이어 스탯을 올리고 적의 대응 성장을 반영한다.

        인자:
            key: 강화할 스탯 키(damage, rapid, speed, hull, range).

        처리:
            1) 강화 가능 여부를 확인하고 해당 플레이어 능력치를 올린다.
            2) 포인트를 차감하고 스탯 레벨을 올린 뒤 적 스탯을 재배분해 능력치를 갱신한다.
            3) 강화 알림과 스탯 선택 목록을 갱신한다.

        반환:
            bool: 강화 성공 시 True, 강화할 수 없으면 False.
        """
        # 1) 강화 가능 여부를 확인하고 해당 플레이어 능력치를 올린다.
        if not self.can_upgrade_stat(key):
            return False
        p = self.player
        if key == "damage":
            p.damage_scale *= 1.25
        elif key == "rapid":
            old_cooldown = p.fire_cooldown_max
            p.fire_cooldown_max = max(4, round(p.fire_cooldown_max * 0.95))
            p.cooldown = math.ceil(p.cooldown * p.fire_cooldown_max / old_cooldown)
        elif key == "speed":
            p.accel_scale *= 1.07
        elif key == "hull":
            p.max_hp += 25
            p.hp = min(p.max_hp, p.hp + 25)
        elif key == "range":
            p.bullet_speed_scale *= 1.2
            p.bullet_life_scale *= 1.15
        # 2) 포인트를 차감하고 스탯 레벨을 올린 뒤 적 스탯을 재배분해 능력치를 갱신한다.
        self.upgrade_points -= 1
        self.stat_levels[key] += 1
        for e in self.enemies:
            self._roll_enemy_stats(e)   # 늘어난 포인트 총량을 다시 무작위로 재배분
            self._apply_enemy_strength(e)
            e.cooldown = min(e.cooldown, e.fire_cooldown_max)
        # 3) 강화 알림과 스탯 선택 목록을 갱신한다.
        self._reward_notice(next(card.title for card in STAT_UPGRADES if card.key == key))
        self.stat_choices = ()
        self.open_stat_upgrades()
        return True

    def _reward_notice(self, title):
        """보상 알림 내용과 표시 종료 프레임을 설정한다.

        인자:
            title: 화면에 표시할 보상 알림 문자열.

        처리:
            1) 화면에 보여 줄 알림 제목을 저장한다.
            2) 현재 프레임부터 3초 뒤를 표시 종료 시점으로 정한다.

        반환:
            None: last_reward와 reward_message_until을 갱신한다.
        """
        # 1) 화면에 보여 줄 알림 제목을 저장한다.
        self.last_reward = title
        # 2) 현재 프레임부터 3초 뒤를 표시 종료 시점으로 정한다.
        self.reward_message_until = self.frame + self.cfg.fps * 3

    @property
    def reload_frames_total(self):
        """플레이어의 재장전 시간을 프레임 수로 계산한다.

        인자:
            없음(self는 현재 게임 상태를 참조한다).

        처리:
            기본 시간에 재장전 배율을 적용하고 최소 0.75초를 보장한 뒤 프레임 수를 올림한다.

        반환:
            int: 재장전 완료까지 필요한 전체 프레임 수.
        """
        return math.ceil(max(0.75, self.cfg.reload_seconds * self.player.reload_scale) * self.cfg.fps)

    def request_reload(self):
        """가능한 상태라면 플레이어 재장전을 시작한다.

        인자:
            없음(self는 현재 게임 상태를 참조한다).

        처리:
            1) 게임 종료·생존·탄약 제한·진행 중 재장전·탄창 잔량을 검사한다.
            2) 재장전 타이머를 시작하고 예약된 점사를 취소한다.

        반환:
            bool: 재장전을 시작하면 True, 시작할 수 없으면 False.
        """
        # 1) 게임 종료·생존·탄약 제한·진행 중 재장전·탄창 잔량을 검사한다.
        if (self.game_over or not self.player.alive or not self.cfg.limited_ammo
                or self.reload_frames_left or self.player.ammo >= self.player.max_ammo):
            return False
        # 2) 재장전 타이머를 시작하고 예약된 점사를 취소한다.
        self.reload_frames_left = self.reload_frames_total
        self.player.pending_shots.clear()
        return True

    def request_skill(self, move=0, aim_position=None):
        """제거된 액티브 스킬 호출을 받아 주는 호환용 API다.

        인자:
            move: 이전 호출 형식을 유지하기 위한 이동 번호. 현재는 사용하지 않는다.
            aim_position: 이전 호출 형식을 유지하기 위한 조준 월드 좌표. 현재는 사용하지 않는다.

        처리:
            게임 상태를 변경하지 않고 스킬 사용 실패를 알린다.

        반환:
            bool: 항상 False.
        """
        return False

    def _shot_delays(self, tank, spec):
        # 발사속도 강화는 연사 묶음 사이 대기뿐 아니라 묶음 안의 점사도 빠르게 한다.
        """우주선 점사 패턴의 지연을 실제 발사 간격에 맞게 환산한다.

        인자:
            tank: 점사를 발사할 Tank.
            spec: shots 발사 패턴을 가진 우주선 정의.

        처리:
            1) 플레이어는 강화된 발사 간격 비율을 구하고 적은 기본 배율 1.0을 사용한다.
            2) 각 고유 지연을 환산하되 서로 다른 지연은 최소 1프레임 간격을 유지한다.

        반환:
            dict[int, int]: 원래 지연을 실제 지연 프레임으로 대응한 사전. 0은 0으로 대응한다.
        """
        # 1) 플레이어는 강화된 발사 간격 비율을 구하고 적은 기본 배율 1.0을 사용한다.
        scale = tank.fire_cooldown_max / max(1, self.cfg.player_fire_cooldown) if tank.team == "player" else 1.0
        # 2) 각 고유 지연을 환산하되 서로 다른 지연은 최소 1프레임 간격을 유지한다.
        delays, previous = {0: 0}, 0
        for delay in sorted({shot.delay for shot in spec.shots if shot.delay}):
            previous = max(previous + 1, round(delay * scale))
            delays[delay] = previous
        return delays

    def weapon_values(self, tank: Tank):
        """선체 종류와 강화·숙련을 반영한 발사 능력치를 계산한다.

        인자:
            tank: 무기 능력치를 조회할 플레이어 또는 적 Tank.

        처리:
            1) 우주선 정의와 플레이어 숙련 배율을 읽고 기본 피해량을 계산한다.
            2) 점사가 끝나는 시점과 최소 간격을 반영해 쿨다운을 계산한다.
            3) 선체 배율을 반영한 탄속과 탄환 수명을 계산한다.

        반환:
            tuple: (우주선 정의, 피해량, 쿨다운 프레임, 탄속(px/frame), 수명 프레임). 개별 shot 배율은 발사 시 추가 적용한다.
        """
        # 1) 우주선 정의와 플레이어 숙련 배율을 읽고 기본 피해량을 계산한다.
        spec = SHIPS[tank.job]
        mastery = 1 + 0.2 * max(0, self.special_levels.get(tank.job, 0) - 1) if tank.team == "player" else 1
        damage = self.cfg.bullet_damage * tank.damage_scale * spec.damage * mastery
        # 2) 점사가 끝나는 시점과 최소 간격을 반영해 쿨다운을 계산한다.
        burst_end = max(self._shot_delays(tank, spec).values())
        cooldown = max(2 if spec.cooldown < 1 else 4, burst_end, int(tank.fire_cooldown_max * spec.cooldown))
        # 3) 선체 배율을 반영한 탄속과 탄환 수명을 계산한다.
        return (spec, damage, cooldown, self.cfg.bullet_speed * tank.bullet_speed_scale * spec.speed,
                int(self.cfg.bullet_life * tank.bullet_life_scale * spec.life))

    def _emit_shot(self, tank, shot, damage, speed, life):
        """포신 위치와 개별 발사 패턴을 반영해 탄환 한 발을 생성한다.

        인자:
            tank: 발사 주체 Tank.
            shot: 포신 위치·각도·구경·탄속·피해·수명 배율을 담은 발사 패턴.
            damage: 개별 발사 배율 적용 전 피해량.
            speed: 개별 발사 배율 적용 전 탄속(px/frame).
            life: 개별 발사 배율 적용 전 수명(프레임).

        처리:
            1) 실제 선체 크기로 포신 축·포구 위치·탄환 반지름을 계산하고 벽 앞에서 포구를 제한한다.
            2) 발사 배율과 스나이퍼 관통 특성을 적용해 탄환을 만든다.
            3) 포신 축에서 이미 겹친 대상을 먼저 판정하고 소멸하지 않은 탄환만 목록에 추가한다.

        반환:
            None: 탄환 목록과 즉시 명중한 대상의 상태를 변경한다.
        """
        # 1) 실제 선체 크기로 포신 축·포구 위치·탄환 반지름을 계산하고 벽 앞에서 포구를 제한한다.
        angle = tank.angle + shot.angle
        ca, sa = math.cos(angle), math.sin(angle)
        forward, lateral = shot.forward * tank.radius, shot.lateral * tank.radius
        radius = tank.radius * shot.caliber
        base_x, base_y = tank.x - sa * lateral, tank.y + ca * lateral
        reach, wall = self.terrain.sweep_circle(base_x, base_y, ca, sa, forward, radius)
        # 포신이 벽과 겹쳐도 벽 뒤에서 탄이 생기지 않게 실제 포신 축을 따라 자른다.
        if wall is not None:
            reach = max(0.0, reach - 0.01)
        # 2) 발사 배율과 스나이퍼 관통 특성을 적용해 탄환을 만든다.
        is_sniper_line = tank.job in SNIPER_LINE_JOBS
        bullet = Bullet(
            base_x + ca * reach, base_y + sa * reach, ca * speed * shot.speed, sa * speed * shot.speed,
            max(1, int(life * shot.life)), tank.id, tank.team, damage * shot.damage, radius,
            kind="shell" if is_sniper_line else "plasma",
            pierce=SNIPER_PIERCE if is_sniper_line else 0)
        # 길어진 포신과 이미 겹친 작은 천체/적을 포구 뒤에 남겨 놓고 발사하지 않는다.
        # 3) 포신 축에서 이미 겹친 대상을 먼저 판정하고 소멸하지 않은 탄환만 목록에 추가한다.
        bullet.prev_x, bullet.prev_y = base_x, base_y
        if not self._bullet_hit(bullet):
            bullet.prev_x = bullet.prev_y = None
            self.bullets.append(bullet)

    def _tick_effects(self):
        """빔과 폭발 연출의 남은 시간을 한 프레임 갱신한다.

        인자:
            없음(self는 현재 게임 상태를 참조한다).

        처리:
            1) 각 연출의 수명을 1 줄인다.
            2) 수명이 끝난 연출을 해당 목록에서 제거한다.

        반환:
            None: beams와 explosions 목록을 제자리에서 갱신한다.
        """
        for effects in (self.beams, self.explosions):
            # 1) 각 연출의 수명을 1 줄인다.
            for effect in effects:
                effect.life -= 1
            # 2) 수명이 끝난 연출을 해당 목록에서 제거한다.
            effects[:] = [effect for effect in effects if effect.life > 0]

    def _explode(self, x, y, damage, radius, team):
        """폭발 연출을 추가하고 주변 개체와 파괴 가능한 벽에 피해를 준다.

        인자:
            x: 폭발 중심의 월드 가로 좌표(px).
            y: 폭발 중심의 월드 세로 좌표(px).
            damage: 폭발의 기준 피해량.
            radius: 폭발 반지름(px, 양수).
            team: 공격 진영. player면 적, 그 외에는 플레이어를 공격한다.

        처리:
            1) 폭발 연출을 등록하고 공격 대상 진영을 결정한다.
            2) 반경에 닿는 선체와 천체에 거리 감쇠 피해를 적용한다.
            3) 중심이 폭발 반경 안에 있는 파괴 가능 벽 타일에 기준 피해를 적용한다.

        반환:
            None: 연출·체력·벽·점수·이벤트 상태를 갱신한다.
        """
        # 1) 폭발 연출을 등록하고 공격 대상 진영을 결정한다.
        by_player = team == "player"
        self.explosions.append(Explosion(x, y, radius))
        targets = self.enemies if by_player else [self.player]
        # 2) 반경에 닿는 선체와 천체에 거리 감쇠 피해를 적용한다.
        for target in list(targets) + list(self.shapes):
            if isinstance(target, Tank) and not target.alive:
                continue
            distance = math.hypot(target.x - x, target.y - y)
            if distance <= radius + target.radius:
                dealt = damage * (0.4 + 0.6 * max(0.0, 1 - distance / radius))
                if isinstance(target, Tank):
                    self._damage_tank(target, dealt, by_player)
                else:
                    self._damage_shape(target, dealt, by_player)
        # 3) 중심이 폭발 반경 안에 있는 파괴 가능 벽 타일에 기준 피해를 적용한다.
        for col, row in list(self.terrain.hp):
            cx, cy = self.terrain.center(col, row)
            if math.hypot(cx - x, cy - y) <= radius:
                self.terrain.damage_tile(col, row, damage)

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
        self._tick_effects()
        self._update_enemy_scaling()
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
                self._enemy_ai(e)
            else:
                e.respawn_timer -= 1
                if e.respawn_timer <= 0:
                    self._respawn_enemy(e)

        # 3) 발사·천체 이동·탄환 이동·몸체 충돌·체력 회복을 처리한다.
        self._fire(self.player, want_fire)
        self._move_shapes()
        self._move_bullets()
        self._collide_bodies()
        self._regen_player()

        # 도형 개수 유지
        # 4) 천체 수를 보충하고 프레임·점수 연출·재장전 타이머·사망 상태를 갱신한다.
        while len(self.shapes) < self.cfg.num_shapes:
            self.shapes.append(self._make_shape())

        self.frame += 1
        if self.score_popups and self.frame - self.score_popups[0][1] > SCORE_POPUP_FRAMES:
            self.score_popups = [pop for pop in self.score_popups if self.frame - pop[1] <= SCORE_POPUP_FRAMES]
        if self.reload_frames_left:
            self.reload_frames_left -= 1
            if self.reload_frames_left == 0 and self.player.hp > 0:
                self.player.ammo = self.player.max_ammo
        if self.player.hp <= 0:
            self.player.hp = 0.0
            self.player.alive = False
            self.player.pending_shots.clear()
            self.game_over = True
            self.events["died"] = True

    # ---------------- 탱크 이동/발사 ----------------
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

    def _fire(self, t: Tank, want_fire: bool):
        """예약 점사와 새 발사를 처리하고 탄약·발사 대기를 갱신한다.

        인자:
            t: 발사할 플레이어 또는 적 Tank.
            want_fire: 발사 조건이 맞을 때 새 발사 묶음을 시작할지 여부.

        처리:
            1) 사망·재장전 상태면 예약 점사를 취소하고, 아니면 발사 시점이 된 점사를 처리한다.
            2) 기존 발사 대기를 줄이고 새 발사 가능 여부와 탄약을 확인한다.
            3) 발사 패턴별로 즉시 탄환을 만들거나 점사를 예약하고 제한 탄약을 소비한다.
            4) 플레이어 발사 소리 시점과 다음 발사 대기를 기록한다.

        반환:
            None: 탄환·예약 점사·탄약·쿨다운·발사 소리 상태를 변경한다.
        """
        # 1) 사망·재장전 상태면 예약 점사를 취소하고, 아니면 발사 시점이 된 점사를 처리한다.
        player = t.team == "player"
        blocked = not t.alive or (player and self.reload_frames_left)
        if blocked:
            t.pending_shots.clear()
        else:
            # 방아쇠를 놓아도 시작한 점사는 마치되, 재장전/전직/죽음은 취소한다.
            due = [entry for entry in t.pending_shots if entry[0] <= self.frame]
            t.pending_shots[:] = [entry for entry in t.pending_shots if entry[0] > self.frame]
            for _, shot, damage, speed, life in due:
                if player and self.cfg.limited_ammo:
                    if t.ammo <= 0:
                        t.pending_shots.clear()
                        break
                    t.ammo -= 1
                self._emit_shot(t, shot, damage, speed, life)
        # 2) 기존 발사 대기를 줄이고 새 발사 가능 여부와 탄약을 확인한다.
        if t.cooldown > 0:
            t.cooldown -= 1
            return
        if blocked or not want_fire:
            return
        if player and self.cfg.limited_ammo and t.ammo <= 0:
            return
        # 3) 발사 패턴별로 즉시 탄환을 만들거나 점사를 예약하고 제한 탄약을 소비한다.
        spec, damage, cooldown, speed, life = self.weapon_values(t)
        delays = self._shot_delays(t, spec)
        for shot in spec.shots:
            if shot.delay:
                t.pending_shots.append((self.frame + delays[shot.delay], shot, damage, speed, life))
            else:
                if player and self.cfg.limited_ammo:
                    if t.ammo <= 0:
                        break
                    t.ammo -= 1
                self._emit_shot(t, shot, damage, speed, life)
        # 4) 플레이어 발사 소리 시점과 다음 발사 대기를 기록한다.
        if player:
            self.player_shot_frame = self.frame
        t.cooldown = cooldown

    # ---------------- 적 AI ----------------
    def _enemy_ai(self, e: Tank):
        """적 하나의 감지·목표 선택·추적 이동·조준·발사를 처리한다.

        인자:
            e: 이번 프레임 행동을 결정할 살아 있는 적 Tank.

        처리:
            1) 시야·근거리 감지·발사 소리로 플레이어 위치를 기억하고 조건에 따라 동료에게 공유한다.
            2) 반응 주기에 맞춰 플레이어·마지막 위치·천체 중 목표와 조준 오차를 정한다.
            3) 직접 접근 가능한 경우 거리를 유지하고, 막히면 A* 경로를 따라 이동 방향을 정한다.
            4) 예측 조준과 발사 각도 조건을 계산해 이동·회전·발사를 실행한다.

        반환:
            None: 적과 동료의 AI 상태, 적 위치·무장 상태, 발사 탄환을 갱신한다.
        """
        c = self.cfg
        ai = c.enemy_ai
        p = self.player
        tm = self.terrain

        # 1) 감지: 시야선이 트였으면 멀리서도 보고, 가까우면 벽 너머도 알아채고,
        #    플레이어가 쏘면 소리로 위치를 안다. 알게 된 위치는 항상 기억한다.
        dist = math.hypot(p.x - e.x, p.y - e.y)
        e.ai_can_see = p.alive and dist <= ai.sight_range and tm.line_of_sight(e.x, e.y, p.x, p.y)
        heard = self.frame - self.player_shot_frame <= ai.hearing_frames and dist <= ai.hearing_range
        sensed = p.alive and (dist <= ai.sense_range or heard)
        knew = e.ai_last_seen is not None
        if e.ai_can_see or sensed:
            e.ai_last_seen = (p.x, p.y)
            e.ai_last_seen_frame = self.frame
        elif knew and self.frame - e.ai_last_seen_frame > ai.memory_frames:
            # 벽을 돌아 마지막 위치로 가는 중이면 도착할 때까지 잊지 않는다 (도착하면 포기).
            following = e.ai_target is not None and e.ai_target[0] == "point" and e.ai_path
            if not following:
                e.ai_last_seen = None
        # 본 적이 근처 동료에게 위치를 알린다. 초반에는 혼자 싸우고 일정 시간 뒤부터 부른다.
        if e.ai_can_see and self.frame >= ai.alert_start_seconds * c.fps:
            for ally in self.enemies:
                if (ally is not e and ally.alive and not ally.ai_can_see
                        and math.hypot(ally.x - e.x, ally.y - e.y) <= ai.alert_range):
                    ally.ai_last_seen = (p.x, p.y)
                    ally.ai_last_seen_frame = self.frame
        # 플레이어를 새로 알아챘거나 눈앞에 보이는데 다른 걸 쫓고 있으면 바로 목표를 바꾼다.
        hunting = e.ai_target is not None and e.ai_target[0] in ("player", "point")
        if (e.ai_last_seen is not None and not hunting) or (e.ai_can_see and (e.ai_target or ("",))[0] != "player"):
            e.ai_timer = 0

        # 2) 목표 선택 (reaction_frames마다): 플레이어를 알고 있으면 무조건 사냥, 모를 때만 천체를 깬다
        e.ai_timer -= 1
        if e.ai_timer <= 0:
            e.ai_timer = ai.reaction_frames
            if e.ai_can_see:
                target = ("player", p.id)
            elif e.ai_last_seen is not None:
                target = ("point", e.ai_last_seen)
            else:
                target, best_d = None, float("inf")
                for s in self.shapes:
                    d = math.hypot(s.x - e.x, s.y - e.y)
                    if d < best_d:
                        target, best_d = ("shape", s.id), d
            if target != e.ai_target:
                e.ai_path_timer = 0          # 목표가 바뀌면 경로 즉시 재계산
            e.ai_target = target
            noise = ai.aim_noise_deg * max(0.4, 1 - ai.aim_noise_decay * self.enemy_scale_tier)
            e.ai_aim_offset = float(self.rng.normal(0.0, math.radians(noise)))
            e.ai_strafe = 1.0 if self.rng.random() < 0.5 else -1.0
            if target is None:
                e.ai_move = int(self.rng.integers(0, N_MOVES))

        tgt = self._target_pos(e)
        if tgt is None and e.ai_target is not None and e.ai_target[0] != "player":
            # 쫓던 천체가 (다른 적에게) 부서져 사라졌을 수 있다. 다음 반응 주기까지
            # 기다리지 않고 바로 새 목표를 고르게 해서 구석에 계속 머무르지 않게 한다.
            e.ai_target = None
            e.ai_path = []
            e.ai_timer = 0

        # 3) 이동
        direct = False
        move = e.ai_move if e.ai_target is None else 0
        e.ai_goal = tgt
        if tgt is not None:
            tx, ty = tgt
            kind = e.ai_target[0]
            direct = kind != "point" and tm.segment_fits(e.x, e.y, tx, ty, e.radius)
            if direct:
                # 직접 보이면: 적정 거리 유지 + 옆으로 돌기
                e.ai_path = []
                dx, dy = tx - e.x, ty - e.y
                d = math.hypot(dx, dy) + 1e-6
                keep = ai.keep_distance if kind == "player" else 140.0
                if d > keep + 40:
                    vx, vy = dx / d, dy / d
                elif d < keep - 40:
                    vx, vy = -dx / d, -dy / d
                else:
                    vx, vy = -dy / d * e.ai_strafe, dx / d * e.ai_strafe
            else:
                # 안 보이면: A* 경로를 따라감
                e.ai_path_timer -= 1
                if e.ai_path_timer <= 0:
                    e.ai_path_timer = ai.path_recompute_frames
                    target_tile = tm.tile_of(tx, ty)
                    if not tm.circle_fits(*tm.center(*target_tile), e.radius):
                        safe = tm.navigation_tiles(e.radius)
                        target_tile = min(safe, key=lambda tile: (tm.center(*tile)[0] - tx) ** 2 + (tm.center(*tile)[1] - ty) ** 2) if safe else target_tile
                    e.ai_path = tm.astar(tm.tile_of(e.x, e.y), target_tile, radius=e.radius)
                while e.ai_path:
                    wx, wy = tm.center(*e.ai_path[0])
                    if (wx - e.x) ** 2 + (wy - e.y) ** 2 < ai.waypoint_reach ** 2:
                        e.ai_path.pop(0)
                    else:
                        break
                if e.ai_path:
                    wx, wy = tm.center(*e.ai_path[0])
                    vx, vy = wx - e.x, wy - e.y
                else:
                    vx, vy = 0.0, 0.0
                    if kind == "point" and (tx - e.x) ** 2 + (ty - e.y) ** 2 < (tm.tile * 0.5) ** 2:
                        e.ai_last_seen = None    # 마지막 위치에 왔는데 없음 → 포기
                        e.ai_timer = 0
            move = move_from_vector(vx, vy)

        # 4) 조준/발사: 목표가 시야에 있을 때만 쏜다
        rot = 0
        aligned = False
        if tgt is not None:
            aim_x, aim_y = tgt
            if e.ai_target[0] == "player" and e.ai_can_see and ai.lead_aim:
                # 탄이 날아가는 동안 플레이어가 움직일 위치를 예측해 쏜다.
                speed = self.weapon_values(e)[3] * SHIPS[e.job].shots[0].speed
                lead = min(60.0, math.hypot(p.x - e.x, p.y - e.y) / max(1e-6, speed)) * ai.lead_aim
                aim_x, aim_y = p.x + p.vx * lead, p.y + p.vy * lead
            desired = math.atan2(aim_y - e.y, aim_x - e.x) + e.ai_aim_offset
            diff = wrap_angle(desired - e.angle)
            step = c.turn_speed * ai.turn_speed_scale
            if diff > step:
                rot = 2
            elif diff < -step:
                rot = 1
            aligned = abs(diff) <= math.radians(ai.fire_angle_tol_deg)
        kind = e.ai_target[0] if e.ai_target else None
        can_fire = (kind == "player" and e.ai_can_see) or (kind == "shape" and direct)

        self._apply_tank_control(e, move, rot, ai.move_speed_scale * e.accel_scale, ai.turn_speed_scale)
        self._fire(e, aligned and can_fire)

    def _target_pos(self, e: Tank):
        """적 AI가 현재 추적해야 할 목표 좌표를 조회한다.

        인자:
            e: 목표 정보와 마지막 플레이어 위치를 가진 적 Tank.

        처리:
            1) 목표가 없거나 사라졌는지 확인한다.
            2) 목표 종류에 따라 보이는 플레이어·기억한 위치·지정 지점·천체의 좌표를 선택한다.

        반환:
            tuple[float, float] 또는 None: 목표 월드 좌표(x, y). 유효한 목표 위치가 없으면 None.
        """
        # 1) 목표가 없거나 사라졌는지 확인한다.
        t = e.ai_target
        if t is None:
            return None
        # 2) 목표 종류에 따라 보이는 플레이어·기억한 위치·지정 지점·천체의 좌표를 선택한다.
        kind, val = t
        if kind == "player":
            if not self.player.alive:
                return None
            return (self.player.x, self.player.y) if e.ai_can_see else e.ai_last_seen
        if kind == "point":
            return e.ai_last_seen or val
        for s in self.shapes:
            if s.id == val:
                return (s.x, s.y)
        return None

    # ---------------- 도형/탄환 ----------------
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

    def _move_bullets(self):
        """탄환의 한 프레임 이동과 충돌·수명 만료를 처리한다.

        인자:
            없음(self는 현재 게임 상태를 참조한다).

        처리:
            1) 이전 위치를 기록하고 첫 벽 접촉 지점까지 이동한 뒤 수명을 줄인다.
            2) 이동 구간에서 개체 명중을 먼저 처리하고 벽 충돌 시 파괴 가능 타일에 피해를 준다.
            3) 소멸하지 않은 탄환만 유지하고 체력이 0 이하인 천체를 제거한다.

        반환:
            None: 탄환·천체 목록과 피해·벽·이벤트 상태를 갱신한다.
        """
        tm = self.terrain
        alive = []
        for b in self.bullets:
            # 1) 이전 위치를 기록하고 첫 벽 접촉 지점까지 이동한 뒤 수명을 줄인다.
            b.prev_x, b.prev_y = b.x, b.y
            travel = math.hypot(b.vx, b.vy)
            reach, wall_tile = tm.sweep_circle(b.x, b.y, b.vx / travel, b.vy / travel, travel, b.radius) if travel else (0.0, None)
            b.x += b.vx * reach / travel if travel else 0.0
            b.y += b.vy * reach / travel if travel else 0.0
            b.life -= 1
            # 월드 경계나 벽에 닿는 마지막 구간에서도 첫 대상만 타격한다.
            # 2) 이동 구간에서 개체 명중을 먼저 처리하고 벽 충돌 시 파괴 가능 타일에 피해를 준다.
            if self._bullet_hit(b):
                continue
            if wall_tile is not None:
                col, row = wall_tile
                if 0 <= row < tm.rows and 0 <= col < tm.cols and tm.tiles[row][col] == BREAKABLE:
                    tm.damage_tile(col, row, b.damage)
                continue
            # 3) 소멸하지 않은 탄환만 유지하고 체력이 0 이하인 천체를 제거한다.
            if b.life > 0:
                alive.append(b)
        self.bullets = alive
        self.shapes = [s for s in self.shapes if s.hp > 0]

    def _bullet_hit(self, b: Bullet) -> bool:
        """탄환 이동 구간의 첫 대상에 피해를 주고 탄환 소멸 여부를 결정한다.

        인자:
            b: 이전·현재 위치, 공격 진영, 피해량, 관통 상태를 가진 Bullet.

        처리:
            1) 상대 진영과 천체 중 이미 맞힌 대상을 제외하고 이동 구간과의 교차를 조사한다.
            2) 가장 먼저 닿는 한 대상에 폭발 또는 직접 피해를 적용한다.
            3) 관통이 남으면 횟수를 차감하고 명중 대상을 기록해 탄환을 유지한다.

        반환:
            bool: 명중 후 탄환을 없애야 하면 True, 명중이 없거나 관통으로 유지하면 False.
        """
        # 1) 상대 진영과 천체 중 이미 맞힌 대상을 제외하고 이동 구간과의 교차를 조사한다.
        by_player = b.team == "player"
        targets = self.enemies if by_player else (self.player,)
        hits = []
        sx, sy = (b.prev_x, b.prev_y) if b.prev_x is not None else (b.x, b.y)
        for target in list(targets) + self.shapes:
            if (target.hp <= 0 or (isinstance(target, Tank) and not target.alive)
                    or target.id in b.hit_ids):
                continue
            fraction = _segment_circle_hit(sx, sy, b.x, b.y, target.x, target.y, target.radius + b.radius)
            if fraction is not None:
                hits.append((fraction, target))
        if not hits:
            return False
        # 2) 가장 먼저 닿는 한 대상에 폭발 또는 직접 피해를 적용한다.
        fraction, target = min(hits, key=lambda item: (item[0], item[1].id))
        if b.blast_radius:
            self._explode(sx + (b.x - sx) * fraction, sy + (b.y - sy) * fraction,
                          b.damage, b.blast_radius, b.team)
        elif isinstance(target, Tank):
            self._damage_tank(target, b.damage, by_player)
        else:
            self._damage_shape(target, b.damage, by_player)
        # 3) 관통이 남으면 횟수를 차감하고 명중 대상을 기록해 탄환을 유지한다.
        if b.pierce > 0:
            b.pierce -= 1
            b.hit_ids.add(target.id)
            return False
        return True

    def _damage_tank(self, t: Tank, dmg: float, by_player: bool):
        """선체 피해를 적용하고 피격·처치·엘리트 보상을 처리한다.

        인자:
            t: 피해를 받을 Tank.
            dmg: 선체별 피해 감소 배율 적용 전 피해량.
            by_player: 플레이어 공격으로 준 피해인지 여부.

        처리:
            1) 우주선의 받는 피해 배율을 적용하고 남은 체력만큼 피해를 제한한다.
            2) 체력·마지막 피격 시점과 진영별 피해 이벤트를 갱신한다.
            3) 적이 죽으면 재등장 타이머를 설정하고 플레이어 처치 시 점수·처치 수·엘리트 회복을 적용한다.

        반환:
            None: 선체와 이벤트·보상 상태를 변경한다. 플레이어 사망 확정은 step에서 처리한다.
        """
        # 1) 우주선의 받는 피해 배율을 적용하고 남은 체력만큼 피해를 제한한다.
        dmg *= SHIPS[t.job].damage_taken
        dealt = min(dmg, t.hp)
        if dealt <= 0:
            return
        # 2) 체력·마지막 피격 시점과 진영별 피해 이벤트를 갱신한다.
        t.hp -= dealt
        t.last_hit_frame = self.frame
        if t.team == "player":
            self.events["damage_taken"] += dealt
            return
        if by_player:
            self.events["enemy_damage"] += dealt
        # 3) 적이 죽으면 재등장 타이머를 설정하고 플레이어 처치 시 점수·처치 수·엘리트 회복을 적용한다.
        if t.hp <= 0:
            t.alive = False
            t.respawn_timer = self.cfg.enemy_ai.respawn_frames
            if by_player:
                self.events["enemies_killed"] += 1
                self.kills += 1
                ai, p = self.cfg.enemy_ai, self.player
                if t.elite:
                    p.hp = min(p.max_hp, p.hp + p.max_hp * ai.elite_heal_ratio)
                    self._reward_notice("엘리트 처치 보상 (체력 회복)")
                amount = round(self.cfg.enemy_kill_score * (ai.elite_score_scale if t.elite else 1))
                self._score_popup(t.x, t.y, amount, "elite" if t.elite else "enemy")
                self._add_score(amount)

    def _score_popup(self, x, y, amount, kind):
        """획득 점수를 표시할 화면 연출 기록을 추가한다.

        인자:
            x: 연출을 띄울 월드 가로 좌표(px).
            y: 연출을 띄울 월드 세로 좌표(px).
            amount: 표시할 획득 점수.
            kind: 연출 종류(enemy, elite 또는 천체 종류 키).

        처리:
            1) 새 점수 연출 번호를 발급한다.
            2) 현재 프레임·위치·점수·종류를 연출 목록에 기록한다.

        반환:
            None: score_popups에 기록을 추가한다. 실제 점수는 변경하지 않는다.
        """
        # 1) 새 점수 연출 번호를 발급한다.
        self._popup_id += 1
        # 2) 현재 프레임·위치·점수·종류를 연출 목록에 기록한다.
        self.score_popups.append((self._popup_id, self.frame, x, y, amount, kind))

    def _damage_shape(self, s: Shape, dmg: float, by_player: bool):
        """천체 피해를 적용하고 플레이어 공격의 보상 이벤트를 기록한다.

        인자:
            s: 피해를 받을 Shape.
            dmg: 천체에 적용할 피해량.
            by_player: 플레이어 공격으로 준 피해인지 여부.

        처리:
            1) 피해량을 남은 체력으로 제한하고 천체 체력을 줄인다.
            2) 플레이어 공격이면 가중 피해를 기록하고 파괴 시 점수·파괴 수·점수 연출을 추가한다.

        반환:
            None: 천체 체력과 플레이어 이벤트·점수를 갱신한다. 천체 목록 제거는 호출 측에서 처리한다.
        """
        # 1) 피해량을 남은 체력으로 제한하고 천체 체력을 줄인다.
        dealt = min(dmg, s.hp)
        if dealt <= 0:
            return
        s.hp -= dealt
        # 2) 플레이어 공격이면 가중 피해를 기록하고 파괴 시 점수·파괴 수·점수 연출을 추가한다.
        if by_player:
            self.events["shape_damage_weighted"] += dealt * s.score / s.max_hp
            if s.hp <= 0:
                self.events["shape_destroyed_score"] += s.score
                self.events["shapes_destroyed"] += 1
                self._score_popup(s.x, s.y, s.score, s.kind)
                self._add_score(s.score)

    # ---------------- 몸체 충돌 ----------------
    def _collide_bodies(self):
        """선체와 천체의 몸체 충돌을 해결하고 접촉 피해를 적용한다.

        인자:
            없음(self는 현재 게임 상태를 참조한다).

        처리:
            1) 선체와 천체의 겹침을 해소하고 양쪽에 접촉 피해를 적용한다.
            2) 플레이어와 적은 겹침·상호 피해를 처리하고 적끼리는 겹침만 해소한다.
            3) 파괴된 천체를 제거하고 밀려난 개체의 벽·월드 경계 겹침을 보정한다.

        반환:
            None: 개체 위치·속도·체력, 천체 목록, 피해·보상 이벤트를 변경한다.
        """
        # 1) 선체와 천체의 겹침을 해소하고 양쪽에 접촉 피해를 적용한다.
        bd = self.cfg.body_damage
        tanks = [self.player] + [e for e in self.enemies if e.alive]
        for t in tanks:
            for s in self.shapes:
                r = t.radius + s.radius
                if (s.x - t.x) ** 2 + (s.y - t.y) ** 2 < r * r and s.hp > 0:
                    _push_apart(t, s, 0.3)
                    self._damage_shape(s, bd, by_player=(t.team == "player"))
                    self._damage_tank(t, bd, by_player=False)
        # 2) 플레이어와 적은 겹침·상호 피해를 처리하고 적끼리는 겹침만 해소한다.
        p = self.player
        for e in self.enemies:
            if e.alive and _overlap(p, e):
                _push_apart(p, e, 0.5)
                self._damage_tank(e, bd, by_player=True)
                self._damage_tank(p, bd, by_player=False)
        for i, a in enumerate(self.enemies):
            for b in self.enemies[i + 1:]:
                if a.alive and b.alive and _overlap(a, b):
                    _push_apart(a, b, 0.5)
        # 3) 파괴된 천체를 제거하고 밀려난 개체의 벽·월드 경계 겹침을 보정한다.
        self.shapes = [s for s in self.shapes if s.hp > 0]
        # 서로 밀어내다 벽에 들어간 경우 다시 밖으로. 부서진 벽의 좁은 홈에
        # 끼어 밀어내도 빠지지 않으면 가장 가까운 넓은 칸으로 옮긴다.
        for o in tanks + self.shapes:
            self.terrain.resolve_circle(o)
            self._clamp_to_arena(o)
            self._fit_tank(o)

    def _regen_player(self):
        """피격 후 대기 시간이 지난 플레이어의 체력을 회복한다.

        인자:
            없음(self는 현재 게임 상태를 참조한다).

        처리:
            1) 플레이어가 살아 있고 마지막 피격 후 회복 지연이 지났는지 확인한다.
            2) 최대 체력에 비례한 기본 회복량과 추가 회복량을 더하되 최대 체력을 넘지 않게 한다.

        반환:
            None: 회복 조건을 만족하면 플레이어 체력을 증가시킨다.
        """
        # 1) 플레이어가 살아 있고 마지막 피격 후 회복 지연이 지났는지 확인한다.
        p = self.player
        c = self.cfg
        if p.hp > 0 and self.frame - p.last_hit_frame >= c.regen_delay:
            # 체력(hull 스탯·전직 보너스 등)이 늘어난 만큼 회복량도 비례해서 커진다
            # (기준 체력 대비 같은 비율로 회복 → 최대 체력의 일정 %/초를 유지).
            # 2) 최대 체력에 비례한 기본 회복량과 추가 회복량을 더하되 최대 체력을 넘지 않게 한다.
            rate = c.regen_rate * (p.max_hp / c.player_hp)
            p.hp = min(p.max_hp, p.hp + rate + p.regen_bonus)


def _segment_circle_hit(x0, y0, x1, y1, cx, cy, radius):
    """선분이 원에 처음 닿는 위치를 선분 내 비율로 계산한다.

    인자:
        x0: 선분 시작점의 가로 좌표.
        y0: 선분 시작점의 세로 좌표.
        x1: 선분 끝점의 가로 좌표.
        y1: 선분 끝점의 세로 좌표.
        cx: 원 중심의 가로 좌표.
        cy: 원 중심의 세로 좌표.
        radius: 원 반지름. 탄환 충돌에서는 두 충돌 반지름의 합을 전달한다.

    처리:
        1) 시작점이 원 안이면 즉시 명중으로 처리하고 길이가 거의 0인 선분은 제외한다.
        2) 선분과 원의 교차 방정식을 풀어 첫 교차가 선분 범위 안에 있는지 검사한다.

    반환:
        float 또는 None: 시작점은 0.0, 끝점은 1.0인 첫 명중 비율. 교차하지 않으면 None.
    """
    # 1) 시작점이 원 안이면 즉시 명중으로 처리하고 길이가 거의 0인 선분은 제외한다.
    dx, dy, ox, oy = x1 - x0, y1 - y0, x0 - cx, y0 - cy
    c = ox * ox + oy * oy - radius * radius
    if c <= 0:
        return 0.0
    a = dx * dx + dy * dy
    if a < 1e-12:
        return None
    # 2) 선분과 원의 교차 방정식을 풀어 첫 교차가 선분 범위 안에 있는지 검사한다.
    b = 2 * (ox * dx + oy * dy)
    disc = b * b - 4 * a * c
    if disc < 0:
        return None
    fraction = (-b - math.sqrt(disc)) / (2 * a)
    return fraction if 0 <= fraction <= 1 else None


def _overlap(a, b) -> bool:
    """두 원형 개체가 서로 겹치는지 검사한다.

    인자:
        a: x·y·radius 속성을 가진 첫 개체.
        b: x·y·radius 속성을 가진 두 번째 개체.

    처리:
        중심 간 거리의 제곱과 반지름 합의 제곱을 비교한다.

    반환:
        bool: 내부가 겹치면 True, 떨어져 있거나 정확히 접하기만 하면 False.
    """
    r = a.radius + b.radius
    dx, dy = a.x - b.x, a.y - b.y
    return dx * dx + dy * dy < r * r


def _push_apart(a, b, a_share: float):
    """겹친 두 원형 개체를 비율에 따라 밀어내고 약한 반동을 준다.

    인자:
        a: 위치·반지름·속도를 가진 첫 개체.
        b: 위치·반지름·속도를 가진 두 번째 개체.
        a_share: 전체 보정 중 a의 이동·반동 비율(0~1). b는 나머지를 부담한다.

    처리:
        1) 중심 간 방향과 겹침량을 계산한다. 중심이 거의 같으면 임의의 가로 방향을 사용한다.
        2) 겹침량을 a_share와 나머지 비율로 나눠 두 개체 위치를 보정한다.
        3) 같은 방향·비율로 약한 반동 속도를 더한다. 호출자는 겹친 개체를 전달해야 한다.

    반환:
        None: 두 개체의 위치와 속도를 직접 변경한다.
    """
    # 1) 중심 간 방향과 겹침량을 계산한다. 중심이 거의 같으면 임의의 가로 방향을 사용한다.
    dx, dy = a.x - b.x, a.y - b.y
    d = math.hypot(dx, dy)
    if d < 1e-6:
        dx, dy, d = 1.0, 0.0, 1.0
    overlap = a.radius + b.radius - d
    nx, ny = dx / d, dy / d
    # 2) 겹침량을 a_share와 나머지 비율로 나눠 두 개체 위치를 보정한다.
    a.x += nx * overlap * a_share
    a.y += ny * overlap * a_share
    b.x -= nx * overlap * (1 - a_share)
    b.y -= ny * overlap * (1 - a_share)
    # 밀려나는 방향으로 약한 반동
    # 3) 같은 방향·비율로 약한 반동 속도를 더한다. 호출자는 겹친 개체를 전달해야 한다.
    a.vx += nx * 0.5 * a_share
    a.vy += ny * 0.5 * a_share
    b.vx -= nx * 0.5 * (1 - a_share)
    b.vy -= ny * 0.5 * (1 - a_share)
