"""일반 레벨업 능력치와 10레벨 단위 전직/스킬 보상."""
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

SPECIAL_REWARDS = (
    RewardCard("laser", "레이저 전직", "전직", ("장거리 관통 레이저", "즉시 명중 / 벽 차단")),
    RewardCard("gunner", "3연장 전직", "전직", ("3방향 동시 발사", "피해 80% · 3발 소모")),
    RewardCard("cannon", "대포 전직", "전직", ("피해 4배 · 느린 연사", "반경 90px 폭발")),
    RewardCard("bomb", "중력 폭탄", "스킬", ("Q: 폭탄 투척", "1초 후 범위 폭발", "재사용 6초")),
    RewardCard("dash", "위상 대시", "스킬", ("Space: 방향 대시", "0.2초 무적", "재사용 4초")),
)
REWARD_CARDS = STAT_UPGRADES + SPECIAL_REWARDS
JOB_NAMES = {"rookie": "기본 우주선", "laser": "레이저 우주선",
             "gunner": "3연장 우주선", "cannon": "대포 우주선"}


def stat_rows(width, height):
    """렌더링과 클릭 판정에서 같은 화면 좌표를 사용한다."""
    return [(card, (24, height - 286 + i * 31, 258, 26)) for i, card in enumerate(STAT_UPGRADES)]


def special_cards(width, height):
    return [(14 + i * 166, 86, 156, 156) for i in range(3)]


def stat_upgrades_visible(game):
    return (game.cfg.progression_enabled and game.upgrade_points > 0
            and game.player.alive and not game.game_over)


def player_stat_summary(game):
    """현재 전직과 강화가 반영된 표시용 수치. 이동은 일반 지형 기준."""
    p, c = game.player, game.cfg
    mastery = 1 + 0.2 * max(0, game.special_levels.get(p.job, 0) - 1)
    damage = c.bullet_damage * p.damage_scale * mastery
    damage *= {"laser": 1.4, "gunner": 0.8, "cannon": 4}.get(p.job, 1)
    cooldown = p.fire_cooldown_max
    if p.job == "laser":
        cooldown = max(4, int(cooldown * 0.65))
    elif p.job == "cannon":
        cooldown *= 2
    speed = c.bullet_speed * p.bullet_speed_scale * (0.7 if p.job == "cannon" else 1)
    lifetime = int(c.bullet_life * p.bullet_life_scale * (1.6 if p.job == "cannon" else 1))
    reach = c.laser_range * p.bullet_life_scale if p.job == "laser" else speed * lifetime
    return (
        ("선체 내구도", f"{p.hp:.0f} / {p.max_hp:.0f}"),
        ("자가 수리", f"{(c.regen_rate + p.regen_bonus) * c.fps:.1f} / 초"),
        ("주무기 피해 · 1발", f"{damage:.2f}"),
        ("발사 간격", f"{(cooldown + 1) / c.fps:.2f}초"),
        ("탄속", "즉시 명중" if p.job == "laser" else f"{speed * c.fps:.0f} px / 초"),
        ("사거리", f"{reach:.0f} px"),
        ("탄창", f"{p.ammo} / {p.max_ammo}" if c.limited_ammo else "무제한"),
        ("재장전 시간", f"{game.reload_frames_total / c.fps:.2f}초"),
        ("최고 이동 속도", f"{c.max_speed * p.accel_scale * c.fps:.0f} px / 초"),
    )
