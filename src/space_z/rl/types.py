"""강화학습 관측값과 reset/step 부가 정보의 구조."""

from typing import TypeAlias, TypedDict

import numpy as np
from numpy.typing import NDArray

from space_z.game.types import CombatEvents

FloatArray: TypeAlias = NDArray[np.float32]


class ObservationDict(TypedDict):
    """vector는 1차원, grid는 (채널, 행, 열) float32 배열이다."""

    vector: FloatArray
    grid: FloatArray


Observation: TypeAlias = FloatArray | ObservationDict


class EnvironmentInfo(TypedDict):
    """reset/step의 info. events와 ammo 키는 값이 None이어도 존재한다."""

    score: int
    kills: int
    map: str
    frames: int
    steps: int
    events: CombatEvents | None
    level: int
    xp: int
    pending_rewards: int
    job: str
    ammo: int | None
    reload_seconds_left: float
    upgrade_points: int
    family: str
    stat_choices: list[str]
    special_reward_levels: list[int]
    stat_levels: dict[str, int]
    special_levels: dict[str, int]
