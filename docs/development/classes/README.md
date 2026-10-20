# 클래스와 상태

각 문서는 **역할 → 상태 묶음 → 속성 표 → 관련 함수 → 다른 객체·동작** 순서입니다. 내부 캐시·비활성 상태는 접힌 설명에 두었습니다.

| 찾는 대상 | 클래스 | 핵심 상태 |
|---|---|---|
| 입력과 메뉴 | [GameApplication](GameApplication.md) | 모드·버튼 포커스·누적 시간·클릭 |
| 공통 월드와 프레임 | [GameCore](GameCore.md) | 지형·개체 목록·프레임·이벤트 |
| 점수와 플레이어 성장 | [PlayerProgression](PlayerProgression.md) | 점수·레벨·강화·진화 |
| 발사와 전투 결과 | [Combat](Combat.md) | 탄환·재장전·전투 연출 |
| 적의 성장과 행동 | [EnemyController](EnemyController.md) | 공통 성장 단계; 적별 기억은 Tank |
| 화면과 표현 | [Renderer](Renderer.md) | 카메라·줌·점수 팝업·표시 캐시 |
| 플레이어·적 한 대 | [Tank](Tank.md) | 체력·이동·무장·AI |
| 탄환 한 발 | [Bullet](Bullet.md) | 위치·수명·피해·관통 |
| 파괴 가능한 천체 | [Shape](Shape.md) | 표류·체력·점수 |
| 빔 표시 | [Beam](Beam.md) | 시작·끝 좌표·수명 |
| 폭발 표시 | [Explosion](Explosion.md) | 중심·크기·수명 |

값이 저장되는 클래스와 값을 변경하는 클래스가 다를 수 있습니다. 예를 들어 [[development/classes/Tank#체력 상태|Tank.hp]]의 변경자는 [[development/classes/Combat#피해 적용|Combat]]과 성장·적 갱신 처리입니다.

[[development/flows/README|동작 흐름]] · [[development/configuration|설정 클래스]] · [[development/README|개발 안내]] · [[README|문서 목차]]
