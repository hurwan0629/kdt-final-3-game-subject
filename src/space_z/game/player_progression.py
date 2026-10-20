"""점수·레벨·강화·진화 상태와 적용 규칙을 관리한다."""
import math
from typing import TYPE_CHECKING, Literal

import numpy as np

from space_z.config.progression_definitions import STAT_UPGRADES, STAT_MAX_LEVEL, SHIPS, FAMILIES

if TYPE_CHECKING:
    from space_z.game.game_core import GameCore


class PlayerProgression:
    """점수·레벨·강화·진화 상태와 적용 규칙을 관리한다. 공통 월드는 game을 통해 조회한다."""

    def __init__(self, game: "GameCore"):
        """코어 참조를 보관한다. 이번 판의 상태는 reset()에서 초기화한다."""
        self.game = game  # 현재 월드·설정·프레임과 다른 담당 객체에 접근하는 코어

    def reset(self, seed=None):
        """새 판의 담당 상태를 초기화한다. 전투 난수는 소비하지 않는다."""
        # 카드 선택이 맵 생성과 전투 난수열을 바꾸지 않도록 분리한다.
        self.reward_rng = np.random.default_rng(seed)  # 보상 추첨용 별도 난수 생성기 (현재 미사용)
        self.score = 0  # 플레이어 누적 점수
        self.kills = 0  # 플레이어가 처치한 적 수
        self.level = 1  # 플레이어의 현재 레벨
        self.xp = 0  # 다음 레벨업을 위해 쌓인 경험치
        self.upgrade_points = 0  # 아직 사용하지 않은 일반 스탯 강화 포인트
        self.special_reward_levels = []  # 진화·숙련 보상을 아직 선택하지 않은 레벨 목록
        self.stat_levels = {card.key: 0 for card in STAT_UPGRADES}  # 스탯 키별 플레이어 강화 단계
        self.stat_choices = STAT_UPGRADES  # 화면에 표시할 스탯 강화 선택지
        self.special_levels = {key: 0 for key in SHIPS}  # 우주선 키별 보상 선택 횟수 (숙련 배율 계산용)
        self.family = ""  # 10레벨에 선택한 첫 진화 계열 키
        self.reward_portrait = None  # 마지막으로 선택한 진화·숙련 보상의 우주선 키
        self.reward_choices = ()  # 현재 선택을 기다리는 진화·숙련 보상 목록
        self.last_reward = ""  # 마지막으로 적용한 보상의 알림 문구
        self.reward_message_until = 0  # 보상 알림 표시를 끝낼 게임 프레임

    @property
    def xp_to_next_level(self):
        """현재 레벨에서 다음 레벨로 오르는 데 필요한 경험치를 계산한다.

        인자:
            없음(self는 현재 게임 상태를 참조한다).

        처리:
            기본 필요 경험치에 현재 레벨에 따른 증가량을 더한다.

        반환:
            int: 다음 레벨업의 전체 필요 경험치(남은 경험치가 아님).
        """
        return self.game.cfg.level_xp_base + (self.level - 1) * self.game.cfg.level_xp_growth

    @property
    def pending_rewards(self):
        """아직 사용하지 않은 강화·진화 보상의 총수를 계산한다.

        인자:
            없음(self는 현재 게임 상태를 참조한다).

        처리:
            일반 강화 포인트와 대기 중인 특수 보상 레벨 수를 합산한다.

        반환:
            int: 미사용 보상 수.
        """
        return self.upgrade_points + len(self.special_reward_levels)

    def record_kill(self):
        """플레이어의 적 처치 수를 1 늘린다. 반환값은 없다."""
        self.kills += 1

    def _add_score(self, amount):
        """점수를 누적하고 성장 설정에 따라 경험치·레벨·보상을 갱신한다.

        인자:
            amount: 추가할 점수. 성장 활성화 시 같은 양을 경험치에도 더한다.

        처리:
            1) 점수를 더하고 성장 비활성화 상태면 종료한다.
            2) 경험치를 더해 가능한 만큼 레벨업하고 10레벨마다 진화 보상, 나머지는 강화 포인트를 쌓는다.
            3) 진화 선택지와 스탯 강화 목록을 준비한다.

        반환:
            None: 점수와 성장 관련 상태를 갱신한다.
        """
        # 1) 점수를 더하고 성장 비활성화 상태면 종료한다.
        self.score += amount
        if not self.game.cfg.progression_enabled:
            return
        # 2) 경험치를 더해 가능한 만큼 레벨업하고 10레벨마다 진화 보상, 나머지는 강화 포인트를 쌓는다.
        self.xp += amount
        while self.xp >= self.xp_to_next_level:
            self.xp -= self.xp_to_next_level
            self.level += 1
            if self.level % 10 == 0:
                self.special_reward_levels.append(self.level)
            else:
                self.upgrade_points += 1
        # 3) 진화 선택지와 스탯 강화 목록을 준비한다.
        self.open_rewards()
        self.open_stat_upgrades()

    def open_rewards(self):
        """가장 먼저 대기 중인 진화 보상의 선택지를 준비한다.

        인자:
            없음(self는 현재 게임 상태를 참조한다).

        처리:
            1) 게임 종료·플레이어 생존·대기 보상을 확인하고 이미 열린 선택지는 재사용한다.
            2) 10레벨은 계열, 20·30레벨은 현재 종류의 다음 진화, 이후는 현재 종류의 숙련 보상을 준비한다.

        반환:
            tuple: 선택 가능한 계열 또는 우주선 정의. 보상을 열 수 없으면 빈 튜플.
        """
        # 1) 게임 종료·플레이어 생존·대기 보상을 확인하고 이미 열린 선택지는 재사용한다.
        if self.game.game_over or not self.game.player.alive or not self.special_reward_levels:
            return ()
        if self.reward_choices:
            return self.reward_choices
        # 2) 10레벨은 계열, 20·30레벨은 현재 종류의 다음 진화, 이후는 현재 종류의 숙련 보상을 준비한다.
        level = self.special_reward_levels[0]
        if level == 10:
            self.reward_choices = FAMILIES
        elif level in (20, 30):
            self.reward_choices = tuple(ship for ship in SHIPS.values()
                                        if ship.parent == self.game.player.job and ship.level == level)
        else:
            self.reward_choices = (SHIPS[self.game.player.job],)
        return self.reward_choices

    def choose_reward(self, index):
        """선택한 진화·숙련 보상을 적용하고 다음 보상을 준비한다.

        인자:
            index: 현재 reward_choices에서 고를 0부터 시작하는 정수 인덱스.

        처리:
            1) 플레이어 상태·대기 보상·인덱스를 검증한다.
            2) 선택한 종류의 체력·반지름·무장을 적용하고 실제 진화 시 적들도 진화시킨다.
            3) 보상을 소모하고 숙련 횟수·알림·초상화를 갱신한 뒤 다음 선택지를 준비한다.

        반환:
            bool: 적용에 성공하면 True, 선택할 수 없는 상태나 인덱스면 False.
        """
        # 1) 플레이어 상태·대기 보상·인덱스를 검증한다.
        if self.game.game_over or not self.game.player.alive or not self.reward_choices or not self.special_reward_levels:
            return False
        if not isinstance(index, int) or not 0 <= index < len(self.reward_choices):
            return False
        # 2) 선택한 종류의 체력·반지름·무장을 적용하고 실제 진화 시 적들도 진화시킨다.
        card = self.reward_choices[index]
        p = self.game.player
        level = self.special_reward_levels[0]
        previous = SHIPS[p.job]
        if level == 10:
            self.family = card.key
        hp_delta = card.hp_bonus - previous.hp_bonus
        p.max_hp += hp_delta
        p.hp = min(p.max_hp, p.hp + hp_delta)
        p.radius = self.game.cfg.tank_radius * card.radius_scale
        promoted = card.level != previous.level
        p.job = card.key
        p.projectiles = len(card.shots)
        p.cooldown = 0
        p.pending_shots.clear()
        self.game._fit_player_after_evolution()
        if promoted:
            self.game.enemy_controller._promote_enemies()
        # 3) 보상을 소모하고 숙련 횟수·알림·초상화를 갱신한 뒤 다음 선택지를 준비한다.
        self.special_levels[card.key] += 1
        self.special_reward_levels.pop(0)
        self.reward_choices = ()
        self.reward_portrait = card.key
        self._reward_notice(card.title if level <= 30 else f"{card.title} 숙련 +1")
        self.open_rewards()
        return True

    def open_stat_upgrades(self):
        # 숫자 1~5와 각 능력치 위치는 포인트 유무나 강화 한도와 관계없이 고정한다.
        """고정 순서의 스탯 강화 목록을 표시용으로 준비한다.

        인자:
            없음(self는 현재 게임 상태를 참조한다).

        처리:
            포인트 수나 강화 상한과 관계없이 전체 강화 정의를 고정 순서로 설정한다.

        반환:
            tuple: STAT_UPGRADES와 같은 강화 정의 목록. 선택 가능 여부는 별도로 검사한다.
        """
        self.stat_choices = STAT_UPGRADES
        return self.stat_choices

    def can_upgrade_stat(self, key):
        """지정한 스탯을 지금 강화할 수 있는지 확인한다.

        인자:
            key: 강화할 스탯 키(damage, rapid, speed, hull, range).

        처리:
            키·포인트·게임 종료·생존·스탯 상한·최소 발사 간격 조건을 함께 검사한다.

        반환:
            bool: 모든 강화 조건을 만족하면 True, 아니면 False.
        """
        return (key in self.stat_levels and self.upgrade_points > 0 and not self.game.game_over
                and self.game.player.alive and self.stat_levels[key] < STAT_MAX_LEVEL
                and not (key == "rapid" and self.game.player.fire_cooldown_max <= 4))

    def upgrade_stat(self, key):
        """강화 포인트 하나로 플레이어 스탯을 올리고 적의 대응 성장을 반영한다.

        인자:
            key: 강화할 스탯 키(damage, rapid, speed, hull, range).

        처리:
            1) 강화 가능 여부를 확인하고 해당 플레이어 능력치를 올린다.
            2) 포인트를 차감하고 스탯 레벨을 올린 뒤 적 스탯을 재배분해 능력치를 갱신한다.
            3) 강화 알림과 스탯 선택 목록을 갱신한다.

        반환:
            bool: 강화 성공 시 True, 강화할 수 없으면 False.
        """
        # 1) 강화 가능 여부를 확인하고 해당 플레이어 능력치를 올린다.
        if not self.can_upgrade_stat(key):
            return False
        p = self.game.player
        if key == "damage":
            p.damage_scale *= 1.25
        elif key == "rapid":
            old_cooldown = p.fire_cooldown_max
            p.fire_cooldown_max = max(4, round(p.fire_cooldown_max * 0.95))
            p.cooldown = math.ceil(p.cooldown * p.fire_cooldown_max / old_cooldown)
        elif key == "speed":
            p.accel_scale *= 1.07
        elif key == "hull":
            p.max_hp += 25
            p.hp = min(p.max_hp, p.hp + 25)
        elif key == "range":
            p.bullet_speed_scale *= 1.2
            p.bullet_life_scale *= 1.15
        # 2) 포인트를 차감하고 스탯 레벨을 올린 뒤 적 스탯을 재배분해 능력치를 갱신한다.
        self.upgrade_points -= 1
        self.stat_levels[key] += 1
        self.game.enemy_controller._refresh_stats()
        # 3) 강화 알림과 스탯 선택 목록을 갱신한다.
        self._reward_notice(next(card.title for card in STAT_UPGRADES if card.key == key))
        self.stat_choices = ()
        self.open_stat_upgrades()
        return True

    def _reward_notice(self, title):
        """보상 알림 내용과 표시 종료 프레임을 설정한다.

        인자:
            title: 화면에 표시할 보상 알림 문자열.

        처리:
            1) 화면에 보여 줄 알림 제목을 저장한다.
            2) 현재 프레임부터 3초 뒤를 표시 종료 시점으로 정한다.

        반환:
            None: last_reward와 reward_message_until을 갱신한다.
        """
        # 1) 화면에 보여 줄 알림 제목을 저장한다.
        self.last_reward = title
        # 2) 현재 프레임부터 3초 뒤를 표시 종료 시점으로 정한다.
        self.reward_message_until = self.game.frame + self.game.cfg.fps * 3
