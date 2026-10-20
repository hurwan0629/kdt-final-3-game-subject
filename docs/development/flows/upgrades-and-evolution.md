# 강화와 진화

## 시작 조건과 참여 객체

앱이 1–5·강화 버튼 또는 F2–F5·진화 카드를 선택할 때 시작합니다. `PlayerProgression`은 정의와 현재 포인트·대기 보상을 검사해 플레이어를 변경하고, 필요한 적 갱신을 `EnemyController`에 요청합니다. 선택 중에도 전투는 계속됩니다.

관련 상태: [[development/classes/PlayerProgression#일반 강화|강화 포인트·단계]], [[development/classes/PlayerProgression#진화와 숙련|진화 대기·숙련]], [[development/classes/Tank#개체별 능력치|기체 배율]], [[development/classes/EnemyController#적 갱신|적 갱신]].

## 일반 강화 순서

1. 앱이 선택한 스탯 키를 `upgrade_stat(key)`에 전달합니다. UI 클릭이 발사로 이어지지 않도록 앱의 발사 입력도 차단합니다.
2. `can_upgrade_stat()`가 키·남은 포인트·생존·종료·최대 단계·연사 제한을 검사합니다. 불가능하면 `False`이며 포인트를 쓰지 않습니다.
3. 가능한 경우 플레이어의 해당 능력치를 변경합니다. 예를 들어 `hull`은 최대 체력을 25 늘리고 현재 체력도 새 최대값 범위에서 25 늘립니다.
4. `upgrade_points`를 하나 줄이고 `stat_levels[key]`를 하나 늘립니다.
5. `_refresh_stats()`를 요청합니다. 적 목록 순서대로 대응 스탯 예산을 다시 배분하고 능력치·남은 발사 대기를 보정합니다.
6. 알림·스탯 선택지를 갱신하고 `True`를 반환합니다. 렌더러는 바뀐 상태를 다음 출력에서 읽습니다.

## 진화와 숙련 순서

1. 경험치가 10의 배수 레벨을 넘으면 대기 레벨을 순서대로 쌓고 `open_rewards()`로 현재 선택지를 준비합니다.
2. 앱이 `choose_reward(index)`를 호출합니다. 대기 보상과 유효한 정수 인덱스가 없으면 `False`를 반환합니다.
3. 플레이어의 종류·체력 차이·반지름·패턴 수를 적용하고 발사 대기와 예약 점사를 비웁니다.
4. 코어에 커진 선체의 위치 보정을 요청합니다. 진화 단계가 달라졌다면 `_promote_enemies()`로 적 종류·능력치·점사·위치를 갱신합니다.
5. 종류별 보상 선택 횟수를 늘리고 대기 목록 맨 앞을 소비합니다. 알림을 갱신하고 다음 대기 선택지를 준비한 뒤 `True`를 반환합니다.

10레벨은 첫 계열, 20·30레벨은 현재 기체의 직계 자식, 이후는 현재 기체의 숙련입니다. 숙련의 실제 공격력 배율은 `Combat.weapon_values()`가 계산합니다. 정의만 바꿨다고 이미 생성된 기체의 현재 체력이 자동 재설정되지는 않습니다.

## 예시와 주의할 구분

플레이어가 `hull`에 포인트 하나를 사용하면 플레이어의 강화 단계가 증가합니다. 적은 그 단계와 난이도 대응 비율로 구한 예산을 다시 무작위 배분하므로 모든 적이 똑같이 체력만 올리는 것은 아닙니다.

| 데이터 | 위치 |
|---|---|
| 강화 수치·우주선·포신·진화 관계 | `config/progression_definitions.py` |
| 플레이어 포인트·강화·진화 실제 적용 | `game/player_progression.py` |
| 적의 대응 스탯·진화 갱신 | `game/enemy_controller.py` |
| 패널 영역·표시용 수치 계산 | `rendering/progression_panel.py` |

새 게임과 N으로 시작한 새 맵은 성장·포인트를 초기화합니다. 일반 강화 포인트를 쓰지 않아도 이후 레벨업·진화 때문에 사라지지는 않습니다.

[[development/configuration|설정과 정의]] · [[development/classes/PlayerProgression|플레이어 성장 상태]] · [[development/flows/README|동작 목차]] · [[README|문서 목차]]
