"""실제 Renderer로 현재 게임/진화/맵 문서 화면을 생성한다."""

import os
from pathlib import Path
from collections import defaultdict

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
ROOT = Path(__file__).resolve().parents[1]
import pygame
from space_z.config import GameConfig, ObsConfig
from space_z.game.game_core import GameCore
from space_z.app import GameApplication
from space_z.rendering.renderer import Renderer
from space_z.config.progression_definitions import SHIPS
from space_z.game.terrain import list_maps


def gain_level(game, target):
    # 목표 레벨에 도달할 때까지 필요한 경험치를 지급한다.
    while game.progression.level < target:
        game.progression._add_score(
            game.progression.xp_to_next_level - game.progression.xp
        )


def evolve(game, target):
    # 목표 우주선까지 필요한 진화 경로를 거슬러 수집한다.
    chain = []
    key = target
    while key != "rookie":
        chain.append(key)
        key = SHIPS[key].parent or "rookie"

    # 초기 우주선부터 순서대로 레벨과 진화 보상을 적용한다.
    for key in reversed(chain):
        gain_level(game, SHIPS[key].level)
        game.progression.choose_reward(
            next(
                choice_index
                for choice_index, card in enumerate(game.progression.reward_choices)
                if card.key == key
            )
        )


def main():
    # 문서 화면의 저장 폴더와 게임·렌더러를 준비한다.
    output = ROOT / "docs/game/assets"
    output.mkdir(parents=True, exist_ok=True)
    pygame.init()
    config = GameConfig()
    game = GameCore(config, seed=42)
    renderer = Renderer(config)
    application = GameApplication(game, renderer, seed=42)

    def capture(name):
        application.draw(ObsConfig())
        pygame.image.save(renderer.screen, str(output / name))

    # 시작 메뉴와 기본 플레이 화면을 저장한다.
    capture("01-main-menu.png")
    application.activate_menu_action("start")
    renderer.draw(game)
    for _ in range(20):
        game.step(0, want_fire=False)
        game.pop_events()
    capture("02-playing.png")

    # 강화·능력치 패널과 재장전·진화 보상 화면을 저장한다.
    gain_level(game, 8)
    game.progression.upgrade_stat("damage")
    game.progression.upgrade_stat("speed")
    capture("09-stats.png")
    # 상태값은 GameApplication의 Tab 입력과 동일한 경로로 적용한다.
    keys = defaultdict(bool)
    keys[pygame.K_TAB] = True
    application.update(0, keys, (640, 400), (False, False, False))
    capture("13-stats-panel.png")
    keys[pygame.K_TAB] = False
    application.update(0, keys, (640, 400), (False, False, False))
    game.player.ammo = 15
    game.combat.request_reload()
    capture("03-reloading.png")
    gain_level(game, 10)
    capture("04-rewards.png")
    application.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE))
    capture("05-settings.png")
    application.activate_menu_action("resume")

    # 플레이어 사망과 추가 지형의 화면을 저장한다.
    game.combat._damage_tank(game.player, 100000, by_player=False)
    game.step(0, want_fire=False)
    capture("06-game-over.png")
    config.terrain.map_name = "belt"
    config.terrain.mud_enabled = config.terrain.breakable_enabled = True
    game.reset(42)
    capture("07-terrain-stage2.png")
    config.terrain.map_name = "drift"
    game.reset(42)
    evolve(game, "citadel")
    renderer.draw(game)
    game.frame = 30
    capture("08-wall-maze.png")
    config.terrain.enabled = False
    game.reset(42)

    # 우주선 진화 계열별 실제 발사 화면을 저장한다.
    evolve(game, "railgunner")
    game.player.angle = 0
    renderer.draw(game)
    for _ in range(8):
        game.step(0, want_fire=True)
    capture("10-sniper-line.png")
    game.reset(42)
    evolve(game, "penta_wing")
    game.player.angle = 0
    renderer.draw(game)
    for _ in range(7):
        game.step(0, want_fire=True)
    capture("11-fan-fire.png")
    game.reset(42)
    evolve(game, "predator")
    game.player.angle = 0
    renderer.draw(game)
    for _ in range(12):
        game.step(0, want_fire=True)
    capture("12-sniper.png")
    game.reset(42)
    evolve(game, "twin")
    gain_level(game, 20)
    capture("14-evolution.png")
    game.progression.choose_reward(0)
    gain_level(game, 30)
    capture("15-final-evolution.png")

    # 각 내장 맵을 한눈에 볼 수 있는 전체 지도 화면을 저장한다.
    overview_config = GameConfig(
        num_shapes=0,
        num_enemies=0,
        camera_zoom=1 / 3,
        window_width=960,
        window_height=720,
    )
    overview_config.terrain.mud_enabled = overview_config.terrain.breakable_enabled = (
        True
    )
    overview_renderer = Renderer(overview_config)
    for name in list_maps():
        overview_config.terrain.map_name = name
        overview_game = GameCore(overview_config, seed=42)
        overview_renderer.draw(overview_game, show_controls=False)
        pygame.image.save(
            overview_renderer.screen, str(output / ("map-" + name + ".png"))
        )
    pygame.quit()
    print("Saved current game documentation screenshots")


if __name__ == "__main__":
    main()
