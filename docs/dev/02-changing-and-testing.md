# 수정 위치와 검증

- 스탯·기체·포신·진화 수치: `progression.py`
- 공통 월드·초기화·프레임 순서: `game_core.py`
- 성장·강화·진화: `gameplay/progression.py`
- 탄약·사격·탄환·피해·충돌: `gameplay/combat.py`
- 적 재등장·성장·AI: `gameplay/enemies.py`
- 개체 상태·행동 변환: `gameplay/entities.py`, `gameplay/actions.py`
- 지형·경로 탐색·선체 여유 검사: `terrain.py`, `maps/`, `config.py`
- 입력·화면·PNG 변환: `main.py`, `renderer.py`, `sprite_assets.py`
- 학습 관찰·보상: `env.py`

```powershell
python -m unittest discover -s tests -v
python random_agent_test.py
python docs/dev/render_screens.py
```

GUI 없는 테스트는 SDL dummy 드라이버로 실행합니다. 검증은 포인트 누적·5개 고정 행·1~5 키·클릭·전직 순서·21종 공격 패턴·순차 연사 시간차·헌터/프레데터 단발·탄 크기·첫 대상 타격과 벽 차단·잔탄과 재장전·2배 기체와 포신별 탄환 크기·최대 반경96px 기체의 전체 미로 통행·미니맵 위치/방향/파괴갱신/입력차단·관찰 크기·seed 재현성을 포함합니다.

`docs/dev/render_screens.py`는 기존 문서 PNG를 덮어쓰므로 일반 테스트와 별도로 실행합니다.

문서용 화면은 실제 Renderer를 사용하지만 경험치와 전직 등 일부 상태를 직접 설정해 촬영합니다. 자연 플레이 기록은 아닙니다. 제공 우주선 PNG 원본은 수정하지 않습니다.

[목차](../README.md)
