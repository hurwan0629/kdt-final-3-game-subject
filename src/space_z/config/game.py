"""공통 게임 기본값과 천체 종류 정의."""
import math
from dataclasses import dataclass, field

from .enemy_ai import EnemyAIConfig
from .terrain import TerrainConfig

# --------------------------------------------------------------------------
# 도형 종류: 체력, 점수, 반지름, 꼭짓점 수, 생성 가중치
# --------------------------------------------------------------------------
SCORE_TIMES = 1

SHAPE_TYPES = {
    "square": {  # 사각형 천체
        "sides": 4,      # 꼭짓점 수
        "hp": 10.0,      # 최대 체력
        "score": 10 * SCORE_TIMES,     # 파괴 시 획득 점수
        "radius": 26,    # 충돌 반지름 (px)
        "weight": 0.65,  # 종류 선택 시 상대 생성 가중치
    },
    "triangle": {  # 삼각형 천체
        "sides": 3,      # 꼭짓점 수
        "hp": 25.0,      # 최대 체력
        "score": 25 * SCORE_TIMES,     # 파괴 시 획득 점수
        "radius": 48,    # 충돌 반지름 (px)
        "weight": 0.27,  # 종류 선택 시 상대 생성 가중치
    },
    "pentagon": {  # 오각형 천체
        "sides": 5,      # 꼭짓점 수
        "hp": 100.0,     # 최대 체력
        "score": 130 * SCORE_TIMES,    # 파괴 시 획득 점수
        "radius": 84,    # 충돌 반지름 (px)
        "weight": 0.08,  # 종류 선택 시 상대 생성 가중치
    },
}
SHAPE_KINDS = list(SHAPE_TYPES.keys())  # 생성 가능한 천체 종류 목록
MAX_SHAPE_SCORE = max(t["score"] for t in SHAPE_TYPES.values())  # 관찰 정규화용 최대 천체 점수
MAX_SHAPE_RADIUS = max(t["radius"] for t in SHAPE_TYPES.values())  # 관찰 정규화용 최대 천체 반지름



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
