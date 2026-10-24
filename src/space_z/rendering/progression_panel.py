"""강화·진화 패널의 배치와 표시용 계산. 게임 규칙을 적용하지 않는다."""
from __future__ import annotations
from collections.abc import Sequence
from typing import TYPE_CHECKING
from space_z.config.progression_definitions import RewardCard
from space_z.rendering.types import RectBounds

if TYPE_CHECKING:
    from space_z.game.game_core import GameCore

from space_z.config.progression_definitions import STAT_UPGRADES


def build_stat_upgrade_rows(width: int, height: int, cards: Sequence[RewardCard]=STAT_UPGRADES) -> list[tuple[RewardCard, RectBounds]]:
    """창 높이와 카드 목록으로 스탯 행의 배치를 구한다. width는 호환용이다."""
    # 하단 여백과 행 간격을 반영해 첫 스탯 행의 위치를 정한다.
    first_row_y = height - 22 - 24 * len(cards)

    # 각 카드와 클릭 영역(x, y, 너비, 높이)을 같은 순서로 묶는다.
    return [
        (card, (22, first_row_y + row_index * 24, 256, 22))
        for row_index, card in enumerate(cards)
    ]


def get_evolution_card_rects(width: int, height: int, count: int=4) -> list[RectBounds]:
    """진화 카드의 고정 배치를 구한다. width·height는 호환용이다."""
    # 90px 카드 사이에 8px 간격을 두고 클릭 영역을 배치한다.
    return [(14 + card_index * 98, 82, 90, 90) for card_index in range(count)]


def get_expanded_stat_panel_rect(width: int, height: int, cards: Sequence[RewardCard]=STAT_UPGRADES) -> RectBounds:
    """스탯 행과 제목을 감싸는 펼친 패널의 영역을 구한다."""
    # 첫 행 위의 제목 공간과 마지막 행 아래의 여백을 포함한다.
    rows = build_stat_upgrade_rows(width, height, cards)
    top = rows[0][1][1] - 30
    bottom = rows[-1][1][1] + rows[-1][1][3] + 8
    return (14, top, 272, bottom - top)


def get_collapsed_stat_panel_rect(width: int, height: int) -> RectBounds:
    """한동안 건드리지 않아 접힌 스탯 창 (클릭 / 마우스를 올리면 다시 펼침)."""
    return (14, height - 54, 196, 38)  # 접힌 패널 (x, y, 너비, 높이), 하단 여백 16px


STAT_PANEL_IDLE_SECONDS = 4.0  # 이 시간 동안 건드리지 않으면 스탯 창을 접는다


def can_show_stat_upgrades(game: GameCore) -> bool:
    """성장 기능과 플레이어 생존 상태로 스탯 패널 표시 여부를 확인한다."""
    return game.config.progression_enabled and game.player.alive and not game.game_over


def build_player_stat_summary(game: GameCore) -> tuple[tuple[str, str], ...]:
    """플레이어 능력치를 화면에 표시할 (항목명, 값) 목록으로 변환한다."""
    # 현재 플레이어와 강화·진화·숙련을 반영한 무기 능력치를 읽는다.
    player = game.player
    config = game.config
    _, damage, cooldown_frames, bullet_speed, bullet_life = game.combat.weapon_values(
        player
    )

    # 프레임 단위 능력치를 화면에 표시할 초·거리 단위로 환산한다.
    repair_per_second = (
        config.regen_rate * (player.max_hp / config.player_hp) + player.regen_bonus
    ) * config.fps
    fire_interval_seconds = (cooldown_frames + 1) / config.fps
    bullet_speed_per_second = bullet_speed * config.fps
    bullet_range = bullet_speed * bullet_life
    reload_seconds = game.combat.reload_frames_total / config.fps
    max_speed_per_second = config.max_speed * player.accel_scale * config.fps

    # 화면에서 사용하는 고정 순서와 표시 형식으로 능력치 목록을 만든다.
    return (
        ("체력", f"{player.hp:.0f} / {player.max_hp:.0f}"),
        ("자가 수리", f"{repair_per_second:.1f} / 초"),
        ("주무기 피해 · 1발", f"{damage:.2f}"),
        ("발사 간격", f"{fire_interval_seconds:.2f}초"),
        ("탄속", f"{bullet_speed_per_second:.0f} px / 초"),
        ("사거리", f"{bullet_range:.0f} px"),
        (
            "탄창",
            f"{player.ammo} / {player.max_ammo}" if config.limited_ammo else "무제한",
        ),
        ("재장전 시간", f"{reload_seconds:.2f}초"),
        ("최고 이동 속도", f"{max_speed_per_second:.0f} px / 초"),
    )
