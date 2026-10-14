"""게임 규칙과 상태. pygame에 의존하지 않는다.

- step(action)을 한 번 부르면 정확히 1프레임(1/fps 초)이 진행된다.
- 전투와 카드 추첨은 별도 난수열을 사용하며, 같은 seed + 같은 행동/카드 선택 → 같은 결과.
- 보상은 여기서 계산하지 않고, 플레이어 관점의 이벤트만 self.events에 누적한다
  (env.py가 pop_events()로 꺼내서 보상으로 변환).
"""
import math
from dataclasses import dataclass, field

import numpy as np

from config import GameConfig, SHAPE_TYPES, SHAPE_KINDS
from terrain import TileMap, load_map, empty_map, generate_random_map, expand_map, BUSH, MUD, BREAKABLE
from progression import REWARD_CARDS

# --------------------------------------------------------------------------
# 행동 정의: 이동 9 × 회전 3 = 27
# --------------------------------------------------------------------------
# move: 0=정지, 1=↑, 2=↗, 3=→, 4=↘, 5=↓, 6=↙, 7=←, 8=↖   (화면 좌표: y가 아래로 증가)
_S = 1.0 / math.sqrt(2.0)
MOVE_VECTORS = [
    (0.0, 0.0), (0.0, -1.0), (_S, -_S), (1.0, 0.0), (_S, _S),
    (0.0, 1.0), (-_S, _S), (-1.0, 0.0), (-_S, -_S),
]
N_MOVES = 9
N_ROTS = 3          # 0=유지, 1=왼쪽(반시계), 2=오른쪽(시계)
N_ACTIONS = N_MOVES * N_ROTS
ROT_DIR = (0.0, -1.0, 1.0)


def encode_action(move: int, rot: int) -> int:
    return move * N_ROTS + rot


def decode_action(action: int):
    action = int(action)
    if not 0 <= action < N_ACTIONS:
        raise ValueError(f"action must be in [0, {N_ACTIONS}), got {action}")
    return divmod(action, N_ROTS)


def move_from_vector(dx: float, dy: float) -> int:
    """임의 방향 벡터를 가장 가까운 8방향 이동 번호로 양자화 (적 AI가 같은 행동 집합을 쓰도록)."""
    if dx * dx + dy * dy < 1e-6:
        return 0
    ang = math.atan2(dy, dx)                       # 0=→, +π/2=↓
    sector = int(round(ang / (math.pi / 4))) % 8   # 0=→,1=↘,2=↓,3=↙,4=←,5=↖,6=↑,7=↗
    return (3, 4, 5, 6, 7, 8, 1, 2)[sector]


def wrap_angle(a: float) -> float:
    return (a + math.pi) % (2 * math.pi) - math.pi


# --------------------------------------------------------------------------
# 엔티티
# --------------------------------------------------------------------------
@dataclass
class Tank:
    id: int
    team: str            # "player" | "enemy"
    x: float
    y: float
    hp: float
    max_hp: float
    radius: float
    fire_cooldown_max: int
    vx: float = 0.0
    vy: float = 0.0
    angle: float = 0.0   # 포신 각도 (rad, 0=→, 시계방향 +)
    cooldown: int = 0
    alive: bool = True
    respawn_timer: int = 0
    last_hit_frame: int = -10**9
    damage_scale: float = 1.0
    accel_scale: float = 1.0
    bullet_speed_scale: float = 1.0
    bullet_life_scale: float = 1.0
    regen_bonus: float = 0.0
    projectiles: int = 1
    job: str = "rookie"
    ammo: int = 0
    max_ammo: int = 0
    # 적 AI 상태
    ai_timer: int = 0
    ai_target: tuple = None      # ("player", id) | ("shape", id) | None
    ai_aim_offset: float = 0.0
    ai_move: int = 0
    ai_can_see: bool = False          # 이번 프레임에 플레이어가 보이는지
    ai_last_seen: tuple = None        # 마지막으로 본 플레이어 위치 (x, y)
    ai_last_seen_frame: int = -10**9
    ai_path: list = field(default_factory=list)   # 남은 경로 (타일 좌표)
    ai_path_timer: int = 0
    ai_goal: tuple = None             # 현재 이동 목표 위치 (디버그 표시용)
    ai_strafe: float = 1.0            # 옆으로 돌 방향


@dataclass
class Shape:
    id: int
    kind: str
    x: float
    y: float
    vx: float
    vy: float
    hp: float
    max_hp: float
    radius: float
    score: int
    angle: float = 0.0
    spin: float = 0.0


@dataclass
class Bullet:
    x: float
    y: float
    vx: float
    vy: float
    life: int
    owner_id: int
    team: str
    damage: float
    radius: float


def empty_events():
    return {
        "shape_damage_weighted": 0.0,  # Σ 데미지 × (점수/최대체력)
        "shape_destroyed_score": 0.0,  # Σ 파괴한 도형 점수
        "shapes_destroyed": 0,
        "enemy_damage": 0.0,
        "enemies_killed": 0,
        "damage_taken": 0.0,
        "died": False,
    }


# --------------------------------------------------------------------------
# 게임
# --------------------------------------------------------------------------
class GameCore:
    def __init__(self, config: GameConfig = None, seed: int = None):
        self.cfg = config or GameConfig()
        if not isinstance(self.cfg.world_scale, int) or self.cfg.world_scale < 1:
            raise ValueError("world_scale은 1 이상의 정수여야 합니다.")
        if self.cfg.level_xp_base <= 0 or self.cfg.level_xp_growth < 0:
            raise ValueError("레벨 경험치는 양수, 증가량은 0 이상이어야 합니다.")
        if not isinstance(self.cfg.player_ammo, int) or self.cfg.player_ammo < 0:
            raise ValueError("player_ammo는 0 이상의 정수여야 합니다.")
        self.reset(seed)

    # ---------------- 초기화 ----------------
    def reset(self, seed: int = None):
        self.rng = np.random.default_rng(seed)
        # 카드 열기/선택이 맵 생성과 전투 난수열을 바꾸지 않도록 분리한다.
        self.reward_rng = np.random.default_rng(seed)
        self.frame = 0
        self.score = 0
        self.kills = 0
        self.game_over = False
        self._next_id = 0
        self.events = empty_events()
        self.level = 1
        self.xp = 0
        self.pending_rewards = 0
        self.reward_choices = ()
        self.last_reward = ""
        self.reward_message_until = 0
        self.bullets = []
        self.shapes = []
        self.enemies = []   # 스폰 위치 계산이 이전 판의 적을 참조하지 않도록 먼저 비움

        c = self.cfg
        self.terrain = self._make_terrain()
        px, py = self.terrain.center(*self.terrain.player_start)
        self.player = Tank(
            id=self._new_id(), team="player", x=px, y=py,
            hp=c.player_hp, max_hp=c.player_hp, radius=c.tank_radius,
            fire_cooldown_max=c.player_fire_cooldown,
            ammo=c.player_ammo, max_ammo=c.player_ammo,
            angle=float(self.rng.uniform(-math.pi, math.pi)),
        )
        for _ in range(c.num_enemies):
            e = Tank(id=self._new_id(), team="enemy", x=0.0, y=0.0,
                     hp=c.enemy_hp, max_hp=c.enemy_hp, radius=c.tank_radius,
                     fire_cooldown_max=c.enemy_ai.fire_cooldown)
            self._respawn_enemy(e)
            self.enemies.append(e)
        for _ in range(c.num_shapes):
            self.shapes.append(self._make_shape())

    def _new_id(self) -> int:
        self._next_id += 1
        return self._next_id

    def _make_terrain(self) -> TileMap:
        c = self.cfg
        tc = c.terrain
        cols, rows = c.width // tc.tile_size, c.height // tc.tile_size
        if cols * tc.tile_size != c.width or rows * tc.tile_size != c.height:
            raise ValueError(f"화면 크기 {c.width}x{c.height}가 타일 크기 {tc.tile_size}로 나누어떨어지지 않습니다.")
        if not tc.enabled:
            return empty_map(tc, cols * c.world_scale, rows * c.world_scale)
        if tc.random_map:
            return generate_random_map(self.rng, tc, cols * c.world_scale, rows * c.world_scale)
        name = tc.map_name
        if tc.map_pool:
            name = tc.map_pool[int(self.rng.integers(len(tc.map_pool)))]
        return expand_map(load_map(name, tc, cols, rows), c.world_scale, tc)

    def is_hidden(self, t) -> bool:
        """수풀 안에 있는 탱크는 상대에게 보이지 않는다."""
        return self.terrain.tile_at(t.x, t.y) == BUSH

    def _random_free_pos(self, radius: float, min_dist: float, tiles=None):
        """벽이 아닌 칸 중에서 탱크들과 min_dist 이상 떨어진 위치."""
        tm = self.terrain
        T = tm.tile
        if tiles is None:
            tiles = tm.open_tiles if radius > T / 2 - 2 and tm.open_tiles else tm.free_tiles
        tanks = [self.player] + [e for e in getattr(self, "enemies", []) if e.alive]
        jitter = max(0.0, T / 2 - radius)
        x = y = 0.0
        for _ in range(20):
            tc, tr = tiles[int(self.rng.integers(len(tiles)))]
            cx, cy = tm.center(tc, tr)
            x = cx + float(self.rng.uniform(-jitter, jitter))
            y = cy + float(self.rng.uniform(-jitter, jitter))
            if all((t.x - x) ** 2 + (t.y - y) ** 2 >= min_dist ** 2 for t in tanks):
                break
        return x, y

    def _make_shape(self) -> Shape:
        c = self.cfg
        weights = np.array([SHAPE_TYPES[k]["weight"] for k in SHAPE_KINDS])
        kind = SHAPE_KINDS[int(self.rng.choice(len(SHAPE_KINDS), p=weights / weights.sum()))]
        t = SHAPE_TYPES[kind]
        x, y = self._random_free_pos(t["radius"], c.spawn_min_dist_from_tanks)
        ang = float(self.rng.uniform(-math.pi, math.pi))
        spd = float(self.rng.uniform(0, c.shape_drift))
        return Shape(id=self._new_id(), kind=kind, x=x, y=y,
                     vx=math.cos(ang) * spd, vy=math.sin(ang) * spd,
                     hp=t["hp"], max_hp=t["hp"], radius=t["radius"], score=t["score"],
                     angle=float(self.rng.uniform(0, 2 * math.pi)),
                     spin=float(self.rng.uniform(-0.01, 0.01)))

    def _respawn_enemy(self, e: Tank):
        tm = self.terrain
        p = self.player
        # 맵의 E 위치 중 플레이어와 멀고 다른 적과 겹치지 않는 곳 우선
        others = [o for o in getattr(self, "enemies", []) if o.alive and o is not e]
        starts = []
        for s in tm.enemy_starts:
            sx, sy = tm.center(*s)
            if (sx - p.x) ** 2 + (sy - p.y) ** 2 >= 300.0 ** 2 and \
                    all((sx - o.x) ** 2 + (sy - o.y) ** 2 >= (2 * e.radius) ** 2 for o in others):
                starts.append((sx, sy))
        if starts:
            e.x, e.y = starts[int(self.rng.integers(len(starts)))]
        else:
            e.x, e.y = self._random_free_pos(e.radius, 300.0)
        e.vx = e.vy = 0.0
        e.hp = e.max_hp
        e.alive = True
        e.cooldown = e.fire_cooldown_max
        e.angle = float(self.rng.uniform(-math.pi, math.pi))
        e.ai_timer = 0
        e.ai_target = None
        e.ai_can_see = False
        e.ai_last_seen = None
        e.ai_path = []
        e.ai_path_timer = 0
        e.ai_goal = None

    # ---------------- 외부 API ----------------
    @property
    def xp_to_next_level(self):
        return self.cfg.level_xp_base + (self.level - 1) * self.cfg.level_xp_growth

    def _add_score(self, amount):
        self.score += amount
        if not self.cfg.progression_enabled:
            return
        self.xp += amount
        while self.xp >= self.xp_to_next_level:
            self.xp -= self.xp_to_next_level
            self.level += 1
            self.pending_rewards += 1

    def open_rewards(self):
        if self.game_over or not self.player.alive or self.pending_rewards == 0:
            return ()
        if not self.reward_choices:
            eligible = [card for card in REWARD_CARDS
                        if (card.category != "전직" or (self.level >= 3 and self.player.job == "rookie"))
                        and (card.key != "ammo" or self.cfg.limited_ammo)]
            indices = self.reward_rng.choice(len(eligible), size=3, replace=False)
            self.reward_choices = tuple(eligible[int(i)] for i in indices)
        return self.reward_choices

    def choose_reward(self, index):
        if self.game_over or not self.player.alive or not self.reward_choices:
            return False
        if not isinstance(index, int) or not 0 <= index < len(self.reward_choices):
            return False
        card = self.reward_choices[index]
        p = self.player
        if card.key == "damage":
            p.damage_scale *= 1.25
        elif card.key == "rapid":
            p.fire_cooldown_max = max(4, int(p.fire_cooldown_max * 0.85))
            p.cooldown = min(p.cooldown, p.fire_cooldown_max)
        elif card.key == "speed":
            p.accel_scale *= 1.15
        elif card.key == "hull":
            p.max_hp += 25
            p.hp = min(p.max_hp, p.hp + 25)
        elif card.key == "heal":
            p.hp = min(p.max_hp, p.hp + p.max_hp * 0.6)
        elif card.key == "regen":
            p.regen_bonus += 1.5 / self.cfg.fps
        elif card.key == "range":
            p.bullet_speed_scale *= 1.2
            p.bullet_life_scale *= 1.15
        elif card.key == "ammo":
            p.ammo = min(p.max_ammo, p.ammo + 40)
        elif card.key == "scout":
            p.job = "scout"
            p.accel_scale *= 1.35
            p.bullet_speed_scale *= 1.2
        elif card.key == "gunner":
            p.job = "gunner"
            p.projectiles = 3
            p.damage_scale *= 0.8
        elif card.key == "guardian":
            p.job = "guardian"
            p.max_hp += 60
            p.hp = p.max_hp
            p.regen_bonus += 1.5 / self.cfg.fps
        self.pending_rewards -= 1
        self.reward_choices = ()
        self.last_reward = card.title
        self.reward_message_until = self.frame + self.cfg.fps * 3
        return True

    def pop_events(self) -> dict:
        ev = self.events
        self.events = empty_events()
        return ev

    def step(self, action: int, *, want_fire: bool = True, aim_position=None):
        """1프레임 진행. 사람 입력은 발사 여부와 월드 좌표 조준점을 별도로 전달한다."""
        if self.game_over:
            return
        move, rot = decode_action(action)
        self._apply_tank_control(self.player, move, rot, self.player.accel_scale, 1.0)
        if aim_position is not None:
            dx, dy = aim_position[0] - self.player.x, aim_position[1] - self.player.y
            if dx * dx + dy * dy > 1e-6:
                self.player.angle = math.atan2(dy, dx)

        for e in self.enemies:
            if e.alive:
                self._enemy_ai(e)
            else:
                e.respawn_timer -= 1
                if e.respawn_timer <= 0:
                    self._respawn_enemy(e)

        self._fire(self.player, want_fire)
        self._move_shapes()
        self._move_bullets()
        self._collide_bullets()
        self._collide_bodies()
        self._regen_player()

        # 도형 개수 유지
        while len(self.shapes) < self.cfg.num_shapes:
            self.shapes.append(self._make_shape())

        self.frame += 1
        if self.player.hp <= 0:
            self.player.hp = 0.0
            self.player.alive = False
            self.game_over = True
            self.events["died"] = True

    # ---------------- 탱크 이동/발사 ----------------
    def _apply_tank_control(self, t: Tank, move: int, rot: int, accel_scale: float, turn_scale: float):
        c = self.cfg
        if self.terrain.tile_at(t.x, t.y) == MUD:
            accel_scale *= c.terrain.mud_accel_scale
        mx, my = MOVE_VECTORS[move]
        t.vx = t.vx * c.friction + mx * c.accel * accel_scale
        t.vy = t.vy * c.friction + my * c.accel * accel_scale
        t.x += t.vx
        t.y += t.vy
        self.terrain.resolve_circle(t)
        self._clamp_to_arena(t)
        t.angle = wrap_angle(t.angle + ROT_DIR[rot] * c.turn_speed * turn_scale)

    def _clamp_to_arena(self, obj):
        c = self.cfg
        r = obj.radius
        if obj.x < r:
            obj.x, obj.vx = r, max(0.0, obj.vx)
        elif obj.x > c.world_width - r:
            obj.x, obj.vx = c.world_width - r, min(0.0, obj.vx)
        if obj.y < r:
            obj.y, obj.vy = r, max(0.0, obj.vy)
        elif obj.y > c.world_height - r:
            obj.y, obj.vy = c.world_height - r, min(0.0, obj.vy)

    def _fire(self, t: Tank, want_fire: bool):
        if t.cooldown > 0:
            t.cooldown -= 1
            return
        if not want_fire:
            return
        c = self.cfg
        offsets = (-0.20, 0.0, 0.20) if t.projectiles == 3 else (0.0,)
        if t.team == "player" and c.limited_ammo:
            # 마지막 탄약이 3발 미만이면 남은 수만큼 발사한다.
            if t.ammo <= 0:
                return
            offsets = offsets[:t.ammo]
            t.ammo -= len(offsets)
        for offset in offsets:
            ca, sa = math.cos(t.angle + offset), math.sin(t.angle + offset)
            self.bullets.append(Bullet(
                x=t.x + ca * c.barrel_length, y=t.y + sa * c.barrel_length,
                vx=ca * c.bullet_speed * t.bullet_speed_scale,
                vy=sa * c.bullet_speed * t.bullet_speed_scale,
                life=int(c.bullet_life * t.bullet_life_scale), owner_id=t.id, team=t.team,
                damage=c.bullet_damage * t.damage_scale, radius=c.bullet_radius,
            ))
        t.cooldown = t.fire_cooldown_max

    # ---------------- 적 AI ----------------
    def _enemy_ai(self, e: Tank):
        c = self.cfg
        ai = c.enemy_ai
        p = self.player
        tm = self.terrain

        # 1) 감지: 사거리 안 + 수풀 밖 + 시야선이 트였을 때만 플레이어를 본다
        e.ai_can_see = (p.alive
                        and (p.x - e.x) ** 2 + (p.y - e.y) ** 2 <= ai.sight_range ** 2
                        and not self.is_hidden(p)
                        and tm.line_of_sight(e.x, e.y, p.x, p.y))
        chasing_player = e.ai_target is not None and e.ai_target[0] in ("player", "point")
        if e.ai_can_see and chasing_player:   # 플레이어를 쫓는 중일 때만 위치를 기억
            e.ai_last_seen = (p.x, p.y)
            e.ai_last_seen_frame = self.frame
        elif e.ai_last_seen is not None and self.frame - e.ai_last_seen_frame > ai.memory_frames:
            e.ai_last_seen = None

        # 2) 목표 선택 (reaction_frames마다): 기억한 위치 추적 중이면 계속, 아니면 플레이어/도형 가중 거리 비교
        e.ai_timer -= 1
        if e.ai_timer <= 0:
            e.ai_timer = ai.reaction_frames
            if e.ai_last_seen is not None and not e.ai_can_see:
                target = ("point", e.ai_last_seen)
            else:
                # 보이는 플레이어와 가장 가까운 도형을 가중 거리로 비교 (player_priority)
                target, best_d = None, float("inf")
                if e.ai_can_see:
                    target, best_d = ("player", p.id), math.hypot(p.x - e.x, p.y - e.y) / ai.player_priority
                for s in self.shapes:
                    d = math.hypot(s.x - e.x, s.y - e.y)
                    if d < best_d:
                        target, best_d = ("shape", s.id), d
            if target != e.ai_target:
                e.ai_path_timer = 0          # 목표가 바뀌면 경로 즉시 재계산
            e.ai_target = target
            e.ai_aim_offset = float(self.rng.normal(0.0, math.radians(ai.aim_noise_deg)))
            e.ai_strafe = 1.0 if self.rng.random() < 0.5 else -1.0
            if target is None:
                e.ai_move = int(self.rng.integers(0, N_MOVES))

        tgt = self._target_pos(e)
        if tgt is None and e.ai_target is not None and e.ai_target[0] != "player":
            e.ai_target = None

        # 3) 이동
        direct = False
        move = e.ai_move if e.ai_target is None else 0
        e.ai_goal = tgt
        if tgt is not None:
            tx, ty = tgt
            kind = e.ai_target[0]
            direct = kind != "point" and tm.line_of_sight(e.x, e.y, tx, ty)
            if direct:
                # 직접 보이면: 적정 거리 유지 + 옆으로 돌기
                e.ai_path = []
                dx, dy = tx - e.x, ty - e.y
                d = math.hypot(dx, dy) + 1e-6
                keep = ai.keep_distance if kind == "player" else 140.0
                if d > keep + 40:
                    vx, vy = dx / d, dy / d
                elif d < keep - 40:
                    vx, vy = -dx / d, -dy / d
                else:
                    vx, vy = -dy / d * e.ai_strafe, dx / d * e.ai_strafe
            else:
                # 안 보이면: A* 경로를 따라감
                e.ai_path_timer -= 1
                if e.ai_path_timer <= 0:
                    e.ai_path_timer = ai.path_recompute_frames
                    e.ai_path = tm.astar(tm.tile_of(e.x, e.y), tm.tile_of(tx, ty))
                while e.ai_path:
                    wx, wy = tm.center(*e.ai_path[0])
                    if (wx - e.x) ** 2 + (wy - e.y) ** 2 < ai.waypoint_reach ** 2:
                        e.ai_path.pop(0)
                    else:
                        break
                if e.ai_path:
                    wx, wy = tm.center(*e.ai_path[0])
                    vx, vy = wx - e.x, wy - e.y
                else:
                    vx, vy = tx - e.x, ty - e.y
                    if kind == "point" and vx * vx + vy * vy < (tm.tile * 0.5) ** 2:
                        e.ai_last_seen = None    # 마지막 위치에 왔는데 없음 → 포기
                        e.ai_timer = 0
            move = move_from_vector(vx, vy)

        # 4) 조준/발사: 목표가 시야에 있을 때만 쏜다
        rot = 0
        aligned = False
        if tgt is not None:
            desired = math.atan2(tgt[1] - e.y, tgt[0] - e.x) + e.ai_aim_offset
            diff = wrap_angle(desired - e.angle)
            step = c.turn_speed * ai.turn_speed_scale
            if diff > step:
                rot = 2
            elif diff < -step:
                rot = 1
            aligned = abs(diff) <= math.radians(ai.fire_angle_tol_deg)
        kind = e.ai_target[0] if e.ai_target else None
        can_fire = (kind == "player" and e.ai_can_see) or (kind == "shape" and direct)

        self._apply_tank_control(e, move, rot, ai.move_speed_scale, ai.turn_speed_scale)
        self._fire(e, aligned and can_fire)

    def _target_pos(self, e: Tank):
        """적 AI 목표의 현재 위치. 플레이어가 안 보이면 마지막으로 본 위치를 쓴다."""
        t = e.ai_target
        if t is None:
            return None
        kind, val = t
        if kind == "player":
            if not self.player.alive:
                return None
            return (self.player.x, self.player.y) if e.ai_can_see else e.ai_last_seen
        if kind == "point":
            return val
        for s in self.shapes:
            if s.id == val:
                return (s.x, s.y)
        return None

    # ---------------- 도형/탄환 ----------------
    def _move_shapes(self):
        c = self.cfg
        for s in self.shapes:
            s.x += s.vx
            s.y += s.vy
            s.angle += s.spin
            if s.x < s.radius or s.x > c.world_width - s.radius:
                s.vx = -s.vx
            if s.y < s.radius or s.y > c.world_height - s.radius:
                s.vy = -s.vy
            self.terrain.resolve_circle(s, bounce=True)
            self._clamp_to_arena(s)
            # 밀려난 속도는 서서히 표류 속도로 감쇠
            spd = math.hypot(s.vx, s.vy)
            if spd > c.shape_drift:
                s.vx *= 0.95
                s.vy *= 0.95

    def _move_bullets(self):
        c = self.cfg
        tm = self.terrain
        alive = []
        for b in self.bullets:
            b.x += b.vx
            b.y += b.vy
            b.life -= 1
            if not (b.life > 0 and b.radius <= b.x <= c.world_width - b.radius and b.radius <= b.y <= c.world_height - b.radius):
                continue
            if tm.has_solid and tm.is_solid_at(b.x, b.y):   # 벽에 닿으면 소멸
                tc, tr = tm.tile_of(b.x, b.y)
                if tm.tiles[tr][tc] == BREAKABLE:
                    tm.damage_tile(tc, tr, b.damage)
                continue
            alive.append(b)
        self.bullets = alive

    def _collide_bullets(self):
        remaining = []
        for b in self.bullets:
            if not self._bullet_hit(b):
                remaining.append(b)
        self.bullets = remaining
        self.shapes = [s for s in self.shapes if s.hp > 0]

    def _bullet_hit(self, b: Bullet) -> bool:
        """탄환이 무언가에 맞았으면 데미지 처리 후 True."""
        bx, by, br = b.x, b.y, b.radius
        by_player = b.team == "player"
        # 탱크
        targets = self.enemies if by_player else (self.player,)
        for t in targets:
            r = br + t.radius
            if t.alive and (t.x - bx) ** 2 + (t.y - by) ** 2 < r * r:
                self._damage_tank(t, b.damage, by_player=by_player)
                return True
        # 도형 (호출 수가 많아 거리 계산을 인라인)
        for s in self.shapes:
            r = br + s.radius
            if (s.x - bx) ** 2 + (s.y - by) ** 2 < r * r and s.hp > 0:
                self._damage_shape(s, b.damage, by_player=by_player)
                return True
        return False

    def _damage_tank(self, t: Tank, dmg: float, by_player: bool):
        dealt = min(dmg, t.hp)
        if dealt <= 0:
            return
        t.hp -= dealt
        t.last_hit_frame = self.frame
        if t.team == "player":
            self.events["damage_taken"] += dealt
            return
        if by_player:
            self.events["enemy_damage"] += dealt
        if t.hp <= 0:
            t.alive = False
            t.respawn_timer = self.cfg.enemy_ai.respawn_frames
            if by_player:
                self.events["enemies_killed"] += 1
                self.kills += 1
                self._add_score(self.cfg.enemy_kill_score)

    def _damage_shape(self, s: Shape, dmg: float, by_player: bool):
        dealt = min(dmg, s.hp)
        if dealt <= 0:
            return
        s.hp -= dealt
        if by_player:
            self.events["shape_damage_weighted"] += dealt * s.score / s.max_hp
            if s.hp <= 0:
                self.events["shape_destroyed_score"] += s.score
                self.events["shapes_destroyed"] += 1
                self._add_score(s.score)

    # ---------------- 몸체 충돌 ----------------
    def _collide_bodies(self):
        bd = self.cfg.body_damage
        tanks = [self.player] + [e for e in self.enemies if e.alive]
        for t in tanks:
            for s in self.shapes:
                r = t.radius + s.radius
                if (s.x - t.x) ** 2 + (s.y - t.y) ** 2 < r * r and s.hp > 0:
                    _push_apart(t, s, 0.3)
                    self._damage_shape(s, bd, by_player=(t.team == "player"))
                    self._damage_tank(t, bd, by_player=False)
        p = self.player
        for e in self.enemies:
            if e.alive and _overlap(p, e):
                _push_apart(p, e, 0.5)
                self._damage_tank(e, bd, by_player=True)
                self._damage_tank(p, bd, by_player=False)
        for i, a in enumerate(self.enemies):
            for b in self.enemies[i + 1:]:
                if a.alive and b.alive and _overlap(a, b):
                    _push_apart(a, b, 0.5)
        self.shapes = [s for s in self.shapes if s.hp > 0]
        # 서로 밀어내다 벽에 들어간 경우 다시 밖으로
        for o in tanks + self.shapes:
            self.terrain.resolve_circle(o)
            self._clamp_to_arena(o)

    def _regen_player(self):
        p = self.player
        c = self.cfg
        if p.hp > 0 and self.frame - p.last_hit_frame >= c.regen_delay:
            p.hp = min(p.max_hp, p.hp + c.regen_rate + p.regen_bonus)


def _overlap(a, b) -> bool:
    r = a.radius + b.radius
    dx, dy = a.x - b.x, a.y - b.y
    return dx * dx + dy * dy < r * r


def _push_apart(a, b, a_share: float):
    """겹친 만큼 밀어낸다. a_share는 a가 움직이는 비율."""
    dx, dy = a.x - b.x, a.y - b.y
    d = math.hypot(dx, dy)
    if d < 1e-6:
        dx, dy, d = 1.0, 0.0, 1.0
    overlap = a.radius + b.radius - d
    nx, ny = dx / d, dy / d
    a.x += nx * overlap * a_share
    a.y += ny * overlap * a_share
    b.x -= nx * overlap * (1 - a_share)
    b.y -= ny * overlap * (1 - a_share)
    # 밀려나는 방향으로 약한 반동
    a.vx += nx * 0.5 * a_share
    a.vy += ny * 0.5 * a_share
    b.vx -= nx * 0.5 * (1 - a_share)
    b.vy -= ny * 0.5 * (1 - a_share)
