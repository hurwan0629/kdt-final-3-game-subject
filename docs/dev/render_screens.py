"""실제 Renderer로 현재 게임/진화/맵 문서 화면을 생성한다."""
import os
import sys
from pathlib import Path
from collections import defaultdict
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import pygame
from config import GameConfig, ObsConfig
from game_core import GameCore
from main import GameApplication
from renderer import Renderer
from progression import SHIPS
from terrain import list_maps


def gain_level(game, target):
    while game.level < target:
        game._add_score(game.xp_to_next_level - game.xp)


def evolve(game, target):
    chain = []
    key = target
    while key != "rookie":
        chain.append(key)
        key = SHIPS[key].parent or "rookie"
    for key in reversed(chain):
        gain_level(game, SHIPS[key].level)
        game.choose_reward(next(i for i, c in enumerate(game.reward_choices) if c.key == key))


def main():
    output = ROOT / "docs/game/assets"
    output.mkdir(parents=True, exist_ok=True)
    pygame.init()
    cfg = GameConfig()
    game = GameCore(cfg, seed=42)
    renderer = Renderer(cfg)
    app = GameApplication(game, renderer, seed=42)
    def capture(name):
        app.draw(ObsConfig())
        pygame.image.save(renderer.screen, str(output / name))
    capture("01-main-menu.png")
    app.activate("start")
    renderer.draw(game)
    for _ in range(20):
        game.step(0, want_fire=False)
        game.pop_events()
    capture("02-playing.png")
    gain_level(game, 8)
    game.upgrade_stat("damage")
    game.upgrade_stat("speed")
    capture("09-stats.png")
    # 상태값은 GameApplication의 Tab 입력과 동일한 경로로 적용한다.
    keys = defaultdict(bool)
    keys[pygame.K_TAB] = True
    app.update(0, keys, (640, 400), (False, False, False))
    capture("13-stats-panel.png")
    keys[pygame.K_TAB] = False
    app.update(0, keys, (640, 400), (False, False, False))
    game.player.ammo = 15
    game.request_reload()
    capture("03-reloading.png")
    gain_level(game, 10)
    capture("04-rewards.png")
    app.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE))
    capture("05-settings.png")
    app.activate("resume")
    game._damage_tank(game.player, 100000, by_player=False)
    game.step(0, want_fire=False)
    capture("06-game-over.png")
    cfg.terrain.map_name = "belt"
    cfg.terrain.mud_enabled = cfg.terrain.breakable_enabled = True
    game.reset(42)
    capture("07-terrain-stage2.png")
    cfg.terrain.map_name = "drift"
    game.reset(42)
    evolve(game, "citadel")
    renderer.draw(game)
    game.frame = 30
    capture("08-wall-maze.png")
    cfg.terrain.enabled = False
    game.reset(42)
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
    game.choose_reward(0)
    gain_level(game, 30)
    capture("15-final-evolution.png")
    overview_cfg = GameConfig(num_shapes=0, num_enemies=0, camera_zoom=1/3,
                              window_width=960, window_height=720)
    overview_cfg.terrain.mud_enabled = overview_cfg.terrain.breakable_enabled = True
    overview_renderer = Renderer(overview_cfg)
    for name in list_maps():
        overview_cfg.terrain.map_name = name
        g = GameCore(overview_cfg, seed=42)
        overview_renderer.draw(g, show_controls=False)
        pygame.image.save(overview_renderer.screen, str(output / ("map-" + name + ".png")))
    pygame.quit()
    print("Saved current game documentation screenshots")


if __name__ == "__main__":
    main()
