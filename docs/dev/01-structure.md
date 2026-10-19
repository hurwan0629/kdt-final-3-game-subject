---
title: 코드 구조와 상태 소유권
updated: 2026-10-19
tags: [space-skirmish, dev]
---

# 코드 구조와 상태 소유권

게임을 읽을 때는 **값이 어느 객체에 저장되는지**, **누가 그 값을 변경하는지**, **어떤 순서로 호출되는지**를 함께 확인합니다. `GameCore`는 공통 월드와 실행 순서를 관리하고, 성장·전투·적 처리는 각각의 담당 객체가 맡습니다.

## 처음 읽는 순서

1. [main.py](../../main.py)의 `main()`: 설정·렌더러·코어·앱 생성과 실행 루프.
2. `GameApplication.handle_event()` → `update()` → `draw()`: 사람 입력과 메뉴 흐름.
3. [game_core.py](../../game_core.py)의 `__init__()` → `reset()` → `step()`: 객체 연결, 새 판 초기화, 한 프레임의 처리 순서.
4. 관심 있는 담당 객체: [성장](../../gameplay/progression.py), [전투](../../gameplay/combat.py), [적 처리](../../gameplay/enemies.py).
5. [renderer.py](../../renderer.py)의 `draw()` → `draw_main_menu()`와 세부 그리기 함수: 현재 상태를 화면에 표현.

`main()`은 파일 앞쪽에 있지만 파일 끝의 `if __name__ == "__main__":`에서 호출됩니다. 이때 아래쪽 클래스와 보조 함수도 이미 정의되어 있습니다. `import main`은 게임 실행 루프를 시작하지 않습니다.

## 사람이 플레이하는 경로

실행 명령은 `python main.py`입니다.

```text
main(): 설정·Renderer·GameCore·GameApplication 생성
  반복:
    GameApplication.handle_event(event): 키·마우스·메뉴 입력
    GameApplication.update(elapsed, ...): 필요한 횟수만큼 GameCore.step()
    GameApplication.draw(obs_cfg): 메인 메뉴 또는 게임 화면
    pygame.display.flip(): 화면 표시
```

`GameApplication`은 `mode`, `selected`, `difficulty_ratio`, `acc` 등 사람 입력과 메뉴 상태를 보관합니다. 이벤트와 `activate()`가 메뉴 상태를 변경하고, `update()`가 누적 시간을 소비합니다. `acc`는 아직 코어 업데이트에 사용하지 않은 누적 시간입니다.

`mode`는 `main`, `playing`, `pause`이며 메인 메뉴와 일시정지에서는 코어를 진행하지 않습니다. `selected`는 버튼 포커스이고 `difficulty_ratio`는 확정한 난이도입니다. 포커스 이동만으로 난이도가 바뀌지는 않습니다.

`read_player_input()`은 WASD를 행동 번호로, 마우스를 월드 조준 좌표로 변환합니다. `debug_lines()`는 `env.build_vector()`로 표시 값을 만들지만 사람이 플레이할 때 `TankEnv`를 생성하지는 않습니다.

## 학습 환경을 사용하는 경로

[env.py](../../env.py)의 `TankEnv`는 외부 학습 프로그램이 가져다 쓰는 인터페이스입니다. 현재 실제 학습용 `train.py`는 없고 [random_agent_test.py](../../random_agent_test.py)가 무작위 행동으로 검증합니다.

```text
외부 프로그램 → TankEnv 생성
  reset(seed) → GameCore.reset() → 관찰값·정보 반환
  반복:
    외부 프로그램이 행동 선택
    TankEnv.step(action)
      → frame_skip만큼 GameCore.step() (게임오버면 조기 중단)
      → 이벤트 수집·보상 계산·관찰 생성
      → 관찰값·보상·terminated·truncated·정보 반환
```

`env.step()`은 환경을 진행시킵니다. 행동 결정과 모델 학습은 외부 프로그램의 역할입니다. 기본 환경은 성장·탄약 제한을 끄고 27개 이동·회전 행동으로 자동 발사합니다. 화면이 필요할 때 `render_mode="human"`을 사용합니다.

`TankEnv`는 환경 step 수와 환경 설정을, `ObservationBuilder`는 관찰 설정과 지형 격자 캐시를 보관합니다. 환경 `reset()`은 같은 코어를 초기화하며, `step()`은 관찰·보상·종료를 계산합니다. 게임 점수는 `game.progression.score`에 있지만 `info["score"]` 같은 학습 반환 키는 유지됩니다.

## 코어 객체별 상태와 책임

### GameCore — 이번 판의 공통 월드

- **역할:** 월드 생성, 이동·위치 보정, 공통 이벤트와 한 프레임 실행 순서 관리.
- **보유 상태:** `cfg`, `rng`, `frame`, `game_over`, `terrain`, `player`, `enemies`, `shapes`, `events`, `_next_id`와 세 담당 객체.
- **초기화:** 생성자에서 설정을 검증하고 담당 객체를 한 번 생성한 뒤 `reset(seed)`를 호출합니다. 새 판에서는 담당 객체를 교체하지 않고 각각의 `reset()`을 호출합니다.
- **변경 메서드:** `reset()`, `step()`, 월드·개체 생성, 이동·위치 보정, `pop_events()`.
- **읽는 객체:** 세 담당 객체, 입력 컨트롤러, 렌더러, 학습 환경·관찰 생성기.

### Progression — 점수와 플레이어 성장

- **역할:** 점수 획득, 레벨업, 강화·진화·숙련과 보상 알림 관리.
- **보유 상태:** `score`, `kills`, `level`, `xp`, `upgrade_points`, 스탯·숙련 단계, 진화 대기 목록·선택지, 계열, 보상 알림과 별도 `reward_rng`.
- **초기화:** `GameCore.reset()`이 `progression.reset(seed)`를 호출합니다. 전투 난수는 소비하지 않습니다.
- **변경 메서드:** `_add_score()`, `record_kill()`, `upgrade_stat()`, `choose_reward()`, 선택지·알림 준비 메서드. 강화 시 `EnemyController._refresh_stats()`, 진화 시 `_promote_enemies()`에 적 갱신을 요청합니다.
- **읽는 객체:** HUD·입력·학습 정보, 숙련 배율을 계산하는 `Combat`, 플레이어 스탯에 대응하는 `EnemyController`.

### Combat — 발사와 전투 결과

- **역할:** 무기 수치 계산, 점사·발사, 탄환 이동·명중, 피해·회복·몸체 충돌, 전투 연출.
- **보유 상태:** `bullets`, `beams`, `explosions`, `reload_frames_left`, `player_shot_frame`, `score_popups`, `_popup_id`. 기존 비활성 스킬·돌진 상태도 이곳에 유지합니다.
- **초기화:** `GameCore.reset()`이 `combat.reset()`으로 목록·타이머를 비웁니다.
- **변경 메서드:** `_fire()`, `_emit_shot()`, `_move_bullets()`, `_damage_tank()`, `_damage_shape()`, `_collide_bodies()`, `_regen_player()`, `request_reload()`, 연출 처리. 처치·점수는 `Progression.record_kill()`과 `_add_score()`에 전달합니다.
- **읽는 객체:** 탄환·효과·재장전을 표시하는 렌더러, 탄환 관찰을 만드는 학습 환경, 발사 소리를 감지하는 `EnemyController`.

`_finish_frame()`은 코어의 프레임 증가 뒤에 호출되어 점수 연출을 정리하고 재장전 완료를 처리합니다. 플레이어 사망 판정은 그 다음 코어에서 수행합니다.

### EnemyController — 적의 생애와 행동

- **역할:** 적 재등장, 종류·스탯 추첨, 시간별 성장, 감지·목표 선택·추적·조준.
- **보유 상태:** `enemy_scale_tier`. 적 목록은 `GameCore.enemies`, 개별 AI 기억은 각 `Tank`가 보관합니다.
- **초기화:** `GameCore.reset()`에서 성장 단계를 초기화한 뒤 적을 생성합니다. `_respawn_enemy()`는 기존과 같은 범위의 개체 상태를 초기화합니다.
- **변경 메서드:** `_respawn_enemy()`, `_roll_enemy_stats()`, `_apply_enemy_strength()`, `_refresh_stats()`, `_update_enemy_scaling()`, `_promote_enemies()`, `_enemy_ai()`.
- **읽는 객체:** 코어의 적 처리 루프. 성장 객체는 적 갱신을 요청하고 화면은 적 개체의 상태를 읽습니다.

세 담당 객체는 `game` 참조 하나로 현재 월드와 다른 담당 객체에 접근합니다. 플레이어나 지형을 별도 필드에 붙잡아 두지 않으므로 새 판이 시작되어도 새 객체를 조회합니다. 코어 타입 import는 `TYPE_CHECKING`에서만 수행합니다.

## 개체가 보관하는 상태와 실제 변경자

[gameplay/entities.py](../../gameplay/entities.py)는 개체 데이터를 정의합니다. 클래스가 값을 보관한다는 사실이 모든 변경 규칙까지 그 클래스 안에 있다는 뜻은 아닙니다.

| 상태 보관 위치 | 주요 상태 | 변경하는 곳 |
|---|---|---|
| `Tank` | 위치·속도·각도 | 코어의 이동·보정, 적 조준, 전투의 몸체 충돌 |
| `Tank` | 체력·무장·탄약·점사 | 전투, 플레이어 강화·진화, 적 재등장·능력치 갱신 |
| `Tank` | `ai_target`, `ai_last_seen`, `ai_path` 등 | `EnemyController` |
| `Shape` | 위치·속도·회전·체력 | 코어의 표류 처리, 전투의 충돌·피해 |
| `Bullet` | 위치·수명·피해·관통 | `Combat` |
| `Beam`, `Explosion` | 연출 위치·수명 | `Combat` |
| `TileMap` | 타일·벽 체력·`version` | `TileMap`의 지형 변경 메서드; 전투가 벽 피해 요청 |

`GameConfig.player_hp`는 기본 설정이고 `game.player.max_hp`는 이번 판 플레이어의 실제 최대 체력입니다. [progression.py](../../progression.py)의 `ShipClass`, `ShotSpec`, `STAT_UPGRADES`는 콘텐츠 정의입니다. 실제 강화·진화는 `game.progression`, 실제 발사 피해 계산과 적용은 `game.combat`이 수행합니다. 콘텐츠 파일의 스탯 UI 계산 함수는 그대로 유지합니다.

[terrain.py](../../terrain.py)는 맵 읽기·검증·확장·생성, 충돌·시야선·경로 탐색을 담당합니다. [menus.py](../../menus.py)는 버튼 목록·문구·영역을 정의하고 입력 처리와 출력은 앱·렌더러가 담당합니다.

`Renderer`는 카메라·화면·연출 캐시를, [sprite_assets.py](../../sprite_assets.py)의 `SpriteAssets`는 이미지 로딩·축소·회전 캐시를 보관합니다. 렌더링은 게임 체력이나 점수를 변경하지 않습니다. 다만 `set_zoom()`은 공유 설정의 카메라 배율을 변경합니다. 원본 PNG는 수정하지 않습니다.

## 한 프레임이 지나가는 순서

사람 플레이는 이벤트 처리 후 실제 지난 시간을 누적하고 기본 1/60초마다 코어를 진행합니다. 한 번의 화면 갱신에서 밀린 업데이트는 최대 5개입니다. 학습 환경의 한 `step()`은 기본 4개 게임 프레임을 진행하므로 둘을 구분합니다.

1. 코어가 게임오버 여부를 확인하고 행동을 해석합니다.
2. 전투 연출 수명, 시간에 따른 적 성장을 갱신합니다.
3. 플레이어를 이동·조준합니다.
4. 적 목록 순서대로 살아 있는 적의 감지·이동·발사 또는 죽은 적의 재등장 타이머를 처리합니다.
5. 플레이어 발사 → 천체 이동 → 탄환 이동·명중 → 몸체 충돌 → 플레이어 회복을 처리합니다.
6. 부족한 천체를 보충합니다.
7. 프레임을 증가시킨 뒤 점수 연출 정리와 재장전 완료를 처리합니다.
8. 플레이어 사망·예약 점사 취소·게임오버·사망 이벤트를 처리합니다.

메뉴에서는 컨트롤러가 코어를 호출하지 않으므로 재장전·회복·적 재등장·점사도 멈춥니다. 강화·진화는 HUD에서 선택하며 전투가 계속됩니다. 별 반짝임 같은 화면 연출은 메뉴에서도 보일 수 있습니다.

## 무엇을 바꾸려면 어디를 읽는가

| 바꾸려는 것 | 정의·설정 | 실제 처리 |
|---|---|---|
| 메뉴 버튼 이동·실행 | `menus.menu_buttons()` | `GameApplication.handle_event()`, `activate()` |
| 버튼 위치·클릭 영역 | `menus.menu_buttons()` | 앱 클릭 판정과 `Renderer._draw_menu()` |
| 벽 배치·통로·고립 방지 | `TerrainConfig` | `terrain.generate_random_map()`, `TileMap.is_connected()` |
| 벽 이미지·8×8 큰 블록 | `assets/etc/guard_*.png` | `Renderer._draw_full_wall_blocks()`, `_ensure_terrain()` |
| 우주선·포신·무기 수치 | 최상위 `progression.py`의 우주선·발사 정의 | `Progression.choose_reward()`, `Combat.weapon_values()`, `_fire()`, `_emit_shot()` |
| 피해·처치·점수 | `GameConfig`, 우주선 피해 배율 | `Combat`의 명중·피해 → `Progression`의 처치·점수 |
| 스탯 강화·진화 | 최상위 `progression.py` | `Progression` → 적 갱신은 `EnemyController` |
| 적 감지·추적·성장 | `EnemyAIConfig` | `EnemyController` |
| 이미지·폭발·메인 배경 | `assets/` | `SpriteAssets`, `Renderer` |
| 학습 관찰·보상·종료 | `ObsConfig`, `RewardConfig`, `EnvConfig` | `ObservationBuilder`, `compute_reward()`, `TankEnv.step()` |

## 접근 경로와 검증

```python
game.progression.level
game.progression.upgrade_stat("hull")
game.progression.choose_reward(0)
game.combat.request_reload()
game.combat.weapon_values(game.player)
game.combat.bullets
game.enemy_controller.enemy_scale_tier
```

성장·전투·적 상태를 코어에서 다시 노출하는 호환 property는 없습니다. 기존 `game.level`이나 `game.request_reload()` 호출은 새 경로로 바꿉니다. 개체·행동 함수는 기존 `from game_core import Tank, encode_action`도 같은 정의를 가져옵니다. 실제 정의는 `gameplay/entities.py`, `gameplay/actions.py`에 있습니다.

구조는 상속 없이 객체를 조합하는 방식입니다. `GameApplication`은 입력·메뉴, `GameCore`와 담당 객체는 게임 규칙, `Renderer`는 표현을 맡습니다. `TankEnv`는 같은 코어를 학습 인터페이스로 감쌉니다. 이벤트는 `pop_events()`로 소비하며 학습 보상은 코어 밖에서 계산합니다. ECS나 별도 이벤트 버스는 도입하지 않았습니다.

설정은 여러 객체가 공유하므로 맵·지형 설정을 실행 중 변경할 때는 새 게임이나 맵 재생성도 함께 고려합니다. `TileMap.version`은 지형 그림·관찰 캐시 갱신에 사용됩니다.

검증은 `python -m unittest discover -s tests -v`, 무작위 환경 검증은 `python random_agent_test.py`입니다. 기존 키보드 이동 기대 순서 불일치와 간헐적 지형 캐시 문제는 이번 책임 분리에서 수정하지 않습니다. 구조 변경 검증은 고정 seed의 프레임별 상태·이벤트·관찰·보상 비교와 새 판 초기화·담당 객체 연결 검사를 포함합니다.

`docs/dev/render_screens.py`는 문서용 화면 생성 진입점입니다. 실행하면 기존 PNG가 바뀌므로 일반 구조 검증 중 실행하지 않습니다.

다음: [수정 위치와 검증](02-changing-and-testing.md) · [강화학습 환경](03-rl-environment.md) · [조작과 사용자 흐름](../game/01-controls-and-flow.md) · [목차](../README.md)
