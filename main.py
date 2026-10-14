"""사람이 키보드로 플레이하는 진입점.

키 입력 → (이동, 회전) → 행동 번호 → GameCore.step(action)
게임은 1/60초 고정 간격으로 업데이트되고, 화면 그리기는 그와 별개로 돈다.

    python main.py                 # 랜덤 seed, 기본 맵
    python main.py --seed 42       # 고정 seed
    python main.py --map belt      # maps/belt.txt
    python main.py --random-map    # 랜덤 맵 생성
    python main.py --no-terrain    # 빈 경기장
    python main.py --stage2        # 진흙/부서지는 벽 켜기
"""
import argparse
import sys

import pygame

from config import GameConfig, ObsConfig
from env import build_vector
from game_core import GameCore, encode_action, move_from_vector
from terrain import list_maps

MAX_FRAMES_PER_TICK = 5  # 느린 PC에서 업데이트가 밀려 멈추는 것 방지


def read_action(keys) -> int:
    dx = (keys[pygame.K_d] - keys[pygame.K_a])
    dy = (keys[pygame.K_s] - keys[pygame.K_w])
    move = move_from_vector(dx, dy)
    left = keys[pygame.K_q] or keys[pygame.K_LEFT]
    right = keys[pygame.K_e] or keys[pygame.K_RIGHT]
    rot = 1 if left and not right else 2 if right and not left else 0
    return encode_action(move, rot)


def debug_lines(game, obs_cfg, action):
    obs = build_vector(game, obs_cfg)
    f = lambda v: f"{v:+.2f}"
    lines = [f"vector obs {obs.size} (+ terrain grid)   action {action}   frame {game.frame}",
             "self x,y " + f(obs[0]) + " " + f(obs[1]) + "  v " + f(obs[2]) + " " + f(obs[3]),
             "self hp " + f(obs[4]) + "  sin/cos " + f(obs[5]) + " " + f(obs[6]) + "  rl " + f(obs[7])
             + f"  bush {obs[8]:.0f}",
             f"map {game.terrain.name}   enemies seeing you: {sum(e.alive and e.ai_can_see for e in game.enemies)}"]
    i = obs_cfg.SELF_DIM
    for n in range(obs_cfg.n_enemies):
        e = obs[i:i + obs_cfg.ENEMY_DIM]
        lines.append(f"enemy{n} ex{e[0]:.0f} d({f(e[1])},{f(e[2])}) hp{e[5]:.2f}")
        i += obs_cfg.ENEMY_DIM
    for n in range(min(3, obs_cfg.n_shapes)):
        s = obs[i:i + obs_cfg.SHAPE_DIM]
        lines.append(f"shape{n} ex{s[0]:.0f} d({f(s[1])},{f(s[2])}) hp{s[3]:.2f} sc{s[4]:.2f}")
        i += obs_cfg.SHAPE_DIM
    i = obs_cfg.vector_size - obs_cfg.n_rays - obs_cfg.n_bullets * obs_cfg.BULLET_DIM
    nb = int(sum(obs[i + k * obs_cfg.BULLET_DIM] for k in range(obs_cfg.n_bullets)))
    lines.append(f"enemy bullets in obs: {nb}/{obs_cfg.n_bullets}")
    lines.append("(lines: green = enemy sees you, yellow = A* path)")
    return lines


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--map", default=None, help=f"맵 이름 ({', '.join(list_maps())})")
    parser.add_argument("--random-map", action="store_true", help="랜덤 맵 생성")
    parser.add_argument("--no-terrain", action="store_true", help="벽 없는 빈 경기장")
    parser.add_argument("--stage2", action="store_true", help="진흙/부서지는 벽 켜기")
    args = parser.parse_args()

    pygame.init()
    cfg = GameConfig()
    tc = cfg.terrain
    tc.enabled = not args.no_terrain
    tc.random_map = args.random_map
    tc.mud_enabled = tc.breakable_enabled = args.stage2
    if args.map:
        tc.map_name = args.map
    # N 키로 순환할 맵 목록: 손으로 만든 맵들 + 랜덤 + 빈 경기장
    map_cycle = [("map", m) for m in list_maps()] + [("random", None), ("empty", None)]
    obs_cfg = ObsConfig()
    from renderer import Renderer
    renderer = Renderer(cfg)
    game = GameCore(cfg, seed=args.seed)

    dt = 1.0 / cfg.fps
    acc = 0.0
    show_debug = False
    paused = False
    rewards_open = False
    action = 0

    while True:
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                pygame.quit()
                return
            if ev.type == pygame.KEYDOWN:
                if ev.key == pygame.K_ESCAPE:
                    if rewards_open:
                        rewards_open = False
                        acc = 0.0
                        continue
                    pygame.quit()
                    return
                if ev.key == pygame.K_l:
                    rewards_open = not rewards_open and bool(game.open_rewards())
                    acc = 0.0
                    continue
                if rewards_open:
                    choice_keys = (pygame.K_1, pygame.K_2, pygame.K_3)
                    if ev.key in choice_keys and game.choose_reward(choice_keys.index(ev.key)):
                        rewards_open = False
                        acc = 0.0
                    continue
                if ev.key == pygame.K_r:
                    game.reset(args.seed)
                    paused = False
                    rewards_open = False
                    acc = 0.0
                elif ev.key == pygame.K_F1:
                    show_debug = not show_debug
                elif ev.key == pygame.K_p:
                    paused = not paused
                elif ev.key == pygame.K_n:
                    cur = ("empty", None) if not tc.enabled else ("random", None) if tc.random_map \
                        else ("map", tc.map_name)
                    kind, name = map_cycle[(map_cycle.index(cur) + 1) % len(map_cycle)] \
                        if cur in map_cycle else map_cycle[0]
                    tc.enabled = kind != "empty"
                    tc.random_map = kind == "random"
                    if name:
                        tc.map_name = name
                    game.reset(args.seed)
                    paused = False
                    rewards_open = False
                    acc = 0.0

        acc += renderer.clock.tick(cfg.fps) / 1000.0
        acc = min(acc, dt * MAX_FRAMES_PER_TICK)
        action = read_action(pygame.key.get_pressed())
        while acc >= dt:
            if not paused and not rewards_open:
                game.step(action)
                game.pop_events()  # 사람 플레이에서는 이벤트를 쓰지 않음
            acc -= dt

        lines = debug_lines(game, obs_cfg, action) if show_debug else None
        renderer.draw(game, lines, paused, show_ai=show_debug, rewards_open=rewards_open)
        pygame.display.flip()


if __name__ == "__main__":
    main()
    sys.exit(0)
