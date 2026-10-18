"""pygame으로 GameCore 상태를 그리기만 한다. 게임 상태를 바꾸지 않는다.

우주 컨셉으로 그린다 (게임 규칙 이름 → 화면 표현):
  탱크 → 우주선 (포신 방향 = 기수 방향)
  도형 square / triangle / pentagon → 별 조각 / 작은 암석 행성 / 고리 행성
  지형 WALL → 회색 장애물 타일, MUD → 중력장, BREAKABLE → 손상 표시가 있는 갈색 장애물
연출(별 반짝임, 등장/폭발 애니메이션 등)은 렌더러 내부 기록과 렌더러 전용 random만 쓴다
→ 게임 결과/재현성에 영향 없음.
"""
import math
import random

import pygame

from config import GameConfig
from terrain import WALL, MUD, BREAKABLE
from progression import (SHIPS, JOB_NAMES, STAT_MAX_LEVEL, stat_rows, special_cards, stat_upgrades_visible,
                         player_stat_summary, stat_collapsed_rect)
from sprite_assets import SpriteAssets, ENEMY_SUFFIX, ELITE_SUFFIX

COLORS = {
    "space_top": (6, 8, 22),
    "space_bottom": (16, 10, 34),
    "player": (70, 200, 255),
    "player_dark": (18, 84, 140),
    "enemy": (255, 92, 112),
    "enemy_dark": (130, 28, 56),
    "elite": (255, 200, 70),
    "player_shot": (90, 220, 255),
    "enemy_shot": (255, 96, 160),
    "square": (255, 220, 110),      # 별 조각
    "triangle": (232, 124, 86),     # 암석 행성
    "pentagon": (128, 118, 255),    # 고리 행성
    "nebula": [(150, 70, 220), (80, 96, 240), (210, 78, 190)],
    "gravity": (255, 150, 60),
    "rock": (122, 110, 102),
    "rock_edge": (70, 62, 58),
    "text": (180, 192, 226),
    "label": (130, 150, 205),
    "white": (255, 255, 255),
    "panel": (14, 20, 42),
    "panel_edge": (78, 98, 160),
    "hp_bg": (36, 40, 66),
    "minimap_floor": (214, 216, 218),
    "minimap_wall": (94, 100, 106),
    "minimap_border": (75, 81, 88),
    "minimap_player": (20, 29, 38),
}
SPAWN_FRAMES = 14   # 등장 애니메이션 길이
SHAPE_FADE_FRAMES = 60  # 천체는 1초 동안 서서히 떠오른다
SCORE_TEXT_FRAMES = 50  # "+점수" 글자가 떠오르는 시간
DEATH_FRAMES = 22   # 파괴/폭발 애니메이션 길이
FLASH_FRAMES = 5    # 피격 깜빡임 길이
MINIMAP_ALPHA = 165  # 우하단 미니맵 반투명도 (0=완전 투명, 255=불투명)

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
        self.fullscreen = False
        self.windowed_size = (cfg.window_width, cfg.window_height)
        self.screen = pygame.display.set_mode(self.windowed_size, pygame.RESIZABLE)
        self.assets = SpriteAssets()
        self._explosion_frames = self._make_explosion_frames()  # 중심과 캔버스를 맞춘 폭발 8단계
        self.set_zoom(cfg.camera_zoom)
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
        self.font_score = pygame.font.SysFont(sans, 22, bold=True)
        self.font_score_big = pygame.font.SysFont(sans, 30, bold=True)

        self._rand = random.Random(2024)   # 렌더러 전용 (배경 별 배치 등)
        self._glow_cache = {}
        self._bg = self._make_background()
        self.camera_x = self.camera_y = 0
        self._twinkles = [(self._rand.uniform(0, cfg.world_width), self._rand.uniform(0, cfg.world_height),
                           self._rand.uniform(0, 6.28), self._rand.uniform(0.02, 0.07))
                          for _ in range(8 * cfg.world_scale ** 2)]
        self._shape_sprites = {k: self._make_shape_sprite(k) for k in ("square", "triangle", "pentagon")}
        self._terrain_key = None
        self._floor = None        # 배경 + 성운/중력장/소행성 캐시
        self._minimap_key = None
        self._minimap_floor = None
        self._tick = 0

        # 연출용 기록 (게임 상태와 무관)
        self._last_frame = -1
        self._first_seen = {}   # id -> 처음 본 frame (등장 애니메이션)
        self._prev_hp = {}      # 도형 id -> 이전 hp (피격 깜빡임)
        self._hit_frame = {}    # 도형 id -> 마지막 피격 frame
        self._prev_shapes = {}  # id -> 이전 프레임 도형 (사라짐 감지)
        self._prev_alive = {}   # 적 id -> 이전 alive
        self._ghosts = []       # 파괴 애니메이션: dict(kind, x, y, r, angle, color, age)
        self._sparks = []       # 점수 획득 불꽃: [x, y, vx, vy, age, life, color]
        self._popups_seen = set()
        self._xp_flash_frame = -999

    # ------------------------------------------------------------------
    # 폭발 프레임: 서로 다른 원본 크기를 공통 캔버스에 정렬
    # ------------------------------------------------------------------
    def _make_explosion_frames(self):
        """폭발 원본 8장의 비율을 유지하며 같은 크기·중심의 표면으로 정렬한다."""
        sources = [self.assets._source(f"etc/boom_effect_{i:02d}") for i in range(1, 9)]
        side = max(max(image.get_size()) for image in sources)
        frames = []
        for source in sources:
            frame = pygame.Surface((side, side), pygame.SRCALPHA)
            frame.blit(source, source.get_rect(center=(side // 2, side // 2)))
            frames.append(frame)
        return tuple(frames)

    def _draw_explosion(self, x, y, diameter, progress):
        """월드 좌표의 폭발을 진행도(0~1)에 해당하는 이미지로 그린다."""
        if not 0 <= progress < 1:
            return
        frame = self._explosion_frames[min(len(self._explosion_frames) - 1,
                                           int(progress * len(self._explosion_frames)))]
        side = max(8, round(diameter))
        image = pygame.transform.smoothscale(frame, (side, side))
        center = tuple(round(value) for value in self.world_to_view(x, y))
        self.screen.blit(image, image.get_rect(center=center))

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
        size = (self.cfg.world_width, self.cfg.world_height)
        surf = self.assets.image("backgrounds/deep_space", size).copy()
        haze = self.assets.image("backgrounds/nebula", size).copy()
        haze.set_alpha(35)
        surf.blit(haze, (0, 0))
        surf.fill((205, 215, 230), special_flags=pygame.BLEND_RGB_MULT)
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
        tile = tm.tile
        floor = self._bg.copy()
        solids = (WALL, BREAKABLE)
        for row in range(tm.rows):
            for col in range(tm.cols):
                kind = tm.tiles[row][col]
                rect = pygame.Rect(col * tile, row * tile, tile, tile)
                center = rect.center
                if kind == MUD:
                    image = self.assets.image("objects/gravity_field", tile * 1.25)
                    floor.blit(image, image.get_rect(center=center))
                elif kind in solids:
                    # 타일 좌표로 무늬를 선택해 게임 난수열과 충돌 영역을 바꾸지 않는다.
                    variant = (col * 3 + row * 5) % 4 + 1
                    image = self.assets.image(f"etc/guard_{variant:02d}", tile)
                    if kind == BREAKABLE:
                        image = image.copy()
                        image.fill((230, 175, 130, 255), special_flags=pygame.BLEND_RGBA_MULT)
                    floor.blit(image, rect)
                    if kind == BREAKABLE and tm.hp[(col, row)] < tm.breakable_hp_max:
                        ratio = tm.hp[(col, row)] / tm.breakable_hp_max
                        pygame.draw.line(floor, (255, 170, 90), (center[0] - 16, center[1] + 16),
                                         (center[0] - 16 + round(32 * ratio), center[1] + 16), 2)
        self._floor = floor

    # ------------------------------------------------------------------
    # 도형 → 천체 스프라이트 (한 번 만들어두고 회전/확대해서 씀)
    # ------------------------------------------------------------------
    def _make_shape_sprite(self, kind):
        from config import SHAPE_TYPES
        path = {"square": "star_fragment", "triangle": "rock_planet", "pentagon": "ring_planet"}[kind]
        sprite = self.assets.image("objects/" + path, SHAPE_TYPES[kind]["radius"] * 2.8)
        flash = sprite.copy()
        flash.fill((100, 100, 100, 0), special_flags=pygame.BLEND_RGBA_ADD)
        return sprite, flash

    # ------------------------------------------------------------------
    # 연출 기록 갱신
    # ------------------------------------------------------------------
    def _track(self, game):
        f = game.frame
        if f < self._last_frame:  # 재시작
            self._first_seen.clear(); self._prev_hp.clear(); self._hit_frame.clear()
            self._prev_shapes.clear(); self._prev_alive.clear(); self._ghosts.clear()
            self._sparks.clear(); self._popups_seen.clear()
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
            # 판을 시작할 때 이미 있던 천체는 바로 보이고, 도중에 생긴 것만 서서히 나타난다.
            self._first_seen.setdefault(s.id, f if f > 0 else -10**6)
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
        # 점수를 얻은 자리에서 불꽃이 튀고 EXP 바가 반짝인다.
        for spark in self._sparks:
            for _ in range(delta):
                spark[0] += spark[2]
                spark[1] += spark[3]
                spark[2] *= 0.9
                spark[3] *= 0.9
            spark[4] += delta
        self._sparks = [spark for spark in self._sparks if spark[4] < spark[5]]
        for pid, frame, x, y, amount, kind in game.score_popups:
            if pid in self._popups_seen:
                continue
            self._popups_seen.add(pid)
            self._xp_flash_frame = frame
            color = COLORS.get(kind, COLORS["elite"])
            count = 10 if amount < 50 else 18 if amount < 200 else 26
            for _ in range(count):
                angle = self._rand.uniform(0, math.tau)
                speed = self._rand.uniform(2.0, 5.5) * (1.3 if amount >= 100 else 1.0)
                self._sparks.append([x, y, math.cos(angle) * speed, math.sin(angle) * speed, 0,
                                     self._rand.randint(18, 32), _mix(color, (255, 255, 255), 0.35)])
        if len(self._popups_seen) > 500:
            self._popups_seen = {pop[0] for pop in game.score_popups}
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
    @property
    def size(self):
        return self.screen.get_size()

    def resize(self, size):
        if self.fullscreen:
            return
        self.windowed_size = (max(960, size[0]), max(640, size[1]))
        self.screen = pygame.display.set_mode(self.windowed_size, pygame.RESIZABLE)
        self.set_zoom(self.cfg.camera_zoom)

    def set_fullscreen(self, enabled):
        if enabled == self.fullscreen:
            return
        if enabled:
            windowed_size = self.size
            self.screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
            self.windowed_size = windowed_size
        else:
            self.screen = pygame.display.set_mode(self.windowed_size, pygame.RESIZABLE)
            # SDL 드라이버에 따라 전체화면 해제 뒤 크기를 한 번 더 적용해야 한다.
            if self.size != self.windowed_size:
                self.screen = pygame.display.set_mode(self.windowed_size, pygame.RESIZABLE)
        self.fullscreen = enabled
        self.set_zoom(self.cfg.camera_zoom)

    def set_zoom(self, zoom):
        if not 0 < zoom <= 1:
            raise ValueError("camera_zoom은 0보다 크고 1 이하여야 합니다.")
        self.cfg.camera_zoom = zoom
        self.effective_zoom = zoom
        # 선체를 그릴 때 반올림해도 정중앙에 오도록 뷰 크기를 짝수로 유지한다.
        self.view_width = max(2, 2 * round(self.size[0] / (2 * zoom)))
        self.view_height = max(2, 2 * round(self.size[1] / (2 * zoom)))
        self._view = pygame.Surface((self.view_width, self.view_height)).convert()

    def world_to_view(self, x, y):
        return x - self.camera_x, y - self.camera_y

    def world_to_screen(self, x, y):
        vx, vy = self.world_to_view(x, y)
        return vx * self.size[0] / self.view_width, vy * self.size[1] / self.view_height

    def screen_to_world(self, x, y):
        return (x * self.view_width / self.size[0] + self.camera_x,
                y * self.view_height / self.size[1] + self.camera_y)

    def _update_camera(self, player):
        self.camera_x = player.x - self.view_width / 2
        self.camera_y = player.y - self.view_height / 2

    def _visible(self, x, y, margin=100):
        sx, sy = self.world_to_view(x, y)
        return -margin <= sx <= self.view_width + margin and -margin <= sy <= self.view_height + margin

    def draw(self, game, debug_lines=None, paused=False, show_ai=False,
             show_controls=True, menu=None, selected=-1, show_stats=False, stats_collapsed=False):
        self._tick += 1
        self._update_camera(game.player)
        self._track(game)
        self._ensure_terrain(game.terrain)
        self._flash_on = not game.game_over  # 게임오버로 멈춘 화면에서는 깜빡임 끔
        display = self.screen
        self.screen = scr = self._view
        # 맵 밖에도 우주 배경을 채우며 카메라는 가장자리에서도 선체를 따라간다.
        bg_width, bg_height = self._bg.get_size()
        offset_x, offset_y = round(-self.camera_x), round(-self.camera_y)
        start_x, start_y = offset_x % bg_width - bg_width, offset_y % bg_height - bg_height
        for y in range(start_y, self.view_height, bg_height):
            for x in range(start_x, self.view_width, bg_width):
                scr.blit(self._bg, (x, y))
        scr.blit(self._floor, (offset_x, offset_y))
        self._draw_twinkles()
        f = game.frame
        p = game.player

        for s in game.shapes:
            if self._visible(s.x, s.y):
                self._draw_shape(s, f)
        for e in game.enemies:
            if e.alive and self._visible(e.x, e.y, e.radius * 3):
                self._draw_ship(e, f)
        if p.alive:
            self._draw_ship(p, f, is_player=True)
        for b in game.bullets:
            if self._visible(b.x, b.y):
                self._draw_bullet(b)
        self._draw_combat_effects(game)
        self._draw_score_effects(game)
        for g in self._ghosts:
            if self._visible(g["x"], g["y"]):
                self._draw_ghost(g)
        # 체력바는 모든 물체 위에 (숨은 적의 체력바는 그리지 않음)
        for s in game.shapes:
            if s.hp < s.max_hp:
                self._hp_bar(s.x, s.y + s.radius + 9, s.radius * 2.2, s.hp / s.max_hp)
        for e in game.enemies:
            if e.alive and e.hp < e.max_hp:
                self._hp_bar(e.x, e.y + e.radius + 12, e.radius * 2.6, e.hp / e.max_hp)
        if p.alive and p.hp < p.max_hp:
            self._hp_bar(p.x, p.y + p.radius + 12, p.radius * 2.6, p.hp / p.max_hp)
        if show_ai:
            self._draw_ai_debug(game)

        self.screen = display
        pygame.transform.smoothscale(scr, self.size, display)
        self._draw_world_boundary()
        self._draw_score_text(game)
        self._draw_hud(game, paused, show_notice=menu is None,
                       show_controls=show_controls, stats_collapsed=stats_collapsed)
        if debug_lines:
            self._draw_debug(debug_lines)
        if show_stats and not paused and menu is None and not game.game_over:
            self._draw_stats_panel(game)
        if menu is not None:
            self._draw_menu(menu, "일시정지 · 설정", selected)
        elif game.game_over:
            self._draw_game_over(game)
        elif paused:
            self._draw_card(["일시정지"], ["P / ESC: 계속"])

    def _draw_world_boundary(self):
        """0.5px 외곽선을 화면 1px의 절반 농도로 표현한다."""
        left, top = (round(value) for value in self.world_to_screen(0, 0))
        right, bottom = (round(value) for value in
                         self.world_to_screen(self.cfg.world_width, self.cfg.world_height))
        width, height = self.size
        if left < 0 and top < 0 and right >= width and bottom >= height:
            return
        layer = getattr(self, "_world_boundary_layer", None)
        if layer is None or layer.get_size() != self.size:
            layer = self._world_boundary_layer = pygame.Surface(self.size, pygame.SRCALPHA)
        layer.fill((0, 0, 0, 0))
        points = [(round(x), round(y)) for x, y in
                  ((left, top), (right, top), (right, bottom), (left, bottom))]
        pygame.draw.lines(layer, (255, 0, 0, 128), True, points, 1)
        self.screen.blit(layer, (0, 0))

    def _draw_score_effects(self, game):
        for x, y, _, _, age, life, color in self._sparks:
            if not self._visible(x, y):
                continue
            k = 1 - age / life
            sx, sy = self.world_to_view(x, y)
            self._blit_glow(self.screen, sx, sy, 5 + 9 * k, color, round(k * 4) / 4)
            pygame.draw.circle(self.screen, color, (round(sx), round(sy)), max(1, round(4.5 * k)))

    def _draw_score_text(self, game):
        """줌과 관계없이 읽히도록 "+점수"는 화면 좌표에 고정 크기로 그린다."""
        for _, frame, x, y, amount, kind in game.score_popups:
            age = game.frame - frame
            if age > SCORE_TEXT_FRAMES or not self._visible(x, y):
                continue
            t = age / SCORE_TEXT_FRAMES
            # 처음엔 살짝 커졌다가 위로 떠오르며 사라진다.
            pop = 1 + 0.35 * max(0.0, 1 - age / 8)
            font = self.font_score_big if amount >= 100 else self.font_score
            color = (255, 230, 120) if kind != "elite" else (255, 190, 60)
            text = font.render(f"+{amount}", True, color)
            shadow = font.render(f"+{amount}", True, (40, 25, 0))
            if pop > 1:
                size = (round(text.get_width() * pop), round(text.get_height() * pop))
                text, shadow = pygame.transform.smoothscale(text, size), pygame.transform.smoothscale(shadow, size)
            alpha = 255 if t < 0.55 else round(255 * (1 - (t - 0.55) / 0.45))
            text.set_alpha(alpha)
            shadow.set_alpha(alpha // 2)
            sx, sy = self.world_to_screen(x, y)
            sy -= 14 + 40 * (1 - (1 - t) ** 2)
            self.screen.blit(shadow, shadow.get_rect(center=(round(sx) + 2, round(sy) + 2)))
            self.screen.blit(text, text.get_rect(center=(round(sx), round(sy))))

    def _draw_combat_effects(self, game):
        for beam in game.beams:
            start = self.world_to_view(beam.x, beam.y)
            end = self.world_to_view(beam.end_x, beam.end_y)
            pygame.draw.line(self.screen, (30, 105, 125), start, end, 10)
            pygame.draw.line(self.screen, (95, 245, 255), start, end, 5)
            pygame.draw.line(self.screen, (240, 255, 255), start, end, 2)
        for explosion in game.explosions:
            self._draw_explosion(explosion.x, explosion.y, explosion.radius * 2,
                                 1 - explosion.life / 18)

    def draw_main_menu(self, buttons, selected=0):
        self.screen.blit(self.assets.image("backgrounds/main", self.size), (0, 0))
        self._draw_menu(buttons, "SPACE SKIRMISH", selected, main=True)

    def _draw_menu(self, buttons, title, selected, main=False):
        W, H = self.size
        shade = pygame.Surface((W, H), pygame.SRCALPHA)
        shade.fill((0, 0, 15, 100 if main else 215))
        self.screen.blit(shade, (0, 0))
        if not main:
            self._panel(pygame.Rect(W // 2 - 225, H // 2 - 276, 450, 552), 240, 20)
        font = self.font_big if main else self.font_card
        text = font.render(title, True, COLORS["white"])
        self.screen.blit(text, text.get_rect(center=(W // 2, H // 2 - (188 if main else 224))))
        sub = "당신의 우주선을 지휘하세요" if main else "설정을 클릭해 변경 · ESC / P로 계속하기"
        text = self.font_body.render(sub, True, COLORS["text"])
        self.screen.blit(text, text.get_rect(center=(W // 2, H // 2 - (132 if main else 194))))
        mouse = pygame.mouse.get_pos()
        for i, button in enumerate(buttons):
            active = button.enabled and (i == selected or button.rect.collidepoint(mouse))
            difficulty_choice = main and button.key.startswith("difficulty_")
            highlighted = button.enabled and (active or (difficulty_choice and button.checked))
            path = "etc/home_selected" if highlighted else "etc/home_selected_normal"
            image = self.assets.image(path, button.rect.size)
            if not button.enabled:
                image = image.copy()
                image.fill((100, 100, 100, 255), special_flags=pygame.BLEND_RGBA_MULT)
            self.screen.blit(image, button.rect)
            text_color = (48, 30, 20) if highlighted else (12, 32, 42) if button.enabled else (145, 150, 160)
            font = self.font_hud if difficulty_choice else self.font_card if main else self.font_body
            if difficulty_choice and button.checked:
                pygame.draw.circle(self.screen, text_color, (button.rect.left + 20, button.rect.centery), 3)
            label = font.render(button.label, True, text_color)
            self.screen.blit(label, label.get_rect(center=button.rect.center))
        hint = "클릭 또는 ↑↓ / Enter로 선택" if main else "새 게임은 진행도를 초기화합니다 · 설정은 이번 실행 동안 유지됩니다"
        text = self.font_small.render(hint, True, COLORS["text"])
        self.screen.blit(text, text.get_rect(center=(W // 2, buttons[-1].rect.bottom + 30)))

    def _draw_shape(self, s, f):
        sprite, flash = self._shape_sprites[s.kind]
        img = flash if self._flash_on and f - self._hit_frame.get(s.id, -999) < FLASH_FRAMES else sprite
        # 투명한 상태에서 살짝 작게 시작해 천천히 선명해진다 (갑자기 튀어나오지 않게).
        t = min(1.0, max(0.0, (f - self._first_seen.get(s.id, -999)) / SHAPE_FADE_FRAMES))
        ease = t * t * (3 - 2 * t)
        if ease <= 0.02:
            return
        img = pygame.transform.rotozoom(img, -math.degrees(s.angle), 0.85 + 0.15 * ease)
        if ease < 1:
            img.set_alpha(round(255 * ease))
        x, y = self.world_to_view(s.x, s.y)
        self.screen.blit(img, img.get_rect(center=(int(x), int(y))))

    def _draw_bullet(self, b):
        path = "cannon_shell" if b.kind == "shell" else "enemy_plasma" if b.team == "enemy" else "player_plasma"
        angle = -90 - math.degrees(math.atan2(b.vy, b.vx))
        image = self.assets.projectile_image("projectiles/" + path, b.radius * 2, angle)
        x, y = self.world_to_view(b.x, b.y)
        if b.kind == "shell":
            # 저격 계열 포탄은 금속 회색이라 우주 배경에 묻히므로 발광을 더해 눈에 띄게 한다.
            glow = COLORS["enemy_shot"] if b.team == "enemy" else COLORS["player_shot"]
            self._blit_glow(self.screen, x, y, b.radius * 2.2, glow, 0.9)
        self.screen.blit(image, image.get_rect(center=(round(x), round(y))))

    def _draw_ship(self, t, f, is_player=False):
        x, y = self.world_to_view(t.x, t.y)
        scale = self._spawn_scale(t.id, f)
        if scale < 0.08:
            return
        # 적도 같은 진화 그림을 쓰되 선체를 붉은색(엘리트는 금색)으로 바꿔 구분한다.
        suffix = "" if is_player else ELITE_SUFFIX if t.elite else ENEMY_SUFFIX
        path = SHIPS[t.job].asset + suffix
        image = self.assets.ship_image(path, t.radius * 2 * scale, -math.degrees(t.angle))
        if self._flash_on and f - t.last_hit_frame < FLASH_FRAMES:
            image = image.copy()
            image.fill((90, 90, 90, 0), special_flags=pygame.BLEND_RGBA_ADD)
        if t.elite:
            self._blit_glow(self.screen, x, y, t.radius * 1.6 * scale, (255, 190, 60), 0.5)
        self.screen.blit(image, image.get_rect(center=(round(x), round(y))))
        if is_player or t.elite:
            text, color = ("YOU", COLORS["white"]) if is_player else ("ELITE", COLORS["elite"])
            label = self.font_label.render(text, True, color)
            self.screen.blit(label, label.get_rect(center=(x, y - t.radius - 20)))

    def _draw_ghost(self, g):
        """우주선·천체 파괴 시 공통 폭발 8단계를 순서대로 재생한다."""
        self._draw_explosion(g["x"], g["y"], g["r"] * 3, g["age"] / DEATH_FRAMES)

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

    def _draw_hud(self, game, paused, show_notice=True, show_controls=True, stats_collapsed=False):
        p = game.player
        W, H = self.size
        secs = game.frame / self.cfg.fps

        if game.cfg.limited_ammo:
            ammo = f"탄약 {p.ammo} / {p.max_ammo}"
            rect = pygame.Rect(W - 198, 14, 184, 60)
            self._panel(rect)
            color = (255, 130, 100) if p.ammo == 0 else COLORS["white"]
            self.screen.blit(self.font_small.render(ammo, True, color), (rect.x + 14, rect.y + 10))
            reloading = game.reload_frames_left > 0
            hint = (f"재장전 {game.reload_frames_left / game.cfg.fps:.1f}초"
                    if reloading else "R: 재장전")
            self.screen.blit(self.font_small.render(hint, True, COLORS["text"]), (rect.x + 14, rect.y + 33))
            if reloading:
                bar = pygame.Rect(rect.x + 14, rect.y + 54, rect.width - 28, 6)
                pygame.draw.rect(self.screen, COLORS["hp_bg"], bar, border_radius=3)
                bar.width = int(bar.width * (1 - game.reload_frames_left / game.reload_frames_total))
                if bar.width:
                    pygame.draw.rect(self.screen, COLORS["player"], bar, border_radius=3)
            if p.ammo == 0 and not game.game_over and not reloading and show_notice:
                text = self.font_body.render("탄약 소진! [R] 재장전", True, (255, 165, 100))
                self.screen.blit(text, text.get_rect(midtop=(W / 2, 270)))

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
            self._draw_progression(game, show_notice, stats_collapsed)

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

        # 메뉴의 조작 안내 설정을 즉시 반영한다.
        if show_controls:
            first_line = "WASD 이동 · 마우스 조준 / 발사"
            if game.cfg.limited_ammo:
                first_line += " · R 재장전"
            second_line = "1–5 스탯 강화 · Tab 능력치 · ESC 메뉴"
            for i, hint in enumerate((first_line, second_line)):
                surf = self.font_small.render(hint, True, COLORS["text"])
                self.screen.blit(surf, surf.get_rect(midtop=(W / 2 + 30, 10 + i * 23)))
        self._draw_minimap(game)

    def minimap_rect(self):
        """현재 창의 우하단에 표시할 전체 지도 영역."""
        width, height = self.size
        max_width = max(176, min(224, round(width * 0.16)))
        max_height = max(112, min(196, round(height * 0.25)))
        scale = min((max_width - 12) / self.cfg.world_width,
                    (max_height - 12) / self.cfg.world_height)
        map_width = max(1, round(self.cfg.world_width * scale))
        map_height = max(1, round(self.cfg.world_height * scale))
        return pygame.Rect(width - map_width - 26, height - map_height - 26,
                           map_width + 12, map_height + 12)

    def _ensure_minimap(self, terrain, size):
        # 맵 객체를 키에 보관해 새 판의 id 재사용도 이전 지도로 오인하지 않는다.
        key = (terrain, terrain.version, size)
        if self._minimap_key == key:
            return
        surface = pygame.Surface(size)
        surface.fill(COLORS["minimap_floor"])
        width, height = size
        for row in range(terrain.rows):
            top = round(row * height / terrain.rows)
            bottom = round((row + 1) * height / terrain.rows)
            for col in range(terrain.cols):
                if terrain.tiles[row][col] not in (WALL, BREAKABLE):
                    continue
                left = round(col * width / terrain.cols)
                right = round((col + 1) * width / terrain.cols)
                pygame.draw.rect(surface, COLORS["minimap_wall"], (left, top, right - left, bottom - top))
        self._minimap_key, self._minimap_floor = key, surface

    def _minimap_marker(self, game, area):
        terrain, player = game.terrain, game.player
        x = area.left + player.x / (terrain.cols * terrain.tile) * area.width
        y = area.top + player.y / (terrain.rows * terrain.tile) * area.height
        ca, sa = math.cos(player.angle), math.sin(player.angle)
        # 화면도 아래쪽이 +Y이므로 월드 조준각을 그대로 쓴다.
        return [(x + ca * dx - sa * dy, y + sa * dx + ca * dy)
                for dx, dy in ((6.0, 0.0), (-4.0, -3.5), (-2.0, 0.0), (-4.0, 3.5))]

    def _draw_minimap(self, game):
        rect = self.minimap_rect()
        area = rect.inflate(-12, -12)
        self._ensure_minimap(game.terrain, area.size)
        # 배경이 비치도록 별도의 알파 표면에 그린 다음 반투명하게 합성한다.
        layer = pygame.Surface(rect.size, pygame.SRCALPHA)
        local_area = pygame.Rect(area.left - rect.left, area.top - rect.top, area.width, area.height)
        pygame.draw.rect(layer, COLORS["minimap_border"], layer.get_rect(), border_radius=3)
        layer.blit(self._minimap_floor, local_area.topleft)
        layer.set_clip(local_area)
        marker = self._minimap_marker(game, local_area)
        pygame.draw.polygon(layer, COLORS["minimap_player"], marker)
        layer.set_clip(None)
        layer.set_alpha(MINIMAP_ALPHA)
        self.screen.blit(layer, rect.topleft)

    def _draw_progression(self, game, show_notice, stats_collapsed=False):
        p = game.player
        W, H = self.size
        panel = pygame.Rect(W // 2 - 166, H - 100, 332, 84)
        self._panel(panel)
        title = f"Lv.{game.level}  {JOB_NAMES[p.job]}"
        text = self.font_body.render(title, True, COLORS["white"])
        self.screen.blit(text, text.get_rect(midtop=(W // 2, H - 98)))
        bar = pygame.Rect(W // 2 - 160, H - 67, 320, 18)
        pygame.draw.rect(self.screen, COLORS["hp_bg"], bar, border_radius=9)
        fill = bar.copy()
        fill.width = int(bar.width * game.xp / game.xp_to_next_level)
        if fill.width:
            pygame.draw.rect(self.screen, COLORS["player"], fill, border_radius=9)
        flash = 1 - (game.frame - self._xp_flash_frame) / 15
        if 0 < flash <= 1:  # 점수를 얻으면 EXP 바가 잠깐 밝게 빛난다
            glow = pygame.Surface(bar.size, pygame.SRCALPHA)
            pygame.draw.rect(glow, (255, 240, 170, round(150 * flash)), glow.get_rect(), border_radius=9)
            self.screen.blit(glow, bar.topleft)
            pygame.draw.rect(self.screen, (255, 230, 140), bar.inflate(4, 4), 2, border_radius=11)
        xp = self.font_label.render(f"EXP  {game.xp} / {game.xp_to_next_level}", True, COLORS["white"])
        self.screen.blit(xp, xp.get_rect(center=bar.center))
        if stat_upgrades_visible(game):
            if stats_collapsed:
                self._draw_stat_collapsed(game)
            else:
                self._draw_stat_upgrades(game)
        self._draw_rewards(game)
        if game.frame < game.reward_message_until and show_notice:
            text = self.font_small.render(f"{game.last_reward} 적용 완료", True, (160, 240, 220))
            self.screen.blit(text, text.get_rect(midtop=(W / 2, H - 126)))

    def _draw_stats_panel(self, game):
        rect = pygame.Rect(self.size[0] // 2 - 230, self.size[1] // 2 - 220, 460, 440)
        self._panel(rect, 175, 16)
        title = self.font_card.render("나의 능력치", True, COLORS["white"])
        self.screen.blit(title, (rect.x + 24, rect.y + 18))
        ship = self.font_body.render(f"Lv.{game.level} · {JOB_NAMES[game.player.job]}", True, COLORS["player"])
        self.screen.blit(ship, (rect.x + 24, rect.y + 52))
        for i, (label, value) in enumerate(player_stat_summary(game)):
            y = rect.y + 92 + i * 31
            name = self.font_body.render(label, True, COLORS["text"])
            number = self.font_body.render(value, True, COLORS["white"])
            self.screen.blit(name, (rect.x + 24, y))
            self.screen.blit(number, number.get_rect(topright=(rect.right - 24, y)))
        hint = f"수리 대기 {game.cfg.regen_delay / game.cfg.fps:g}초 · 이동 속도는 일반 지형 기준"
        self.screen.blit(self.font_small.render(hint, True, COLORS["label"]), (rect.x + 24, rect.bottom - 55))
        hint = self.font_small.render("Tab을 놓으면 닫힘 · 전투는 계속됩니다", True, COLORS["player"])
        self.screen.blit(hint, (rect.x + 24, rect.bottom - 31))

    def _draw_stat_upgrades(self, game):
        rows = stat_rows(*self.size, game.stat_choices)
        if not rows:
            return
        top = rows[0][1][1] - 30
        bottom = rows[-1][1][1] + rows[-1][1][3] + 8
        self._panel(pygame.Rect(14, top, 272, bottom - top), 195, 10)
        title = self.font_small.render(f"남은 스탯 {game.upgrade_points}P · 1–5 / 클릭", True, COLORS["player"])
        self.screen.blit(title, (22, top + 7))
        for i, (card, coords) in enumerate(rows):
            rect = pygame.Rect(coords)
            enabled = game.can_upgrade_stat(card.key)
            pygame.draw.rect(self.screen, (25, 38, 59) if enabled else (20, 25, 38), rect, border_radius=8)
            pygame.draw.rect(self.screen, (65, 110, 140) if enabled else (44, 53, 70), rect, 1, border_radius=8)
            text = self.font_small.render(f"{i + 1}  {card.title}", True,
                                          COLORS["white"] if enabled else COLORS["label"])
            self.screen.blit(text, (rect.x + 5, rect.y + 2))
            level = game.stat_levels[card.key]
            at_limit = level >= STAT_MAX_LEVEL or (card.key == "rapid" and game.player.fire_cooldown_max <= 4)
            rank = self.font_label.render("MAX" if at_limit else f"{level}/{STAT_MAX_LEVEL}", True, COLORS["player"])
            self.screen.blit(rank, rank.get_rect(topright=(rect.right - 30, rect.y + 3)))
            plus = pygame.Rect(rect.right - 24, rect.y + 1, 23, 20)
            pygame.draw.rect(self.screen, (80, 185, 215) if enabled else (45, 60, 77), plus, border_radius=7)
            label = self.font_body.render("+", True, (10, 25, 35) if enabled else (100, 115, 140))
            self.screen.blit(label, label.get_rect(center=plus.center))
            if rect.collidepoint(pygame.mouse.get_pos()):
                self._tooltip(card.description, (14, top - 42), 300)

    def _draw_stat_collapsed(self, game):
        rect = pygame.Rect(stat_collapsed_rect(*self.size))
        hover = rect.collidepoint(pygame.mouse.get_pos())
        self._panel(rect, 215 if hover else 185, 10)
        badge = pygame.Rect(rect.x + 8, rect.y + 8, 22, 22)
        pygame.draw.rect(self.screen, (80, 185, 215), badge, border_radius=7)
        plus = self.font_body.render("+", True, (10, 25, 35))
        self.screen.blit(plus, plus.get_rect(center=badge.center))
        text = self.font_small.render(f"남은 스탯 {game.upgrade_points}P · 펼치기", True, COLORS["white"])
        self.screen.blit(text, text.get_rect(midleft=(badge.right + 9, rect.centery)))

    def _tooltip(self, lines, pos, width):
        wrapped = [line for text in lines for line in self._wrapped_text(text, width - 20)]
        rect = pygame.Rect(pos, (width, 14 + len(wrapped) * 18))
        self._panel(rect, 240, 8)
        for i, line in enumerate(wrapped):
            self.screen.blit(self.font_small.render(line, True, COLORS["text"]), (rect.x + 10, rect.y + 7 + i * 18))

    def _wrapped_text(self, text, width):
        lines, line = [], ""
        for char in text:
            if line and self.font_small.size(line + char)[0] > width:
                lines.append(line)
                line = ""
            line += char
        return lines + ([line] if line else [])

    def _draw_rewards(self, game):
        pending = game.special_reward_levels
        level = pending[0] if pending else (game.level // 10 + 1) * 10
        count = len(game.reward_choices)
        stage = "최종 진화" if level == 30 else "전직" if level < 30 else "숙련"
        heading = (f"Lv.{level} {stage} · F2–F{count + 1} / 클릭" if count > 1
                   else f"Lv.{level} {stage} · F2 / 클릭" if count else f"다음 성장 Lv.{level}")
        self.screen.blit(self.font_small.render(heading, True, (225, 205, 145)), (16, 61))
        cards = game.reward_choices
        for i, card in enumerate(cards):
            rect = pygame.Rect(special_cards(*self.size, len(cards))[i])
            self._panel(rect, 205, 10)
            image = self.assets.image(SHIPS[card.key].asset, 62)
            self.screen.blit(image, image.get_rect(midtop=(rect.centerx, rect.y + 3)))
            name = self.font_small.render(card.title, True, COLORS["white"])
            if name.get_width() > rect.width - 8:
                width = rect.width - 8
                name = pygame.transform.smoothscale(name, (width, max(1, round(name.get_height() * width / name.get_width()))))
            self.screen.blit(name, name.get_rect(midtop=(rect.centerx, rect.y + 67)))
            if count and rect.collidepoint(pygame.mouse.get_pos()):
                description = ("현재 우주선 피해 +20%",) if level >= 40 else card.description
                self._tooltip(description, (14, rect.bottom + 8), 330)

    def _draw_debug(self, lines):
        lh = 16
        w = max(self.font_mono.size(l)[0] for l in lines) + 24
        rect = pygame.Rect(self.size[0] - w - 14, 14, w, 14 + lh * len(lines))
        self._panel(rect, 200)
        for i, line in enumerate(lines):
            col = (140, 220, 255) if i == 0 else (215, 222, 240)
            self.screen.blit(self.font_mono.render(line, True, col), (rect.x + 12, rect.y + 8 + lh * i))

    def _draw_card(self, titles, subs, stats=None):
        W, H = self.size
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
        self._draw_card(["GAME OVER"], ["Enter: 새 게임 · ESC: 메뉴"],
                        stats=[("SCORE", f"{game.score:,}"), ("KILLS", str(game.kills)),
                               ("TIME", f"{int(secs) // 60}:{int(secs) % 60:02d}")])


class _ShapeSnap:
    """사라진 도형의 마지막 모습을 기억하기 위한 복사본."""
    __slots__ = ("kind", "x", "y", "radius", "angle")

    def __init__(self, s):
        self.kind, self.x, self.y, self.radius, self.angle = s.kind, s.x, s.y, s.radius, s.angle
