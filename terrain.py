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

EMPTY, WALL, BUSH, MUD, BREAKABLE = 0, 1, 2, 3, 4
CHAR_TO_TILE = {".": EMPTY, "#": WALL, "*": BUSH, "~": MUD, "+": BREAKABLE, "P": EMPTY, "E": EMPTY}
TILE_TO_CHAR = {EMPTY: ".", WALL: "#", BUSH: "*", MUD: "~", BREAKABLE: "+"}

# 8방향 이웃 (dc, dr, 비용)
_NEIGHBORS = [(1, 0, 1.0), (-1, 0, 1.0), (0, 1, 1.0), (0, -1, 1.0),
              (1, 1, math.sqrt(2)), (1, -1, math.sqrt(2)), (-1, 1, math.sqrt(2)), (-1, -1, math.sqrt(2))]


class MapError(ValueError):
    pass


def grid_channels(tcfg: TerrainConfig):
    """관찰 격자에 들어가는 지형 채널 이름 (설정에 따라 고정)."""
    ch = ["wall", "bush"]
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
    def astar(self, start, goal, max_nodes=2000):
        """8방향 A* (벽 모서리 대각선 통과 금지). 타일 좌표 리스트 반환 (start 제외), 실패 시 []."""
        if start == goal or self.is_solid_tile(*goal):
            return []
        gx, gy = goal

        def h(c, r):
            ax, ay = abs(c - gx), abs(r - gy)
            return max(ax, ay) + (math.sqrt(2) - 1) * min(ax, ay)

        open_heap = [(h(*start), 0, 0.0, start)]
        came = {start: None}
        g = {start: 0.0}
        counter = 0
        while open_heap and counter < max_nodes:
            _, _, cost, cur = heapq.heappop(open_heap)
            if cur == goal:
                path = []
                while cur != start:
                    path.append(cur)
                    cur = came[cur]
                return path[::-1]
            if cost > g[cur]:
                continue
            c, r = cur
            for dc, dr, w in _NEIGHBORS:
                nc, nr = c + dc, r + dr
                if self.is_solid_tile(nc, nr):
                    continue
                if dc and dr and (self.is_solid_tile(c + dc, r) or self.is_solid_tile(c, r + dr)):
                    continue
                ng = cost + w
                if ng < g.get((nc, nr), float("inf")):
                    g[(nc, nr)] = ng
                    came[(nc, nr)] = cur
                    counter += 1
                    heapq.heappush(open_heap, (ng + h(nc, nr), counter, ng, (nc, nr)))
        return []

    def reachable_from(self, start):
        """4방향 BFS로 start에서 갈 수 있는 빈칸 집합."""
        seen = {start}
        q = deque([start])
        while q:
            c, r = q.popleft()
            for dc, dr in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                n = (c + dc, r + dr)
                if n not in seen and not self.is_solid_tile(*n):
                    seen.add(n)
                    q.append(n)
        return seen

    def is_connected(self):
        return len(self.reachable_from(self.player_start)) == len(self.free_tiles)


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
    return tm


_MAP_TEXT_CACHE = {}


def load_map(name, tcfg: TerrainConfig, cols, rows) -> TileMap:
    if name not in _MAP_TEXT_CACHE:
        path = resource_path(os.path.join("maps", f"{name}.txt"))
        if not os.path.exists(path):
            raise MapError(f"맵 파일이 없습니다: {path} (사용 가능: {list_maps()})")
        with open(path, encoding="utf-8") as f:
            _MAP_TEXT_CACHE[name] = f.read()
    return parse_map(_MAP_TEXT_CACHE[name], name, tcfg, cols, rows)


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
    return expanded


def generate_random_map(rng, tcfg: TerrainConfig, cols, rows, max_attempts=50) -> TileMap:
    """랜덤 맵 생성. BFS로 모든 빈칸이 연결될 때까지 다시 생성 (끝내 실패하면 고립된 칸을 벽으로 메움)."""
    p = (cols // 2, rows // 2)
    tiles = None
    for _ in range(max_attempts):
        tiles = [[EMPTY] * cols for _ in range(rows)]

        def stamp(kind, density, wmax, hmax, only_empty):
            target = int(density * cols * rows)
            count, guard = 0, 0
            while count < target and guard < 500:
                guard += 1
                w, h = int(rng.integers(1, wmax + 1)), int(rng.integers(1, hmax + 1))
                c0, r0 = int(rng.integers(0, cols - w + 1)), int(rng.integers(0, rows - h + 1))
                for r in range(r0, r0 + h):
                    for c in range(c0, c0 + w):
                        if (not only_empty or tiles[r][c] == EMPTY) and tiles[r][c] != kind:
                            tiles[r][c] = kind
                            count += 1

        stamp(WALL, tcfg.random_wall_density, 3, 3, False)
        stamp(BUSH, tcfg.random_bush_density, 3, 2, True)
        if tcfg.mud_enabled:
            stamp(MUD, tcfg.random_mud_density, 3, 3, True)
        if tcfg.breakable_enabled:
            stamp(BREAKABLE, tcfg.random_breakable_density, 2, 1, True)
        for r in range(p[1] - 1, p[1] + 2):          # 시작점 주변 비우기
            for c in range(p[0] - 1, p[0] + 2):
                tiles[r][c] = EMPTY
        tm = TileMap(tiles, tcfg.tile_size, p, [], "random", tcfg)
        if tm.is_connected():
            break
    else:
        reach = tm.reachable_from(p)
        for c, r in tm.free_tiles:
            if (c, r) not in reach:
                tiles[r][c] = WALL
        tm = TileMap(tiles, tcfg.tile_size, p, [], "random", tcfg)

    # 적 시작점: 플레이어에서 먼 빈칸 중 랜덤 4개
    far = [t for t in tm.free_tiles if abs(t[0] - p[0]) + abs(t[1] - p[1]) >= 10 and tm.tiles[t[1]][t[0]] == EMPTY]
    if far:
        idx = rng.choice(len(far), size=min(4, len(far)), replace=False)
        tm.enemy_starts = [far[int(i)] for i in idx]
    return tm


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
