"""모든 게임/환경 설정값.

값은 dataclass 기본값으로 정의하고, 필요하면 인스턴스를 만들어 일부만 바꿔 쓴다.
    cfg = GameConfig(num_enemies=2)
    env = TankEnv(game_config=cfg, obs_config=ObsConfig(n_enemies=2))
"""
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
    "square":   {"sides": 4, "hp": 10.0,  "score": 10,  "radius": 26, "weight": 0.65},
    "triangle": {"sides": 3, "hp": 25.0,  "score": 25,  "radius": 48, "weight": 0.27},
    "pentagon": {"sides": 5, "hp": 100.0, "score": 130, "radius": 84, "weight": 0.08},
}
SHAPE_KINDS = list(SHAPE_TYPES.keys())
MAX_SHAPE_SCORE = max(t["score"] for t in SHAPE_TYPES.values())
MAX_SHAPE_RADIUS = max(t["radius"] for t in SHAPE_TYPES.values())


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
    hearing_frames: int = 30         # 발사 후 이 시간 동안 소리가 들린다
    alert_range: float = 700.0       # 플레이어를 본 적이 이 거리 안의 동료에게 위치를 알린다
    alert_start_seconds: float = 120.0  # 동료 호출은 게임 시작 후 이 시간이 지나야 켜진다 (초반 난이도 완화)
    # 초반 봐주기: 게임 시작 후 mercy_seconds 동안 적이 아래 배율에서 1.0까지 서서히 강해진다
    mercy_seconds: float = 45.0
    mercy_hp_scale: float = 0.7
    mercy_damage_scale: float = 0.55
    mercy_fire_rate_scale: float = 0.7
    mercy_elite_chance_scale: float = 0.0   # 0이면 mercy_seconds 동안 엘리트가 등장하지 않음
    lead_aim: float = 0.65           # 이동 예측 조준 비율 (0이면 현재 위치를 조준)
    keep_distance: float = 230.0     # 플레이어와 유지하려는 거리
    respawn_frames: int = 300        # 사망 후 재등장까지 프레임 (5초)
    memory_frames: int = 300         # 플레이어를 놓친 뒤 마지막 위치를 기억하는 시간 (5초)
    path_recompute_frames: int = 20  # A* 경로 재계산 주기
    waypoint_reach: float = 14.0     # 경로의 다음 칸 중심에 이만큼 가까워지면 다음 칸으로
    # 시간이 지날수록 강해짐: scale_interval_seconds마다 한 단계 (최대 max_scale_tier)
    scale_interval_seconds: float = 45.0
    max_scale_tier: int = 20
    hp_growth: float = 0.12          # 단계당 최대 체력 +12%
    damage_growth: float = 0.08      # 단계당 공격 피해 +8%
    fire_rate_growth: float = 0.05   # 단계당 발사 속도 +5%
    speed_growth: float = 0.02       # 단계당 이동 가속도 +2%
    min_fire_cooldown: int = 14      # 아무리 강해져도 이보다 빨리 쏘지 않음
    aim_noise_decay: float = 0.04    # 단계당 조준 오차 -4% (최소 40%까지)
    # 엘리트: 등장할 때 elite_chance 확률. 더 단단하고 세며, 잡으면 플레이어 체력 회복
    elite_chance: float = 0.15
    elite_hp_scale: float = 2.5
    elite_damage_scale: float = 1.6
    elite_heal_ratio: float = 0.4    # 처치 시 플레이어 최대 체력의 40% 회복
    elite_score_scale: float = 2.0
    # 적 능력치 강화: 플레이어가 스탯 카드를 찍을 때마다 같은 항목을 적에게도 반영한다.
    # 비율이 1보다 작을수록 적이 플레이어보다 약하게 성장한다(다수이므로).
    stat_mirror_ratio: float = 0.6
    # 적은 가능하면 플레이어 화면 밖에서 (재)생성된다. 화면 경계 바깥으로 이만큼 더 띄운다.
    spawn_offscreen_margin: float = 80.0


@dataclass
class TerrainConfig:
    # 큰 소행성 벽과 넓은 통로. 중력장/파괴 가능한 벽은 선택 기능이다.
    enabled: bool = True             # False면 벽 없는 빈 경기장
    tile_size: int = 48              # 기본 전체 월드 2880x2160 → 60x45 타일
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
    wall_thickness: int = 4
    wall_min_length: int = 6
    wall_max_length: int = 10
    min_passage_tiles: int = 6          # 288px: 반지름 96px 선체와 작은 적이 통과
    navigation_radius: float = 96.0     # 두 배 커진 최종 가디언의 실제 반지름
    random_mud_density: float = 0.03     # 중력장
    random_breakable_density: float = 0.03  # 소행성
    # 2단계 지형 (끄면 진흙은 빈칸, 부서지는 벽은 일반 벽으로 취급)
    mud_enabled: bool = False
    mud_accel_scale: float = 0.5
    breakable_enabled: bool = False
    breakable_hp: float = 40.0


@dataclass
class GameConfig:
    # 맵 원본 크기와 실제 창 크기를 분리한다.
    width: int = 960
    height: int = 720
    window_width: int = 1280
    window_height: int = 800
    world_scale: int = 5              # 4800x3600 전체 미로, 100x75 타일 (기존 2880x2160의 약 1.67배)
    camera_zoom: float = 0.6         # 기본 창에서 약 2133x1333 월드 영역 표시
    progression_enabled: bool = True
    level_xp_base: int = 60
    level_xp_growth: int = 40
    fps: int = 60                    # 고정 업데이트 주기 (1프레임 = 1/fps 초)

    # 탱크 공통
    tank_radius: float = 44.0
    barrel_length: float = 38.0
    barrel_width: float = 16.0
    accel: float = 0.35              # px/frame^2
    friction: float = 0.90           # 매 프레임 속도 감쇠 (최대속도 ≈ accel/(1-friction))
    turn_speed: float = 0.07         # rad/frame
    body_damage: float = 0.6         # 접촉 시 프레임당 데미지

    # 플레이어
    player_hp: float = 100.0
    player_fire_cooldown: int = 28   # 기본 발사 간격 (프레임): 초당 약 2.1발
    limited_ammo: bool = True
    player_ammo: int = 120           # 탄창 용량 (예비 탄약은 무제한)
    reload_seconds: float = 2.5
    regen_delay: int = 240           # 마지막 피격 후 회복 시작까지 프레임
    regen_rate: float = 0.05         # 프레임당 회복량

    # 적
    num_enemies: int = 6             # 적이 똑똑해져서 9 → 6마리
    enemy_hp: float = 60.0
    enemy_ai: EnemyAIConfig = field(default_factory=EnemyAIConfig)
    enemy_kill_score: int = 200

    # 지형
    terrain: TerrainConfig = field(default_factory=TerrainConfig)

    # 탄환
    bullet_speed: float = 9.0
    bullet_radius: float = 6.0
    bullet_life: int = 70
    bullet_damage: float = 7.0
    laser_range: float = 720.0
    dash_speed: float = 18.0

    # 도형
    num_shapes: int = 30             # 천체를 드문드문 (72 → 30개)
    shape_drift: float = 0.25        # 도형 표류 속도 최대값
    spawn_margin: float = 40.0
    spawn_min_dist_from_tanks: float = 120.0
    shape_respawn_dist_from_player: float = 900.0  # 판 도중 새로 생기는 천체는 화면 밖 먼 곳에
    shape_spawn_gap: float = 90.0    # 새 천체는 다른 천체와 최소 이만큼 떨어져서 생긴다 (뭉침 방지)
    shape_spawn_candidates: int = 12 # 후보 위치 수: 그중 다른 천체와 가장 먼 곳에 생겨 뭉치지 않는다

    @property
    def world_width(self) -> int:
        return self.width * self.world_scale

    @property
    def world_height(self) -> int:
        return self.height * self.world_scale

    @property
    def max_speed(self) -> float:
        return self.accel / (1.0 - self.friction)


@dataclass
class ObsConfig:
    n_enemies: int = 3   # N
    n_shapes: int = 8    # M
    n_bullets: int = 8   # K
    grid_size: int = 11  # 내 주변 grid_size x grid_size 타일 (홀수)
    n_rays: int = 0      # 레이캐스트 센서 개수 (0이면 끔)
    ray_max_dist: float = 480.0
    obs_mode: str = "flat"  # "flat": 1차원 배열 / "dict": {"vector", "grid"}

    SELF_DIM = 8
    ENEMY_DIM = 8
    SHAPE_DIM = 6
    BULLET_DIM = 5

    @property
    def vector_size(self) -> int:
        """지형 격자를 제외한 벡터 부분 (레이 포함)."""
        return (self.SELF_DIM + self.n_enemies * self.ENEMY_DIM
                + self.n_shapes * self.SHAPE_DIM + self.n_bullets * self.BULLET_DIM + self.n_rays)

    def grid_shape(self, n_channels: int):
        return (n_channels, self.grid_size, self.grid_size)

    def flat_size(self, n_channels: int) -> int:
        return self.vector_size + n_channels * self.grid_size * self.grid_size


@dataclass
class RewardConfig:
    shape_damage: float = 0.002      # × 준 데미지 × (도형 점수 / 도형 최대 체력)
    shape_destroy: float = 0.01      # × 도형 점수
    enemy_damage: float = 0.01       # × 준 데미지
    enemy_kill: float = 2.0
    damage_taken: float = -0.02      # × 받은 데미지
    death: float = -5.0
    time_step: float = 0.0           # step마다 (생존 보너스/시간 페널티용)


@dataclass
class EnvConfig:
    frame_skip: int = 4              # 1 step = 몇 게임 프레임
    max_steps: int = 3000            # 초과 시 truncated
