---
title: EnemyController — 적의 성장과 행동
updated: 2026-10-20
tags: [space-z, class]
---

# EnemyController

## 역할과 접근 경로

적을 재등장시키고, 능력치를 계산하고, 매 프레임 감지·추적·조준·발사를 결정합니다. `game.enemy_controller`로 접근하며 [enemy_controller.py](../../../src/space_z/game/enemy_controller.py)에 구현되어 있습니다.

직접 가진 상태는 코어 참조와 공통 성장 단계뿐입니다. 적 목록은 `GameCore.enemies`, 적마다 다른 체력·직업·AI 기억은 각 `Tank`가 보관합니다.

## 찾아보기

- [[development/classes/EnemyController#공통 성장 상태|시간에 따른 성장]]
- [[development/classes/EnemyController#적 갱신|강화·진화에 대응하는 적 갱신]]
- [[development/classes/EnemyController#적별 AI 상태|시야·마지막 위치·경로]]
- [[development/classes/EnemyController#관련 함수|재등장과 행동 함수]]

## 공통 성장 상태

| 속성 | 의미와 단위 | 초기값 | 변경 함수 |
|---|---|---|---|
| `game` | 코어의 현재 월드·설정·담당 객체 참조 | 생성 인자 | `__init__()` |
| `enemy_scale_tier` | 경과 시간에 따른 공통 적 강화 단계 | `0` | `reset()`, `_update_enemy_scaling()` |

`_update_enemy_scaling()`은 `game.frame`, FPS, 성장 간격과 최대 단계 설정을 읽습니다. 단계가 바뀌거나 초반 완화 구간에 있으면 적들의 능력치를 다시 계산합니다. `_mercy_factor()`는 초반 완화 정도를 계산해 반환하며 상태를 저장하지 않습니다.

난수는 이 객체에 따로 두지 않고 `game.rng`를 사용합니다. 따라서 적 추첨·AI의 난수 소비 순서는 전투 재현성에 영향을 줍니다. `reset()` 자체는 성장 단계만 비우고 난수를 소비하지 않습니다.

## 적 갱신

플레이어 성장에 대응하는 두 경로를 구분합니다.

| 요청한 동작 | 호출 관계 | 바뀌는 적 상태 |
|---|---|---|
| 일반 스탯 강화 | `PlayerProgression.upgrade_stat()` → `_refresh_stats()` | 플레이어 스탯별 대응 비율을 합친 예산을 무작위 재배분; 능력치 재계산·남은 발사 대기 보정 |
| 우주선 진화 단계 변경 | `PlayerProgression.choose_reward()` → `_promote_enemies()` | 같은 진화 단계에서 적 종류 추첨; 능력치 갱신·점사 취소·발사 대기 보정·살아 있는 적 위치 보정 |

`_apply_enemy_strength(e)`는 시간별 성장, 초반 완화, 엘리트 여부, 우주선 종류와 적 스탯을 반영합니다. 최대 체력을 바꾸면서 기존 체력 비율을 유지하고, 반지름·피해·속도·발사 간격·탄속·수명을 갱신합니다.

적 스탯 예산은 플레이어의 `game.progression.stat_levels`에서 구하고, 무작위 분배 결과는 **적의 `e.stat_levels`**에 저장합니다. 두 딕셔너리는 별개입니다.

## 적별 AI 상태

[[development/classes/Tank#AI 기억과 이동 목표|Tank의 AI 속성 표]]에서 필드를 확인할 수 있습니다. `_enemy_ai(e)`는 다음 순서로 상태를 다룹니다.

1. 시야선·근거리 감지·발사 소리를 확인해 마지막 플레이어 위치를 기억합니다. 조건을 만족하면 근처 동료에게 위치를 전달합니다.
2. 반응 주기에 맞춰 플레이어, 마지막 위치, 천체 중 목표를 고릅니다. 필요하면 조준 오차·옆돌기 방향을 다시 추첨합니다.
3. 직접 이동할 수 있으면 적정 거리를 유지하거나 옆으로 돕니다. 막히면 지형의 A* 경로를 따라갑니다.
4. 예측 조준·각도 조건으로 발사 여부를 결정하고 코어의 이동 처리와 `Combat._fire()`에 요청합니다.

`ai_last_seen`은 마지막으로 확인하거나 전달받은 플레이어의 **월드 좌표**입니다. 현재 시야 여부와는 다릅니다. `ai_target`은 없을 수도 있고, 천체가 사라져 유효하지 않게 될 수도 있습니다. `_target_pos()`는 이런 상태를 확인해 좌표 또는 `None`을 반환합니다.

목표를 바로 향할 수 있을 때는 너무 멀면 접근, 너무 가까우면 후퇴, 적정 거리 안에서는 `ai_strafe` 방향으로 옆돌기를 합니다. 목표가 있어도 항상 그 좌표로 직진하는 구조는 아닙니다.

## 재등장

적이 죽으면 `Combat`이 `alive=False`와 `respawn_timer`를 설정합니다. 코어는 죽은 적의 타이머를 줄이다가 0이 되면 `_respawn_enemy(e)`를 호출합니다. 같은 `Tank`를 재사용하며 종류·엘리트·스탯·위치·체력·무장·주요 AI 상태를 준비합니다.

매번 새 `Tank`를 만드는 방식이 아니며, 모든 필드를 dataclass 기본값으로 되돌리는 것도 아닙니다. 실제로 재설정하는 필드는 코드의 `_respawn_enemy()`를 기준으로 읽습니다.

## 관련 함수

| 함수 | 조건·읽는 상태 | 변경·다른 객체 요청 | 반환 |
|---|---|---|---|
| `_update_enemy_scaling()` | 매 프레임, 시간·설정·현재 단계 | 공통 단계와 적 능력치 갱신 | `None` |
| `_mercy_factor()` | 초반 완화 계산 시 시간·설정 | 변경 없음 | 완화 비율 `float` |
| `_random_enemy_job()` | 재등장·진화 시 플레이어의 진화 단계 | 전투 난수 소비 | 우주선 종류 키 |
| `_enemy_stat_budget()` | 플레이어 스탯·난이도 대응 비율 | 변경 없음 | 정수 예산 |
| `_roll_enemy_stats(e)` | 예산에 맞춘 배분 시 | `e.stat_levels` 변경, 양수 예산이면 난수 소비 | `None` |
| `_apply_enemy_strength(e)` | 적 종류·현재 체력 비율·스탯·성장 설정 | 적 체력·반지름·무장·이동 배율 변경 | `None` |
| `_refresh_stats()` | 플레이어 일반 강화 성공 시 | 목록 순서대로 스탯 재추첨·능력치·발사 대기 갱신 | `None` |
| `_promote_enemies()` | 플레이어의 진화 단계 변경 시 | 적 종류·능력치·점사·발사 대기 변경, 코어에 위치 보정 요청 | `None` |
| `_respawn_enemy(e)` | 초기 생성 또는 재등장 타이머 완료 | 종류·스탯·생성 위치·생존·무장·AI 상태 준비 | `None` |
| `_target_pos(e)` | 현재 목표 종류·생존·마지막 위치·천체 목록 | 변경 없음 | 월드 좌표 쌍 또는 `None` |
| `_enemy_ai(e)` | 살아 있는 적의 매 프레임 처리 | AI 기억·목표·경로·조준 변경, 코어 이동·전투 발사 요청 | `None` |
| `reset()` | 코어의 새 판 초기화 | 공통 성장 단계 초기화 | `None` |

## 관련 동작과 객체

[[development/flows/upgrades-and-evolution|플레이어 성장에서 적 갱신까지]] · [[development/classes/Tank#AI 기억과 이동 목표|적별 AI 상태]] · [[development/classes/Combat#발사 상태|실제 발사]] · [[game/enemies-and-world|플레이 관점의 적과 월드]]

지형의 충돌·시야선·경로 탐색은 [terrain.py](../../../src/space_z/game/terrain.py)의 `TileMap`이 담당합니다. 경로를 보관하는 곳은 `Tank.ai_path`, 경로를 계산하는 곳은 `TileMap.astar()`입니다.

돌아가기: [[development/project-structure|전체 지도]]
