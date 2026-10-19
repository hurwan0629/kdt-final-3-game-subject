"""적의 재등장·능력치·성장·감지·추적·조준을 관리한다."""
import math
from typing import TYPE_CHECKING

from progression import STAT_UPGRADES, SHIPS, SHIPS_BY_LEVEL
from .actions import N_MOVES, move_from_vector, wrap_angle
from .entities import Tank

if TYPE_CHECKING:
    from game_core import GameCore


class EnemyController:
    """적의 재등장·능력치·성장·감지·추적·조준을 관리한다. 공통 월드는 game을 통해 조회한다."""

    def __init__(self, game: "GameCore"):
        """코어 참조를 보관한다. 이번 판의 상태는 reset()에서 초기화한다."""
        self.game = game  # 현재 월드·설정·프레임과 다른 담당 객체에 접근하는 코어

    def reset(self):
        """새 판의 담당 상태를 초기화한다. 전투 난수는 소비하지 않는다."""
        self.enemy_scale_tier = 0  # 경과 시간에 따른 적 성장 단계

    def _respawn_enemy(self, e: Tank):
        """적의 종류·능력치를 다시 정하고 재등장 상태로 초기화한다.

        인자:
            e: 생성 또는 재등장시킬 적 Tank.

        처리:
            1) 플레이어 진화 단계에 맞는 종류·엘리트 여부·스탯을 추첨하고 능력치를 적용한다.
            2) 플레이어와 멀고 다른 적과 겹치지 않는 시작 위치를 우선 선택한다.
            3) 체력·속도·발사 대기·조준·AI 목표·경로를 초기화한다.

        반환:
            None: 전달받은 적 개체를 살아 있는 재등장 상태로 변경한다.
        """
        # 1) 플레이어 진화 단계에 맞는 종류·엘리트 여부·스탯을 추첨하고 능력치를 적용한다.
        tm = self.game.terrain
        p = self.game.player
        e.job = self._random_enemy_job()
        ai = self.game.cfg.enemy_ai
        mercy = self._mercy_factor()
        elite_chance = ai.elite_chance * (ai.mercy_elite_chance_scale + (1 - ai.mercy_elite_chance_scale) * mercy)
        e.elite = bool(self.game.rng.random() < elite_chance)
        self._roll_enemy_stats(e)
        self._apply_enemy_strength(e)
        # 맵의 E 위치 중 플레이어와 멀고 다른 적과 겹치지 않는 곳 우선 (화면 안이든 밖이든 상관없음).
        # 2) 플레이어와 멀고 다른 적과 겹치지 않는 시작 위치를 우선 선택한다.
        others = [o for o in getattr(self.game, "enemies", []) if o.alive and o is not e]
        starts = []
        for s in tm.enemy_starts:
            sx, sy = tm.center(*s)
            if not tm.circle_fits(sx, sy, e.radius):
                continue
            if (sx - p.x) ** 2 + (sy - p.y) ** 2 >= 300.0 ** 2 and \
                    all((sx - o.x) ** 2 + (sy - o.y) ** 2 >= (2 * e.radius) ** 2 for o in others):
                starts.append((sx, sy))
        if starts:
            e.x, e.y = starts[int(self.game.rng.integers(len(starts)))]
        else:
            e.x, e.y = self.game._random_free_pos(e.radius, 300.0)
        # 3) 체력·속도·발사 대기·조준·AI 목표·경로를 초기화한다.
        e.vx = e.vy = 0.0
        e.hp = e.max_hp
        e.alive = True
        e.cooldown = e.fire_cooldown_max
        e.pending_shots.clear()
        e.angle = float(self.game.rng.uniform(-math.pi, math.pi))
        e.ai_timer = 0
        e.ai_target = None
        e.ai_can_see = False
        e.ai_last_seen = None
        e.ai_path = []
        e.ai_path_timer = 0
        e.ai_goal = None

    def _random_enemy_job(self):
        """플레이어와 같은 진화 단계의 적 우주선 종류를 추첨한다.

        인자:
            없음(self는 현재 게임 상태를 참조한다).

        처리:
            1) 플레이어 우주선과 같은 진화 단계의 후보 목록을 조회한다.
            2) 후보 중 하나를 균등 확률로 추첨한다.

        반환:
            str: SHIPS에서 사용하는 우주선 종류 키.
        """
        # 1) 플레이어 우주선과 같은 진화 단계의 후보 목록을 조회한다.
        jobs = SHIPS_BY_LEVEL[SHIPS[self.game.player.job].level]
        # 2) 후보 중 하나를 균등 확률로 추첨한다.
        return jobs[int(self.game.rng.integers(len(jobs)))]

    def _mercy_factor(self):
        """초반 적 약화가 정상 난이도로 돌아오는 진행도를 계산한다.

        인자:
            없음(self는 현재 게임 상태를 참조한다).

        처리:
            현재 프레임과 약화 지속 시간으로 진행도를 계산한다. 지속 시간이 0 이하면 즉시 완료로 처리한다.

        반환:
            float: 시작 시 0.0, 약화 종료 후 1.0인 진행도.
        """
        ai = self.game.cfg.enemy_ai
        if ai.mercy_seconds <= 0:
            return 1.0
        return min(1.0, self.game.frame / (ai.mercy_seconds * self.game.cfg.fps))

    def _enemy_stat_budget(self):
        """플레이어 스탯 투자량을 기준으로 적의 강화 포인트 총량을 계산한다.

        인자:
            없음(self는 현재 게임 상태를 참조한다).

        처리:
            플레이어의 각 스탯 레벨에 반영 비율을 곱하고 항목별 정수 절삭값을 합산한다.

        반환:
            int: 적 한 개체에 배분할 스탯 포인트 수.
        """
        ratio = self.game.cfg.enemy_ai.stat_mirror_ratio
        return sum(int(self.game.progression.stat_levels.get(card.key, 0) * ratio) for card in STAT_UPGRADES)

    def _roll_enemy_stats(self, e: Tank):
        """적 강화 포인트를 스탯 항목에 무작위로 배분한다.

        인자:
            e: 스탯 배분을 갱신할 적 Tank.

        처리:
            1) 강화 항목과 포인트 총량을 구한다.
            2) 포인트가 없으면 모든 항목을 0으로 두고, 있으면 균등 확률의 다항분포로 배분한다.

        반환:
            None: e.stat_levels를 새 배분 결과로 교체한다.
        """
        # 1) 강화 항목과 포인트 총량을 구한다.
        keys = [card.key for card in STAT_UPGRADES]
        budget = self._enemy_stat_budget()
        # 2) 포인트가 없으면 모든 항목을 0으로 두고, 있으면 균등 확률의 다항분포로 배분한다.
        if budget <= 0:
            e.stat_levels = dict.fromkeys(keys, 0)
            return
        counts = self.game.rng.multinomial(budget, [1.0 / len(keys)] * len(keys))
        e.stat_levels = {key: int(n) for key, n in zip(keys, counts)}

    def _apply_enemy_strength(self, e: Tank):
        """성장 단계·초반 약화·엘리트·우주선·스탯을 합쳐 적 능력치를 갱신한다.

        인자:
            e: 능력치를 갱신할 적 Tank.

        처리:
            1) 성장 배율과 초반 약화·엘리트 배율, 기존 체력 비율을 계산한다.
            2) 스탯 배분이 없으면 추첨하고 항목별 레벨을 읽는다.
            3) 최대 체력·반지름·공격력·연사·이동·탄환 능력치를 갱신하되 현재 체력 비율은 유지한다.

        반환:
            None: 전달받은 적의 전투 능력치를 직접 변경한다.
        """
        # 1) 성장 배율과 초반 약화·엘리트 배율, 기존 체력 비율을 계산한다.
        c, ai, spec = self.game.cfg, self.game.cfg.enemy_ai, SHIPS[e.job]
        tier = self.enemy_scale_tier
        mercy = self._mercy_factor()
        hp_mercy = ai.mercy_hp_scale + (1 - ai.mercy_hp_scale) * mercy
        damage_mercy = ai.mercy_damage_scale + (1 - ai.mercy_damage_scale) * mercy
        fire_rate_mercy = ai.mercy_fire_rate_scale + (1 - ai.mercy_fire_rate_scale) * mercy
        ratio = e.hp / e.max_hp if e.max_hp > 0 else 1.0
        # 대형 선체의 체력 보너스는 플레이어의 절반만 받는다.
        elite_hp, elite_damage = (ai.elite_hp_scale, ai.elite_damage_scale) if e.elite else (1.0, 1.0)
        # 플레이어의 upgrade_stat()과 같은 배율을 적용한다(hull은 +25, 나머지는 레벨당 배율).
        # 어느 항목에 얼마나 찍혔는지는 개체마다 무작위로 다르다(_roll_enemy_stats).
        # 2) 스탯 배분이 없으면 추첨하고 항목별 레벨을 읽는다.
        if not e.stat_levels:
            self._roll_enemy_stats(e)
        levels = e.stat_levels
        hull_lv = levels.get("hull", 0)
        damage_lv = levels.get("damage", 0)
        rapid_lv = levels.get("rapid", 0)
        speed_lv = levels.get("speed", 0)
        range_lv = levels.get("range", 0)
        # 3) 최대 체력·반지름·공격력·연사·이동·탄환 능력치를 갱신하되 현재 체력 비율은 유지한다.
        e.max_hp = ((c.enemy_hp + spec.hp_bonus * 0.5 + 25 * hull_lv)
                    * (1 + ai.hp_growth * tier) * elite_hp * hp_mercy)
        e.hp = e.max_hp * ratio
        e.radius = c.tank_radius * spec.radius_scale
        e.damage_scale = (1 + ai.damage_growth * tier) * elite_damage * damage_mercy * (1.25 ** damage_lv)
        rapid_factor = (1 + ai.fire_rate_growth * tier) * fire_rate_mercy * ((1 / 0.95) ** rapid_lv)
        e.fire_cooldown_max = max(ai.min_fire_cooldown, round(ai.fire_cooldown / rapid_factor))
        e.accel_scale = (1 + ai.speed_growth * tier) * (1.07 ** speed_lv)
        e.bullet_speed_scale = 1.2 ** range_lv
        e.bullet_life_scale = 1.15 ** range_lv
        e.projectiles = len(spec.shots)

    def _refresh_stats(self):
        """플레이어 강화에 맞춰 적 스탯을 재배분하고 능력치를 갱신한다.

        인자:
            없음(self.game은 현재 적 목록과 플레이어 강화 상태를 참조한다).

        처리:
            1) 적 목록 순서대로 스탯을 추첨하고 능력치를 다시 적용한다.
            2) 기존 발사 대기가 새 기본 발사 대기를 넘지 않도록 보정한다.

        반환:
            None: 적별 스탯·능력치·발사 대기를 갱신한다.
        """
        for e in self.game.enemies:
            # 1) 늘어난 포인트 총량을 다시 무작위로 재배분한다.
            self._roll_enemy_stats(e)
            self._apply_enemy_strength(e)
            # 2) 새 발사 대기에 맞춰 남은 대기를 보정한다.
            e.cooldown = min(e.cooldown, e.fire_cooldown_max)

    def _update_enemy_scaling(self):
        """경과 시간에 맞춰 적 성장 단계와 능력치를 갱신한다.

        인자:
            없음(self는 현재 게임 상태를 참조한다).

        처리:
            1) 현재 프레임으로 성장 단계를 계산하고 상한을 적용한다.
            2) 단계가 바뀌었거나 초반 약화 기간이면 모든 적의 능력치를 다시 적용한다.

        반환:
            None: 성장 단계와 필요한 적 능력치를 갱신한다.
        """
        # 1) 현재 프레임으로 성장 단계를 계산하고 상한을 적용한다.
        ai = self.game.cfg.enemy_ai
        tier = min(ai.max_scale_tier, int(self.game.frame / (ai.scale_interval_seconds * self.game.cfg.fps)))
        tier_changed = tier != self.enemy_scale_tier
        if tier_changed:
            self.enemy_scale_tier = tier
        # 2) 단계가 바뀌었거나 초반 약화 기간이면 모든 적의 능력치를 다시 적용한다.
        if tier_changed or self.game.frame <= ai.mercy_seconds * self.game.cfg.fps:
            for e in self.game.enemies:
                self._apply_enemy_strength(e)

    def _promote_enemies(self):
        """플레이어 진화에 맞춰 모든 적을 같은 단계의 우주선으로 진화시킨다.

        인자:
            없음(self는 현재 게임 상태를 참조한다).

        처리:
            1) 적마다 새 종류를 추첨하고 능력치를 다시 계산한다.
            2) 예약 점사를 취소하고 발사 대기를 제한하며 살아 있는 적의 지형 겹침을 보정한다.

        반환:
            None: 모든 적의 종류·능력치·발사 상태와 필요한 위치를 변경한다.
        """
        for e in self.game.enemies:
            # 1) 적마다 새 종류를 추첨하고 능력치를 다시 계산한다.
            e.job = self._random_enemy_job()
            self._apply_enemy_strength(e)
            # 2) 예약 점사를 취소하고 발사 대기를 제한하며 살아 있는 적의 지형 겹침을 보정한다.
            e.pending_shots.clear()
            e.cooldown = min(e.cooldown, e.fire_cooldown_max)
            if e.alive:
                self.game._fit_tank(e)

    def _enemy_ai(self, e: Tank):
        """적 하나의 감지·목표 선택·추적 이동·조준·발사를 처리한다.

        인자:
            e: 이번 프레임 행동을 결정할 살아 있는 적 Tank.

        처리:
            1) 시야·근거리 감지·발사 소리로 플레이어 위치를 기억하고 조건에 따라 동료에게 공유한다.
            2) 반응 주기에 맞춰 플레이어·마지막 위치·천체 중 목표와 조준 오차를 정한다.
            3) 직접 접근 가능한 경우 거리를 유지하고, 막히면 A* 경로를 따라 이동 방향을 정한다.
            4) 예측 조준과 발사 각도 조건을 계산해 이동·회전·발사를 실행한다.

        반환:
            None: 적과 동료의 AI 상태, 적 위치·무장 상태, 발사 탄환을 갱신한다.
        """
        c = self.game.cfg
        ai = c.enemy_ai
        p = self.game.player
        tm = self.game.terrain

        # 1) 감지: 시야선이 트였으면 멀리서도 보고, 가까우면 벽 너머도 알아채고,
        #    플레이어가 쏘면 소리로 위치를 안다. 알게 된 위치는 항상 기억한다.
        dist = math.hypot(p.x - e.x, p.y - e.y)
        e.ai_can_see = p.alive and dist <= ai.sight_range and tm.line_of_sight(e.x, e.y, p.x, p.y)
        heard = self.game.frame - self.game.combat.player_shot_frame <= ai.hearing_frames and dist <= ai.hearing_range
        sensed = p.alive and (dist <= ai.sense_range or heard)
        knew = e.ai_last_seen is not None
        if e.ai_can_see or sensed:
            e.ai_last_seen = (p.x, p.y)
            e.ai_last_seen_frame = self.game.frame
        elif knew and self.game.frame - e.ai_last_seen_frame > ai.memory_frames:
            # 벽을 돌아 마지막 위치로 가는 중이면 도착할 때까지 잊지 않는다 (도착하면 포기).
            following = e.ai_target is not None and e.ai_target[0] == "point" and e.ai_path
            if not following:
                e.ai_last_seen = None
        # 본 적이 근처 동료에게 위치를 알린다. 초반에는 혼자 싸우고 일정 시간 뒤부터 부른다.
        if e.ai_can_see and self.game.frame >= ai.alert_start_seconds * c.fps:
            for ally in self.game.enemies:
                if (ally is not e and ally.alive and not ally.ai_can_see
                        and math.hypot(ally.x - e.x, ally.y - e.y) <= ai.alert_range):
                    ally.ai_last_seen = (p.x, p.y)
                    ally.ai_last_seen_frame = self.game.frame
        # 플레이어를 새로 알아챘거나 눈앞에 보이는데 다른 걸 쫓고 있으면 바로 목표를 바꾼다.
        hunting = e.ai_target is not None and e.ai_target[0] in ("player", "point")
        if (e.ai_last_seen is not None and not hunting) or (e.ai_can_see and (e.ai_target or ("",))[0] != "player"):
            e.ai_timer = 0

        # 2) 목표 선택 (reaction_frames마다): 플레이어를 알고 있으면 무조건 사냥, 모를 때만 천체를 깬다
        e.ai_timer -= 1
        if e.ai_timer <= 0:
            e.ai_timer = ai.reaction_frames
            if e.ai_can_see:
                target = ("player", p.id)
            elif e.ai_last_seen is not None:
                target = ("point", e.ai_last_seen)
            else:
                target, best_d = None, float("inf")
                for s in self.game.shapes:
                    d = math.hypot(s.x - e.x, s.y - e.y)
                    if d < best_d:
                        target, best_d = ("shape", s.id), d
            if target != e.ai_target:
                e.ai_path_timer = 0          # 목표가 바뀌면 경로 즉시 재계산
            e.ai_target = target
            noise = ai.aim_noise_deg * max(0.4, 1 - ai.aim_noise_decay * self.enemy_scale_tier)
            e.ai_aim_offset = float(self.game.rng.normal(0.0, math.radians(noise)))
            e.ai_strafe = 1.0 if self.game.rng.random() < 0.5 else -1.0
            if target is None:
                e.ai_move = int(self.game.rng.integers(0, N_MOVES))

        tgt = self._target_pos(e)
        if tgt is None and e.ai_target is not None and e.ai_target[0] != "player":
            # 쫓던 천체가 (다른 적에게) 부서져 사라졌을 수 있다. 다음 반응 주기까지
            # 기다리지 않고 바로 새 목표를 고르게 해서 구석에 계속 머무르지 않게 한다.
            e.ai_target = None
            e.ai_path = []
            e.ai_timer = 0

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
            aim_x, aim_y = tgt
            if e.ai_target[0] == "player" and e.ai_can_see and ai.lead_aim:
                # 탄이 날아가는 동안 플레이어가 움직일 위치를 예측해 쏜다.
                speed = self.game.combat.weapon_values(e)[3] * SHIPS[e.job].shots[0].speed
                lead = min(60.0, math.hypot(p.x - e.x, p.y - e.y) / max(1e-6, speed)) * ai.lead_aim
                aim_x, aim_y = p.x + p.vx * lead, p.y + p.vy * lead
            desired = math.atan2(aim_y - e.y, aim_x - e.x) + e.ai_aim_offset
            diff = wrap_angle(desired - e.angle)
            step = c.turn_speed * ai.turn_speed_scale
            if diff > step:
                rot = 2
            elif diff < -step:
                rot = 1
            aligned = abs(diff) <= math.radians(ai.fire_angle_tol_deg)
        kind = e.ai_target[0] if e.ai_target else None
        can_fire = (kind == "player" and e.ai_can_see) or (kind == "shape" and direct)

        self.game._apply_tank_control(e, move, rot, ai.move_speed_scale * e.accel_scale, ai.turn_speed_scale)
        self.game.combat._fire(e, aligned and can_fire)

    def _target_pos(self, e: Tank):
        """적 AI가 현재 추적해야 할 목표 좌표를 조회한다.

        인자:
            e: 목표 정보와 마지막 플레이어 위치를 가진 적 Tank.

        처리:
            1) 목표가 없거나 사라졌는지 확인한다.
            2) 목표 종류에 따라 보이는 플레이어·기억한 위치·지정 지점·천체의 좌표를 선택한다.

        반환:
            tuple[float, float] 또는 None: 목표 월드 좌표(x, y). 유효한 목표 위치가 없으면 None.
        """
        # 1) 목표가 없거나 사라졌는지 확인한다.
        t = e.ai_target
        if t is None:
            return None
        # 2) 목표 종류에 따라 보이는 플레이어·기억한 위치·지정 지점·천체의 좌표를 선택한다.
        kind, val = t
        if kind == "player":
            if not self.game.player.alive:
                return None
            return (self.game.player.x, self.game.player.y) if e.ai_can_see else e.ai_last_seen
        if kind == "point":
            return e.ai_last_seen or val
        for s in self.game.shapes:
            if s.id == val:
                return (s.x, s.y)
        return None
