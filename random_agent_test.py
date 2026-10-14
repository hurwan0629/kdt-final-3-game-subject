"""랜덤 에이전트로 env를 headless 실행해 안정성/속도/재현성을 확인한다.

    python random_agent_test.py              # 맵마다 기본 3000 step
    python random_agent_test.py --steps 20000

검사 항목
- 맵 파일 로드/검증, 랜덤 맵 연결성 (BFS)
- 맵별(손맵 3개, 2단계 기능, 랜덤 맵, 빈 경기장) 랜덤 행동 실행: 관찰/보상 유효성, 탱크·도형이 벽에 끼지 않는지
- 같은 seed + 같은 행동 → 같은 결과 (새 env / 한 판 끝난 뒤 reset한 env 모두)
"""
import argparse
import time

import numpy as np

from config import GameConfig, ObsConfig, TerrainConfig
from env import TankEnv
from terrain import list_maps, load_map, parse_map, generate_random_map, MapError


def make_env(map_name="drift", stage2=False, random_map=False, terrain=True, obs_mode="flat"):
    cfg = GameConfig(progression_enabled=False)
    tc = cfg.terrain
    tc.enabled = terrain
    tc.map_name = map_name
    tc.random_map = random_map
    tc.mud_enabled = tc.breakable_enabled = stage2
    return TankEnv(game_config=cfg, obs_config=ObsConfig(obs_mode=obs_mode))


def check_not_stuck(game):
    """어떤 탱크/도형의 중심도 벽 타일 안에 있으면 안 된다."""
    tm = game.terrain
    objs = [game.player] + [e for e in game.enemies if e.alive] + game.shapes
    for o in objs:
        assert not tm.is_solid_at(o.x, o.y), f"벽에 낌: {type(o).__name__} at ({o.x:.1f}, {o.y:.1f}) map={tm.name}"


def run_random(env, total_steps, seed):
    rng = np.random.default_rng(seed)
    obs, info = env.reset(seed=seed)
    shape = env.observation_space.shape
    assert obs.shape == shape, obs.shape
    episodes, ep_return, returns, scores, ep_lens, ep_len = 0, 0.0, [], [], [], 0
    t0 = time.perf_counter()
    for _ in range(total_steps):
        action = int(rng.integers(env.action_space.n))
        obs, reward, terminated, truncated, info = env.step(action)
        assert obs.shape == shape and np.all(np.isfinite(obs)), "bad obs"
        assert np.isfinite(reward), "bad reward"
        check_not_stuck(env.game)
        ep_return += reward
        ep_len += 1
        if terminated or truncated:
            episodes += 1
            returns.append(ep_return)
            scores.append(info["score"])
            ep_lens.append(ep_len)
            ep_return, ep_len = 0.0, 0
            obs, info = env.reset(seed=seed + episodes)
    elapsed = time.perf_counter() - t0
    return elapsed, episodes, returns, scores, ep_lens


def rollout(env, seed, actions):
    obs, _ = env.reset(seed=seed)
    trace = [obs.copy()]
    rewards = []
    info = {"score": 0}
    for a in actions:
        obs, r, term, trunc, info = env.step(a)
        trace.append(obs.copy())
        rewards.append(r)
        if term or trunc:
            break
    return np.stack(trace), np.array(rewards), info["score"]


def determinism_test(n_steps=1500):
    actions = np.random.default_rng(123).integers(0, 27, size=n_steps)
    ok = True
    for label, kwargs in [("drift", {}), ("belt+2단계", dict(map_name="belt", stage2=True)),
                          ("랜덤 맵", dict(random_map=True, stage2=True))]:
        env = make_env(**kwargs)
        o1, r1, s1 = rollout(make_env(**kwargs), 7, actions)
        rollout(env, 99, actions[:300])        # 다른 판을 먼저 하고
        o2, r2, s2 = rollout(env, 7, actions)  # 같은 env에서 reset
        o3, _, _ = rollout(make_env(**kwargs), 8, actions)
        same = o1.shape == o2.shape and np.array_equal(o1, o2) and np.array_equal(r1, r2) and s1 == s2
        diff = not (o1.shape == o3.shape and np.array_equal(o1, o3))
        print(f"[재현성] {label:10s} 같은 seed → 동일: {same}  다른 seed → 다름: {diff}  (steps={len(r1)})")
        ok &= same and diff
    return ok


def map_tests():
    tc = TerrainConfig()
    for name in list_maps():
        tm = load_map(name, tc, 20, 15)
        assert tm.is_connected()
    print(f"[맵] 손맵 {len(list_maps())}개 로드/연결성 OK: {', '.join(list_maps())}")

    bad = "\n".join(["." * 20] * 15)  # P 없음
    try:
        parse_map(bad, "bad", tc, 20, 15)
        raise AssertionError("P 없는 맵이 통과됨")
    except MapError:
        pass
    walled = ["." * 20 for _ in range(15)]
    walled[0] = "P" + "." * 19
    walled[7] = "#" * 20
    try:
        parse_map("\n".join(walled), "split", tc, 20, 15)
        raise AssertionError("끊어진 맵이 통과됨")
    except MapError:
        pass
    print("[맵] 잘못된 맵(시작점 없음 / 끊어진 영역) 검출 OK")

    tc2 = TerrainConfig(mud_enabled=True, breakable_enabled=True)
    for s in range(100):
        tm = generate_random_map(np.random.default_rng(s), tc2, 20, 15)
        assert tm.is_connected(), f"랜덤 맵 seed {s} 연결 안 됨"
    print("[맵] 랜덤 맵 100개 생성, 모두 BFS 연결 OK")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--steps", type=int, default=3000)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    map_tests()

    env = make_env()
    print(f"obs size = {env.observation_space.shape[0]} "
          f"(vector {env.obs_cfg.vector_size} + grid {env.obs_builder.grid_shape}), "
          f"actions = {env.action_space.n}, frame_skip = {env.env_cfg.frame_skip}")
    d = make_env(obs_mode="dict").reset(seed=0)[0]
    print(f"obs_mode='dict' → vector {d['vector'].shape}, grid {d['grid'].shape}")

    cases = [(f"map:{m}", dict(map_name=m)) for m in list_maps()]
    cases += [("belt+2단계", dict(map_name="belt", stage2=True)),
              ("ring+2단계", dict(map_name="ring", stage2=True)),
              ("랜덤 맵", dict(random_map=True, stage2=True)),
              ("빈 경기장", dict(terrain=False))]
    total_steps, total_time = 0, 0.0
    for label, kwargs in cases:
        env = make_env(**kwargs)
        elapsed, episodes, returns, scores, lens = run_random(env, args.steps, args.seed)
        total_steps += args.steps
        total_time += elapsed
        ep = (f"에피소드 {episodes}개, 평균 길이 {np.mean(lens):.0f} step, 평균 score {np.mean(scores):.1f}"
              if returns else "완료된 에피소드 없음")
        print(f"[실행] {label:12s} {args.steps / elapsed:6,.0f} steps/s   {ep}")
    sps = total_steps / total_time
    print(f"[속도] 전체 평균 {sps:,.0f} steps/s ({sps * 4:,.0f} game frames/s)")

    ok = determinism_test()
    print("ALL OK" if ok else "FAILED")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
