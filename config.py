"""모든 게임/환경 설정값.

값은 dataclass 기본값으로 정의하고, 필요하면 인스턴스를 만들어 일부만 바꿔 쓴다.
    cfg = GameConfig(num_enemies=2)
    env = TankEnv(game_config=cfg, obs_config=ObsConfig(n_enemies=2))
"""
import math
import os
import sys
from dataclasses import dataclass, field


def resource_path(relative: str) -> str:
    """PyInstaller 실행 파일(_MEIPASS)과 일반 실행 모두에서 동작하는 리소스 경로."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, relative)


# --------------------------------------------------------------------------
# 도형 종류: 체력, 점수, 반지름, 꼭짓점 수, 생성 가중치
# --------------------------------------------------------------------------
SHAPE_TYPES = {
    "square": {  # 사각형 천체
        "sides": 4,      # 꼭짓점 수
        "hp": 10.0,      # 최대 체력
        "score": 10,     # 파괴 시 획득 점수
        "radius": 26,    # 충돌 반지름 (px)
        "weight": 0.65,  # 종류 선택 시 상대 생성 가중치
    },
    "triangle": {  # 삼각형 천체
        "sides": 3,      # 꼭짓점 수
        "hp": 25.0,      # 최대 체력
        "score": 25,     # 파괴 시 획득 점수
        "radius": 48,    # 충돌 반지름 (px)
        "weight": 0.27,  # 종류 선택 시 상대 생성 가중치
    },
    "pentagon": {  # 오각형 천체
        "sides": 5,      # 꼭짓점 수
        "hp": 100.0,     # 최대 체력
        "score": 130,    # 파괴 시 획득 점수
        "radius": 84,    # 충돌 반지름 (px)
        "weight": 0.08,  # 종류 선택 시 상대 생성 가중치
    },
}
SHAPE_KINDS = list(SHAPE_TYPES.keys())  # 생성 가능한 천체 종류 목록
MAX_SHAPE_SCORE = max(t["score"] for t in SHAPE_TYPES.values())  # 관찰 정규화용 최대 천체 점수
MAX_SHAPE_RADIUS = max(t["radius"] for t in SHAPE_TYPES.values())  # 관찰 정규화용 최대 천체 반지름


@dataclass
class EnemyAIConfig:
    """규칙 기반 적 AI 난이도 파라미터."""
    reaction_frames: int = 20        # 목표/이동 방향을 다시 정하는 주기 (프레임)
    aim_noise_deg: float = 13.5      # 조준 오차 표준편차 (도)
    turn_speed_scale: float = 0.7    # 플레이어 포신 회전 속도 대비 배율
    move_speed_scale: float = 0.8    # 플레이어 가속도 대비 배율
    fire_cooldown: int = 39          # 발사 간격 (프레임)
    fire_angle_tol_deg: float = 15.0 # 조준 오차가 이 값 이내일 때만 발사
    sight_range: float = 750.0       # 시야선이 트였을 때 플레이어를 보는 거리
    sense_range: float = 340.0       # 이 거리 안이면 벽 너머의 플레이어도 알아챈다
    hearing_range: float = 850.0     # 플레이어가 쏘면 이 거리 안의 적은 위치를 알아챈다
    hearing_frames: int = 30         # 발사 소리가 유지되는 시간 (프레임)
    alert_range: float = 700.0       # 플레이어를 본 적이 이 거리 안의 동료에게 위치를 알린다
    alert_start_seconds: float = 120.0  # 동료 호출은 게임 시작 후 이 시간이 지나야 켜진다 (초반 난이도 완화)
    # 초반 봐주기: 게임 시작 후 mercy_seconds 동안 적이 아래 배율에서 1.0까지 서서히 강해진다
    mercy_seconds: float = 45.0      # 초반 약화가 정상 배율로 돌아오는 시간 (초)
    mercy_hp_scale: float = 0.7      # 게임 시작 시 적 최대 체력 배율
    mercy_damage_scale: float = 0.55  # 게임 시작 시 적 공격 피해 배율
    mercy_fire_rate_scale: float = 0.7  # 게임 시작 시 적 발사 속도 배율
    mercy_elite_chance_scale: float = 0.0  # 게임 시작 시 엘리트 확률 배율 (이후 1.0까지 증가)
    lead_aim: float = 0.65           # 이동 예측 조준 비율 (0이면 현재 위치를 조준)
    keep_distance: float = 230.0     # 플레이어와 유지하려는 거리
    respawn_frames: int = 300        # 사망 후 재등장까지 프레임 (5초)
    memory_frames: int = 300         # 플레이어를 놓친 뒤 마지막 위치를 기억하는 시간 (5초)
    path_recompute_frames: int = 20  # A* 경로 재계산 주기
    waypoint_reach: float = 14.0     # 경로의 다음 칸 중심에 이만큼 가까워지면 다음 칸으로
    # 시간이 지날수록 강해짐: scale_interval_seconds마다 한 단계 (최대 max_scale_tier)
    scale_interval_seconds: float = 45.0  # 적 성장 단계가 오르는 간격 (초)
    max_scale_tier: int = 20         # 적 성장 단계 상한
    hp_growth: float = 0.12          # 단계당 최대 체력 +12%
    damage_growth: float = 0.08      # 단계당 공격 피해 +8%
    fire_rate_growth: float = 0.05   # 단계당 발사 속도 +5%
    speed_growth: float = 0.02       # 단계당 이동 가속도 +2%
    min_fire_cooldown: int = 14      # 아무리 강해져도 이보다 빨리 쏘지 않음
    aim_noise_decay: float = 0.04    # 단계당 조준 오차 -4% (최소 40%까지)
    # 엘리트: 등장할 때 elite_chance 확률. 더 단단하고 세며, 잡으면 플레이어 체력 회복
    elite_chance: float = 0.15       # 적 등장 시 엘리트가 될 기본 확률 (0~1)
    elite_hp_scale: float = 2.5      # 엘리트 최대 체력 배율
    elite_damage_scale: float = 1.6  # 엘리트 공격 피해 배율
    elite_heal_ratio: float = 0.4    # 처치 시 플레이어 최대 체력의 40% 회복
    elite_score_scale: float = 2.0   # 엘리트 처치 점수 배율
    # 플레이어 스탯 투자량의 일부를 적의 강화 포인트로 삼아 항목별로 무작위 배분한다.
    stat_mirror_ratio: float = 0.6   # 플레이어 투자량 대비 적 강화 포인트 비율


@dataclass
class TerrainConfig:
    # 큰 소행성 벽과 넓은 통로. 중력장/파괴 가능한 벽은 선택 기능이다.
    enabled: bool = True             # False면 벽 없는 빈 경기장
    tile_size: int = 48              # 지형 타일 한 변 길이 (px)
    map_name: str = "drift"          # maps/<map_name>.txt (drift / ring / belt)
    map_pool: tuple = ()             # 비어있지 않으면 reset마다 seed로 이 중 하나 선택
    random_map: bool = True          # True면 reset마다 랜덤 블록 지형, False면 map_name 미로
    # 랜덤 지형 (diep.io 미로 모드 느낌): 큰 블록 격자 미로에서 벽 일부를 뚫는다
    block_tiles: int = 8                 # 블록 한 변 (8칸 = 384px, 통로/벽 폭 — 더 개방감 있게)
    extra_openings: float = 0.6          # 미로에서 막힌 연결 벽을 추가로 뚫는 비율 (클수록 덜 갑갑)
    pillar_removal: float = 0.5          # 벽 기둥을 없애 넓은 공간을 만드는 비율
    wall_merge: float = 0.0              # 벽 옆 바닥 블록을 메워 큰 벽 덩어리를 만드는 비율
    # 0보다 크면 가끔 ㄱ/ㄷ자처럼 꺾인 벽 덩어리가 생긴다. 각진 미로 느낌보다
    # 단순한 사각 장애물이 흩어진 느낌을 원해서 기본은 끈다.
    random_wall_density: float = 0.14    # 이전 설정 호환용: 미로 밀도는 통로/벽 두께로 결정
    wall_thickness: int = 4             # 방 기반 미로 생성기의 벽 두께 (타일)
    wall_min_length: int = 6            # 벽 최소 길이 (타일, 현재 생성기에서 미사용)
    wall_max_length: int = 10           # 벽 최대 길이 (타일, 현재 생성기에서 미사용)
    min_passage_tiles: int = 6          # 288px: 반지름 96px 선체와 작은 적이 통과
    navigation_radius: float = 96.0     # 두 배 커진 최종 가디언의 실제 반지름
    random_mud_density: float = 0.03     # 랜덤 중력장 생성 밀도 (mud_enabled일 때)
    random_breakable_density: float = 0.03  # 랜덤 파괴 가능 벽 생성 밀도 (breakable_enabled일 때)
    # 2단계 지형 (끄면 진흙은 빈칸, 부서지는 벽은 일반 벽으로 취급)
    mud_enabled: bool = False           # 중력장 지형 활성화 여부
    mud_accel_scale: float = 0.5         # 중력장 안에서의 이동 가속도 배율
    breakable_enabled: bool = False     # 파괴 가능한 벽 활성화 여부
    breakable_hp: float = 40.0          # 파괴 가능한 벽 타일당 체력


@dataclass
class GameConfig:
    # 맵 원본 크기와 실제 창 크기를 분리한다.
    width: int = 960                 # 월드 크기 계산의 기준 가로 길이 (px)
    height: int = 720                # 월드 크기 계산의 기준 세로 길이 (px)
    window_width: int = 1280         # 게임 창 가로 길이 (px)
    window_height: int = 800         # 게임 창 세로 길이 (px)
    world_scale: int = 5              # 면적 배율 적용 전 기준 월드: 4800x3600
    world_area_scale: float = 1.8    # 가로·세로 비율을 유지하며 기존 월드 면적의 약 1.8배
    camera_zoom: float = 0.6         # 기본 창에서 약 2133x1333 월드 영역 표시
    progression_enabled: bool = True  # 경험치·레벨업·보상 선택 활성화 여부
    level_xp_base: int = 60          # 첫 레벨업에 필요한 경험치
    level_xp_growth: int = 40        # 레벨당 추가되는 필요 경험치
    fps: int = 60                    # 고정 업데이트 주기 (1프레임 = 1/fps 초)

    # 탱크 공통
    tank_radius: float = 44.0        # 기본 선체 충돌 반지름 (px)
    barrel_length: float = 38.0      # 포신 길이 (px, 현재 미사용)
    barrel_width: float = 16.0       # 포신 너비 (px, 현재 미사용)
    accel: float = 0.35              # 기본 이동 가속도 (px/frame^2)
    friction: float = 0.90           # 매 프레임 속도 감쇠 (최대속도 ≈ accel/(1-friction))
    turn_speed: float = 0.07         # 포신 회전 속도 (rad/frame)
    body_damage: float = 0.6         # 접촉 시 프레임당 데미지

    # 플레이어
    player_hp: float = 100.0         # 플레이어 기본 최대 체력
    player_fire_cooldown: int = 28   # 기본 발사 간격 (프레임): 초당 약 2.1발
    limited_ammo: bool = True        # 탄약 제한 여부 (False면 재장전 불필요, main.py 기본값은 False)
    player_ammo: int = 120           # limited_ammo=True일 때만 쓰는 탄창 용량
    reload_seconds: float = 2.5      # 기본 재장전 소요 시간 (초)
    regen_delay: int = 240           # 마지막 피격 후 회복 시작까지 프레임
    regen_rate: float = 0.05         # 프레임당 회복량

    # 적
    num_enemies: int = 9             # 동시에 유지할 적 수
    enemy_hp: float = 60.0           # 적 기본 최대 체력
    enemy_ai: EnemyAIConfig = field(default_factory=EnemyAIConfig)  # 적 행동·성장·엘리트 설정
    enemy_kill_score: int = 200      # 일반 적 처치 시 획득 점수

    # 지형
    terrain: TerrainConfig = field(default_factory=TerrainConfig)  # 지형 생성·충돌 관련 설정

    # 탄환
    bullet_speed: float = 9.0        # 기본 탄환 이동 속도 (px/frame)
    bullet_radius: float = 6.0       # 기본 탄환 충돌 반지름 (px)
    bullet_life: int = 70            # 기본 탄환 생존 시간 (프레임)
    bullet_damage: float = 7.0       # 기본 탄환 명중 피해량
    laser_range: float = 720.0       # 레이저 사거리 (px, 현재 미사용)
    dash_speed: float = 18.0         # 돌진 속도 (px/frame, 현재 미사용)

    # 도형
    num_shapes: int = 30             # 동시에 유지할 천체 수
    shape_drift: float = 0.25        # 천체 초기 표류 속도 상한 (px/frame)
    spawn_margin: float = 40.0       # 생성 위치의 맵 가장자리 여백 (px, 현재 미사용)
    spawn_min_dist_from_tanks: float = 120.0  # 천체 생성 시 선체 중심과의 목표 최소 거리 (px)
    shape_respawn_dist_from_player: float = 900.0  # 판 도중 새로 생기는 천체는 화면 밖 먼 곳에
    shape_spawn_gap: float = 90.0    # 새 천체는 다른 천체와 최소 이만큼 떨어져서 생긴다 (뭉침 방지)
    shape_spawn_candidates: int = 12 # 후보 위치 수: 그중 다른 천체와 가장 먼 곳에 생겨 뭉치지 않는다

    @property
    def world_cols(self) -> int:  # 월드 가로 타일 수 (크기·면적 배율 반영)
        return max(1, round(self.width * self.world_scale * math.sqrt(self.world_area_scale)
                            / self.terrain.tile_size))

    @property
    def world_rows(self) -> int:  # 월드 세로 타일 수 (크기·면적 배율 반영)
        return max(1, round(self.height * self.world_scale * math.sqrt(self.world_area_scale)
                            / self.terrain.tile_size))

    @property
    def world_width(self) -> int:  # 타일 크기에 맞춘 실제 월드 가로 길이 (px)
        return self.world_cols * self.terrain.tile_size

    @property
    def world_height(self) -> int:  # 타일 크기에 맞춘 실제 월드 세로 길이 (px)
        return self.world_rows * self.terrain.tile_size

    @property
    def max_speed(self) -> float:  # 기본 가속도·마찰로 계산한 속도 정규화 기준 (px/frame)
        return self.accel / (1.0 - self.friction)


@dataclass
class ObsConfig:
    n_enemies: int = 3   # 관찰에 포함할 가까운 적의 최대 수
    n_shapes: int = 8    # 관찰에 포함할 가까운 천체의 최대 수
    n_bullets: int = 8   # 관찰에 포함할 가까운 적 탄환의 최대 수
    grid_size: int = 11  # 내 주변 grid_size x grid_size 타일 (홀수)
    n_rays: int = 0      # 레이캐스트 센서 개수 (0이면 끔)
    ray_max_dist: float = 480.0  # 레이캐스트 센서 최대 탐지 거리 (px)
    obs_mode: str = "flat"  # "flat": 1차원 배열 / "dict": {"vector", "grid"}

    SELF_DIM = 8    # 플레이어 관찰 벡터 길이
    ENEMY_DIM = 8   # 적 한 개체의 관찰 벡터 길이
    SHAPE_DIM = 6   # 천체 한 개체의 관찰 벡터 길이
    BULLET_DIM = 5  # 적 탄환 한 발의 관찰 벡터 길이

    @property
    def vector_size(self) -> int:  # 지형 격자를 제외한 전체 관찰 벡터 길이
        """지형 격자를 제외한 벡터 부분 (레이 포함)."""
        return (self.SELF_DIM + self.n_enemies * self.ENEMY_DIM
                + self.n_shapes * self.SHAPE_DIM + self.n_bullets * self.BULLET_DIM + self.n_rays)

    def grid_shape(self, n_channels: int):  # 지형 격자 배열 크기 (채널, 세로, 가로)
        return (n_channels, self.grid_size, self.grid_size)

    def flat_size(self, n_channels: int) -> int:  # 벡터와 지형 격자를 펼쳐 합친 관찰 길이
        return self.vector_size + n_channels * self.grid_size * self.grid_size


@dataclass
class RewardConfig:
    shape_damage: float = 0.002      # 천체 피해 보상 계수: 피해량 × (점수 / 최대 체력)에 곱함
    shape_destroy: float = 0.01      # 천체 파괴 보상 계수: 파괴한 천체 점수에 곱함
    enemy_damage: float = 0.01       # 적 피해 보상 계수: 적에게 준 피해량에 곱함
    enemy_kill: float = 2.0          # 적 한 대 처치 시 보상
    damage_taken: float = -0.02      # 피격 보상 계수: 받은 피해량에 곱함 (음수면 페널티)
    death: float = -5.0              # 플레이어 사망 시 보상 (음수면 페널티)
    time_step: float = 0.0           # step마다 (생존 보너스/시간 페널티용)


@dataclass
class EnvConfig:
    frame_skip: int = 4              # 1 step = 몇 게임 프레임
    max_steps: int = 3000            # 에피소드 최대 step 수 (도달 시 truncated=True)
