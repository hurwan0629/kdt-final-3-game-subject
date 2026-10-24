"""적 감지·행동·성장 설정."""

from dataclasses import dataclass


@dataclass
class EnemyAIConfig:
    """규칙 기반 적 AI 난이도 파라미터."""

    reaction_frames: int = 20  # 목표/이동 방향을 다시 정하는 주기 (프레임)
    aim_noise_deg: float = 13.5  # 조준 오차 표준편차 (도)
    turn_speed_scale: float = 0.7  # 플레이어 포신 회전 속도 대비 배율
    move_speed_scale: float = 0.8  # 플레이어 가속도 대비 배율
    fire_cooldown: int = 39  # 발사 간격 (프레임)
    fire_angle_tol_deg: float = 15.0  # 조준 오차가 이 값 이내일 때만 발사
    sight_range: float = 750.0  # 시야선이 트였을 때 플레이어를 보는 거리
    sense_range: float = 340.0  # 이 거리 안이면 벽 너머의 플레이어도 알아챈다
    hearing_range: float = 850.0  # 플레이어가 쏘면 이 거리 안의 적은 위치를 알아챈다
    hearing_frames: int = 30  # 발사 소리가 유지되는 시간 (프레임)
    alert_range: float = 700.0  # 플레이어를 본 적이 이 거리 안의 동료에게 위치를 알린다
    # 동료 호출은 게임 시작 후 이 시간이 지나야 켜진다 (초반 난이도 완화)
    alert_start_seconds: float = 120.0
    # 초반 봐주기: 게임 시작 후 mercy_seconds 동안 적이 아래 배율에서 1.0까지 서서히 강해진다
    mercy_seconds: float = 45.0  # 초반 약화가 정상 배율로 돌아오는 시간 (초)
    mercy_hp_scale: float = 0.7  # 게임 시작 시 적 최대 체력 배율
    mercy_damage_scale: float = 0.55  # 게임 시작 시 적 공격 피해 배율
    mercy_fire_rate_scale: float = 0.7  # 게임 시작 시 적 발사 속도 배율
    # 게임 시작 시 엘리트 확률 배율 (이후 1.0까지 증가)
    mercy_elite_chance_scale: float = 0.0
    lead_aim: float = 0.65  # 이동 예측 조준 비율 (0이면 현재 위치를 조준)
    keep_distance: float = 230.0  # 플레이어와 유지하려는 거리
    respawn_frames: int = 300  # 사망 후 재등장까지 프레임 (5초)
    memory_frames: int = 300  # 플레이어를 놓친 뒤 마지막 위치를 기억하는 시간 (5초)
    path_recompute_frames: int = 20  # A* 경로 재계산 주기
    waypoint_reach: float = 14.0  # 경로의 다음 칸 중심에 이만큼 가까워지면 다음 칸으로
    # 시간이 지날수록 강해짐: scale_interval_seconds마다 한 단계 (최대 max_scale_tier)
    scale_interval_seconds: float = 45.0  # 적 성장 단계가 오르는 간격 (초)
    max_scale_tier: int = 20  # 적 성장 단계 상한
    hp_growth: float = 0.12  # 단계당 최대 체력 +12%
    damage_growth: float = 0.08  # 단계당 공격 피해 +8%
    fire_rate_growth: float = 0.05  # 단계당 발사 속도 +5%
    speed_growth: float = 0.02  # 단계당 이동 가속도 +2%
    min_fire_cooldown: int = 14  # 아무리 강해져도 이보다 빨리 쏘지 않음
    aim_noise_decay: float = 0.04  # 단계당 조준 오차 -4% (최소 40%까지)
    # 엘리트: 등장할 때 elite_chance 확률. 더 단단하고 세며, 잡으면 플레이어 체력 회복
    elite_chance: float = 0.15  # 적 등장 시 엘리트가 될 기본 확률 (0~1)
    elite_hp_scale: float = 2.5  # 엘리트 최대 체력 배율
    elite_damage_scale: float = 1.6  # 엘리트 공격 피해 배율
    elite_heal_ratio: float = 0.4  # 처치 시 플레이어 최대 체력의 40% 회복
    elite_score_scale: float = 2.0  # 엘리트 처치 점수 배율
    # 플레이어 스탯 투자량의 일부를 적의 강화 포인트로 삼아 항목별로 무작위 배분한다.
    stat_mirror_ratio: float = 0.6  # 플레이어 투자량 대비 적 강화 포인트 비율
