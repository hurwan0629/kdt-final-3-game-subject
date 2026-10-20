"""강화학습 환경 (Gymnasium 스타일).

    env = TankEnv()
    obs, info = env.reset(seed=0)
    obs, reward, terminated, truncated, info = env.step(action)   # action: 0..26

gymnasium이 설치되어 있으면 gymnasium.Env를 상속하고 observation_space/action_space를
gymnasium.spaces로 제공한다. 없으면 같은 인터페이스의 최소 대체 클래스를 쓴다.
"""
import math

import numpy as np

from space_z.config import GameConfig, ObsConfig, RewardConfig, EnvConfig, MAX_SHAPE_SCORE, MAX_SHAPE_RADIUS
from space_z.game.game_core import GameCore, N_ACTIONS, empty_events
from space_z.game.terrain import grid_channels, WALL, MUD, BREAKABLE

try:
    import gymnasium as gym
    from gymnasium import spaces
    _BaseEnv = gym.Env
except ImportError:  # gymnasium 없이도 동작
    gym = None
    spaces = None
    _BaseEnv = object


class _Discrete:
    def __init__(self, n):
        self.n = n

    def sample(self, rng=None):
        rng = rng or np.random.default_rng()
        return int(rng.integers(self.n))


class _Box:
    def __init__(self, low, high, shape, dtype):
        self.low, self.high, self.shape, self.dtype = low, high, shape, dtype


# --------------------------------------------------------------------------
# 관찰
# --------------------------------------------------------------------------
def build_vector(game: GameCore, oc: ObsConfig) -> np.ndarray:
    """지형 격자를 제외한 벡터 관찰 (내 탱크, 적, 도형, 적 탄환, 레이)."""
    c = game.cfg
    W, H = float(c.world_width), float(c.world_height)
    vmax = c.max_speed
    bspd = c.bullet_speed
    p = game.player
    obs = np.zeros(oc.vector_size, dtype=np.float32)

    # 내 탱크 (8): 은신 지형/관찰 항목은 사용하지 않는다.
    obs[0:8] = (
        p.x / W, p.y / H, p.vx / vmax, p.vy / vmax, p.hp / p.max_hp,
        math.sin(p.angle), math.cos(p.angle),
        1.0 - p.cooldown / p.fire_cooldown_max,
    )
    i = oc.SELF_DIM

    def nearest(objs, k):
        return sorted(objs, key=lambda o: (o.x - p.x) ** 2 + (o.y - p.y) ** 2)[:k]

    # 적 탱크 N × 8
    for e in nearest([e for e in game.enemies if e.alive], oc.n_enemies):
        obs[i:i + 8] = (1.0, (e.x - p.x) / W, (e.y - p.y) / H, e.vx / vmax, e.vy / vmax,
                        e.hp / e.max_hp, math.sin(e.angle), math.cos(e.angle))
        i += oc.ENEMY_DIM
    i = oc.SELF_DIM + oc.n_enemies * oc.ENEMY_DIM

    # 도형 M × 6
    for s in nearest(game.shapes, oc.n_shapes):
        obs[i:i + 6] = (1.0, (s.x - p.x) / W, (s.y - p.y) / H, s.hp / s.max_hp,
                        s.score / MAX_SHAPE_SCORE, s.radius / MAX_SHAPE_RADIUS)
        i += oc.SHAPE_DIM
    i = oc.SELF_DIM + oc.n_enemies * oc.ENEMY_DIM + oc.n_shapes * oc.SHAPE_DIM

    # 적 탄환 K × 5
    for b in nearest([b for b in game.combat.bullets if b.team != "player"], oc.n_bullets):
        obs[i:i + 5] = (1.0, (b.x - p.x) / W, (b.y - p.y) / H, b.vx / bspd, b.vy / bspd)
        i += oc.BULLET_DIM
    i = oc.vector_size - oc.n_rays

    # 레이캐스트 (선택): 화면 기준 고정 방향으로 가장 가까운 벽까지 거리 (0~1)
    tm = game.terrain
    for k in range(oc.n_rays):
        a = 2 * math.pi * k / oc.n_rays
        obs[i + k] = tm.raycast(p.x, p.y, math.cos(a), math.sin(a), oc.ray_max_dist) / oc.ray_max_dist
    return obs


class ObservationBuilder:
    """벡터 + 내 주변 타일 격자(지형 종류별 채널) 관찰을 만든다.
    격자는 맵 바깥을 벽으로 채운 배열을 캐시해 두고 잘라서 쓴다 (지형이 바뀔 때만 다시 만듦)."""

    def __init__(self, game_cfg: GameConfig, oc: ObsConfig):
        if oc.grid_size % 2 != 1:
            raise ValueError("grid_size는 홀수여야 합니다.")
        self.oc = oc
        self.channels = grid_channels(game_cfg.terrain)
        self.grid_shape = oc.grid_shape(len(self.channels))
        self.flat_size = oc.flat_size(len(self.channels))
        self._key = None
        self._padded = None

    def _padded_grid(self, tm):
        key = (id(tm), tm.version)
        if key != self._key:
            h = self.oc.grid_size // 2
            arr = tm.as_array()
            codes = {"wall": WALL, "mud": MUD, "breakable": BREAKABLE}
            pad = np.zeros((len(self.channels), tm.rows + 2 * h, tm.cols + 2 * h), dtype=np.float32)
            for ci, name in enumerate(self.channels):
                if name == "wall":
                    pad[ci] = 1.0  # 맵 바깥 = 벽
                pad[ci, h:h + tm.rows, h:h + tm.cols] = (arr == codes[name])
            self._padded, self._key = pad, key
        return self._padded

    def grid(self, game: GameCore) -> np.ndarray:
        tm = game.terrain
        pad = self._padded_grid(tm)
        c, r = tm.tile_of(game.player.x, game.player.y)
        c = min(max(c, 0), tm.cols - 1)
        r = min(max(r, 0), tm.rows - 1)
        g = self.oc.grid_size
        return pad[:, r:r + g, c:c + g].copy()

    def build(self, game: GameCore):
        vec = build_vector(game, self.oc)
        grid = self.grid(game)
        if self.oc.obs_mode == "dict":
            return {"vector": vec, "grid": grid}
        return np.concatenate([vec, grid.ravel()])


def compute_reward(ev: dict, rc: RewardConfig) -> float:
    return (rc.shape_damage * ev["shape_damage_weighted"]
            + rc.shape_destroy * ev["shape_destroyed_score"]
            + rc.enemy_damage * ev["enemy_damage"]
            + rc.enemy_kill * ev["enemies_killed"]
            + rc.damage_taken * ev["damage_taken"]
            + (rc.death if ev["died"] else 0.0)
            + rc.time_step)


def _merge_events(acc: dict, ev: dict):
    for k, v in ev.items():
        acc[k] = (acc[k] or v) if isinstance(v, bool) else acc[k] + v


# --------------------------------------------------------------------------
# 환경
# --------------------------------------------------------------------------
class TankEnv(_BaseEnv):
    metadata = {"render_modes": ["human"], "render_fps": 15}

    def __init__(self, game_config: GameConfig = None, obs_config: ObsConfig = None,
                 reward_config: RewardConfig = None, env_config: EnvConfig = None,
                 render_mode: str = None):
        # 27개 이동/회전 행동으로 학습할 때는 카드 선택을 요구하지 않는다.
        self.game_cfg = game_config or GameConfig(progression_enabled=False, limited_ammo=False)
        self.obs_cfg = obs_config or ObsConfig()
        self.reward_cfg = reward_config or RewardConfig()
        self.env_cfg = env_config or EnvConfig()
        self.render_mode = render_mode
        self.metadata = {"render_modes": ["human"],
                         "render_fps": self.game_cfg.fps // self.env_cfg.frame_skip}

        self.obs_builder = ObservationBuilder(self.game_cfg, self.obs_cfg)
        ob = self.obs_builder
        vec_shape = (self.obs_cfg.vector_size,)
        if spaces is not None:
            self.action_space = spaces.Discrete(N_ACTIONS)
            if self.obs_cfg.obs_mode == "dict":
                self.observation_space = spaces.Dict({
                    "vector": spaces.Box(-np.inf, np.inf, shape=vec_shape, dtype=np.float32),
                    "grid": spaces.Box(0.0, 1.0, shape=ob.grid_shape, dtype=np.float32)})
            else:
                self.observation_space = spaces.Box(-np.inf, np.inf, shape=(ob.flat_size,), dtype=np.float32)
        else:
            self.action_space = _Discrete(N_ACTIONS)
            if self.obs_cfg.obs_mode == "dict":
                self.observation_space = {"vector": _Box(-np.inf, np.inf, vec_shape, np.float32),
                                          "grid": _Box(0.0, 1.0, ob.grid_shape, np.float32)}
            else:
                self.observation_space = _Box(-np.inf, np.inf, (ob.flat_size,), np.float32)

        self.game = GameCore(self.game_cfg, seed=None)
        self.steps = 0
        self._renderer = None

    def reset(self, seed: int = None, options: dict = None):
        if gym is not None:
            super().reset(seed=seed)
        self.game.reset(seed)
        self.steps = 0
        obs = self.obs_builder.build(self.game)
        if self.render_mode == "human":
            self.render()
        return obs, self._info(None)

    def step(self, action):
        acc = empty_events()
        for _ in range(self.env_cfg.frame_skip):
            self.game.step(action)
            _merge_events(acc, self.game.pop_events())
            if self.game.game_over:
                break
        self.steps += 1

        reward = compute_reward(acc, self.reward_cfg)
        terminated = self.game.game_over
        truncated = (not terminated) and self.steps >= self.env_cfg.max_steps
        obs = self.obs_builder.build(self.game)
        if self.render_mode == "human":
            self.render()
        return obs, float(reward), terminated, truncated, self._info(acc)

    def _info(self, events):
        return {"score": self.game.progression.score, "kills": self.game.progression.kills, "map": self.game.terrain.name,
                "frames": self.game.frame, "steps": self.steps, "events": events,
                "level": self.game.progression.level, "xp": self.game.progression.xp,
                "pending_rewards": self.game.progression.pending_rewards, "job": self.game.player.job,
                "ammo": self.game.player.ammo if self.game_cfg.limited_ammo else None,
                "reload_seconds_left": self.game.combat.reload_frames_left / self.game_cfg.fps,
                "upgrade_points": self.game.progression.upgrade_points,
                "family": self.game.progression.family,
                "stat_choices": [card.key for card in self.game.progression.stat_choices],
                "special_reward_levels": list(self.game.progression.special_reward_levels),
                "stat_levels": dict(self.game.progression.stat_levels), "special_levels": dict(self.game.progression.special_levels)}

    def render(self):
        if self.render_mode != "human":
            return
        import pygame
        from space_z.rendering.renderer import Renderer
        if self._renderer is None:
            pygame.init()
            self._renderer = Renderer(self.game_cfg)
        pygame.event.pump()
        self._renderer.draw(self.game)
        pygame.display.flip()
        self._renderer.clock.tick(self.metadata["render_fps"])

    def close(self):
        if self._renderer is not None:
            import pygame
            pygame.quit()
            self._renderer = None
