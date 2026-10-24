"""게임 모듈 사이에서 공유하는 데이터 계약. 실행 중 dict·tuple 형태는 유지한다."""

from typing import Literal, TypeAlias, TypedDict

from space_z.config.progression_definitions import ShotSpec

WorldPoint: TypeAlias = tuple[float, float]  # 월드 px 좌표
TilePosition: TypeAlias = tuple[int, int]  # 타일 (열, 행)
AITarget: TypeAlias = (
    tuple[Literal["player"], int]
    | tuple[Literal["shape"], int]
    | tuple[Literal["point"], WorldPoint]
)
PendingShot: TypeAlias = tuple[int, ShotSpec, float, float, int]
ScoreAward: TypeAlias = tuple[int, float, float, int, str]
# 예약 발사: (프레임, 발사 명세, 피해, px/frame, 수명 프레임)
# 점수 획득: (프레임, 월드 x, 월드 y, 점수, 대상 종류)


class CombatEvents(TypedDict):
    """pop_events()로 전달하는 플레이어 관점의 전투 누적값."""

    shape_damage_weighted: float
    shape_destroyed_score: float
    shapes_destroyed: int
    enemy_damage: float
    enemies_killed: int
    damage_taken: float
    died: bool
