"""적 유형별 기본값. 시간 배율은 생성할 때 GameCore에서 적용한다."""
from dataclasses import dataclass

from progression import ENEMY_SHOTS, SHIPS, ShotSpec


@dataclass(frozen=True)
class EnemyType:
    name: str
    hp: float
    damage: float
    move_speed: float
    score: int
    keep_distance: float
    cooldown: int = 36
    aim_noise: float = 12.0
    bullet_speed: float = 1.0
    bullet_life: float = 1.0
    radius_scale: float = 1.0
    asset: str = "enemies/fighter"
    shot: ShotSpec = ENEMY_SHOTS[1]


ENEMY_TYPES = {
    "basic": EnemyType("기본 추격선", 60, 7, 0.80, 200, 230),
    "assault": EnemyType("경량 돌격선", 45, 6, 1.15, 180, 110,
                         radius_scale=0.8, asset="enemies/scout", shot=ENEMY_SHOTS[0]),
    "sniper": EnemyType("원거리 저격선", 50, 12, 0.65, 250, 360,
                        cooldown=72, aim_noise=3, bullet_speed=1.5, bullet_life=1.3,
                        radius_scale=0.95, asset=SHIPS["sniper"].asset, shot=SHIPS["sniper"].shots[0]),
    "guardian": EnemyType("중장갑 수호선", 120, 8, 0.55, 320, 210,
                          radius_scale=1.3, asset="enemies/heavy", shot=ENEMY_SHOTS[2]),
}
