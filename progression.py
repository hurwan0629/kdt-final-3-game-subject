"""성장 능력치, 21종 우주선 진화와 포신별 사격 명세."""
import math
from dataclasses import dataclass


@dataclass(frozen=True)
class RewardCard:
    key: str                         # 보상·능력치·우주선을 식별하는 내부 키
    title: str                       # 화면에 표시할 이름
    category: str                    # 보상 분류 (능력치 / 전직)
    description: tuple[str, ...]      # 화면에 줄별로 표시할 설명 목록


STAT_UPGRADES = (  # 스탯 강화 목록과 화면·숫자 단축키의 고정 순서
    RewardCard("hull", "체력", "능력치", ("최대 / 현재 체력 +25",)),  # 최대·현재 체력 강화
    RewardCard("damage", "공격력", "능력치", ("공격 피해 +25%",)),  # 탄환 공격력 강화
    RewardCard("range", "사거리 및 탄속도", "능력치", ("탄속 +20%, 수명 +15%",)),  # 탄속·수명 강화
    RewardCard("rapid", "발사속도", "능력치", ("발사 대기 -5%",)),  # 발사 간격 단축
    RewardCard("speed", "이동속도", "능력치", ("이동 가속도 +7%",)),  # 이동 가속도 강화
)
STAT_MAX_LEVEL = 7   # 능력치마다 올릴 수 있는 최대 단계


@dataclass(frozen=True)
class ShotSpec:
    # 각도는 기체 정면(오른쪽) 기준 rad. 포구 거리는 실제 선체 반지름 단위.
    angle: float = 0.0               # 기체 조준 방향 대비 포신 각도 (rad, 시계방향이 양수)
    lateral: float = 0.0             # 포신 방향의 오른쪽으로 치우친 포구 위치 (선체 반지름 배수)
    forward: float = 1.6187          # 포신 방향으로 나아간 포구 위치 (선체 반지름 배수)
    delay: int = 0                  # 발사 묶음 시작 후 지연 (프레임, 플레이어 연사 강화로 환산)
    damage: float = 1.0             # 우주선 무기 피해에 추가로 곱할 개별 탄환 피해 배율
    # 512px 원본의 밝은 회색 포신 내경 / 청록색 실선체 지름 × 90%.
    # 세계 탄환 반지름 = 선체 반지름 × caliber (투명 패딩에 영향받지 않음).
    caliber: float = 26 / 139 * 0.9  # 선체 반지름 대비 탄환 반지름 비율
    speed: float = 1.0              # 우주선 탄속에 추가로 곱할 개별 탄환 속도 배율
    life: float = 1.0               # 우주선 탄환 수명에 추가로 곱할 개별 탄환 수명 배율


@dataclass(frozen=True)
class ShipClass(RewardCard):
    parent: str = ""                # 이 우주선으로 진화하기 전 종류 키 (빈 문자열이면 이전 종류 없음)
    level: int = 1                  # 진화 단계 (1 / 10 / 20 / 30레벨)
    asset: str = "ships/Lv1_베이직"  # 확장자를 제외한 우주선 이미지 리소스 키
    shots: tuple[ShotSpec, ...] = (ShotSpec(),)  # 한 발사 묶음의 포신별 탄환 패턴
    damage: float = 1.0             # 기본 탄환 피해에 곱할 우주선 피해 배율
    cooldown: float = 1.0           # 기본 발사 대기에 곱할 간격 배율 (작을수록 빠름)
    speed: float = 1.0              # 기본 탄환 속도에 곱할 우주선 탄속 배율
    life: float = 1.0               # 기본 탄환 수명에 곱할 우주선 수명 배율
    hp_bonus: float = 0.0           # 기본 최대 체력에 더할 종류별 체력 보너스 (적은 절반 적용)
    radius_scale: float = 1.0       # 기본 선체 충돌 반지름에 곱할 크기 배율
    damage_taken: float = 1.0       # 받는 피해 배율 (0.8이면 피해 20% 감소)

    @property
    def angles(self):  # 발사 패턴 순서대로 포신 상대 각도 목록 반환
        return tuple(shot.angle for shot in self.shots)

    @property
    def muzzles(self):  # 발사 패턴 순서대로 포구 측면 위치 목록 반환
        return tuple(shot.lateral for shot in self.shots)


def _muzzle(angle, x, y, **kwargs):
    """선체 중심 기준 포구(x,y)를 포신 방향의 전방/측면 좌표로 바꾼다."""
    return ShotSpec(angle=angle, forward=x * math.cos(angle) + y * math.sin(angle),
                    lateral=-x * math.sin(angle) + y * math.cos(angle), **kwargs)


# 가디언 대구경 포신: (포구 전방 거리, 안쪽 폭 / 선체 지름). 원본 소형 포신 대신 그린다.
GUARDIAN_BARREL = (1.45, 0.2)  # 가디언 포구 전방 거리와 내경 비율 (선체 반지름·지름 기준)
BARREL_OVERRIDES = {"ships/Lv10_가디언": GUARDIAN_BARREL}  # 이미지 키별 대체 포신 크기

_CARDINAL = (  # 쿼드 윙의 전후좌우 4방향 동시 발사 패턴
    ShotSpec(forward=1.4969, caliber=24/161*0.9), ShotSpec(angle=math.pi/2, forward=1.3913, lateral=0.0373, caliber=24/161*0.9),  # 정면·기체 오른쪽 포신
    ShotSpec(angle=math.pi, forward=1.4224, caliber=24/161*0.9), ShotSpec(angle=-math.pi/2, forward=1.3913, lateral=-0.0373, caliber=24/161*0.9),  # 후면·기체 왼쪽 포신
)
SHIP_CLASSES = (  # 21종 우주선의 진화 관계·이미지·사격 패턴·능력치 정의
    # 1레벨: 시작 우주선
    ShipClass("rookie", "베이직", "전직", ("전방 단포 1문",)),
    # 10레벨: 첫 계열 선택 (베이직에서 직접 선택하므로 parent 생략)
    ShipClass("twin", "트윈", "전직", ("평행 쌍포 교차 2연사",), level=10,
              asset="ships/Lv10_트윈", shots=(ShotSpec(lateral=-0.3676, forward=1.6618, caliber=22/136*0.9), ShotSpec(lateral=0.3676, forward=1.6618, delay=3, caliber=22/136*0.9)),
              damage=0.8, cooldown=1.2),  # 탄환 피해 0.8배, 발사 간격 1.2배
    ShipClass("sniper", "스나이퍼", "전직", ("장거리 고속 단발 저격",), level=10,
              asset="ships/Lv10_스나이퍼", shots=(ShotSpec(forward=1.8144, caliber=22/167*0.9*2),),
              damage=1.9, cooldown=1.7, speed=1.71, life=1.4),  # 저격 계열 탄속 5% 감소; 피해·수명·발사 간격 유지
    ShipClass("flank", "플랭크", "전직", ("전후방 2방향 동시 사격",), level=10,
              asset="ships/Lv10_플랭크", shots=(ShotSpec(forward=1.5714, caliber=26/147*0.9), ShotSpec(angle=math.pi, forward=1.5170, caliber=24/147*0.9)), damage=0.72),  # 정면·후면 동시 발사, 탄환당 피해 감소
    ShipClass("guardian", "가디언", "전직", ("장갑 선체 · 전방 대구경포", "체력 +100 · 받는 피해 -20%"), level=10,
              asset="ships/Lv10_가디언", shots=(ShotSpec(forward=GUARDIAN_BARREL[0], caliber=GUARDIAN_BARREL[1] * 0.9),),
              damage=0.65, cooldown=1.0, hp_bonus=100, radius_scale=26/22, damage_taken=0.8),  # 체력 +100, 선체 확대, 받는 피해 20% 감소
    # 20레벨: parent로 지정한 10레벨 종류에서 진화
    ShipClass("dual_striker", "듀얼 스트라이커", "전직", ("중앙 쌍포 + 날개 부포", "전방 포구 4곳에서 순차 사격"),
              parent="twin", level=20, asset="ships/Lv20_듀얼 스트라이커",
              shots=(ShotSpec(lateral=-0.19, forward=1.36, caliber=22/158*0.9), ShotSpec(lateral=0.19, forward=1.36, delay=2, caliber=22/158*0.9),
                     ShotSpec(lateral=-0.48, forward=1.60, delay=4, caliber=19/158*0.9), ShotSpec(lateral=0.48, forward=1.60, delay=6, caliber=19/158*0.9)),
              damage=0.4, cooldown=0.75),  # 포신별 0·2·4·6프레임 순차 발사, 발사 간격 단축
    ShipClass("triple_wing", "트리플 윙", "전직", ("전방 3방향 부채꼴 동시 사격",),
              parent="twin", level=20, asset="ships/Lv20_트리플 윙",
              shots=(_muzzle(-math.pi/8, 1.4085, -0.7113, caliber=21/142*0.9), ShotSpec(forward=1.7746, caliber=24/142*0.9), _muzzle(math.pi/8, 1.4085, 0.7113, caliber=21/142*0.9)), damage=0.7),  # 정면과 양옆 22.5도 방향에 동시 발사
    ShipClass("railgunner", "레일거너", "전직", ("고속 저격탄 · 벽 차단",),
              parent="sniper", level=20, asset="ships/Lv20_레일거너",
              shots=(ShotSpec(forward=1.8842, caliber=16/190*0.9),), damage=2.15, cooldown=1.8,
              speed=2.28, life=1.6),  # 탄속 2.28배·수명 1.6배로 사거리 증가
    ShipClass("hunter", "헌터", "전직", ("장거리 단발 저격",),
              parent="sniper", level=20, asset="ships/Lv20_헌터",
              shots=(ShotSpec(forward=1.8621, caliber=19/174*0.9),),
              damage=2.3, cooldown=1.65, speed=1.805, life=1.5),  # 고피해 장거리 단발, 긴 발사 간격
    ShipClass("quad_wing", "쿼드 윙", "전직", ("전후좌우 4방향 동시 사격",),
              parent="flank", level=20, asset="ships/Lv20_쿼드 윙", shots=_CARDINAL, damage=0.48),  # 플랭크에서 진화, 공유 4방향 발사 패턴 사용
    ShipClass("twin_flank", "트윈 플랭크", "전직", ("전후방 평행 쌍포 교차 사격",),
              parent="flank", level=20, asset="ships/Lv20_트윈 플랭크",
              shots=(ShotSpec(lateral=-0.2987, forward=1.4286, caliber=21/154*0.9), ShotSpec(angle=math.pi, lateral=-0.2987, forward=1.5065, caliber=21/154*0.9),
                     ShotSpec(lateral=0.2987, forward=1.4286, delay=3, caliber=21/154*0.9), ShotSpec(angle=math.pi, lateral=0.2987, forward=1.5065, delay=3, caliber=21/154*0.9)),
              damage=0.45, cooldown=0.85),  # 전후방 쌍포를 두 묶음으로 나눠 3프레임 간격 발사
    ShipClass("bastion", "바스티온", "전직", ("중장갑 대형 선체 · 소형 쌍포", "체력 +220 · 받는 피해 -28%"),
              parent="guardian", level=20, asset="ships/Lv20_바스티온",
              shots=(ShotSpec(lateral=-0.1694, forward=1.2769, caliber=22/242*0.9), ShotSpec(lateral=0.1612, forward=1.2769, caliber=22/242*0.9)),
              damage=0.65, hp_bonus=220, radius_scale=40/22, damage_taken=0.72),  # 체력 +220, 대형 선체, 받는 피해 28% 감소
    ShipClass("aegis", "이지스", "전직", ("대형 방어 선체 · 전후방 소형포", "체력 +200 · 받는 피해 -30%"),
              parent="guardian", level=20, asset="ships/Lv20_이지스",
              shots=(ShotSpec(forward=1.2597, caliber=24/258*0.9), ShotSpec(angle=math.pi, forward=1.02, caliber=24/258*0.9)),
              damage=0.65, hp_bonus=200, radius_scale=40/22, damage_taken=0.7),  # 체력 +200, 대형 선체, 받는 피해 30% 감소
    # 30레벨: parent로 지정한 20레벨 종류에서 최종 진화
    ShipClass("gatling_storm", "개틀링 스톰", "전직", ("6개 포신에서 전방 고속 6연사",),
              parent="dual_striker", level=30, asset="ships/Lv30_개틀링 스톰",
              shots=tuple(ShotSpec(lateral=(i-2.5)*0.21, forward=1.7202-abs(i-2.5)*0.13, delay=i*2, caliber=width/168*0.9) for i, width in enumerate((8, 12, 22, 22, 12, 8))),  # 대칭 포신 6개를 2프레임 간격으로 순차 발사
              damage=0.27, cooldown=0.5, speed=1.25),  # 한 발 피해를 줄이고 발사 간격·탄속 강화
    ShipClass("penta_wing", "펜타 윙", "전직", ("넓은 전방 5방향 동시 탄막",),
              parent="triple_wing", level=30, asset="ships/Lv30_펜타 윙",
              shots=(_muzzle(-0.56, 0.9737, -1.0, caliber=19/152*0.9), _muzzle(-0.28, 1.3947, -0.5789, caliber=21/152*0.9), ShotSpec(forward=1.8026, caliber=24/152*0.9),
                     _muzzle(0.28, 1.3947, 0.5789, caliber=21/152*0.9), _muzzle(0.56, 0.9737, 1.0, caliber=19/152*0.9)), damage=0.6),  # 정면과 ±0.28·±0.56rad 방향에 5발 동시 발사
    ShipClass("hyper_railgun", "하이퍼 레일건", "전직", ("초장거리 최고속 저격탄",),
              parent="railgunner", level=30, asset="ships/Lv30_하이퍼 레일건",
              shots=(ShotSpec(forward=2.0099, caliber=16/202*0.9),), damage=3.2, cooldown=2.0,
              speed=3.04, life=2.0),  # 탄속 3.04배·수명 2배의 초장거리 저격
    ShipClass("predator", "프레데터", "전직", ("강한 초장거리 단발 저격",),
              parent="hunter", level=30, asset="ships/Lv30_프레데터",
              shots=(ShotSpec(forward=1.9514, caliber=18/185*0.9),),
              damage=3.27, cooldown=1.75, speed=2.09, life=1.7),  # 피해 3.27배의 장거리 단발 저격
    ShipClass("octa_star", "옥타 스타", "전직", ("45도 간격 8방향 전방위 사격",),
              parent="quad_wing", level=30, asset="ships/Lv30_옥타 스타",
              shots=tuple(ShotSpec(angle=i*math.pi/4, forward=1.3953, caliber=(22 if i%2 == 0 else 19)/172*0.9) for i in range(8)), damage=0.33),  # 45도 간격 8방향 발사, 직선·대각선 포신 구경 구분
    ShipClass("hexa_cruiser", "헥사 크루저", "전직", ("전후방 3연장포 6문 순차 사격",),
              parent="twin_flank", level=30, asset="ships/Lv30_헥사 크루저",
              shots=(ShotSpec(lateral=-0.364, forward=1.29, caliber=18/165*0.9), ShotSpec(angle=math.pi, lateral=0.364, forward=1.37, caliber=18/165*0.9),
                     ShotSpec(forward=1.47, delay=2, caliber=21/165*0.9), ShotSpec(angle=math.pi, forward=1.55, delay=2, caliber=21/165*0.9),
                     ShotSpec(lateral=0.364, forward=1.29, delay=4, caliber=18/165*0.9), ShotSpec(angle=math.pi, lateral=-0.364, forward=1.37, delay=4, caliber=18/165*0.9)),
              damage=0.44, cooldown=0.8),  # 전후방 각 3발을 0·2·4프레임에 짝지어 발사
    ShipClass("colossus", "콜로서스", "전직", ("초거대 중장갑 선체 · 소형 3연장포", "체력 +400 · 받는 피해 -40%"),
              parent="bastion", level=30, asset="ships/Lv30_콜로서스",
              shots=(ShotSpec(lateral=-0.1867, forward=1.19, caliber=7/300*0.9), ShotSpec(forward=1.29, caliber=10/300*0.9),
                     ShotSpec(lateral=0.18, forward=1.19, caliber=7/300*0.9)),
              damage=0.67, hp_bonus=400, radius_scale=46/22, damage_taken=0.6),  # 체력 +400, 초대형 선체, 받는 피해 40% 감소
    ShipClass("citadel", "시타델", "전직", ("최대 크기 성채 선체 · 사방 소형포", "체력 +440 · 받는 피해 -45%"),
              parent="aegis", level=30, asset="ships/Lv30_시타델",
              shots=tuple(ShotSpec(angle=i*math.pi/2, forward=1.2828, caliber=10/290*0.9) for i in range(4)),  # 90도 간격 사방 소형포 동시 발사
              damage=0.5, hp_bonus=440, radius_scale=48/22, damage_taken=0.55),  # 체력 +440, 최대 크기 선체, 받는 피해 45% 감소
)
SHIPS = {ship.key: ship for ship in SHIP_CLASSES}  # 종류 키로 우주선 정의를 조회하는 사전
# 적은 플레이어와 같은 진화 단계(Lv.1 / 10 / 20 / 30)의 우주선 중 하나를 쓴다.
SHIPS_BY_LEVEL = {level: tuple(ship.key for ship in SHIP_CLASSES if ship.level == level) for level in (1, 10, 20, 30)}  # 진화 단계별 적 종류 추첨 후보
SPECIAL_REWARDS = SHIP_CLASSES[1:]  # 시작 우주선을 제외한 진화 보상 정의
REWARD_CARDS = STAT_UPGRADES + SPECIAL_REWARDS  # 일반 능력치·진화 보상의 전체 목록
JOB_NAMES = {key: ship.title for key, ship in SHIPS.items()}  # 우주선 종류 키별 화면 표시 이름
FAMILIES = tuple(ship for ship in SHIP_CLASSES if ship.level == 10)  # 10레벨에 고르는 첫 진화 계열
# 이전 호출자가 이 이름을 가져와도 동작하지만 Q/Space 액티브는 없다.
SKILLS = {}  # 제거된 액티브 스킬의 이전 import를 유지하는 빈 사전


def stat_rows(width, height, cards=STAT_UPGRADES):  # 창 크기와 카드 목록으로 스탯 행의 배치 계산 (width는 호환용)
    start = height - 22 - 24 * len(cards)  # 하단 여백 22px, 행 간격 24px에 맞춘 첫 행 위치
    return [(card, (22, start + i * 24, 256, 22)) for i, card in enumerate(cards)]  # (카드, (x, y, 너비, 높이)) 목록


def special_cards(width, height, count=4):  # 진화 카드 count개의 고정 배치 계산 (width·height는 호환용)
    return [(14 + i * 98, 82, 90, 90) for i in range(count)]  # (x, y, 너비, 높이), 카드 크기 90px·간격 8px


def stat_panel_rect(width, height, cards=STAT_UPGRADES):  # 스탯 행을 감싸는 펼친 패널 영역 계산
    rows = stat_rows(width, height, cards)  # 카드별 행 배치
    top = rows[0][1][1] - 30  # 첫 행 위 제목 공간 30px 포함
    bottom = rows[-1][1][1] + rows[-1][1][3] + 8  # 마지막 행 아래 여백 8px 포함
    return (14, top, 272, bottom - top)  # 패널 (x, y, 너비, 높이)


def stat_collapsed_rect(width, height):
    """한동안 건드리지 않아 접힌 스탯 창 (클릭 / 마우스를 올리면 다시 펼침)."""
    return (14, height - 54, 196, 38)  # 접힌 패널 (x, y, 너비, 높이), 하단 여백 16px


STAT_PANEL_IDLE_SECONDS = 4.0   # 이 시간 동안 건드리지 않으면 스탯 창을 접는다


def stat_upgrades_visible(game):  # 성장 기능이 켜져 있고 플레이어가 생존 중인지 확인
    return game.cfg.progression_enabled and game.player.alive and not game.game_over


def player_stat_summary(game):  # 플레이어 상태를 화면 표시용 (항목명, 값) 목록으로 변환
    p, c = game.player, game.cfg  # 플레이어 개체와 기본 게임 설정
    spec, damage, cooldown, speed, life = game.combat.weapon_values(p)  # 강화·우주선·숙련을 반영한 무기 값
    return (
        ("체력", f"{p.hp:.0f} / {p.max_hp:.0f}"),  # 현재 / 최대 체력
        ("자가 수리", f"{(c.regen_rate * (p.max_hp / c.player_hp) + p.regen_bonus) * c.fps:.1f} / 초"),  # 피격 후 회복 지연이 끝났을 때의 초당 회복량
        ("주무기 피해 · 1발", f"{damage:.2f}"),  # 개별 ShotSpec 피해 배율 적용 전 한 발 기준 피해
        ("발사 간격", f"{(cooldown + 1) / c.fps:.2f}초"),  # 쿨다운이 0이 되는 다음 프레임 발사까지 포함한 간격
        ("탄속", f"{speed * c.fps:.0f} px / 초"),  # 프레임당 탄속을 초당 속도로 환산
        ("사거리", f"{speed * life:.0f} px"),  # 벽·대상 충돌이 없을 때 탄속 × 수명으로 계산한 기준 거리
        ("탄창", f"{p.ammo} / {p.max_ammo}" if c.limited_ammo else "무제한"),  # 탄약 제한 여부에 따른 잔탄 표시
        ("재장전 시간", f"{game.combat.reload_frames_total / c.fps:.2f}초"),  # 재장전 프레임 수를 초로 환산
        ("최고 이동 속도", f"{c.max_speed * p.accel_scale * c.fps:.0f} px / 초"),  # 기본 최고속도에 강화 배율을 적용한 초당 이동 속도
    )
