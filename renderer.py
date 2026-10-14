"""pygame으로 GameCore 상태를 그리기만 한다. 게임 상태를 바꾸지 않는다.

우주 컨셉으로 그린다 (게임 규칙 이름 → 화면 표현):
  탱크 → 우주선 (포신 방향 = 기수 방향)
  도형 square / triangle / pentagon → 별 조각 / 작은 암석 행성 / 고리 행성
  지형 WALL → 성운 띠 (통과 불가), BUSH → 가스 구름 (안에 숨기), MUD → 중력장 (감속), BREAKABLE → 소행성
연출(별 반짝임, 등장/폭발 애니메이션 등)은 렌더러 내부 기록과 렌더러 전용 random만 쓴다
→ 게임 결과/재현성에 영향 없음.
"""
import math
import random

import pygame
import pygame.gfxdraw

from config import GameConfig
from terrain import WALL, BUSH, MUD, BREAKABLE
from progression import JOB_NAMES

COLORS = {
    "space_top": (6, 8, 22),
    "space_bottom": (16, 10, 34),
    "player": (70, 200, 255),
    "player_dark": (18, 84, 140),
    "enemy": (255, 92, 112),
    "enemy_dark": (130, 28, 56),
    "player_shot": (90, 220, 255),
    "enemy_shot": (255, 96, 160),
    "square": (255, 220, 110),      # 별 조각
    "triangle": (232, 124, 86),     # 암석 행성
    "pentagon": (128, 118, 255),    # 고리 행성
    "nebula": [(150, 70, 220), (80, 96, 240), (210, 78, 190)],
    "cloud": (34, 62, 94),
    "cloud_edge": (92, 150, 196),
    "gravity": (255, 150, 60),
    "rock": (122, 110, 102),
    "rock_edge": (70, 62, 58),
    "text": (180, 192, 226),
    "label": (130, 150, 205),
    "white": (255, 255, 255),
    "panel": (14, 20, 42),
    "panel_edge": (78, 98, 160),
    "hp_bg": (36, 40, 66),
}
SPAWN_FRAMES = 14   # 등장 애니메이션 길이
DEATH_FRAMES = 22   # 파괴/폭발 애니메이션 길이
FLASH_FRAMES = 5    # 피격 깜빡임 길이

# 우주선 선체 모양 (반지름 단위, 기수가 +x)
PLAYER_HULL = [(1.25, 0), (0.35, 0.32), (-0.15, 0.95), (-0.6, 0.95), (-0.45, 0.35),
               (-0.62, 0), (-0.45, -0.35), (-0.6, -0.95), (-0.15, -0.95), (0.35, -0.32)]
ENEMY_HULL = [(1.15, 0), (0.55, 0.38), (0.95, 0.9), (0.1, 0.8), (-0.6, 0.5),
              (-0.45, 0), (-0.6, -0.5), (0.1, -0.8), (0.95, -0.9), (0.55, -0.38)]


def _darken(c, f=0.7):
    return tuple(int(v * f) for v in c)


def _mix(a, b, t):
    return tuple(int(x + (y - x) * t) for x, y in zip(a, b))


def _hp_color(ratio):
    if ratio > 0.5:
        return _mix((250, 210, 80), (90, 230, 170), (ratio - 0.5) * 2)
    return _mix((245, 80, 100), (250, 210, 80), ratio * 2)


class Renderer:
    def __init__(self, cfg: GameConfig, caption: str = "Space Skirmish - RL Demo"):
        self.cfg = cfg
        if not 0 < cfg.camera_zoom <= 1:
            raise ValueError("camera_zoom은 0보다 크고 1 이하여야 합니다.")
        self.screen = pygame.display.set_mode((cfg.width, cfg.height))
        self.view_width = round(cfg.width / cfg.camera_zoom)
        self.view_height = round(cfg.height / cfg.camera_zoom)
        self._view = pygame.Surface((self.view_width, self.view_height)).convert()
        pygame.display.set_caption(caption)
        self.clock = pygame.time.Clock()
        # 시스템 폰트가 없으면 pygame 기본 폰트로 대체됨 → 실행 파일에서도 안전
        sans = "malgungothic,applegothic,nanumgothic,notosanscjkkr,segoeui,arial"
        self.font_hud = pygame.font.SysFont(sans, 22, bold=True)
        self.font_label = pygame.font.SysFont(sans, 13, bold=True)
        self.font_small = pygame.font.SysFont(sans, 14)
        self.font_big = pygame.font.SysFont(sans, 56, bold=True)
        self.font_card = pygame.font.SysFont(sans, 24, bold=True)
        self.font_body = pygame.font.SysFont(sans, 17)
        self.font_mono = pygame.font.SysFont("consolas,couriernew,monospace", 13)

        self._rand = random.Random(2024)   # 렌더러 전용 (배경 별 배치 등)
        self._glow_cache = {}
        self._bg = self._make_background()
        self.camera_x = self.camera_y = 0
        self._twinkles = [(self._rand.uniform(0, cfg.world_width), self._rand.uniform(0, cfg.world_height),
                           self._rand.uniform(0, 6.28), self._rand.uniform(0.02, 0.07))
                          for _ in range(45 * cfg.world_scale ** 2)]
        self._shape_sprites = {k: self._make_shape_sprite(k) for k in ("square", "triangle", "pentagon")}
        self._terrain_key = None
        self._floor = None        # 배경 + 성운/중력장/소행성 캐시
        self._cloud_layer = None  # 우주선 위에 덮는 가스 구름 레이어 캐시
        self._fx_layer = pygame.Surface((self.view_width, self.view_height), pygame.SRCALPHA)
        self._tick = 0

        # 연출용 기록 (게임 상태와 무관)
        self._last_frame = -1
        self._first_seen = {}   # id -> 처음 본 frame (등장 애니메이션)
        self._prev_hp = {}      # 도형 id -> 이전 hp (피격 깜빡임)
        self._hit_frame = {}    # 도형 id -> 마지막 피격 frame
        self._prev_shapes = {}  # id -> 이전 프레임 도형 (사라짐 감지)
        self._prev_alive = {}   # 적 id -> 이전 alive
        self._ghosts = []       # 파괴 애니메이션: dict(kind, x, y, r, angle, color, age)

    # ------------------------------------------------------------------
    # 빛 번짐 스프라이트 (BLEND_ADD로 더해서 발광 효과)
    # ------------------------------------------------------------------
    def _glow(self, radius, color, intensity=1.0):
        radius = max(2, int(radius))
        key = (radius, color, round(intensity, 2))
        surf = self._glow_cache.get(key)
        if surf is None:
            surf = pygame.Surface((radius * 2, radius * 2))
            surf.fill((0, 0, 0))
            for r in range(radius, 0, -1):
                k = (1 - r / radius) ** 2 * intensity
                pygame.draw.circle(surf, tuple(min(255, int(c * k)) for c in color), (radius, radius), r)
            if len(self._glow_cache) > 600:
                self._glow_cache.clear()
            self._glow_cache[key] = surf
        return surf

    def _blit_glow(self, target, x, y, radius, color, intensity=1.0):
        g = self._glow(radius, color, intensity)
        target.blit(g, (int(x) - g.get_width() // 2, int(y) - g.get_height() // 2),
                    special_flags=pygame.BLEND_ADD)

    # ------------------------------------------------------------------
    # 배경: 그라데이션 우주 + 희미한 성운 + 별
    # ------------------------------------------------------------------
    def _make_background(self):
        w, h = self.cfg.world_width, self.cfg.world_height
        rnd = self._rand
        surf = pygame.Surface((w, h))
        for y in range(h):
            pygame.draw.line(surf, _mix(COLORS["space_top"], COLORS["space_bottom"], y / h), (0, y), (w, y))
        haze = pygame.Surface((w, h))
        haze.fill((0, 0, 0))
        for _ in range(6):
            col = rnd.choice([(70, 40, 130), (30, 50, 120), (110, 40, 100)])
            self._blit_glow(haze, rnd.uniform(0, w), rnd.uniform(0, h), rnd.uniform(160, 300), col, 0.35)
        surf.blit(haze, (0, 0), special_flags=pygame.BLEND_ADD)
        for _ in range(260 * self.cfg.world_scale ** 2):
            x, y = rnd.randrange(w), rnd.randrange(h)
            b = rnd.choice([70, 90, 120, 160, 210])
            tint = rnd.choice([(1, 1, 1), (0.8, 0.9, 1), (1, 0.9, 0.8)])
            surf.set_at((x, y), tuple(int(b * t) for t in tint))
        for _ in range(14):   # 밝은 별 몇 개
            x, y = rnd.randrange(w), rnd.randrange(h)
            self._blit_glow(surf, x, y, 7, (200, 210, 255), 0.7)
            surf.set_at((x, y), (255, 255, 255))
        pygame.draw.rect(surf, (60, 72, 120), (0, 0, w, h), 2)
        return surf

    def _draw_twinkles(self):
        for x, y, phase, speed in self._twinkles:
            b = 0.5 + 0.5 * math.sin(self._tick * speed + phase)
            c = int(90 + 165 * b)
            sx, sy = self.world_to_view(x, y)
            if -2 <= sx <= self.view_width + 2 and -2 <= sy <= self.view_height + 2:
                pygame.draw.circle(self.screen, (c, c, min(255, c + 20)), (int(sx), int(sy)), 1 if b < 0.7 else 2)

    # ------------------------------------------------------------------
    # 지형 (지형이 바뀔 때만 다시 그림)
    # ------------------------------------------------------------------
    def _ensure_terrain(self, tm):
        key = (id(tm), tm.version)
        if key == self._terrain_key:
            return
        self._terrain_key = key
        T = tm.tile
        W, H = self.cfg.world_width, self.cfg.world_height
        floor = self._bg.copy()
        add = pygame.Surface((W, H))
        add.fill((0, 0, 0))
        body = pygame.Surface((W, H), pygame.SRCALPHA)
        nebula_tiles = []

        def h(c, r, k=0):  # 타일마다 고정된 의사 난수 (0~1)
            return ((c * 92821 + r * 68917 + k * 1237) % 1009) / 1009

        for r in range(tm.rows):
            for c in range(tm.cols):
                kind = tm.tiles[r][c]
                cx, cy = (c + 0.5) * T, (r + 0.5) * T
                if kind == WALL:
                    # 성운 띠: 반투명 몸체 + 빛 번짐. 이웃 칸끼리 겹쳐 하나의 띠처럼 보임
                    col = COLORS["nebula"][int(h(c, r) * 3)]
                    nebula_tiles.append((cx, cy, col))
                    self._blit_glow(add, cx, cy, T * 1.05, col, 0.55)
                    self._blit_glow(add, cx + (h(c, r, 1) - 0.5) * T * 0.4, cy + (h(c, r, 2) - 0.5) * T * 0.4,
                                    T * 0.55, _mix(col, (255, 255, 255), 0.35), 0.45)
                elif kind == MUD:
                    self._blit_glow(add, cx, cy, T * 0.75, COLORS["gravity"], 0.32)
        # 성운 몸체: 바깥 안개 → 진한 안쪽 순으로 전체를 그려 막힌 영역이 분명히 보이게
        for cx, cy, col in nebula_tiles:
            self._aa_circle(body, cx, cy, T * 0.78, (*_mix(col, (40, 30, 80), 0.5), 120))
        for cx, cy, col in nebula_tiles:
            self._aa_circle(body, cx, cy, T * 0.64, (*_darken(col, 0.5), 215))
        floor.blit(body, (0, 0))
        floor.blit(add, (0, 0), special_flags=pygame.BLEND_ADD)

        for r in range(tm.rows):
            for c in range(tm.cols):
                kind = tm.tiles[r][c]
                cx, cy = (c + 0.5) * T, (r + 0.5) * T
                if kind == WALL:   # 성운 속 작은 별들
                    for k in range(7):
                        x = int(c * T + h(c, r, k + 3) * T)
                        y = int(r * T + h(c, r, k + 11) * T)
                        b = 150 + int(h(c, r, k + 19) * 105)
                        floor.set_at((x, y), (b, b, 255))
                        if k == 0:
                            pygame.draw.circle(floor, (235, 235, 255), (x, y), 1)
                elif kind == MUD:  # 중력장: 소용돌이 고리
                    for k, rr in enumerate((0.42, 0.28, 0.15)):
                        rect = pygame.Rect(0, 0, int(T * rr * 2), int(T * rr * 2))
                        rect.center = (int(cx), int(cy))
                        a0 = h(c, r, k) * 6.28
                        pygame.draw.arc(floor, _darken(COLORS["gravity"], 0.75 - 0.15 * k), rect, a0, a0 + 4.2, 2)

        # 소행성 (부서지는 벽): 울퉁불퉁한 바위 + 체력에 따라 금
        for (c, r), hp in tm.hp.items():
            cx, cy = (c + 0.5) * T, (r + 0.5) * T
            pts = []
            for k in range(10):
                a = 2 * math.pi * k / 10
                rad = T * (0.4 + 0.1 * h(c, r, k))
                pts.append((cx + math.cos(a) * rad, cy + math.sin(a) * rad))
            self._aa_poly(floor, [(x + 3, y + 4) for x, y in pts], (10, 10, 20))
            self._aa_poly(floor, pts, COLORS["rock_edge"])
            inner = [(cx + (x - cx) * 0.86, cy + (y - cy) * 0.86) for x, y in pts]
            self._aa_poly(floor, inner, COLORS["rock"])
            self._aa_circle(floor, cx - T * 0.12, cy - T * 0.14, T * 0.2, _mix(COLORS["rock"], (255, 255, 255), 0.12))
            for k, (ox, oy, rr) in enumerate(((0.12, 0.1, 0.09), (-0.15, 0.15, 0.06), (0.05, -0.2, 0.05))):
                self._aa_circle(floor, cx + ox * T, cy + oy * T, rr * T, _darken(COLORS["rock"], 0.8))
            dmg = 1 - hp / tm.breakable_hp_max
            cracks = [((-0.25, -0.2), (0.0, 0.0), (-0.1, 0.3)), ((0.3, -0.15), (0.05, 0.05), (0.25, 0.28)),
                      ((0.0, -0.32), (0.02, -0.05), (-0.28, 0.08))]
            for crack in cracks[:int(dmg * 3.999)]:
                pygame.draw.lines(floor, (40, 34, 30), False, [(cx + x * T, cy + y * T) for x, y in crack], 2)
        self._floor = floor

        # 가스 구름 (수풀): 테두리 → 채움 → 결 순으로 그려 하나의 구름처럼
        layer = pygame.Surface((W, H), pygame.SRCALPHA)
        blobs = []
        for r in range(tm.rows):
            for c in range(tm.cols):
                if tm.tiles[r][c] == BUSH:
                    for k, (ox, oy) in enumerate(((0.28, 0.3), (0.72, 0.28), (0.3, 0.72), (0.7, 0.7), (0.5, 0.5))):
                        blobs.append(((c + ox) * T, (r + oy) * T, T * (0.32 + h(c, r, k) * 0.1)))
        rim = _mix(COLORS["cloud"], COLORS["cloud_edge"], 0.7)
        for x, y, rad in blobs:
            self._aa_circle(layer, x, y, rad + 2, rim)
        for x, y, rad in blobs:
            self._aa_circle(layer, x, y, rad, COLORS["cloud"])
        # 구름 속 희미한 별빛
        for r in range(tm.rows):
            for c in range(tm.cols):
                if tm.tiles[r][c] == BUSH:
                    for k in range(3):
                        x = int(c * T + 6 + h(c, r, k + 50) * (T - 12))
                        y = int(r * T + 6 + h(c, r, k + 60) * (T - 12))
                        layer.set_at((x, y), (170, 205, 235, 255))
        layer.set_alpha(240)
        self._cloud_layer = layer

    # ------------------------------------------------------------------
    # 도형 → 천체 스프라이트 (한 번 만들어두고 회전/확대해서 씀)
    # ------------------------------------------------------------------
    def _make_shape_sprite(self, kind):
        from config import SHAPE_TYPES
        r = SHAPE_TYPES[kind]["radius"]
        col = COLORS[kind]
        size = int(r * 3.6) + 8
        c = size / 2
        s = pygame.Surface((size, size), pygame.SRCALPHA)
        # 은은한 후광 (알파 원)
        for k in range(12, 0, -1):
            rr = r * (1 + 0.065 * k)
            pygame.gfxdraw.filled_circle(s, int(c), int(c), int(rr), (*col, int(10 * (1 - k / 13))))
        if kind == "square":        # 별 조각: 4갈래 별
            pts = []
            for k in range(8):
                a = math.pi / 4 * k
                rad = r * (1.25 if k % 2 == 0 else 0.45)
                pts.append((c + math.cos(a) * rad, c + math.sin(a) * rad))
            self._aa_poly(s, pts, _darken(col, 0.75))
            self._aa_poly(s, [(c + (x - c) * 0.8, c + (y - c) * 0.8) for x, y in pts], col)
            self._aa_circle(s, c, c, r * 0.28, (255, 250, 230))
        elif kind == "triangle":    # 암석 행성: 음영 + 크레이터
            self._aa_circle(s, c, c, r, _darken(col, 0.6))
            self._aa_circle(s, c - r * 0.15, c - r * 0.15, r * 0.82, col)
            self._aa_circle(s, c - r * 0.35, c - r * 0.38, r * 0.25, _mix(col, (255, 255, 255), 0.25))
            for ox, oy, rr in ((0.3, 0.2, 0.22), (-0.25, 0.35, 0.14), (0.1, -0.4, 0.12)):
                self._aa_circle(s, c + ox * r, c + oy * r, rr * r, _darken(col, 0.78))
        else:                       # 고리 행성: 뒤쪽 고리 → 줄무늬 행성 → 앞쪽 고리
            ring = pygame.Rect(0, 0, int(r * 3.3), int(r * 0.95))
            ring.center = (int(c), int(c))
            ring_col = _mix(col, (255, 230, 200), 0.45)
            pygame.draw.ellipse(s, (*ring_col, 200), ring, 3)
            planet = pygame.Surface((size, size), pygame.SRCALPHA)
            self._aa_circle(planet, c, c, r, col)
            for k, dy in enumerate((-0.55, -0.2, 0.2, 0.55)):
                band = _mix(col, (255, 255, 255), 0.18) if k % 2 == 0 else _darken(col, 0.82)
                pygame.draw.rect(planet, band, (c - r, c + dy * r - r * 0.09, 2 * r, r * 0.18))
            mask = pygame.Surface((size, size), pygame.SRCALPHA)
            self._aa_circle(mask, c, c, r, (255, 255, 255, 255))
            planet.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MIN)
            s.blit(planet, (0, 0))
            shade = pygame.Surface((size, size), pygame.SRCALPHA)
            self._aa_circle(shade, c + r * 0.3, c + r * 0.3, r * 0.95, (0, 0, 20, 70))
            shade.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MIN)
            s.blit(shade, (0, 0))
            pygame.draw.arc(s, ring_col, ring, math.pi, 2 * math.pi, 3)
        flash = s.copy()
        flash.fill((110, 110, 110, 0), special_flags=pygame.BLEND_RGBA_ADD)
        return s, flash

    # ------------------------------------------------------------------
    # 기본 도형 (안티앨리어싱)
    # ------------------------------------------------------------------
    def _aa_poly(self, surf, pts, color):
        ipts = [(int(round(x)), int(round(y))) for x, y in pts]
        pygame.gfxdraw.filled_polygon(surf, ipts, color)
        pygame.gfxdraw.aapolygon(surf, ipts, color)

    def _aa_circle(self, surf, x, y, r, color):
        x, y, r = int(round(x)), int(round(y)), max(1, int(round(r)))
        pygame.gfxdraw.filled_circle(surf, x, y, r, color)
        pygame.gfxdraw.aacircle(surf, x, y, r, color)

    def _rect_rot(self, cx, cy, ang, length, half_w, start=0.0):
        ca, sa = math.cos(ang), math.sin(ang)
        x0, y0 = cx + ca * start, cy + sa * start
        x1, y1 = cx + ca * length, cy + sa * length
        return [(x0 - sa * half_w, y0 + ca * half_w), (x0 + sa * half_w, y0 - ca * half_w),
                (x1 + sa * half_w, y1 - ca * half_w), (x1 - sa * half_w, y1 + ca * half_w)]

    # ------------------------------------------------------------------
    # 연출 기록 갱신
    # ------------------------------------------------------------------
    def _track(self, game):
        f = game.frame
        if f < self._last_frame:  # 재시작
            self._first_seen.clear(); self._prev_hp.clear(); self._hit_frame.clear()
            self._prev_shapes.clear(); self._prev_alive.clear(); self._ghosts.clear()
        # 파괴 애니메이션 진행량: 게임 프레임 기준, 단 게임오버로 멈춘 동안에도 끝까지 재생
        delta = f - self._last_frame if f > self._last_frame else (1 if game.game_over else 0)
        for g in self._ghosts:
            g["age"] += delta
        self._last_frame = f

        cur = {s.id: s for s in game.shapes}
        for sid, s in self._prev_shapes.items():
            if sid not in cur:
                self._ghosts.append(dict(kind=s.kind, x=s.x, y=s.y, r=s.radius, angle=s.angle,
                                         color=COLORS[s.kind], age=0))
        for s in game.shapes:
            self._first_seen.setdefault(s.id, f)
            if s.hp < self._prev_hp.get(s.id, s.hp):
                self._hit_frame[s.id] = f
            self._prev_hp[s.id] = s.hp
        self._prev_shapes = {sid: _ShapeSnap(s) for sid, s in cur.items()}

        for e in game.enemies:
            was = self._prev_alive.get(e.id, e.alive)
            if was and not e.alive:
                self._ghosts.append(dict(kind="ship", x=e.x, y=e.y, r=e.radius, angle=e.angle,
                                         color=COLORS["enemy"], age=0))
            if not was and e.alive:
                self._first_seen[e.id] = f
            self._first_seen.setdefault(e.id, f)
            self._prev_alive[e.id] = e.alive
        p = game.player
        if self._prev_alive.get(p.id, True) and not p.alive:
            self._ghosts.append(dict(kind="ship", x=p.x, y=p.y, r=p.radius, angle=p.angle,
                                     color=COLORS["player"], age=0))
        self._prev_alive[p.id] = p.alive

        self._ghosts = [g for g in self._ghosts if g["age"] < DEATH_FRAMES]
        # 오래된 id 정리
        if len(self._first_seen) > 400:
            live = set(cur) | {e.id for e in game.enemies} | {p.id}
            self._first_seen = {k: v for k, v in self._first_seen.items() if k in live}
            self._prev_hp = {k: v for k, v in self._prev_hp.items() if k in live}
            self._hit_frame = {k: v for k, v in self._hit_frame.items() if k in live}

    def _spawn_scale(self, oid, frame):
        t = (frame - self._first_seen.get(oid, -999)) / SPAWN_FRAMES
        if t >= 1:
            return 1.0
        t = max(0.0, t)
        return 1 - (1 - t) ** 3  # ease-out

    # ------------------------------------------------------------------
    # 그리기
    # ------------------------------------------------------------------
    def world_to_view(self, x, y):
        return x - self.camera_x, y - self.camera_y

    def world_to_screen(self, x, y):
        vx, vy = self.world_to_view(x, y)
        return vx * self.cfg.width / self.view_width, vy * self.cfg.height / self.view_height

    def screen_to_world(self, x, y):
        return (x * self.view_width / self.cfg.width + self.camera_x,
                y * self.view_height / self.cfg.height + self.camera_y)

    def _update_camera(self, player):
        c = self.cfg
        self.camera_x = (int(max(0, min(player.x - self.view_width / 2, c.world_width - self.view_width)))
                         if c.world_width >= self.view_width else (c.world_width - self.view_width) // 2)
        self.camera_y = (int(max(0, min(player.y - self.view_height / 2, c.world_height - self.view_height)))
                         if c.world_height >= self.view_height else (c.world_height - self.view_height) // 2)

    def _visible(self, x, y, margin=100):
        sx, sy = self.world_to_view(x, y)
        return -margin <= sx <= self.view_width + margin and -margin <= sy <= self.view_height + margin

    def draw(self, game, debug_lines=None, paused=False, show_ai=False, rewards_open=False):
        self._tick += 1
        self._update_camera(game.player)
        self._track(game)
        self._ensure_terrain(game.terrain)
        self._flash_on = not game.game_over  # 게임오버로 멈춘 화면에서는 깜빡임 끔
        display = self.screen
        self.screen = scr = self._view
        scr.fill(COLORS["space_top"])
        scr.blit(self._floor, (-self.camera_x, -self.camera_y))
        self._draw_twinkles()
        f = game.frame
        p = game.player
        player_hidden = p.alive and game.is_hidden(p)

        for s in game.shapes:
            if self._visible(s.x, s.y):
                self._draw_shape(s, f)
        for e in game.enemies:
            if e.alive and self._visible(e.x, e.y):
                self._draw_ship(e, f, ENEMY_HULL, COLORS["enemy"], COLORS["enemy_dark"])
        if p.alive and not player_hidden:
            self._draw_ship(p, f, PLAYER_HULL, COLORS["player"], COLORS["player_dark"], is_player=True)
        # 가스 구름은 우주선 위에 덮는다 → 안에 있는 적은 실제로 가려짐
        scr.blit(self._cloud_layer, (-self.camera_x, -self.camera_y))
        if player_hidden:  # 내 우주선만 반투명하게 보여줌
            self._fx_layer.fill((0, 0, 0, 0))
            self.screen = self._fx_layer
            self._draw_ship(p, f, PLAYER_HULL, COLORS["player"], COLORS["player_dark"], is_player=True)
            self.screen = scr
            self._fx_layer.set_alpha(150)
            scr.blit(self._fx_layer, (0, 0))
        for b in game.bullets:
            if self._visible(b.x, b.y):
                self._draw_bullet(b)
        for g in self._ghosts:
            if self._visible(g["x"], g["y"]):
                self._draw_ghost(g)
        # 체력바는 모든 물체 위에 (숨은 적의 체력바는 그리지 않음)
        for s in game.shapes:
            if s.hp < s.max_hp:
                self._hp_bar(s.x, s.y + s.radius + 9, s.radius * 2.2, s.hp / s.max_hp)
        for e in game.enemies:
            if e.alive and e.hp < e.max_hp and not game.is_hidden(e):
                self._hp_bar(e.x, e.y + e.radius + 12, e.radius * 2.6, e.hp / e.max_hp)
        if p.alive and p.hp < p.max_hp:
            self._hp_bar(p.x, p.y + p.radius + 12, p.radius * 2.6, p.hp / p.max_hp)
        if show_ai:
            self._draw_ai_debug(game)

        self.screen = display
        pygame.transform.smoothscale(scr, (self.cfg.width, self.cfg.height), display)
        self._draw_hud(game, paused, show_notice=not rewards_open)
        if debug_lines:
            self._draw_debug(debug_lines)
        if game.game_over:
            self._draw_game_over(game)
        elif rewards_open:
            self._draw_rewards(game)
        elif paused:
            self._draw_card(["일시정지"], ["P / ESC: 계속    Q: 종료    R: 새 게임"])

    def _draw_shape(self, s, f):
        sprite, flash = self._shape_sprites[s.kind]
        img = flash if self._flash_on and f - self._hit_frame.get(s.id, -999) < FLASH_FRAMES else sprite
        scale = self._spawn_scale(s.id, f)
        if scale < 0.08:
            return
        img = pygame.transform.rotozoom(img, -math.degrees(s.angle), scale)
        x, y = self.world_to_view(s.x, s.y)
        self.screen.blit(img, img.get_rect(center=(int(x), int(y))))

    def _draw_bullet(self, b):
        color = COLORS["player_shot"] if b.team == "player" else COLORS["enemy_shot"]
        r = b.radius
        x, y = self.world_to_view(b.x, b.y)
        tail = (x - b.vx * 2.2, y - b.vy * 2.2)
        pygame.draw.line(self.screen, _darken(color, 0.55), tail, (x, y), max(2, int(r * 1.1)))
        self._blit_glow(self.screen, x, y, r * 3.2, color, 0.75)
        self._aa_circle(self.screen, x, y, r * 0.75, _mix(color, (255, 255, 255), 0.6))

    def _draw_ship(self, t, f, hull, color, dark, is_player=False):
        c = self.cfg
        x, y = self.world_to_view(t.x, t.y)
        scale = self._spawn_scale(t.id, f)
        if scale < 0.08:
            return
        if self._flash_on and f - t.last_hit_frame < FLASH_FRAMES:
            color = _mix(color, (255, 255, 255), 0.55)
        R = t.radius * scale
        ca, sa = math.cos(t.angle), math.sin(t.angle)

        def tf(px, py):
            return x + (px * ca - py * sa) * R, y + (px * sa + py * ca) * R

        # 엔진 불꽃: 속도가 빠를수록 길게
        spd = min(1.0, math.hypot(t.vx, t.vy) / (c.max_speed * t.accel_scale))
        flick = 0.08 * ((self._tick // 2) % 3)
        length = 0.35 + 0.55 * spd + flick
        ex, ey = tf(-0.62, 0)
        self._blit_glow(self.screen, ex, ey, R * (0.55 + 0.4 * spd), (255, 140, 60), 0.8)
        self._aa_poly(self.screen, [tf(-0.55, 0.24), tf(-0.55, -0.24), tf(-0.6 - length, 0)], (255, 150, 70))
        self._aa_poly(self.screen, [tf(-0.55, 0.12), tf(-0.55, -0.12), tf(-0.6 - length * 0.6, 0)], (255, 235, 170))

        # 보호막 (충돌 범위 표시)
        pygame.gfxdraw.aacircle(self.screen, int(x), int(y), int(R), (*color, 70))

        # 포 (발사 직후 반동으로 짧아짐)
        recoil = max(0.0, (t.cooldown - (t.fire_cooldown_max - 6)) / 6) * 6
        gun_len = (c.barrel_length - recoil) * scale
        self._aa_poly(self.screen, self._rect_rot(x, y, t.angle, gun_len, 4.5 * scale, R * 0.4), dark)
        self._aa_poly(self.screen, self._rect_rot(x, y, t.angle, gun_len - 1.5, 2.8 * scale, R * 0.4),
                      (200, 210, 228))

        # 선체
        pts = [tf(x, y) for x, y in hull]
        self._aa_poly(self.screen, pts, color)
        pygame.draw.polygon(self.screen, dark, pts, 2)
        panel = [tf(x * 0.55 - 0.05, y * 0.55) for x, y in hull]
        self._aa_poly(self.screen, panel, _mix(color, (255, 255, 255), 0.22))
        # 조종석
        cx, cy = tf(0.28, 0)
        self._aa_circle(self.screen, cx, cy, R * 0.22, dark)
        self._aa_circle(self.screen, cx, cy, R * 0.16, (225, 242, 255))

        if is_player:
            label = self.font_label.render("YOU", True, COLORS["white"])
            pos = label.get_rect(center=(x, y - t.radius - 16))
            self.screen.blit(self.font_label.render("YOU", True, (0, 0, 0)), pos.move(1, 1))
            self.screen.blit(label, pos)

    def _draw_ghost(self, g):
        """파괴 연출: 천체는 커지며 사라지고, 우주선은 폭발."""
        t = g["age"] / DEATH_FRAMES
        x, y = self.world_to_view(g["x"], g["y"])
        if g["kind"] == "ship":
            r = g["r"] * (1 + 2.2 * t)
            self._blit_glow(self.screen, x, y, r * 1.4, (255, 170, 80), round((1 - t) * 8) / 8 * 1.2)
            ring = _mix(g["color"], (255, 255, 255), 0.4)
            pygame.gfxdraw.aacircle(self.screen, int(x), int(y), int(r), (*ring, int(255 * (1 - t))))
            pygame.gfxdraw.aacircle(self.screen, int(x), int(y), int(r) - 1, (*ring, int(200 * (1 - t))))
            return
        sprite = self._shape_sprites[g["kind"]][1]
        img = pygame.transform.rotozoom(sprite, -math.degrees(g["angle"]), 1 + 0.7 * t)
        img.set_alpha(int(255 * (1 - t) ** 1.5))
        self.screen.blit(img, img.get_rect(center=(int(x), int(y))))
        self._blit_glow(self.screen, x, y, g["r"] * 2, g["color"], round((1 - t) * 8) / 8 * 0.6)

    def _hp_bar(self, cx, y, w, ratio, h=6):
        if not self._visible(cx, y):
            return
        cx, y = self.world_to_view(cx, y)
        x = int(cx - w / 2)
        w = int(w)
        pygame.draw.rect(self.screen, COLORS["hp_bg"], (x - 1, y - 1, w + 2, h + 2), border_radius=(h + 2) // 2)
        fill = max(h, int(w * ratio))
        pygame.draw.rect(self.screen, _hp_color(ratio), (x, y, fill, h), border_radius=h // 2)

    def _draw_ai_debug(self, game):
        tm = game.terrain
        p = game.player
        for e in game.enemies:
            if not e.alive:
                continue
            if e.ai_path:
                pts = [self.world_to_view(e.x, e.y)] + [self.world_to_view(*tm.center(c, r)) for c, r in e.ai_path]
                pygame.draw.lines(self.screen, (235, 190, 40), False, pts, 2)
            if e.ai_can_see:
                pygame.draw.line(self.screen, (60, 220, 110), self.world_to_view(e.x, e.y), self.world_to_view(p.x, p.y), 2)
            if e.ai_goal:
                gx, gy = self.world_to_view(*e.ai_goal)
                pygame.draw.circle(self.screen, (235, 190, 40), (int(gx), int(gy)), 5, 2)

    # ------------------------------------------------------------------
    # HUD
    # ------------------------------------------------------------------
    def _panel(self, rect, alpha=170, radius=10):
        surf = pygame.Surface(rect.size, pygame.SRCALPHA)
        pygame.draw.rect(surf, (*COLORS["panel"], alpha), surf.get_rect(), border_radius=radius)
        pygame.draw.rect(surf, (*COLORS["panel_edge"], 150), surf.get_rect(), 1, border_radius=radius)
        self.screen.blit(surf, rect.topleft)

    def _draw_hud(self, game, paused, show_notice=True):
        p = game.player
        W, H = self.cfg.width, self.cfg.height
        secs = game.frame / self.cfg.fps

        ammo = f"탄약 {p.ammo} / {p.max_ammo}" if game.cfg.limited_ammo else "탄약 무제한"
        rect = pygame.Rect(W - 224, 14, 210, 70)
        self._panel(rect)
        color = (255, 130, 100) if game.cfg.limited_ammo and p.ammo == 0 else COLORS["white"]
        self.screen.blit(self.font_body.render(ammo, True, color), (rect.x + 14, rect.y + 10))
        self.screen.blit(self.font_small.render("P / ESC: 일시정지", True, COLORS["text"]), (rect.x + 14, rect.y + 42))
        if game.cfg.limited_ammo and p.ammo == 0 and not game.game_over:
            text = self.font_body.render("탄약 소진! [L] 보급 카드 또는 [R] 새 게임", True, (255, 165, 100))
            self.screen.blit(text, text.get_rect(midtop=(W / 2, 218)))

        # 좌상단: 점수/처치/시간
        items = [(self.font_label.render(label, True, COLORS["label"]),
                  self.font_hud.render(value, True, COLORS["white"]))
                 for label, value in (("SCORE", f"{game.score:,}"), ("KILLS", str(game.kills)),
                                      ("TIME", f"{int(secs) // 60}:{int(secs) % 60:02d}"))]
        width = 10 + sum(l.get_width() + v.get_width() + 18 for l, v in items)
        rect = pygame.Rect(14, 14, width, 40)
        self._panel(rect)
        x = rect.x + 14
        for lab, val in items:
            self.screen.blit(lab, (x, rect.y + 13))
            self.screen.blit(val, (x + lab.get_width() + 6, rect.y + 6))
            x += lab.get_width() + val.get_width() + 18

        if game.cfg.progression_enabled:
            self._draw_progression(game, show_notice)

        # 하단 중앙: 선체 내구도
        w, h = 320, 18
        bx, by = W / 2 - w / 2, H - 42
        self._panel(pygame.Rect(bx - 6, by - 6, w + 12, h + 12), 170, 15)
        ratio = p.hp / p.max_hp
        pygame.draw.rect(self.screen, COLORS["hp_bg"], (bx, by, w, h), border_radius=h // 2)
        if ratio > 0:
            col = _hp_color(ratio)
            pygame.draw.rect(self.screen, col, (bx, by, max(h, w * ratio), h), border_radius=h // 2)
            pygame.draw.rect(self.screen, _mix(col, (255, 255, 255), 0.4),
                             (bx + 6, by + 3, max(0, w * ratio - 12), 3), border_radius=2)
        txt = f"HULL  {math.ceil(p.hp)} / {p.max_hp:.0f}"
        r = self.font_label.render(txt, True, COLORS["white"]).get_rect(center=(W / 2, by + h / 2))
        self.screen.blit(self.font_label.render(txt, True, (0, 0, 0)), r.move(1, 1))
        self.screen.blit(self.font_label.render(txt, True, COLORS["white"]), r)

        # 조작 안내: 시작 10초 동안과 일시정지 중에만
        if secs < 10 or paused:
            hint = "WASD: 이동   커서: 조준   좌클릭: 발사   L: 보상   P / ESC: 일시정지   R: 새 게임"
            surf = self.font_small.render(hint, True, COLORS["text"])
            self.screen.blit(surf, surf.get_rect(midbottom=(W / 2, by - 14)))

    def _draw_progression(self, game, show_notice):
        p = game.player
        panel = pygame.Rect(14, 64, 300, 90)
        self._panel(panel)
        title = f"Lv.{game.level}  {JOB_NAMES[p.job]}"
        self.screen.blit(self.font_hud.render(title, True, COLORS["white"]), (28, 72))
        bar = pygame.Rect(28, 107, 270, 10)
        pygame.draw.rect(self.screen, COLORS["hp_bg"], bar, border_radius=5)
        fill = bar.copy()
        fill.width = int(bar.width * game.xp / game.xp_to_next_level)
        if fill.width:
            pygame.draw.rect(self.screen, COLORS["player"], fill, border_radius=5)
        xp = f"경험치 {game.xp} / {game.xp_to_next_level}   보상 {game.pending_rewards}개"
        self.screen.blit(self.font_small.render(xp, True, COLORS["text"]), (28, 126))
        message = ""
        if game.pending_rewards and not game.game_over:
            message = f"레벨 업! [L] 보상 선택 — 남은 보상 {game.pending_rewards}개"
        elif game.frame < game.reward_message_until:
            message = f"{game.last_reward} 적용 완료!"
        if message and show_notice:
            text = self.font_body.render(message, True, (255, 230, 130))
            box = pygame.Rect(0, 0, text.get_width() + 36, 44)
            box.midtop = (self.cfg.width // 2, 168)
            self._panel(box, 220)
            self.screen.blit(text, text.get_rect(center=box.center))

    def _draw_rewards(self, game):
        W, H = self.cfg.width, self.cfg.height
        shade = pygame.Surface((W, H), pygame.SRCALPHA)
        shade.fill((0, 0, 12, 210))
        self.screen.blit(shade, (0, 0))
        title = self.font_card.render("레벨업 보상 — 카드 한 장을 선택하세요", True, COLORS["white"])
        self.screen.blit(title, title.get_rect(center=(W // 2, H // 2 - 175)))
        gap, margin = 18, 30
        width = (W - 2 * margin - 2 * gap) // 3
        accents = {"강화": (95, 205, 255), "능력치": (178, 150, 255),
                   "회복": (100, 230, 165), "전직": (255, 205, 95), "보급": (255, 165, 100)}
        for i, card in enumerate(game.reward_choices):
            rect = pygame.Rect(margin + i * (width + gap), H // 2 - 110, width, 240)
            self._panel(rect, 245, 16)
            color = accents[card.category]
            pygame.draw.rect(self.screen, color, (rect.x + 16, rect.y + 18, width - 32, 4), border_radius=2)
            label = self.font_body.render(f"[{i + 1}]  {card.category}", True, color)
            self.screen.blit(label, (rect.x + 20, rect.y + 38))
            name = self.font_card.render(card.title, True, COLORS["white"])
            self.screen.blit(name, (rect.x + 20, rect.y + 76))
            for j, line in enumerate(card.description):
                text = self.font_small.render(line, True, COLORS["text"])
                self.screen.blit(text, (rect.x + 20, rect.y + 126 + j * 28))
            self.screen.blit(self.font_body.render(f"{i + 1} 키로 선택", True, color), (rect.x + 20, rect.bottom - 44))
        hint = f"전투 일시정지 · 남은 보상 {game.pending_rewards}개 · L / ESC: 닫기 (카드 유지) · 전직은 Lv.3부터"
        text = self.font_small.render(hint, True, COLORS["text"])
        self.screen.blit(text, text.get_rect(center=(W // 2, H // 2 + 166)))

    def _draw_debug(self, lines):
        lh = 16
        w = max(self.font_mono.size(l)[0] for l in lines) + 24
        rect = pygame.Rect(self.cfg.width - w - 14, 14, w, 14 + lh * len(lines))
        self._panel(rect, 200)
        for i, line in enumerate(lines):
            col = (140, 220, 255) if i == 0 else (215, 222, 240)
            self.screen.blit(self.font_mono.render(line, True, col), (rect.x + 12, rect.y + 8 + lh * i))

    def _draw_card(self, titles, subs, stats=None):
        W, H = self.cfg.width, self.cfg.height
        shade = pygame.Surface((W, H), pygame.SRCALPHA)
        shade.fill((0, 0, 10, 130))
        self.screen.blit(shade, (0, 0))
        ch = 140 + (70 if stats else 0)
        card = pygame.Rect(0, 0, 420, ch)
        card.center = (W / 2, H / 2)
        self._panel(card, 225, 18)
        y = card.y + 22
        for t in titles:
            s = self.font_big.render(t, True, COLORS["white"])
            self.screen.blit(s, s.get_rect(midtop=(W / 2, y)))
            y += s.get_height() + 4
        if stats:
            cw = card.width / len(stats)
            for i, (label, value) in enumerate(stats):
                cx = card.x + cw * (i + 0.5)
                v = self.font_hud.render(value, True, COLORS["white"])
                l = self.font_label.render(label, True, COLORS["label"])
                self.screen.blit(v, v.get_rect(midtop=(cx, y + 4)))
                self.screen.blit(l, l.get_rect(midtop=(cx, y + 34)))
            y += 64
        for t in subs:
            s = self.font_small.render(t, True, COLORS["text"])
            self.screen.blit(s, s.get_rect(midtop=(W / 2, y + 4)))
            y += 22

    def _draw_game_over(self, game):
        secs = game.frame / self.cfg.fps
        self._draw_card(["GAME OVER"], ["Press R to restart"],
                        stats=[("SCORE", f"{game.score:,}"), ("KILLS", str(game.kills)),
                               ("TIME", f"{int(secs) // 60}:{int(secs) % 60:02d}")])


class _ShapeSnap:
    """사라진 도형의 마지막 모습을 기억하기 위한 복사본."""
    __slots__ = ("kind", "x", "y", "radius", "angle")

    def __init__(self, s):
        self.kind, self.x, self.y, self.radius, self.angle = s.kind, s.x, s.y, s.radius, s.angle
