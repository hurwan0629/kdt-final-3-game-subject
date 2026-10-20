---
title: PlayerProgression — 점수와 성장
updated: 2026-10-20
tags: [space-z, class]
---

# PlayerProgression

## 역할과 접근 경로

점수·처치 수·레벨·강화·진화 선택을 관리합니다. `game.progression`으로 접근하며 [player_progression.py](../../../src/space_z/game/player_progression.py)에 구현되어 있습니다. 스탯·우주선·포신의 **정의**는 [progression_definitions.py](../../../src/space_z/config/progression_definitions.py), UI 배치·표시용 계산은 [progression_panel.py](../../../src/space_z/rendering/progression_panel.py)에 있습니다.

코어 생성 때 한 번 만들어지고 새 판마다 `reset(seed)`로 상태를 비웁니다. `Renderer`는 이 상태를 HUD로 읽고, `Combat`은 숙련 배율을, `EnemyController`는 적의 대응 스탯을 계산할 때 읽습니다.

## 찾아보기

- [[development/classes/PlayerProgression#점수와 레벨|점수·처치·경험치]]
- [[development/classes/PlayerProgression#일반 강화|포인트·스탯 단계·선택지]]
- [[development/classes/PlayerProgression#진화와 숙련|진화 대기·계열·숙련]]
- [[development/classes/PlayerProgression#관련 함수|상태 조회와 실제 적용]]

## 점수와 레벨

| 속성 | 의미 | 초기값 | 변경 함수 |
|---|---|---|---|
| `score` | 누적 게임 점수 | `0` | `reset()`, `_add_score()` |
| `kills` | 플레이어가 처치한 적 수 | `0` | `reset()`, `record_kill()` |
| `level` | 현재 플레이어 레벨 | `1` | `reset()`, `_add_score()` |
| `xp` | 현재 레벨에서 다음 레벨을 위해 쌓인 경험치 | `0` | `reset()`, `_add_score()` |

피해 처리 객체가 처치 시 `record_kill()`과 `_add_score(amount)`를 요청합니다. 점수는 성장 비활성화 상태에서도 증가합니다. `cfg.progression_enabled`가 꺼져 있으면 경험치·레벨 처리는 진행하지 않습니다.

`xp_to_next_level`은 저장 필드가 아닌 property입니다. `cfg.level_xp_base + (level - 1) * cfg.level_xp_growth`로 전체 필요 경험치를 계산합니다. `_add_score()`는 한 번에 여러 레벨을 올릴 수 있고, 레벨마다 필요량을 `xp`에서 차감합니다.

## 일반 강화

| 속성 | 의미 | 초기값 또는 기준 | 변경 함수 |
|---|---|---|---|
| `upgrade_points` | 사용하지 않은 일반 강화 포인트 | `0` | `_add_score()`가 지급, `upgrade_stat()`가 소비, `reset()` |
| `stat_levels` | 플레이어 스탯 키별 강화 단계 | `STAT_UPGRADES`의 키마다 `0` | `upgrade_stat()`, `reset()` |
| `stat_choices` | 표시할 일반 강화 항목 | `STAT_UPGRADES` | `open_stat_upgrades()`, `upgrade_stat()`, `reset()` |

10의 배수가 아닌 레벨업에서 포인트를 받습니다. `upgrade_stat(key)`는 유효한 키·남은 포인트·생존·종료 여부·최대 단계와 연사 제한을 검사합니다. 성공하면 플레이어의 해당 능력치를 변경하고 포인트 하나를 소비한 뒤 [[development/classes/EnemyController#적 갱신|적 스탯 재배분]]을 요청합니다.

`Tank.stat_levels`는 **적 개체에 배분한 스탯**입니다. 이곳의 플레이어 `stat_levels`와 다른 상태입니다. `open_stat_upgrades()`는 이름에 조회처럼 보이더라도 선택지 필드를 다시 설정합니다.

## 진화와 숙련

| 속성 | 의미 | 초기값 | 변경 함수 |
|---|---|---|---|
| `special_reward_levels` | 선택을 기다리는 10·20·30·그 이후 보상 레벨의 순서 | 빈 리스트 | `_add_score()`가 추가, `choose_reward()`가 앞 항목 소비, `reset()` |
| `reward_choices` | 현재 고를 수 있는 우주선·숙련 보상 | 빈 튜플 | `open_rewards()`, `choose_reward()`, `reset()` |
| `special_levels` | 우주선 키별 보상 선택 횟수 | `SHIPS`의 키마다 `0` | `choose_reward()`, `reset()` |
| `family` | 10레벨에서 정한 첫 진화 계열 | 빈 문자열 | `choose_reward()`, `reset()` |

`open_rewards()`는 10레벨의 첫 계열, 20·30레벨의 현재 우주선 자식, 그 이후 현재 우주선의 숙련 순으로 선택지를 준비합니다. 이미 선택지가 있으면 유지합니다. 큰 경험치로 여러 진화 레벨을 지나도 대기 목록을 앞에서부터 소비합니다.

`choose_reward(index)`는 플레이어의 `job`, 체력, 반지름, 발사 패턴 수, 발사 대기와 예약 점사를 바꿉니다. 코어에 진화 후 위치 보정을 요청하고, 실제 진화 단계가 달라진 경우 적의 진화 갱신도 요청합니다. 숙련의 실제 공격력 배율 계산은 `Combat.weapon_values()`가 맡습니다.

`pending_rewards`도 property입니다. `upgrade_points + len(special_reward_levels)`이며 별도 카운터로 저장하지 않습니다.

> [!info]- 보상 표시와 보조 속성
> | 속성 | 의미 | 초기값 또는 기준 | 변경 함수 |
> |---|---|---|---|
> | `game` | 현재 월드·설정·다른 담당 객체에 접근할 코어 | 생성 인자 | `__init__()` |
> | `reward_portrait` | 마지막 진화·숙련 보상의 우주선 키 | `None` | `choose_reward()`, `reset()`; 현재 직접 읽는 호출자는 없음 |
> | `last_reward` | 마지막 보상 알림 문구 | 빈 문자열 | `_reward_notice()`, `reset()` |
> | `reward_message_until` | 알림 표시 종료 게임 프레임 | `0` | `_reward_notice()`가 현재 프레임 + `cfg.fps * 3`으로 설정, `reset()` |
> | `reward_rng` | 전투 난수와 분리한 보상 난수 | `default_rng(seed)` | `reset()`; 현재 추첨에는 미사용 |
>
> 알림은 `Renderer`가 읽습니다. `Combat`도 엘리트 적 처치 회복 알림을 `_reward_notice()`로 요청할 수 있습니다.

## 관련 함수

| 함수 | 조건·읽는 상태 | 변경·다른 객체 요청 | 반환 |
|---|---|---|---|
| `_add_score(amount)` | 점수 획득 시 설정·현재 경험치 조회 | 점수 누적, 성장 활성화 시 레벨·포인트·진화 대기 갱신과 선택지 준비 | `None` |
| `record_kill()` | 플레이어의 적 처치 확정 | `kills` 증가 | `None` |
| `can_upgrade_stat(key)` | 키·포인트·생존·단계 조회 | 변경 없음 | `bool` |
| `upgrade_stat(key)` | 강화 가능 시 | 플레이어 능력치·강화 상태 변경, 적 `_refresh_stats()` 요청, 알림 준비 | 성공 `True`, 불가 `False` |
| `open_stat_upgrades()` | 강화 항목 준비 시 | `stat_choices` 설정 | 선택지 튜플 |
| `open_rewards()` | 생존하고 대기 보상이 있을 때 | 필요한 `reward_choices` 준비 | 현재 선택지 또는 빈 튜플 |
| `choose_reward(index)` | 대기 보상과 유효한 정수 인덱스 | 플레이어 진화·숙련, 코어 위치 보정, 필요 시 적 `_promote_enemies()` | 성공 `True`, 불가 `False` |
| `_reward_notice(title)` | 강화·진화·회복 알림 시 | 알림 문구·종료 시각 변경 | `None` |
| `reset(seed)` | 코어의 새 판 초기화 | 담당 상태 초기화, 전투 난수 소비 없음 | `None` |

## 관련 동작과 객체

[[development/flows/upgrades-and-evolution|강화에서 적 갱신까지]] · [[development/flows/damage-and-kills|점수를 받기 전 전투 과정]] · [[development/classes/Tank#체력 상태|강화가 바꾸는 선체 체력]] · [[development/classes/Combat#발사 상태|숙련을 실제 발사에 반영하는 곳]]

돌아가기: [[development/project-structure|전체 지도]]
