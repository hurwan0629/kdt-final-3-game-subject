"""강화학습의 관찰·보상·환경 설정."""
from dataclasses import dataclass


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
