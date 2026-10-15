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
from terrain import TileMap, load_map, empty_map, generate_random_map, MUD, BREAKABLE
from progression import STAT_UPGRADES, SHIPS, FAMILIES, ENEMY_SHOTS

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
    reload_scale: float = 1.0
    pending_shots: list = field(default_factory=list)
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
    blast_radius: float = 0.0
    prev_x: float = None
    prev_y: float = None
    kind: str = "plasma"
    arming_frames: int = 0
    homing: bool = False


@dataclass
class Beam:
    x: float
    y: float
    end_x: float
    end_y: float
    life: int = 6


@dataclass
class Explosion:
    x: float
    y: float
    radius: float
    life: int = 18


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
        if self.cfg.reload_seconds <= 0 or self.cfg.fps <= 0:
            raise ValueError("reload_seconds와 fps는 양수여야 합니다.")
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
        self.upgrade_points = 0
        self.special_reward_levels = []
        self.stat_levels = {card.key: 0 for card in STAT_UPGRADES}
        self.stat_choices = STAT_UPGRADES
        self.special_levels = {key: 0 for key in SHIPS}
        self.family = ""
        self.active_skill = None
        self.skill_cooldown = 0
        self.reward_portrait = None
        self.reward_choices = ()
        self.last_reward = ""
        self.reward_message_until = 0
        self.reload_frames_left = 0
        self.dash_frames_left = 0
        self.beams = []
        self.explosions = []
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
        return load_map(name, tc, cols * c.world_scale, rows * c.world_scale)

    def _random_free_pos(self, radius: float, min_dist: float, tiles=None):
        """선체 전체가 벽 밖에 있고 다른 선체와 떨어진 위치를 고른다."""
        tm = self.terrain
        if tiles is None:
            tiles = tm.navigation_tiles(radius)
        else:
            tiles = tuple(tile for tile in tiles if tm.circle_fits(*tm.center(*tile), radius))
        if not tiles:
            raise ValueError(f"반지름 {radius:g}의 개체가 들어갈 공간이 없습니다.")
        tanks = [self.player] + [e for e in getattr(self, "enemies", []) if e.alive]
        jitter = max(0.0, tm.tile / 2 - radius)
        best = None
        for _ in range(80):
            col, row = tiles[int(self.rng.integers(len(tiles)))]
            cx, cy = tm.center(col, row)
            x = cx + float(self.rng.uniform(-jitter, jitter))
            y = cy + float(self.rng.uniform(-jitter, jitter))
            if not tm.circle_fits(x, y, radius):
                x, y = cx, cy
            clearance = min((math.hypot(t.x - x, t.y - y) - radius - t.radius for t in tanks), default=math.inf)
            if best is None or clearance > best[0]:
                best = clearance, x, y
            if all(math.hypot(t.x - x, t.y - y) >= max(min_dist, radius + t.radius) for t in tanks):
                return x, y
        return best[1], best[2]

    def _fit_player_after_evolution(self):
        """반지름이 커져 벽과 겹쳤을 때 가장 가까운 넓은 칸으로 옮긴다."""
        p, tm = self.player, self.terrain
        if tm.circle_fits(p.x, p.y, p.radius):
            return
        candidates = tm.navigation_tiles(p.radius)
        if not candidates:
            raise ValueError("진화한 선체가 들어갈 공간이 없습니다.")
        col, row = min(candidates, key=lambda tile: (tm.center(*tile)[0] - p.x) ** 2 + (tm.center(*tile)[1] - p.y) ** 2)
        p.x, p.y = tm.center(col, row)
        p.vx = p.vy = 0.0

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
            if not tm.circle_fits(sx, sy, e.radius):
                continue
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
        e.pending_shots.clear()
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

    @property
    def pending_rewards(self):
        return self.upgrade_points + len(self.special_reward_levels)

    def _add_score(self, amount):
        self.score += amount
        if not self.cfg.progression_enabled:
            return
        self.xp += amount
        while self.xp >= self.xp_to_next_level:
            self.xp -= self.xp_to_next_level
            self.level += 1
            if self.level % 10 == 0:
                self.special_reward_levels.append(self.level)
            else:
                self.upgrade_points += 1
        self.open_rewards()
        self.open_stat_upgrades()

    def open_rewards(self):
        if self.game_over or not self.player.alive or not self.special_reward_levels:
            return ()
        if self.reward_choices:
            return self.reward_choices
        level = self.special_reward_levels[0]
        if level == 10:
            self.reward_choices = FAMILIES
        elif level in (20, 30):
            self.reward_choices = tuple(ship for ship in SHIPS.values()
                                        if ship.parent == self.player.job and ship.level == level)
        else:
            self.reward_choices = (SHIPS[self.player.job],)
        return self.reward_choices

    def choose_reward(self, index):
        if self.game_over or not self.player.alive or not self.reward_choices or not self.special_reward_levels:
            return False
        if not isinstance(index, int) or not 0 <= index < len(self.reward_choices):
            return False
        card = self.reward_choices[index]
        p = self.player
        level = self.special_reward_levels[0]
        previous = SHIPS[p.job]
        if level == 10:
            self.family = card.key
        hp_delta = card.hp_bonus - previous.hp_bonus
        p.max_hp += hp_delta
        p.hp = min(p.max_hp, p.hp + hp_delta)
        p.radius = self.cfg.tank_radius * card.radius_scale
        p.job = card.key
        p.projectiles = len(card.shots)
        p.cooldown = 0
        p.pending_shots.clear()
        self._fit_player_after_evolution()
        self.special_levels[card.key] += 1
        self.special_reward_levels.pop(0)
        self.reward_choices = ()
        self.reward_portrait = card.key
        self._reward_notice(card.title if level <= 30 else f"{card.title} 숙련 +1")
        self.open_rewards()
        return True

    def open_stat_upgrades(self):
        # 숫자 1~5와 각 능력치 위치는 포인트 유무나 강화 한도와 관계없이 고정한다.
        self.stat_choices = STAT_UPGRADES
        return self.stat_choices

    def can_upgrade_stat(self, key):
        return (key in self.stat_levels and self.upgrade_points > 0 and not self.game_over
                and self.player.alive and not (key == "rapid" and self.player.fire_cooldown_max <= 4))

    def upgrade_stat(self, key):
        if not self.can_upgrade_stat(key):
            return False
        p = self.player
        if key == "damage":
            p.damage_scale *= 1.25
        elif key == "rapid":
            old_cooldown = p.fire_cooldown_max
            p.fire_cooldown_max = max(4, int(p.fire_cooldown_max * 0.85))
            p.cooldown = math.ceil(p.cooldown * p.fire_cooldown_max / old_cooldown)
        elif key == "speed":
            p.accel_scale *= 1.15
        elif key == "hull":
            p.max_hp += 25
            p.hp = min(p.max_hp, p.hp + 25)
        elif key == "range":
            p.bullet_speed_scale *= 1.2
            p.bullet_life_scale *= 1.15
        self.upgrade_points -= 1
        self.stat_levels[key] += 1
        self._reward_notice(next(card.title for card in STAT_UPGRADES if card.key == key))
        self.stat_choices = ()
        self.open_stat_upgrades()
        return True

    def _reward_notice(self, title):
        self.last_reward = title
        self.reward_message_until = self.frame + self.cfg.fps * 3

    @property
    def reload_frames_total(self):
        return math.ceil(max(0.75, self.cfg.reload_seconds * self.player.reload_scale) * self.cfg.fps)

    def request_reload(self):
        if (self.game_over or not self.player.alive or not self.cfg.limited_ammo
                or self.reload_frames_left or self.player.ammo >= self.player.max_ammo):
            return False
        self.reload_frames_left = self.reload_frames_total
        self.player.pending_shots.clear()
        return True

    def request_skill(self, move=0, aim_position=None):
        """이전 호출자를 위한 호환 API. Q/Space 액티브는 제거됐다."""
        return False

    def _shot_delays(self, tank, spec):
        # 발사속도 강화는 연사 묶음 사이 대기뿐 아니라 묶음 안의 점사도 빠르게 한다.
        scale = tank.fire_cooldown_max / max(1, self.cfg.player_fire_cooldown) if tank.team == "player" else 1.0
        delays, previous = {0: 0}, 0
        for delay in sorted({shot.delay for shot in spec.shots if shot.delay}):
            previous = max(previous + 1, round(delay * scale))
            delays[delay] = previous
        return delays

    def weapon_values(self, tank):
        spec = SHIPS[tank.job] if tank.team == "player" else SHIPS["rookie"]
        mastery = 1 + 0.2 * max(0, self.special_levels.get(tank.job, 0) - 1) if tank.team == "player" else 1
        damage = self.cfg.bullet_damage * tank.damage_scale * spec.damage * mastery
        burst_end = max(self._shot_delays(tank, spec).values())
        cooldown = max(2 if spec.cooldown < 1 else 4, burst_end, int(tank.fire_cooldown_max * spec.cooldown))
        return (spec, damage, cooldown, self.cfg.bullet_speed * tank.bullet_speed_scale * spec.speed,
                int(self.cfg.bullet_life * tank.bullet_life_scale * spec.life))

    def _emit_shot(self, tank, shot, damage, speed, life):
        """실선체·포신 크기에 맞춘 위치와 내경으로 한 발을 만든다."""
        angle = tank.angle + shot.angle
        ca, sa = math.cos(angle), math.sin(angle)
        forward, lateral = shot.forward * tank.radius, shot.lateral * tank.radius
        radius = tank.radius * shot.caliber
        base_x, base_y = tank.x - sa * lateral, tank.y + ca * lateral
        reach, wall = self.terrain.sweep_circle(base_x, base_y, ca, sa, forward, radius)
        # 포신이 벽과 겹쳐도 벽 뒤에서 탄이 생기지 않게 실제 포신 축을 따라 자른다.
        if wall is not None:
            reach = max(0.0, reach - 0.01)
        bullet = Bullet(
            base_x + ca * reach, base_y + sa * reach, ca * speed * shot.speed, sa * speed * shot.speed,
            max(1, int(life * shot.life)), tank.id, tank.team, damage * shot.damage, radius,
            kind="shell" if tank.job in ("sniper", "railgunner", "hyper_railgun", "hunter", "predator") else "plasma")
        # 길어진 포신과 이미 겹친 작은 천체/적을 포구 뒤에 남겨 놓고 발사하지 않는다.
        bullet.prev_x, bullet.prev_y = base_x, base_y
        if not self._bullet_hit(bullet):
            bullet.prev_x = bullet.prev_y = None
            self.bullets.append(bullet)

    def _tick_effects(self):
        for effects in (self.beams, self.explosions):
            for effect in effects:
                effect.life -= 1
            effects[:] = [effect for effect in effects if effect.life > 0]

    def _explode(self, x, y, damage, radius, team):
        by_player = team == "player"
        self.explosions.append(Explosion(x, y, radius))
        targets = self.enemies if by_player else [self.player]
        for target in list(targets) + list(self.shapes):
            if isinstance(target, Tank) and not target.alive:
                continue
            distance = math.hypot(target.x - x, target.y - y)
            if distance <= radius + target.radius:
                dealt = damage * (0.4 + 0.6 * max(0.0, 1 - distance / radius))
                if isinstance(target, Tank):
                    self._damage_tank(target, dealt, by_player)
                else:
                    self._damage_shape(target, dealt, by_player)
        for col, row in list(self.terrain.hp):
            cx, cy = self.terrain.center(col, row)
            if math.hypot(cx - x, cy - y) <= radius:
                self.terrain.damage_tile(col, row, damage)

    def pop_events(self) -> dict:
        ev = self.events
        self.events = empty_events()
        return ev

    def step(self, action: int, *, want_fire: bool = True, aim_position=None,
             want_skill: bool = False, want_dash: bool = False):
        """1프레임 진행. 사람 입력은 발사 여부와 월드 좌표 조준점을 별도로 전달한다."""
        if self.game_over:
            return
        move, rot = decode_action(action)
        self._tick_effects()
        if aim_position is not None:
            self.player.angle = math.atan2(aim_position[1] - self.player.y, aim_position[0] - self.player.x)
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
        self._collide_bodies()
        self._regen_player()

        # 도형 개수 유지
        while len(self.shapes) < self.cfg.num_shapes:
            self.shapes.append(self._make_shape())

        self.frame += 1
        if self.reload_frames_left:
            self.reload_frames_left -= 1
            if self.reload_frames_left == 0 and self.player.hp > 0:
                self.player.ammo = self.player.max_ammo
        if self.player.hp <= 0:
            self.player.hp = 0.0
            self.player.alive = False
            self.player.pending_shots.clear()
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
        # 대시와 누적 속도 강화도 얇은 벽을 건너뛰지 않도록 나눠 이동한다.
        count = max(1, math.ceil(math.hypot(t.vx, t.vy) / max(1, t.radius * 0.5)))
        for _ in range(count):
            t.x += t.vx / count
            t.y += t.vy / count
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
        player = t.team == "player"
        blocked = not t.alive or (player and self.reload_frames_left)
        if blocked:
            t.pending_shots.clear()
        else:
            # 방아쇠를 놓아도 시작한 점사는 마치되, 재장전/전직/죽음은 취소한다.
            due = [entry for entry in t.pending_shots if entry[0] <= self.frame]
            t.pending_shots[:] = [entry for entry in t.pending_shots if entry[0] > self.frame]
            for _, shot, damage, speed, life in due:
                if player and self.cfg.limited_ammo:
                    if t.ammo <= 0:
                        t.pending_shots.clear()
                        break
                    t.ammo -= 1
                self._emit_shot(t, shot, damage, speed, life)
        if t.cooldown > 0:
            t.cooldown -= 1
            return
        if blocked or not want_fire:
            return
        if player and self.cfg.limited_ammo and t.ammo <= 0:
            return
        spec, damage, cooldown, speed, life = self.weapon_values(t)
        delays = self._shot_delays(t, spec)
        shots = spec.shots if player else (ENEMY_SHOTS[t.id % len(ENEMY_SHOTS)],)
        for shot in shots:
            if shot.delay:
                t.pending_shots.append((self.frame + delays[shot.delay], shot, damage, speed, life))
            else:
                if player and self.cfg.limited_ammo:
                    if t.ammo <= 0:
                        break
                    t.ammo -= 1
                self._emit_shot(t, shot, damage, speed, life)
        t.cooldown = cooldown

    # ---------------- 적 AI ----------------
    def _enemy_ai(self, e: Tank):
        c = self.cfg
        ai = c.enemy_ai
        p = self.player
        tm = self.terrain

        # 1) 감지: 사거리 안 + 시야선이 트였을 때 플레이어를 본다
        e.ai_can_see = (p.alive
                        and (p.x - e.x) ** 2 + (p.y - e.y) ** 2 <= ai.sight_range ** 2
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
            direct = kind != "point" and tm.segment_fits(e.x, e.y, tx, ty, e.radius)
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
                    target_tile = tm.tile_of(tx, ty)
                    if not tm.circle_fits(*tm.center(*target_tile), e.radius):
                        safe = tm.navigation_tiles(e.radius)
                        target_tile = min(safe, key=lambda tile: (tm.center(*tile)[0] - tx) ** 2 + (tm.center(*tile)[1] - ty) ** 2) if safe else target_tile
                    e.ai_path = tm.astar(tm.tile_of(e.x, e.y), target_tile, radius=e.radius)
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
                    vx, vy = 0.0, 0.0
                    if kind == "point" and (tx - e.x) ** 2 + (ty - e.y) ** 2 < (tm.tile * 0.5) ** 2:
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
        tm = self.terrain
        alive = []
        for b in self.bullets:
            b.prev_x, b.prev_y = b.x, b.y
            travel = math.hypot(b.vx, b.vy)
            reach, wall_tile = tm.sweep_circle(b.x, b.y, b.vx / travel, b.vy / travel, travel, b.radius) if travel else (0.0, None)
            b.x += b.vx * reach / travel if travel else 0.0
            b.y += b.vy * reach / travel if travel else 0.0
            b.life -= 1
            # 월드 경계나 벽에 닿는 마지막 구간에서도 첫 대상만 타격한다.
            if self._bullet_hit(b):
                continue
            if wall_tile is not None:
                col, row = wall_tile
                if 0 <= row < tm.rows and 0 <= col < tm.cols and tm.tiles[row][col] == BREAKABLE:
                    tm.damage_tile(col, row, b.damage)
                continue
            if b.life > 0:
                alive.append(b)
        self.bullets = alive
        self.shapes = [s for s in self.shapes if s.hp > 0]

    def _bullet_hit(self, b: Bullet) -> bool:
        """모든 탄환은 이동 구간의 첫 대상만 타격하고 소멸한다."""
        by_player = b.team == "player"
        targets = self.enemies if by_player else (self.player,)
        hits = []
        sx, sy = (b.prev_x, b.prev_y) if b.prev_x is not None else (b.x, b.y)
        for target in list(targets) + self.shapes:
            if target.hp <= 0 or (isinstance(target, Tank) and not target.alive):
                continue
            fraction = _segment_circle_hit(sx, sy, b.x, b.y, target.x, target.y, target.radius + b.radius)
            if fraction is not None:
                hits.append((fraction, target))
        if not hits:
            return False
        fraction, target = min(hits, key=lambda item: (item[0], item[1].id))
        if b.blast_radius:
            self._explode(sx + (b.x - sx) * fraction, sy + (b.y - sy) * fraction,
                          b.damage, b.blast_radius, b.team)
        elif isinstance(target, Tank):
            self._damage_tank(target, b.damage, by_player)
        else:
            self._damage_shape(target, b.damage, by_player)
        return True

    def _damage_tank(self, t: Tank, dmg: float, by_player: bool):
        if t.team == "player":
            dmg *= SHIPS[t.job].damage_taken
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


def _segment_circle_hit(x0, y0, x1, y1, cx, cy, radius):
    dx, dy, ox, oy = x1 - x0, y1 - y0, x0 - cx, y0 - cy
    c = ox * ox + oy * oy - radius * radius
    if c <= 0:
        return 0.0
    a = dx * dx + dy * dy
    if a < 1e-12:
        return None
    b = 2 * (ox * dx + oy * dy)
    disc = b * b - 4 * a * c
    if disc < 0:
        return None
    fraction = (-b - math.sqrt(disc)) / (2 * a)
    return fraction if 0 <= fraction <= 1 else None


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
