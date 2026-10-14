"""문서용 화면을 실제 Renderer로 재현한다. 게임 파일은 수정하지 않는다.

프로젝트 루트에서: python docs/dev/render_screens.py
레벨업, 숨기, 사망 등은 설명용 상태를 설정해 촬영한다.
"""
import os
import sys
from pathlib import Path

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
from terrain import BUSH, list_maps


def main():
    output = ROOT / "docs" / "game" / "assets"
    output.mkdir(parents=True, exist_ok=True)
    pygame.init()
    cfg = GameConfig()
    game = GameCore(cfg, seed=42)
    renderer = Renderer(cfg)
    app = GameApplication(game, renderer, seed=42)

    def capture(name):
        app.draw(ObsConfig())
        assert renderer.screen.get_size() == (cfg.width, cfg.height)
        pygame.image.save(renderer.screen, str(output / name))

    capture("01-main-menu.png")
    app.activate("start")
    renderer.draw(game)
    for _ in range(45):
        game.step(0, want_fire=False)
        game.pop_events()
    capture("02-playing.png")
    game.player.ammo = 15
    app.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_r))
    capture("03-reloading.png")
    game._add_score(190)
    app.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_l))
    capture("04-rewards.png")
    app.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE))
    capture("05-settings.png")
    app.activate("resume")
    app.rewards_open = False
    game._damage_tank(game.player, game.player.hp, by_player=False)
    game.step(0, want_fire=False)
    capture("06-game-over.png")

    # 같은 타일 크기에서 지형 기능을 켠 실제 화면.
    tc = cfg.terrain
    tc.map_name = "belt"
    tc.mud_enabled = tc.breakable_enabled = True
    game.reset(42)
    app.rewards_open = False
    renderer.draw(game)
    game.frame = 30
    capture("07-terrain-stage2.png")
    bush = next((c, r) for c, r in game.terrain.free_tiles
                if game.terrain.tiles[r][c] == BUSH and 20 <= c < 40 and 15 <= r < 30)
    game.player.x, game.player.y = game.terrain.center(*bush)
    capture("08-hidden-player.png")

    # 맵 비교는 동일 배율로 렌더링한 확장 월드 전체를 사용한다.
    overview_cfg = GameConfig(num_shapes=0, num_enemies=0, camera_zoom=1 / 3)
    overview_cfg.terrain.mud_enabled = overview_cfg.terrain.breakable_enabled = True
    overview_renderer = Renderer(overview_cfg)
    for name in list_maps():
        overview_cfg.terrain.map_name = name
        overview_game = GameCore(overview_cfg, seed=42)
        overview_renderer.draw(overview_game, show_controls=False)
        pygame.image.save(overview_renderer.screen, str(output / f"map-{name}.png"))
    pygame.quit()
    print(f"Saved {len(list(output.glob('*.png')))} documentation images to {output}")


if __name__ == "__main__":
    main()
