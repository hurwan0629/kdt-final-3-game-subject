"""능력치, 전직 트리와 화면에서 공유하는 보상 배치."""
import math
from dataclasses import dataclass


@dataclass(frozen=True)
class RewardCard:
    key: str
    title: str
    category: str
    description: tuple[str, ...]


STAT_UPGRADES = (
    RewardCard("regen", "자가 수리", "능력치", ("초당 회복 +1.5",)),
    RewardCard("hull", "선체 내구도", "능력치", ("최대 / 현재 체력 +25",)),
    RewardCard("damage", "플라즈마 화력", "능력치", ("공격 피해 +25%",)),
    RewardCard("range", "탄속 · 사거리", "능력치", ("탄속 +20%, 수명 +15%",)),
    RewardCard("magazine", "탄창 확장", "능력치", ("최대 / 현재 탄약 +20",)),
    RewardCard("rapid", "연사 장치", "능력치", ("발사 대기 -15%, 최소 4프레임",)),
    RewardCard("reload", "재장전 장치", "능력치", ("재장전 시간 -10%, 최소 0.75초",)),
    RewardCard("speed", "기동 추진기", "능력치", ("이동 가속도 +15%",)),
)


@dataclass(frozen=True)
class ShipClass(RewardCard):
    parent: str = ""
    angles: tuple[float, ...] = (0.0,)
    muzzles: tuple[float, ...] = ()
    damage: float = 1.0
    cooldown: float = 1.0
    speed: float = 1.0
    life: float = 1.0
    beam: bool = False
    mine: bool = False
    homing: bool = False


SHIP_CLASSES = (
    ShipClass("rookie", "기본 우주선", "전직", ("단발 플라즈마",)),
    ShipClass("twin", "쌍포선", "전직", ("평행한 포 2개 동시 발사",),
              angles=(0.0, 0.0), muzzles=(-11.0, 11.0), damage=0.8),
    ShipClass("sniper", "저격선", "전직", ("강한 단발 · 빠른 탄속",), damage=2.5, cooldown=1.7, speed=1.8, life=1.4),
    ShipClass("gatling", "개틀링선", "전직", ("빠른 연사 · 낮은 단발 피해",), damage=0.6, cooldown=0.35, speed=1.2),
    ShipClass("guardian", "수호선", "전직", ("최대 / 현재 체력 +50", "받는 피해 35% 감소"), cooldown=1.1),
    ShipClass("triple", "삼연포선", "전직", ("3방향 동시 발사",), "twin", (-0.2, 0.0, 0.2), damage=0.8),
    ShipClass("cross", "십자포선", "전직", ("전후좌우 4방향 발사",), "twin",
              (0.0, math.pi / 2, math.pi, -math.pi / 2), damage=0.85),
    ShipClass("railgun", "레일건선", "전직", ("적 무제한 관통 · 벽 차단",), "sniper",
              damage=3.5, cooldown=1.8, life=1.6, beam=True),
    ShipClass("minelayer", "기뢰선", "전직", ("탄이 멈추면 기뢰 · 접촉 폭발",), "sniper",
              damage=3, cooldown=1.4, speed=0.75, mine=True),
    ShipClass("shotgun", "산탄선", "전직", ("한 번에 6발 부채꼴 발사",), "gatling",
              (-0.35, -0.21, -0.07, 0.07, 0.21, 0.35), damage=0.65, cooldown=1.2),
    ShipClass("homing", "유도탄선", "전직", ("적을 추적하는 미사일",), "gatling",
              damage=1.8, cooldown=1.2, speed=0.85, life=1.8, homing=True),
    ShipClass("booster", "추진선", "전직", ("전방 / 후방 발사 · 반동 가속",), "guardian",
              (0.0, math.pi, math.pi), (0.0, -12.0, 12.0)),
    ShipClass("ram", "돌격선", "전직", ("포 없음 · 충돌 피해 8배", "받는 피해 65% 감소"), "guardian", ()),
)
SHIPS = {ship.key: ship for ship in SHIP_CLASSES}
SPECIAL_REWARDS = SHIP_CLASSES[1:]
REWARD_CARDS = STAT_UPGRADES + SPECIAL_REWARDS
JOB_NAMES = {key: ship.title for key, ship in SHIPS.items()}
FAMILIES = tuple(ship for ship in SHIP_CLASSES[1:] if not ship.parent)


@dataclass(frozen=True)
class ActiveSkill:
    key: str
    title: str
    cooldown: float
    description: str


SKILLS = {
    "triple": ActiveSkill("barrage", "전방위 탄막", 8, "주변 20방향으로 탄막 발사"),
    "cross": ActiveSkill("turret", "회전 포탑", 10, "5초 동안 회전하는 4방향 포탑"),
    "railgun": ActiveSkill("charge", "차지 빔", 8, "0.75초 충전 후 주무기 피해 5배"),
    "minelayer": ActiveSkill("detonate", "일제 기폭", 4, "설치한 기뢰를 모두 폭발"),
    "shotgun": ActiveSkill("overload", "과부하", 12, "5초 동안 발사 대기 -60%, 피해 +30%"),
    "homing": ActiveSkill("salvo", "미사일 일제사격", 10, "유도 미사일 8발 발사"),
    "booster": ActiveSkill("warp", "워프 대시", 5, "이동 방향으로 0.18초 고속 이동 · 무적"),
    "ram": ActiveSkill("ram_charge", "램 차지", 7, "0.5초 돌진 · 충돌 피해 4배 · 무적"),
}


def stat_rows(width, height, cards=STAT_UPGRADES[:3]):
    """실제 표시한 선택지와 클릭 영역을 일치시킨다."""
    return [(card, (22, height - 94 + i * 24, 208, 22)) for i, card in enumerate(cards)]


def special_cards(width, height, count=4):
    return [(14 + i * 98, 82, 90, 90) for i in range(count)]


def stat_upgrades_visible(game):
    return (game.cfg.progression_enabled and game.upgrade_points > 0
            and game.player.alive and not game.game_over)


def player_stat_summary(game):
    p, c = game.player, game.cfg
    spec, damage, cooldown, speed, life = game.weapon_values(p)
    reach = c.laser_range * p.bullet_life_scale * spec.life if spec.beam else speed * life
    return (
        ("선체 내구도", f"{p.hp:.0f} / {p.max_hp:.0f}"),
        ("자가 수리", f"{(c.regen_rate + p.regen_bonus) * c.fps:.1f} / 초"),
        ("주무기 피해 · 1발", f"{damage:.2f}" if spec.angles else "충돌 전용"),
        ("발사 간격", f"{(cooldown + 1) / c.fps:.2f}초" if spec.angles else "발사 없음"),
        ("탄속", "즉시 명중" if spec.beam else f"{speed * c.fps:.0f} px / 초"),
        ("사거리", f"{reach:.0f} px" if spec.angles else "접촉"),
        ("탄창", f"{p.ammo} / {p.max_ammo}" if c.limited_ammo else "무제한"),
        ("재장전 시간", f"{game.reload_frames_total / c.fps:.2f}초"),
        ("최고 이동 속도", f"{c.max_speed * p.accel_scale * c.fps:.0f} px / 초"),
    )
