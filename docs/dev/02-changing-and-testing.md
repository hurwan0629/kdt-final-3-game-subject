---
title: 수정 위치와 검증
updated: 2026-10-15
tags: [space-skirmish, dev]
---

# 수정 위치와 검증

수치만 바꾸는 일과 동작을 바꾸는 일을 구분하면 수정 범위를 찾기 쉽습니다. 현재 구조에서는 수치는 `config.py`, 규칙은 `game_core.py`, 입력과 사용자 흐름은 `main.py`, 그림은 `renderer.py`가 출발점입니다.

## 바꾸려는 내용별 출발점

| 바꾸려는 것 | 먼저 볼 곳 | 함께 확인할 곳 |
|---|---|---|
| 기본 체력·피해량·탄창·재장전 | `GameConfig` | 코어의 `_fire()`, `_regen_player()`, `request_reload()`, HUD |
| 이동감·관성 | `accel`, `friction`, `_apply_tank_control()` | 지형 감속, 속도 강화 카드 |
| WASD·조준·단축키 | `read_player_input()`, `GameApplication.handle_event()` | 조작 안내, 입력 테스트 |
| 카드 추가·삭제·효과 | `REWARD_CARDS`, `choose_reward()` | 전직 자격, 설명, 랜덤 3장 선택, 보상 테스트 |
| 메인/설정 메뉴 | `menu_buttons()`, `activate()`, `_draw_menu()` | 버튼 영역과 클릭 판정, 설정 유지 여부 |
| 줌·카메라 | `set_zoom()`, 좌표 변환, `_update_camera()` | 마우스 조준 역변환, 화면 가장자리, HUD 크기 |
| 새 맵 | `maps/*.txt` | 기본 20×15, P 한 개, 연결성, 3×3 반복 구역 연결 |
| 새 지형 | `CHAR_TO_TILE`, `TileMap`, 코어 지형 처리 | 그림, 충돌, 시야, 관찰 채널, 맵 검증 |
| 적 난이도 | `EnemyAIConfig`, `_enemy_ai()` | 기억·거리·조준·경로·재등장 |
| 학습 보상·관찰 | `RewardConfig`, `ObservationBuilder`, `TankEnv` | 관찰 공간 크기와 기존 정책 호환성 |

`spawn_margin`은 설정에 존재하지만 현재 스폰 함수에서 사용하지 않습니다. 이 값만 바꿔도 스폰 여백이 달라진다고 생각하면 안 됩니다. 실제 스폰은 빈 타일과 탱크와의 거리 조건을 사용합니다.

## 검증 명령

의존성이 설치된 Python으로 프로젝트 루트에서 실행합니다.

```bash
python -m unittest discover -s tests -v
python random_agent_test.py --steps 200
```

현재 테스트는 메뉴·재장전, WASD와 마우스 입력, 카드 효과, 카메라, 맵 연결성, 기본 학습 환경을 확인합니다. 랜덤 에이전트 검사는 여러 맵에서 관찰·보상의 유효성, 벽에 끼는 상태, seed 재현성을 봅니다. 화면의 재미나 난이도 균형까지 판정하지는 않습니다.

맵·보상·카메라를 바꿀 때는 관련 테스트를 먼저 실행하면 됩니다. 문구만 바꿨다면 화면에서 잘리는지 확인하는 것이 더 유용합니다.

## 문서 이미지 다시 만들기

```bash
python docs/dev/render_screens.py
```

실제 렌더러로 `docs/game/assets/`의 PNG를 갱신합니다. 별도 창을 띄우지 않고, 고정 seed와 설명용 상태를 사용합니다. 게임 코드·맵·설정 파일을 저장하거나 변경하지 않습니다. 레벨업 장면의 190점과 강제 사망, 숨기 위치는 화면 설명을 위한 재현입니다.

새 화면을 추가할 때는 이미지와 문서 링크도 함께 갱신하세요. 문서 폴더를 옮겨도 읽을 수 있도록 절대 경로 대신 상대 경로를 유지하는 것이 좋습니다.

## 개발 실행과 배포

필수 의존성은 Pygame과 NumPy입니다. Gymnasium은 선택 사항이며, 없으면 학습 인터페이스의 간단한 대체 클래스를 사용합니다.

```bash
pip install -r requirements.txt
python main.py --seed 42
python main.py --map belt --stage2
```

PyInstaller 배포에서는 `config.resource_path()`가 실행 파일의 임시 리소스 경로를 지원합니다. 별도 게임 이미지 파일은 없지만 `maps/`는 함께 포함해야 합니다. 문서 PNG는 게임 실행에 필요하지 않습니다.

다음: [강화학습 환경 →](03-rl-environment.md) · [목차](../README.md)
