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
    "square":   {"sides": 4, "hp": 10.0,  "score": 10,  "radius": 14, "weight": 0.65},
    "triangle": {"sides": 3, "hp": 25.0,  "score": 25,  "radius": 16, "weight": 0.27},
    "pentagon": {"sides": 5, "hp": 100.0, "score": 130, "radius": 26, "weight": 0.08},
}
SHAPE_KINDS = list(SHAPE_TYPES.keys())
MAX_SHAPE_SCORE = max(t["score"] for t in SHAPE_TYPES.values())
MAX_SHAPE_RADIUS = max(t["radius"] for t in SHAPE_TYPES.values())


@dataclass
class EnemyAIConfig:
    """규칙 기반 적 AI 난이도 파라미터."""
    reaction_frames: int = 20        # 목표/이동 방향을 다시 정하는 주기 (프레임)
    aim_noise_deg: float = 12.0      # 조준 오차 표준편차 (도)
    turn_speed_scale: float = 0.7    # 플레이어 포신 회전 속도 대비 배율
    move_speed_scale: float = 0.8    # 플레이어 가속도 대비 배율
    fire_cooldown: int = 36          # 발사 간격 (프레임)
    fire_angle_tol_deg: float = 15.0 # 조준 오차가 이 값 이내일 때만 발사
    player_priority: float = 1.6     # 플레이어까지 거리를 이 값으로 나눠서 비교 (클수록 플레이어 우선)
    sight_range: float = 450.0       # 이 거리 밖의 플레이어는 무시
    keep_distance: float = 230.0     # 플레이어와 유지하려는 거리
    respawn_frames: int = 300        # 사망 후 재등장까지 프레임 (5초)
    memory_frames: int = 120         # 플레이어를 놓친 뒤 마지막 위치를 기억하는 시간 (2초)
    path_recompute_frames: int = 20  # A* 경로 재계산 주기
    waypoint_reach: float = 14.0     # 경로의 다음 칸 중심에 이만큼 가까워지면 다음 칸으로


@dataclass
class TerrainConfig:
    # 화면 표현: 벽=성운 띠, 수풀=가스 구름, 진흙=중력장, 부서지는 벽=소행성
    enabled: bool = True             # False면 벽 없는 빈 경기장
    tile_size: int = 48              # 기본 맵 템플릿 960x720 → 20x15 타일
    map_name: str = "drift"          # maps/<map_name>.txt (drift / ring / belt)
    map_pool: tuple = ()             # 비어있지 않으면 reset마다 seed로 이 중 하나 선택
    random_map: bool = False         # (2단계) True면 reset마다 랜덤 맵 생성
    random_wall_density: float = 0.06    # 성운
    random_bush_density: float = 0.05    # 가스 구름
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
    world_scale: int = 3             # 2880x2160 월드, 60x45 타일
    camera_zoom: float = 0.6         # 기본 창에서 약 2133x1333 월드 영역 표시
    progression_enabled: bool = True
    level_xp_base: int = 60
    level_xp_growth: int = 40
    fps: int = 60                    # 고정 업데이트 주기 (1프레임 = 1/fps 초)

    # 탱크 공통
    tank_radius: float = 22.0
    barrel_length: float = 38.0
    barrel_width: float = 16.0
    accel: float = 0.35              # px/frame^2
    friction: float = 0.90           # 매 프레임 속도 감쇠 (최대속도 ≈ accel/(1-friction))
    turn_speed: float = 0.07         # rad/frame
    body_damage: float = 0.6         # 접촉 시 프레임당 데미지

    # 플레이어
    player_hp: float = 100.0
    player_fire_cooldown: int = 20
    limited_ammo: bool = True
    player_ammo: int = 120           # 탄창 용량 (예비 탄약은 무제한)
    reload_seconds: float = 2.5
    regen_delay: int = 240           # 마지막 피격 후 회복 시작까지 프레임
    regen_rate: float = 0.05         # 프레임당 회복량

    # 적
    num_enemies: int = 9
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
    num_shapes: int = 72
    shape_drift: float = 0.25        # 도형 표류 속도 최대값
    spawn_margin: float = 40.0
    spawn_min_dist_from_tanks: float = 120.0

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

    SELF_DIM = 9
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
