# Space Z 문서

**게임을 해보려면 실행 안내부터, 코드를 이해하려면 개발 안내부터 읽으세요.** 각 문서는 필요한 상태나 동작으로 바로 이동할 수 있게 연결되어 있습니다.

| 알고 싶은 것 | 시작할 문서 |
|---|---|
| 설치하고 게임 실행하기 | [처음 실행하기](getting-started.md) |
| 조작·전투·강화·맵 이해하기 | [게임 안내 목차](game/README.md) |
| 폴더와 객체의 책임 이해하기 | [개발 안내 목차](development/README.md) |
| 특정 클래스의 속성과 변경 함수 찾기 | [클래스·상태 목차](development/classes/README.md) |
| 발사·처치·강화의 객체 간 연결 따라가기 | [동작 흐름 목차](development/flows/README.md) |
| 학습 환경에서 관찰·보상 받기 | [강화학습 안내 목차](reinforcement-learning/README.md) |
| 수정 위치와 검증 방법 찾기 | [수정과 테스트](development/testing-and-changes.md) |

## 추천 탐색 경로

- 체력이 궁금하다면: [[development/classes/Tank#체력 상태|Tank의 체력]] → [[development/classes/Combat#피해 적용|피해 적용]] → [[development/flows/damage-and-kills|적 처치와 성장]].
- 강화가 궁금하다면: [[development/classes/PlayerProgression#일반 강화|일반 강화]] → [[development/classes/EnemyController#적 갱신|적 스탯 갱신]].
- 화면이 궁금하다면: [[development/classes/Renderer#화면과 카메라|카메라·줌]] → [[development/classes/Bullet|탄환 상태]].

문서의 설정 기본값과 실제 판의 상태는 구분합니다. 코드의 인자·반환값 상세 설명은 각 클래스 문서의 소스 링크에서 확인할 수 있습니다. 문서는 `docs/`를 Obsidian vault 루트로 사용하는 링크를 포함하며 추가 플러그인이 필요하지 않습니다.
