---
title: Beam — 빔 연출 상태
updated: 2026-10-20
tags: [space-z, class, entity]
---

# Beam

## 역할과 접근 경로

시작점과 끝점 사이에 표시할 빔 연출 상태입니다. [entities.py](../../../src/space_z/game/entities.py)의 dataclass이며 `game.combat.beams`에 보관합니다. 현재 일반 사격은 이 연출을 생성하지 않습니다.

## 찾아보기

[[development/classes/Beam#연출 속성|좌표·수명]] · [[development/classes/Beam#관련 함수|수명 감소·표시]]

## 연출 속성

| 속성 | 의미와 단위 | 초기값 또는 기준 | 변경 함수 |
|---|---|---|---|
| `x`, `y` | 시작점 월드 좌표, px | 생성자 필수 인자 | 생성 시 지정 |
| `end_x`, `end_y` | 끝점 월드 좌표, px | 생성자 필수 인자 | 생성 시 지정 |
| `life` | 남은 연출 수명, 게임 프레임 | 기본 `6`, 생성 시 지정 가능 | `Combat._tick_effects()` |

## 관련 함수

`Combat._tick_effects()`는 매 코어 프레임 수명을 줄이고 0 이하인 빔을 목록에서 제거합니다. `Renderer._draw_combat_effects()`는 좌표와 남은 수명을 읽어 표시합니다. 둘 다 반환값은 없습니다. `Combat.reset()`은 목록을 비웁니다.

이 객체는 표시 상태를 담습니다. 자체 명중·피해 메서드는 없습니다. 게임 프레임이 멈추면 이 수명도 줄지 않습니다.

[[development/classes/Combat|전투 목록]] · [[development/classes/Renderer|화면 표현]] · [[development/classes/README|클래스 목차]]
