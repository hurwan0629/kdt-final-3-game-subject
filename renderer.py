"""pygame으로 GameCore 상태를 그리기만 한다. 게임 상태를 바꾸지 않는다.

우주 컨셉으로 그린다 (게임 규칙 이름 → 화면 표현):
  탱크 → 우주선 (포신 방향 = 기수 방향)
  도형 square / triangle / pentagon → 별 조각 / 작은 암석 행성 / 고리 행성
  지형 WALL → 소행성 벽, BUSH → 가스 구름, MUD → 중력장, BREAKABLE → 금이 간 소행성
연출(별 반짝임, 등장/폭발 애니메이션 등)은 렌더러 내부 기록과 렌더러 전용 random만 쓴다
→ 게임 결과/재현성에 영향 없음.
"""
import math
import random

import pygame
import pygame.gfxdraw

from config import GameConfig
from terrain import WALL, BUSH, MUD, BREAKABLE
from progression import JOB_NAMES, stat_rows, special_cards, stat_upgrades_visible, player_stat_summary
from sprite_assets import SpriteAssets

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
        self._cloud_layer = None  # 우주선 위에 덮는 가스 구름 레이어 캐시
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
        size = (self.cfg.world_width, self.cfg.world_height)
        surf = self.assets.image("backgrounds/deep_space", size).copy()
        haze = self.assets.image("backgrounds/nebula", size).copy()
        haze.set_alpha(35)
        surf.blit(haze, (0, 0))
        surf.fill((120, 125, 145), special_flags=pygame.BLEND_RGB_MULT)
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
        clouds = pygame.Surface(floor.get_size(), pygame.SRCALPHA)
        paths = {WALL: "asteroid_wall", BREAKABLE: "breakable_asteroid",
                 MUD: "gravity_field", BUSH: "gas_cloud"}
        for row in range(tm.rows):
            for col in range(tm.cols):
                kind = tm.tiles[row][col]
                if kind not in paths:
                    continue
                center = (round((col + 0.5) * tile), round((row + 0.5) * tile))
                target = clouds if kind == BUSH else floor
                if kind in (WALL, BREAKABLE):
                    pygame.draw.rect(floor, (22, 29, 44), (col * tile, row * tile, tile, tile))
                image = self.assets.image("objects/" + paths[kind], tile * (1.5 if kind == BUSH else 1.25))
                target.blit(image, image.get_rect(center=center))
                if kind == BREAKABLE and tm.hp[(col, row)] < tm.breakable_hp_max:
                    ratio = tm.hp[(col, row)] / tm.breakable_hp_max
                    pygame.draw.line(floor, (255, 170, 90), (center[0] - 16, center[1] + 16),
                                     (center[0] - 16 + round(32 * ratio), center[1] + 16), 2)
        clouds.set_alpha(240)
        self._floor, self._cloud_layer = floor, clouds

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
        # 큰 모니터에서도 맵 밖 빈 공간 대신 플레이 영역을 채운다.
        self.effective_zoom = max(zoom, self.size[0] / self.cfg.world_width, self.size[1] / self.cfg.world_height)
        self.view_width = round(self.size[0] / self.effective_zoom)
        self.view_height = round(self.size[1] / self.effective_zoom)
        self._view = pygame.Surface((self.view_width, self.view_height)).convert()
        self._fx_layer = pygame.Surface((self.view_width, self.view_height), pygame.SRCALPHA)

    def world_to_view(self, x, y):
        return x - self.camera_x, y - self.camera_y

    def world_to_screen(self, x, y):
        vx, vy = self.world_to_view(x, y)
        return vx * self.size[0] / self.view_width, vy * self.size[1] / self.view_height

    def screen_to_world(self, x, y):
        return (x * self.view_width / self.size[0] + self.camera_x,
                y * self.view_height / self.size[1] + self.camera_y)

    def _update_camera(self, player):
        c = self.cfg
        self.camera_x = (int(max(0, min(player.x - self.view_width / 2, c.world_width - self.view_width)))
                         if c.world_width >= self.view_width else (c.world_width - self.view_width) // 2)
        self.camera_y = (int(max(0, min(player.y - self.view_height / 2, c.world_height - self.view_height)))
                         if c.world_height >= self.view_height else (c.world_height - self.view_height) // 2)

    def _visible(self, x, y, margin=100):
        sx, sy = self.world_to_view(x, y)
        return -margin <= sx <= self.view_width + margin and -margin <= sy <= self.view_height + margin

    def draw(self, game, debug_lines=None, paused=False, show_ai=False,
             show_controls=True, menu=None, selected=-1, show_stats=False):
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
            if e.alive and self._visible(e.x, e.y) and not game.is_hidden(e):
                self._draw_ship(e, f)
        if p.alive and not player_hidden:
            self._draw_ship(p, f, is_player=True)
        # 가스 구름은 우주선 위에 덮는다 → 안에 있는 적은 실제로 가려짐
        scr.blit(self._cloud_layer, (-self.camera_x, -self.camera_y))
        if player_hidden:  # 내 우주선만 반투명하게 보여줌
            self._fx_layer.fill((0, 0, 0, 0))
            self.screen = self._fx_layer
            self._draw_ship(p, f, is_player=True)
            self.screen = scr
            self._fx_layer.set_alpha(150)
            scr.blit(self._fx_layer, (0, 0))
        for b in game.bullets:
            if self._visible(b.x, b.y):
                self._draw_bullet(b)
        self._draw_combat_effects(game)
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
        pygame.transform.smoothscale(scr, self.size, display)
        self._draw_hud(game, paused, show_notice=menu is None,
                       show_controls=show_controls)
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

    def _draw_combat_effects(self, game):
        for beam in game.beams:
            start = self.world_to_view(beam.x, beam.y)
            end = self.world_to_view(beam.end_x, beam.end_y)
            pygame.draw.line(self.screen, (30, 105, 125), start, end, 10)
            pygame.draw.line(self.screen, (95, 245, 255), start, end, 5)
            pygame.draw.line(self.screen, (240, 255, 255), start, end, 2)
        if game.charge_frames_left:
            x, y = self.world_to_view(game.player.x, game.player.y)
            radius = 12 + game.charge_frames_left % 16
            pygame.draw.circle(self.screen, (120, 240, 255), (round(x), round(y)), radius, 2)
        for explosion in game.explosions:
            x, y = self.world_to_view(explosion.x, explosion.y)
            progress = 1 - explosion.life / 18
            radius = max(4, int(explosion.radius * (0.2 + 0.8 * progress)))
            color = _mix((255, 185, 90), (40, 20, 55), progress)
            self._blit_glow(self.screen, x, y, radius, color, round(1 - progress, 1))
            pygame.draw.circle(self.screen, color, (int(x), int(y)), radius, 3)
        if game.dash_frames_left:
            x, y = self.world_to_view(game.player.x, game.player.y)
            pygame.draw.circle(self.screen, (150, 245, 255), (int(x), int(y)), int(game.player.radius + 8), 3)

    def draw_main_menu(self, buttons, selected=0):
        pygame.transform.smoothscale(self._bg, self.size, self.screen)
        self._draw_menu(buttons, "SPACE SKIRMISH", selected, main=True)

    def _draw_menu(self, buttons, title, selected, main=False):
        W, H = self.size
        shade = pygame.Surface((W, H), pygame.SRCALPHA)
        shade.fill((0, 0, 15, 170 if main else 215))
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
            color = (32, 65, 95) if active else (20, 29, 51)
            edge = COLORS["player"] if active else COLORS["panel_edge"]
            if not button.enabled:
                color, edge = (21, 23, 35), (48, 51, 66)
            pygame.draw.rect(self.screen, color, button.rect, border_radius=10)
            pygame.draw.rect(self.screen, edge, button.rect, 2 if active else 1, border_radius=10)
            text_color = COLORS["white"] if button.enabled else (94, 100, 120)
            label = (self.font_card if main else self.font_body).render(button.label, True, text_color)
            self.screen.blit(label, label.get_rect(center=button.rect.center))
        hint = "클릭 또는 ↑↓ / Enter로 선택" if main else "새 게임은 진행도를 초기화합니다 · 설정은 이번 실행 동안 유지됩니다"
        text = self.font_small.render(hint, True, COLORS["text"])
        self.screen.blit(text, text.get_rect(center=(W // 2, buttons[-1].rect.bottom + 30)))

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
        path = ("mine" if b.kind == "mine" else "homing_missile" if b.kind == "missile"
                else "cannon_shell" if b.kind == "shell" else "enemy_plasma" if b.team == "enemy" else "player_plasma")
        angle = None if b.kind == "mine" and not b.arming_frames else -90 - math.degrees(math.atan2(b.vy, b.vx))
        image = self.assets.image("projectiles/" + path, 24 if b.kind == "mine" else b.radius * 4, angle)
        x, y = self.world_to_view(b.x, b.y)
        self.screen.blit(image, image.get_rect(center=(round(x), round(y))))

    def _draw_ship(self, t, f, is_player=False):
        x, y = self.world_to_view(t.x, t.y)
        scale = self._spawn_scale(t.id, f)
        if scale < 0.08:
            return
        path = "ships/" + t.job if is_player else "enemies/" + ("scout", "fighter", "heavy")[t.id % 3]
        image = self.assets.image(path, t.radius * 3.4 * scale, -90 - math.degrees(t.angle))
        if self._flash_on and f - t.last_hit_frame < FLASH_FRAMES:
            image = image.copy()
            image.fill((90, 90, 90, 0), special_flags=pygame.BLEND_RGBA_ADD)
        self.screen.blit(image, image.get_rect(center=(round(x), round(y))))
        if is_player:
            pygame.gfxdraw.aacircle(self.screen, round(x), round(y), round(t.radius + 3), (70, 200, 255, 100))
            label = self.font_label.render("YOU", True, COLORS["white"])
            self.screen.blit(label, label.get_rect(center=(x, y - t.radius - 20)))

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

    def _draw_hud(self, game, paused, show_notice=True, show_controls=True):
        p = game.player
        W, H = self.size
        secs = game.frame / self.cfg.fps

        ammo = f"탄약 {p.ammo} / {p.max_ammo}" if game.cfg.limited_ammo else "탄약 무제한"
        rect = pygame.Rect(W - 198, 14, 184, 60)
        self._panel(rect)
        color = (255, 130, 100) if game.cfg.limited_ammo and p.ammo == 0 else COLORS["white"]
        self.screen.blit(self.font_small.render(ammo, True, color), (rect.x + 14, rect.y + 10))
        reloading = game.reload_frames_left > 0
        hint = f"재장전 {game.reload_frames_left / game.cfg.fps:.1f}초" if reloading else "R: 재장전 · ESC: 메뉴"
        self.screen.blit(self.font_small.render(hint, True, COLORS["text"]), (rect.x + 14, rect.y + 33))
        if reloading:
            bar = pygame.Rect(rect.x + 14, rect.y + 54, rect.width - 28, 6)
            pygame.draw.rect(self.screen, COLORS["hp_bg"], bar, border_radius=3)
            bar.width = int(bar.width * (1 - game.reload_frames_left / game.reload_frames_total))
            if bar.width:
                pygame.draw.rect(self.screen, COLORS["player"], bar, border_radius=3)
        if game.cfg.limited_ammo and p.ammo == 0 and not game.game_over and not reloading and show_notice:
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

        # 메뉴의 조작 안내 설정을 즉시 반영한다.
        if show_controls:
            for i, hint in enumerate(("WASD 이동 · 마우스 조준 / 발사 · Tab 능력치", "R 재장전 · Q 고유 스킬 · ESC 화면 설정")):
                surf = self.font_small.render(hint, True, COLORS["text"])
                self.screen.blit(surf, surf.get_rect(midtop=(W / 2 + 30, 10 + i * 23)))
        self._draw_skills(game)

    def _draw_progression(self, game, show_notice):
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
        xp = self.font_label.render(f"EXP  {game.xp} / {game.xp_to_next_level}", True, COLORS["white"])
        self.screen.blit(xp, xp.get_rect(center=bar.center))
        if stat_upgrades_visible(game):
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
        H = self.size[1]
        self._panel(pygame.Rect(14, H - 134, 224, 118), 195, 10)
        title = self.font_small.render(f"강화 {game.upgrade_points}P  ·  1–3 / + 클릭", True, COLORS["player"])
        self.screen.blit(title, (22, H - 126))
        for i, (card, coords) in enumerate(stat_rows(*self.size, game.stat_choices)):
            rect = pygame.Rect(coords)
            pygame.draw.rect(self.screen, (25, 38, 59), rect, border_radius=8)
            pygame.draw.rect(self.screen, (65, 110, 140), rect, 1, border_radius=8)
            text = self.font_small.render(f"{i + 1}  {card.title}", True, COLORS["white"])
            self.screen.blit(text, (rect.x + 5, rect.y + 2))
            rank = self.font_label.render(str(game.stat_levels[card.key]), True, COLORS["player"])
            self.screen.blit(rank, (rect.right - 45, rect.y + 3))
            plus = pygame.Rect(rect.right - 24, rect.y + 1, 23, 20)
            pygame.draw.rect(self.screen, (80, 185, 215), plus, border_radius=7)
            label = self.font_body.render("+", True, (10, 25, 35))
            self.screen.blit(label, label.get_rect(center=plus.center))
            if rect.collidepoint(pygame.mouse.get_pos()):
                self._tooltip(card.description, (14, H - 174), 300)

    def _draw_skills(self, game):
        skill = game.active_skill
        if skill is None:
            return
        rect = pygame.Rect(self.size[0] - 208, self.size[1] - 62, 194, 46)
        self._panel(rect, 190)
        image = self.assets.image("ships/" + game.player.job, 34)
        self.screen.blit(image, (rect.x + 4, rect.y + 6))
        title = self.font_small.render("Q · " + skill.title, True, COLORS["player"])
        self.screen.blit(title, (rect.x + 42, rect.y + 4))
        status = ("충전 중" if game.charge_frames_left else "사용 중" if game.skill_frames_left or game.dash_frames_left
                  else f"{game.skill_cooldown / game.cfg.fps:.1f}초" if game.skill_cooldown else "준비")
        text = self.font_small.render(status, True, COLORS["text"])
        self.screen.blit(text, (rect.x + 42, rect.y + 25))

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
        heading = (f"Lv.{level} 전직 · F2–F{count + 1} / 클릭" if count > 1
                   else f"Lv.{level} 숙련 · F2 / 클릭" if count else f"다음 성장 Lv.{level}")
        self.screen.blit(self.font_small.render(heading, True, (225, 205, 145)), (16, 61))
        cards = game.reward_choices
        if not cards and game.reward_portrait and game.frame < game.reward_message_until:
            from progression import SHIPS
            cards = (SHIPS[game.reward_portrait],)
        for i, card in enumerate(cards):
            rect = pygame.Rect(special_cards(*self.size, len(cards))[i])
            self._panel(rect, 205, 10)
            image = self.assets.image("ships/" + card.key, 62)
            self.screen.blit(image, image.get_rect(midtop=(rect.centerx, rect.y + 3)))
            name = self.font_small.render(card.title, True, COLORS["white"])
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
