---
title: Combat — 발사와 전투 결과
updated: 2026-10-20
tags: [space-z, class]
---

# Combat

## 역할과 접근 경로

발사·점사·탄환 이동·명중·피해·회복·몸체 충돌을 처리합니다. 접근 경로는 `game.combat`, 구현은 [combat.py](../../../src/space_z/game/combat.py)입니다. 생성 때 코어 참조를 받고, 새 판에서는 `reset()`으로 전투 목록과 타이머를 비웁니다.

탄환 목록은 이 객체에 있지만 **탄약·발사 대기·예약 점사는 각 `Tank`에** 있습니다. 플레이어와 적 모두 같은 발사 함수를 사용합니다. 적 처치·점수는 `PlayerProgression`에 전달합니다.

점수를 획득한 위치와 시각은 `GameCore.record_score_award()`로 기록합니다. 팝업 목록·고유 번호·표시 시간은 [[development/classes/Renderer#점수 팝업|Renderer]]가 관리합니다.

## 찾아보기

- [[development/classes/Combat#발사 상태|탄환·예약 점사·발사 수치]]
- [[development/classes/Combat#재장전|탄약과 재장전 타이머]]
- [[development/classes/Combat#피해 적용|체력·처치·회복]]
- [[development/classes/Combat#관련 함수|전투 함수의 입력과 결과]]

## 발사 상태

| 속성 | 의미와 단위 | 초기값 | 변경 함수 |
|---|---|---|---|
| `bullets` | 현재 남아 있는 `Bullet` 목록 | 빈 리스트 | `reset()`, `_emit_shot()`가 추가, `_move_bullets()`가 정리 |
| `player_shot_frame` | 적의 청각 감지에 쓰는 마지막 플레이어 발사 묶음 시작 프레임 | `-10**9` | `reset()`, `_fire()` |

`weapon_values(tank)`는 우주선 정의, 개체 배율과 플레이어 숙련을 읽어 `(spec, damage, cooldown, speed, life)`를 반환합니다. `_shot_delays(tank, spec)`는 패턴의 원래 지연을 실제 점사 지연으로 바꿉니다. 둘은 상태를 변경하지 않습니다.

`_fire(t, want_fire)`는 먼저 이미 예약된 발사를 처리합니다. 이후 발사 대기를 줄이고, 가능할 때 새 묶음을 시작합니다. 따라서 `want_fire=False`여도 이전 점사는 이어질 수 있습니다. 사망·플레이어 재장전 중에는 예약을 취소합니다.

예약 값은 `Tank.pending_shots`에 `(발사 프레임, ShotSpec, 피해, 탄속, 수명)`으로 저장합니다. 예약 당시의 수치를 사용하지만 실제 포구 위치와 조준 각도는 발사 시점의 기체 상태로 계산합니다. [[development/flows/firing-projectiles|트윈의 순차 발사 예시]]를 참고하세요.

`_emit_shot()`은 포구까지 벽을 검사하고 탄환을 만듭니다. 생성 직후의 이동 구간에서도 명중을 검사하므로, 바로 소멸한 탄환은 `bullets`에 추가되지 않을 수 있습니다. 현재 저격 계열은 포탄 이미지와 관통 1회를 사용합니다.

## 재장전

| 속성 | 의미와 단위 | 초기값 | 변경 함수 |
|---|---|---|---|
| `reload_frames_left` | 플레이어 재장전 완료까지 남은 게임 프레임 | `0` | `reset()`, `request_reload()`, `_finish_frame()` |

`reload_frames_total`은 property입니다. `ceil(max(0.75, cfg.reload_seconds * player.reload_scale) * cfg.fps)`를 계산하며 저장하지 않습니다.

`request_reload()`는 게임 종료·사망·무제한 탄약·이미 재장전 중·가득 찬 탄창이면 `False`를 반환합니다. 가능하면 타이머를 설정하고 플레이어 예약 점사를 비운 뒤 `True`를 반환합니다.

실제 `ammo`, `max_ammo`, `reload_scale`은 [[development/classes/Tank#무장과 탄약|Tank]]의 상태입니다. 탄약 제한이 켜진 플레이어는 **실제로 각 탄환을 방출할 때마다** 탄약 하나를 소비합니다. 적에게 이 플레이어 탄창 제한을 적용하지 않습니다.

`_finish_frame()`은 코어가 프레임을 증가시킨 뒤 타이머를 하나 줄입니다. 완료 시 체력이 양수인 플레이어의 탄창을 채웁니다. 메뉴에서는 코어 호출이 멈추므로 재장전도 멈춥니다.

## 피해 적용

체력은 `Combat`에 저장하지 않습니다. 대상의 `Tank.hp` 또는 `Shape.hp`를 변경하며, 결과를 코어 이벤트와 성장 객체에 전달합니다.

- `_damage_tank(t, dmg, by_player)`는 우주선의 받는 피해 배율을 적용하고, 실제 남은 체력까지만 피해를 기록합니다. 피격 프레임을 갱신합니다. 적이 죽으면 생존 상태·재등장 타이머를 바꾸고 플레이어 처치에 한해 점수·처치 수를 전달합니다.
- `_damage_shape(s, dmg, by_player)`는 천체 체력을 줄입니다. 플레이어가 입힌 피해와 파괴는 이벤트로 기록하고, 파괴 시 천체 점수를 성장 객체에 전달합니다.
- `_regen_player()`는 체력이 양수이고 피격 후 회복 대기 시간이 지났을 때 현재 최대 체력에 비례해 회복합니다. 최대 체력을 넘지 않습니다.
- `_collide_bodies()`는 겹침을 풀고 접촉 피해를 위 함수들에 전달합니다. 파괴된 천체를 제거하고 코어·지형에 위치 보정을 요청합니다.

**플레이어와 적의 사망 확정 시점이 다릅니다.** 적은 `_damage_tank()` 안에서 사망 상태가 됩니다. 플레이어는 피격 이벤트를 기록한 뒤 반환하며, `GameCore.step()` 끝에서 사망·예약 취소·게임오버를 확정합니다.

자세한 연결: [[development/flows/damage-and-kills|피해 적용에서 처치·성장까지]].

> [!info]- 전투 연출과 보조 속성
> | 속성 | 의미 | 초기값 또는 기준 | 변경 함수 |
> |---|---|---|---|
> | `game` | 현재 코어 참조 | 생성 인자 | `__init__()` |
> | `beams` | `Beam` 연출 목록 | 빈 리스트 | `reset()`, `_tick_effects()`; 현재 일반 사격은 빔을 생성하지 않음 |
> | `explosions` | `Explosion` 연출 목록 | 빈 리스트 | `reset()`, `_explode()`, `_tick_effects()` |
>
> `_tick_effects()`는 빔·폭발 수명을 줄여 만료 항목을 제거합니다. `_finish_frame()`은 프레임 증가 뒤 재장전 타이머와 완료된 탄창을 갱신합니다.

> [!note]- 현재 비활성인 상태
> | 속성 | 의미 | 초기값 | 변경 함수 |
> |---|---|---|---|
> | `active_skill` | 이전 액티브 스킬 상태 | `None` | `reset()`만 설정 |
> | `skill_cooldown` | 이전 스킬 대기 | `0` | `reset()`만 설정 |
> | `dash_frames_left` | 이전 돌진 잔여 시간 | `0` | `reset()`만 설정 |
>
> `request_skill(move, aim_position)`는 상태를 변경하지 않고 항상 `False`를 반환합니다. 이 필드를 현재 사용 가능한 기능으로 해석하지 않습니다.

## 관련 함수

| 함수 | 조건·읽는 상태 | 변경·다른 객체 요청 | 반환 |
|---|---|---|---|
| `weapon_values(tank)` | 기체 종류·배율·숙련 조회 | 변경 없음 | 정의·피해·대기·탄속·수명 튜플 |
| `_shot_delays(tank, spec)` | 기체 발사 간격·패턴 지연 | 변경 없음 | 원래 지연 → 실제 프레임 지연의 `dict` |
| `_fire(t, want_fire)` | 매 프레임의 기체 생존·대기·점사·입력 | 점사·탄약·대기·발사 시각 갱신, `_emit_shot()` 호출 | `None` |
| `_emit_shot(tank, shot, damage, speed, life)` | 발사할 패턴과 기체 위치·각도 | 벽·즉시 명중 검사, 탄환 추가 또는 피해 적용 | `None` |
| `_move_bullets()` | 탄환 목록·지형·개체 | 이동·수명 감소·첫 명중·벽 피해·소멸·천체 정리 | `None` |
| `_bullet_hit(b)` | 이전·현재 탄환 위치와 대상 목록 | 가장 먼저 닿는 한 대상에 피해, 관통 상태 변경 | 탄환 소멸 여부 `bool` |
| `_damage_tank(t, dmg, by_player)`, `_damage_shape(s, dmg, by_player)` | 대상 체력·피해·공격 주체 | 체력·전투 이벤트 변경, 코어에 점수 획득 기록, 성장에 실제 점수 전달 | `None` |
| `_explode(x, y, damage, radius, team)` | 폭발 범위의 개체·벽 | 거리별 피해·벽 피해·폭발 연출 추가 | `None` |
| `_collide_bodies()`, `_regen_player()` | 현재 개체·접촉·피격 시각 | 위치·체력 변경, 코어·지형 보정 요청 | `None` |
| `_tick_effects()` | 빔·폭발의 남은 수명 | 수명 감소와 만료 항목 제거 | `None` |
| `_finish_frame()` | 현재 재장전 타이머·플레이어 체력 | 타이머·완료 탄약 변경 | `None` |
| `request_reload()` | 생존·탄약 제한·잔탄·현재 타이머 | 가능한 경우 재장전 시작·점사 취소 | `bool` |
| `reset()` | 새 판 시작 | 전투 상태 초기화; 전투 난수 소비 없음 | `None` |

파일 하단의 `_segment_circle_hit()`·`_overlap()`은 충돌을 조회하는 계산 함수이고, `_push_apart()`는 두 개체의 위치·속도를 직접 보정합니다. 자세한 수학식과 각 인자는 코드의 docstring에서 확인합니다.

## 관련 동작과 객체

[[development/flows/firing-projectiles|입력과 점사 흐름]] · [[development/classes/Tank#체력 상태|선체 체력]] · [[development/classes/Bullet|탄환 상태]] · [[development/classes/Shape|천체·연출]] · [[development/classes/PlayerProgression|처치 뒤 성장]]

돌아가기: [[development/project-structure|전체 지도]]
