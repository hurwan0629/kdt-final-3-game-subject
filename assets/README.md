# Space Skirmish PNG 에셋

생성일: 2026-10-15. 내장 `image_gen`으로 제작했습니다. 현재 게임에 연결한 이미지 에셋입니다. 원본 PNG를 유지하고 화면에서 크기·회전을 조절합니다.

## 공통 규칙

- 배경을 제외한 PNG는 투명 배경입니다. 원본의 알파 채널을 유지합니다.
- 우주선과 방향이 있는 탄알은 위쪽(12시 방향)을 향합니다. 좌표는 오른쪽이 +X, 아래쪽이 +Y입니다.
- PNG 30개 모두 1254 × 1254px 정사각형 원본입니다. 게임에 연결할 때 화면 표시 크기와 충돌 범위를 따로 정합니다.
- 이미지에는 이름이나 설명을 넣지 않았습니다. 이름은 게임 UI에서 별도로 표시합니다.
- 참고 이미지의 계열 색을 따라 쌍포·저격은 청색, 개틀링은 주황색, 수호는 녹색, 적군은 적색 계열입니다.
- 개별 PNG는 애니메이션이 없는 정지 스프라이트입니다.

## 전직 카드에 적용할 디자인 메모

좌상단 위치는 유지합니다. 작은 정사각형 카드에 **우주선 이미지와 우주선명만** 표시하는 방향입니다. 현재 카드는 90 × 90px, 이미지는 62 × 62px입니다. 상세 설명은 상시 카드에 넣지 않습니다. 상세 효과는 마우스를 올렸을 때만 보여줍니다. 전직 선택지와 플레이어 선체는 같은 PNG를 사용합니다.

## 전직 연결

| Lv.10 계열 | Lv.20 진화 A → Lv.30 스킬 | Lv.20 진화 B → Lv.30 스킬 |
|---|---|---|
| 쌍포선 | 삼연포선 → 전방위 탄막 | 십자포선 → 회전 포탑 |
| 저격선 | 레일건선 → 차지 빔 | 기뢰선 → 일제 기폭 |
| 개틀링선 | 산탄선 → 과부하 | 유도탄선 → 미사일 일제사격 |
| 수호선 | 추진선 → 워프 대시 | 돌격선 → 램 차지 |

## 우주선

기본 우주선 1종, Lv.10 계열 4종, Lv.20 진화 8종입니다.

| 미리보기 | 이름 | 파일 |
|---|---|---|
| <img src="ships/rookie.png" width="96" alt="기본 우주선"> | 기본 우주선 | [ships/rookie.png](ships/rookie.png) |
| <img src="ships/twin.png" width="96" alt="쌍포선"> | 쌍포선 | [ships/twin.png](ships/twin.png) |
| <img src="ships/triple.png" width="96" alt="삼연포선"> | 삼연포선 | [ships/triple.png](ships/triple.png) |
| <img src="ships/cross.png" width="96" alt="십자포선"> | 십자포선 | [ships/cross.png](ships/cross.png) |
| <img src="ships/sniper.png" width="96" alt="저격선"> | 저격선 | [ships/sniper.png](ships/sniper.png) |
| <img src="ships/railgun.png" width="96" alt="레일건선"> | 레일건선 | [ships/railgun.png](ships/railgun.png) |
| <img src="ships/minelayer.png" width="96" alt="기뢰선"> | 기뢰선 | [ships/minelayer.png](ships/minelayer.png) |
| <img src="ships/gatling.png" width="96" alt="개틀링선"> | 개틀링선 | [ships/gatling.png](ships/gatling.png) |
| <img src="ships/shotgun.png" width="96" alt="산탄선"> | 산탄선 | [ships/shotgun.png](ships/shotgun.png) |
| <img src="ships/homing.png" width="96" alt="유도탄선"> | 유도탄선 | [ships/homing.png](ships/homing.png) |
| <img src="ships/guardian.png" width="96" alt="수호선"> | 수호선 | [ships/guardian.png](ships/guardian.png) |
| <img src="ships/booster.png" width="96" alt="추진선"> | 추진선 | [ships/booster.png](ships/booster.png) |
| <img src="ships/ram.png" width="96" alt="돌격선"> | 돌격선 | [ships/ram.png](ships/ram.png) |

## 배경

어두운 심우주와 청보라 성운 배경입니다. 반복 사용을 고려해 요청했으며, 실제 맵에 반복 배치했을 때 이음새 확인이 필요합니다.

| 미리보기 | 이름 | 파일 |
|---|---|---|
| <img src="backgrounds/deep_space.png" width="96" alt="심우주 배경"> | 심우주 배경 | [backgrounds/deep_space.png](backgrounds/deep_space.png) |
| <img src="backgrounds/nebula.png" width="96" alt="성운 배경"> | 성운 배경 | [backgrounds/nebula.png](backgrounds/nebula.png) |

## 맵 오브젝트

벽·파괴 가능한 소행성·은폐 구름·감속 중력장과 기존 천체 3종입니다.

| 미리보기 | 이름 | 파일 |
|---|---|---|
| <img src="objects/asteroid_wall.png" width="96" alt="소행성 벽"> | 소행성 벽 | [objects/asteroid_wall.png](objects/asteroid_wall.png) |
| <img src="objects/breakable_asteroid.png" width="96" alt="파괴 가능한 소행성"> | 파괴 가능한 소행성 | [objects/breakable_asteroid.png](objects/breakable_asteroid.png) |
| <img src="objects/gas_cloud.png" width="96" alt="은폐 가스 구름"> | 은폐 가스 구름 | [objects/gas_cloud.png](objects/gas_cloud.png) |
| <img src="objects/gravity_field.png" width="96" alt="감속 중력장"> | 감속 중력장 | [objects/gravity_field.png](objects/gravity_field.png) |
| <img src="objects/star_fragment.png" width="96" alt="별 조각"> | 별 조각 | [objects/star_fragment.png](objects/star_fragment.png) |
| <img src="objects/rock_planet.png" width="96" alt="암석 행성"> | 암석 행성 | [objects/rock_planet.png](objects/rock_planet.png) |
| <img src="objects/ring_planet.png" width="96" alt="고리 행성"> | 고리 행성 | [objects/ring_planet.png](objects/ring_planet.png) |

## 적군

정찰선·전투선·중장갑선의 시각 에셋입니다. 적 종류별 전투 규칙을 추가한 것은 아닙니다.

| 미리보기 | 이름 | 파일 |
|---|---|---|
| <img src="enemies/scout.png" width="96" alt="적 정찰선"> | 적 정찰선 | [enemies/scout.png](enemies/scout.png) |
| <img src="enemies/fighter.png" width="96" alt="적 전투선"> | 적 전투선 | [enemies/fighter.png](enemies/fighter.png) |
| <img src="enemies/heavy.png" width="96" alt="적 중장갑선"> | 적 중장갑선 | [enemies/heavy.png](enemies/heavy.png) |

## 탄알

플레이어/적 플라즈마 탄, 대포 탄, 유도 미사일, 기뢰입니다.

| 미리보기 | 이름 | 파일 |
|---|---|---|
| <img src="projectiles/player_plasma.png" width="96" alt="플레이어 플라즈마 탄"> | 플레이어 플라즈마 탄 | [projectiles/player_plasma.png](projectiles/player_plasma.png) |
| <img src="projectiles/enemy_plasma.png" width="96" alt="적 플라즈마 탄"> | 적 플라즈마 탄 | [projectiles/enemy_plasma.png](projectiles/enemy_plasma.png) |
| <img src="projectiles/cannon_shell.png" width="96" alt="대포 탄"> | 대포 탄 | [projectiles/cannon_shell.png](projectiles/cannon_shell.png) |
| <img src="projectiles/homing_missile.png" width="96" alt="유도 미사일"> | 유도 미사일 | [projectiles/homing_missile.png](projectiles/homing_missile.png) |
| <img src="projectiles/mine.png" width="96" alt="기뢰"> | 기뢰 | [projectiles/mine.png](projectiles/mine.png) |

## 제작 기록

파일별 해상도·투명도·크기·SHA-256은 [catalog.json](catalog.json)에 있습니다. PNG 30개의 파일 손상·정사각형 크기·배경 알파와 미리보기 링크를 확인했습니다.

최종 생성 프롬프트와 제작 목록은 [generation-prompts.json](references/generation-prompts.json)에 있습니다. 각 파일은 별도로 생성했으며, 첨부된 전직 트리 그림을 그대로 잘라낸 이미지는 아닙니다. 같은 기준으로 다시 생성하거나 외형을 수정할 때 이 기록을 참고하세요.
