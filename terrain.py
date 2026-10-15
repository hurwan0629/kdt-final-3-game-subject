"""타일 기반 지형. pygame에 의존하지 않는다.

- 맵 텍스트 파싱/검증, 랜덤 맵 생성 (+BFS 연결성 검증)
- 원 ↔ 벽 충돌 (벽을 따라 미끄러짐), 시야선/레이캐스트 (격자 DDA), A* 경로 탐색
"""
import heapq
import math
import os
from collections import deque

import numpy as np

from config import TerrainConfig, resource_path

EMPTY, WALL, MUD, BREAKABLE = 0, 1, 3, 4
CHAR_TO_TILE = {".": EMPTY, "#": WALL, "~": MUD, "+": BREAKABLE, "P": EMPTY, "E": EMPTY}
TILE_TO_CHAR = {EMPTY: ".", WALL: "#", MUD: "~", BREAKABLE: "+"}

# 8방향 이웃 (dc, dr, 비용)
_NEIGHBORS = [(1, 0, 1.0), (-1, 0, 1.0), (0, 1, 1.0), (0, -1, 1.0),
              (1, 1, math.sqrt(2)), (1, -1, math.sqrt(2)), (-1, 1, math.sqrt(2)), (-1, -1, math.sqrt(2))]


class MapError(ValueError):
    pass


def grid_channels(tcfg: TerrainConfig):
    """관찰 격자에 들어가는 지형 채널 이름 (설정에 따라 고정)."""
    ch = ["wall"]
    if tcfg.mud_enabled:
        ch.append("mud")
    if tcfg.breakable_enabled:
        ch.append("breakable")
    return ch


def list_maps():
    d = resource_path("maps")
    if not os.path.isdir(d):
        return []
    return sorted(f[:-4] for f in os.listdir(d) if f.endswith(".txt"))


class TileMap:
    def __init__(self, tiles, tile_size, player_start, enemy_starts, name, tcfg: TerrainConfig):
        self.rows = len(tiles)
        self.cols = len(tiles[0])
        self.tile = tile_size
        self.name = name
        self.player_start = player_start          # (col, row)
        self.enemy_starts = list(enemy_starts)    # [(col, row), ...]
        self.breakable_hp_max = tcfg.breakable_hp
        # 설정에서 끈 기능은 해당 타일을 일반 타일로 취급
        conv = {MUD: MUD if tcfg.mud_enabled else EMPTY,
                BREAKABLE: BREAKABLE if tcfg.breakable_enabled else WALL}
        self.tiles = [[conv.get(t, t) for t in row] for row in tiles]
        self.hp = {(c, r): tcfg.breakable_hp for r in range(self.rows) for c in range(self.cols)
                   if self.tiles[r][c] == BREAKABLE}
        self.version = 0          # 지형이 바뀔 때마다 증가 (렌더러/관찰 캐시 무효화용)
        self._refresh()

    def _refresh(self):
        self._navigation_cache = {}
        self._segment_cache = {}
        self.solid = [[t in (WALL, BREAKABLE) for t in row] for row in self.tiles]
        self.has_solid = any(any(row) for row in self.solid)
        # 자신/주변 8칸(맵 바깥 포함)에 막힌 칸이 있는지. 물체 반지름 < 타일 크기라
        # 이 값이 False인 칸에 중심이 있으면 벽 충돌 검사를 건너뛸 수 있다.
        self.near_solid = [[any(self.is_solid_tile(c + dc, r + dr) for dc in (-1, 0, 1) for dr in (-1, 0, 1))
                            for c in range(self.cols)] for r in range(self.rows)]
        self.free_tiles = [(c, r) for r in range(self.rows) for c in range(self.cols) if not self.solid[r][c]]
        # 사방이 막히지 않은 칸 (큰 도형 스폰용)
        self.open_tiles = [(c, r) for c, r in self.free_tiles
                           if all(not self.is_solid_tile(c + dc, r + dr)
                                  for dc, dr in ((1, 0), (-1, 0), (0, 1), (0, -1)))]
        self.version += 1

    # ---------------- 조회 ----------------
    def is_solid_tile(self, c, r):
        return c < 0 or r < 0 or c >= self.cols or r >= self.rows or self.solid[r][c]

    def tile_of(self, x, y):
        return int(x // self.tile), int(y // self.tile)

    def tile_at(self, x, y):
        c, r = int(x // self.tile), int(y // self.tile)
        if c < 0 or r < 0 or c >= self.cols or r >= self.rows:
            return WALL
        return self.tiles[r][c]

    def is_solid_at(self, x, y):
        return self.is_solid_tile(int(x // self.tile), int(y // self.tile))

    def center(self, c, r):
        return (c + 0.5) * self.tile, (r + 0.5) * self.tile

    def as_array(self):
        return np.array(self.tiles, dtype=np.int8)

    # ---------------- 선체 여유 ----------------
    def circle_fits(self, x, y, radius):
        """경계/벽과 겹치지 않는 원인지 검사한다. 정확히 닿는 것은 허용한다."""
        if radius < 0:
            raise ValueError("선체 반지름은 0 이상이어야 합니다.")
        eps = 1e-7
        if (x < radius - eps or y < radius - eps
                or x > self.cols * self.tile - radius + eps
                or y > self.rows * self.tile - radius + eps):
            return False
        if radius == 0:
            return not self.is_solid_at(x, y)
        if not self.has_solid:
            return True
        t, rr = self.tile, radius * radius
        col, row = int(x // t), int(y // t)
        if radius < t and 0 <= col < self.cols and 0 <= row < self.rows and not self.near_solid[row][col]:
            return True
        c0, c1 = max(0, int((x - radius) // t)), min(self.cols - 1, int((x + radius) // t))
        r0, r1 = max(0, int((y - radius) // t)), min(self.rows - 1, int((y + radius) // t))
        for r in range(r0, r1 + 1):
            for c in range(c0, c1 + 1):
                if not self.solid[r][c]:
                    continue
                dx = x - min(max(x, c * t), (c + 1) * t)
                dy = y - min(max(y, r * t), (r + 1) * t)
                if dx * dx + dy * dy < rr - eps:
                    return False
        return True

    def segment_fits(self, x0, y0, x1, y1, radius):
        """원형 선체가 선분 전체를 이동할 수 있는지 검사한다. 시야선보다 넓은 여유를 쓴다."""
        if not self.circle_fits(x0, y0, radius) or not self.circle_fits(x1, y1, radius):
            return False
        if not self.has_solid:
            return True
        dx, dy = x1 - x0, y1 - y0
        length2 = dx * dx + dy * dy
        if length2 < 1e-12:
            return True
        t, rr = self.tile, radius * radius
        c0 = max(0, int((min(x0, x1) - radius) // t))
        c1 = min(self.cols - 1, int((max(x0, x1) + radius) // t))
        r0 = max(0, int((min(y0, y1) - radius) // t))
        r1 = min(self.rows - 1, int((max(y0, y1) + radius) // t))
        for r in range(r0, r1 + 1):
            for c in range(c0, c1 + 1):
                if not self.solid[r][c]:
                    continue
                left, right, top, bottom = c * t, (c + 1) * t, r * t, (r + 1) * t
                # 선분 자체와 사각형의 교차: slab clipping.
                lo, hi = 0.0, 1.0
                for origin, delta, low, high in ((x0, dx, left, right), (y0, dy, top, bottom)):
                    if abs(delta) < 1e-12:
                        if origin < low or origin > high:
                            lo, hi = 1.0, 0.0
                            break
                    else:
                        a, b = (low - origin) / delta, (high - origin) / delta
                        lo, hi = max(lo, min(a, b)), min(hi, max(a, b))
                if lo <= hi:
                    return False
                if radius == 0:
                    continue
                # 비교할 최소 거리는 끝점→벽, 모서리→선분 중 하나다.
                distance2 = min(
                    (px - min(max(px, left), right)) ** 2 + (py - min(max(py, top), bottom)) ** 2
                    for px, py in ((x0, y0), (x1, y1)))
                for cx, cy in ((left, top), (left, bottom), (right, top), (right, bottom)):
                    u = min(1.0, max(0.0, ((cx - x0) * dx + (cy - y0) * dy) / length2))
                    distance2 = min(distance2, (cx - x0 - u * dx) ** 2 + (cy - y0 - u * dy) ** 2)
                if distance2 < rr - 1e-7:
                    return False
        return True

    def sweep_circle(self, x, y, dx, dy, max_distance, radius):
        """단위 방향으로 움직이는 원의 첫 벽 접촉 (거리, 타일). 없으면 (거리한도, None).

        벽 사각형에 반지름을 더한 둥근 사각형과 ray를 정확히 교차시킨다.
        모서리도 원으로 검사하므로 중심선이 벽을 비껴가는 탄환을 놓치지 않는다.
        경계 충돌의 타일 좌표는 맵 바깥의 한 칸이다.
        """
        if radius < 0 or max_distance < 0:
            raise ValueError("반지름과 이동 거리는 0 이상이어야 합니다.")
        norm2 = dx * dx + dy * dy
        if norm2 > 0 and abs(norm2 - 1.0) > 1e-9:
            length = math.sqrt(norm2)
            dx, dy, norm2 = dx / length, dy / length, 1.0
        best, hit_tile = float(max_distance), None
        width, height, tile = self.cols * self.tile, self.rows * self.tile, self.tile
        eps = 1e-9

        def consider(distance, cell):
            nonlocal best, hit_tile
            if -eps <= distance <= best + eps:
                distance = max(0.0, min(float(max_distance), distance))
                if hit_tile is None or distance < best - eps:
                    best, hit_tile = distance, cell

        # 선체 중심이 경계를 넘기 전에 반지름만큼 먼저 닿는다.
        for origin, direction, low, high, vertical in (
                (x, dx, radius, width - radius, True),
                (y, dy, radius, height - radius, False)):
            if origin < low - eps:
                distance, side = 0.0, -1
            elif origin > high + eps:
                distance, side = 0.0, self.cols if vertical else self.rows
            elif direction < -eps:
                distance, side = (low - origin) / direction, -1
            elif direction > eps:
                distance, side = (high - origin) / direction, self.cols if vertical else self.rows
            else:
                continue
            other = y + dy * distance if vertical else x + dx * distance
            other_cell = min((self.rows if vertical else self.cols) - 1, max(0, int(other // tile)))
            consider(distance, (side, other_cell) if vertical else (other_cell, side))
        if not self.has_solid:
            return best, hit_tile

        def ray_box(left, top, right, bottom):
            enter, leave = 0.0, best
            for origin, direction, low, high in ((x, dx, left, right), (y, dy, top, bottom)):
                if abs(direction) < 1e-12:
                    if origin < low or origin > high:
                        return None
                else:
                    a, b = (low - origin) / direction, (high - origin) / direction
                    enter, leave = max(enter, min(a, b)), min(leave, max(a, b))
                    if enter > leave + eps:
                        return None
            return max(0.0, enter)

        def ray_circle(cx, cy):
            ox, oy = x - cx, y - cy
            constant = ox * ox + oy * oy - radius * radius
            if constant <= eps:
                return 0.0
            if norm2 == 0:
                return None
            projection = ox * dx + oy * dy
            discriminant = projection * projection - norm2 * constant
            if discriminant < -eps:
                return None
            distance = (-projection - math.sqrt(max(0.0, discriminant))) / norm2
            return distance if distance >= -eps else None

        end_x, end_y = x + dx * best, y + dy * best
        c0 = max(0, int((min(x, end_x) - radius) // tile))
        c1 = min(self.cols - 1, int((max(x, end_x) + radius) // tile))
        r0 = max(0, int((min(y, end_y) - radius) // tile))
        r1 = min(self.rows - 1, int((max(y, end_y) + radius) // tile))
        for row in range(r0, r1 + 1):
            for col in range(c0, c1 + 1):
                if not self.solid[row][col]:
                    continue
                left, top, right, bottom = col * tile, row * tile, (col + 1) * tile, (row + 1) * tile
                # 둥근 사각형 = 두 직사각형과 네 모서리 원의 합집합.
                candidates = [ray_box(left - radius, top, right + radius, bottom),
                              ray_box(left, top - radius, right, bottom + radius)]
                if radius > 0:
                    candidates.extend(ray_circle(cx, cy)
                                      for cx, cy in ((left, top), (left, bottom), (right, top), (right, bottom)))
                for distance in candidates:
                    if distance is not None:
                        consider(distance, (col, row))
        return best, hit_tile

    def navigation_tiles(self, radius=0.0):
        """지정 반지름의 선체가 중심에 놓일 수 있는 타일 목록(파괴 시 캐시 갱신)."""
        radius = float(radius)
        if radius not in self._navigation_cache:
            tiles = tuple(self.free_tiles) if radius == 0 else tuple(t for t in self.free_tiles if self.circle_fits(*self.center(*t), radius))
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
        a, b = sorted((start, end))
        key = (float(radius), a, b)
        if key not in self._segment_cache:
            self._segment_cache[key] = self.segment_fits(*self.center(*a), *self.center(*b), radius)
        return self._segment_cache[key]

    # ---------------- 부서지는 벽 ----------------
    def damage_tile(self, c, r, dmg) -> bool:
        """부서지는 벽에 데미지. 파괴되면 True."""
        key = (c, r)
        if key not in self.hp:
            return False
        self.hp[key] -= dmg
        if self.hp[key] <= 0:
            del self.hp[key]
            self.tiles[r][c] = EMPTY
            self._refresh()
            return True
        self.version += 1
        return False

    # ---------------- 충돌 ----------------
    def resolve_circle(self, obj, bounce=False) -> bool:
        """원(obj.x, obj.y, obj.radius)을 벽 밖으로 밀어낸다.
        벽을 향하는 속도 성분만 제거(bounce면 반사)하므로 벽을 따라 미끄러진다."""
        if not self.has_solid:
            return False
        T = self.tile
        r = obj.radius
        tc0, tr0 = int(obj.x // T), int(obj.y // T)
        if 0 <= tc0 < self.cols and 0 <= tr0 < self.rows and not self.near_solid[tr0][tc0] and r < T:
            return False   # 주변에 벽이 없음 (대부분의 경우 여기서 끝)
        hit = False
        for _ in range(2):  # 모서리에서 두 벽에 동시에 닿는 경우 대비
            moved = False
            c0, c1 = int((obj.x - r) // T), int((obj.x + r) // T)
            r0, r1 = int((obj.y - r) // T), int((obj.y + r) // T)
            for tr in range(r0, r1 + 1):
                for tc in range(c0, c1 + 1):
                    if not self.is_solid_tile(tc, tr):
                        continue
                    left, top = tc * T, tr * T
                    px = min(max(obj.x, left), left + T)
                    py = min(max(obj.y, top), top + T)
                    dx, dy = obj.x - px, obj.y - py
                    d2 = dx * dx + dy * dy
                    if d2 >= r * r:
                        continue
                    if d2 > 1e-9:
                        d = math.sqrt(d2)
                        nx, ny = dx / d, dy / d
                        push = r - d
                    else:  # 중심이 벽 안: 가장 얕은 축으로 밀기
                        pens = [(obj.x - left, -1.0, 0.0), (left + T - obj.x, 1.0, 0.0),
                                (obj.y - top, 0.0, -1.0), (top + T - obj.y, 0.0, 1.0)]
                        pen, nx, ny = min(pens)
                        push = pen + r
                    obj.x += nx * push
                    obj.y += ny * push
                    vn = obj.vx * nx + obj.vy * ny
                    if vn < 0:
                        k = 2.0 if bounce else 1.0
                        obj.vx -= k * vn * nx
                        obj.vy -= k * vn * ny
                    moved = hit = True
            if not moved:
                break
        return hit

    # ---------------- 시야 ----------------
    def raycast(self, x0, y0, dx, dy, max_dist) -> float:
        """(x0,y0)에서 단위벡터 (dx,dy) 방향으로 첫 벽까지 거리 (없으면 max_dist). 격자 DDA."""
        T = self.tile
        c, r = int(x0 // T), int(y0 // T)
        if self.is_solid_tile(c, r):
            return 0.0
        step_c = 1 if dx > 0 else -1
        step_r = 1 if dy > 0 else -1
        inf = float("inf")
        t_dc = abs(T / dx) if dx != 0 else inf
        t_dr = abs(T / dy) if dy != 0 else inf
        t_c = (((c + 1) * T - x0) / dx if dx > 0 else (x0 - c * T) / -dx) if dx != 0 else inf
        t_r = (((r + 1) * T - y0) / dy if dy > 0 else (y0 - r * T) / -dy) if dy != 0 else inf
        while True:
            if t_c < t_r:
                t, c = t_c, c + step_c
                t_c += t_dc
            else:
                t, r = t_r, r + step_r
                t_r += t_dr
            if t >= max_dist:
                return max_dist
            if self.is_solid_tile(c, r):
                return t

    def line_of_sight(self, x0, y0, x1, y1) -> bool:
        if not self.has_solid:
            return True
        dx, dy = x1 - x0, y1 - y0
        d = math.hypot(dx, dy)
        if d < 1e-6:
            return True
        return self.raycast(x0, y0, dx / d, dy / d, d) >= d

    # ---------------- 경로 ----------------
    def astar(self, start, goal, max_nodes=None, *, radius=0.0):
        """선체 반지름을 고려한 8방향 A*. start 제외 타일 목록, 실패 시 []."""
        walkable = self._navigation_set(radius)
        if start == goal or start not in walkable or goal not in walkable:
            return []
        gx, gy = goal

        def h(c, r):
            ax, ay = abs(c - gx), abs(r - gy)
            return max(ax, ay) + (math.sqrt(2) - 1) * min(ax, ay)

        open_heap = [(h(*start), 0, 0.0, start)]
        came, costs = {start: None}, {start: 0.0}
        serial, expanded = 0, 0
        limit = len(walkable) if max_nodes is None else max_nodes
        closed = set()
        while open_heap and expanded < limit:
            _, _, cost, cur = heapq.heappop(open_heap)
            if cur in closed or cost > costs[cur]:
                continue
            if cur == goal:
                path = []
                while cur != start:
                    path.append(cur)
                    cur = came[cur]
                return path[::-1]
            closed.add(cur)
            expanded += 1
            c, r = cur
            for dc, dr, weight in _NEIGHBORS:
                nxt = (c + dc, r + dr)
                if nxt not in walkable or nxt in closed:
                    continue
                if dc and dr and ((c + dc, r) not in walkable or (c, r + dr) not in walkable):
                    continue
                if not self._navigation_edge(cur, nxt, radius):
                    continue
                new_cost = cost + weight
                if new_cost < costs.get(nxt, float("inf")):
                    costs[nxt], came[nxt] = new_cost, cur
                    serial += 1
                    heapq.heappush(open_heap, (new_cost + h(*nxt), serial, new_cost, nxt))
        return []

    def reachable_from(self, start, *, radius=0.0):
        """4방향 BFS. radius를 지정하면 선체가 통과할 수 있는 중심만 탐색한다."""
        walkable = self._navigation_set(radius)
        if start not in walkable:
            return set()
        seen, queue = {start}, deque([start])
        while queue:
            c, r = cur = queue.popleft()
            for dc, dr in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nxt = (c + dc, r + dr)
                if nxt in walkable and nxt not in seen and self._navigation_edge(cur, nxt, radius):
                    seen.add(nxt)
                    queue.append(nxt)
        return seen

    def is_connected(self, radius=0.0):
        tiles = self.navigation_tiles(radius)
        return bool(tiles) and len(self.reachable_from(self.player_start, radius=radius)) == len(tiles)

    def validate_navigation(self, radius):
        """최대 선체의 시작 위치/통로 연결성을 확인한다."""
        if not self.circle_fits(*self.center(*self.player_start), radius):
            raise MapError(f"[{self.name}] 플레이어 시작점에 반지름 {radius:g}px 선체가 들어가지 않습니다.")
        if not self.is_connected(radius):
            raise MapError(f"[{self.name}] 반지름 {radius:g}px 선체로 통과할 수 없는 분리된 통로가 있습니다.")
        for spawn in self.enemy_starts:
            if not self.circle_fits(*self.center(*spawn), radius):
                raise MapError(f"[{self.name}] 적 시작점 {spawn}에 반지름 {radius:g}px 선체가 들어가지 않습니다.")


# --------------------------------------------------------------------------
# 맵 로드 / 생성
# --------------------------------------------------------------------------
def parse_map(text, name, tcfg: TerrainConfig, cols, rows) -> TileMap:
    lines = [ln.rstrip() for ln in text.splitlines()]
    lines = [ln for ln in lines if ln and not ln.startswith(";")]  # ';'로 시작하면 주석
    if len(lines) != rows:
        raise MapError(f"[{name}] 행 수가 {len(lines)}개입니다. {rows}개여야 합니다 (화면 {cols}x{rows} 타일).")
    tiles, player, enemies = [], None, []
    for r, ln in enumerate(lines):
        if len(ln) != cols:
            raise MapError(f"[{name}] {r + 1}번째 줄 길이가 {len(ln)}입니다. {cols}이어야 합니다: '{ln}'")
        row = []
        for c, ch in enumerate(ln):
            if ch not in CHAR_TO_TILE:
                raise MapError(f"[{name}] {r + 1}번째 줄 {c + 1}번째 문자 '{ch}'는 알 수 없는 지형입니다.")
            if ch == "P":
                if player is not None:
                    raise MapError(f"[{name}] P(플레이어 시작)가 여러 개입니다.")
                player = (c, r)
            elif ch == "E":
                enemies.append((c, r))
            row.append(CHAR_TO_TILE[ch])
        tiles.append(row)
    if player is None:
        raise MapError(f"[{name}] P(플레이어 시작)가 없습니다.")
    tm = TileMap(tiles, tcfg.tile_size, player, enemies, name, tcfg)
    if not tm.is_connected():
        unreachable = set(tm.free_tiles) - tm.reachable_from(player)
        raise MapError(f"[{name}] 플레이어 시작점에서 갈 수 없는 빈칸이 있습니다: {sorted(unreachable)[:5]}...")
    tm.validate_navigation(tcfg.navigation_radius)
    return tm


_MAP_TEXT_CACHE = {}
# 같은 이름을 작은 사용자 지정 월드에서도 일관된 미로 형태로 사용할 고정 시드.
BUILTIN_MAP_SEEDS = {"drift": 1109, "ring": 2027, "belt": 3037, "hello-world": 4051}


def load_map(name, tcfg: TerrainConfig, cols, rows) -> TileMap:
    if name not in _MAP_TEXT_CACHE:
        path = resource_path(os.path.join("maps", f"{name}.txt"))
        if not os.path.exists(path):
            raise MapError(f"맵 파일이 없습니다: {path} (사용 가능: {list_maps()})")
        with open(path, encoding="utf-8") as f:
            _MAP_TEXT_CACHE[name] = f.read()
    text = _MAP_TEXT_CACHE[name]
    lines = [line.rstrip() for line in text.splitlines() if line.strip() and not line.startswith(";")]
    if name in BUILTIN_MAP_SEEDS:
        # 내장 파일 손상/오타는 적응 생성으로 숨기지 않는다.
        if len(lines) != 45 or any(len(line) != 60 for line in lines):
            return parse_map(text, name, tcfg, 60, 45)
        if (cols, rows) != (60, 45):
            # 기본 파일 자체도 먼저 검증한다. 사용자 지정 크기에서는 같은 이름의
            # 고정 시드로 전체 미로를 새로 만들며 반복/축소 배치하지 않는다.
            parse_map(text, name, tcfg, 60, 45)
            return _generate_maze(np.random.default_rng(BUILTIN_MAP_SEEDS[name]), tcfg, cols, rows, name)
    return parse_map(text, name, tcfg, cols, rows)


def empty_map(tcfg: TerrainConfig, cols, rows) -> TileMap:
    tiles = [[EMPTY] * cols for _ in range(rows)]
    return TileMap(tiles, tcfg.tile_size, (cols // 2, rows // 2), [], "empty", tcfg)


def expand_map(tm: TileMap, scale: int, tcfg: TerrainConfig) -> TileMap:
    """원본 타일 크기를 유지하고 맵을 반복 배치한다. 시작점은 중앙 구역에 둔다."""
    if scale == 1:
        return tm
    tiles = [[tm.tiles[r % tm.rows][c % tm.cols] for c in range(tm.cols * scale)]
             for r in range(tm.rows * scale)]
    player = (tm.player_start[0] + (scale // 2) * tm.cols,
              tm.player_start[1] + (scale // 2) * tm.rows)
    enemies = [(c + sx * tm.cols, r + sy * tm.rows)
               for sy in range(scale) for sx in range(scale) for c, r in tm.enemy_starts]
    expanded = TileMap(tiles, tm.tile, player, enemies, tm.name, tcfg)
    if not expanded.is_connected():
        raise MapError(f"[{tm.name}] 확장된 맵의 구역들이 연결되지 않습니다.")
    expanded.validate_navigation(tcfg.navigation_radius)
    return expanded


def _generate_maze(rng, tcfg: TerrainConfig, cols, rows, name="random") -> TileMap:
    """넓은 방을 굵은 벽으로 나누고 DFS 통로로 잇는 하나의 전체 월드 미로.

    큰 선체의 중심이 지나는 모든 방/통로가 연결된다. 방 사이의 열린 연결을
    트리로 만들어 남은 벽도 외곽과 이어지고, 고립된 작은 장애물을 만들지 않는다.
    """
    minimum = max(1, 2 * math.ceil(tcfg.navigation_radius / tcfg.tile_size) + 1)
    if min(cols, rows) < minimum:
        raise MapError(f"[{name}] 반지름 {tcfg.navigation_radius:g}px 선체에는 최소 {minimum}칸 너비가 필요합니다.")
    passage = min(min(cols, rows), max(minimum, tcfg.min_passage_tiles))
    thickness = max(2, tcfg.wall_thickness)
    border = min(thickness, min(cols, rows) // 6)
    border = min(border, (min(cols, rows) - passage) // 2)
    inner_cols, inner_rows = cols - 2 * border, rows - 2 * border
    nx = max(1, (inner_cols + thickness) // (passage + thickness))
    ny = max(1, (inner_rows + thickness) // (passage + thickness))

    def spans(total, count):
        available = total - thickness * (count - 1)
        base, extra = divmod(available, count)
        positions, start = [], border
        for index in range(count):
            width = base + (index < extra)
            positions.append((start, width))
            start += width + thickness
        return positions

    x_spans, y_spans = spans(inner_cols, nx), spans(inner_rows, ny)
    tiles = [[WALL] * cols for _ in range(rows)]

    def carve(c0, r0, width, height, kind=EMPTY):
        for row in range(r0, r0 + height):
            for col in range(c0, c0 + width):
                tiles[row][col] = kind

    centers = {}
    for gy, (r0, height) in enumerate(y_spans):
        for gx, (c0, width) in enumerate(x_spans):
            carve(c0, r0, width, height)
            centers[gx, gy] = (c0 + width // 2, r0 + height // 2)
    root = (nx // 2, ny // 2)
    visited, stack, opened = {root}, [root], set()
    while stack:
        gx, gy = stack[-1]
        neighbors = [(gx + dc, gy + dr) for dc, dr in ((1, 0), (-1, 0), (0, 1), (0, -1))
                     if 0 <= gx + dc < nx and 0 <= gy + dr < ny and (gx + dc, gy + dr) not in visited]
        if not neighbors:
            stack.pop()
            continue
        nxt = neighbors[int(rng.integers(len(neighbors)))]
        ex, ey = nxt
        opened.add(frozenset(((gx, gy), nxt)))
        if gx != ex:
            left, right = sorted((gx, ex))
            c0, width = x_spans[left]
            r0, height = y_spans[gy]
            carve(c0 + width, r0 + (height - passage) // 2, thickness, passage)
        else:
            top, bottom = sorted((gy, ey))
            c0, width = x_spans[gx]
            r0, height = y_spans[top]
            carve(c0 + (width - passage) // 2, r0 + height, passage, thickness)
        visited.add(nxt)
        stack.append(nxt)

    # 선택 지형도 바닥/벽의 큰 면 안에 넣어 기본 미로의 통로 폭을 바꾸지 않는다.
    if tcfg.mud_enabled and tcfg.random_mud_density > 0:
        count = max(1, int(tcfg.random_mud_density * cols * rows / 9))
        for _ in range(min(count, len(centers))):
            cell = tuple(centers)[int(rng.integers(len(centers)))]
            c, r = centers[cell]
            carve(c - 1, r - 1, 3, 3, MUD)
    if tcfg.breakable_enabled and tcfg.random_breakable_density > 0:
        closed = []
        for gx, gy in centers:
            for ex, ey in ((gx + 1, gy), (gx, gy + 1)):
                if (ex, ey) not in centers or frozenset(((gx, gy), (ex, ey))) in opened:
                    continue
                if gx != ex:
                    c0, width = x_spans[gx]
                    r0, height = y_spans[gy]
                    closed.append((c0 + width, r0 + (height - thickness) // 2))
                else:
                    c0, width = x_spans[gx]
                    r0, height = y_spans[gy]
                    closed.append((c0 + (width - thickness) // 2, r0 + height))
        count = min(len(closed), max(1, int(tcfg.random_breakable_density * cols * rows / (thickness ** 2))))
        if count:
            for index in rng.choice(len(closed), size=count, replace=False):
                carve(*closed[int(index)], thickness, thickness, BREAKABLE)
    player = centers[root]
    enemies = sorted((point for node, point in centers.items() if node != root),
                     key=lambda point: (-(point[0] - player[0]) ** 2 - (point[1] - player[1]) ** 2, point))[:12]
    tm = TileMap(tiles, tcfg.tile_size, player, enemies, name, tcfg)
    if not tm.is_connected():
        raise MapError(f"[{name}] 생성된 미로의 바닥이 연결되지 않습니다.")
    tm.validate_navigation(tcfg.navigation_radius)
    return tm


def generate_random_map(rng, tcfg: TerrainConfig, cols, rows, max_attempts=50) -> TileMap:
    """기존 호출 규약으로 전체 월드를 가로지르는 연결 미로를 생성한다."""
    return _generate_maze(rng, tcfg, cols, rows)


def map_to_text(tm: TileMap) -> str:
    rows = []
    for r in range(tm.rows):
        line = "".join(TILE_TO_CHAR[t] for t in tm.tiles[r])
        rows.append(line)
    pc, pr = tm.player_start
    rows[pr] = rows[pr][:pc] + "P" + rows[pr][pc + 1:]
    for ec, er in tm.enemy_starts:
        rows[er] = rows[er][:ec] + "E" + rows[er][ec + 1:]
    return "\n".join(rows)
