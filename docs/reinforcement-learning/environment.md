# 강화학습 환경

`TankEnv`는 같은 `GameCore`를 Gymnasium 형태의 reset/step 인터페이스로 감쌉니다. 기본값은 성장·탄약 제한이 꺼지고, 이동 9방향 × 회전 3방향의 27개 행동으로 자동 발사합니다.

환경은 설정과 환경 step 수를 보관하고, `ObservationBuilder`는 관찰 설정과 지형 격자 캐시를 보관합니다. `reset()`은 같은 코어를 초기화해 `(observation, info)`를 반환합니다. `step()`은 기본 4개 코어 프레임을 진행하며 사망하면 일찍 중단하고, `(observation, reward, terminated, truncated, info)`를 반환합니다. 모델이 행동을 고르고 학습하는 코드는 외부 프로그램에 둡니다.

## 관찰

은신 관찰값과 채널을 제거해 기본 float32 관찰은 **241차원**입니다. 기존 363차원 학습 모델은 입력 크기가 달라 재학습 또는 별도 변환이 필요합니다.

| 부분 | 크기 |
|---|---|
| 플레이어 위치·속도·체력·조준·발사 대기 | 8 |
| 가까운 적 3개 | 24 |
| 천체 8개 | 48 |
| 적 탄환 8개 | 40 |
| 벽 채널 11×11 | 121 |

중력장과 파괴 가능 벽을 모두 켜면 483차원입니다. `obs_mode="dict"`는 벡터와 지형을 나누고, 선택 레이 센서도 지원합니다. 적은 은신으로 제외되지 않습니다.

```python
from space_z.rl.environment import TankEnv
env = TankEnv()
obs, info = env.reset(seed=42)
obs, reward, terminated, truncated, info = env.step(0)
```

사용자 지정 설정에서 성장을 켜면 `env.game.progression.upgrade_stat(key)`와 `env.game.progression.choose_reward(index)`로 별도 선택합니다. 액티브 스킬과 관련 info 항목은 제거했습니다.

학습 보상은 `RewardConfig`와 `compute_reward()`에서 계산하고, 게임 점수·경험치와 분리합니다. 기본 3000 step은 truncated, 사망은 terminated입니다. 동일 seed·행동·성장 선택은 재현되며 줌은 관찰에 영향을 주지 않습니다.

`info`에는 점수·처치·맵·게임 프레임·환경 step·누적 이벤트와 성장·탄약·재장전 상태가 들어갑니다. 정확한 키는 코드의 `TankEnv._info()`를 확인합니다. `render_mode="human"`일 때만 렌더러를 생성하며 기본 실행은 화면을 만들지 않습니다.

점수 팝업용 획득 기록은 학습 보상용 이벤트와 별도로 처리합니다. 화면 없는 `step()`은 매 코어 프레임 `pop_score_award_events()`를 호출해 기록을 버립니다. `render_mode="human"`은 여러 프레임의 기록을 `render()`에서 꺼내 렌더러에 한 번 전달하며, `reset()`은 기존 팝업도 초기화합니다. 이 기록은 관찰·보상·`info`에 추가하지 않습니다.

구현: [environment.py](../../src/space_z/rl/environment.py) · 설정: [[development/configuration|관찰·보상·환경 설정]] · [[reinforcement-learning/README|강화학습 목차]] · [[README|문서 목차]]
