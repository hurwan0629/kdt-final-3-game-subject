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

from space_z.config import GameConfig
from space_z.game.terrain import WALL, MUD, BREAKABLE
from space_z.config.progression_definitions import SHIPS, JOB_NAMES, STAT_MAX_LEVEL
from space_z.rendering.progression_panel import (
    build_stat_upgrade_rows,
    get_evolution_card_rects,
    can_show_stat_upgrades,
    build_player_stat_summary,
    get_collapsed_stat_panel_rect,
)
from space_z.rendering.sprite_assets import SpriteAssets, ENEMY_SUFFIX, ELITE_SUFFIX

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
    "square": (255, 220, 110),  # 별 조각
    "triangle": (232, 124, 86),  # 암석 행성
    "pentagon": (128, 118, 255),  # 고리 행성
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
SPAWN_FRAMES = 14  # 등장 애니메이션 길이
SHAPE_FADE_FRAMES = 60  # 천체는 1초 동안 서서히 떠오른다
SCORE_TEXT_FRAMES = 50  # "+점수" 글자가 떠오르는 시간
SCORE_POPUP_FRAMES = 60  # 점수 팝업 기록을 유지하는 게임 프레임 수
CONFIRMED_DIFFICULTY_ALPHA = 170  # 다른 난이도를 가리킬 때 확정된 난이도의 불투명도
DEATH_FRAMES = 22  # 파괴/폭발 애니메이션 길이
FLASH_FRAMES = 5  # 피격 깜빡임 길이
MIN_BULLET_SCREEN_DIAMETER = 4  # 줌아웃해도 탄체 폭을 화면 기준 최소 4px로 표시
MINIMAP_ALPHA = 165  # 우하단 미니맵 반투명도 (0=완전 투명, 255=불투명)


def _mix(start_color, end_color, blend_ratio):
    return tuple(
        int(start_channel + (end_channel - start_channel) * blend_ratio)
        for start_channel, end_channel in zip(start_color, end_color)
    )


def _hp_color(ratio):
    if ratio > 0.5:
        return _mix((250, 210, 80), (90, 230, 170), (ratio - 0.5) * 2)
    return _mix((245, 80, 100), (250, 210, 80), ratio * 2)


class Renderer:
    # 읽는 순서: __init__() → draw() / draw_main_menu() → 필요한 세부 그리기 함수.
    def __init__(self, config: GameConfig, caption: str = "Space Z - RL Demo"):
        # 화면 설정을 검증하고 창·이미지·프레임 제어 객체를 준비한다.
        self.config = config
        if not 0 < config.camera_zoom <= 1:
            raise ValueError("camera_zoom은 0보다 크고 1 이하여야 합니다.")
        self.fullscreen = False
        self.windowed_size = (config.window_width, config.window_height)
        self.screen = pygame.display.set_mode(self.windowed_size, pygame.RESIZABLE)
        self.assets = SpriteAssets()
        self._explosion_frames = (
            self._make_explosion_frames()
        )  # 중심과 캔버스를 맞춘 폭발 8단계
        self.set_zoom(config.camera_zoom)
        pygame.display.set_caption(caption)
        self.clock = pygame.time.Clock()
        # 시스템 폰트가 없으면 pygame 기본 폰트로 대체됨 → 실행 파일에서도 안전
        font_families = (
            "malgungothic,applegothic,nanumgothic,notosanscjkkr,segoeui,arial"
        )
        self.font_hud = pygame.font.SysFont(font_families, 22, bold=True)
        self.font_label = pygame.font.SysFont(font_families, 13, bold=True)
        self.font_small = pygame.font.SysFont(font_families, 14)
        self.font_big = pygame.font.SysFont(font_families, 56, bold=True)
        self.font_card = pygame.font.SysFont(font_families, 24, bold=True)
        self.font_body = pygame.font.SysFont(font_families, 17)
        self.font_mono = pygame.font.SysFont("consolas,couriernew,monospace", 13)
        self.font_score = pygame.font.SysFont(font_families, 22, bold=True)
        self.font_score_big = pygame.font.SysFont(font_families, 30, bold=True)

        # 게임 난수와 분리된 배경·연출용 난수와 캐시를 초기화한다.
        self._rand = random.Random(2024)  # 렌더러 전용 (배경 별 배치 등)
        self._glow_cache = {}
        self._bg = self._make_background()
        self.camera_x = self.camera_y = 0
        self._twinkles = [
            (
                self._rand.uniform(0, config.world_width),
                self._rand.uniform(0, config.world_height),
                self._rand.uniform(0, 6.28),
                self._rand.uniform(0.02, 0.07),
            )
            for _ in range(8 * config.world_scale**2)
        ]
        self._shape_sprites = {
            shape_kind: self._make_shape_sprite(shape_kind)
            for shape_kind in ("square", "triangle", "pentagon")
        }
        self._terrain_key = None
        self._floor = None  # 배경 + 성운/중력장/소행성 캐시
        self._minimap_key = None
        self._minimap_floor = None
        self._tick = 0

        # 연출용 기록 (게임 상태와 무관)
        self._last_frame = -1
        self._first_seen = {}  # id -> 처음 본 frame (등장 애니메이션)
        self._prev_hp = {}  # 도형 id -> 이전 hp (피격 깜빡임)
        self._hit_frame = {}  # 도형 id -> 마지막 피격 frame
        self._prev_shapes = {}  # id -> 이전 프레임 도형 (사라짐 감지)
        self._prev_alive = {}  # 적 id -> 이전 alive
        self._ghosts = []  # 파괴 애니메이션: dict(kind, x, y, r, angle, color, age)
        self.reset_score_popups()

    # ------------------------------------------------------------------
    # 화면 출력의 진입점: 게임 화면과 메인 메뉴
    # ------------------------------------------------------------------
    def draw(
        self,
        game,
        debug_lines=None,
        paused=False,
        show_ai=False,
        show_controls=True,
        menu=None,
        selected_button_index=-1,
        show_stats=False,
        stat_panel_collapsed=False,
    ):
        self._tick += 1
        self._update_camera(game.player)

        # 지난 화면과 현재 게임 상태를 비교해 등장·피격·파괴 연출을 갱신한다.
        self._track(game)
        self._ensure_terrain(game.terrain)
        self._flash_on = not game.game_over  # 게임오버로 멈춘 화면에서는 깜빡임 끔
        display = self.screen
        self.screen = display_surface = self._view
        # 맵 밖에도 우주 배경을 채우며 카메라는 가장자리에서도 선체를 따라간다.
        bg_width, bg_height = self._bg.get_size()
        offset_x, offset_y = round(-self.camera_x), round(-self.camera_y)
        start_x, start_y = (
            offset_x % bg_width - bg_width,
            offset_y % bg_height - bg_height,
        )
        for y in range(start_y, self.view_height, bg_height):
            for x in range(start_x, self.view_width, bg_width):
                display_surface.blit(self._bg, (x, y))
        display_surface.blit(self._floor, (offset_x, offset_y))
        self._draw_twinkles()
        frame = game.frame
        player = game.player

        # 카메라 영역 안의 천체·우주선·탄환을 월드 좌표에 그린다.
        for shape in game.shapes:
            if self._visible(shape.x, shape.y):
                self._draw_shape(shape, frame)
        for enemy in game.enemies:
            if enemy.alive and self._visible(enemy.x, enemy.y, enemy.radius * 3):
                self._draw_ship(enemy, frame)
        if player.alive:
            self._draw_ship(player, frame, is_player=True)
        for bullet in game.combat.bullets:
            if self._visible(bullet.x, bullet.y):
                self._draw_bullet(bullet)
        self._draw_combat_effects(game)
        self._draw_score_effects(game)
        for ghost in self._ghosts:
            if self._visible(ghost["x"], ghost["y"]):
                self._draw_ghost(ghost)
        # 체력바는 모든 물체 위에 (숨은 적의 체력바는 그리지 않음)
        for shape in game.shapes:
            if shape.hp < shape.max_hp:
                self._hp_bar(
                    shape.x,
                    shape.y + shape.radius + 9,
                    shape.radius * 2.2,
                    shape.hp / shape.max_hp,
                )
        for enemy in game.enemies:
            if enemy.alive and enemy.hp < enemy.max_hp:
                self._hp_bar(
                    enemy.x,
                    enemy.y + enemy.radius + 12,
                    enemy.radius * 2.6,
                    enemy.hp / enemy.max_hp,
                )
        if player.alive and player.hp < player.max_hp:
            self._hp_bar(
                player.x,
                player.y + player.radius + 12,
                player.radius * 2.6,
                player.hp / player.max_hp,
            )
        if show_ai:
            self._draw_ai_debug(game)

        self.screen = display
        pygame.transform.smoothscale(display_surface, self.size, display)
        self._draw_world_boundary()
        self._draw_score_text(game)

        # 화면 좌표로 HUD·메뉴·디버그 패널을 덧그린다.
        self._draw_hud(
            game,
            paused,
            show_notice=menu is None,
            show_controls=show_controls,
            stat_panel_collapsed=stat_panel_collapsed,
        )
        if debug_lines:
            self._draw_debug(debug_lines)
        if show_stats and not paused and menu is None and not game.game_over:
            self._draw_stats_panel(game)
        if menu is not None:
            self._draw_menu(menu, "일시정지 · 설정", selected_button_index)
        elif game.game_over:
            self._draw_game_over(game)
        elif paused:
            self._draw_card(["일시정지"], ["P / ESC: 계속"])

    def draw_main_menu(self, buttons, selected_button_index=0):
        self.screen.blit(self.assets.image("backgrounds/main", self.size), (0, 0))
        self._draw_menu(buttons, "SPACE Z", selected_button_index, main=True)

    # ------------------------------------------------------------------
    # 폭발 프레임: 서로 다른 원본 크기를 공통 캔버스에 정렬
    # ------------------------------------------------------------------
    def _make_explosion_frames(self):
        """폭발 원본 8장의 비율을 유지하며 같은 크기·중심의 표면으로 정렬한다."""

        # 폭발 단계별 원본 이미지를 가져와 공통 캔버스 크기를 정한다.
        sources = [
            self.assets._source(f"etc/boom_effect_{frame_index:02d}")
            for frame_index in range(1, 9)
        ]
        side = max(max(image.get_size()) for image in sources)
        frames = []

        # 각 폭발 이미지를 같은 중심에 맞춰 애니메이션 프레임으로 저장한다.
        for source in sources:
            frame = pygame.Surface((side, side), pygame.SRCALPHA)
            frame.blit(source, source.get_rect(center=(side // 2, side // 2)))
            frames.append(frame)
        return tuple(frames)

    def _draw_explosion(self, x, y, diameter, progress):
        """월드 좌표의 폭발을 진행도(0~1)에 해당하는 이미지로 그린다."""

        # 폭발 진행도에 해당하는 프레임과 표시 크기를 선택한다.
        if not 0 <= progress < 1:
            return
        frame = self._explosion_frames[
            min(
                len(self._explosion_frames) - 1,
                int(progress * len(self._explosion_frames)),
            )
        ]
        side = max(8, round(diameter))
        image = pygame.transform.smoothscale(frame, (side, side))

        # 폭발의 월드 중심을 현재 카메라 위치에 맞춰 그린다.
        center = tuple(round(value) for value in self.world_to_view(x, y))
        self.screen.blit(image, image.get_rect(center=center))

    # ------------------------------------------------------------------
    # 빛 번짐 스프라이트 (BLEND_ADD로 더해서 발광 효과)
    # ------------------------------------------------------------------
    def _glow(self, radius, color, intensity=1.0):
        # 빛 번짐의 크기·색·강도를 캐시 키로 묶는다.
        radius = max(2, int(radius))
        key = (radius, color, round(intensity, 2))
        surface = self._glow_cache.get(key)

        # 캐시에 없는 빛 번짐은 중심 밝기를 가진 원형 이미지로 만든다.
        if surface is None:
            surface = pygame.Surface((radius * 2, radius * 2))
            surface.fill((0, 0, 0))
            for ring_radius in range(radius, 0, -1):
                brightness = (1 - ring_radius / radius) ** 2 * intensity
                pygame.draw.circle(
                    surface,
                    tuple(min(255, int(channel * brightness)) for channel in color),
                    (radius, radius),
                    ring_radius,
                )
            if len(self._glow_cache) > 600:
                self._glow_cache.clear()
            self._glow_cache[key] = surface
        return surface

    def _blit_glow(self, target, x, y, radius, color, intensity=1.0):
        glow_surface = self._glow(radius, color, intensity)
        target.blit(
            glow_surface,
            (
                int(x) - glow_surface.get_width() // 2,
                int(y) - glow_surface.get_height() // 2,
            ),
            special_flags=pygame.BLEND_ADD,
        )

    # ------------------------------------------------------------------
    # 배경: 그라데이션 우주 + 희미한 성운 + 별
    # ------------------------------------------------------------------
    def _make_background(self):
        # 월드 크기에 맞춘 우주 배경에 성운과 색조를 합성한다.
        size = (self.config.world_width, self.config.world_height)
        surface = self.assets.image("backgrounds/deep_space", size).copy()
        haze = self.assets.image("backgrounds/nebula", size).copy()
        haze.set_alpha(35)
        surface.blit(haze, (0, 0))
        surface.fill((205, 215, 230), special_flags=pygame.BLEND_RGB_MULT)
        return surface

    def _draw_twinkles(self):
        # 배경 별의 밝기를 갱신하고 카메라 영역 안의 별만 그린다.
        for x, y, phase, speed in self._twinkles:
            brightness_ratio = 0.5 + 0.5 * math.sin(self._tick * speed + phase)
            brightness = int(90 + 165 * brightness_ratio)
            view_x, view_y = self.world_to_view(x, y)
            if (
                -2 <= view_x <= self.view_width + 2
                and -2 <= view_y <= self.view_height + 2
            ):
                pygame.draw.circle(
                    self.screen,
                    (brightness, brightness, min(255, brightness + 20)),
                    (int(view_x), int(view_y)),
                    1 if brightness_ratio < 0.7 else 2,
                )

    # ------------------------------------------------------------------
    # 지형 (지형이 바뀔 때만 다시 그림)
    # ------------------------------------------------------------------
    def _draw_full_wall_blocks(self, floor, terrain):
        """빈칸이 없는 8×8 벽 영역을 큰 이미지로 그리고 처리한 타일 좌표를 반환한다."""
        block = max(
            self.config.terrain.block_tiles,
            2 * math.ceil(self.config.terrain.navigation_radius / terrain.tile) + 1,
        )
        covered = set()
        if block != 8:
            return covered  # 다른 크기의 생성 블록은 기존 타일별 렌더링을 사용한다.
        # 랜덤 생성기의 가운데 정렬을 따르고, 파일 맵은 첫 타일부터 검사한다.
        col_offset, row_offset = (
            ((terrain.cols % block) // 2, (terrain.rows % block) // 2)
            if terrain.name == "random"
            else (0, 0)
        )
        for row in range(row_offset, terrain.rows - block + 1, block):
            for col in range(col_offset, terrain.cols - block + 1, block):
                cells = [
                    (tile_col, tile_row)
                    for tile_row in range(row, row + block)
                    for tile_col in range(col, col + block)
                ]
                if not all(
                    terrain.tiles[tile_row][tile_col] in (WALL, BREAKABLE)
                    for tile_col, tile_row in cells
                ):
                    continue
                variant = (col // block * 3 + row // block * 5) % 4 + 1
                image = self.assets.image(
                    f"etc/guard_{variant:02d}", block * terrain.tile
                )
                breakable = [
                    (tile_col, tile_row)
                    for tile_col, tile_row in cells
                    if terrain.tiles[tile_row][tile_col] == BREAKABLE
                ]
                if breakable:
                    image = (
                        image.copy()
                    )  # 일반 벽과 섞여 있어도 파괴 가능한 영역만 착색한다.
                    for tile_col, tile_row in breakable:
                        area = pygame.Rect(
                            (tile_col - col) * terrain.tile,
                            (tile_row - row) * terrain.tile,
                            terrain.tile,
                            terrain.tile,
                        )
                        image.fill(
                            (230, 175, 130, 255),
                            area,
                            special_flags=pygame.BLEND_RGBA_MULT,
                        )
                floor.blit(image, (col * terrain.tile, row * terrain.tile))
                covered.update(cells)
        return covered

    def _ensure_terrain(self, terrain):
        # 맵과 지형 버전이 같으면 이전 지형 이미지를 재사용한다.
        key = (id(terrain), terrain.version)
        if key == self._terrain_key:
            return
        self._terrain_key = key

        # 배경 위에 큰 벽 블록을 먼저 배치하고 나머지 타일을 그린다.
        tile = terrain.tile
        floor = self._bg.copy()
        covered = self._draw_full_wall_blocks(floor, terrain)
        solids = (WALL, BREAKABLE)
        for row in range(terrain.rows):
            for col in range(terrain.cols):
                kind = terrain.tiles[row][col]
                rect = pygame.Rect(col * tile, row * tile, tile, tile)
                center = rect.center
                if kind == MUD:
                    image = self.assets.image("objects/gravity_field", tile * 1.25)
                    floor.blit(image, image.get_rect(center=center))
                elif kind in solids:
                    if (col, row) not in covered:
                        # 빈칸이 있는 블록·가장자리·다른 블록 크기는 작은 이미지로 그린다.
                        variant = (col * 3 + row * 5) % 4 + 1
                        image = self.assets.image(f"etc/guard_{variant:02d}", tile)
                        if kind == BREAKABLE:
                            image = image.copy()
                            image.fill(
                                (230, 175, 130, 255),
                                special_flags=pygame.BLEND_RGBA_MULT,
                            )
                        floor.blit(image, rect)
                    if (
                        kind == BREAKABLE
                        and terrain.hp[(col, row)] < terrain.breakable_hp_max
                    ):
                        ratio = terrain.hp[(col, row)] / terrain.breakable_hp_max
                        pygame.draw.line(
                            floor,
                            (255, 170, 90),
                            (center[0] - 16, center[1] + 16),
                            (center[0] - 16 + round(32 * ratio), center[1] + 16),
                            2,
                        )
        self._floor = floor

    # ------------------------------------------------------------------
    # 도형 → 천체 스프라이트 (한 번 만들어두고 회전/확대해서 씀)
    # ------------------------------------------------------------------
    def _make_shape_sprite(self, kind):
        from space_z.config import SHAPE_TYPES

        path = {
            "square": "star_fragment",
            "triangle": "rock_planet",
            "pentagon": "ring_planet",
        }[kind]
        sprite = self.assets.image("objects/" + path, SHAPE_TYPES[kind]["radius"] * 2.8)
        flash = sprite.copy()
        flash.fill((100, 100, 100, 0), special_flags=pygame.BLEND_RGBA_ADD)
        return sprite, flash

    # ------------------------------------------------------------------
    # 연출 기록 갱신
    # ------------------------------------------------------------------
    def reset_score_popups(self):
        """새 판을 시작할 때 점수 팝업과 관련 화면 연출을 초기화한다.

        인자:
            없음.

        처리:
            1) 팝업 목록과 고유 번호를 초기화한다.
            2) 점수 불꽃·처리한 번호·경험치 반짝임 시각을 초기화한다.

        반환:
            None: 렌더러의 점수 연출 상태만 변경한다.
        """

        # 1) 팝업 목록과 고유 번호를 초기화한다.
        self.score_popups = []  # 표시 중인 팝업 (번호, 발생 프레임, x, y, 점수, 종류)
        self._popup_id = 0  # 화면 연출용 팝업 고유 번호

        # 2) 점수 불꽃·처리한 번호·경험치 반짝임 시각을 초기화한다.
        self._sparks = []  # 점수 획득 불꽃의 위치·속도·수명·색
        self._popups_seen = set()  # 이미 불꽃 연출을 생성한 팝업 번호
        self._xp_flash_frame = -999  # 최근 점수 획득의 게임 프레임

    def add_score_popups(self, score_award_events):
        """전달받은 점수 획득 이벤트를 렌더러의 팝업으로 변환한다.

        인자:
            score_award_events: (발생 프레임, 월드 x, 월드 y, 점수, 대상 종류) 목록.
                앱이나 학습 환경이 코어에서 한 번 꺼낸 이벤트를 전달한다.

        처리:
            1) 각 이벤트에 화면 연출용 고유 번호를 발급한다.
            2) 발생 프레임·위치·점수·종류를 팝업 목록에 추가한다.
            발생 시각을 유지해 여러 게임 프레임 뒤에 그려도 표시 시간이 맞도록 한다.

        반환:
            None: 렌더러의 팝업 목록과 번호만 변경한다.
        """
        for frame, x, y, amount, kind in score_award_events:
            # 1) 화면 연출용 고유 번호를 발급한다.
            self._popup_id += 1

            # 2) 원래 발생 시각을 유지한 팝업을 목록에 추가한다.
            self.score_popups.append((self._popup_id, frame, x, y, amount, kind))

    def _track(self, game):
        # 새 판인지 확인하고 이전 판의 등장·피격·파괴 기록을 비운다.
        current_frame = game.frame
        if current_frame < self._last_frame:  # 재시작
            self._first_seen.clear()
            self._prev_hp.clear()
            self._hit_frame.clear()
            self._prev_shapes.clear()
            self._prev_alive.clear()
            self._ghosts.clear()
            self._sparks.clear()
            self._popups_seen.clear()
        # 파괴 애니메이션 진행량: 게임 프레임 기준, 단 게임오버로 멈춘 동안에도 끝까지 재생
        delta = (
            current_frame - self._last_frame
            if current_frame > self._last_frame
            else (1 if game.game_over else 0)
        )
        for ghost in self._ghosts:
            ghost["age"] += delta
        self._last_frame = current_frame
        self.score_popups = [
            popup
            for popup in self.score_popups
            if current_frame - popup[1] <= SCORE_POPUP_FRAMES
        ]

        # 사라진 천체를 파괴 연출로 옮기고 남은 천체의 피격 시점을 기록한다.
        current_shapes = {shape.id: shape for shape in game.shapes}
        for shape_id, shape in self._prev_shapes.items():
            if shape_id not in current_shapes:
                self._ghosts.append(
                    dict(
                        kind=shape.kind,
                        x=shape.x,
                        y=shape.y,
                        r=shape.radius,
                        angle=shape.angle,
                        color=COLORS[shape.kind],
                        age=0,
                    )
                )
        for shape in game.shapes:
            # 판을 시작할 때 이미 있던 천체는 바로 보이고, 도중에 생긴 것만 서서히 나타난다.
            self._first_seen.setdefault(
                shape.id, current_frame if current_frame > 0 else -(10**6)
            )
            if shape.hp < self._prev_hp.get(shape.id, shape.hp):
                self._hit_frame[shape.id] = current_frame
            self._prev_hp[shape.id] = shape.hp
        self._prev_shapes = {
            shape_id: _ShapeSnap(shape) for shape_id, shape in current_shapes.items()
        }

        # 적과 플레이어의 생존 변화를 등장·파괴 연출에 반영한다.
        for enemy in game.enemies:
            was_alive = self._prev_alive.get(enemy.id, enemy.alive)
            if was_alive and not enemy.alive:
                self._ghosts.append(
                    dict(
                        kind="ship",
                        x=enemy.x,
                        y=enemy.y,
                        r=enemy.radius,
                        angle=enemy.angle,
                        color=COLORS["enemy"],
                        age=0,
                    )
                )
            if not was_alive and enemy.alive:
                self._first_seen[enemy.id] = current_frame
            self._first_seen.setdefault(enemy.id, current_frame)
            self._prev_alive[enemy.id] = enemy.alive
        player = game.player
        if self._prev_alive.get(player.id, True) and not player.alive:
            self._ghosts.append(
                dict(
                    kind="ship",
                    x=player.x,
                    y=player.y,
                    r=player.radius,
                    angle=player.angle,
                    color=COLORS["player"],
                    age=0,
                )
            )
        self._prev_alive[player.id] = player.alive

        self._ghosts = [ghost for ghost in self._ghosts if ghost["age"] < DEATH_FRAMES]
        # 점수를 얻은 자리에서 불꽃이 튀고 EXP 바가 반짝인다.
        for spark in self._sparks:
            for _ in range(delta):
                spark[0] += spark[2]
                spark[1] += spark[3]
                spark[2] *= 0.9
                spark[3] *= 0.9
            spark[4] += delta
        self._sparks = [spark for spark in self._sparks if spark[4] < spark[5]]
        for popup_id, frame, x, y, amount, kind in self.score_popups:
            if popup_id in self._popups_seen:
                continue
            self._popups_seen.add(popup_id)
            self._xp_flash_frame = frame
            color = COLORS.get(kind, COLORS["elite"])
            count = 10 if amount < 50 else 18 if amount < 200 else 26
            for _ in range(count):
                angle = self._rand.uniform(0, math.tau)
                speed = self._rand.uniform(2.0, 5.5) * (1.3 if amount >= 100 else 1.0)
                self._sparks.append(
                    [
                        x,
                        y,
                        math.cos(angle) * speed,
                        math.sin(angle) * speed,
                        0,
                        self._rand.randint(18, 32),
                        _mix(color, (255, 255, 255), 0.35),
                    ]
                )
        if len(self._popups_seen) > 500:
            self._popups_seen = {popup[0] for popup in self.score_popups}
        # 오래된 id 정리
        if len(self._first_seen) > 400:
            live = (
                set(current_shapes) | {enemy.id for enemy in game.enemies} | {player.id}
            )
            self._first_seen = {
                entity_id: cached_value
                for entity_id, cached_value in self._first_seen.items()
                if entity_id in live
            }
            self._prev_hp = {
                entity_id: cached_value
                for entity_id, cached_value in self._prev_hp.items()
                if entity_id in live
            }
            self._hit_frame = {
                entity_id: cached_value
                for entity_id, cached_value in self._hit_frame.items()
                if entity_id in live
            }

    def _spawn_scale(self, entity_id, frame):
        # 등장 후 경과한 시간으로 우주선의 표시 크기를 계산한다.
        spawn_progress = (frame - self._first_seen.get(entity_id, -999)) / SPAWN_FRAMES
        if spawn_progress >= 1:
            return 1.0
        spawn_progress = max(0.0, spawn_progress)
        return 1 - (1 - spawn_progress) ** 3  # ease-out

    # ------------------------------------------------------------------
    # 그리기
    # ------------------------------------------------------------------
    @property
    def size(self):
        return self.screen.get_size()

    def resize(self, size):
        # 창 모드에서 최소 화면 크기를 보장하고 카메라 표시 영역을 다시 만든다.
        if self.fullscreen:
            return
        self.windowed_size = (max(960, size[0]), max(640, size[1]))
        self.screen = pygame.display.set_mode(self.windowed_size, pygame.RESIZABLE)
        self.set_zoom(self.config.camera_zoom)

    def set_fullscreen(self, enabled):
        # 전체화면 전환이 필요한지 확인하고 이전 창 크기를 보관하거나 복원한다.
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
                self.screen = pygame.display.set_mode(
                    self.windowed_size, pygame.RESIZABLE
                )

        # 전환한 창 크기에 맞춰 카메라 표시 영역을 다시 만든다.
        self.fullscreen = enabled
        self.set_zoom(self.config.camera_zoom)

    def set_zoom(self, zoom):
        if not 0 < zoom <= 1:
            raise ValueError("camera_zoom은 0보다 크고 1 이하여야 합니다.")
        self.config.camera_zoom = zoom
        self.effective_zoom = zoom
        # 선체를 그릴 때 반올림해도 정중앙에 오도록 뷰 크기를 짝수로 유지한다.
        self.view_width = max(2, 2 * round(self.size[0] / (2 * zoom)))
        self.view_height = max(2, 2 * round(self.size[1] / (2 * zoom)))
        self._view = pygame.Surface((self.view_width, self.view_height)).convert()

    def world_to_view(self, x, y):
        return x - self.camera_x, y - self.camera_y

    def world_to_screen(self, x, y):
        view_x, view_y = self.world_to_view(x, y)
        return view_x * self.size[0] / self.view_width, view_y * self.size[
            1
        ] / self.view_height

    def screen_to_world(self, x, y):
        return (
            x * self.view_width / self.size[0] + self.camera_x,
            y * self.view_height / self.size[1] + self.camera_y,
        )

    def _update_camera(self, player):
        self.camera_x = player.x - self.view_width / 2
        self.camera_y = player.y - self.view_height / 2

    def _visible(self, x, y, margin=100):
        view_x, view_y = self.world_to_view(x, y)
        return (
            -margin <= view_x <= self.view_width + margin
            and -margin <= view_y <= self.view_height + margin
        )

    def _draw_world_boundary(self):
        """0.5px 외곽선을 화면 1px의 절반 농도로 표현한다."""

        # 월드 경계를 화면 좌표로 옮기고 경계선이 화면에 보이는지 확인한다.
        left, top = (round(value) for value in self.world_to_screen(0, 0))
        right, bottom = (
            round(value)
            for value in self.world_to_screen(
                self.config.world_width, self.config.world_height
            )
        )
        width, height = self.size
        if left < 0 and top < 0 and right >= width and bottom >= height:
            return

        # 반투명 레이어에 월드 외곽선을 그린 뒤 화면에 합성한다.
        layer = getattr(self, "_world_boundary_layer", None)
        if layer is None or layer.get_size() != self.size:
            layer = self._world_boundary_layer = pygame.Surface(
                self.size, pygame.SRCALPHA
            )
        layer.fill((0, 0, 0, 0))
        points = [
            (round(x), round(y))
            for x, y in ((left, top), (right, top), (right, bottom), (left, bottom))
        ]
        pygame.draw.lines(layer, (255, 0, 0, 128), True, points, 1)
        self.screen.blit(layer, (0, 0))

    def _draw_score_effects(self, game):
        # 점수 획득 불꽃의 남은 수명에 맞춰 밝기와 크기를 줄여 그린다.
        for x, y, _, _, age, life, color in self._sparks:
            if not self._visible(x, y):
                continue
            remaining_ratio = 1 - age / life
            view_x, view_y = self.world_to_view(x, y)
            self._blit_glow(
                self.screen,
                view_x,
                view_y,
                5 + 9 * remaining_ratio,
                color,
                round(remaining_ratio * 4) / 4,
            )
            pygame.draw.circle(
                self.screen,
                color,
                (round(view_x), round(view_y)),
                max(1, round(4.5 * remaining_ratio)),
            )

    def _draw_score_text(self, game):
        """줌과 관계없이 읽히도록 "+점수"는 화면 좌표에 고정 크기로 그린다."""
        for _, frame, x, y, amount, kind in self.score_popups:
            age = game.frame - frame
            if age > SCORE_TEXT_FRAMES or not self._visible(x, y):
                continue
            progress = age / SCORE_TEXT_FRAMES
            # 처음엔 살짝 커졌다가 위로 떠오르며 사라진다.
            text_scale = 1 + 0.35 * max(0.0, 1 - age / 8)
            font = self.font_score_big if amount >= 100 else self.font_score
            color = (255, 230, 120) if kind != "elite" else (255, 190, 60)
            text = font.render(f"+{amount}", True, color)
            shadow = font.render(f"+{amount}", True, (40, 25, 0))
            if text_scale > 1:
                size = (
                    round(text.get_width() * text_scale),
                    round(text.get_height() * text_scale),
                )
                text, shadow = (
                    pygame.transform.smoothscale(text, size),
                    pygame.transform.smoothscale(shadow, size),
                )
            alpha = (
                255 if progress < 0.55 else round(255 * (1 - (progress - 0.55) / 0.45))
            )
            text.set_alpha(alpha)
            shadow.set_alpha(alpha // 2)
            screen_x, screen_y = self.world_to_screen(x, y)
            screen_y -= 14 + 40 * (1 - (1 - progress) ** 2)
            self.screen.blit(
                shadow,
                shadow.get_rect(center=(round(screen_x) + 2, round(screen_y) + 2)),
            )
            self.screen.blit(
                text, text.get_rect(center=(round(screen_x), round(screen_y)))
            )

    def _draw_combat_effects(self, game):
        for beam in game.combat.beams:
            start = self.world_to_view(beam.x, beam.y)
            end = self.world_to_view(beam.end_x, beam.end_y)
            pygame.draw.line(self.screen, (30, 105, 125), start, end, 10)
            pygame.draw.line(self.screen, (95, 245, 255), start, end, 5)
            pygame.draw.line(self.screen, (240, 255, 255), start, end, 2)
        for explosion in game.combat.explosions:
            self._draw_explosion(
                explosion.x, explosion.y, explosion.radius * 2, 1 - explosion.life / 18
            )

    def _draw_menu(self, buttons, title, selected_button_index, main=False):
        # 메뉴 배경과 제목·설명 문구를 배치한다.
        screen_width, screen_height = self.size
        shade = pygame.Surface((screen_width, screen_height), pygame.SRCALPHA)
        shade.fill((0, 0, 15, 100 if main else 215))
        self.screen.blit(shade, (0, 0))
        if not main:
            self._panel(
                pygame.Rect(
                    screen_width // 2 - 225, screen_height // 2 - 276, 450, 552
                ),
                240,
                20,
            )
        font = self.font_big if main else self.font_card
        text = font.render(title, True, COLORS["white"])
        self.screen.blit(
            text,
            text.get_rect(
                center=(screen_width // 2, screen_height // 2 - (188 if main else 224))
            ),
        )
        subtitle = (
            "당신의 우주선을 지휘하세요"
            if main
            else "설정을 클릭해 변경 · ESC / P로 계속하기"
        )
        text = self.font_body.render(subtitle, True, COLORS["text"])
        self.screen.blit(
            text,
            text.get_rect(
                center=(screen_width // 2, screen_height // 2 - (132 if main else 194))
            ),
        )

        # 마우스와 키보드 선택 상태로 현재 강조할 버튼을 정한다.
        mouse = pygame.mouse.get_pos()
        hovered_button_index = next(
            (
                button_index
                # 활성화·난이도 확정 상태에 맞춰 버튼 그림과 글자를 합성한다.
                for button_index, button in enumerate(buttons)
                if button.enabled and button.rect.collidepoint(mouse)
            ),
            None,
        )
        focused_button_index = (
            hovered_button_index
            if hovered_button_index is not None
            else selected_button_index
        )
        difficulty_has_focus = (
            main
            and 0 <= focused_button_index < len(buttons)
            and buttons[focused_button_index].enabled
            and buttons[focused_button_index].key.startswith("difficulty_")
        )
        for button_index, button in enumerate(buttons):
            if main:
                active = button.enabled and button_index == focused_button_index
            else:
                active = button.enabled and (
                    button_index == selected_button_index
                    or button.rect.collidepoint(mouse)
                )
            difficulty_choice = main and button.key.startswith("difficulty_")
            highlighted = button.enabled and (
                active or (difficulty_choice and button.checked)
            )
            path = "etc/home_selected" if highlighted else "etc/home_selected_normal"
            image = self.assets.image(path, button.rect.size).copy()
            if not button.enabled:
                image.fill((100, 100, 100, 255), special_flags=pygame.BLEND_RGBA_MULT)
            text_color = (
                (48, 30, 20)
                if highlighted
                else (12, 32, 42)
                if button.enabled
                else (145, 150, 160)
            )
            font = (
                self.font_hud
                if difficulty_choice
                else self.font_card
                if main
                else self.font_body
            )
            if difficulty_choice and button.checked:
                pygame.draw.circle(image, text_color, (20, button.rect.height // 2), 3)
            label = font.render(button.label, True, text_color)
            image.blit(
                label,
                label.get_rect(
                    center=(button.rect.width // 2, button.rect.height // 2)
                ),
            )
            if (
                difficulty_has_focus
                and difficulty_choice
                and button.checked
                and not active
            ):
                image.set_alpha(CONFIRMED_DIFFICULTY_ALPHA)
            self.screen.blit(image, button.rect)
        hint = (
            "클릭 또는 ↑↓ / Enter로 선택"
            if main
            else "새 게임은 진행도를 초기화합니다 · 설정은 이번 실행 동안 유지됩니다"
        )
        text = self.font_small.render(hint, True, COLORS["text"])
        self.screen.blit(
            text,
            text.get_rect(center=(screen_width // 2, buttons[-1].rect.bottom + 30)),
        )

    def _draw_shape(self, shape, frame):
        # 천체 종류와 최근 피격 여부에 맞는 이미지를 고른다.
        sprite, flash = self._shape_sprites[shape.kind]
        image = (
            flash
            if self._flash_on
            and frame - self._hit_frame.get(shape.id, -999) < FLASH_FRAMES
            else sprite
        )
        # 투명한 상태에서 살짝 작게 시작해 천천히 선명해진다 (갑자기 튀어나오지 않게).
        fade_progress = min(
            1.0,
            max(
                0.0, (frame - self._first_seen.get(shape.id, -999)) / SHAPE_FADE_FRAMES
            ),
        )
        ease = fade_progress * fade_progress * (3 - 2 * fade_progress)
        if ease <= 0.02:
            return

        # 등장 진행도와 회전 방향을 반영해 천체를 그린다.
        image = pygame.transform.rotozoom(
            image, -math.degrees(shape.angle), 0.85 + 0.15 * ease
        )
        if ease < 1:
            image.set_alpha(round(255 * ease))
        x, y = self.world_to_view(shape.x, shape.y)
        self.screen.blit(image, image.get_rect(center=(int(x), int(y))))

    def _draw_bullet(self, bullet):
        # 탄환 종류와 이동 방향으로 사용할 이미지와 회전각을 정한다.
        path = (
            "cannon_shell"
            if bullet.kind == "shell"
            else "enemy_plasma"
            if bullet.team == "enemy"
            else "player_plasma"
        )
        angle = -90 - math.degrees(math.atan2(bullet.velocity_y, bullet.velocity_x))
        # 표시 크기만 보정한다. 탄환의 실제 충돌 반지름과 포구 계산은 유지한다.
        diameter = max(
            bullet.radius * 2,
            math.ceil(MIN_BULLET_SCREEN_DIAMETER / self.effective_zoom),
        )

        # 화면에서 식별 가능한 크기로 탄환을 그리고 저격탄에는 발광을 더한다.
        image = self.assets.projectile_image("projectiles/" + path, diameter, angle)
        x, y = self.world_to_view(bullet.x, bullet.y)
        if bullet.kind == "shell":
            # 저격 계열 포탄은 금속 회색이라 우주 배경에 묻히므로 발광을 더해 눈에 띄게 한다.
            glow = (
                COLORS["enemy_shot"]
                if bullet.team == "enemy"
                else COLORS["player_shot"]
            )
            self._blit_glow(self.screen, x, y, diameter * 1.1, glow, 0.9)
        self.screen.blit(image, image.get_rect(center=(round(x), round(y))))

    def _draw_ship(self, tank, frame, is_player=False):
        # 카메라 좌표와 등장 진행도에 맞춰 선체 표시 크기를 정한다.
        x, y = self.world_to_view(tank.x, tank.y)
        scale = self._spawn_scale(tank.id, frame)
        if scale < 0.08:
            return
        # 적도 같은 진화 그림을 쓰되 선체를 붉은색(엘리트는 금색)으로 바꿔 구분한다.
        suffix = "" if is_player else ELITE_SUFFIX if tank.elite else ENEMY_SUFFIX
        path = SHIPS[tank.job].asset + suffix
        image = self.assets.ship_image(
            path, tank.radius * 2 * scale, -math.degrees(tank.angle)
        )

        # 피격·엘리트 상태에 맞춰 선체 강조 효과를 더한다.
        if self._flash_on and frame - tank.last_hit_frame < FLASH_FRAMES:
            image = image.copy()
            image.fill((90, 90, 90, 0), special_flags=pygame.BLEND_RGBA_ADD)
        if tank.elite:
            self._blit_glow(
                self.screen, x, y, tank.radius * 1.6 * scale, (255, 190, 60), 0.5
            )
        self.screen.blit(image, image.get_rect(center=(round(x), round(y))))

        # 플레이어와 엘리트 우주선에 식별 문구를 표시한다.
        if is_player or tank.elite:
            text, color = (
                ("YOU", COLORS["white"]) if is_player else ("ELITE", COLORS["elite"])
            )
            label = self.font_label.render(text, True, color)
            self.screen.blit(label, label.get_rect(center=(x, y - tank.radius - 20)))

    def _draw_ghost(self, ghost):
        """우주선·천체 파괴 시 공통 폭발 8단계를 순서대로 재생한다."""
        self._draw_explosion(
            ghost["x"], ghost["y"], ghost["r"] * 3, ghost["age"] / DEATH_FRAMES
        )

    def _hp_bar(self, center_x, y, width, ratio, height=6):
        # 개체 체력바의 화면 위치와 표시 크기를 구한다.
        if not self._visible(center_x, y):
            return
        center_x, y = self.world_to_view(center_x, y)
        x = int(center_x - width / 2)
        width = int(width)
        pygame.draw.rect(
            self.screen,
            COLORS["hp_bg"],
            (x - 1, y - 1, width + 2, height + 2),
            border_radius=(height + 2) // 2,
        )

        # 체력 비율에 맞는 색상과 채움 길이로 체력바를 그린다.
        fill = max(height, int(width * ratio))
        pygame.draw.rect(
            self.screen,
            _hp_color(ratio),
            (x, y, fill, height),
            border_radius=height // 2,
        )

    def _draw_ai_debug(self, game):
        # 적의 경로·플레이어 감지·이동 목표를 표시할 좌표를 준비한다.
        terrain = game.terrain
        player = game.player

        # 살아 있는 적의 경로와 감지 선·목표점을 디버그 화면에 그린다.
        for enemy in game.enemies:
            if not enemy.alive:
                continue
            if enemy.ai_path:
                points = [self.world_to_view(enemy.x, enemy.y)] + [
                    self.world_to_view(*terrain.center(col, row))
                    for col, row in enemy.ai_path
                ]
                pygame.draw.lines(self.screen, (235, 190, 40), False, points, 2)
            if enemy.ai_can_see:
                pygame.draw.line(
                    self.screen,
                    (60, 220, 110),
                    self.world_to_view(enemy.x, enemy.y),
                    self.world_to_view(player.x, player.y),
                    2,
                )
            if enemy.ai_goal:
                goal_x, goal_y = self.world_to_view(*enemy.ai_goal)
                pygame.draw.circle(
                    self.screen, (235, 190, 40), (int(goal_x), int(goal_y)), 5, 2
                )

    # ------------------------------------------------------------------
    # HUD
    # ------------------------------------------------------------------
    def _panel(self, rect, alpha=170, radius=10):
        # 요청한 크기의 반투명 패널과 테두리를 만들어 화면에 합성한다.
        surface = pygame.Surface(rect.size, pygame.SRCALPHA)
        pygame.draw.rect(
            surface, (*COLORS["panel"], alpha), surface.get_rect(), border_radius=radius
        )
        pygame.draw.rect(
            surface,
            (*COLORS["panel_edge"], 150),
            surface.get_rect(),
            1,
            border_radius=radius,
        )
        self.screen.blit(surface, rect.topleft)

    def _draw_hud(
        self,
        game,
        paused,
        show_notice=True,
        show_controls=True,
        stat_panel_collapsed=False,
    ):
        # 플레이어 상태와 화면 크기·경과 시간을 읽는다.
        player = game.player
        screen_width, screen_height = self.size
        elapsed_seconds = game.frame / self.config.fps

        # 탄약 제한이 켜져 있으면 잔탄과 재장전 진행도를 표시한다.
        if game.config.limited_ammo:
            ammo = f"탄약 {player.ammo} / {player.max_ammo}"
            rect = pygame.Rect(screen_width - 198, 14, 184, 60)
            self._panel(rect)
            color = (255, 130, 100) if player.ammo == 0 else COLORS["white"]
            self.screen.blit(
                self.font_small.render(ammo, True, color), (rect.x + 14, rect.y + 10)
            )
            reloading = game.combat.reload_frames_left > 0
            hint = (
                f"재장전 {game.combat.reload_frames_left / game.config.fps:.1f}초"
                if reloading
                else "R: 재장전"
            )
            self.screen.blit(
                self.font_small.render(hint, True, COLORS["text"]),
                (rect.x + 14, rect.y + 33),
            )
            if reloading:
                bar = pygame.Rect(rect.x + 14, rect.y + 54, rect.width - 28, 6)
                pygame.draw.rect(self.screen, COLORS["hp_bg"], bar, border_radius=3)
                bar.width = int(
                    bar.width
                    * (
                        1
                        - game.combat.reload_frames_left
                        / game.combat.reload_frames_total
                    )
                )
                if bar.width:
                    pygame.draw.rect(
                        self.screen, COLORS["player"], bar, border_radius=3
                    )
            if (
                player.ammo == 0
                and not game.game_over
                and not reloading
                and show_notice
            ):
                text = self.font_body.render(
                    "탄약 소진! [R] 재장전", True, (255, 165, 100)
                )
                self.screen.blit(text, text.get_rect(midtop=(screen_width / 2, 270)))

        # 좌상단: 점수/처치/시간
        items = [
            (
                self.font_label.render(label, True, COLORS["label"]),
                self.font_hud.render(value, True, COLORS["white"]),
            )
            for label, value in (
                ("SCORE", f"{game.progression.score:,}"),
                ("KILLS", str(game.progression.kills)),
                (
                    "TIME",
                    f"{int(elapsed_seconds) // 60}:{int(elapsed_seconds) % 60:02d}",
                ),
            )
        ]
        width = 10 + sum(
            label_surface.get_width() + value_surface.get_width() + 18
            for label_surface, value_surface in items
        )
        rect = pygame.Rect(14, 14, width, 40)
        self._panel(rect)
        x = rect.x + 14
        for label_surface, value_surface in items:
            self.screen.blit(label_surface, (x, rect.y + 13))
            self.screen.blit(
                value_surface, (x + label_surface.get_width() + 6, rect.y + 6)
            )
            x += label_surface.get_width() + value_surface.get_width() + 18

        if game.config.progression_enabled:
            self._draw_progression(game, show_notice, stat_panel_collapsed)

        # 하단 중앙: 선체 내구도
        bar_width, bar_height = 320, 18
        bar_x, bar_y = screen_width / 2 - bar_width / 2, screen_height - 42
        self._panel(
            pygame.Rect(bar_x - 6, bar_y - 6, bar_width + 12, bar_height + 12), 170, 15
        )
        ratio = player.hp / player.max_hp
        pygame.draw.rect(
            self.screen,
            COLORS["hp_bg"],
            (bar_x, bar_y, bar_width, bar_height),
            border_radius=bar_height // 2,
        )
        if ratio > 0:
            health_color = _hp_color(ratio)
            pygame.draw.rect(
                self.screen,
                health_color,
                (bar_x, bar_y, max(bar_height, bar_width * ratio), bar_height),
                border_radius=bar_height // 2,
            )
            pygame.draw.rect(
                self.screen,
                _mix(health_color, (255, 255, 255), 0.4),
                (bar_x + 6, bar_y + 3, max(0, bar_width * ratio - 12), 3),
                border_radius=2,
            )
        text = f"HULL  {math.ceil(player.hp)} / {player.max_hp:.0f}"
        health_text_rect = self.font_label.render(text, True, COLORS["white"]).get_rect(
            center=(screen_width / 2, bar_y + bar_height / 2)
        )
        self.screen.blit(
            self.font_label.render(text, True, (0, 0, 0)), health_text_rect.move(1, 1)
        )
        self.screen.blit(
            self.font_label.render(text, True, COLORS["white"]), health_text_rect
        )

        # 메뉴의 조작 안내 설정을 즉시 반영한다.
        if show_controls:
            first_line = "WASD 이동 · 마우스 조준 / 발사"
            if game.config.limited_ammo:
                first_line += " · R 재장전"
            second_line = "1–5 스탯 강화 · Tab 능력치 · ESC 메뉴"
            for hint_index, hint in enumerate((first_line, second_line)):
                surface = self.font_small.render(hint, True, COLORS["text"])
                self.screen.blit(
                    surface,
                    surface.get_rect(
                        midtop=(screen_width / 2 + 30, 10 + hint_index * 23)
                    ),
                )
        self._draw_minimap(game)

    def minimap_rect(self):
        """현재 창의 우하단에 표시할 전체 지도 영역."""

        # 창 크기와 월드 비율을 반영해 미니맵의 최대 표시 크기를 정한다.
        width, height = self.size
        max_width = max(176, min(224, round(width * 0.16)))
        max_height = max(112, min(196, round(height * 0.25)))
        scale = min(
            (max_width - 12) / self.config.world_width,
            (max_height - 12) / self.config.world_height,
        )

        # 종횡비를 유지한 지도 크기와 우하단 여백을 계산한다.
        map_width = max(1, round(self.config.world_width * scale))
        map_height = max(1, round(self.config.world_height * scale))
        return pygame.Rect(
            width - map_width - 26,
            height - map_height - 26,
            map_width + 12,
            map_height + 12,
        )

    def _ensure_minimap(self, terrain, size):
        # 맵 객체를 키에 보관해 새 판의 id 재사용도 이전 지도로 오인하지 않는다.
        key = (terrain, terrain.version, size)
        if self._minimap_key == key:
            return

        # 전체 월드의 바닥과 벽을 미니맵 크기로 축소해 캐시에 보관한다.
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
                pygame.draw.rect(
                    surface,
                    COLORS["minimap_wall"],
                    (left, top, right - left, bottom - top),
                )
        self._minimap_key, self._minimap_floor = key, surface

    def _minimap_marker(self, game, area):
        # 플레이어의 월드 위치를 미니맵 위치로 변환한다.
        terrain, player = game.terrain, game.player
        x = area.left + player.x / (terrain.cols * terrain.tile) * area.width
        y = area.top + player.y / (terrain.rows * terrain.tile) * area.height

        # 조준 방향에 맞춰 플레이어 표시 도형을 회전한다.
        cos_angle, sin_angle = math.cos(player.angle), math.sin(player.angle)
        # 화면도 아래쪽이 +Y이므로 월드 조준각을 그대로 쓴다.
        return [
            (
                x + cos_angle * local_x - sin_angle * local_y,
                y + sin_angle * local_x + cos_angle * local_y,
            )
            for local_x, local_y in ((6.0, 0.0), (-4.0, -3.5), (-2.0, 0.0), (-4.0, 3.5))
        ]

    def _draw_minimap(self, game):
        # 화면의 미니맵 영역을 구하고 정적 지형 이미지를 준비한다.
        rect = self.minimap_rect()
        area = rect.inflate(-12, -12)
        self._ensure_minimap(game.terrain, area.size)
        # 배경이 비치도록 별도의 알파 표면에 그린 다음 반투명하게 합성한다.
        layer = pygame.Surface(rect.size, pygame.SRCALPHA)
        local_area = pygame.Rect(
            area.left - rect.left, area.top - rect.top, area.width, area.height
        )
        pygame.draw.rect(
            layer, COLORS["minimap_border"], layer.get_rect(), border_radius=3
        )
        layer.blit(self._minimap_floor, local_area.topleft)
        layer.set_clip(local_area)
        marker = self._minimap_marker(game, local_area)
        pygame.draw.polygon(layer, COLORS["minimap_player"], marker)
        layer.set_clip(None)
        layer.set_alpha(MINIMAP_ALPHA)
        self.screen.blit(layer, rect.topleft)

    def _draw_progression(self, game, show_notice, stat_panel_collapsed=False):
        # 현재 레벨과 우주선 이름을 성장 패널에 배치한다.
        player = game.player
        screen_width, screen_height = self.size
        panel = pygame.Rect(screen_width // 2 - 166, screen_height - 100, 332, 84)
        self._panel(panel)
        title = f"Lv.{game.progression.level}  {JOB_NAMES[player.job]}"
        text = self.font_body.render(title, True, COLORS["white"])
        self.screen.blit(
            text, text.get_rect(midtop=(screen_width // 2, screen_height - 98))
        )

        # 다음 레벨에 필요한 경험치 대비 현재 경험치를 표시한다.
        bar = pygame.Rect(screen_width // 2 - 160, screen_height - 67, 320, 18)
        pygame.draw.rect(self.screen, COLORS["hp_bg"], bar, border_radius=9)
        fill = bar.copy()
        fill.width = int(
            bar.width * game.progression.xp / game.progression.xp_to_next_level
        )
        if fill.width:
            pygame.draw.rect(self.screen, COLORS["player"], fill, border_radius=9)
        flash = 1 - (game.frame - self._xp_flash_frame) / 15
        if 0 < flash <= 1:  # 점수를 얻으면 EXP 바가 잠깐 밝게 빛난다
            glow = pygame.Surface(bar.size, pygame.SRCALPHA)
            pygame.draw.rect(
                glow,
                (255, 240, 170, round(150 * flash)),
                glow.get_rect(),
                border_radius=9,
            )
            self.screen.blit(glow, bar.topleft)
            pygame.draw.rect(
                self.screen, (255, 230, 140), bar.inflate(4, 4), 2, border_radius=11
            )
        experience_ratio = self.font_label.render(
            f"EXP  {game.progression.xp} / {game.progression.xp_to_next_level}",
            True,
            COLORS["white"],
        )
        self.screen.blit(experience_ratio, experience_ratio.get_rect(center=bar.center))
        if can_show_stat_upgrades(game):
            if stat_panel_collapsed:
                self._draw_stat_collapsed(game)
            else:
                self._draw_stat_upgrades(game)
        self._draw_rewards(game)
        if game.frame < game.progression.reward_message_until and show_notice:
            text = self.font_small.render(
                f"{game.progression.last_reward} 적용 완료", True, (160, 240, 220)
            )
            self.screen.blit(
                text, text.get_rect(midtop=(screen_width / 2, screen_height - 126))
            )

    def _draw_stats_panel(self, game):
        # 화면 중앙에 능력치 패널과 현재 우주선·레벨을 표시한다.
        rect = pygame.Rect(self.size[0] // 2 - 230, self.size[1] // 2 - 220, 460, 440)
        self._panel(rect, 175, 16)
        title = self.font_card.render("나의 능력치", True, COLORS["white"])
        self.screen.blit(title, (rect.x + 24, rect.y + 18))
        ship = self.font_body.render(
            f"Lv.{game.progression.level} · {JOB_NAMES[game.player.job]}",
            True,
            COLORS["player"],
        )
        self.screen.blit(ship, (rect.x + 24, rect.y + 52))

        # 각 능력치의 이름과 현재 값을 행 단위로 표시한다.
        for row_index, (label, value) in enumerate(build_player_stat_summary(game)):
            y = rect.y + 92 + row_index * 31
            name = self.font_body.render(label, True, COLORS["text"])
            number = self.font_body.render(value, True, COLORS["white"])
            self.screen.blit(name, (rect.x + 24, y))
            self.screen.blit(number, number.get_rect(topright=(rect.right - 24, y)))
        hint = f"수리 대기 {game.config.regen_delay / game.config.fps:g}초 · 이동 속도는 일반 지형 기준"
        self.screen.blit(
            self.font_small.render(hint, True, COLORS["label"]),
            (rect.x + 24, rect.bottom - 55),
        )
        hint = self.font_small.render(
            "Tab을 놓으면 닫힘 · 전투는 계속됩니다", True, COLORS["player"]
        )
        self.screen.blit(hint, (rect.x + 24, rect.bottom - 31))

    def _draw_stat_upgrades(self, game):
        rows = build_stat_upgrade_rows(*self.size, game.progression.stat_choices)

        # 표시할 스탯 행이 있는지 확인하고 패널 영역을 정한다.
        if not rows:
            return
        top = rows[0][1][1] - 30
        bottom = rows[-1][1][1] + rows[-1][1][3] + 8
        self._panel(pygame.Rect(14, top, 272, bottom - top), 195, 10)
        title = self.font_small.render(
            f"남은 스탯 {game.progression.upgrade_points}P · 1–5 / 클릭",
            True,
            COLORS["player"],
        )
        self.screen.blit(title, (22, top + 7))

        # 스탯 단계와 강화 가능 여부에 맞춰 행을 표시한다.
        for row_index, (card, coords) in enumerate(rows):
            rect = pygame.Rect(coords)
            enabled = game.progression.can_upgrade_stat(card.key)
            pygame.draw.rect(
                self.screen,
                (25, 38, 59) if enabled else (20, 25, 38),
                rect,
                border_radius=8,
            )
            pygame.draw.rect(
                self.screen,
                (65, 110, 140) if enabled else (44, 53, 70),
                rect,
                1,
                border_radius=8,
            )
            text = self.font_small.render(
                f"{row_index + 1}  {card.title}",
                True,
                COLORS["white"] if enabled else COLORS["label"],
            )
            self.screen.blit(text, (rect.x + 5, rect.y + 2))
            level = game.progression.stat_levels[card.key]
            at_limit = level >= STAT_MAX_LEVEL or (
                card.key == "rapid" and game.player.fire_cooldown_max <= 4
            )
            rank = self.font_label.render(
                "MAX" if at_limit else f"{level}/{STAT_MAX_LEVEL}",
                True,
                COLORS["player"],
            )
            self.screen.blit(
                rank, rank.get_rect(topright=(rect.right - 30, rect.y + 3))
            )
            plus = pygame.Rect(rect.right - 24, rect.y + 1, 23, 20)
            pygame.draw.rect(
                self.screen,
                (80, 185, 215) if enabled else (45, 60, 77),
                plus,
                border_radius=7,
            )
            label = self.font_body.render(
                "+", True, (10, 25, 35) if enabled else (100, 115, 140)
            )
            self.screen.blit(label, label.get_rect(center=plus.center))
            if rect.collidepoint(pygame.mouse.get_pos()):
                self._tooltip(card.description, (14, top - 42), 300)

    def _draw_stat_collapsed(self, game):
        # 접힌 스탯 패널의 위치와 남은 강화 포인트 문구를 준비한다.
        rect = pygame.Rect(get_collapsed_stat_panel_rect(*self.size))
        hover = rect.collidepoint(pygame.mouse.get_pos())
        self._panel(rect, 215 if hover else 185, 10)
        badge = pygame.Rect(rect.x + 8, rect.y + 8, 22, 22)
        pygame.draw.rect(self.screen, (80, 185, 215), badge, border_radius=7)
        plus = self.font_body.render("+", True, (10, 25, 35))
        self.screen.blit(plus, plus.get_rect(center=badge.center))
        text = self.font_small.render(
            f"남은 스탯 {game.progression.upgrade_points}P · 펼치기",
            True,
            COLORS["white"],
        )
        self.screen.blit(text, text.get_rect(midleft=(badge.right + 9, rect.centery)))

    def _tooltip(self, lines, position, width):
        wrapped = [
            line for text in lines for line in self._wrapped_text(text, width - 20)
        ]
        rect = pygame.Rect(position, (width, 14 + len(wrapped) * 18))
        self._panel(rect, 240, 8)
        for line_index, line in enumerate(wrapped):
            self.screen.blit(
                self.font_small.render(line, True, COLORS["text"]),
                (rect.x + 10, rect.y + 7 + line_index * 18),
            )

    def _wrapped_text(self, text, width):
        lines, line = [], ""
        for char in text:
            if line and self.font_small.size(line + char)[0] > width:
                lines.append(line)
                line = ""
            line += char
        return lines + ([line] if line else [])

    def _draw_rewards(self, game):
        pending = game.progression.special_reward_levels
        level = pending[0] if pending else (game.progression.level // 10 + 1) * 10

        # 대기 중인 진화 보상의 단계와 선택지 개수를 확인한다.
        count = len(game.progression.reward_choices)
        stage = "최종 진화" if level == 30 else "전직" if level < 30 else "숙련"
        heading = (
            f"Lv.{level} {stage} · F2–F{count + 1} / 클릭"
            if count > 1
            else f"Lv.{level} {stage} · F2 / 클릭"
            if count
            else f"다음 성장 Lv.{level}"
        )
        self.screen.blit(
            self.font_small.render(heading, True, (225, 205, 145)), (16, 61)
        )
        cards = game.progression.reward_choices

        # 진화 카드의 이미지와 이름을 배치하고 가리킨 카드의 설명을 표시한다.
        for choice_index, card in enumerate(cards):
            rect = pygame.Rect(
                get_evolution_card_rects(*self.size, len(cards))[choice_index]
            )
            self._panel(rect, 205, 10)
            image = self.assets.image(SHIPS[card.key].asset, 62)
            self.screen.blit(image, image.get_rect(midtop=(rect.centerx, rect.y + 3)))
            name = self.font_small.render(card.title, True, COLORS["white"])
            if name.get_width() > rect.width - 8:
                width = rect.width - 8
                name = pygame.transform.smoothscale(
                    name,
                    (
                        width,
                        max(1, round(name.get_height() * width / name.get_width())),
                    ),
                )
            self.screen.blit(name, name.get_rect(midtop=(rect.centerx, rect.y + 67)))
            if count and rect.collidepoint(pygame.mouse.get_pos()):
                description = (
                    ("현재 우주선 피해 +20%",) if level >= 40 else card.description
                )
                self._tooltip(description, (14, rect.bottom + 8), 330)

    def _draw_debug(self, lines):
        # 디버그 문장 길이에 맞춰 패널 크기를 정한다.
        line_height = 16
        width = max(self.font_mono.size(line)[0] for line in lines) + 24
        rect = pygame.Rect(
            self.size[0] - width - 14, 14, width, 14 + line_height * len(lines)
        )
        self._panel(rect, 200)

        # 관측 요약과 세부 항목을 행 단위로 표시한다.
        for line_index, line in enumerate(lines):
            col = (140, 220, 255) if line_index == 0 else (215, 222, 240)
            self.screen.blit(
                self.font_mono.render(line, True, col),
                (rect.x + 12, rect.y + 8 + line_height * line_index),
            )

    def _draw_card(self, titles, subs, stats=None):
        # 화면 중앙의 안내 카드와 배경을 준비한다.
        screen_width, screen_height = self.size
        shade = pygame.Surface((screen_width, screen_height), pygame.SRCALPHA)
        shade.fill((0, 0, 10, 130))
        self.screen.blit(shade, (0, 0))
        card_height = 140 + (70 if stats else 0)
        card = pygame.Rect(0, 0, 420, card_height)
        card.center = (screen_width / 2, screen_height / 2)
        self._panel(card, 225, 18)
        y = card.y + 22

        # 카드 제목을 표시하고 통계 행의 시작 위치를 정한다.
        for title_or_subtitle in titles:
            text_surface = self.font_big.render(
                title_or_subtitle, True, COLORS["white"]
            )
            self.screen.blit(
                text_surface, text_surface.get_rect(midtop=(screen_width / 2, y))
            )
            y += text_surface.get_height() + 4

        # 점수·처치·시간 같은 통계를 열 단위로 배치한다.
        if stats:
            column_width = card.width / len(stats)
            for stat_index, (label, value) in enumerate(stats):
                center_x = card.x + column_width * (stat_index + 0.5)
                value_surface = self.font_hud.render(value, True, COLORS["white"])
                label_surface = self.font_label.render(label, True, COLORS["label"])
                self.screen.blit(
                    value_surface, value_surface.get_rect(midtop=(center_x, y + 4))
                )
                self.screen.blit(
                    label_surface, label_surface.get_rect(midtop=(center_x, y + 34))
                )
            y += 64

        # 카드 하단에 조작 안내 문구를 표시한다.
        for title_or_subtitle in subs:
            text_surface = self.font_small.render(
                title_or_subtitle, True, COLORS["text"]
            )
            self.screen.blit(
                text_surface, text_surface.get_rect(midtop=(screen_width / 2, y + 4))
            )
            y += 22

    def _draw_game_over(self, game):
        # 종료 시점의 점수·처치 수·경과 시간을 안내 카드에 표시한다.
        elapsed_seconds = game.frame / self.config.fps
        self._draw_card(
            ["GAME OVER"],
            ["Enter: 새 게임 · ESC: 메뉴"],
            stats=[
                ("SCORE", f"{game.progression.score:,}"),
                ("KILLS", str(game.progression.kills)),
                (
                    "TIME",
                    f"{int(elapsed_seconds) // 60}:{int(elapsed_seconds) % 60:02d}",
                ),
            ],
        )


class _ShapeSnap:
    """사라진 도형의 마지막 모습을 기억하기 위한 복사본."""

    __slots__ = ("kind", "x", "y", "radius", "angle")

    def __init__(self, shape):
        self.kind, self.x, self.y, self.radius, self.angle = (
            shape.kind,
            shape.x,
            shape.y,
            shape.radius,
            shape.angle,
        )
