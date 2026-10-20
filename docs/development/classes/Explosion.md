---
title: Explosion — 폭발 연출 상태
updated: 2026-10-20
tags: [space-z, class, entity]
---

# Explosion

## 역할과 접근 경로

폭발 중심·반지름·남은 표시 시간을 보관합니다. [entities.py](../../../src/space_z/game/entities.py)의 dataclass이며 `game.combat.explosions`에서 접근합니다.

## 찾아보기

[[development/classes/Explosion#연출 속성|중심·크기·수명]] · [[development/classes/Explosion#관련 함수|폭발 피해와 표시의 차이]]

## 연출 속성

| 속성 | 의미와 단위 | 초기값 또는 기준 | 변경 함수 |
|---|---|---|---|
| `x`, `y` | 폭발 중심 월드 좌표, px | 생성자 필수 인자 | 생성 시 지정 |
| `radius` | 폭발 연출 크기의 기준 반지름, px | 생성자 필수 인자 | 생성 시 지정 |
| `life` | 남은 연출 수명, 게임 프레임 | 기본 `18`, 생성 시 지정 가능 | `Combat._tick_effects()` |

## 관련 함수

`Combat._explode()`는 연출을 목록에 추가하고, 범위 내 대상과 벽에 피해를 적용합니다. 피해는 그 호출에서 처리하며 이후 `Explosion.life`가 줄 때마다 반복해서 피해를 주지는 않습니다. 반환값은 없습니다.

`Combat._tick_effects()`가 수명을 줄이고 만료된 항목을 제거합니다. `Renderer._draw_combat_effects()`가 상태를 읽어 그림을 표시하며 `Combat.reset()`은 목록을 비웁니다. 게임오버 뒤 렌더러가 자체 기록으로 진행하는 사망 효과와 이 코어 연출 목록은 구분합니다.

[[development/classes/Combat#피해 적용|폭발 피해 적용]] · [[development/classes/Renderer#게임 상태와 화면 연출의 차이|게임 상태와 화면 연출]] · [[development/classes/README|클래스 목차]]
