---
title: GameCore — 월드와 실행 순서
updated: 2026-10-20
tags: [space-z, class]
---

# GameCore

## 역할과 접근 경로

이번 판의 공통 월드를 보관하고 **한 프레임에 무엇을 어떤 순서로 처리할지** 정합니다. 성장·전투·적 행동은 연결된 담당 객체에 요청합니다. Pygame에 의존하지 않아 사람 플레이와 학습 환경이 함께 사용할 수 있습니다.

[game_core.py](../../../src/space_z/game/game_core.py)의 `GameCore(config, seed)`로 생성하며, 앱에서는 `app.game`, 학습에서는 `env.game`으로 접근합니다.

## 찾아보기

- [[development/classes/GameCore#담당 객체와 설정|성장·전투·적 객체의 연결]]
- [[development/classes/GameCore#월드와 개체 목록|플레이어·적·천체·지형]]
- [[development/classes/GameCore#시간과 전투 이벤트|프레임·종료·이벤트]]
- [[development/classes/GameCore#한 프레임의 순서|step의 실행 순서]]
- [[development/classes/GameCore#새 판 초기화|reset의 생명 주기]]

## 담당 객체와 설정

| 속성 | 의미 | 초기값 또는 기준 | 변경 함수 |
|---|---|---|---|
| `cfg` | 공통 게임 설정 | 생성 인자, 없으면 `GameConfig()` | `__init__()`; 공유 객체 내부는 앱·렌더러에서도 변경 |
| `progression` | 점수·성장 담당 객체 | `PlayerProgression(self)` | `__init__()`에서 한 번 생성 |
| `combat` | 전투 담당 객체 | `Combat(self)` | `__init__()`에서 한 번 생성 |
| `enemy_controller` | 적 생애·행동 담당 객체 | `EnemyController(self)` | `__init__()`에서 한 번 생성 |

세 담당 객체는 `game`으로 이 코어를 참조합니다. 별도의 플레이어·지형 참조를 저장하지 않아 새 판에서도 현재 월드를 조회합니다. 코어 타입 import는 `TYPE_CHECKING`에서만 수행합니다. 이 구조는 상속 대신 객체 조합으로 책임을 나눈 것입니다.

## 월드와 개체 목록

| 속성 | 의미 | 초기값 또는 기준 | 변경 함수 |
|---|---|---|---|
| `terrain` | 현재 타일 맵 | `_make_terrain()`의 결과 | `reset()`에서 교체; 타일 변경은 `TileMap` |
| `player` | 플레이어 `Tank` | 맵 시작 위치, `cfg.player_hp`·반지름·무장 설정 | `reset()`에서 교체; 필드 변경자는 [[development/classes/Tank\|Tank]] 참조 |
| `enemies` | 적 `Tank` 목록 | 빈 목록을 만든 뒤 `cfg.num_enemies`만큼 생성 | `reset()`; 개별 적 재등장·성장은 `EnemyController` |
| `shapes` | 천체 `Shape` 목록 | 빈 목록을 만든 뒤 `cfg.num_shapes`만큼 생성 | `reset()`, `step()`의 보충, `Combat`의 파괴된 천체 제거 |

설정의 기본 체력과 실제 개체의 최대 체력은 다릅니다. `cfg.player_hp`는 생성 기준이고 `player.max_hp`는 강화·진화가 적용된 현재 값입니다. 목록을 코어가 보관해도, 원소의 체력이나 목록 제거까지 전부 코어가 직접 처리하지는 않습니다.

## 시간과 전투 이벤트

| 속성 | 의미와 단위 | 초기값 | 변경 함수 |
|---|---|---|---|
| `frame` | 이번 판에 처리한 게임 프레임 수 | `0` | `reset()`, 진행 중 `step()` 끝부분에서 증가 |
| `game_over` | 플레이어 사망으로 판이 끝났는지 | `False` | `reset()`, `step()`의 마지막 사망 판정 |
| `events` | 플레이어 관점의 전투 결과 누적 | `empty_events()` | 피해·처치는 `Combat`, 사망은 `step()`, 소비·교체는 `pop_events()` |

이벤트에는 천체 가중 피해·파괴 점수·파괴 수, 적 피해·처치 수, 플레이어 피격 피해·사망 여부가 들어갑니다. `pop_events()`는 현재 딕셔너리를 반환한 뒤 새 빈 딕셔너리로 교체합니다. 학습 환경은 이를 보상으로 변환하고 사람 플레이는 업데이트 후 소비합니다. 코어 자체가 학습 보상을 계산하지는 않습니다.

> [!info]- 난수와 개체 번호
> | 속성 | 의미 | 초기값 또는 기준 | 변경 함수 |
> |---|---|---|---|
> | `rng` | 맵 생성·전투·적 스탯용 난수 생성기 | `default_rng(seed)` | `reset()`에서 교체; 생성·추첨·AI에서 소비 |
> | `_next_id` | 선체·천체의 공통 번호 카운터 | `0` | `reset()`, `_new_id()` |
>
> 보상용 난수는 `progression.reward_rng`에 따로 보관하며 현재는 미사용입니다. 같은 seed뿐 아니라 행동과 강화 선택도 같아야 같은 경과를 비교할 수 있습니다.

## 한 프레임의 순서

`step(action, want_fire=..., aim_position=...)` 한 번은 정확히 게임 한 프레임입니다. 게임오버면 상태를 진행하지 않고 반환합니다.

1. 행동 해석 → `Combat._tick_effects()` → `EnemyController._update_enemy_scaling()`.
2. 플레이어 조준·이동·이동 후 조준 보정.
3. 적 목록 순서대로 AI·이동·발사 또는 재등장 타이머 처리.
4. 플레이어 발사 → 천체 이동 → 탄환 이동·명중 → 몸체 충돌 → 플레이어 회복.
5. 부족한 천체 보충.
6. `frame` 증가 → `Combat._finish_frame()`의 점수 연출 정리·재장전 완료.
7. 플레이어 체력이 0 이하라면 체력·생존·예약 점사·게임오버·사망 이벤트 확정.

적의 발사와 플레이어의 발사는 같은 위치의 한 묶음으로 처리되지 않습니다. 또한 적 사망은 피해 처리에서 확정하지만 플레이어 사망은 마지막 단계에서 확정합니다. 이 시점 차이는 [[development/flows/damage-and-kills|피해 흐름]]에서 설명합니다.

사람 플레이는 앱이 실제 시간을 누적해 코어를 호출하며 화면 갱신 한 번에 최대 5프레임을 처리합니다. 학습의 `TankEnv.step()`은 기본 4개 게임 프레임을 처리합니다. 메뉴에서는 앱이 코어를 호출하지 않으므로 재장전·점사·회복·재등장도 멈춥니다.

## 새 판 초기화

`__init__()`은 월드 배율·경험치·탄약·재장전·FPS 설정을 검증하고 세 담당 객체를 연결한 뒤 `reset(seed)`를 호출합니다. `reset()`은 난수·공통 상태와 담당 객체 상태를 초기화하고, 새 지형·플레이어·적·천체를 만듭니다. 담당 객체 자체는 유지합니다.

`_make_terrain()`은 비활성·랜덤·파일 맵 설정에 따라 생성 경로를 선택합니다. 맵 풀이 있으면 전투 난수로 맵을 추첨합니다. 지형 설정을 실행 중 바꿨다면 이미 생성된 맵과 일치하도록 새 게임이나 맵 재생성까지 고려해야 합니다.

## 관련 함수

| 함수 | 읽는 상태·호출 조건 | 변경·요청 | 반환 |
|---|---|---|---|
| `reset(seed)` | 새 판 시작·재시작 | 모든 판 상태 초기화, 담당 객체 초기화, 맵·개체 생성 | `None` |
| `step(action, ...)` | 진행할 행동·현재 월드 | 위 순서로 각 담당 객체 실행 | `None` |
| `pop_events()` | 누적 이벤트 | 이벤트 버퍼 교체 | 기존 이벤트 `dict` |
| `_make_terrain()` | 설정·난수 | 지형 생성·읽기 요청 | `TileMap` |
| `_make_shape()` | 설정·난수·현재 월드 | 개체 번호 발급, 생성 위치 계산 | `Shape` |
| `_new_id()` | 번호 카운터 | 카운터 증가 | `int` |
| `_random_free_pos(...)`, `_shape_spawn_pos(radius)` | 지형·반지름·기존 개체 | 후보 추첨; 위치 상태를 직접 저장하지 않음 | 월드 좌표 쌍 |
| `_apply_tank_control(...)`, `_move_shapes()` | 이동 입력·개체 속도·지형 | 위치·속도·각도와 충돌 보정 | `None` |
| `_clamp_to_arena(obj)`, `_fit_tank(p)`, `_fit_player_after_evolution()` | 현재 위치·반지름·경계·지형 | 겹침·월드 밖 위치 보정 | `None` |

개체 정의와 행동 변환은 [entities.py](../../../src/space_z/game/entities.py)·[actions.py](../../../src/space_z/game/actions.py)에 있습니다. `from space_z.game.game_core import Tank, encode_action`으로도 같은 정의를 가져올 수 있습니다. 이전 루트 모듈 import와 `game.level` 같은 이전 상태 접근은 지원하지 않습니다. 현재 접근은 `game.progression.level`, `game.combat.bullets`처럼 소유자를 통합니다.

## 관련 동작과 객체

[[development/classes/PlayerProgression|성장]] · [[development/classes/Combat|전투]] · [[development/classes/EnemyController|적 처리]] · [[development/classes/Tank|선체 상태]] · [[reinforcement-learning/environment|학습 환경]]

돌아가기: [[development/project-structure|전체 지도]]
