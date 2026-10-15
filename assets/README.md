# 게임 이미지 에셋

플레이어 우주선 21종은 사용자가 제공한 512 × 512px 투명 배경 PNG입니다. 파일명과 원본 RGBA 데이터를 그대로 유지합니다. 모든 플레이어 우주선의 정면은 오른쪽(0도)입니다. 기존 적 우주선과 방향성 탄환은 위쪽을 향합니다.

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

진화는 Lv.10 / Lv.20 / Lv.30에 진행합니다. [제공된 구조도](references/우주선_진화트리.png)도 보관했습니다. 기능은 요청한 진화 트리와 무기 명세를 따릅니다.

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

기존 배경 2종, 경험치 천체 3종, 지형 이미지, 적 우주선 3종, 탄환 5종을 유지합니다. 현재 지형은 연결된 두꺼운 벽으로 그리며 은신 구름 이미지는 사용하지 않습니다. 예전 지형 PNG는 호환 자료로 보관합니다.

파일별 해상도·투명도·바이트 크기·SHA-256·선체 경계는 [catalog.json](catalog.json)에 있습니다. 기존 생성 이미지의 제작 기록은 [generation-prompts.json](references/generation-prompts.json)에 있습니다.
