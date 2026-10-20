# 수정 위치와 검증

처음이라면 [[getting-started#개발 환경 설치|개발 환경 설치]]를 먼저 진행합니다. 기능에서 찾는 상세 표는 [[development/project-structure#바꾸려는 기능으로 찾기|프로젝트 구조]]에 있습니다.

- 스탯·기체·포신·진화 수치: `src/space_z/config/progression_definitions.py`
- 공통 월드·초기화·프레임 순서: `src/space_z/game/game_core.py`
- 성장·강화·진화: `src/space_z/game/player_progression.py`
- 탄약·사격·탄환·피해·충돌: `src/space_z/game/combat.py`
- 적 재등장·성장·AI: `src/space_z/game/enemy_controller.py`
- 개체 상태·행동 변환: `src/space_z/game/entities.py`, `src/space_z/game/actions.py`
- 지형·경로 탐색·선체 여유 검사: `src/space_z/game/terrain.py`, `maps/`, `src/space_z/config/terrain.py`
- 입력·메뉴 동작: `src/space_z/app.py`; 실행 준비·루프: `src/space_z/main.py`
- 화면·PNG 변환: `src/space_z/rendering/renderer.py`, `src/space_z/rendering/sprite_assets.py`
- 학습 관찰·보상: `src/space_z/rl/environment.py`

```powershell
python -m unittest discover -s tests -v
python scripts/random_agent_test.py
python scripts/render_screens.py
```

GUI 없는 테스트는 SDL dummy 드라이버로 실행합니다. 검증은 포인트 누적·5개 고정 행·1~5 키·클릭·전직 순서·21종 공격 패턴·순차 연사 시간차·헌터/프레데터 단발·탄 크기·관통과 벽 차단·잔탄과 재장전·2배 기체와 포신별 탄환 크기·최대 반경96px 기체의 전체 미로 통행·미니맵 위치/방향/파괴갱신/사격 전달·관찰 크기·seed 재현성을 포함합니다.

`scripts/render_screens.py`는 기존 문서 PNG를 덮어쓰므로 일반 테스트와 별도로 실행합니다.

문서용 화면은 실제 Renderer를 사용하지만 경험치와 전직 등 일부 상태를 직접 설정해 촬영합니다. 자연 플레이 기록은 아닙니다. 제공 우주선 PNG 원본은 수정하지 않습니다.

## 이번 구조 정리의 검증 결과

2026-10-20, Python 3.12 개발 설치 기준입니다.

- 전체 149개 테스트 중 148개 통과. 이전 키보드 이동 순서를 기대하는 테스트 1개의 불일치는 유지했습니다.
- 변경 전후 고정 seed·같은 입력의 게임 상태·이벤트·관찰·보상을 1,446개 시점에서 대조해 일치했습니다.
- 옮긴 클래스·함수 65개의 본문·기본값·decorator와 메인 루프를 대조했습니다. import 경로와 명시한 이름 변경을 제외한 계산·실행 순서는 같습니다.
- `python scripts/random_agent_test.py --steps 100` 통과. 맵 8개 조건의 무작위 실행, 랜덤 맵 100개 연결성, 같은 seed 재현성을 포함합니다.
- 다른 작업 디렉터리에서 설치된 패키지의 진입점·리소스 경로·실제 앱 루프와 flat/dict 학습 환경을 SDL dummy로 확인했습니다.
- 기존 이미지·맵·문서 PNG 114개의 해시를 대조했습니다. 문서 화면 생성 도구는 실행하지 않았습니다.

구조 정리 시점에는 실행 파일 빌드를 별도로 남겼으며, 이후 완료한 검증은 [[development/windows-release#이번 배포본 검증|Windows 배포 검증]]에 있습니다. 기존 테스트 불일치와 지형 캐시 검토 사항은 [[game/known-issues#기존 테스트 불일치와 캐시 검토|현재 제한]]에 정리했습니다.

## 점수 획득 기록과 팝업 분리 검증

점수 획득 사실은 [[development/classes/GameCore#점수 획득 기록|GameCore]], 팝업 목록·번호·유지 시간은 [[development/classes/Renderer#점수 팝업|Renderer]]가 소유합니다. 앱과 학습 환경이 이벤트를 꺼내 전달하며 화면 없는 학습은 매 코어 프레임 소비합니다.

- 전체 157개 테스트 중 156개 통과. 기존 키보드 이동 기대값 불일치 1개는 유지했습니다.
- 변경 전후 고정 seed·동일 입력의 게임 상태·전투 이벤트·관찰·보상이 1,446개 시점에서 일치했습니다. 이동한 화면 연출 상태는 게임 규칙 비교에서 분리했습니다.
- 여러 코어 프레임의 기록 전달, 한 번만 소비, 반복 그리기 시 불꽃 중복 방지, 팝업 만료 경계, 같은 프레임의 재시작 초기화, 학습 화면의 frame skip 전달과 화면 없는 환경의 기록 폐기를 검증했습니다.
- 메인 메뉴에서 다른 난이도에 포커스가 있을 때만 반투명 표시, 무한 스테이지·게임 나가기 포커스에서 선명한 표시, 마우스 우선 강조와 키보드 포커스, 원본 이미지 캐시의 투명도 보존을 화면 픽셀로 검증했습니다.

[[development/README|개발 목차]] · [[game/known-issues|현재 제한과 검토 사항]]
