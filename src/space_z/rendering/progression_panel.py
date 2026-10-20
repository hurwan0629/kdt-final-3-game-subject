"""강화·진화 패널의 배치와 표시용 계산. 게임 규칙을 적용하지 않는다."""
from space_z.config.progression_definitions import STAT_UPGRADES

def build_stat_upgrade_rows(width, height, cards=STAT_UPGRADES):  # 창 크기와 카드 목록으로 스탯 행의 배치 계산 (width는 호환용)
    start = height - 22 - 24 * len(cards)  # 하단 여백 22px, 행 간격 24px에 맞춘 첫 행 위치
    return [(card, (22, start + i * 24, 256, 22)) for i, card in enumerate(cards)]  # (카드, (x, y, 너비, 높이)) 목록


def get_evolution_card_rects(width, height, count=4):  # 진화 카드 count개의 고정 배치 계산 (width·height는 호환용)
    return [(14 + i * 98, 82, 90, 90) for i in range(count)]  # (x, y, 너비, 높이), 카드 크기 90px·간격 8px


def get_expanded_stat_panel_rect(width, height, cards=STAT_UPGRADES):  # 스탯 행을 감싸는 펼친 패널 영역 계산
    rows = build_stat_upgrade_rows(width, height, cards)  # 카드별 행 배치
    top = rows[0][1][1] - 30  # 첫 행 위 제목 공간 30px 포함
    bottom = rows[-1][1][1] + rows[-1][1][3] + 8  # 마지막 행 아래 여백 8px 포함
    return (14, top, 272, bottom - top)  # 패널 (x, y, 너비, 높이)


def get_collapsed_stat_panel_rect(width, height):
    """한동안 건드리지 않아 접힌 스탯 창 (클릭 / 마우스를 올리면 다시 펼침)."""
    return (14, height - 54, 196, 38)  # 접힌 패널 (x, y, 너비, 높이), 하단 여백 16px


STAT_PANEL_IDLE_SECONDS = 4.0   # 이 시간 동안 건드리지 않으면 스탯 창을 접는다


def can_show_stat_upgrades(game):  # 성장 기능이 켜져 있고 플레이어가 생존 중인지 확인
    return game.cfg.progression_enabled and game.player.alive and not game.game_over


def build_player_stat_summary(game):  # 플레이어 상태를 화면 표시용 (항목명, 값) 목록으로 변환
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
