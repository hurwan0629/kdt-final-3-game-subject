# 게임 이미지 에셋

플레이어 우주선 21종은 사용자가 제공한 512 × 512px 투명 배경 PNG입니다. 파일명과 원본 RGBA 데이터를 그대로 유지합니다. 모든 우주선의 정면은 오른쪽(0도)이며, 적은 같은 그림의 선체를 붉은색·금색으로 바꿔 사용합니다. 방향성 탄환 원본은 위쪽을 향합니다.

화면용 로더는 청록색 실선체 경계를 측정해 선체 중심을 맞추고, 실선체 지름이 게임의 충돌 지름과 일치하도록 그립니다. 긴 포신과 투명 여백은 충돌 크기에 포함하지 않습니다. 전직 카드도 같은 이미지를 사용합니다. PNG 원본은 변경하지 않습니다.

## 진화 트리

- 베이직 → 트윈 → 듀얼스트라이커 → 개틀링스톰
- 베이직 → 트윈 → 트리플윙 → 펜타윙
- 베이직 → 스나이퍼 → 레일거너 → 하이퍼레일건
- 베이직 → 스나이퍼 → 헌터 → 프레데터
- 베이직 → 플랭크 → 쿼드윙 → 옥타스타
- 베이직 → 플랭크 → 트윈플랭크 → 헥사크루저
- 베이직 → 가디언 → 바스티온 → 콜로서스
- 베이직 → 가디언 → 이지스 → 시타델

진화는 Lv.10 / Lv.20 / Lv.30에 진행합니다. [제공된 구조도](pre/v2/references/우주선_진화트리.png)도 보관했습니다. 기능은 요청한 진화 트리와 무기 명세를 따릅니다.

| 레벨 | 우주선 | 원본 PNG |
|---|---|---|
| Lv10 | 가디언 | [ships/Lv10_가디언.png](ships/Lv10_가디언.png) |
| Lv10 | 스나이퍼 | [ships/Lv10_스나이퍼.png](ships/Lv10_스나이퍼.png) |
| Lv10 | 트윈 | [ships/Lv10_트윈.png](ships/Lv10_트윈.png) |
| Lv10 | 플랭크 | [ships/Lv10_플랭크.png](ships/Lv10_플랭크.png) |
| Lv1 | 베이직 | [ships/Lv1_베이직.png](ships/Lv1_베이직.png) |
| Lv20 | 듀얼 스트라이커 | [ships/Lv20_듀얼 스트라이커.png](ships/Lv20_듀얼%20스트라이커.png) |
| Lv20 | 레일거너 | [ships/Lv20_레일거너.png](ships/Lv20_레일거너.png) |
| Lv20 | 바스티온 | [ships/Lv20_바스티온.png](ships/Lv20_바스티온.png) |
| Lv20 | 이지스 | [ships/Lv20_이지스.png](ships/Lv20_이지스.png) |
| Lv20 | 쿼드 윙 | [ships/Lv20_쿼드 윙.png](ships/Lv20_쿼드%20윙.png) |
| Lv20 | 트리플 윙 | [ships/Lv20_트리플 윙.png](ships/Lv20_트리플%20윙.png) |
| Lv20 | 트윈 플랭크 | [ships/Lv20_트윈 플랭크.png](ships/Lv20_트윈%20플랭크.png) |
| Lv20 | 헌터 | [ships/Lv20_헌터.png](ships/Lv20_헌터.png) |
| Lv30 | 개틀링 스톰 | [ships/Lv30_개틀링 스톰.png](ships/Lv30_개틀링%20스톰.png) |
| Lv30 | 시타델 | [ships/Lv30_시타델.png](ships/Lv30_시타델.png) |
| Lv30 | 옥타 스타 | [ships/Lv30_옥타 스타.png](ships/Lv30_옥타%20스타.png) |
| Lv30 | 콜로서스 | [ships/Lv30_콜로서스.png](ships/Lv30_콜로서스.png) |
| Lv30 | 펜타 윙 | [ships/Lv30_펜타 윙.png](ships/Lv30_펜타%20윙.png) |
| Lv30 | 프레데터 | [ships/Lv30_프레데터.png](ships/Lv30_프레데터.png) |
| Lv30 | 하이퍼 레일건 | [ships/Lv30_하이퍼 레일건.png](ships/Lv30_하이퍼%20레일건.png) |
| Lv30 | 헥사 크루저 | [ships/Lv30_헥사 크루저.png](ships/Lv30_헥사%20크루저.png) |

## 그 외 에셋

2026-10-18에 `new-images/`로 제공된 PNG 20장을 실제 사용 폴더로 옮겨 적용했습니다. 파일의 원본 픽셀은 변경하지 않습니다.

| 경로 | 용도 |
|---|---|
| `backgrounds/deep_space.png`, `nebula.png` | 월드 배경 합성 |
| `backgrounds/main.png` | 메인 메뉴 전용 배경 |
| `objects/star_fragment.png`, `rock_planet.png`, `ring_planet.png` | 별 조각·암석 행성·고리 행성 |
| `objects/gravity_field.png` | 선택 기능인 중력장 (이전 이미지와 동일) |
| `etc/guard_01.png` ~ `guard_04.png` | 벽 이미지 4종. 꽉 찬 8×8 영역은 큰 이미지 한 장, 나머지는 타일별 표시 |
| `etc/boom_effect_01.png` ~ `boom_effect_08.png` | 우주선·천체 파괴 및 범위 폭발의 순차 연출 |
| `etc/home_selected.png`, `home_selected_normal.png` | 메인·일시정지 메뉴 버튼의 선택·일반 상태 |
| `projectiles/player_plasma.png`, `enemy_plasma.png`, `cannon_shell.png` | 일반 탄환·저격탄 |

장애물·버튼의 투명 여백은 로더에서 제외하고 기존 타일·클릭 영역 크기에 맞춰 표시합니다. 폭발 8장은 원본 비율을 유지한 공통 캔버스에 정렬합니다. 이미지 교체는 충돌·피해·성장·입력 판정에 영향을 주지 않습니다.

벽의 큰 이미지 표시는 생성 블록 크기가 8일 때만 적용합니다. 64칸 모두 일반 벽 또는 파괴 가능한 벽이어야 하며, 빈칸이 하나라도 있으면 그 블록 전체를 작은 이미지로 표시합니다. 벽 일부가 파괴되어 빈칸이 생기면 다음 지형 갱신 때 자동 전환됩니다. 파괴 가능한 영역의 갈색 구분과 타일별 손상 표시는 유지합니다.

교체 전 이미지와 기존 미사용 PNG 29장은 원래 폴더 구분을 유지해 [pre/v2/](pre/v2/README.md)에 보관했습니다. `new-images/`에는 제공된 ZIP 원본 3개가 남아 있으며 게임은 이 ZIP을 읽지 않습니다.

현재 사용하는 이미지의 해상도·투명도·바이트 크기·SHA-256·선체 경계는 [catalog.json](catalog.json)에 있습니다. 이전 목록은 [pre/v2/catalog.json](pre/v2/catalog.json), 기존 생성 이미지의 제작 기록은 [generation-prompts.json](references/generation-prompts.json)에 있습니다.
