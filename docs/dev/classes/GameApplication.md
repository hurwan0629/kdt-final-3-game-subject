---
title: GameApplication — 입력과 메뉴
updated: 2026-10-19
tags: [space-skirmish, class]
---

# GameApplication

## 역할과 접근 경로

사람의 키·마우스 입력을 게임 동작으로 연결하는 객체입니다. 메뉴를 열었는지, 어떤 버튼을 선택했는지, 게임을 몇 프레임 진행할지를 관리합니다. 체력·점수 계산은 코어의 담당 객체에 요청합니다.

[main.py](../../../main.py)의 `main()`에서 `app = GameApplication(game, renderer, seed)`로 생성합니다. 생성 직후 `mode`는 `main`입니다.

## 찾아보기

- [[dev/classes/GameApplication#메뉴와 표시 상태|메뉴·난이도·버튼 선택]]
- [[dev/classes/GameApplication#시간과 발사 입력|acc·클릭·발사 차단]]
- [[dev/classes/GameApplication#스탯 창 상태|강화 창 자동 접기]]
- [[dev/classes/GameApplication#관련 함수|입력이 게임에 전달되는 과정]]

## 메뉴와 표시 상태

| 속성 | 의미 | 초기값 또는 기준 | 변경 함수 |
|---|---|---|---|
| `mode` | `main`·`playing`·`pause` 중 현재 화면 흐름 | `main` | `activate()`, `handle_event()` |
| `running` | 실행 루프를 계속할지 | `True` | `activate()`, `handle_event()` |
| `selected` | 버튼 목록에서 키보드 포커스의 인덱스 | `start` 버튼의 위치 | `activate()`, `handle_event()` |
| `difficulty_ratio` | 확정한 난이도의 적 스탯 대응 비율 | `0.5` | `activate()` |
| `show_debug` | 디버그 정보·적 AI 표시 여부 | `False` | `activate()`, `handle_event()` |
| `show_controls` | 조작 안내 표시 여부 | `True` | `activate()` |
| `show_stats` | Tab 능력치 창 표시 여부 | `False` | `activate()`, `update()` |
| `auto_pause` | 창 포커스를 잃으면 일시정지할지 | `True` | `activate()` |

`selected`와 `difficulty_ratio`는 다릅니다. 난이도 버튼에 포커스를 옮긴 뒤 확정해야 선택이 바뀝니다. 메인 메뉴의 좌우는 난이도 행 안에서 순환하고, 상하는 난이도 행을 한 줄로 취급합니다. 새 게임 시작 시 확정한 비율을 공유 설정 `cfg.enemy_ai.stat_mirror_ratio`에 적용합니다.

## 시간과 발사 입력

| 속성 | 의미와 단위 | 초기값 | 변경 함수 |
|---|---|---|---|
| `acc` | 아직 코어 업데이트에 쓰지 않은 누적 시간, 초 | `0.0` | `update()`가 누적·차감, `activate()`·`handle_event()`가 전환 시 비움 |
| `action` | 이동·회전을 합친 행동 번호 | `0` | `update()` |
| `click_requested` | 아직 업데이트에 전달하지 않은 단발 클릭 요청 | `False` | `handle_event()`, `update()`, `activate()` |
| `suppress_fire` | 메뉴·강화 클릭이 게임 발사로 이어지는 것을 막는 상태 | `True` | `handle_event()`, `activate()`, `update()` |

`update(elapsed, ...)`는 `1 / cfg.fps`초마다 `GameCore.step()`을 호출합니다. 예를 들어 한 프레임이 0.02초이고 0.05초가 쌓이면 두 프레임을 처리하고 0.01초를 남깁니다. 밀린 시간은 `MAX_FRAMES_PER_TICK = 5`프레임 분량으로 제한합니다.

메뉴·게임오버에서는 `acc`와 클릭 요청을 비우고 코어를 진행하지 않습니다. 왼쪽 마우스를 놓으면 `suppress_fire`가 해제됩니다. 미니맵은 발사 차단 영역에 포함되지 않습니다.

## 스탯 창 상태

| 속성 | 의미와 단위 | 초기값 | 변경 함수 |
|---|---|---|---|
| `stat_touch_frame` | 스탯 창을 마지막으로 사용한 게임 프레임 | `0` | `touch_stat_panel()`, 새 게임의 `activate()` |
| `stat_points_seen` | 직전 확인 때의 남은 강화 포인트 | `0` | `update()`, 새 게임의 `activate()` |

새 포인트 획득, 창 위 마우스 이동, 강화 키 입력 시 사용 시각을 갱신합니다. `stats_collapsed`는 저장 필드가 아닌 property입니다. 강화 UI가 표시 가능한 상태에서 `STAT_PANEL_IDLE_SECONDS`만큼 게임 프레임이 지나면 접힌 것으로 계산합니다.

> [!info]- 연결 참조와 보조 속성
> | 속성 | 의미 | 초기값 또는 기준 | 변경 함수 |
> |---|---|---|---|
> | `game` | 현재 `GameCore` | 생성 인자 | `__init__()` |
> | `renderer` | 현재 `Renderer` | 생성 인자 | `__init__()` |
> | `seed` | 재시작 시 사용할 시드 | 생성 인자, 기본 `None` | `__init__()` |
> | `cfg` | `game.cfg`와 같은 공유 설정 | 코어 참조 | `__init__()`; 내부 설정은 이벤트·메뉴에서 변경 가능 |
> | `map_cycle` | N 키로 순환할 맵·랜덤 맵·빈 경기장 목록 | `list_maps()`와 두 추가 항목 | `__init__()` |
>
> `size`도 property입니다. 렌더러 크기를 조회하며 없으면 설정의 가로·세로를 사용합니다. 별도로 화면 크기를 저장하지 않습니다.

## 관련 함수

| 함수 | 호출 조건과 읽는 상태 | 변경·요청 | 반환 |
|---|---|---|---|
| `handle_event(ev)` | 메인 루프의 각 Pygame 이벤트 | 메뉴·클릭 상태 변경; 강화·진화·재장전·창 크기 변경 요청 | `None` |
| `activate(key)` | 버튼 실행 또는 메뉴 전환 | 메뉴 상태 변경; 시작 시 코어 `reset()`, 표시 옵션은 렌더러에 요청 | `None` |
| `update(elapsed, keys, mouse_pos, buttons)` | 이벤트 처리 후; 메뉴·시간·현재 입력 조회 | 스탯 창·입력 상태 갱신, 필요한 횟수만큼 코어 `step()`; 사람 플레이 이벤트 소비 | `None` |
| `draw(obs_cfg)` | 업데이트 후; 메뉴·표시 옵션 조회 | `Renderer.draw_main_menu()` 또는 `draw()` 호출 | `None` |
| `buttons()` | 메뉴를 표시하거나 클릭·포커스를 판정할 때 | `menus.menu_buttons()` 조회, 앱 상태 변경 없음 | 버튼 목록 |
| `touch_stat_panel()` | 스탯 창 사용 시 | `stat_touch_frame` 갱신 | `None` |
| `pointer_over_rewards(pos)` | 발사 여부 결정 시 | 강화·진화 UI 영역 조회; 경우에 따라 `open_stat_upgrades()`로 선택지 준비 | `bool` |
| `pointer_over_minimap(pos)` | 미니맵 영역 조회 시 | 렌더러 영역 조회만 수행 | `bool` |

파일의 `read_player_input()`은 WASD를 행동 번호로, 마우스를 월드 조준 좌표로 바꿉니다. `debug_lines()`는 `env.build_vector()`로 디버그 값을 만듭니다. 사람 플레이가 `TankEnv`를 통해 실행되는 것은 아닙니다.

## 관련 동작과 객체

[[dev/flows/탄환 발사|클릭에서 실제 발사까지]] · [[dev/flows/강화와 진화|강화·진화 선택]] · [[dev/classes/Renderer|입력을 화면 좌표와 연결하는 렌더러]] · [[dev/classes/GameCore|한 프레임의 진행]]

돌아가기: [[dev/01-structure|전체 지도]]
