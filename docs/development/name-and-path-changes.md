# 이름과 경로 변경

소스는 `space_z` 패키지로 통일했습니다. 이전 루트 모듈을 대신하는 호환 파일은 두지 않습니다. 저장소 밖의 호출 코드도 새 import를 사용합니다.

| 이전 | 현재 |
|---|---|
| `python main.py` | `python -m space_z` 또는 `space-z` |
| `from config import GameConfig` | `from space_z.config import GameConfig` |
| `from main import GameApplication` | `from space_z.app import GameApplication` |
| `from game_core import GameCore` | `from space_z.game.game_core import GameCore` |
| `from env import TankEnv` | `from space_z.rl.environment import TankEnv` |
| 최상위 `progression.py` | `config/progression_definitions.py`와 `rendering/progression_panel.py` |
| `gameplay/progression.py`, `Progression` | `game/player_progression.py`, `PlayerProgression` |
| `gameplay/enemies.py` | `game/enemy_controller.py` |
| `menus.py` | `rendering/menu_layout.py` |
| `GameApplication.acc` | `accumulated_time`: 미처리 누적 시간 |
| `selected` | `selected_button_index`: 메뉴 포커스 인덱스 |
| `buttons()` | `get_menu_buttons()` |
| `activate(key)` | `activate_menu_action(key)` |
| `touch_stat_panel()`, `stat_touch_frame` | `mark_stat_panel_used()`, `stat_panel_last_used_frame` |
| `stats_collapsed`, `stat_points_seen` | `stat_panel_collapsed`, `previous_upgrade_points` |
| `menu_buttons()` | `build_menu_buttons()` |
| `stat_rows()`, `special_cards()` | `build_stat_upgrade_rows()`, `get_evolution_card_rects()` |
| `stat_panel_rect()`, `stat_collapsed_rect()` | `get_expanded_stat_panel_rect()`, `get_collapsed_stat_panel_rect()` |
| `stat_upgrades_visible()`, `player_stat_summary()` | `can_show_stat_upgrades()`, `build_player_stat_summary()` |

`game.progression`의 접근 경로와 `TankEnv.reset()/step()` 반환 형식은 유지합니다. `x`, `y`, `vx`, `vy` 같은 수학·물리 표기는 기존 관례를 유지합니다. 게임 규칙과 설정값을 바꾸기 위한 작업은 아닙니다.

[[development/project-structure|현재 구조]] · [[development/README|개발 안내]]
