# 강화학습 안내

현재는 학습 알고리즘을 실행하는 프로그램보다 **학습에 사용할 공통 게임 환경**을 제공합니다.

- [환경 인터페이스·관찰·보상](environment.md): `TankEnv.reset()/step()`과 반환 데이터.
- [[development/classes/GameCore|화면 없는 공통 게임 코어]]: 실제 규칙과 프레임 진행.
- [[development/configuration|학습 설정 위치]]: `ObsConfig`·`RewardConfig`·`EnvConfig`.
- [[development/testing-and-changes|무작위 행동·seed 재현성 검증]]: 개발 도구 실행.

학습의 한 step과 게임의 한 프레임은 다릅니다. 모델이 행동을 정하고 경험을 학습하는 코드는 이후 실제 학습 기능을 구현할 때 추가합니다.

[[getting-started|설치와 환경 사용 예시]] · [[README|문서 목차]]
