---
title: Renderer — 화면과 표현 상태
updated: 2026-10-19
tags: [space-skirmish, class]
---

# Renderer

## 역할과 접근 경로

월드·개체·성장 상태를 읽어 화면에 그립니다. 화면·카메라·이미지와 연출 캐시를 보관하며 게임 체력이나 점수를 변경하지 않습니다. 다만 `set_zoom()`은 공유 설정의 `cfg.camera_zoom`을 변경합니다.

[renderer.py](../../../renderer.py)의 `Renderer(cfg)`로 생성합니다. 사람 플레이는 `app.renderer`, 학습 화면은 `TankEnv`가 필요할 때 만드는 `_renderer`를 사용합니다. 이미지 로딩·축소·회전 캐시는 [sprite_assets.py](../../../sprite_assets.py)의 `SpriteAssets`에 요청합니다.

## 찾아보기

- [[dev/classes/Renderer#화면과 카메라|창 크기·전체화면·줌·좌표 변환]]
- [[dev/classes/Renderer#지형과 이미지|벽·미니맵 캐시]]
- [[dev/classes/Renderer#게임 상태와 화면 연출의 차이|체력과 피격 효과의 차이]]
- [[dev/classes/Renderer#관련 함수|그리기 시작점과 세부 함수]]

## 화면과 카메라

| 속성 | 의미와 단위 | 초기값 또는 기준 | 변경 함수 |
|---|---|---|---|
| `cfg` | 코어와 공유하는 설정 | 생성 인자 | `__init__()`; 줌은 `set_zoom()` |
| `screen` | 현재 그리기 대상 Surface | 창 크기의 Pygame 화면 | 생성·창 변경; `draw()` 중 월드 Surface로 잠시 교체 후 복원 |
| `fullscreen` | 전체화면 여부 | `False` | `set_fullscreen()` |
| `windowed_size` | 창 모드로 돌아갈 화면 크기, px | `cfg.window_width`, `cfg.window_height` | `resize()`, `set_fullscreen()` |
| `effective_zoom` | 현재 적용된 화면 배율 | `set_zoom(cfg.camera_zoom)` | `set_zoom()` |
| `view_width`, `view_height` | 월드 그리기 영역의 가로·세로, 월드 px | 실제 화면 크기와 줌으로 계산 | `set_zoom()` |
| `camera_x`, `camera_y` | 월드 그리기 영역 왼쪽 위 좌표 | 각각 `0` | `_update_camera(player)` |
| `assets` | PNG 변환·로딩 담당 객체 | `SpriteAssets()` | `__init__()`; 내부 캐시는 이미지 요청 시 갱신 |
| `clock` | 메인 루프의 FPS·경과 시간 측정기 | `pygame.time.Clock()` | 생성 후 앱 실행 루프의 `tick()` |

`size`는 `screen.get_size()`를 반환하는 property입니다. `view_width`·`view_height`와 다릅니다. 줌이 작아지면 같은 화면에 더 넓은 월드가 들어갑니다.

`_update_camera()`는 플레이어가 항상 화면 중앙에 오도록 카메라를 정합니다. 맵 가장자리에서도 이 규칙을 유지하므로 맵 밖 배경이 보일 수 있습니다. `screen_to_world()`는 마우스 조준을 위해 반대 방향으로 좌표를 변환합니다.

`resize()`는 창 모드에서 최소 크기를 적용하고 화면·줌 영역을 다시 만듭니다. 전체화면 전환도 그리기 대상을 바꾸지만 게임 맵·진행도를 재생성하지 않습니다.

## 지형과 이미지

`_ensure_terrain()`은 타일 상태를 읽어 배경과 벽을 합친 Surface를 준비합니다. 완전히 막힌 8×8 영역은 큰 벽 이미지 하나를 사용합니다. 안에 빈칸이 있거나 다른 블록 크기라면 남은 벽을 작은 이미지로 그립니다. 타일의 실제 충돌이나 체력을 바꾸지 않습니다.

미니맵은 별도의 `_ensure_minimap()`으로 만듭니다. 파괴 가능한 벽이 바뀌면 `TileMap.version`을 기준으로 그림을 갱신합니다. `minimap_rect()`가 반환하는 영역을 입력 코드도 조회할 수 있습니다.

> [!info]- 지형·이미지·그리기 Surface 캐시
> | 속성 | 의미 | 초기값 또는 기준 | 변경 함수 |
> |---|---|---|---|
> | `_view` | 줌을 적용하기 전 월드 그리기 Surface | `set_zoom()`에서 생성 | `set_zoom()`, 내용은 `draw()` |
> | `_bg` | 반복해 깔 배경 Surface | `_make_background()`의 결과 | `__init__()` |
> | `_floor` | 배경·지형을 합친 Surface | `None` | `_ensure_terrain()` |
> | `_terrain_key` | 지형 캐시 판별 키 | `None`, 갱신 시 `(id(tm), tm.version)` | `_ensure_terrain()` |
> | `_minimap_floor` | 축소한 타일 그림 | `None` | `_ensure_minimap()` |
> | `_minimap_key` | 미니맵 캐시 판별 키 | `None`, 갱신 시 `(terrain, terrain.version, size)` | `_ensure_minimap()` |
> | `_shape_sprites` | 천체 종류별 그림 | `_make_shape_sprite()` 결과 사전 | `__init__()` |
> | `_explosion_frames` | 폭발 애니메이션 프레임 이미지 | `_make_explosion_frames()` 결과 | `__init__()` |
> | `_glow_cache` | 크기·색·강도별 발광 Surface | 빈 사전 | `_glow()` |
> | `_world_boundary_layer` | 월드 경계선용 투명 Surface | 필요할 때 처음 생성 | `_draw_world_boundary()`; 화면 크기 변경 시 재생성 |
>
> 지형 캐시의 객체 번호 재사용에 따른 간헐 문제는 기존 검토 사항입니다. 이 문서는 현재 키를 설명하며 문제가 해결되었다고 전제하지 않습니다.

## 게임 상태와 화면 연출의 차이

`Tank.hp`는 게임 규칙이 사용하는 실제 체력입니다. `_prev_hp`는 렌더러가 이전 체력과 비교해 피격 효과를 만들기 위한 기록입니다. 렌더러의 기록을 지워도 실제 체력이 회복되는 것은 아닙니다.

`_track(game)`는 현재 개체와 이전 기록을 비교해 등장·피격·사망·점수 효과를 만듭니다. 프레임 번호가 이전보다 작아지면 판이 바뀐 것으로 보고 주요 추적 기록을 비웁니다. 일반 일시정지에서는 게임 프레임이 멈추며, 게임오버 이후에는 자체 사망 연출을 계속 진행할 수 있습니다.

> [!info]- 연출 시간과 추적 기록
> | 속성 | 의미 | 초기값 또는 기준 | 변경 함수 |
> |---|---|---|---|
> | `_rand` | 게임과 분리한 화면 연출 난수 | `random.Random(2024)` | 생성 후 배경·점수 연출에서 소비 |
> | `_twinkles` | 별 위치·위상·반짝임 속도 목록 | 월드 크기·배율과 `_rand`로 생성 | `__init__()`; `_draw_twinkles()`는 조회 |
> | `_tick` | 게임 화면을 그린 횟수 | `0` | `draw()` |
> | `_last_frame` | 직전 추적 게임 프레임 | `-1` | `_track()` |
> | `_first_seen` | 개체 번호별 처음 등장한 프레임 | 빈 사전 | `_track()` |
> | `_prev_hp` | 천체 번호별 직전 체력 | 빈 사전 | `_track()` |
> | `_hit_frame` | 천체 번호별 마지막 피격 효과 시각 | 빈 사전 | `_track()` |
> | `_prev_shapes` | 직전 천체의 표시 정보 스냅샷 | 빈 사전 | `_track()` |
> | `_prev_alive` | 선체 번호별 직전 생존 여부 | 빈 사전 | `_track()` |
> | `_ghosts` | 사라지는 개체의 사망 연출 | 빈 리스트 | `_track()` |
> | `_sparks` | 점수 획득 불꽃의 위치·속도·수명·색 | 빈 리스트 | `_track()` |
> | `_popups_seen` | 이미 연출로 만든 점수 기록 번호 | 빈 집합 | `_track()` |
> | `_xp_flash_frame` | 최근 점수 연출의 게임 프레임 | `-999` | `_track()` |
> | `_flash_on` | 게임오버 전 피격 반짝임 허용 여부 | 첫 `draw()`에서 결정 | `draw()` |

> [!info]- 글꼴 리소스
> | 속성 | 용도 | 초기값 또는 기준 | 변경 함수 |
> |---|---|---|---|
> | `font_hud`, `font_label`, `font_small` | HUD·라벨·작은 안내 | 시스템 글꼴 22·13·14 크기 | `__init__()` |
> | `font_big`, `font_card`, `font_body` | 큰 제목·카드·본문 | 시스템 글꼴 56·24·17 크기 | `__init__()` |
> | `font_mono` | 고정폭 디버그 표시 | 고정폭 시스템 글꼴 13 크기 | `__init__()` |
> | `font_score`, `font_score_big` | 점수·큰 점수 | 시스템 글꼴 22·30 크기 | `__init__()` |

## 관련 함수

| 함수 | 읽는 상태·조건 | 변경·요청 | 반환 |
|---|---|---|---|
| `draw(game, ...)` | 매 게임 화면 갱신; 월드·전투·성장·표시 옵션 | 카메라·추적·캐시·화면 갱신; 게임 규칙 상태는 변경하지 않음 | `None` |
| `draw_main_menu(buttons, selected)` | 메인 메뉴 표시 | 메인 배경·메뉴 버튼을 화면에 그림 | `None` |
| `resize(size)`, `set_fullscreen(enabled)`, `set_zoom(zoom)` | 창 변경·옵션 선택 | 화면·줌 상태·월드 Surface 갱신; 줌은 공유 설정에도 반영 | `None` |
| `_update_camera(player)` | 현재 플레이어 위치·월드 그리기 크기 | `camera_x`, `camera_y` 변경 | `None` |
| `world_to_view(x, y)`, `world_to_screen(x, y)`, `screen_to_world(x, y)` | 카메라·배율 | 변경 없음 | 좌표 쌍 |
| `_visible(x, y, margin)`, `_spawn_scale(oid, frame)` | 시야·등장 기록 | 변경 없음 | 표시 여부 또는 등장 배율 |
| `_track(game)` | 현재·이전 개체와 점수 연출 | 화면 연출의 기록·수명 갱신 | `None` |
| `_ensure_terrain(tm)`, `_ensure_minimap(terrain, size)` | 타일·버전·캐시 키 | 필요 시 지형 그림 재생성 | `None` |
| `minimap_rect()` | 실제 화면 크기 | 변경 없음 | 미니맵 `Rect` |
| `_make_background()`, `_make_shape_sprite(kind)`, `_make_explosion_frames()` | 설정·이미지 | Surface·이미지 준비 | Surface 또는 프레임 목록 |
| `_glow(radius, color, intensity)` | 발광 캐시 | 필요 시 발광 Surface 보관 | Surface |

`_draw_ship()`·`_draw_bullet()`·`_draw_shape()` 등 월드 그리기와 `_draw_hud()`·`_draw_progression()`·`_draw_rewards()` 등 UI 그리기는 현재 상태를 읽어 Surface에 출력합니다. 전투 피해나 강화 효과를 적용하는 곳은 각각 `Combat`, `Progression`입니다.

## 관련 동작과 객체

[[dev/classes/GameApplication|입력·메뉴 상태]] · [[dev/classes/Combat|실제 탄환·전투 결과]] · [[dev/classes/WorldEntities#Explosion|게임 프레임으로 관리하는 폭발]] · [[game/04-maps|맵 설명]] · [[dev/02-changing-and-testing|수정 위치와 검증]]

돌아가기: [[dev/01-structure|전체 지도]]
