---
title: Tank — 플레이어와 적의 개체 상태
updated: 2026-10-19
tags: [space-skirmish, class, entity]
---

# Tank

## 역할과 접근 경로

플레이어와 적 한 대의 상태를 묶는 dataclass입니다. 화면에서는 우주선으로 보이지만 코드 이름은 `Tank`입니다. `game.player` 또는 `game.enemies`의 원소로 접근합니다. 정의는 [gameplay/entities.py](../../../gameplay/entities.py)에 있습니다.

이 클래스에는 직접 구현한 전투·AI 메서드가 없습니다. 아래 표의 변경 함수는 주로 **다른 클래스의 함수**입니다. 기본값이 있는 필드도 생성·재등장 과정에서 설정이나 계산값으로 덮어쓸 수 있습니다.

## 찾아보기

- [[dev/classes/Tank#체력 상태|체력·생존·재등장]]
- [[dev/classes/Tank#위치와 이동|좌표·속도·각도·반지름]]
- [[dev/classes/Tank#무장과 탄약|발사 간격·탄약·예약 점사]]
- [[dev/classes/Tank#개체별 능력치|강화·진화 배율]]
- [[dev/classes/Tank#AI 기억과 이동 목표|적이 플레이어를 기억하는 방법]]

## 체력 상태

| 속성 | 의미와 단위 | 初기값 또는 기준 | 변경 함수 |
|---|---|---|---|
| `hp` | 현재 체력 | 플레이어는 `cfg.player_hp`; 적은 생성 후 능력치 계산 | `Combat._damage_tank()`·`_regen_player()`·엘리트 처치 회복, `Progression.upgrade_stat()`·`choose_reward()`, 적 능력치·재등장, 코어 사망 확정 |
| `max_hp` | 현재 최대 체력 | 플레이어 기본 설정 또는 적 능력치 계산 | `Progression.upgrade_stat()`·`choose_reward()`, `EnemyController._apply_enemy_strength()` |
| `alive` | 생존 여부 | 기본 `True` | 적 피해·재등장, 플레이어는 `GameCore.step()` 마지막 판정 |
| `last_hit_frame` | 마지막 피해를 받은 게임 프레임 | 기본 `-10**9` | `Combat._damage_tank()` |
| `respawn_timer` | 죽은 적의 재등장까지 남은 프레임 | 기본 `0` | 적 사망 시 `Combat._damage_tank()`, 감소는 `GameCore.step()` |

**`hp`가 저장되는 곳은 이 객체이고, 피해를 적용하는 곳은 [[dev/classes/Combat#피해 적용|Combat의 피해 적용]]입니다.** 적과 플레이어는 사망 확정 시점이 다르므로 [[dev/flows/피해와 적 처치|처치 흐름]]도 함께 확인합니다.

## 위치와 이동

| 속성 | 의미와 단위 | 초기값 또는 기준 | 변경 함수 |
|---|---|---|---|
| `id` | 이번 판의 선체·천체 공통 고유 번호 | `GameCore._new_id()` | 생성 시 지정; 적 재등장은 번호 유지 |
| `team` | 플레이어 또는 적 진영 | 생성 시 `player` / `enemy` | 생성 시 지정 |
| `x`, `y` | 선체 중심 월드 좌표, px; y는 아래가 양수 | 플레이어 맵 시작점 또는 적 생성 위치 | 코어 이동·위치 보정, 전투 몸체 충돌, 적 재등장 |
| `vx`, `vy` | 월드 가로·세로 속도, px/frame | 기본 각각 `0.0` | 코어 이동·경계 보정, 몸체 충돌, 적 재등장 |
| `angle` | 포신 방향, rad; 0은 오른쪽·시계방향 양수 | 기본 `0.0`, 코어 생성·적 재등장에서 추첨 | 코어 조준·이동 회전, 적 재등장 |
| `radius` | 충돌 반지름, px | `cfg.tank_radius` 기준, 종류별 배율 적용 | 플레이어 진화, 적 능력치 갱신 |

종류가 커지면 벽에 겹칠 수 있어 진화 뒤 코어에 위치 보정을 요청합니다. `EnemyController`는 이동 방향을 결정하고 실제 위치·속도 변경은 코어의 `_apply_tank_control()`에 요청합니다.

## 무장과 탄약

| 속성 | 의미와 단위 | 초기값 또는 기준 | 변경 함수 |
|---|---|---|---|
| `job` | 현재 우주선 종류 키 | 기본 `rookie`; 적은 종류 추첨 | `Progression.choose_reward()`, 적 재등장·진화 |
| `fire_cooldown_max` | 종류별 간격 배율 적용 전 기본 발사 대기, 프레임 | 플레이어 설정 또는 적 AI 설정·계산 | 일반 연사 강화, 적 능력치 계산 |
| `cooldown` | 새 발사 묶음까지 남은 대기, 프레임 | 기본 `0`; 적 재등장에서 기본 대기로 설정 | `Combat._fire()`, 강화·진화·적 갱신 |
| `projectiles` | 현재 종류의 발사 패턴 개수 표시 값 | 기본 `1` | 플레이어 진화, 적 능력치 갱신 |
| `ammo` | 플레이어 잔탄 | 기본 `0`, 플레이어 생성 시 `cfg.player_ammo` | `Combat._fire()`가 소비, `_finish_frame()`이 재장전 완료 시 채움 |
| `max_ammo` | 플레이어 탄창 용량 | 기본 `0`, 플레이어 생성 시 `cfg.player_ammo` | 현재 생성 시 지정 |
| `reload_scale` | 재장전 시간 배율 | 기본 `1.0` | 현재 일반 강화·진화는 변경하지 않음 |
| `pending_shots` | 예약 발사 목록 | 개체마다 새 빈 리스트 | 발사 예약·실행, 재장전, 진화·적 갱신, 플레이어 사망 때 취소 |

실제 패턴은 `ShipClass.shots`를 사용합니다. `projectiles` 숫자만큼 단순 반복하는 방식은 아닙니다. 탄약 제한이 켜져 있으면 실제 방출 탄환마다 하나를 소비합니다.

예약 한 항목의 형태는 `(발사할 게임 프레임: int, 패턴: ShotSpec, 피해: float, 탄속: float, 수명: int)`입니다. 탄속은 px/frame, 수명은 프레임입니다. 예를 들어 지연 3은 3초가 아니라 **3개 게임 프레임**입니다. 프레임은 메뉴에서 멈추며, 점사 수치는 [[dev/classes/Combat#발사 상태|Combat]]이 계산합니다.

## 개체별 능력치

| 속성 | 의미 | 초기값 | 변경 함수 |
|---|---|---|---|
| `damage_scale` | 기본 탄환 피해 배율 | `1.0` | 플레이어 피해 강화, 적 능력치 계산 |
| `accel_scale` | 이동 가속·속도 배율 | `1.0` | 플레이어 이동 강화, 적 능력치 계산 |
| `bullet_speed_scale` | 기본 탄속 배율 | `1.0` | 플레이어 사거리 강화, 적 능력치 계산 |
| `bullet_life_scale` | 기본 탄환 수명 배율 | `1.0` | 플레이어 사거리 강화, 적 능력치 계산 |
| `regen_bonus` | 프레임당 추가 플레이어 회복량 | `0.0` | 현재 일반 강화·진화는 변경하지 않음; 회복 시 조회 |
| `elite` | 엘리트 적 여부 | 기본 `False` | `EnemyController._respawn_enemy()` |
| `stat_levels` | 적 개체의 스탯 배분 단계 | 개체마다 새 빈 사전 | `EnemyController._roll_enemy_stats()` |

우주선 종류의 배율은 별도 콘텐츠 정의에 있습니다. 실제 발사 값은 `Combat.weapon_values()`가 개체 배율·종류 배율·플레이어 숙련을 합쳐 계산합니다. 플레이어의 강화 단계 사전은 이 필드가 아닌 `Progression.stat_levels`입니다.

## AI 기억과 이동 목표

아래 필드는 적의 `_enemy_ai()`·`_respawn_enemy()`가 다룹니다. 플레이어에도 같은 필드가 있으나 사람 입력을 결정하는 데 사용하지 않습니다.

| 속성 | 의미와 단위 | dataclass 기본값 | 변경 함수 |
|---|---|---|---|
| `ai_timer` | 목표·오차·옆돌기를 다시 정하기까지 남은 프레임 | `0` | 적 AI·재등장 |
| `ai_target` | `player`·`shape`·`point`와 식별 정보로 구성한 목표 | `None` | 적 AI·재등장 |
| `ai_can_see` | 이번 프레임 시야 조건에서 플레이어가 보이는지 | `False` | 적 AI·재등장 |
| `ai_last_seen` | 마지막으로 확인하거나 전달받은 플레이어 월드 좌표 | `None` | 자신의 AI·동료의 위치 공유·재등장 |
| `ai_last_seen_frame` | 마지막 위치를 확인·전달받은 게임 프레임 | `-10**9` | 자신의 AI·동료의 위치 공유 |
| `ai_path` | 앞으로 따라갈 타일 좌표 목록 | 개체마다 새 빈 리스트 | 적 AI·재등장 |
| `ai_path_timer` | 경로 재계산까지 남은 프레임 | `0` | 적 AI·재등장 |
| `ai_goal` | 디버그로 표시할 현재 이동 목표 월드 좌표 | `None` | 적 AI·재등장 |
| `ai_move` | 목표가 없을 때 사용할 이동 번호 | `0` | 적 AI |
| `ai_aim_offset` | 목표 방향에 더할 조준 오차, rad | `0.0` | 적 AI |
| `ai_strafe` | 옆돌기 방향, 1 또는 -1 | `1.0` | 적 AI |

`ai_target`이 없거나 이미 파괴된 천체를 가리킬 수도 있습니다. `ai_last_seen`이 있다는 것은 현재 보인다는 뜻이 아닙니다. 마지막 위치를 따라가는 행동과 현재 보이는 대상을 공격하는 행동을 구분합니다. 자세한 조건은 [[dev/classes/EnemyController#적별 AI 상태|적 행동 문서]]에 있습니다.

## 관련 함수와 읽는 객체

자체 업무 메서드는 없습니다. 생성자는 dataclass가 만들며, 상태 처리는 코어·전투·성장·적 처리에서 수행합니다. `Renderer`는 위치·종류·체력을, 학습 관찰은 위치·속도·체력·무장 등을 읽습니다.

[[dev/classes/GameCore#월드와 개체 목록|생성·목록 소유]] · [[dev/classes/Combat#피해 적용|피해·회복]] · [[dev/classes/Progression#일반 강화|강화]] · [[dev/classes/EnemyController#재등장|적 재등장]]

돌아가기: [[dev/01-structure|전체 지도]]
