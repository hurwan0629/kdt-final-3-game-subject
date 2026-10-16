"""실제 Pygame 렌더러를 촬영하고 오프라인 디자인 검토용 assets/index.html을 만든다.

실행: python docs/dev/build_asset_gallery.py
게임 실행 경로나 원본 PNG를 변경하지 않는다. 미사용 원본은 trash/에 보존한다.
"""
import hashlib
import html
import inspect
import json
import os
import shutil
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import quote, unquote
from html.parser import HTMLParser

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import pygame
from config import GameConfig, ObsConfig, TerrainConfig
from game_core import GameCore, Beam, Explosion
from main import GameApplication, debug_lines
from menus import menu_buttons
from progression import SHIPS, STAT_MAX_LEVEL, STAT_UPGRADES, stat_panel_rect, stat_collapsed_rect
from renderer import Renderer, COLORS
from sprite_assets import SpriteAssets
from terrain import TileMap, WALL, BREAKABLE, MUD

ASSETS = ROOT / "assets"
OUTPUT = ASSETS / "made_by_code"
EXTRA_IMAGES = {
    "backgrounds/deep_space.png": ("우주 배경", "배경", Renderer._make_background),
    "backgrounds/nebula.png": ("성운 레이어", "배경", Renderer._make_background),
    "objects/star_fragment.png": ("별 조각", "천체", Renderer._make_shape_sprite),
    "objects/rock_planet.png": ("암석 행성", "천체", Renderer._make_shape_sprite),
    "objects/ring_planet.png": ("고리 행성", "천체", Renderer._make_shape_sprite),
    "objects/gravity_field.png": ("중력장", "지형", Renderer._ensure_terrain),
    "projectiles/player_plasma.png": ("플레이어 플라즈마", "탄환", Renderer._draw_bullet),
    "projectiles/enemy_plasma.png": ("적 플라즈마", "탄환", Renderer._draw_bullet),
    "projectiles/cannon_shell.png": ("저격탄 · 포탄", "탄환", Renderer._draw_bullet),
}
ACTIVE = {spec.asset + ".png" for spec in SHIPS.values()} | EXTRA_IMAGES.keys()
ARCHIVED = ({"enemies/" + name + ".png" for name in ("fighter", "heavy", "scout")}
            | {"objects/" + name + ".png" for name in ("asteroid_wall", "breakable_asteroid", "gas_cloud")}
            | {"projectiles/homing_missile.png", "projectiles/mine.png", "references/우주선_진화트리.png"}
            | {"ships/" + name + ".png" for name in
               ("booster", "cross", "gatling", "guardian", "homing", "minelayer", "railgun", "ram",
                "rookie", "shotgun", "sniper", "triple", "twin")})
KIND_NAMES = {"image": "이미지 기반", "code": "코드 기반", "mixed": "이미지 + 코드",
              "screen": "전체 화면", "unused": "미사용 · 보관"}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def archive_unused():
    """승인된 22개만 이동. 재실행할 때 중복 이동하거나 파일을 덮어쓰지 않는다."""
    originals = {p.relative_to(ASSETS).as_posix() for p in ASSETS.rglob("*.png")
                 if p.relative_to(ASSETS).parts[0] not in ("trash", "made_by_code")}
    assert originals - ACTIVE <= ARCHIVED, f"미분류 이미지: {originals - ACTIVE - ARCHIVED}"
    assert len(ACTIVE) == 30 and len(ARCHIVED) == 22
    hashes = {}
    for relative in sorted(ACTIVE | ARCHIVED):
        source = ASSETS / relative
        target = ASSETS / "trash" / relative if relative in ARCHIVED else source
        assert source.resolve().is_relative_to(ASSETS.resolve())
        if relative in ARCHIVED:
            assert target.resolve().is_relative_to((ASSETS / "trash").resolve())
        if relative in ARCHIVED and source.exists():
            assert not target.exists(), f"이동 대상 충돌: {target}"
            before = digest(source)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(target))
            assert digest(target) == before
        assert target.is_file(), f"이미지 없음: {target}"
        hashes[target.relative_to(ASSETS).as_posix()] = digest(target)
    return hashes


def code_reference(function):
    path = Path(inspect.getsourcefile(function)).relative_to(ROOT).as_posix()
    lines, line = inspect.getsourcelines(function)
    return {"path": path, "line": line, "function": function.__qualname__,
            "excerpt": "".join(lines[:12]).rstrip()}


def gain_level(game, target):
    while game.level < target:
        game._add_score(game.xp_to_next_level - game.xp)


def capture_components():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    cfg = GameConfig(num_enemies=2, num_shapes=3)
    cfg.terrain.random_map = False
    game = GameCore(cfg, seed=42)
    renderer = Renderer(cfg)
    app = GameApplication(game, renderer, seed=42)
    display = renderer.screen
    entries = []

    def add(slug, title, kind, group, description, functions, design, draw, rect=None,
            state="실제 렌더러 · 시연용 상태", extra=None):
        renderer.screen = display
        display.fill((10, 15, 27))
        draw()
        area = pygame.Rect(rect) if rect is not None else display.get_rect()
        assert display.get_rect().contains(area), (slug, area)
        image = display.subsurface(area).copy()
        rgb = pygame.surfarray.array3d(image)
        assert int(rgb.max()) - int(rgb.min()) > 15, f"빈 캡처: {slug}"
        path = OUTPUT / (slug + ".png")
        pygame.image.save(image, str(path))
        entries.append(dict(id=slug, title=title, kind=kind, group=group, description=description,
                            design=design, state=state, path=path.relative_to(ASSETS).as_posix(),
                            width=image.get_width(), height=image.get_height(),
                            refs=[code_reference(f) for f in functions], extra=extra or ""))

    def hud():
        renderer._draw_hud(game, False)

    def hp_hud():
        cfg.progression_enabled = False
        try:
            hud()
        finally:
            cfg.progression_enabled = True

    def world(draw):
        renderer.camera_x = renderer.camera_y = 0
        renderer._flash_on = False
        draw()

    # 완성 화면은 실제 GameApplication.draw 경로로 촬영한다.
    add("screen-main", "메인 화면 전체", "screen", "화면 맥락", "우주 배경 PNG 위에 제목과 버튼을 코드로 합성합니다.",
        [Renderer.draw_main_menu], "배경·제목·버튼의 전체 톤과 대비를 함께 검토하세요.", lambda: app.draw(ObsConfig()))
    add("main-menu", "메인 메뉴 · 버튼", "code", "메뉴", "제목, 부제, 활성·비활성 버튼, 조작 힌트.",
        [Renderer._draw_menu, menu_buttons], "버튼 표면은 이미지화할 수 있습니다. 문구·포커스·비활성 상태는 별도로 필요합니다.",
        lambda: renderer._draw_menu(app.buttons(), "SPACE SKIRMISH", 0, main=True), (370, 166, 540, 480))
    app.activate("start")
    renderer.draw(game)
    for _ in range(24):
        game.step(0, want_fire=False)
        game.pop_events()
    add("screen-playing", "플레이 화면 전체", "screen", "화면 맥락", "기본 HUD·지형·기체의 상대 크기와 배치를 확인하는 화면.",
        [Renderer.draw], "전체 배치 참고용입니다. 개별 UI는 아래 분리 캡처를 사용하세요.", lambda: app.draw(ObsConfig()))
    add("pause-menu", "ESC 일시정지 · 설정", "code", "메뉴", "설정 5개와 계속·새 게임·메인·종료 버튼.",
        [Renderer._draw_menu, menu_buttons], "설정값과 버튼 문구는 동적 텍스트입니다. 선택·비활성 상태를 함께 디자인하세요.",
        lambda: renderer._draw_menu(menu_buttons("pause", cfg, size=renderer.size), "일시정지 · 설정", 0),
        (398, 112, 484, 588))
    add("hud-score", "점수 · 처치 · 시간", "code", "HUD", "좌상단 반투명 패널과 수치.", [Renderer._draw_hud],
        "패널 배경과 숫자를 분리하세요. 자릿수 증가에 따라 패널 폭이 변합니다.", hud, (8, 8, 430, 54))
    add("hud-ammo", "탄약 · 기본 상태", "code", "HUD", "잔탄과 탄창 크기, 재장전 안내.", [Renderer._draw_hud],
        "잔탄 수와 무제한 모드는 텍스트로 유지할 수 있어야 합니다.", hud, (1074, 8, 200, 76))
    game.player.ammo = 15
    assert game.request_reload()
    game.reload_frames_left = max(1, game.reload_frames_total // 2)
    add("hud-reload", "탄약 · 재장전 중", "code", "HUD", "남은 재장전 시간과 진행 게이지.", [Renderer._draw_hud],
        "게이지의 채움 폭과 남은 시간은 실시간으로 변합니다. 빈 바·채움·텍스트를 분리하세요.", hud, (1074, 8, 200, 76))
    game.reload_frames_left = 0
    game.player.ammo = 0
    add("ammo-empty", "탄약 소진 알림", "code", "알림", "화면 중앙 상단의 재장전 경고.", [Renderer._draw_hud],
        "경고색과 가독성을 검토하세요. 탄약 소진 시에만 표시됩니다.", hud, (380, 250, 520, 64))
    game.player.ammo = game.player.max_ammo
    add("hp-bar", "선체 HP · 정상", "code", "HUD", "하단 HP 패널과 현재·최대 체력.", [Renderer._draw_hud],
        "수치와 채움 길이는 동적입니다. 체력 비율에 따라 색상도 변합니다.", hp_hud, (464, 750, 352, 44))
    game.player.hp = game.player.max_hp * 0.22
    add("hp-low", "선체 HP · 위험", "code", "HUD", "낮은 체력일 때 붉게 변하는 체력바.", [Renderer._draw_hud],
        "정상·주의·위험 색상과 텍스트 대비를 함께 설계하세요.", hp_hud, (464, 750, 352, 44))
    game.player.hp = game.player.max_hp
    gain_level(game, 8)
    game.upgrade_stat("damage")
    game._add_score(max(1, game.xp_to_next_level // 3))
    add("exp-bar", "레벨 · EXP", "code", "HUD", "기체명, 레벨, 경험치 수치와 채움 바.", [Renderer._draw_progression],
        "기체명·레벨·경험치는 동적입니다. 바의 테두리와 채움은 분리해주세요.",
        lambda: renderer._draw_progression(game, False), (464, 694, 352, 96))
    renderer._xp_flash_frame = game.frame - 4
    add("exp-flash", "EXP 획득 · 발광", "code", "효과", "점수를 얻으면 EXP 바에 짧은 발광 테두리가 나타납니다.",
        [Renderer._draw_progression], "기본 바와 발광 오버레이를 따로 전달할 수 있습니다.",
        lambda: renderer._draw_progression(game, False), (464, 694, 352, 96))
    renderer._xp_flash_frame = -999
    add("stat-upgrades", "스탯 강화 · 사용 가능", "code", "성장", "5개 강화 행, 순위와 + 버튼.", [Renderer._draw_stat_upgrades],
        "행 배경은 이미지화 가능. 스탯명·포인트·랭크·활성 상태는 코드에서 갱신됩니다.",
        lambda: renderer._draw_stat_upgrades(game), pygame.Rect(stat_panel_rect(*renderer.size)).inflate(12, 12))
    saved_points = game.upgrade_points
    game.upgrade_points = 0
    add("stat-disabled", "스탯 강화 · 포인트 없음", "code", "성장", "사용 불가능한 강화 버튼의 어두운 색상.",
        [Renderer._draw_stat_upgrades], "클릭 가능한 상태와 불가능한 상태를 구별해주세요.",
        lambda: renderer._draw_stat_upgrades(game), pygame.Rect(stat_panel_rect(*renderer.size)).inflate(12, 12))
    game.upgrade_points = saved_points
    saved_levels = game.stat_levels.copy()
    game.stat_levels = {key: STAT_MAX_LEVEL for key in game.stat_levels}
    add("stat-max", "스탯 강화 · MAX", "code", "성장", "최대 강화 상태의 MAX 표시와 비활성 버튼.",
        [Renderer._draw_stat_upgrades], "최대 강화 상태는 포인트 부족 상태와 문구가 다릅니다.",
        lambda: renderer._draw_stat_upgrades(game), pygame.Rect(stat_panel_rect(*renderer.size)).inflate(12, 12))
    game.stat_levels = saved_levels
    add("stat-collapsed", "접힌 스탯 강화", "code", "성장", "4초 동안 조작하지 않으면 접히는 포인트 배지.",
        [Renderer._draw_stat_collapsed], "확장 패널과 동일한 디자인 언어로, 남은 포인트 수를 표시합니다.",
        lambda: renderer._draw_stat_collapsed(game), pygame.Rect(stat_collapsed_rect(*renderer.size)).inflate(12, 12))
    add("stats-panel", "Tab 상세 능력치", "code", "성장", "기체·체력·공격·사거리·발사속도·이동속도 등의 상세 수치.",
        [Renderer._draw_stats_panel], "패널 크기와 행 간격을 유지하고 긴 값과 단위를 고려해주세요.",
        lambda: renderer._draw_stats_panel(game), (398, 172, 484, 456))
    add("tooltip", "툴팁 · 자동 줄바꿈", "code", "알림", "스탯 강화 설명을 지정 너비로 줄바꿈합니다.",
        [Renderer._tooltip, Renderer._wrapped_text], "내용에 따라 높이가 달라집니다. 고정된 한 장의 텍스트 이미지로 만들기 어렵습니다.",
        lambda: renderer._tooltip(STAT_UPGRADES[1].description, (24, 30), 330), (16, 22, 346, 108))
    add("controls", "조작 안내", "code", "HUD", "상단 두 줄의 키·마우스 안내. 설정에서 끌 수 있습니다.",
        [Renderer._draw_hud], "키 표시와 글자 대비를 검토하세요. 안내 텍스트는 별도 레이어가 적합합니다.", hud, (418, 4, 540, 60))
    add("minimap", "미니맵", "code", "HUD", "실제 타일맵과 플레이어 위치·방향을 축소하여 표시.",
        [Renderer._draw_minimap, Renderer._ensure_minimap], "외곽 프레임은 이미지화 가능. 지도 내용과 방향 마커는 계속 갱신됩니다.",
        lambda: renderer._draw_minimap(game), renderer.minimap_rect().inflate(12, 12))
    for level in (10, 20, 30):
        gain_level(game, level)
        assert game.reward_choices
        add(f"evolution-{level}", f"Lv.{level} 전직 카드", "mixed", "성장", "우주선 PNG + 코드 패널·기체명·전직 안내.",
            [Renderer._draw_rewards], "이미지: 카드 속 기체. 코드: 프레임·이름·안내·툴팁. 카드별 선택 상태를 고려하세요.",
            lambda: renderer._draw_rewards(game), (8, 54, 414, 130))
        if level == 10:
            add("screen-rewards", "전직 화면 전체", "screen", "화면 맥락", "Lv.10 네 장의 전직 카드와 기존 HUD 배치.",
                [Renderer.draw, Renderer._draw_rewards], "전투 중 표시되는 카드와 주변 HUD의 관계를 확인하세요.", lambda: app.draw(ObsConfig()))
        assert game.choose_reward(0)
    add("reward-notice", "전직 적용 알림", "code", "알림", "전직 후 하단 중앙에 잠시 나타나는 적용 완료 메시지.",
        [Renderer._draw_progression], "기체명과 보상 문구가 변합니다. 배경 없이 표시되는 동적 텍스트입니다.",
        lambda: renderer._draw_progression(game, True), (380, 660, 520, 42))
    debug = debug_lines(game, ObsConfig(), 0)
    debug_width = max(renderer.font_mono.size(line)[0] for line in debug) + 24
    add("debug-panel", "디버그 수치 패널", "code", "디버그", "관찰 벡터·행동·위치·AI 상태. F1 또는 설정에서 표시.",
        [Renderer._draw_debug, debug_lines], "개발용 화면입니다. 글자 폭과 여러 줄의 가독성을 확인하세요.",
        lambda: renderer._draw_debug(debug), (1280 - debug_width - 20, 8, debug_width + 12, 26 + 16 * len(debug)))
    add("world-hp", "개체 체력바", "code", "월드 표시", "플레이어·적·천체 위의 작은 체력바. 피해를 입었을 때만 표시.",
        [Renderer._hp_bar], "세 가지 체력 비율을 나란히 촬영했습니다. 막대 폭은 개체 반경에 비례합니다.",
        lambda: world(lambda: [renderer._hp_bar(x, 130, 100, ratio) for x, ratio in ((100, .9), (250, .5), (400, .15))]),
        (32, 105, 438, 54))
    # 실제 기체 스프라이트와 코드 변형을 같은 배율로 비교한다.
    game.reset(42)
    p, e = game.player, game.enemies[0]
    p.x, p.y, p.angle = 140, 150, 0
    e.x, e.y, e.angle, e.job = 340, 150, 0, "rookie"
    renderer._first_seen.clear()
    def draw_teams():
        renderer._draw_ship(p, 100, True)
        e.elite = False
        renderer._draw_ship(e, 100)
        e.x, e.elite = 540, True
        renderer._draw_ship(e, 100)
        e.x, e.elite = 340, False
    add("ship-teams", "플레이어 · 적 · 엘리트", "mixed", "기체 변형", "같은 기체 PNG를 사용하고 적은 붉게, 엘리트는 금색으로 변환.",
        [Renderer._draw_ship, SpriteAssets._source], "이미지: 기체 원본. 코드: 색상 변환·YOU/ELITE 글자·엘리트 발광.",
        lambda: world(draw_teams), (40, 45, 610, 205))
    def draw_guardian():
        for x, image in ((140, pygame.image.load(str(ASSETS / "ships/Lv10_가디언.png")).convert_alpha()),
                         (420, renderer.assets._source("ships/Lv10_가디언"))):
            picture = pygame.transform.smoothscale(image, (240, 240))
            display.blit(picture, picture.get_rect(center=(x, 150)))
    add("guardian-barrel", "가디언 · 원본 / 런타임 포신", "mixed", "기체 변형", "왼쪽은 원본 PNG, 오른쪽은 코드로 대구경 포신을 다시 그린 결과.",
        [SpriteAssets._source, __import__("sprite_assets")._redraw_barrel],
        "이미지: 청록 선체. 코드: 기존 회색 포신 제거·대구경 포신 재작성. 새 이미지에 포신을 포함할지 결정하세요.",
        draw_guardian, (10, 25, 550, 250))
    renderer._flash_on = True
    p.last_hit_frame = 100
    add("ship-hit", "기체 피격 · 밝기 변화", "mixed", "기체 변형", "피격 시 원본 이미지에 밝은 색상을 가산하는 순간 상태.",
        [Renderer._draw_ship], "이미지: 기체. 코드: 짧은 피격 플래시. 기본 원본과 별도 피격 이미지를 제공해도 됩니다.",
        lambda: renderer._draw_ship(p, 100, True), (50, 45, 200, 210))
    renderer._flash_on = False
    renderer._first_seen[p.id] = 100
    add("ship-spawn", "기체 등장 · 확대 중", "mixed", "기체 변형", "등장 후 14프레임 동안 원본 이미지의 크기를 변화시킵니다.",
        [Renderer._draw_ship, Renderer._spawn_scale], "등장은 코드 확대 효과입니다. 이미지를 바꿔도 중심점과 여백을 일관되게 맞춰주세요.",
        lambda: renderer._draw_ship(p, 104, True), (50, 45, 200, 210))
    renderer._first_seen.clear()
    # 별·점수·파괴·AI 경로도 UI와 같은 갤러리에서 확인할 수 있다.
    renderer._twinkles = [(100 + i * 60, 120, i * .7, .04) for i in range(7)]
    add("twinkles", "배경 별 · 반짝임", "code", "효과", "배경 PNG 위에 작은 원을 그리고 밝기를 시간에 따라 바꿉니다.",
        [Renderer._draw_twinkles], "원본 배경 속 별과 코드로 추가되는 반짝임을 구분해주세요.",
        lambda: world(renderer._draw_twinkles), (60, 85, 450, 70))
    game.frame = 100
    game.score_popups = [(1, 95, 120, 140, 20, "square"), (2, 95, 340, 140, 200, "elite")]
    add("score-popup", "점수 획득 · 떠오르는 숫자", "code", "효과", "+점수 텍스트에 그림자·확대·상승·페이드가 적용됩니다.",
        [Renderer._draw_score_text], "내용이 변하는 숫자이므로 폰트·그림자·움직임을 구분해 설계하세요.",
        lambda: world(lambda: renderer._draw_score_text(game)), (30, 20, 450, 150))
    renderer._track(game)
    game.frame += 6
    renderer._track(game)
    add("score-sparks", "점수 획득 · 불꽃", "code", "효과", "점수 위치에서 바깥으로 퍼지는 작은 발광 입자.",
        [Renderer._draw_score_effects, Renderer._glow], "입자 색·크기·발광을 통일하세요. PNG 스프라이트로 대체할 수도 있습니다.",
        lambda: world(lambda: renderer._draw_score_effects(game)), (30, 50, 450, 150))
    add("ship-explosion", "우주선 파괴 · 원형 발광", "code", "효과", "커지는 원형 폭발과 발광으로 구성된 파괴 애니메이션.",
        [Renderer._draw_ghost, Renderer._glow], "22프레임 중간 상태입니다. 이미지화한다면 애니메이션 프레임이나 스프라이트 시트를 고려하세요.",
        lambda: world(lambda: renderer._draw_ghost(dict(kind="ship", x=180, y=150, r=44, color=COLORS["enemy"], age=10))),
        (20, 0, 320, 300))
    s = game.shapes[0]
    s.x, s.y = 150, 140
    add("object-fade", "천체 파괴 · 확대와 페이드", "mixed", "효과", "천체 PNG를 확대·회전·페이드하고 코드 발광을 더합니다.",
        [Renderer._draw_ghost, Renderer._make_shape_sprite], "이미지: 천체. 코드: 확대·투명도·발광. 실제 렌더러 중간 프레임입니다.",
        lambda: world(lambda: renderer._draw_ghost(dict(kind=s.kind, x=s.x, y=s.y, r=s.radius, angle=0, color=COLORS[s.kind], age=8))),
        (20, 10, 260, 260))
    renderer._first_seen[s.id] = game.frame - 25
    add("object-spawn", "천체 등장 · 페이드인", "mixed", "효과", "새 천체는 60프레임에 걸쳐 선명해집니다.",
        [Renderer._draw_shape], "원본 천체 PNG의 투명도와 크기를 코드에서 변화시킵니다.",
        lambda: world(lambda: renderer._draw_shape(s, game.frame)), (20, 10, 260, 260))
    e.x, e.y, p.x, p.y = 110, 140, 460, 140
    e.ai_path = [(3, 2), (5, 3), (7, 2)]
    e.ai_can_see, e.ai_goal = True, (360, 220)
    add("ai-path", "AI 경로 · 시야 · 목표점", "code", "디버그", "노란 경로와 목표점, 초록 시야선.",
        [Renderer._draw_ai_debug], "개발용 표시입니다. 게임 아트와 별도 우선순위로 검토할 수 있습니다.",
        lambda: world(lambda: renderer._draw_ai_debug(game)), (60, 65, 470, 195))
    # 지형은 검토용 소형 TileMap에 실제 _ensure_terrain을 호출한다.
    terrain_cfg = TerrainConfig(mud_enabled=True, breakable_enabled=True)
    tiles = [[0] * 12 for _ in range(7)]
    for row in (2, 3):
        for col in (2, 3, 4):
            tiles[row][col] = WALL
        for col in (7, 8, 9):
            tiles[row][col] = BREAKABLE
    tiles[5][3] = MUD
    tm = TileMap(tiles, 48, (1, 1), [], "design-preview", terrain_cfg)
    tm.hp[(8, 2)] *= .4
    def terrain():
        renderer._terrain_key = None
        renderer._ensure_terrain(tm)
        display.blit(renderer._floor, (0, 0))
    add("terrain-walls", "연결형 장벽", "code", "지형", "사각 타일을 연결하고 노출된 면에만 테두리를 그립니다.",
        [Renderer._ensure_terrain], "벽 본체·모서리·연결 면을 고려하세요. 배경은 PNG지만 이 장벽 자체는 코드입니다.",
        terrain, (64, 65, 210, 165))
    add("terrain-breakable", "파괴 가능한 장벽", "code", "지형", "갈색 벽, 노출 테두리와 피해량에 따른 균열선. --stage2 옵션.",
        [Renderer._ensure_terrain], "일반 벽과 구별하고 손상 상태도 디자인하세요. 배경을 제외한 장벽은 코드입니다.",
        terrain, (304, 65, 210, 165))
    add("terrain-gravity", "중력장 · 실제 배치", "mixed", "지형", "중력장 PNG를 타일 크기의 1.25배로 배치. --stage2 옵션.",
        [Renderer._ensure_terrain], "이미지: 중력장·배경. 코드: 타일별 크기와 위치 결정. 이 요소는 기본 플레이에서는 꺼져 있습니다.",
        terrain, (90, 185, 160, 150))
    game.beams = [Beam(70, 100, 460, 100)]
    game.explosions = []
    add("beam-dormant", "빔 · 렌더링 지원만 존재", "code", "효과", "현재 발사 로직에서는 생성하지 않는 빔을 시연 상태로 촬영.",
        [Renderer._draw_combat_effects], "현재 일반 플레이에서 보이지 않습니다. 활성 UI와 구별해 보관용으로 검토하세요.",
        lambda: world(lambda: renderer._draw_combat_effects(game)), (35, 60, 460, 80), state="현재 미생성 · 렌더러 시연")
    game.beams = []
    game.explosions = [Explosion(180, 150, 85, life=9)]
    add("blast-dormant", "범위 폭발 · 시연", "code", "효과", "폭발 반경이 있는 탄환용 효과. 현재 발사되는 탄환의 폭발 반경은 0.",
        [Renderer._draw_combat_effects], "현재 발사 로직의 일반 탄환에서는 나타나지 않습니다. 파괴 링 효과와 별개입니다.",
        lambda: world(lambda: renderer._draw_combat_effects(game)), (40, 10, 280, 280), state="현재 미생성 · 렌더러 시연")
    game.reset(42)
    app.mode = "playing"
    gain_level(game, 8)
    app.show_stats = True
    add("screen-stats", "능력치 화면 전체", "screen", "화면 맥락", "Tab 상세 패널과 다른 HUD의 관계.",
        [Renderer.draw, Renderer._draw_stats_panel], "개별 패널과 전체 화면을 함께 검토하세요.", lambda: app.draw(ObsConfig()))
    app.show_stats = False
    app.mode = "pause"
    add("screen-pause", "일시정지 화면 전체", "screen", "화면 맥락", "전투 화면 위에 어두운 오버레이와 설정 패널.",
        [Renderer.draw, Renderer._draw_menu], "뒤쪽 게임 화면과 오버레이의 명암을 확인하세요.", lambda: app.draw(ObsConfig()))
    app.mode = "playing"
    game._damage_tank(game.player, 100000, by_player=False)
    game.step(0, want_fire=False)
    assert game.game_over
    add("game-over", "게임 오버 카드", "code", "메뉴", "GAME OVER, 점수·처치·생존시간과 재시작 안내.",
        [Renderer._draw_game_over, Renderer._draw_card], "프레임은 이미지화 가능. 결과 수치와 텍스트는 분리하세요.",
        lambda: renderer._draw_game_over(game), (416, 281, 448, 240))
    add("pause-card", "일시정지 · 공통 카드", "code", "메뉴", "Renderer.draw(paused=True)에서 메뉴 없이 표시하는 간단 카드.",
        [Renderer._draw_card, Renderer.draw], "현재 앱의 ESC는 설정 메뉴를 사용합니다. 이 카드는 렌더러가 지원하는 별도 형태입니다.",
        lambda: renderer._draw_card(["일시정지"], ["P / ESC: 계속"]), (416, 320, 448, 160),
        state="렌더러 지원 · 앱 ESC는 설정 메뉴 사용")
    add("screen-game-over", "게임 오버 화면 전체", "screen", "화면 맥락", "정지된 전투 화면 위의 결과 카드.",
        [Renderer.draw, Renderer._draw_game_over], "어두운 오버레이와 결과 카드의 집중도를 검토하세요.", lambda: app.draw(ObsConfig()))
    pygame.quit()
    return entries


def image_entries():
    entries = []
    for spec in SHIPS.values():
        entries.append(dict(id="source-" + spec.key, title=f"Lv.{spec.level} {spec.title}", kind="image", group="기체 원본",
                            path=spec.asset + ".png", description="플레이어·적·전직 카드가 공유하는 투명 PNG. 정면은 오른쪽입니다.",
                            design="512×512 원본. 선체 중심과 반경에 맞춰 코드에서 크기·회전을 조절합니다. 적의 선체 색상은 코드로 변환합니다.",
                            state="사용 중 · 원본 PNG", refs=[code_reference(Renderer._draw_ship), code_reference(Renderer._draw_rewards)],
                            extra="가디언은 포신을 코드로 다시 그립니다. 혼합 항목의 원본/런타임 비교를 확인하세요." if spec.key == "guardian" else ""))
    for path, (title, group, function) in EXTRA_IMAGES.items():
        description = ("--stage2에서 켜지는 선택 지형 이미지." if "gravity" in path else
                       "두 배경을 합성한 뒤 어둡게 보정합니다. 성운은 투명도 35/255로 합성." if group == "배경" else
                       "원본의 투명 여백을 잘라내고 탄체 너비를 충돌 지름에 맞춰 그립니다." if group == "탄환" else
                       "경험치를 주는 천체. 회전·등장·피격 효과는 코드에서 적용합니다.")
        entries.append(dict(id="source-" + Path(path).stem, title=title, kind="image", group=group, path=path,
                            description=description, design="실제 사용 파일입니다. 투명도·방향·게임 속 표시 크기를 유지하며 재디자인할 수 있습니다.",
                            state="옵션 사용 · --stage2" if "gravity" in path else "사용 중 · 원본 PNG",
                            refs=[code_reference(function)], extra=""))
    for path in sorted(ARCHIVED):
        if path.startswith("enemies/"):
            reason = "예전 적 기체. 현재는 한글 우주선 PNG의 선체 색상을 변환하여 사용합니다."
        elif path.startswith("ships/"):
            reason = "예전 영문 파일명 기체. 현재는 한글 파일명 21종을 사용합니다."
        elif path.startswith("projectiles/"):
            reason = "렌더러 분기는 있지만 현재 발사 로직에서는 생성하지 않습니다. 기능 복원 시 원래 경로로 돌려놓아야 합니다."
        elif path.startswith("references/"):
            reason = "게임에서 로드하지 않는 진화 트리 참고 자료입니다. 삭제하지 않고 보관합니다."
        else:
            reason = "현재 장벽은 코드로 그리며 은신 구름 기능은 제거되었습니다."
        entries.append(dict(id="trash-" + Path(path).stem, title=Path(path).stem, kind="unused", group="미사용 원본",
                            path="trash/" + path, description=reason, design="현재 재디자인 대상에서 제외할 수 있는 보관 자료입니다.",
                            state="미사용 · 참고 자료" if path.startswith("references/") else "미사용 · 보관",
                            refs=[code_reference(Renderer._draw_bullet)] if path.startswith("projectiles/") else [],
                            extra="원래 경로: assets/" + path))
    return entries


def update_catalog(entries, original_hashes):
    path = ASSETS / "catalog.json"
    catalog = json.loads(path.read_text(encoding="utf-8"))
    old = {entry.get("original_path", entry["path"]): entry for entry in catalog["assets"]}
    records = []
    pygame.init()
    for entry in entries:
        relative = entry["path"]
        original = relative.removeprefix("trash/")
        record = old.get(original, {}).copy()
        image_path = ASSETS / relative
        image = pygame.image.load(str(image_path))
        record.update(id=record.get("id", entry["id"]), name=entry["title"], path=relative,
                      category=relative.split("/")[0], width=image.get_width(), height=image.get_height(),
                      bytes=image_path.stat().st_size, sha256=digest(image_path),
                      status="archived" if entry["kind"] == "unused" else "capture" if relative.startswith("made_by_code/") else "active",
                      rendering=entry["kind"], usage=entry["description"], rendering_code=entry["refs"])
        if relative.startswith("trash/"):
            record["original_path"] = original
        if record["status"] == "capture":
            record["capture_state"] = entry["state"]
            record["mode"] = "RGB"
            record["transparent_background"] = False
        records.append(record)
    pygame.quit()
    assert all(digest(ASSETS / p) == value for p, value in original_hashes.items()), "원본 이미지 변경 감지"
    catalog.update(updated="2026-10-16", gallery="index.html", square_images=False,
                   direction="Active ships face right; directional projectile source images face up.",
                   categories=dict(Counter(e["path"].split("/")[0] for e in entries if e["kind"] == "image")),
                   counts=dict(Counter(r["status"] for r in records)), assets=records,
                   capture_note="Actual Pygame Renderer, SDL dummy, 1280x800. Scripted demonstration states, not natural gameplay. Captures are documentation only.")
    path.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_html(entries):
    cards = []
    for entry in entries:
        escape = html.escape
        picture = quote(entry["path"])
        refs = "".join(f'<a href="../{quote(ref["path"])}#L{ref["line"]}">{escape(ref["path"])}:{ref["line"]} · {escape(ref["function"])}</a>'
                       for ref in entry["refs"])
        snippets = "\n\n".join(f'{ref["path"]}:{ref["line"]}\n{ref["excerpt"]}' for ref in entry["refs"])
        image = pygame.image.load(str(ASSETS / entry["path"]))
        size = f"{image.get_width()} × {image.get_height()}"
        search = " ".join(str(entry.get(key, "")) for key in ("title", "group", "path", "description", "state"))
        search += " " + " ".join(ref["function"] for ref in entry["refs"])
        cards.append(f'''<article class="asset-card" data-kind="{entry['kind']}" data-group="{escape(entry['group'], quote=True)}" data-search="{escape(search, quote=True)}" id="{entry['id']}">
          <a class="preview {'source' if entry['kind'] in ('image', 'unused') else ''}" href="{picture}" data-viewer aria-label="{escape(entry['title'], quote=True)} 확대">
            <img src="{picture}" alt="{escape(entry['title'], quote=True)}" loading="lazy" width="{image.get_width()}" height="{image.get_height()}"><span class="zoom">확대 ↗</span>
          </a>
          <div class="card-body"><div class="badges"><span class="badge {entry['kind']}">{KIND_NAMES[entry['kind']]}</span><span class="group-label">{escape(entry['group'])}</span></div>
          <h3>{escape(entry['title'])}</h3><p class="state">{escape(entry['state'])} · {size}</p>
          <p>{escape(entry['description'])}</p><p class="design"><b>디자인 참고</b> {escape(entry['design'])}</p>
          {'<p class="extra">' + escape(entry['extra']) + '</p>' if entry.get('extra') else ''}
          <a class="file-path" href="{picture}">{escape(entry['path'])}</a>
          <div class="code-links">{refs or '<span>현재 게임 렌더링 참조 없음</span>'}</div>
          {'<details><summary>렌더링 코드 미리보기</summary><pre><code>' + escape(snippets) + '</code></pre></details>' if snippets else ''}
          </div></article>''')
    template = (ROOT / "docs/dev/asset_gallery_template.html").read_text(encoding="utf-8")
    groups = sorted({entry["group"] for entry in entries})
    options = "".join(f'<option value="{html.escape(group, quote=True)}">{html.escape(group)}</option>' for group in groups)
    page = template.replace("<!-- CARDS -->", "\n".join(cards)).replace("<!-- GROUPS -->", options)
    page = page.replace("{{CAPTURE_COUNT}}", str(sum(e["path"].startswith("made_by_code/") for e in entries)))
    (ASSETS / "index.html").write_text(page, encoding="utf-8")


def validate_gallery(entries):
    class Links(HTMLParser):
        def handle_starttag(self, tag, attrs):
            for key, value in attrs:
                if key in ("src", "href") and value and not value.startswith(("#", "https:", "http:")):
                    path = (ASSETS / unquote(value.split("#")[0])).resolve()
                    assert path.is_relative_to(ROOT), value
                    assert path.is_file(), f"깨진 링크: {value}"
    Links().feed((ASSETS / "index.html").read_text(encoding="utf-8"))
    files = {p.relative_to(ASSETS).as_posix() for p in ASSETS.rglob("*.png")}
    assert {e["path"] for e in entries} == files, "갤러리에서 누락되거나 중복된 PNG"
    assert len(entries) == len({e["id"] for e in entries}), "중복 카드 ID"
    assert len(files & ACTIVE) == 30
    assert len(list((ASSETS / "trash").rglob("*.png"))) == 22
    catalog = json.loads((ASSETS / "catalog.json").read_text(encoding="utf-8"))
    assert {entry["path"] for entry in catalog["assets"]} == files
    print(f"Validated: 30 active PNGs, 22 archived PNGs, {len(entries) - 52} captures; all images, metadata and HTML links resolve.")


def main():
    original_hashes = archive_unused()
    pygame.init()
    captures = capture_components()
    entries = image_entries() + captures
    update_catalog(entries, original_hashes)
    build_html(entries)
    validate_gallery(entries)


if __name__ == "__main__":
    main()
