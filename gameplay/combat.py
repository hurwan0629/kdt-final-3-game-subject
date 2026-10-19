"""무장·탄환·피해·회복·충돌과 전투 연출 상태를 관리한다."""
import math
from typing import TYPE_CHECKING

from progression import SHIPS
from terrain import BREAKABLE
from .entities import Tank, Shape, Bullet, Explosion

if TYPE_CHECKING:
    from game_core import GameCore


# 스나이퍼 계열(단발 장거리): 포탄 그림을 쓰고, 다수 상대 약점을 보완하는 관통을 1회 받는다.
SNIPER_LINE_JOBS = ("sniper", "railgunner", "hyper_railgun", "hunter", "predator")
SNIPER_PIERCE = 1

SCORE_POPUP_FRAMES = 60   # 점수 연출을 기억하는 시간 (1초)


class Combat:
    """무장·탄환·피해·회복·충돌과 전투 연출 상태를 관리한다. 공통 월드는 game을 통해 조회한다."""

    def __init__(self, game: "GameCore"):
        """코어 참조를 보관한다. 이번 판의 상태는 reset()에서 초기화한다."""
        self.game = game  # 현재 월드·설정·프레임과 다른 담당 객체에 접근하는 코어

    def reset(self):
        """새 판의 담당 상태를 초기화한다. 전투 난수는 소비하지 않는다."""
        self.active_skill = None  # 이전 액티브 스킬 상태 (현재 미사용)
        self.skill_cooldown = 0  # 이전 액티브 스킬의 남은 대기 프레임 (현재 미사용)
        self.reload_frames_left = 0  # 플레이어 재장전 완료까지 남은 프레임
        self.dash_frames_left = 0  # 이전 돌진 동작의 남은 프레임 (현재 미사용)
        self.beams = []  # 수명이 남은 빔 연출 목록
        self.explosions = []  # 수명이 남은 폭발 연출 목록
        # 화면 연출용 기록이며 게임 규칙에는 쓰지 않는다.
        self.score_popups = []  # 획득 점수 연출 기록 (번호, 프레임, x, y, 점수, 종류)
        self._popup_id = 0  # 점수 연출의 고유 번호 발급용 카운터
        self.player_shot_frame = -10**9  # 적의 청각 감지에 쓰는 마지막 플레이어 발사 프레임
        self.bullets = []  # 현재 비행 중인 탄환 목록

    def _finish_frame(self):
        """프레임 증가 뒤 점수 연출과 재장전 완료를 처리한다.

        인자:
            없음(self.game은 현재 월드를 참조한다).

        처리:
            1) 표시 시간이 지난 점수 연출을 제거한다.
            2) 재장전 타이머를 줄이고 완료 시 살아 있는 플레이어의 탄창을 채운다.

        반환:
            None: 연출 목록·재장전 타이머·플레이어 탄약을 갱신한다.
        """
        # 1) 표시 시간이 지난 점수 연출을 제거한다.
        if self.score_popups and self.game.frame - self.score_popups[0][1] > SCORE_POPUP_FRAMES:
            self.score_popups = [pop for pop in self.score_popups if self.game.frame - pop[1] <= SCORE_POPUP_FRAMES]
        # 2) 재장전 완료는 프레임 증가 뒤, 플레이어 사망 판정 전에 처리한다.
        if self.reload_frames_left:
            self.reload_frames_left -= 1
            if self.reload_frames_left == 0 and self.game.player.hp > 0:
                self.game.player.ammo = self.game.player.max_ammo

    @property
    def reload_frames_total(self):
        """플레이어의 재장전 시간을 프레임 수로 계산한다.

        인자:
            없음(self는 현재 게임 상태를 참조한다).

        처리:
            기본 시간에 재장전 배율을 적용하고 최소 0.75초를 보장한 뒤 프레임 수를 올림한다.

        반환:
            int: 재장전 완료까지 필요한 전체 프레임 수.
        """
        return math.ceil(max(0.75, self.game.cfg.reload_seconds * self.game.player.reload_scale) * self.game.cfg.fps)

    def request_reload(self):
        """가능한 상태라면 플레이어 재장전을 시작한다.

        인자:
            없음(self는 현재 게임 상태를 참조한다).

        처리:
            1) 게임 종료·생존·탄약 제한·진행 중 재장전·탄창 잔량을 검사한다.
            2) 재장전 타이머를 시작하고 예약된 점사를 취소한다.

        반환:
            bool: 재장전을 시작하면 True, 시작할 수 없으면 False.
        """
        # 1) 게임 종료·생존·탄약 제한·진행 중 재장전·탄창 잔량을 검사한다.
        if (self.game.game_over or not self.game.player.alive or not self.game.cfg.limited_ammo
                or self.reload_frames_left or self.game.player.ammo >= self.game.player.max_ammo):
            return False
        # 2) 재장전 타이머를 시작하고 예약된 점사를 취소한다.
        self.reload_frames_left = self.reload_frames_total
        self.game.player.pending_shots.clear()
        return True

    def request_skill(self, move=0, aim_position=None):
        """제거된 액티브 스킬 호출을 받아 주는 호환용 API다.

        인자:
            move: 이전 호출 형식을 유지하기 위한 이동 번호. 현재는 사용하지 않는다.
            aim_position: 이전 호출 형식을 유지하기 위한 조준 월드 좌표. 현재는 사용하지 않는다.

        처리:
            게임 상태를 변경하지 않고 스킬 사용 실패를 알린다.

        반환:
            bool: 항상 False.
        """
        return False

    def _shot_delays(self, tank, spec):
        # 발사속도 강화는 연사 묶음 사이 대기뿐 아니라 묶음 안의 점사도 빠르게 한다.
        """우주선 점사 패턴의 지연을 실제 발사 간격에 맞게 환산한다.

        인자:
            tank: 점사를 발사할 Tank.
            spec: shots 발사 패턴을 가진 우주선 정의.

        처리:
            1) 플레이어는 강화된 발사 간격 비율을 구하고 적은 기본 배율 1.0을 사용한다.
            2) 각 고유 지연을 환산하되 서로 다른 지연은 최소 1프레임 간격을 유지한다.

        반환:
            dict[int, int]: 원래 지연을 실제 지연 프레임으로 대응한 사전. 0은 0으로 대응한다.
        """
        # 1) 플레이어는 강화된 발사 간격 비율을 구하고 적은 기본 배율 1.0을 사용한다.
        scale = tank.fire_cooldown_max / max(1, self.game.cfg.player_fire_cooldown) if tank.team == "player" else 1.0
        # 2) 각 고유 지연을 환산하되 서로 다른 지연은 최소 1프레임 간격을 유지한다.
        delays, previous = {0: 0}, 0
        for delay in sorted({shot.delay for shot in spec.shots if shot.delay}):
            previous = max(previous + 1, round(delay * scale))
            delays[delay] = previous
        return delays

    def weapon_values(self, tank: Tank):
        """선체 종류와 강화·숙련을 반영한 발사 능력치를 계산한다.

        인자:
            tank: 무기 능력치를 조회할 플레이어 또는 적 Tank.

        처리:
            1) 우주선 정의와 플레이어 숙련 배율을 읽고 기본 피해량을 계산한다.
            2) 점사가 끝나는 시점과 최소 간격을 반영해 쿨다운을 계산한다.
            3) 선체 배율을 반영한 탄속과 탄환 수명을 계산한다.

        반환:
            tuple: (우주선 정의, 피해량, 쿨다운 프레임, 탄속(px/frame), 수명 프레임). 개별 shot 배율은 발사 시 추가 적용한다.
        """
        # 1) 우주선 정의와 플레이어 숙련 배율을 읽고 기본 피해량을 계산한다.
        spec = SHIPS[tank.job]
        mastery = 1 + 0.2 * max(0, self.game.progression.special_levels.get(tank.job, 0) - 1) if tank.team == "player" else 1
        damage = self.game.cfg.bullet_damage * tank.damage_scale * spec.damage * mastery
        # 2) 점사가 끝나는 시점과 최소 간격을 반영해 쿨다운을 계산한다.
        burst_end = max(self._shot_delays(tank, spec).values())
        cooldown = max(2 if spec.cooldown < 1 else 4, burst_end, int(tank.fire_cooldown_max * spec.cooldown))
        # 3) 선체 배율을 반영한 탄속과 탄환 수명을 계산한다.
        return (spec, damage, cooldown, self.game.cfg.bullet_speed * tank.bullet_speed_scale * spec.speed,
                int(self.game.cfg.bullet_life * tank.bullet_life_scale * spec.life))

    def _emit_shot(self, tank, shot, damage, speed, life):
        """포신 위치와 개별 발사 패턴을 반영해 탄환 한 발을 생성한다.

        인자:
            tank: 발사 주체 Tank.
            shot: 포신 위치·각도·구경·탄속·피해·수명 배율을 담은 발사 패턴.
            damage: 개별 발사 배율 적용 전 피해량.
            speed: 개별 발사 배율 적용 전 탄속(px/frame).
            life: 개별 발사 배율 적용 전 수명(프레임).

        처리:
            1) 실제 선체 크기로 포신 축·포구 위치·탄환 반지름을 계산하고 벽 앞에서 포구를 제한한다.
            2) 발사 배율과 스나이퍼 관통 특성을 적용해 탄환을 만든다.
            3) 포신 축에서 이미 겹친 대상을 먼저 판정하고 소멸하지 않은 탄환만 목록에 추가한다.

        반환:
            None: 탄환 목록과 즉시 명중한 대상의 상태를 변경한다.
        """
        # 1) 실제 선체 크기로 포신 축·포구 위치·탄환 반지름을 계산하고 벽 앞에서 포구를 제한한다.
        angle = tank.angle + shot.angle
        ca, sa = math.cos(angle), math.sin(angle)
        forward, lateral = shot.forward * tank.radius, shot.lateral * tank.radius
        radius = tank.radius * shot.caliber
        base_x, base_y = tank.x - sa * lateral, tank.y + ca * lateral
        reach, wall = self.game.terrain.sweep_circle(base_x, base_y, ca, sa, forward, radius)
        # 포신이 벽과 겹쳐도 벽 뒤에서 탄이 생기지 않게 실제 포신 축을 따라 자른다.
        if wall is not None:
            reach = max(0.0, reach - 0.01)
        # 2) 발사 배율과 스나이퍼 관통 특성을 적용해 탄환을 만든다.
        is_sniper_line = tank.job in SNIPER_LINE_JOBS
        bullet = Bullet(
            base_x + ca * reach, base_y + sa * reach, ca * speed * shot.speed, sa * speed * shot.speed,
            max(1, int(life * shot.life)), tank.id, tank.team, damage * shot.damage, radius,
            kind="shell" if is_sniper_line else "plasma",
            pierce=SNIPER_PIERCE if is_sniper_line else 0)
        # 길어진 포신과 이미 겹친 작은 천체/적을 포구 뒤에 남겨 놓고 발사하지 않는다.
        # 3) 포신 축에서 이미 겹친 대상을 먼저 판정하고 소멸하지 않은 탄환만 목록에 추가한다.
        bullet.prev_x, bullet.prev_y = base_x, base_y
        if not self._bullet_hit(bullet):
            bullet.prev_x = bullet.prev_y = None
            self.bullets.append(bullet)

    def _tick_effects(self):
        """빔과 폭발 연출의 남은 시간을 한 프레임 갱신한다.

        인자:
            없음(self는 현재 게임 상태를 참조한다).

        처리:
            1) 각 연출의 수명을 1 줄인다.
            2) 수명이 끝난 연출을 해당 목록에서 제거한다.

        반환:
            None: beams와 explosions 목록을 제자리에서 갱신한다.
        """
        for effects in (self.beams, self.explosions):
            # 1) 각 연출의 수명을 1 줄인다.
            for effect in effects:
                effect.life -= 1
            # 2) 수명이 끝난 연출을 해당 목록에서 제거한다.
            effects[:] = [effect for effect in effects if effect.life > 0]

    def _explode(self, x, y, damage, radius, team):
        """폭발 연출을 추가하고 주변 개체와 파괴 가능한 벽에 피해를 준다.

        인자:
            x: 폭발 중심의 월드 가로 좌표(px).
            y: 폭발 중심의 월드 세로 좌표(px).
            damage: 폭발의 기준 피해량.
            radius: 폭발 반지름(px, 양수).
            team: 공격 진영. player면 적, 그 외에는 플레이어를 공격한다.

        처리:
            1) 폭발 연출을 등록하고 공격 대상 진영을 결정한다.
            2) 반경에 닿는 선체와 천체에 거리 감쇠 피해를 적용한다.
            3) 중심이 폭발 반경 안에 있는 파괴 가능 벽 타일에 기준 피해를 적용한다.

        반환:
            None: 연출·체력·벽·점수·이벤트 상태를 갱신한다.
        """
        # 1) 폭발 연출을 등록하고 공격 대상 진영을 결정한다.
        by_player = team == "player"
        self.explosions.append(Explosion(x, y, radius))
        targets = self.game.enemies if by_player else [self.game.player]
        # 2) 반경에 닿는 선체와 천체에 거리 감쇠 피해를 적용한다.
        for target in list(targets) + list(self.game.shapes):
            if isinstance(target, Tank) and not target.alive:
                continue
            distance = math.hypot(target.x - x, target.y - y)
            if distance <= radius + target.radius:
                dealt = damage * (0.4 + 0.6 * max(0.0, 1 - distance / radius))
                if isinstance(target, Tank):
                    self._damage_tank(target, dealt, by_player)
                else:
                    self._damage_shape(target, dealt, by_player)
        # 3) 중심이 폭발 반경 안에 있는 파괴 가능 벽 타일에 기준 피해를 적용한다.
        for col, row in list(self.game.terrain.hp):
            cx, cy = self.game.terrain.center(col, row)
            if math.hypot(cx - x, cy - y) <= radius:
                self.game.terrain.damage_tile(col, row, damage)

    def _fire(self, t: Tank, want_fire: bool):
        """예약 점사와 새 발사를 처리하고 탄약·발사 대기를 갱신한다.

        인자:
            t: 발사할 플레이어 또는 적 Tank.
            want_fire: 발사 조건이 맞을 때 새 발사 묶음을 시작할지 여부.

        처리:
            1) 사망·재장전 상태면 예약 점사를 취소하고, 아니면 발사 시점이 된 점사를 처리한다.
            2) 기존 발사 대기를 줄이고 새 발사 가능 여부와 탄약을 확인한다.
            3) 발사 패턴별로 즉시 탄환을 만들거나 점사를 예약하고 제한 탄약을 소비한다.
            4) 플레이어 발사 소리 시점과 다음 발사 대기를 기록한다.

        반환:
            None: 탄환·예약 점사·탄약·쿨다운·발사 소리 상태를 변경한다.
        """
        # 1) 사망·재장전 상태면 예약 점사를 취소하고, 아니면 발사 시점이 된 점사를 처리한다.
        player = t.team == "player"
        blocked = not t.alive or (player and self.reload_frames_left)
        if blocked:
            t.pending_shots.clear()
        else:
            # 방아쇠를 놓아도 시작한 점사는 마치되, 재장전/전직/죽음은 취소한다.
            due = [entry for entry in t.pending_shots if entry[0] <= self.game.frame]
            t.pending_shots[:] = [entry for entry in t.pending_shots if entry[0] > self.game.frame]
            for _, shot, damage, speed, life in due:
                if player and self.game.cfg.limited_ammo:
                    if t.ammo <= 0:
                        t.pending_shots.clear()
                        break
                    t.ammo -= 1
                self._emit_shot(t, shot, damage, speed, life)
        # 2) 기존 발사 대기를 줄이고 새 발사 가능 여부와 탄약을 확인한다.
        if t.cooldown > 0:
            t.cooldown -= 1
            return
        if blocked or not want_fire:
            return
        if player and self.game.cfg.limited_ammo and t.ammo <= 0:
            return
        # 3) 발사 패턴별로 즉시 탄환을 만들거나 점사를 예약하고 제한 탄약을 소비한다.
        spec, damage, cooldown, speed, life = self.weapon_values(t)
        delays = self._shot_delays(t, spec)
        for shot in spec.shots:
            if shot.delay:
                t.pending_shots.append((self.game.frame + delays[shot.delay], shot, damage, speed, life))
            else:
                if player and self.game.cfg.limited_ammo:
                    if t.ammo <= 0:
                        break
                    t.ammo -= 1
                self._emit_shot(t, shot, damage, speed, life)
        # 4) 플레이어 발사 소리 시점과 다음 발사 대기를 기록한다.
        if player:
            self.player_shot_frame = self.game.frame
        t.cooldown = cooldown

    def _move_bullets(self):
        """탄환의 한 프레임 이동과 충돌·수명 만료를 처리한다.

        인자:
            없음(self는 현재 게임 상태를 참조한다).

        처리:
            1) 이전 위치를 기록하고 첫 벽 접촉 지점까지 이동한 뒤 수명을 줄인다.
            2) 이동 구간에서 개체 명중을 먼저 처리하고 벽 충돌 시 파괴 가능 타일에 피해를 준다.
            3) 소멸하지 않은 탄환만 유지하고 체력이 0 이하인 천체를 제거한다.

        반환:
            None: 탄환·천체 목록과 피해·벽·이벤트 상태를 갱신한다.
        """
        tm = self.game.terrain
        alive = []
        for b in self.bullets:
            # 1) 이전 위치를 기록하고 첫 벽 접촉 지점까지 이동한 뒤 수명을 줄인다.
            b.prev_x, b.prev_y = b.x, b.y
            travel = math.hypot(b.vx, b.vy)
            reach, wall_tile = tm.sweep_circle(b.x, b.y, b.vx / travel, b.vy / travel, travel, b.radius) if travel else (0.0, None)
            b.x += b.vx * reach / travel if travel else 0.0
            b.y += b.vy * reach / travel if travel else 0.0
            b.life -= 1
            # 월드 경계나 벽에 닿는 마지막 구간에서도 첫 대상만 타격한다.
            # 2) 이동 구간에서 개체 명중을 먼저 처리하고 벽 충돌 시 파괴 가능 타일에 피해를 준다.
            if self._bullet_hit(b):
                continue
            if wall_tile is not None:
                col, row = wall_tile
                if 0 <= row < tm.rows and 0 <= col < tm.cols and tm.tiles[row][col] == BREAKABLE:
                    tm.damage_tile(col, row, b.damage)
                continue
            # 3) 소멸하지 않은 탄환만 유지하고 체력이 0 이하인 천체를 제거한다.
            if b.life > 0:
                alive.append(b)
        self.bullets = alive
        self.game.shapes = [s for s in self.game.shapes if s.hp > 0]

    def _bullet_hit(self, b: Bullet) -> bool:
        """탄환 이동 구간의 첫 대상에 피해를 주고 탄환 소멸 여부를 결정한다.

        인자:
            b: 이전·현재 위치, 공격 진영, 피해량, 관통 상태를 가진 Bullet.

        처리:
            1) 상대 진영과 천체 중 이미 맞힌 대상을 제외하고 이동 구간과의 교차를 조사한다.
            2) 가장 먼저 닿는 한 대상에 폭발 또는 직접 피해를 적용한다.
            3) 관통이 남으면 횟수를 차감하고 명중 대상을 기록해 탄환을 유지한다.

        반환:
            bool: 명중 후 탄환을 없애야 하면 True, 명중이 없거나 관통으로 유지하면 False.
        """
        # 1) 상대 진영과 천체 중 이미 맞힌 대상을 제외하고 이동 구간과의 교차를 조사한다.
        by_player = b.team == "player"
        targets = self.game.enemies if by_player else (self.game.player,)
        hits = []
        sx, sy = (b.prev_x, b.prev_y) if b.prev_x is not None else (b.x, b.y)
        for target in list(targets) + self.game.shapes:
            if (target.hp <= 0 or (isinstance(target, Tank) and not target.alive)
                    or target.id in b.hit_ids):
                continue
            fraction = _segment_circle_hit(sx, sy, b.x, b.y, target.x, target.y, target.radius + b.radius)
            if fraction is not None:
                hits.append((fraction, target))
        if not hits:
            return False
        # 2) 가장 먼저 닿는 한 대상에 폭발 또는 직접 피해를 적용한다.
        fraction, target = min(hits, key=lambda item: (item[0], item[1].id))
        if b.blast_radius:
            self._explode(sx + (b.x - sx) * fraction, sy + (b.y - sy) * fraction,
                          b.damage, b.blast_radius, b.team)
        elif isinstance(target, Tank):
            self._damage_tank(target, b.damage, by_player)
        else:
            self._damage_shape(target, b.damage, by_player)
        # 3) 관통이 남으면 횟수를 차감하고 명중 대상을 기록해 탄환을 유지한다.
        if b.pierce > 0:
            b.pierce -= 1
            b.hit_ids.add(target.id)
            return False
        return True

    def _damage_tank(self, t: Tank, dmg: float, by_player: bool):
        """선체 피해를 적용하고 피격·처치·엘리트 보상을 처리한다.

        인자:
            t: 피해를 받을 Tank.
            dmg: 선체별 피해 감소 배율 적용 전 피해량.
            by_player: 플레이어 공격으로 준 피해인지 여부.

        처리:
            1) 우주선의 받는 피해 배율을 적용하고 남은 체력만큼 피해를 제한한다.
            2) 체력·마지막 피격 시점과 진영별 피해 이벤트를 갱신한다.
            3) 적이 죽으면 재등장 타이머를 설정하고 플레이어 처치 시 점수·처치 수·엘리트 회복을 적용한다.

        반환:
            None: 선체와 이벤트·보상 상태를 변경한다. 플레이어 사망 확정은 step에서 처리한다.
        """
        # 1) 우주선의 받는 피해 배율을 적용하고 남은 체력만큼 피해를 제한한다.
        dmg *= SHIPS[t.job].damage_taken
        dealt = min(dmg, t.hp)
        if dealt <= 0:
            return
        # 2) 체력·마지막 피격 시점과 진영별 피해 이벤트를 갱신한다.
        t.hp -= dealt
        t.last_hit_frame = self.game.frame
        if t.team == "player":
            self.game.events["damage_taken"] += dealt
            return
        if by_player:
            self.game.events["enemy_damage"] += dealt
        # 3) 적이 죽으면 재등장 타이머를 설정하고 플레이어 처치 시 점수·처치 수·엘리트 회복을 적용한다.
        if t.hp <= 0:
            t.alive = False
            t.respawn_timer = self.game.cfg.enemy_ai.respawn_frames
            if by_player:
                self.game.events["enemies_killed"] += 1
                self.game.progression.record_kill()
                ai, p = self.game.cfg.enemy_ai, self.game.player
                if t.elite:
                    p.hp = min(p.max_hp, p.hp + p.max_hp * ai.elite_heal_ratio)
                    self.game.progression._reward_notice("엘리트 처치 보상 (체력 회복)")
                amount = round(self.game.cfg.enemy_kill_score * (ai.elite_score_scale if t.elite else 1))
                self._score_popup(t.x, t.y, amount, "elite" if t.elite else "enemy")
                self.game.progression._add_score(amount)

    def _score_popup(self, x, y, amount, kind):
        """획득 점수를 표시할 화면 연출 기록을 추가한다.

        인자:
            x: 연출을 띄울 월드 가로 좌표(px).
            y: 연출을 띄울 월드 세로 좌표(px).
            amount: 표시할 획득 점수.
            kind: 연출 종류(enemy, elite 또는 천체 종류 키).

        처리:
            1) 새 점수 연출 번호를 발급한다.
            2) 현재 프레임·위치·점수·종류를 연출 목록에 기록한다.

        반환:
            None: score_popups에 기록을 추가한다. 실제 점수는 변경하지 않는다.
        """
        # 1) 새 점수 연출 번호를 발급한다.
        self._popup_id += 1
        # 2) 현재 프레임·위치·점수·종류를 연출 목록에 기록한다.
        self.score_popups.append((self._popup_id, self.game.frame, x, y, amount, kind))

    def _damage_shape(self, s: Shape, dmg: float, by_player: bool):
        """천체 피해를 적용하고 플레이어 공격의 보상 이벤트를 기록한다.

        인자:
            s: 피해를 받을 Shape.
            dmg: 천체에 적용할 피해량.
            by_player: 플레이어 공격으로 준 피해인지 여부.

        처리:
            1) 피해량을 남은 체력으로 제한하고 천체 체력을 줄인다.
            2) 플레이어 공격이면 가중 피해를 기록하고 파괴 시 점수·파괴 수·점수 연출을 추가한다.

        반환:
            None: 천체 체력과 플레이어 이벤트·점수를 갱신한다. 천체 목록 제거는 호출 측에서 처리한다.
        """
        # 1) 피해량을 남은 체력으로 제한하고 천체 체력을 줄인다.
        dealt = min(dmg, s.hp)
        if dealt <= 0:
            return
        s.hp -= dealt
        # 2) 플레이어 공격이면 가중 피해를 기록하고 파괴 시 점수·파괴 수·점수 연출을 추가한다.
        if by_player:
            self.game.events["shape_damage_weighted"] += dealt * s.score / s.max_hp
            if s.hp <= 0:
                self.game.events["shape_destroyed_score"] += s.score
                self.game.events["shapes_destroyed"] += 1
                self._score_popup(s.x, s.y, s.score, s.kind)
                self.game.progression._add_score(s.score)

    def _collide_bodies(self):
        """선체와 천체의 몸체 충돌을 해결하고 접촉 피해를 적용한다.

        인자:
            없음(self는 현재 게임 상태를 참조한다).

        처리:
            1) 선체와 천체의 겹침을 해소하고 양쪽에 접촉 피해를 적용한다.
            2) 플레이어와 적은 겹침·상호 피해를 처리하고 적끼리는 겹침만 해소한다.
            3) 파괴된 천체를 제거하고 밀려난 개체의 벽·월드 경계 겹침을 보정한다.

        반환:
            None: 개체 위치·속도·체력, 천체 목록, 피해·보상 이벤트를 변경한다.
        """
        # 1) 선체와 천체의 겹침을 해소하고 양쪽에 접촉 피해를 적용한다.
        bd = self.game.cfg.body_damage
        tanks = [self.game.player] + [e for e in self.game.enemies if e.alive]
        for t in tanks:
            for s in self.game.shapes:
                r = t.radius + s.radius
                if (s.x - t.x) ** 2 + (s.y - t.y) ** 2 < r * r and s.hp > 0:
                    _push_apart(t, s, 0.3)
                    self._damage_shape(s, bd, by_player=(t.team == "player"))
                    self._damage_tank(t, bd, by_player=False)
        # 2) 플레이어와 적은 겹침·상호 피해를 처리하고 적끼리는 겹침만 해소한다.
        p = self.game.player
        for e in self.game.enemies:
            if e.alive and _overlap(p, e):
                _push_apart(p, e, 0.5)
                self._damage_tank(e, bd, by_player=True)
                self._damage_tank(p, bd, by_player=False)
        for i, a in enumerate(self.game.enemies):
            for b in self.game.enemies[i + 1:]:
                if a.alive and b.alive and _overlap(a, b):
                    _push_apart(a, b, 0.5)
        # 3) 파괴된 천체를 제거하고 밀려난 개체의 벽·월드 경계 겹침을 보정한다.
        self.game.shapes = [s for s in self.game.shapes if s.hp > 0]
        # 서로 밀어내다 벽에 들어간 경우 다시 밖으로. 부서진 벽의 좁은 홈에
        # 끼어 밀어내도 빠지지 않으면 가장 가까운 넓은 칸으로 옮긴다.
        for o in tanks + self.game.shapes:
            self.game.terrain.resolve_circle(o)
            self.game._clamp_to_arena(o)
            self.game._fit_tank(o)

    def _regen_player(self):
        """피격 후 대기 시간이 지난 플레이어의 체력을 회복한다.

        인자:
            없음(self는 현재 게임 상태를 참조한다).

        처리:
            1) 플레이어가 살아 있고 마지막 피격 후 회복 지연이 지났는지 확인한다.
            2) 최대 체력에 비례한 기본 회복량과 추가 회복량을 더하되 최대 체력을 넘지 않게 한다.

        반환:
            None: 회복 조건을 만족하면 플레이어 체력을 증가시킨다.
        """
        # 1) 플레이어가 살아 있고 마지막 피격 후 회복 지연이 지났는지 확인한다.
        p = self.game.player
        c = self.game.cfg
        if p.hp > 0 and self.game.frame - p.last_hit_frame >= c.regen_delay:
            # 체력(hull 스탯·전직 보너스 등)이 늘어난 만큼 회복량도 비례해서 커진다
            # (기준 체력 대비 같은 비율로 회복 → 최대 체력의 일정 %/초를 유지).
            # 2) 최대 체력에 비례한 기본 회복량과 추가 회복량을 더하되 최대 체력을 넘지 않게 한다.
            rate = c.regen_rate * (p.max_hp / c.player_hp)
            p.hp = min(p.max_hp, p.hp + rate + p.regen_bonus)


def _segment_circle_hit(x0, y0, x1, y1, cx, cy, radius):
    """선분이 원에 처음 닿는 위치를 선분 내 비율로 계산한다.

    인자:
        x0: 선분 시작점의 가로 좌표.
        y0: 선분 시작점의 세로 좌표.
        x1: 선분 끝점의 가로 좌표.
        y1: 선분 끝점의 세로 좌표.
        cx: 원 중심의 가로 좌표.
        cy: 원 중심의 세로 좌표.
        radius: 원 반지름. 탄환 충돌에서는 두 충돌 반지름의 합을 전달한다.

    처리:
        1) 시작점이 원 안이면 즉시 명중으로 처리하고 길이가 거의 0인 선분은 제외한다.
        2) 선분과 원의 교차 방정식을 풀어 첫 교차가 선분 범위 안에 있는지 검사한다.

    반환:
        float 또는 None: 시작점은 0.0, 끝점은 1.0인 첫 명중 비율. 교차하지 않으면 None.
    """
    # 1) 시작점이 원 안이면 즉시 명중으로 처리하고 길이가 거의 0인 선분은 제외한다.
    dx, dy, ox, oy = x1 - x0, y1 - y0, x0 - cx, y0 - cy
    c = ox * ox + oy * oy - radius * radius
    if c <= 0:
        return 0.0
    a = dx * dx + dy * dy
    if a < 1e-12:
        return None
    # 2) 선분과 원의 교차 방정식을 풀어 첫 교차가 선분 범위 안에 있는지 검사한다.
    b = 2 * (ox * dx + oy * dy)
    disc = b * b - 4 * a * c
    if disc < 0:
        return None
    fraction = (-b - math.sqrt(disc)) / (2 * a)
    return fraction if 0 <= fraction <= 1 else None

def _overlap(a, b) -> bool:
    """두 원형 개체가 서로 겹치는지 검사한다.

    인자:
        a: x·y·radius 속성을 가진 첫 개체.
        b: x·y·radius 속성을 가진 두 번째 개체.

    처리:
        중심 간 거리의 제곱과 반지름 합의 제곱을 비교한다.

    반환:
        bool: 내부가 겹치면 True, 떨어져 있거나 정확히 접하기만 하면 False.
    """
    r = a.radius + b.radius
    dx, dy = a.x - b.x, a.y - b.y
    return dx * dx + dy * dy < r * r

def _push_apart(a, b, a_share: float):
    """겹친 두 원형 개체를 비율에 따라 밀어내고 약한 반동을 준다.

    인자:
        a: 위치·반지름·속도를 가진 첫 개체.
        b: 위치·반지름·속도를 가진 두 번째 개체.
        a_share: 전체 보정 중 a의 이동·반동 비율(0~1). b는 나머지를 부담한다.

    처리:
        1) 중심 간 방향과 겹침량을 계산한다. 중심이 거의 같으면 임의의 가로 방향을 사용한다.
        2) 겹침량을 a_share와 나머지 비율로 나눠 두 개체 위치를 보정한다.
        3) 같은 방향·비율로 약한 반동 속도를 더한다. 호출자는 겹친 개체를 전달해야 한다.

    반환:
        None: 두 개체의 위치와 속도를 직접 변경한다.
    """
    # 1) 중심 간 방향과 겹침량을 계산한다. 중심이 거의 같으면 임의의 가로 방향을 사용한다.
    dx, dy = a.x - b.x, a.y - b.y
    d = math.hypot(dx, dy)
    if d < 1e-6:
        dx, dy, d = 1.0, 0.0, 1.0
    overlap = a.radius + b.radius - d
    nx, ny = dx / d, dy / d
    # 2) 겹침량을 a_share와 나머지 비율로 나눠 두 개체 위치를 보정한다.
    a.x += nx * overlap * a_share
    a.y += ny * overlap * a_share
    b.x -= nx * overlap * (1 - a_share)
    b.y -= ny * overlap * (1 - a_share)
    # 밀려나는 방향으로 약한 반동
    # 3) 같은 방향·비율로 약한 반동 속도를 더한다. 호출자는 겹친 개체를 전달해야 한다.
    a.vx += nx * 0.5 * a_share
    a.vy += ny * 0.5 * a_share
    b.vx -= nx * 0.5 * (1 - a_share)
    b.vy -= ny * 0.5 * (1 - a_share)
