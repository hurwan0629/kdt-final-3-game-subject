"""랜덤 에이전트로 env를 headless 실행해 안정성/속도/재현성을 확인한다.

    python scripts/random_agent_test.py              # 맵마다 기본 3000 step
    python scripts/random_agent_test.py --steps 20000

검사 항목
- 맵 파일 로드/검증, 랜덤 맵 연결성 (BFS)
- 맵별(전체 미로맵 4개, 2단계 기능, 랜덤 맵, 빈 경기장) 랜덤 행동 실행: 관찰/보상 유효성, 탱크·도형이 벽에 끼지 않는지
- 같은 seed + 같은 행동 → 같은 결과 (새 environment / 한 판 끝난 뒤 reset한 environment 모두)
"""

import argparse
import time

import numpy as np

from space_z.config import GameConfig, ObsConfig, TerrainConfig
from space_z.rl.environment import TankEnv
from space_z.game.terrain import (
    list_maps,
    load_map,
    parse_map,
    generate_random_map,
    expand_map,
    MapError,
)


def make_env(
    map_name="drift", stage2=False, random_map=False, terrain=True, obs_mode="flat"
):
    # 맵·지형·관측 방식에 맞춰 무제한 탄약의 학습 환경을 만든다.
    config = GameConfig(progression_enabled=False, limited_ammo=False)
    terrain_config = config.terrain
    terrain_config.enabled = terrain
    terrain_config.map_name = map_name
    terrain_config.random_map = random_map
    terrain_config.mud_enabled = terrain_config.breakable_enabled = stage2
    return TankEnv(game_config=config, obs_config=ObsConfig(obs_mode=obs_mode))


def check_not_stuck(game):
    """탱크와 경험치 천체의 전체 충돌 원이 벽/경계를 침범하지 않아야 한다."""
    terrain = game.terrain
    entities = (
        [game.player] + [enemy for enemy in game.enemies if enemy.alive] + game.shapes
    )
    for entity in entities:
        assert terrain.circle_fits(entity.x, entity.y, entity.radius), (
            f"벽에 낌: {type(entity).__name__} at ({entity.x:.1f}, {entity.y:.1f}) radius={entity.radius:.1f} map={terrain.name}"
        )


def run_random(environment, total_steps, seed):
    # 시드를 고정하고 관측 크기와 에피소드 집계 상태를 준비한다.
    random_generator = np.random.default_rng(seed)
    observation, info = environment.reset(seed=seed)
    observation_shape = environment.observation_space.shape
    assert observation.shape == observation_shape, observation.shape
    episodes = 0
    episode_return = 0.0
    episode_length = 0
    returns = []
    scores = []
    episode_lengths = []

    # 무작위 행동을 적용하면서 관측·보상·개체 위치가 유효한지 검사한다.
    start_time = time.perf_counter()
    for _ in range(total_steps):
        action = int(random_generator.integers(environment.action_space.n))
        observation, reward, terminated, truncated, info = environment.step(action)
        assert observation.shape == observation_shape and np.all(
            np.isfinite(observation)
        ), "bad obs"
        assert np.isfinite(reward), "bad reward"
        check_not_stuck(environment.game)
        episode_return += reward
        episode_length += 1

        # 끝난 에피소드의 점수·보상·길이를 기록하고 다음 판을 시작한다.
        if terminated or truncated:
            episodes += 1
            returns.append(episode_return)
            scores.append(info["score"])
            episode_lengths.append(episode_length)
            episode_return, episode_length = 0.0, 0
            observation, info = environment.reset(seed=seed + episodes)

    # 전체 실행 시간과 에피소드별 집계 결과를 반환한다.
    elapsed = time.perf_counter() - start_time
    return elapsed, episodes, returns, scores, episode_lengths


def rollout(environment, seed, actions):
    # 같은 시드와 행동을 비교할 관측·보상 기록을 준비한다.
    observation, _ = environment.reset(seed=seed)
    trace = [observation.copy()]
    rewards = []
    info = {"score": 0}

    # 정해진 행동 순서대로 게임을 진행하고 관측과 보상을 기록한다.
    for action in actions:
        observation, reward, terminated, truncated, info = environment.step(action)
        trace.append(observation.copy())
        rewards.append(reward)
        if terminated or truncated:
            break
    return np.stack(trace), np.array(rewards), info["score"]


def determinism_test(n_steps=1500):
    # 비교에 사용할 행동 순서를 고정한다.
    actions = np.random.default_rng(123).integers(0, 27, size=n_steps)
    all_passed = True
    for label, kwargs in [
        ("drift", {}),
        ("belt+2단계", dict(map_name="belt", stage2=True)),
        ("랜덤 맵", dict(random_map=True, stage2=True)),
    ]:
        # 새 환경과 재시작한 환경에서 같은 시드의 결과를 수집한다.
        environment = make_env(**kwargs)
        first_observations, first_rewards, first_score = rollout(
            make_env(**kwargs), 7, actions
        )
        rollout(environment, 99, actions[:300])  # 다른 판을 먼저 하고
        replayed_observations, replayed_rewards, replayed_score = rollout(
            environment, 7, actions
        )  # 같은 env에서 reset
        different_seed_observations, _, _ = rollout(make_env(**kwargs), 8, actions)

        # 같은 시드의 완전 일치와 다른 시드의 결과 차이를 확인한다.
        same = (
            first_observations.shape == replayed_observations.shape
            and np.array_equal(first_observations, replayed_observations)
            and np.array_equal(first_rewards, replayed_rewards)
            and first_score == replayed_score
        )
        different_seed_changes_result = not (
            first_observations.shape == different_seed_observations.shape
            and np.array_equal(first_observations, different_seed_observations)
        )
        print(
            f"[재현성] {label:10s} 같은 seed → 동일: {same}  다른 seed → 다름: {different_seed_changes_result}  (steps={len(first_rewards)})"
        )
        all_passed &= same and different_seed_changes_result
    return all_passed


def map_tests():
    # 내장 맵의 연결성과 큰 선체의 통행 가능 여부를 검사한다.
    terrain_config = TerrainConfig()
    for name in list_maps():
        terrain = load_map(name, terrain_config, 60, 45)
        assert terrain.is_connected() and terrain.is_connected(
            terrain_config.navigation_radius
        )
        assert terrain.validate_navigation(terrain_config.navigation_radius) is None
    print(f"[맵] 손맵 {len(list_maps())}개 로드/연결성 OK: {', '.join(list_maps())}")

    # 시작점이 없는 맵과 영역이 끊긴 맵이 거부되는지 확인한다.
    bad = "\n".join(["." * 20] * 15)  # P 없음
    try:
        parse_map(bad, "bad", terrain_config, 20, 15)
        raise AssertionError("P 없는 맵이 통과됨")
    except MapError:
        pass
    walled = ["." * 20 for _ in range(15)]
    walled[0] = "P" + "." * 19
    walled[7] = "#" * 20
    try:
        parse_map("\n".join(walled), "split", terrain_config, 20, 15)
        raise AssertionError("끊어진 맵이 통과됨")
    except MapError:
        pass
    print("[맵] 잘못된 맵(시작점 없음 / 끊어진 영역) 검출 OK")

    # 여러 시드의 랜덤 맵에서도 큰 선체가 이동할 수 있는지 검사한다.
    stage2_config = TerrainConfig(mud_enabled=True, breakable_enabled=True)
    for seed in range(100):
        terrain = generate_random_map(
            np.random.default_rng(seed), stage2_config, 20, 15
        )
        assert terrain.is_connected() and terrain.is_connected(
            stage2_config.navigation_radius
        ), f"랜덤 맵 seed {seed} 최대 선체로 연결 안 됨"
    print("[맵] 랜덤 맵 100개 생성, 모두 최대 선체 경로 연결 OK")


def main():
    # 실행 길이와 난수 시드를 명령줄에서 읽는다.
    parser = argparse.ArgumentParser()
    parser.add_argument("--steps", type=int, default=3000)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    map_tests()

    environment = make_env()
    print(
        f"obs size = {environment.observation_space.shape[0]} "
        f"(vector {environment.observation_config.vector_size} + grid {environment.observation_builder.grid_shape}), "
        f"actions = {environment.action_space.n}, frame_skip = {environment.environment_config.frame_skip}"
    )
    dict_observation = make_env(obs_mode="dict").reset(seed=0)[0]
    print(
        f"obs_mode='dict' → vector {dict_observation['vector'].shape}, grid {dict_observation['grid'].shape}"
    )

    # 내장 맵·추가 지형·빈 경기장을 순회하며 실행 성능을 집계한다.
    cases = [(f"map:{map_name}", dict(map_name=map_name)) for map_name in list_maps()]
    cases += [
        ("belt+2단계", dict(map_name="belt", stage2=True)),
        ("ring+2단계", dict(map_name="ring", stage2=True)),
        ("랜덤 맵", dict(random_map=True, stage2=True)),
        ("빈 경기장", dict(terrain=False)),
    ]
    total_steps, total_time = 0, 0.0
    for label, kwargs in cases:
        environment = make_env(**kwargs)
        elapsed, episodes, returns, scores, episode_lengths = run_random(
            environment, args.steps, args.seed
        )
        total_steps += args.steps
        total_time += elapsed
        episode_summary = (
            f"에피소드 {episodes}개, 평균 길이 {np.mean(episode_lengths):.0f} step, 평균 score {np.mean(scores):.1f}"
            if returns
            else "완료된 에피소드 없음"
        )
        print(
            f"[실행] {label:12s} {args.steps / elapsed:6,.0f} steps/s   {episode_summary}"
        )
    steps_per_second = total_steps / total_time
    print(
        f"[속도] 전체 평균 {steps_per_second:,.0f} steps/s ({steps_per_second * 4:,.0f} game frames/s)"
    )

    # 같은 입력의 재현성까지 확인한 뒤 종료 상태를 반환한다.
    all_passed = determinism_test()
    print("ALL OK" if all_passed else "FAILED")
    raise SystemExit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
