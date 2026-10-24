"""타일 기반 지형. pygame에 의존하지 않는다.

- 맵 텍스트 파싱/검증, 랜덤 맵 생성 (+BFS 연결성 검증)
- 원 ↔ 벽 충돌 (벽을 따라 미끄러짐), 시야선/레이캐스트 (격자 DDA), A* 경로 탐색
"""

import heapq
import math
import os
from collections import deque

import numpy as np

from space_z.config import TerrainConfig
from space_z.resource_paths import resource_path

EMPTY, WALL, MUD, BREAKABLE = 0, 1, 3, 4
CHAR_TO_TILE = {".": EMPTY, "#": WALL, "~": MUD, "+": BREAKABLE, "P": EMPTY, "E": EMPTY}
TILE_TO_CHAR = {EMPTY: ".", WALL: "#", MUD: "~", BREAKABLE: "+"}

# 8방향 이웃 (dc, dr, 비용)
_NEIGHBORS = [
    (1, 0, 1.0),
    (-1, 0, 1.0),
    (0, 1, 1.0),
    (0, -1, 1.0),
    (1, 1, math.sqrt(2)),
    (1, -1, math.sqrt(2)),
    (-1, 1, math.sqrt(2)),
    (-1, -1, math.sqrt(2)),
]


class MapError(ValueError):
    pass


def grid_channels(terrain_config: TerrainConfig):
    """관찰 격자에 들어가는 지형 채널 이름 (설정에 따라 고정)."""

    # 활성화된 지형 기능에 맞춰 관측 채널 목록을 구성한다.
    channels = ["wall"]
    if terrain_config.mud_enabled:
        channels.append("mud")
    if terrain_config.breakable_enabled:
        channels.append("breakable")
    return channels


def list_maps():
    # 리소스 폴더에서 사용할 수 있는 맵 파일 이름을 찾는다.
    maps_directory = resource_path("maps")
    if not os.path.isdir(maps_directory):
        return []
    return sorted(
        filename[:-4]
        for filename in os.listdir(maps_directory)
        if filename.endswith(".txt")
    )


class TileMap:
    def __init__(
        self,
        tiles,
        tile_size,
        player_start,
        enemy_starts,
        name,
        terrain_config: TerrainConfig,
    ):
        self.rows = len(tiles)
        self.cols = len(tiles[0])
        self.tile = tile_size
        self.name = name
        self.player_start = player_start  # (col, row)
        self.enemy_starts = list(enemy_starts)  # [(col, row), ...]
        self.breakable_hp_max = terrain_config.breakable_hp
        # 설정에서 끈 기능은 해당 타일을 일반 타일로 취급
        tile_conversion = {
            MUD: MUD if terrain_config.mud_enabled else EMPTY,
            BREAKABLE: BREAKABLE if terrain_config.breakable_enabled else WALL,
        }
        self.tiles = [
            [tile_conversion.get(tile_code, tile_code) for tile_code in row]
            for row in tiles
        ]
        self.hp = {
            (col, row_index): terrain_config.breakable_hp
            for row_index in range(self.rows)
            for col in range(self.cols)
            if self.tiles[row_index][col] == BREAKABLE
        }
        self.version = 0  # 지형이 바뀔 때마다 증가 (렌더러/관찰 캐시 무효화용)
        self._refresh()

    def _refresh(self):
        # 지형 변경으로 유효하지 않게 된 경로·이동 구간 캐시를 비운다.
        self._navigation_cache = {}
        self._segment_cache = {}

        # 벽 타일과 벽 주변 타일을 다시 표시한다.
        self.solid = [
            [tile_code in (WALL, BREAKABLE) for tile_code in row] for row in self.tiles
        ]
        self.has_solid = any(any(row) for row in self.solid)
        # 자신/주변 8칸(맵 바깥 포함)에 막힌 칸이 있는지. 물체 반지름 < 타일 크기라
        # 이 값이 False인 칸에 중심이 있으면 벽 충돌 검사를 건너뛸 수 있다.
        self.near_solid = [
            [
                any(
                    self.is_solid_tile(col + delta_col, row_index + delta_row)
                    for delta_col in (-1, 0, 1)
                    for delta_row in (-1, 0, 1)
                )
                for col in range(self.cols)
            ]
            for row_index in range(self.rows)
        ]

        # 빈 타일과 큰 개체 생성에 사용할 여유 있는 타일을 수집한다.
        self.free_tiles = [
            (col, row_index)
            for row_index in range(self.rows)
            for col in range(self.cols)
            if not self.solid[row_index][col]
        ]
        # 사방이 막히지 않은 칸 (큰 도형 스폰용)
        self.open_tiles = [
            (col, row_index)
            for col, row_index in self.free_tiles
            if all(
                not self.is_solid_tile(col + delta_col, row_index + delta_row)
                for delta_col, delta_row in ((1, 0), (-1, 0), (0, 1), (0, -1))
            )
        ]
        self.version += 1

    # ---------------- 조회 ----------------
    def is_solid_tile(self, col, row):
        return (
            col < 0
            or row < 0
            or col >= self.cols
            or row >= self.rows
            or self.solid[row][col]
        )

    def tile_of(self, x, y):
        return int(x // self.tile), int(y // self.tile)

    def tile_at(self, x, y):
        col, row = int(x // self.tile), int(y // self.tile)
        if col < 0 or row < 0 or col >= self.cols or row >= self.rows:
            return WALL
        return self.tiles[row][col]

    def is_solid_at(self, x, y):
        return self.is_solid_tile(int(x // self.tile), int(y // self.tile))

    def center(self, col, row):
        return (col + 0.5) * self.tile, (row + 0.5) * self.tile

    def as_array(self):
        return np.array(self.tiles, dtype=np.int8)

    # ---------------- 선체 여유 ----------------
    def circle_fits(self, x, y, radius):
        """경계/벽과 겹치지 않는 원인지 검사한다. 정확히 닿는 것은 허용한다."""

        # 반지름과 월드 경계를 검사해 배치할 수 없는 원을 걸러낸다.
        if radius < 0:
            raise ValueError("선체 반지름은 0 이상이어야 합니다.")
        tolerance = 1e-7
        if (
            x < radius - tolerance
            or y < radius - tolerance
            or x > self.cols * self.tile - radius + tolerance
            or y > self.rows * self.tile - radius + tolerance
        ):
            return False
        if radius == 0:
            return not self.is_solid_at(x, y)
        if not self.has_solid:
            return True

        # 원 주변에서 충돌 가능성이 있는 타일 범위를 구한다.
        tile_size, radius_squared = self.tile, radius * radius
        col, row = int(x // tile_size), int(y // tile_size)
        if (
            radius < tile_size
            and 0 <= col < self.cols
            and 0 <= row < self.rows
            and not self.near_solid[row][col]
        ):
            return True
        first_col, last_col = (
            max(0, int((x - radius) // tile_size)),
            min(self.cols - 1, int((x + radius) // tile_size)),
        )
        first_row, last_row = (
            max(0, int((y - radius) // tile_size)),
            min(self.rows - 1, int((y + radius) // tile_size)),
        )

        # 가까운 벽 타일과 원이 실제로 겹치는지 확인한다.
        for tile_row in range(first_row, last_row + 1):
            for tile_col in range(first_col, last_col + 1):
                if not self.solid[tile_row][tile_col]:
                    continue
                delta_x = x - min(
                    max(x, tile_col * tile_size), (tile_col + 1) * tile_size
                )
                delta_y = y - min(
                    max(y, tile_row * tile_size), (tile_row + 1) * tile_size
                )
                if delta_x * delta_x + delta_y * delta_y < radius_squared - tolerance:
                    return False
        return True

    def segment_fits(self, start_x, start_y, end_x, end_y, radius):
        """원형 선체가 선분 전체를 이동할 수 있는지 검사한다. 시야선보다 넓은 여유를 쓴다."""

        # 이동의 시작점과 끝점에 선체가 들어갈 수 있는지 확인한다.
        if not self.circle_fits(start_x, start_y, radius) or not self.circle_fits(
            end_x, end_y, radius
        ):
            return False
        if not self.has_solid:
            return True
        delta_x, delta_y = end_x - start_x, end_y - start_y
        length_squared = delta_x * delta_x + delta_y * delta_y
        if length_squared < 1e-12:
            return True

        # 선체 이동 구간 주변에서 검사할 타일 범위를 구한다.
        tile_size, radius_squared = self.tile, radius * radius
        first_col = max(0, int((min(start_x, end_x) - radius) // tile_size))
        last_col = min(self.cols - 1, int((max(start_x, end_x) + radius) // tile_size))
        first_row = max(0, int((min(start_y, end_y) - radius) // tile_size))
        last_row = min(self.rows - 1, int((max(start_y, end_y) + radius) // tile_size))

        # 이동 선분과 주변 벽 사이에 선체 반지름만큼 여유가 있는지 확인한다.
        for row in range(first_row, last_row + 1):
            for col in range(first_col, last_col + 1):
                if not self.solid[row][col]:
                    continue
                left, right, top, bottom = (
                    col * tile_size,
                    (col + 1) * tile_size,
                    row * tile_size,
                    (row + 1) * tile_size,
                )
                # 선분 자체와 사각형의 교차: slab clipping.
                entry_fraction, exit_fraction = 0.0, 1.0
                for origin, delta, low, high in (
                    (start_x, delta_x, left, right),
                    (start_y, delta_y, top, bottom),
                ):
                    if abs(delta) < 1e-12:
                        if origin < low or origin > high:
                            entry_fraction, exit_fraction = 1.0, 0.0
                            break
                    else:
                        first_fraction, second_fraction = (
                            (low - origin) / delta,
                            (high - origin) / delta,
                        )
                        entry_fraction, exit_fraction = (
                            max(entry_fraction, min(first_fraction, second_fraction)),
                            min(exit_fraction, max(first_fraction, second_fraction)),
                        )
                if entry_fraction <= exit_fraction:
                    return False
                if radius == 0:
                    continue
                # 비교할 최소 거리는 끝점→벽, 모서리→선분 중 하나다.
                distance_squared = min(
                    (point_x - min(max(point_x, left), right)) ** 2
                    + (point_y - min(max(point_y, top), bottom)) ** 2
                    for point_x, point_y in ((start_x, start_y), (end_x, end_y))
                )
                for center_x, center_y in (
                    (left, top),
                    (left, bottom),
                    (right, top),
                    (right, bottom),
                ):
                    projection_fraction = min(
                        1.0,
                        max(
                            0.0,
                            (
                                (center_x - start_x) * delta_x
                                + (center_y - start_y) * delta_y
                            )
                            / length_squared,
                        ),
                    )
                    distance_squared = min(
                        distance_squared,
                        (center_x - start_x - projection_fraction * delta_x) ** 2
                        + (center_y - start_y - projection_fraction * delta_y) ** 2,
                    )
                if distance_squared < radius_squared - 1e-7:
                    return False
        return True

    def sweep_circle(self, x, y, delta_x, delta_y, max_distance, radius):
        """단위 방향으로 움직이는 원의 첫 벽 접촉 (거리, 타일). 없으면 (거리한도, None).

        벽 사각형에 반지름을 더한 둥근 사각형과 ray를 정확히 교차시킨다.
        모서리도 원으로 검사하므로 중심선이 벽을 비껴가는 탄환을 놓치지 않는다.
        경계 충돌의 타일 좌표는 맵 바깥의 한 칸이다.
        """

        # 충돌 검사 입력을 확인하고 이동 방향의 길이를 정규화한다.
        if radius < 0 or max_distance < 0:
            raise ValueError("반지름과 이동 거리는 0 이상이어야 합니다.")
        direction_length_squared = delta_x * delta_x + delta_y * delta_y
        if direction_length_squared > 0 and abs(direction_length_squared - 1.0) > 1e-9:
            length = math.sqrt(direction_length_squared)
            delta_x, delta_y, direction_length_squared = (
                delta_x / length,
                delta_y / length,
                1.0,
            )

        # 현재까지의 가장 가까운 충돌 거리와 맵 경계를 준비한다.
        best, hit_tile = float(max_distance), None
        width, height, tile = self.cols * self.tile, self.rows * self.tile, self.tile
        tolerance = 1e-9

        def consider(distance, cell):
            nonlocal best, hit_tile
            if -tolerance <= distance <= best + tolerance:
                distance = max(0.0, min(float(max_distance), distance))
                if hit_tile is None or distance < best - tolerance:
                    best, hit_tile = distance, cell

        # 선체 중심이 경계를 넘기 전에 반지름만큼 먼저 닿는다.
        for origin, direction, low, high, vertical in (
            (x, delta_x, radius, width - radius, True),
            (y, delta_y, radius, height - radius, False),
        ):
            if origin < low - tolerance:
                distance, side = 0.0, -1
            elif origin > high + tolerance:
                distance, side = 0.0, self.cols if vertical else self.rows
            elif direction < -tolerance:
                distance, side = (low - origin) / direction, -1
            elif direction > tolerance:
                distance, side = (
                    (high - origin) / direction,
                    self.cols if vertical else self.rows,
                )
            else:
                continue
            other = y + delta_y * distance if vertical else x + delta_x * distance
            other_cell = min(
                (self.rows if vertical else self.cols) - 1, max(0, int(other // tile))
            )
            consider(distance, (side, other_cell) if vertical else (other_cell, side))
        if not self.has_solid:
            return best, hit_tile

        def ray_box(left, top, right, bottom):
            # 광선이 사각형 내부에 머무는 진입·이탈 거리 범위를 구한다.
            enter, leave = 0.0, best
            for origin, direction, low, high in (
                (x, delta_x, left, right),
                (y, delta_y, top, bottom),
            ):
                if abs(direction) < 1e-12:
                    if origin < low or origin > high:
                        return None
                else:
                    first_distance, second_distance = (
                        (low - origin) / direction,
                        (high - origin) / direction,
                    )
                    enter, leave = (
                        max(enter, min(first_distance, second_distance)),
                        min(leave, max(first_distance, second_distance)),
                    )
                    if enter > leave + tolerance:
                        return None
            return max(0.0, enter)

        def ray_circle(center_x, center_y):
            # 광선 시작점과 벽 모서리 원의 상대 위치를 구한다.
            offset_x, offset_y = x - center_x, y - center_y
            constant = offset_x * offset_x + offset_y * offset_y - radius * radius
            if constant <= tolerance:
                return 0.0
            if direction_length_squared == 0:
                return None

            # 광선이 모서리 원에 처음 닿는 거리를 구한다.
            projection = offset_x * delta_x + offset_y * delta_y
            discriminant = projection * projection - direction_length_squared * constant
            if discriminant < -tolerance:
                return None
            distance = (
                -projection - math.sqrt(max(0.0, discriminant))
            ) / direction_length_squared
            return distance if distance >= -tolerance else None

        # 이동 경로 주변 타일을 조사해 가장 먼저 닿는 벽을 고른다.
        end_x, end_y = x + delta_x * best, y + delta_y * best
        first_col = max(0, int((min(x, end_x) - radius) // tile))
        last_col = min(self.cols - 1, int((max(x, end_x) + radius) // tile))
        first_row = max(0, int((min(y, end_y) - radius) // tile))
        last_row = min(self.rows - 1, int((max(y, end_y) + radius) // tile))
        for row in range(first_row, last_row + 1):
            for col in range(first_col, last_col + 1):
                if not self.solid[row][col]:
                    continue
                left, top, right, bottom = (
                    col * tile,
                    row * tile,
                    (col + 1) * tile,
                    (row + 1) * tile,
                )
                # 둥근 사각형 = 두 직사각형과 네 모서리 원의 합집합.
                candidates = [
                    ray_box(left - radius, top, right + radius, bottom),
                    ray_box(left, top - radius, right, bottom + radius),
                ]
                if radius > 0:
                    candidates.extend(
                        ray_circle(center_x, center_y)
                        for center_x, center_y in (
                            (left, top),
                            (left, bottom),
                            (right, top),
                            (right, bottom),
                        )
                    )
                for distance in candidates:
                    if distance is not None:
                        consider(distance, (col, row))
        return best, hit_tile

    def navigation_tiles(self, radius=0.0):
        """지정 반지름의 선체가 중심에 놓일 수 있는 타일 목록(파괴 시 캐시 갱신)."""

        # 선체 반지름별로 들어갈 수 있는 타일 목록을 계산해 캐시에 보관한다.
        radius = float(radius)
        if radius not in self._navigation_cache:
            tiles = (
                tuple(self.free_tiles)
                if radius == 0
                else tuple(
                    tile_position
                    for tile_position in self.free_tiles
                    if self.circle_fits(*self.center(*tile_position), radius)
                )
            )
            self._navigation_cache[radius] = (tiles, frozenset(tiles))
        return self._navigation_cache[radius][0]

    def _navigation_set(self, radius):
        self.navigation_tiles(radius)
        return self._navigation_cache[float(radius)][1]

    def _navigation_edge(self, start, end, radius):
        # 인접 타일 중심 및 대각선 양옆의 통행 가능 여부는 호출자가 확인한다.
        # 반 타일보다 작은 원은 이 타일들 밖의 벽과 만날 수 없다.
        if radius <= self.tile / 2:
            return True
        # 큰 선체의 중심 사이 판정은 재탐색할 때 재사용한다.
        first_tile, second_tile = sorted((start, end))
        key = (float(radius), first_tile, second_tile)
        if key not in self._segment_cache:
            self._segment_cache[key] = self.segment_fits(
                *self.center(*first_tile), *self.center(*second_tile), radius
            )
        return self._segment_cache[key]

    # ---------------- 부서지는 벽 ----------------
    def damage_tile(self, col, row, damage) -> bool:
        """부서지는 벽에 데미지. 파괴되면 True."""

        # 피해를 받을 파괴 가능 벽과 남은 체력을 확인한다.
        key = (col, row)
        if key not in self.hp:
            return False
        self.hp[key] -= damage

        # 벽이 파괴되면 타일을 비우고 이동·충돌 캐시를 갱신한다.
        if self.hp[key] <= 0:
            del self.hp[key]
            self.tiles[row][col] = EMPTY
            self._refresh()
            return True
        self.version += 1
        return False

    # ---------------- 충돌 ----------------
    def resolve_circle(self, entity, bounce=False) -> bool:
        """원(entity.x, entity.y, entity.radius)을 벽 밖으로 밀어낸다.
        벽을 향하는 속도 성분만 제거(bounce면 반사)하므로 벽을 따라 미끄러진다."""

        # 주변에 벽이 없으면 충돌 보정을 생략한다.
        if not self.has_solid:
            return False
        tile_size = self.tile
        radius = entity.radius
        center_col, center_row = int(entity.x // tile_size), int(entity.y // tile_size)
        if (
            0 <= center_col < self.cols
            and 0 <= center_row < self.rows
            and not self.near_solid[center_row][center_col]
            and radius < tile_size
        ):
            return False  # 주변에 벽이 없음 (대부분의 경우 여기서 끝)

        # 주변 벽과 겹친 선체를 밀어내고 벽 방향의 속도를 보정한다.
        hit = False
        for _ in range(2):  # 모서리에서 두 벽에 동시에 닿는 경우 대비
            moved = False
            first_col, last_col = (
                int((entity.x - radius) // tile_size),
                int((entity.x + radius) // tile_size),
            )
            first_row, last_row = (
                int((entity.y - radius) // tile_size),
                int((entity.y + radius) // tile_size),
            )
            for tile_row in range(first_row, last_row + 1):
                for tile_col in range(first_col, last_col + 1):
                    if not self.is_solid_tile(tile_col, tile_row):
                        continue
                    left, top = tile_col * tile_size, tile_row * tile_size
                    point_x = min(max(entity.x, left), left + tile_size)
                    point_y = min(max(entity.y, top), top + tile_size)
                    delta_x, delta_y = entity.x - point_x, entity.y - point_y
                    distance_squared = delta_x * delta_x + delta_y * delta_y
                    if distance_squared >= radius * radius:
                        continue
                    if distance_squared > 1e-9:
                        distance = math.sqrt(distance_squared)
                        normal_x, normal_y = delta_x / distance, delta_y / distance
                        push = radius - distance
                    else:  # 중심이 벽 안: 가장 얕은 축으로 밀기
                        penetrations = [
                            (entity.x - left, -1.0, 0.0),
                            (left + tile_size - entity.x, 1.0, 0.0),
                            (entity.y - top, 0.0, -1.0),
                            (top + tile_size - entity.y, 0.0, 1.0),
                        ]
                        penetration, normal_x, normal_y = min(penetrations)
                        push = penetration + radius
                    entity.x += normal_x * push
                    entity.y += normal_y * push
                    normal_velocity = (
                        entity.velocity_x * normal_x + entity.velocity_y * normal_y
                    )
                    if normal_velocity < 0:
                        direction_sign = 2.0 if bounce else 1.0
                        entity.velocity_x -= direction_sign * normal_velocity * normal_x
                        entity.velocity_y -= direction_sign * normal_velocity * normal_y
                    moved = hit = True
            if not moved:
                break
        return hit

    # ---------------- 시야 ----------------
    def raycast(self, start_x, start_y, delta_x, delta_y, max_distance) -> float:
        """(start_x,start_y)에서 단위벡터 (delta_x,delta_y) 방향으로 첫 벽까지 거리 (없으면 max_dist). 격자 DDA."""
        tile_size = self.tile
        col, row = int(start_x // tile_size), int(start_y // tile_size)
        if self.is_solid_tile(col, row):
            return 0.0
        col_step = 1 if delta_x > 0 else -1
        row_step = 1 if delta_y > 0 else -1
        infinity = float("inf")
        col_step_distance = abs(tile_size / delta_x) if delta_x != 0 else infinity
        row_step_distance = abs(tile_size / delta_y) if delta_y != 0 else infinity
        col_distance = (
            (
                ((col + 1) * tile_size - start_x) / delta_x
                if delta_x > 0
                else (start_x - col * tile_size) / -delta_x
            )
            if delta_x != 0
            else infinity
        )
        row_distance = (
            (
                ((row + 1) * tile_size - start_y) / delta_y
                if delta_y > 0
                else (start_y - row * tile_size) / -delta_y
            )
            if delta_y != 0
            else infinity
        )

        # 타일 경계를 따라 이동하며 처음 만나는 벽까지의 거리를 찾는다.
        while True:
            if col_distance < row_distance:
                distance, col = col_distance, col + col_step
                col_distance += col_step_distance
            else:
                distance, row = row_distance, row + row_step
                row_distance += row_step_distance
            if distance >= max_distance:
                return max_distance
            if self.is_solid_tile(col, row):
                return distance

    def line_of_sight(self, start_x, start_y, end_x, end_y) -> bool:
        if not self.has_solid:
            return True

        # 두 지점 사이의 방향과 거리를 구한다.
        delta_x, delta_y = end_x - start_x, end_y - start_y
        distance = math.hypot(delta_x, delta_y)
        if distance < 1e-6:
            return True

        # 목표 지점 전에 벽이 나타나는지 광선으로 확인한다.
        return (
            self.raycast(
                start_x, start_y, delta_x / distance, delta_y / distance, distance
            )
            >= distance
        )

    # ---------------- 경로 ----------------
    def astar(self, start, goal, max_nodes=None, *, radius=0.0):
        """선체 반지름을 고려한 8방향 A*. start 제외 타일 목록, 실패 시 []."""

        # 선체 크기로 통과 가능한 타일과 출발·도착 조건을 확인한다.
        walkable = self._navigation_set(radius)
        if start == goal or start not in walkable or goal not in walkable:
            return []
        goal_col, goal_row = goal

        def heuristic(col, row):
            candidate_col, candidate_row = abs(col - goal_col), abs(row - goal_row)
            return max(candidate_col, candidate_row) + (math.sqrt(2) - 1) * min(
                candidate_col, candidate_row
            )

        # 탐색 후보와 타일별 최저 이동 비용을 준비한다.
        open_heap = [(heuristic(*start), 0, 0.0, start)]
        came, costs = {start: None}, {start: 0.0}
        serial, expanded = 0, 0
        limit = len(walkable) if max_nodes is None else max_nodes
        closed = set()

        # 이동 비용이 낮은 후보부터 탐색하고 도착하면 경로를 복원한다.
        while open_heap and expanded < limit:
            _, _, cost, current_tile = heapq.heappop(open_heap)
            if current_tile in closed or cost > costs[current_tile]:
                continue
            if current_tile == goal:
                path = []
                while current_tile != start:
                    path.append(current_tile)
                    current_tile = came[current_tile]
                return path[::-1]
            closed.add(current_tile)
            expanded += 1
            col, row = current_tile
            for delta_col, delta_row, weight in _NEIGHBORS:
                next_tile = (col + delta_col, row + delta_row)
                if next_tile not in walkable or next_tile in closed:
                    continue
                if (
                    delta_col
                    and delta_row
                    and (
                        (col + delta_col, row) not in walkable
                        or (col, row + delta_row) not in walkable
                    )
                ):
                    continue
                if not self._navigation_edge(current_tile, next_tile, radius):
                    continue
                new_cost = cost + weight
                if new_cost < costs.get(next_tile, float("inf")):
                    costs[next_tile], came[next_tile] = new_cost, current_tile
                    serial += 1
                    heapq.heappush(
                        open_heap,
                        (new_cost + heuristic(*next_tile), serial, new_cost, next_tile),
                    )
        return []

    def reachable_from(self, start, *, radius=0.0):
        """4방향 BFS. radius를 지정하면 선체가 통과할 수 있는 중심만 탐색한다."""

        # 선체가 통과할 수 있는 타일과 탐색 시작점을 확인한다.
        walkable = self._navigation_set(radius)
        if start not in walkable:
            return set()

        # 인접한 네 방향을 순회하며 시작점에서 연결된 타일을 수집한다.
        seen, queue = {start}, deque([start])
        while queue:
            col, row = current_tile = queue.popleft()
            for delta_col, delta_row in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                next_tile = (col + delta_col, row + delta_row)
                if (
                    next_tile in walkable
                    and next_tile not in seen
                    and self._navigation_edge(current_tile, next_tile, radius)
                ):
                    seen.add(next_tile)
                    queue.append(next_tile)
        return seen

    def is_connected(self, radius=0.0):
        tiles = self.navigation_tiles(radius)
        return bool(tiles) and len(
            self.reachable_from(self.player_start, radius=radius)
        ) == len(tiles)

    def validate_navigation(self, radius):
        """최대 선체의 시작 위치/통로 연결성을 확인한다."""
        if not self.circle_fits(*self.center(*self.player_start), radius):
            raise MapError(
                f"[{self.name}] 플레이어 시작점에 반지름 {radius:g}px 선체가 들어가지 않습니다."
            )
        if not self.is_connected(radius):
            raise MapError(
                f"[{self.name}] 반지름 {radius:g}px 선체로 통과할 수 없는 분리된 통로가 있습니다."
            )
        for spawn in self.enemy_starts:
            if not self.circle_fits(*self.center(*spawn), radius):
                raise MapError(
                    f"[{self.name}] 적 시작점 {spawn}에 반지름 {radius:g}px 선체가 들어가지 않습니다."
                )


# --------------------------------------------------------------------------
# 맵 로드 / 생성
# --------------------------------------------------------------------------
def parse_map(text, name, terrain_config: TerrainConfig, cols, rows) -> TileMap:
    # 주석과 빈 줄을 제외한 맵 텍스트의 크기를 확인한다.
    lines = [line.rstrip() for line in text.splitlines()]
    lines = [
        line for line in lines if line and not line.startswith(";")
    ]  # ';'로 시작하면 주석
    if len(lines) != rows:
        raise MapError(
            f"[{name}] 행 수가 {len(lines)}개입니다. {rows}개여야 합니다 (화면 {cols}x{rows} 타일)."
        )

    # 맵 문자를 지형 타일과 플레이어·적 시작점으로 변환한다.
    tiles, player, enemies = [], None, []
    for row_index, line in enumerate(lines):
        if len(line) != cols:
            raise MapError(
                f"[{name}] {row_index + 1}번째 줄 길이가 {len(line)}입니다. {cols}이어야 합니다: '{line}'"
            )
        row = []
        for col, character in enumerate(line):
            if character not in CHAR_TO_TILE:
                raise MapError(
                    f"[{name}] {row_index + 1}번째 줄 {col + 1}번째 문자 '{character}'는 알 수 없는 지형입니다."
                )
            if character == "P":
                if player is not None:
                    raise MapError(f"[{name}] P(플레이어 시작)가 여러 개입니다.")
                player = (col, row_index)
            elif character == "E":
                enemies.append((col, row_index))
            row.append(CHAR_TO_TILE[character])
        tiles.append(row)
    if player is None:
        raise MapError(f"[{name}] P(플레이어 시작)가 없습니다.")

    # 변환한 맵의 연결성과 선체 이동 가능 여부를 검사한다.
    terrain = TileMap(
        tiles, terrain_config.tile_size, player, enemies, name, terrain_config
    )
    if not terrain.is_connected():
        unreachable = set(terrain.free_tiles) - terrain.reachable_from(player)
        raise MapError(
            f"[{name}] 플레이어 시작점에서 갈 수 없는 빈칸이 있습니다: {sorted(unreachable)[:5]}..."
        )
    terrain.validate_navigation(terrain_config.navigation_radius)
    return terrain


_MAP_TEXT_CACHE = {}
# 같은 이름을 작은 사용자 지정 월드에서도 일관된 미로 형태로 사용할 고정 시드.
BUILTIN_MAP_SEEDS = {"drift": 1109, "ring": 2027, "belt": 3037, "hello-world": 4051}


def load_map(name, terrain_config: TerrainConfig, cols, rows) -> TileMap:
    # 맵 파일을 처음 읽을 때 내용을 캐시에 보관한다.
    if name not in _MAP_TEXT_CACHE:
        path = resource_path(os.path.join("maps", f"{name}.txt"))
        if not os.path.exists(path):
            raise MapError(f"맵 파일이 없습니다: {path} (사용 가능: {list_maps()})")
        with open(path, encoding="utf-8") as map_file:
            _MAP_TEXT_CACHE[name] = map_file.read()
    text = _MAP_TEXT_CACHE[name]
    lines = [
        line.rstrip()
        for line in text.splitlines()
        if line.strip() and not line.startswith(";")
    ]

    # 내장 맵은 원본을 검증하고 요청한 월드 크기에 맞춰 준비한다.
    if name in BUILTIN_MAP_SEEDS:
        # 내장 파일 손상/오타는 적응 생성으로 숨기지 않는다.
        if len(lines) != 45 or any(len(line) != 60 for line in lines):
            return parse_map(text, name, terrain_config, 60, 45)
        if (cols, rows) != (60, 45):
            # 기본 파일 자체도 먼저 검증한다. 사용자 지정 크기에서는 같은 이름의
            # 고정 시드로 전체 미로를 새로 만들며 반복/축소 배치하지 않는다.
            parse_map(text, name, terrain_config, 60, 45)
            return _generate_maze(
                np.random.default_rng(BUILTIN_MAP_SEEDS[name]),
                terrain_config,
                cols,
                rows,
                name,
            )
    return parse_map(text, name, terrain_config, cols, rows)


def empty_map(terrain_config: TerrainConfig, cols, rows) -> TileMap:
    tiles = [[EMPTY] * cols for _ in range(rows)]
    return TileMap(
        tiles,
        terrain_config.tile_size,
        (cols // 2, rows // 2),
        [],
        "empty",
        terrain_config,
    )


def expand_map(terrain: TileMap, scale: int, terrain_config: TerrainConfig) -> TileMap:
    """원본 타일 크기를 유지하고 맵을 반복 배치한다. 시작점은 중앙 구역에 둔다."""
    if scale == 1:
        return terrain

    # 원본 지형을 반복 배치하고 플레이어·적 시작점을 확장한다.
    tiles = [
        [
            terrain.tiles[row % terrain.rows][col % terrain.cols]
            for col in range(terrain.cols * scale)
        ]
        for row in range(terrain.rows * scale)
    ]
    player = (
        terrain.player_start[0] + (scale // 2) * terrain.cols,
        terrain.player_start[1] + (scale // 2) * terrain.rows,
    )
    enemies = [
        (col + scale_x * terrain.cols, row + scale_y * terrain.rows)
        for scale_y in range(scale)
        for scale_x in range(scale)
        for col, row in terrain.enemy_starts
    ]

    # 확장한 지형의 연결성과 이동 가능 여부를 검사한다.
    expanded = TileMap(
        tiles, terrain.tile, player, enemies, terrain.name, terrain_config
    )
    if not expanded.is_connected():
        raise MapError(f"[{terrain.name}] 확장된 맵의 구역들이 연결되지 않습니다.")
    expanded.validate_navigation(terrain_config.navigation_radius)
    return expanded


def _clear_outer_wall_band(tiles, *, left, right, top, bottom):
    """생성기의 외곽 벽띠만 비우며 내부 장애물은 유지한다."""
    rows, cols = len(tiles), len(tiles[0])
    for row_index, row in enumerate(tiles):
        for col, tile in enumerate(row):
            if (
                col < left
                or col >= cols - right
                or row_index < top
                or row_index >= rows - bottom
            ):
                if tile in (WALL, BREAKABLE):
                    row[col] = EMPTY


def _generate_maze(
    random_generator, terrain_config: TerrainConfig, cols, rows, name="random"
) -> TileMap:
    """넓은 방을 굵은 벽으로 나누고 DFS 통로로 잇는 하나의 전체 월드 미로.

    큰 선체의 중심이 지나는 모든 방/통로가 연결된다. 방 사이의 열린 연결을
    트리로 만들어 남은 벽도 외곽과 이어지고, 고립된 작은 장애물을 만들지 않는다.
    """

    # 가장 큰 선체에 필요한 통로 폭과 방 배치 크기를 계산한다.
    minimum = max(
        1,
        2 * math.ceil(terrain_config.navigation_radius / terrain_config.tile_size) + 1,
    )
    if min(cols, rows) < minimum:
        raise MapError(
            f"[{name}] 반지름 {terrain_config.navigation_radius:g}px 선체에는 최소 {minimum}칸 너비가 필요합니다."
        )
    passage = min(min(cols, rows), max(minimum, terrain_config.min_passage_tiles))
    thickness = max(2, terrain_config.wall_thickness)
    border = min(thickness, min(cols, rows) // 6)
    border = min(border, (min(cols, rows) - passage) // 2)
    inner_cols, inner_rows = cols - 2 * border, rows - 2 * border
    room_col_count = max(1, (inner_cols + thickness) // (passage + thickness))
    room_row_count = max(1, (inner_rows + thickness) // (passage + thickness))

    def spans(total, count):
        available = total - thickness * (count - 1)
        base, extra = divmod(available, count)
        positions, start = [], border
        for index in range(count):
            width = base + (index < extra)
            positions.append((start, width))
            start += width + thickness
        return positions

    # 월드 안에 배치할 방 영역과 벽으로 채운 지형을 준비한다.
    x_spans, y_spans = (
        spans(inner_cols, room_col_count),
        spans(inner_rows, room_row_count),
    )
    tiles = [[WALL] * cols for _ in range(rows)]

    def carve(first_col, first_row, width, height, kind=EMPTY):
        for row in range(first_row, first_row + height):
            for col in range(first_col, first_col + width):
                tiles[row][col] = kind

    # 각 방의 바닥을 만들고 방 중심 좌표를 기록한다.
    centers = {}
    for room_row, (first_row, height) in enumerate(y_spans):
        for room_col, (first_col, width) in enumerate(x_spans):
            carve(first_col, first_row, width, height)
            centers[room_col, room_row] = (
                first_col + width // 2,
                first_row + height // 2,
            )

    # 가운데 방에서 탐색을 시작해 모든 방을 통로로 연결한다.
    root = (room_col_count // 2, room_row_count // 2)
    visited, stack, opened = {root}, [root], set()
    while stack:
        room_col, room_row = stack[-1]
        neighbors = [
            (room_col + delta_col, room_row + delta_row)
            for delta_col, delta_row in ((1, 0), (-1, 0), (0, 1), (0, -1))
            if 0 <= room_col + delta_col < room_col_count
            and 0 <= room_row + delta_row < room_row_count
            and (room_col + delta_col, room_row + delta_row) not in visited
        ]
        if not neighbors:
            stack.pop()
            continue
        next_tile = neighbors[int(random_generator.integers(len(neighbors)))]
        neighbor_col, neighbor_row = next_tile
        opened.add(frozenset(((room_col, room_row), next_tile)))
        if room_col != neighbor_col:
            left, right = sorted((room_col, neighbor_col))
            first_col, width = x_spans[left]
            first_row, height = y_spans[room_row]
            carve(
                first_col + width,
                first_row + (height - passage) // 2,
                thickness,
                passage,
            )
        else:
            top, bottom = sorted((room_row, neighbor_row))
            first_col, width = x_spans[room_col]
            first_row, height = y_spans[top]
            carve(
                first_col + (width - passage) // 2,
                first_row + height,
                passage,
                thickness,
            )
        visited.add(next_tile)
        stack.append(next_tile)

    # 선택 지형도 바닥/벽의 큰 면 안에 넣어 기본 미로의 통로 폭을 바꾸지 않는다.
    if terrain_config.mud_enabled and terrain_config.random_mud_density > 0:
        count = max(1, int(terrain_config.random_mud_density * cols * rows / 9))
        for _ in range(min(count, len(centers))):
            cell = tuple(centers)[int(random_generator.integers(len(centers)))]
            tile_col, tile_row = centers[cell]
            carve(tile_col - 1, tile_row - 1, 3, 3, MUD)
    if terrain_config.breakable_enabled and terrain_config.random_breakable_density > 0:
        closed = []
        for room_col, room_row in centers:
            for neighbor_col, neighbor_row in (
                (room_col + 1, room_row),
                (room_col, room_row + 1),
            ):
                if (neighbor_col, neighbor_row) not in centers or frozenset(
                    ((room_col, room_row), (neighbor_col, neighbor_row))
                ) in opened:
                    continue
                if room_col != neighbor_col:
                    first_col, width = x_spans[room_col]
                    first_row, height = y_spans[room_row]
                    closed.append(
                        (first_col + width, first_row + (height - thickness) // 2)
                    )
                else:
                    first_col, width = x_spans[room_col]
                    first_row, height = y_spans[room_row]
                    closed.append(
                        (first_col + (width - thickness) // 2, first_row + height)
                    )
        count = min(
            len(closed),
            max(
                1,
                int(
                    terrain_config.random_breakable_density
                    * cols
                    * rows
                    / (thickness**2)
                ),
            ),
        )
        if count:
            for index in random_generator.choice(
                len(closed), size=count, replace=False
            ):
                carve(*closed[int(index)], thickness, thickness, BREAKABLE)
    _clear_outer_wall_band(tiles, left=border, right=border, top=border, bottom=border)

    # 플레이어와 적 시작점을 배치하고 완성된 미로를 검증한다.
    player = centers[root]
    enemies = sorted(
        (point for node, point in centers.items() if node != root),
        key=lambda point: (
            -((point[0] - player[0]) ** 2) - (point[1] - player[1]) ** 2,
            point,
        ),
    )[:12]
    terrain = TileMap(
        tiles, terrain_config.tile_size, player, enemies, name, terrain_config
    )
    if not terrain.is_connected():
        raise MapError(f"[{name}] 생성된 미로의 바닥이 연결되지 않습니다.")
    terrain.validate_navigation(terrain_config.navigation_radius)
    return terrain


def generate_random_map(
    random_generator, terrain_config: TerrainConfig, cols, rows, max_attempts=50
) -> TileMap:
    """diep.io 미로 모드 같은 블록 지형.

    월드를 큰 정사각 블록(block_tiles칸) 격자로 나누고, 짝수 칸을 방으로 삼아 DFS 미로를 판다.
    그다음 막힌 벽의 일부(extra_openings)와 벽 기둥(pillar_removal)을 없애 순환 통로와
    넓은 공간을 만든다. 미로처럼 길은 있지만 막다른 길과 갑갑함이 적다.
    통로 폭이 한 블록이라 가장 큰 선체도 지나간다.
    """
    minimum = max(
        1,
        2 * math.ceil(terrain_config.navigation_radius / terrain_config.tile_size) + 1,
    )
    block = max(minimum, terrain_config.block_tiles)
    block_cols, block_rows = cols // block, rows // block
    if block_cols < 1 or block_rows < 1:
        raise MapError(
            f"[random] {cols}x{rows} 월드는 {block}칸 블록 지형을 만들기에 너무 작습니다."
        )
    rooms = [(x, y) for y in range(0, block_rows, 2) for x in range(0, block_cols, 2)]
    terrain = None
    for _ in range(max_attempts):
        # 1) 방(짝수, 짝수)은 바닥, 그 사이 연결 블록과 기둥(홀수, 홀수)은 벽으로 시작
        grid = [
            [(x % 2 == 0 and y % 2 == 0) for x in range(block_cols)]
            for y in range(block_rows)
        ]

        # 2) 가운데 방에서 DFS로 모든 방을 잇는다
        root = min(
            rooms,
            key=lambda row: (
                (row[0] - block_cols // 2) ** 2 + (row[1] - block_rows // 2) ** 2
            ),
        )
        seen, stack = {root}, [root]
        while stack:
            x, y = stack[-1]
            unvisited_neighbors = [
                (x + delta_x, y + delta_y)
                for delta_x, delta_y in ((2, 0), (-2, 0), (0, 2), (0, -2))
                if 0 <= x + delta_x < block_cols
                and 0 <= y + delta_y < block_rows
                and (x + delta_x, y + delta_y) not in seen
            ]
            if not unvisited_neighbors:
                stack.pop()
                continue
            next_x, next_y = unvisited_neighbors[
                int(random_generator.integers(len(unvisited_neighbors)))
            ]
            grid[(y + next_y) // 2][(x + next_x) // 2] = True
            seen.add((next_x, next_y))
            stack.append((next_x, next_y))

        def touches_floor(x, y):
            return any(
                0 <= x + delta_x < block_cols
                and 0 <= y + delta_y < block_rows
                and grid[y + delta_y][x + delta_x]
                for delta_x, delta_y in ((1, 0), (-1, 0), (0, 1), (0, -1))
            )

        # 3) 순환 통로: 남은 연결 벽 일부를 뚫는다 (가장자리 줄도 포함)
        for y in range(block_rows):
            for x in range(block_cols):
                if grid[y][x] or (x % 2 == 1 and y % 2 == 1):
                    continue
                if random_generator.random() < terrain_config.extra_openings:
                    grid[y][x] = True

        # 4) 넓은 공간: 기둥 일부를 없앤다. 주변 바닥과 이어진 기둥만 없애 고립된 바닥을 막는다.
        for y in range(1, block_rows, 2):
            for x in range(1, block_cols, 2):
                if (
                    random_generator.random() < terrain_config.pillar_removal
                    and touches_floor(x, y)
                ):
                    grid[y][x] = True
        # 가장자리 남는 줄(블록 수가 짝수일 때)의 고립된 바닥은 벽으로 되돌린다
        for y in range(block_rows):
            for x in range(block_cols):
                if grid[y][x] and not touches_floor(x, y) and (x, y) not in seen:
                    grid[y][x] = False

        # 5) 벽 덩어리: 벽 옆 바닥 블록 일부를 메워 크기가 제각각인 큰 벽을 만든다.
        #    전체 바닥이 여전히 이어질 때만 메운다.
        def floor_connected():
            floor = {
                (x, y)
                for y in range(block_rows)
                for x in range(block_cols)
                if grid[y][x]
            }

            # 열린 블록 하나에서 시작해 모든 바닥 블록이 연결되는지 검사한다.
            start = next(iter(floor))
            reach, todo = {start}, [start]
            while todo:
                x, y = todo.pop()
                for neighbor_block in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                    if neighbor_block in floor and neighbor_block not in reach:
                        reach.add(neighbor_block)
                        todo.append(neighbor_block)
            return len(reach) == len(floor)

        candidates = [
            (x, y)
            for y in range(block_rows)
            for x in range(block_cols)
            if grid[y][x]
            and (x, y) != root
            and abs(x - root[0]) + abs(y - root[1]) > 1
            and any(
                0 <= x + delta_x < block_cols
                and 0 <= y + delta_y < block_rows
                and not grid[y + delta_y][x + delta_x]
                for delta_x, delta_y in ((1, 0), (-1, 0), (0, 1), (0, -1))
            )
        ]
        for index in random_generator.permutation(len(candidates)):
            if random_generator.random() >= terrain_config.wall_merge:
                continue
            x, y = candidates[int(index)]
            grid[y][x] = False
            if not floor_connected():
                grid[y][x] = True

        tiles = [[WALL] * cols for _ in range(rows)]
        col_offset, row_offset = (
            (cols - block_cols * block) // 2,
            (rows - block_rows * block) // 2,
        )
        for y in range(block_rows):
            for x in range(block_cols):
                if grid[y][x]:
                    for row in range(
                        row_offset + y * block, row_offset + (y + 1) * block
                    ):
                        for col in range(
                            col_offset + x * block, col_offset + (x + 1) * block
                        ):
                            tiles[row][col] = EMPTY
        # 블록 격자에 들어가지 않는 가장자리 자투리는 바깥 벽과 이어 둔다

        def block_center(x, y):
            return (
                col_offset + x * block + block // 2,
                row_offset + y * block + block // 2,
            )

        if (
            terrain_config.breakable_enabled
            and terrain_config.random_breakable_density > 0
        ):
            links = [
                (x, y)
                for y in range(block_rows)
                for x in range(block_cols)
                if not grid[y][x] and (x % 2) != (y % 2)
            ]
            count = min(
                len(links),
                max(1, int(terrain_config.random_breakable_density * len(links) * 4)),
            )
            for index in (
                random_generator.choice(len(links), size=count, replace=False)
                if links
                else ()
            ):
                x, y = links[int(index)]
                for row in range(row_offset + y * block, row_offset + (y + 1) * block):
                    for col in range(
                        col_offset + x * block, col_offset + (x + 1) * block
                    ):
                        tiles[row][col] = BREAKABLE
        if terrain_config.mud_enabled and terrain_config.random_mud_density > 0:
            floor_rooms = [row for row in rooms if row != root]
            count = min(
                len(floor_rooms),
                max(1, int(terrain_config.random_mud_density * len(floor_rooms) * 3)),
            )
            for index in (
                random_generator.choice(len(floor_rooms), size=count, replace=False)
                if floor_rooms
                else ()
            ):
                col, row = block_center(*floor_rooms[int(index)])
                for tile_row in range(row - 1, row + 2):
                    for tile_col in range(col - 1, col + 2):
                        tiles[tile_row][tile_col] = MUD

        _clear_outer_wall_band(
            tiles,
            left=col_offset,
            right=cols - col_offset - block_cols * block,
            top=row_offset,
            bottom=rows - row_offset - block_rows * block,
        )
        player = block_center(*root)
        terrain = TileMap(
            tiles, terrain_config.tile_size, player, [], "random", terrain_config
        )
        if terrain.is_connected() and terrain.is_connected(
            terrain_config.navigation_radius
        ):
            break
    else:
        raise MapError("[random] 연결된 랜덤 지형을 만들지 못했습니다.")

    # 적 시작점: 플레이어 방에서 먼 바닥 블록의 중앙
    floors = [
        (x, y) for y in range(block_rows) for x in range(block_cols) if grid[y][x]
    ]
    distant_blocks = sorted(
        floors,
        key=lambda block_position: (
            -((block_position[0] - root[0]) ** 2 + (block_position[1] - root[1]) ** 2)
        ),
    )
    distant_blocks = [
        block_position
        for block_position in distant_blocks
        if abs(block_position[0] - root[0]) + abs(block_position[1] - root[1]) >= 3
    ] or distant_blocks[:-1]
    spawn_indices = (
        random_generator.choice(
            len(distant_blocks), size=min(12, len(distant_blocks)), replace=False
        )
        if distant_blocks
        else ()
    )
    terrain.enemy_starts = sorted(
        block_center(*distant_blocks[int(tile_index)]) for tile_index in spawn_indices
    )
    terrain.validate_navigation(terrain_config.navigation_radius)
    return terrain


def map_to_text(terrain: TileMap) -> str:
    # 지형 타일을 행별 맵 문자로 변환한다.
    rows = []
    for row in range(terrain.rows):
        line = "".join(TILE_TO_CHAR[tile_code] for tile_code in terrain.tiles[row])
        rows.append(line)
    # 플레이어와 적 시작점을 해당 위치의 문자에 덧씌운다.
    player_col, player_row = terrain.player_start
    rows[player_row] = (
        rows[player_row][:player_col] + "P" + rows[player_row][player_col + 1 :]
    )
    for enemy_col, enemy_row in terrain.enemy_starts:
        rows[enemy_row] = (
            rows[enemy_row][:enemy_col] + "E" + rows[enemy_row][enemy_col + 1 :]
        )
    return "\n".join(rows)
