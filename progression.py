"""성장 능력치, 21종 우주선 진화와 포신별 사격 명세."""
import math
from dataclasses import dataclass


@dataclass(frozen=True)
class RewardCard:
    key: str
    title: str
    category: str
    description: tuple[str, ...]


STAT_UPGRADES = (
    RewardCard("hull", "체력", "능력치", ("최대 / 현재 체력 +25",)),
    RewardCard("damage", "공격력", "능력치", ("공격 피해 +25%",)),
    RewardCard("range", "사거리 및 탄속도", "능력치", ("탄속 +20%, 수명 +15%",)),
    RewardCard("rapid", "발사속도", "능력치", ("발사 대기 -5%",)),
    RewardCard("speed", "이동속도", "능력치", ("이동 가속도 +7%",)),
)
STAT_MAX_LEVEL = 7   # 능력치마다 올릴 수 있는 최대 단계


@dataclass(frozen=True)
class ShotSpec:
    # 각도는 기체 정면(오른쪽) 기준 rad. 포구 거리는 실제 선체 반지름 단위.
    angle: float = 0.0
    lateral: float = 0.0
    forward: float = 1.6187
    delay: int = 0
    damage: float = 1.0
    # 512px 원본의 밝은 회색 포신 내경 / 청록색 실선체 지름 × 90%.
    # 세계 탄환 반지름 = 선체 반지름 × caliber (투명 패딩에 영향받지 않음).
    caliber: float = 26 / 139 * 0.9
    speed: float = 1.0
    life: float = 1.0


@dataclass(frozen=True)
class ShipClass(RewardCard):
    parent: str = ""
    level: int = 1
    asset: str = "ships/Lv1_베이직"
    shots: tuple[ShotSpec, ...] = (ShotSpec(),)
    damage: float = 1.0
    cooldown: float = 1.0
    speed: float = 1.0
    life: float = 1.0
    hp_bonus: float = 0.0
    radius_scale: float = 1.0
    damage_taken: float = 1.0

    @property
    def angles(self):
        return tuple(shot.angle for shot in self.shots)

    @property
    def muzzles(self):
        return tuple(shot.lateral for shot in self.shots)


def _muzzle(angle, x, y, **kwargs):
    """선체 중심 기준 포구(x,y)를 포신 방향의 전방/측면 좌표로 바꾼다."""
    return ShotSpec(angle=angle, forward=x * math.cos(angle) + y * math.sin(angle),
                    lateral=-x * math.sin(angle) + y * math.cos(angle), **kwargs)


# 가디언 대구경 포신: (포구 전방 거리, 안쪽 폭 / 선체 지름). 원본 소형 포신 대신 그린다.
GUARDIAN_BARREL = (1.45, 0.2)
BARREL_OVERRIDES = {"ships/Lv10_가디언": GUARDIAN_BARREL}

_CARDINAL = (
    ShotSpec(forward=1.4969, caliber=24/161*0.9), ShotSpec(angle=math.pi/2, forward=1.3913, lateral=0.0373, caliber=24/161*0.9),
    ShotSpec(angle=math.pi, forward=1.4224, caliber=24/161*0.9), ShotSpec(angle=-math.pi/2, forward=1.3913, lateral=-0.0373, caliber=24/161*0.9),
)
SHIP_CLASSES = (
    ShipClass("rookie", "베이직", "전직", ("전방 단포 1문",)),
    ShipClass("twin", "트윈", "전직", ("평행 쌍포 교차 2연사",), level=10,
              asset="ships/Lv10_트윈", shots=(ShotSpec(lateral=-0.3676, forward=1.6618, caliber=22/136*0.9), ShotSpec(lateral=0.3676, forward=1.6618, delay=3, caliber=22/136*0.9)),
              damage=0.8, cooldown=0.8),
    ShipClass("sniper", "스나이퍼", "전직", ("장거리 고속 단발 저격",), level=10,
              asset="ships/Lv10_스나이퍼", shots=(ShotSpec(forward=1.8144, caliber=22/167*0.9*2),),
              damage=2.5, cooldown=1.7, speed=1.8, life=1.4),
    ShipClass("flank", "플랭크", "전직", ("전후방 2방향 동시 사격",), level=10,
              asset="ships/Lv10_플랭크", shots=(ShotSpec(forward=1.5714, caliber=26/147*0.9), ShotSpec(angle=math.pi, forward=1.5170, caliber=24/147*0.9)), damage=0.85),
    ShipClass("guardian", "가디언", "전직", ("장갑 선체 · 전방 대구경포", "체력 +100 · 받는 피해 -20%"), level=10,
              asset="ships/Lv10_가디언", shots=(ShotSpec(forward=GUARDIAN_BARREL[0], caliber=GUARDIAN_BARREL[1] * 0.9),),
              damage=0.4, cooldown=1.0, hp_bonus=100, radius_scale=26/22, damage_taken=0.8),
    ShipClass("dual_striker", "듀얼 스트라이커", "전직", ("중앙 쌍포 + 날개 부포", "전방 포구 4곳에서 순차 사격"),
              parent="twin", level=20, asset="ships/Lv20_듀얼 스트라이커",
              shots=(ShotSpec(lateral=-0.19, forward=1.36, caliber=22/158*0.9), ShotSpec(lateral=0.19, forward=1.36, delay=2, caliber=22/158*0.9),
                     ShotSpec(lateral=-0.48, forward=1.60, delay=4, caliber=19/158*0.9), ShotSpec(lateral=0.48, forward=1.60, delay=6, caliber=19/158*0.9)),
              damage=0.8, cooldown=0.75),
    ShipClass("triple_wing", "트리플 윙", "전직", ("전방 3방향 부채꼴 동시 사격",),
              parent="twin", level=20, asset="ships/Lv20_트리플 윙",
              shots=(_muzzle(-math.pi/8, 1.4085, -0.7113, caliber=21/142*0.9), ShotSpec(forward=1.7746, caliber=24/142*0.9), _muzzle(math.pi/8, 1.4085, 0.7113, caliber=21/142*0.9)), damage=0.85),
    ShipClass("railgunner", "레일거너", "전직", ("고속 저격탄 · 벽 차단",),
              parent="sniper", level=20, asset="ships/Lv20_레일거너",
              shots=(ShotSpec(forward=1.8842, caliber=16/190*0.9),), damage=3.5, cooldown=1.8,
              speed=2.4, life=1.6),
    ShipClass("hunter", "헌터", "전직", ("장거리 단발 저격",),
              parent="sniper", level=20, asset="ships/Lv20_헌터",
              shots=(ShotSpec(forward=1.8621, caliber=19/174*0.9),),
              damage=2.0, cooldown=1.65, speed=1.9, life=1.5),
    ShipClass("quad_wing", "쿼드 윙", "전직", ("전후좌우 4방향 동시 사격",),
              parent="flank", level=20, asset="ships/Lv20_쿼드 윙", shots=_CARDINAL, damage=0.85),
    ShipClass("twin_flank", "트윈 플랭크", "전직", ("전후방 평행 쌍포 교차 사격",),
              parent="flank", level=20, asset="ships/Lv20_트윈 플랭크",
              shots=(ShotSpec(lateral=-0.2987, forward=1.4286, caliber=21/154*0.9), ShotSpec(angle=math.pi, lateral=-0.2987, forward=1.5065, caliber=21/154*0.9),
                     ShotSpec(lateral=0.2987, forward=1.4286, delay=3, caliber=21/154*0.9), ShotSpec(angle=math.pi, lateral=0.2987, forward=1.5065, delay=3, caliber=21/154*0.9)),
              damage=0.8, cooldown=0.85),
    ShipClass("bastion", "바스티온", "전직", ("중장갑 대형 선체 · 소형 쌍포", "체력 +220 · 받는 피해 -28%"),
              parent="guardian", level=20, asset="ships/Lv20_바스티온",
              shots=(ShotSpec(lateral=-0.1694, forward=1.2769, caliber=10/242*0.9), ShotSpec(lateral=0.1612, forward=1.2769, caliber=10/242*0.9)),
              damage=0.55, hp_bonus=220, radius_scale=40/22, damage_taken=0.72),
    ShipClass("aegis", "이지스", "전직", ("대형 방어 선체 · 전후방 소형포", "체력 +200 · 받는 피해 -30%"),
              parent="guardian", level=20, asset="ships/Lv20_이지스",
              shots=(ShotSpec(forward=1.2597, caliber=12/258*0.9), ShotSpec(angle=math.pi, forward=1.02, caliber=12/258*0.9)),
              damage=0.55, hp_bonus=200, radius_scale=40/22, damage_taken=0.7),
    ShipClass("gatling_storm", "개틀링 스톰", "전직", ("6개 포신에서 전방 고속 6연사",),
              parent="dual_striker", level=30, asset="ships/Lv30_개틀링 스톰",
              shots=tuple(ShotSpec(lateral=(i-2.5)*0.21, forward=1.7202-abs(i-2.5)*0.13, delay=i*2, caliber=width/168*0.9) for i, width in enumerate((8, 12, 22, 22, 12, 8))),
              damage=0.65, cooldown=0.5, speed=1.25),
    ShipClass("penta_wing", "펜타 윙", "전직", ("넓은 전방 5방향 동시 탄막",),
              parent="triple_wing", level=30, asset="ships/Lv30_펜타 윙",
              shots=(_muzzle(-0.56, 0.9737, -1.0, caliber=19/152*0.9), _muzzle(-0.28, 1.3947, -0.5789, caliber=21/152*0.9), ShotSpec(forward=1.8026, caliber=24/152*0.9),
                     _muzzle(0.28, 1.3947, 0.5789, caliber=21/152*0.9), _muzzle(0.56, 0.9737, 1.0, caliber=19/152*0.9)), damage=0.85),
    ShipClass("hyper_railgun", "하이퍼 레일건", "전직", ("초장거리 최고속 저격탄",),
              parent="railgunner", level=30, asset="ships/Lv30_하이퍼 레일건",
              shots=(ShotSpec(forward=2.0099, caliber=16/202*0.9),), damage=5.0, cooldown=2.0,
              speed=3.2, life=2.0),
    ShipClass("predator", "프레데터", "전직", ("강한 초장거리 단발 저격",),
              parent="hunter", level=30, asset="ships/Lv30_프레데터",
              shots=(ShotSpec(forward=1.9514, caliber=18/185*0.9),),
              damage=2.5, cooldown=1.75, speed=2.2, life=1.7),
    ShipClass("octa_star", "옥타 스타", "전직", ("45도 간격 8방향 전방위 사격",),
              parent="quad_wing", level=30, asset="ships/Lv30_옥타 스타",
              shots=tuple(ShotSpec(angle=i*math.pi/4, forward=1.3953, caliber=(22 if i%2 == 0 else 19)/172*0.9) for i in range(8)), damage=0.85),
    ShipClass("hexa_cruiser", "헥사 크루저", "전직", ("전후방 3연장포 6문 순차 사격",),
              parent="twin_flank", level=30, asset="ships/Lv30_헥사 크루저",
              shots=(ShotSpec(lateral=-0.364, forward=1.29, caliber=18/165*0.9), ShotSpec(angle=math.pi, lateral=0.364, forward=1.37, caliber=18/165*0.9),
                     ShotSpec(forward=1.47, delay=2, caliber=21/165*0.9), ShotSpec(angle=math.pi, forward=1.55, delay=2, caliber=21/165*0.9),
                     ShotSpec(lateral=0.364, forward=1.29, delay=4, caliber=18/165*0.9), ShotSpec(angle=math.pi, lateral=-0.364, forward=1.37, delay=4, caliber=18/165*0.9)),
              damage=0.8, cooldown=0.8),
    ShipClass("colossus", "콜로서스", "전직", ("초거대 중장갑 선체 · 소형 3연장포", "체력 +400 · 받는 피해 -40%"),
              parent="bastion", level=30, asset="ships/Lv30_콜로서스",
              shots=(ShotSpec(lateral=-0.1867, forward=1.19, caliber=7/300*0.9), ShotSpec(forward=1.29, caliber=10/300*0.9),
                     ShotSpec(lateral=0.18, forward=1.19, caliber=7/300*0.9)),
              damage=0.55, hp_bonus=400, radius_scale=46/22, damage_taken=0.6),
    ShipClass("citadel", "시타델", "전직", ("최대 크기 성채 선체 · 사방 소형포", "체력 +440 · 받는 피해 -45%"),
              parent="aegis", level=30, asset="ships/Lv30_시타델",
              shots=tuple(ShotSpec(angle=i*math.pi/2, forward=1.2828, caliber=10/290*0.9) for i in range(4)),
              damage=0.55, hp_bonus=440, radius_scale=48/22, damage_taken=0.55),
)
SHIPS = {ship.key: ship for ship in SHIP_CLASSES}
# 적은 플레이어와 같은 진화 단계(Lv.1 / 10 / 20 / 30)의 우주선 중 하나를 쓴다.
SHIPS_BY_LEVEL = {level: tuple(ship.key for ship in SHIP_CLASSES if ship.level == level) for level in (1, 10, 20, 30)}
SPECIAL_REWARDS = SHIP_CLASSES[1:]
REWARD_CARDS = STAT_UPGRADES + SPECIAL_REWARDS
JOB_NAMES = {key: ship.title for key, ship in SHIPS.items()}
FAMILIES = tuple(ship for ship in SHIP_CLASSES if ship.level == 10)
# 이전 호출자가 이 이름을 가져와도 동작하지만 Q/Space 액티브는 없다.
SKILLS = {}


def stat_rows(width, height, cards=STAT_UPGRADES):
    start = height - 22 - 24 * len(cards)
    return [(card, (22, start + i * 24, 256, 22)) for i, card in enumerate(cards)]


def special_cards(width, height, count=4):
    return [(14 + i * 98, 82, 90, 90) for i in range(count)]


def stat_panel_rect(width, height, cards=STAT_UPGRADES):
    rows = stat_rows(width, height, cards)
    top = rows[0][1][1] - 30
    bottom = rows[-1][1][1] + rows[-1][1][3] + 8
    return (14, top, 272, bottom - top)


def stat_collapsed_rect(width, height):
    """한동안 건드리지 않아 접힌 스탯 창 (클릭 / 마우스를 올리면 다시 펼침)."""
    return (14, height - 54, 196, 38)


STAT_PANEL_IDLE_SECONDS = 4.0   # 이 시간 동안 건드리지 않으면 스탯 창을 접는다


def stat_upgrades_visible(game):
    return game.cfg.progression_enabled and game.player.alive and not game.game_over


def player_stat_summary(game):
    p, c = game.player, game.cfg
    spec, damage, cooldown, speed, life = game.weapon_values(p)
    return (
        ("체력", f"{p.hp:.0f} / {p.max_hp:.0f}"),
        ("자가 수리", f"{(c.regen_rate + p.regen_bonus) * c.fps:.1f} / 초"),
        ("주무기 피해 · 1발", f"{damage:.2f}"),
        ("발사 간격", f"{(cooldown + 1) / c.fps:.2f}초"),
        ("탄속", f"{speed * c.fps:.0f} px / 초"),
        ("사거리", f"{speed * life:.0f} px"),
        ("탄창", f"{p.ammo} / {p.max_ammo}" if c.limited_ammo else "무제한"),
        ("재장전 시간", f"{game.reload_frames_total / c.fps:.2f}초"),
        ("최고 이동 속도", f"{c.max_speed * p.accel_scale * c.fps:.0f} px / 초"),
    )
