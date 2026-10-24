"""Space Z 실행 인자·객체 생성과 메인 루프.

    python -m space_z
    python -m space_z --seed 42 --map belt
"""
import argparse
import sys

import pygame

from space_z.config import GameConfig, ObsConfig
from space_z.game.game_core import GameCore
from space_z.game.terrain import list_maps
from space_z.app import GameApplication


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--map", default=None, help=f"맵 이름 ({', '.join(list_maps())})")
    parser.add_argument("--random-map", action="store_true", help="랜덤 지형 (기본값)")
    parser.add_argument("--no-terrain", action="store_true", help="벽 없는 빈 경기장")
    parser.add_argument("--stage2", action="store_true", help="진흙/부서지는 벽 켜기")
    parser.add_argument("--limited-ammo", action="store_true", help="탄약 제한 켜기 (기본은 무제한)")
    args = parser.parse_args()

    pygame.init()

    # 게임 설정 가져오기
    game_config = GameConfig()

    # 맵 설정
    terrain_config = game_config.terrain
    terrain_config.enabled = not args.no_terrain
    terrain_config.random_map = args.random_map or not args.map   # --map을 주지 않으면 랜덤 지형
    terrain_config.mud_enabled = terrain_config.breakable_enabled = args.stage2
    
    if args.map:
        terrain_config.map_name = args.map

    # 강화학습 설정
    observation_config = ObsConfig()

    # 렌더링 객체
    from space_z.rendering.renderer import Renderer
    renderer = Renderer(game_config)

    # 인게임 코어
    game_core = GameCore(game_config, seed=args.seed)

    # 어플리케이션 객체 (게임 코어와 렌더링 객체 장착)
    application = GameApplication(game_core, renderer, args.seed)

    # 게임 루프
    while application.running:
        # 모든 이벤트 처리
        for ev in pygame.event.get():
            application.handle_event(ev)
            if not application.running:
                break
        if not application.running:
            break
        # 게임 어플리케이션 업데이트
        application.update(renderer.clock.tick(game_config.fps) / 1000.0, pygame.key.get_pressed(),
                   pygame.mouse.get_pos(), pygame.mouse.get_pressed())
        # 렌더링
        application.draw(observation_config)
        # 게임 화면 업데이트
        pygame.display.flip()
    pygame.quit()


if __name__ == "__main__":
    main()
    sys.exit(0)
