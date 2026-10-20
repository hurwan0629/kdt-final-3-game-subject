# 프로젝트 구조

실행 소스는 `src/space_z/`에 있고, 이미지·맵·테스트·문서는 프로젝트 루트에서 분리합니다. `main.py`는 실행 준비, `app.py`는 사람 입력, `game/`은 사람 플레이와 학습이 공유하는 규칙입니다.

## 폴더별 책임

| 위치 | 담당 |
|---|---|
| `src/space_z/main.py`, `__main__.py` | 실행 인자·객체 생성·실행 루프, `python -m space_z` 진입점 |
| `src/space_z/app.py` | `GameApplication`: 입력·메뉴·시간 누적·코어와 렌더러 연결 |
| `src/space_z/config/` | 기본 설정과 우주선·포신·강화 정의 |
| `src/space_z/game/` | 월드·개체·전투·성장·적 행동·지형 |
| `src/space_z/rendering/` | 화면·이미지 변환·메뉴·강화 패널 배치 |
| `src/space_z/rl/environment.py` | `TankEnv`, 관찰 생성·학습 보상·환경 종료 |
| `src/space_z/resource_paths.py` | 작업 폴더와 무관한 이미지·맵 경로 계산 |
| `assets/`, `maps/` | 기존 리소스와 맵 원본 |
| `tests/`, `scripts/` | 자동 테스트·무작위 검증·문서 화면 생성 도구 |

## 실제 소스 배치

```text
src/space_z/
├── __main__.py                 # python -m space_z
├── main.py                     # 실행 준비와 메인 루프
├── app.py                      # 사람 입력·메뉴·시간 누적
├── resource_paths.py           # 이미지·맵 경로
├── config/
│   ├── game.py                 # 공통 기본값과 천체 종류
│   ├── enemy_ai.py             # 적 감지·추적·성장 설정
│   ├── terrain.py              # 타일·맵 생성 설정
│   ├── learning.py             # 관찰·보상·환경 설정
│   └── progression_definitions.py  # 강화·우주선·포신 정의
├── game/
│   ├── game_core.py            # 월드와 한 프레임 조율
│   ├── entities.py             # 선체·탄환·천체 데이터
│   ├── actions.py              # 행동 번호와 이동·회전 변환
│   ├── player_progression.py   # 점수·강화·진화 적용
│   ├── combat.py               # 발사·명중·피해·회복
│   ├── enemy_controller.py     # 적 생성·성장·행동
│   └── terrain.py              # 맵 생성·충돌·경로 탐색
├── rendering/
│   ├── renderer.py             # 화면 출력
│   ├── sprite_assets.py        # 이미지 로딩·변환·캐시
│   ├── menu_layout.py          # 메뉴 버튼 문구와 영역
│   └── progression_panel.py    # 강화·진화 UI 배치와 표시 계산
└── rl/
    └── environment.py          # TankEnv·관찰·보상
```

각 패키지의 `__init__.py`는 위 트리에서 생략했습니다. 설정을 가져올 때는 `from space_z.config import GameConfig`처럼 사용합니다.

## 처음 읽는 순서

1. [main.py](../../src/space_z/main.py)의 `main()`: 설정·렌더러·코어·앱 생성.
2. [[development/classes/GameApplication|GameApplication]]의 이벤트 → 업데이트 → 화면 출력.
3. [[development/classes/GameCore|GameCore]]의 생성 → 초기화 → 한 프레임.
4. [[development/classes/PlayerProgression|성장]], [[development/classes/Combat|전투]], [[development/classes/EnemyController|적 처리]] 중 관심 있는 부분.
5. [[development/classes/Renderer|Renderer]]의 출력 시작점과 세부 함수.

`main()`의 위치와 관계없이 모듈 정의가 끝난 뒤 진입점에서 호출합니다. `import space_z.main`은 게임 루프를 시작하지 않습니다.

## 사람이 플레이하는 경로

`python -m space_z` → `main()`의 준비 → 앱의 `handle_event()` → `update()` → 코어 `step()` → 앱의 `draw()` → 화면 표시 순서입니다. WASD·마우스 입력은 코어 행동과 월드 조준 좌표로 변환합니다. 앱의 디버그 출력이 `build_vector()`를 사용해도 사람 플레이를 `TankEnv`로 실행하는 구조는 아닙니다.

메인 메뉴·일시정지에서는 코어를 호출하지 않습니다. 강화·진화는 HUD에서 선택하며 전투가 계속됩니다. 메뉴 포커스와 확정 난이도는 별도 상태입니다. 자세한 입력·누적 시간은 [[development/classes/GameApplication|앱 상태]]에 있습니다.

## 학습 환경 경로

외부 프로그램 → `TankEnv.reset()/step()` → 같은 `GameCore` → 이벤트 소비·관찰·보상·종료 정보 반환 순서입니다. 모델의 행동 결정과 학습은 외부 프로그램의 역할입니다. 실제 학습용 `train.py`는 아직 없습니다. [[reinforcement-learning/environment|환경 인터페이스]]와 `scripts/random_agent_test.py`를 참고합니다.

## 한 프레임의 개요

연출·적 성장 → 플레이어 이동·조준 → 적별 행동·발사·재등장 → 플레이어 발사·천체·탄환 이동·명중·몸체 충돌·회복 → 천체 보충 → 프레임 증가·재장전 완료 → 플레이어 사망 확정입니다.

상세 순서는 [[development/classes/GameCore#한 프레임의 순서|GameCore.step]]에 한 번만 정리합니다. 사람 플레이는 기본 1/60초 단위, 한 화면 갱신당 최대 5프레임이며, 학습의 한 step은 기본 4개 게임 프레임입니다.

## 소유와 협력

`GameCore`는 월드와 개체 목록을, 각 담당 객체는 성장·전투·적 성장 상태를 소유합니다. `Tank` 같은 데이터 객체에는 체력이 저장되지만 실제 피해 규칙은 `Combat`이 처리합니다. [[development/classes/README|클래스 목차]]에서 보유 상태와 변경자를 함께 확인합니다.

코어·지형은 Pygame 없이 실행할 수 있습니다. 렌더러는 게임 상태를 읽어 표현하고 별도 연출 캐시를 갱신합니다. 줌은 공유 설정을 변경합니다. 설정의 지형 조건을 실행 중 바꿀 때는 실제 맵 재생성도 고려합니다. `TileMap.version`은 그림·관찰 캐시 갱신에 사용합니다.

상속 계층이나 ECS·별도 이벤트 버스는 추가하지 않았습니다. 코어 이벤트는 `pop_events()`로 소비하며 학습 보상 계산은 환경에 있습니다. [[development/flows/README|동작 흐름]]은 객체 간 요청을 따라갑니다.

위치가 포함된 점수 획득 사실은 코어의 `score_award_events`에 임시 보관합니다. 앱 또는 학습 환경이 이를 꺼내 렌더러에 전달하고, 실제 팝업 목록·표시 시간은 렌더러가 관리합니다. [[development/classes/GameCore#점수 획득 기록|기록과 전달]] → [[development/classes/Renderer#점수 팝업|팝업 관리]]로 이어집니다.

## 바꾸려는 기능으로 찾기

| 바꾸려는 것 | 정의·설정 | 실제 처리 |
|---|---|---|
| 버튼 이동·실행 | `menu_layout.build_menu_buttons()` | [[development/classes/GameApplication#관련 함수\|handle_event와 activate_menu_action]] |
| 버튼 위치·클릭 영역 | `menu_layout.build_menu_buttons()` | 앱 클릭 판정과 `Renderer._draw_menu()` |
| 벽 배치·통로·고립 방지 | `config.terrain.TerrainConfig` | `game.terrain.generate_random_map()`, `TileMap.is_connected()` |
| 벽 이미지·8×8 큰 블록 | `assets/etc/guard_*.png` | [[development/classes/Renderer#지형과 이미지\|_draw_full_wall_blocks와 _ensure_terrain]] |
| 우주선·포신·무기 수치 | `config/progression_definitions.py` | [[development/classes/Combat#발사 상태\|weapon_values와 발사 처리]] |
| 피해·처치·점수 | `GameConfig`, 우주선 피해 배율 | [[development/flows/damage-and-kills\|Combat → PlayerProgression]] |
| 스탯 강화·진화 | `config/progression_definitions.py` | [[development/flows/upgrades-and-evolution\|PlayerProgression → EnemyController]] |
| 적 감지·추적·성장 | `EnemyAIConfig` | [[development/classes/EnemyController\|EnemyController]] |
| 이미지·폭발·메인 배경 | `assets/` | `SpriteAssets`, [[development/classes/Renderer\|Renderer]] |
| 학습 관찰·보상·종료 | `ObsConfig`, `RewardConfig`, `EnvConfig` | [[reinforcement-learning/environment\|ObservationBuilder와 TankEnv]] |

[[development/README|개발 안내]] · [[README|문서 목차]]
