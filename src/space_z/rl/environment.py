"""강화학습 환경 (Gymnasium 스타일).

    env = TankEnv()
    observation, info = env.reset(seed=0)
    observation, reward, terminated, truncated, info = env.step(action)   # action: 0..26

gymnasium이 설치되어 있으면 gymnasium.Env를 상속하고 observation_space/action_space를
gymnasium.spaces로 제공한다. 없으면 같은 인터페이스의 최소 대체 클래스를 쓴다.
"""

import math

import numpy as np

from space_z.config import (
    GameConfig,
    ObsConfig,
    RewardConfig,
    EnvConfig,
    MAX_SHAPE_SCORE,
    MAX_SHAPE_RADIUS,
)
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
def build_vector(game: GameCore, observation_config: ObsConfig) -> np.ndarray:
    """지형 격자를 제외한 벡터 관찰 (내 탱크, 적, 도형, 적 탄환, 레이)."""

    # 월드 크기와 속도 정규화 기준을 읽고 관측 벡터를 준비한다.
    config = game.config
    world_width, world_height = float(config.world_width), float(config.world_height)
    max_speed = config.max_speed
    bullet_speed = config.bullet_speed
    player = game.player
    observation = np.zeros(observation_config.vector_size, dtype=np.float32)

    # 내 탱크 (8): 은신 지형/관찰 항목은 사용하지 않는다.
    observation[0:8] = (
        player.x / world_width,
        player.y / world_height,
        player.velocity_x / max_speed,
        player.velocity_y / max_speed,
        player.hp / player.max_hp,
        math.sin(player.angle),
        math.cos(player.angle),
        1.0 - player.cooldown / player.fire_cooldown_max,
    )
    observation_offset = observation_config.SELF_DIM

    def nearest(entities, limit):
        return sorted(
            entities,
            key=lambda entity: (entity.x - player.x) ** 2 + (entity.y - player.y) ** 2,
        )[:limit]

    # 적 탱크 N × 8
    for enemy in nearest(
        [enemy for enemy in game.enemies if enemy.alive], observation_config.n_enemies
    ):
        observation[observation_offset : observation_offset + 8] = (
            1.0,
            (enemy.x - player.x) / world_width,
            (enemy.y - player.y) / world_height,
            enemy.velocity_x / max_speed,
            enemy.velocity_y / max_speed,
            enemy.hp / enemy.max_hp,
            math.sin(enemy.angle),
            math.cos(enemy.angle),
        )
        observation_offset += observation_config.ENEMY_DIM
    observation_offset = (
        observation_config.SELF_DIM
        + observation_config.n_enemies * observation_config.ENEMY_DIM
    )

    # 도형 M × 6
    for shape in nearest(game.shapes, observation_config.n_shapes):
        observation[observation_offset : observation_offset + 6] = (
            1.0,
            (shape.x - player.x) / world_width,
            (shape.y - player.y) / world_height,
            shape.hp / shape.max_hp,
            shape.score / MAX_SHAPE_SCORE,
            shape.radius / MAX_SHAPE_RADIUS,
        )
        observation_offset += observation_config.SHAPE_DIM
    observation_offset = (
        observation_config.SELF_DIM
        + observation_config.n_enemies * observation_config.ENEMY_DIM
        + observation_config.n_shapes * observation_config.SHAPE_DIM
    )

    # 적 탄환 K × 5
    for bullet in nearest(
        [bullet for bullet in game.combat.bullets if bullet.team != "player"],
        observation_config.n_bullets,
    ):
        observation[observation_offset : observation_offset + 5] = (
            1.0,
            (bullet.x - player.x) / world_width,
            (bullet.y - player.y) / world_height,
            bullet.velocity_x / bullet_speed,
            bullet.velocity_y / bullet_speed,
        )
        observation_offset += observation_config.BULLET_DIM
    observation_offset = observation_config.vector_size - observation_config.n_rays

    # 레이캐스트 (선택): 화면 기준 고정 방향으로 가장 가까운 벽까지 거리 (0~1)
    terrain = game.terrain
    for ray_index in range(observation_config.n_rays):
        ray_angle_radians = 2 * math.pi * ray_index / observation_config.n_rays
        observation[observation_offset + ray_index] = (
            terrain.raycast(
                player.x,
                player.y,
                math.cos(ray_angle_radians),
                math.sin(ray_angle_radians),
                observation_config.ray_max_dist,
            )
            / observation_config.ray_max_dist
        )
    return observation


class ObservationBuilder:
    """벡터 + 내 주변 타일 격자(지형 종류별 채널) 관찰을 만든다.
    격자는 맵 바깥을 벽으로 채운 배열을 캐시해 두고 잘라서 쓴다 (지형이 바뀔 때만 다시 만듦)."""

    def __init__(self, game_config: GameConfig, observation_config: ObsConfig):
        if observation_config.grid_size % 2 != 1:
            raise ValueError("grid_size는 홀수여야 합니다.")
        self.observation_config = observation_config
        self.channels = grid_channels(game_config.terrain)
        self.grid_shape = observation_config.grid_shape(len(self.channels))
        self.flat_size = observation_config.flat_size(len(self.channels))
        self._key = None
        self._padded = None

    def _padded_grid(self, terrain):
        # 맵이나 지형 버전이 바뀐 경우에만 관측용 격자 캐시를 다시 만든다.
        key = (id(terrain), terrain.version)
        if key != self._key:
            # 맵 가장자리 밖을 포함할 채널별 격자 공간을 준비한다.
            padding = self.observation_config.grid_size // 2
            tile_array = terrain.as_array()
            codes = {"wall": WALL, "mud": MUD, "breakable": BREAKABLE}
            padded_grid = np.zeros(
                (
                    len(self.channels),
                    terrain.rows + 2 * padding,
                    terrain.cols + 2 * padding,
                ),
                dtype=np.float32,
            )

            # 지형 종류별 채널을 채우고 맵 바깥은 벽으로 표시한다.
            for channel_index, name in enumerate(self.channels):
                if name == "wall":
                    padded_grid[channel_index] = 1.0  # 맵 바깥 = 벽
                padded_grid[
                    channel_index,
                    padding : padding + terrain.rows,
                    padding : padding + terrain.cols,
                ] = tile_array == codes[name]
            self._padded, self._key = padded_grid, key
        return self._padded

    def grid(self, game: GameCore) -> np.ndarray:
        # 플레이어의 타일 좌표와 주변 격자 캐시를 가져온다.
        terrain = game.terrain
        padded_grid = self._padded_grid(terrain)
        col, row = terrain.tile_of(game.player.x, game.player.y)

        # 플레이어 좌표를 맵 내부로 제한하고 주변 타일 영역을 복사한다.
        col = min(max(col, 0), terrain.cols - 1)
        row = min(max(row, 0), terrain.rows - 1)
        grid_size = self.observation_config.grid_size
        return padded_grid[:, row : row + grid_size, col : col + grid_size].copy()

    def build(self, game: GameCore):
        # 플레이어 주변의 벡터 관측과 타일 격자 관측을 만든다.
        vector = build_vector(game, self.observation_config)
        grid = self.grid(game)

        # 설정에 따라 관측을 사전 또는 평탄화한 배열로 반환한다.
        if self.observation_config.obs_mode == "dict":
            return {"vector": vector, "grid": grid}
        return np.concatenate([vector, grid.ravel()])


def compute_reward(events: dict, reward_config: RewardConfig) -> float:
    # 이번 행동 동안 누적된 피해·처치·사망 이벤트를 학습 보상으로 합산한다.
    return (
        reward_config.shape_damage * events["shape_damage_weighted"]
        + reward_config.shape_destroy * events["shape_destroyed_score"]
        + reward_config.enemy_damage * events["enemy_damage"]
        + reward_config.enemy_kill * events["enemies_killed"]
        + reward_config.damage_taken * events["damage_taken"]
        + (reward_config.death if events["died"] else 0.0)
        + reward_config.time_step
    )


def _merge_events(accumulated_events: dict, events: dict):
    # 피해량과 횟수는 합산하고 사망 여부 같은 불리언 이벤트는 누적한다.
    for event_name, event_value in events.items():
        accumulated_events[event_name] = (
            (accumulated_events[event_name] or event_value)
            if isinstance(event_value, bool)
            else accumulated_events[event_name] + event_value
        )


# --------------------------------------------------------------------------
# 환경
# --------------------------------------------------------------------------
class TankEnv(_BaseEnv):
    metadata = {"render_modes": ["human"], "render_fps": 15}

    def __init__(
        self,
        game_config: GameConfig = None,
        obs_config: ObsConfig = None,
        reward_config: RewardConfig = None,
        env_config: EnvConfig = None,
        render_mode: str = None,
    ):
        # 27개 이동/회전 행동으로 학습할 때는 카드 선택을 요구하지 않는다.
        self.game_config = game_config or GameConfig(
            progression_enabled=False, limited_ammo=False
        )
        self.observation_config = obs_config or ObsConfig()
        self.reward_config = reward_config or RewardConfig()
        self.environment_config = env_config or EnvConfig()
        self.render_mode = render_mode
        self.metadata = {
            "render_modes": ["human"],
            "render_fps": self.game_config.fps // self.environment_config.frame_skip,
        }

        # 관측 모양을 계산하고 설치된 Gymnasium에 맞춰 행동·관측 공간을 정의한다.
        self.observation_builder = ObservationBuilder(
            self.game_config, self.observation_config
        )
        observation_builder = self.observation_builder
        vector_shape = (self.observation_config.vector_size,)
        if spaces is not None:
            self.action_space = spaces.Discrete(N_ACTIONS)
            if self.observation_config.obs_mode == "dict":
                self.observation_space = spaces.Dict(
                    {
                        "vector": spaces.Box(
                            -np.inf, np.inf, shape=vector_shape, dtype=np.float32
                        ),
                        "grid": spaces.Box(
                            0.0,
                            1.0,
                            shape=observation_builder.grid_shape,
                            dtype=np.float32,
                        ),
                    }
                )
            else:
                self.observation_space = spaces.Box(
                    -np.inf,
                    np.inf,
                    shape=(observation_builder.flat_size,),
                    dtype=np.float32,
                )
        else:
            self.action_space = _Discrete(N_ACTIONS)
            if self.observation_config.obs_mode == "dict":
                self.observation_space = {
                    "vector": _Box(-np.inf, np.inf, vector_shape, np.float32),
                    "grid": _Box(0.0, 1.0, observation_builder.grid_shape, np.float32),
                }
            else:
                self.observation_space = _Box(
                    -np.inf, np.inf, (observation_builder.flat_size,), np.float32
                )

        # 환경이 진행할 게임과 에피소드 카운터를 초기화한다.
        self.game = GameCore(self.game_config, seed=None)
        self.steps = 0
        self._renderer = None

    def reset(self, seed: int = None, options: dict = None):
        # 환경과 게임을 같은 시드로 초기화하고 이전 판의 화면 연출을 비운다.
        if gym is not None:
            super().reset(seed=seed)
        self.game.reset(seed)
        if self._renderer is not None:
            self._renderer.reset_score_popups()
        self.steps = 0

        # 새 판의 첫 관측과 부가 정보를 만들고 요청 시 화면을 갱신한다.
        observation = self.observation_builder.build(self.game)
        if self.render_mode == "human":
            self.render()
        return observation, self._info(None)

    def step(self, action):
        # 하나의 행동을 여러 게임 프레임에 적용하면서 발생한 이벤트를 모은다.
        accumulated_events = empty_events()
        for _ in range(self.environment_config.frame_skip):
            self.game.step(action)
            _merge_events(accumulated_events, self.game.pop_events())
            if self.render_mode != "human":
                self.game.pop_score_award_events()  # 화면 없는 학습에서는 전달 대기 기록을 남기지 않음
            if self.game.game_over:
                break
        self.steps += 1

        # 누적 보상과 종료·시간 제한 여부를 계산하고 다음 관측을 만든다.
        reward = compute_reward(accumulated_events, self.reward_config)
        terminated = self.game.game_over
        truncated = (not terminated) and self.steps >= self.environment_config.max_steps
        observation = self.observation_builder.build(self.game)
        if self.render_mode == "human":
            self.render()
        return (
            observation,
            float(reward),
            terminated,
            truncated,
            self._info(accumulated_events),
        )

    def _info(self, events):
        # 점수·성장·무장·맵 상태를 학습 결과의 부가 정보로 정리한다.
        return {
            "score": self.game.progression.score,
            "kills": self.game.progression.kills,
            "map": self.game.terrain.name,
            "frames": self.game.frame,
            "steps": self.steps,
            "events": events,
            "level": self.game.progression.level,
            "xp": self.game.progression.xp,
            "pending_rewards": self.game.progression.pending_rewards,
            "job": self.game.player.job,
            "ammo": self.game.player.ammo if self.game_config.limited_ammo else None,
            "reload_seconds_left": self.game.combat.reload_frames_left
            / self.game_config.fps,
            "upgrade_points": self.game.progression.upgrade_points,
            "family": self.game.progression.family,
            "stat_choices": [card.key for card in self.game.progression.stat_choices],
            "special_reward_levels": list(self.game.progression.special_reward_levels),
            "stat_levels": dict(self.game.progression.stat_levels),
            "special_levels": dict(self.game.progression.special_levels),
        }

    def render(self):
        # 화면 출력이 요청된 경우 렌더러를 준비한다.
        if self.render_mode != "human":
            return
        import pygame
        from space_z.rendering.renderer import Renderer

        if self._renderer is None:
            pygame.init()
            self._renderer = Renderer(self.game_config)

        # 대기 이벤트를 처리하고 점수 연출과 현재 게임 화면을 표시한다.
        pygame.event.pump()
        self._renderer.add_score_popups(self.game.pop_score_award_events())
        self._renderer.draw(self.game)
        pygame.display.flip()
        self._renderer.clock.tick(self.metadata["render_fps"])

    def close(self):
        if self._renderer is not None:
            import pygame

            pygame.quit()
            self._renderer = None
