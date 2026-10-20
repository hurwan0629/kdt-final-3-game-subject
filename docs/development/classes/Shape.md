---
title: Shape — 파괴 가능한 천체
updated: 2026-10-20
tags: [space-z, class, entity]
---

# Shape

## 역할과 접근 경로

별 조각·행성처럼 파괴해 점수를 얻는 천체 한 개의 상태입니다. `game.shapes`의 원소이며 [entities.py](../../../src/space_z/game/entities.py)의 dataclass입니다. 생성·표류는 코어, 피해·접촉은 전투, 표시는 렌더러가 담당합니다.

## 찾아보기

[[development/classes/Shape#종류와 체력|종류·체력·점수]] · [[development/classes/Shape#위치와 표류|이동·회전]] · [[development/flows/damage-and-kills|피해·파괴 흐름]]

## 종류와 체력

| 속성 | 의미 | 초기값 또는 기준 | 변경 함수 |
|---|---|---|---|
| `id` | 이번 판의 공통 개체 번호 | `GameCore._new_id()` | 생성 시 지정 |
| `kind` | `square`·`triangle`·`pentagon` 종류 키 | 생성 확률과 난수로 선택 | `GameCore._make_shape()` |
| `hp`, `max_hp` | 현재·최대 체력 | `SHAPE_TYPES`의 해당 종류 수치 | 현재 체력은 `Combat._damage_shape()` |
| `radius` | 충돌 반지름, px | 종류별 정의 | 생성 시 지정 |
| `score` | 플레이어가 파괴했을 때 얻는 점수 | 종류별 정의 | 생성 시 지정 |

기본 정의는 [config/game.py](../../../src/space_z/config/game.py)에 있습니다. 기본 체력·점수는 종류별로 10·10, 25·25, 100·130입니다. 설정 정의를 바꾸면 새로 생성한 개체의 값도 달라집니다.

## 위치와 표류

| 속성 | 의미와 단위 | 초기값 또는 기준 | 변경 함수 |
|---|---|---|---|
| `x`, `y` | 중심 월드 좌표, px | 코어의 생성 후보 계산 | `GameCore._move_shapes()`, 전투 몸체 충돌·보정 |
| `vx`, `vy` | 표류 속도, px/frame | `cfg.shape_drift` 기준 추첨 | 표류의 벽 반사·감쇠, 몸체 충돌 |
| `angle` | 현재 표시 회전 각도, rad | dataclass 기본 `0.0`, 생성 시 추첨 | `_move_shapes()` |
| `spin` | 매 게임 프레임의 회전량, rad/frame | dataclass 기본 `0.0`, 생성 시 추첨 | 생성 시 지정 |

## 관련 함수

- **생성:** `GameCore._make_shape()`는 종류·위치·표류를 정하고 `Shape`를 반환합니다. `_shape_spawn_pos()`는 지형·기체·다른 천체를 고려해 좌표를 반환합니다.
- **이동:** `GameCore._move_shapes()`는 좌표·회전을 갱신하고 벽 반사·속도 감쇠를 처리합니다. 반환값은 없습니다.
- **피해:** `Combat._damage_shape()`는 체력·피해 이벤트를 바꾸고 플레이어가 파괴했다면 점수·연출을 요청합니다. 반환값은 없습니다.
- **제거·보충:** 전투의 이동·몸체 충돌 정리에서 파괴된 천체를 제거하고, 코어 `step()`이 부족한 수만큼 새로 생성합니다.
- **표시·관찰:** 렌더러와 학습 관찰은 상태를 조회합니다. `EnemyController`도 목표 천체를 고를 때 읽습니다.

[[development/classes/Combat#피해 적용|피해 적용]] · [[development/classes/GameCore#월드와 개체 목록|개체 목록 소유]] · [[development/classes/README|클래스 목차]]
