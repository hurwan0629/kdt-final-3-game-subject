"""화면 모듈에서 공유하는 색상·배치 및 연출 데이터 계약."""

from typing import TypeAlias, TypedDict

RGB: TypeAlias = tuple[int, int, int]
RectBounds: TypeAlias = tuple[int, int, int, int]
ScorePopup: TypeAlias = tuple[int, int, float, float, int, str]


class Ghost(TypedDict):
    """파괴된 개체의 마지막 위치와 연출 진행 프레임."""

    kind: str
    x: float
    y: float
    r: float
    angle: float
    color: RGB
    age: int


class Palette(TypedDict):
    """단색 RGB 항목과 성운 색상 목록."""

    space_top: RGB
    space_bottom: RGB
    player: RGB
    player_dark: RGB
    enemy: RGB
    enemy_dark: RGB
    elite: RGB
    player_shot: RGB
    enemy_shot: RGB
    square: RGB
    triangle: RGB
    pentagon: RGB
    nebula: list[RGB]
    gravity: RGB
    rock: RGB
    rock_edge: RGB
    text: RGB
    label: RGB
    white: RGB
    panel: RGB
    panel_edge: RGB
    hp_bg: RGB
    minimap_floor: RGB
    minimap_wall: RGB
    minimap_border: RGB
    minimap_player: RGB
