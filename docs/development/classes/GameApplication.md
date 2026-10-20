---
title: GameApplication — 입력과 메뉴
updated: 2026-10-20
tags: [space-z, class]
---

# GameApplication

## 역할과 접근 경로

사람의 키·마우스 입력을 게임 동작으로 연결하는 객체입니다. 메뉴를 열었는지, 어떤 버튼을 선택했는지, 게임을 몇 프레임 진행할지를 관리합니다. 체력·점수 계산은 코어의 담당 객체에 요청합니다.

[main.py](../../../src/space_z/main.py)의 `main()`에서 생성하고, 클래스와 입력 보조 함수는 [app.py](../../../src/space_z/app.py)에 있습니다. 생성 직후 `mode`는 `main`입니다.

## 찾아보기

- [[development/classes/GameApplication#메뉴와 표시 상태|메뉴·난이도·버튼 선택]]
- [[development/classes/GameApplication#시간과 발사 입력|accumulated_time·클릭·발사 차단]]
- [[development/classes/GameApplication#스탯 창 상태|강화 창 자동 접기]]
- [[development/classes/GameApplication#관련 함수|입력이 게임에 전달되는 과정]]

## 메뉴와 표시 상태

| 속성 | 의미 | 초기값 또는 기준 | 변경 함수 |
|---|---|---|---|
| `mode` | `main`·`playing`·`pause` 중 현재 화면 흐름 | `main` | `activate_menu_action()`, `handle_event()` |
| `running` | 실행 루프를 계속할지 | `True` | `activate_menu_action()`, `handle_event()` |
| `selected_button_index` | 버튼 목록에서 키보드 포커스의 인덱스 | `start` 버튼의 위치 | `activate_menu_action()`, `handle_event()` |
| `difficulty_ratio` | 확정한 난이도의 적 스탯 대응 비율 | `0.5` | `activate_menu_action()` |
| `show_debug` | 디버그 정보·적 AI 표시 여부 | `False` | `activate_menu_action()`, `handle_event()` |
| `show_controls` | 조작 안내 표시 여부 | `True` | `activate_menu_action()` |
| `show_stats` | Tab 능력치 창 표시 여부 | `False` | `activate_menu_action()`, `update()` |
| `auto_pause` | 창 포커스를 잃으면 일시정지할지 | `True` | `activate_menu_action()` |

`selected_button_index`와 `difficulty_ratio`는 다릅니다. 난이도 버튼에 포커스를 옮긴 뒤 확정해야 선택이 바뀝니다. 메인 메뉴의 좌우는 난이도 행 안에서 순환하고, 상하는 난이도 행을 한 줄로 취급합니다. 새 게임 시작 시 확정한 비율을 공유 설정 `cfg.enemy_ai.stat_mirror_ratio`에 적용합니다.

렌더러는 메인 메뉴에서 마우스로 가리키는 버튼을 먼저 강조하고, 버튼 위에 마우스가 없을 때 키보드 포커스를 표시합니다. 확정한 난이도가 현재 포커스와 다르면 점 표시를 유지한 채 버튼 전체를 반투명하게 그립니다. 이 표시가 앱의 포커스 인덱스나 확정 난이도를 변경하지는 않습니다.

## 시간과 발사 입력

| 속성 | 의미와 단위 | 초기값 | 변경 함수 |
|---|---|---|---|
| `accumulated_time` | 아직 코어 업데이트에 쓰지 않은 누적 시간, 초 | `0.0` | `update()`가 누적·차감, `activate_menu_action()`·`handle_event()`가 전환 시 비움 |
| `action` | 이동·회전을 합친 행동 번호 | `0` | `update()` |
| `click_requested` | 아직 업데이트에 전달하지 않은 단발 클릭 요청 | `False` | `handle_event()`, `update()`, `activate_menu_action()` |
| `suppress_fire` | 메뉴·강화 클릭이 게임 발사로 이어지는 것을 막는 상태 | `True` | `handle_event()`, `activate_menu_action()`, `update()` |

`update(elapsed, ...)`는 `1 / cfg.fps`초마다 `GameCore.step()`을 호출합니다. 예를 들어 한 프레임이 0.02초이고 0.05초가 쌓이면 두 프레임을 처리하고 0.01초를 남깁니다. 밀린 시간은 `MAX_FRAMES_PER_TICK = 5`프레임 분량으로 제한합니다.

메뉴·게임오버에서는 `accumulated_time`와 클릭 요청을 비우고 코어를 진행하지 않습니다. 왼쪽 마우스를 놓으면 `suppress_fire`가 해제됩니다. 미니맵은 발사 차단 영역에 포함되지 않습니다.

## 스탯 창 상태

| 속성 | 의미와 단위 | 초기값 | 변경 함수 |
|---|---|---|---|
| `stat_panel_last_used_frame` | 스탯 창을 마지막으로 사용한 게임 프레임 | `0` | `mark_stat_panel_used()`, 새 게임의 `activate_menu_action()` |
| `previous_upgrade_points` | 직전 확인 때의 남은 강화 포인트 | `0` | `update()`, 새 게임의 `activate_menu_action()` |

새 포인트 획득, 창 위 마우스 이동, 강화 키 입력 시 사용 시각을 갱신합니다. `stat_panel_collapsed`는 저장 필드가 아닌 property입니다. 강화 UI가 표시 가능한 상태에서 `STAT_PANEL_IDLE_SECONDS`만큼 게임 프레임이 지나면 접힌 것으로 계산합니다.

> [!info]- 연결 참조와 보조 속성
> | 속성 | 의미 | 초기값 또는 기준 | 변경 함수 |
> |---|---|---|---|
> | `game` | 현재 `GameCore` | 생성 인자 | `__init__()` |
> | `renderer` | 현재 `Renderer` | 생성 인자 | `__init__()` |
> | `seed` | 재시작 시 사용할 시드 | 생성 인자, 기본 `None` | `__init__()`; 고정 시드일 때 N 입력마다 1 증가 |
> | `cfg` | `game.cfg`와 같은 공유 설정 | 코어 참조 | `__init__()`; 내부 설정은 이벤트·메뉴에서 변경 가능 |
>
> `size`도 property입니다. 렌더러 크기를 조회하며 없으면 설정의 가로·세로를 사용합니다. 별도로 화면 크기를 저장하지 않습니다.

N 입력은 지형을 활성화하고 기존 8×8 랜덤 블록 생성 경로로 새 게임을 시작합니다. 이름별 파일 맵이나 빈 월드를 순환하지 않으며, 맵 파일과 로딩 함수는 변경하지 않습니다.

## 관련 함수

| 함수 | 호출 조건과 읽는 상태 | 변경·요청 | 반환 |
|---|---|---|---|
| `handle_event(ev)` | 메인 루프의 각 Pygame 이벤트 | 메뉴·클릭 상태 변경; 강화·진화·재장전·창 크기 변경 요청 | `None` |
| `activate_menu_action(key)` | 버튼 실행 또는 메뉴 전환 | 메뉴 상태 변경; 시작·재시작 시 코어와 렌더러의 점수 팝업 초기화, 표시 옵션 변경 요청 | `None` |
| `update(elapsed, keys, mouse_pos, buttons)` | 이벤트 처리 후; 메뉴·시간·현재 입력 조회 | 코어 `step()`마다 점수 획득 기록을 꺼내 `Renderer.add_score_popups()`에 전달; 학습 보상용 이벤트는 소비 | `None` |
| `draw(obs_cfg)` | 업데이트 후; 메뉴·표시 옵션 조회 | `Renderer.draw_main_menu()` 또는 `draw()` 호출 | `None` |
| `get_menu_buttons()` | 메뉴를 표시하거나 클릭·포커스를 판정할 때 | `menu_layout.build_menu_buttons()` 조회, 앱 상태 변경 없음 | 버튼 목록 |
| `mark_stat_panel_used()` | 스탯 창 사용 시 | `stat_panel_last_used_frame` 갱신 | `None` |
| `pointer_over_rewards(pos)` | 발사 여부 결정 시 | 강화·진화 UI 영역 조회; 경우에 따라 `open_stat_upgrades()`로 선택지 준비 | `bool` |
| `pointer_over_minimap(pos)` | 미니맵 영역 조회 시 | 렌더러 영역 조회만 수행 | `bool` |

파일의 `read_player_input()`은 WASD를 행동 번호로, 마우스를 월드 조준 좌표로 바꿉니다. `debug_lines()`는 `rl.environment.build_vector()`로 디버그 값을 만듭니다. 사람 플레이가 `TankEnv`를 통해 실행되는 것은 아닙니다.

## 관련 동작과 객체

[[development/flows/firing-projectiles|클릭에서 실제 발사까지]] · [[development/flows/upgrades-and-evolution|강화·진화 선택]] · [[development/classes/Renderer|입력을 화면 좌표와 연결하는 렌더러]] · [[development/classes/GameCore|한 프레임의 진행]]

돌아가기: [[development/project-structure|전체 지도]]
