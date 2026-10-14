"""레벨업 카드 정의. 게임 로직과 화면에서 같은 설명을 사용한다."""
from dataclasses import dataclass


@dataclass(frozen=True)
class RewardCard:
    key: str
    title: str
    category: str
    description: tuple[str, ...]


REWARD_CARDS = (
    RewardCard("damage", "화력 강화", "강화", ("탄환 피해량 +25%",)),
    RewardCard("rapid", "속사 장치", "강화", ("발사 대기 시간 -15%", "최소 4프레임까지 강화")),
    RewardCard("speed", "추진기 강화", "능력치", ("이동 가속도 +15%",)),
    RewardCard("hull", "선체 확장", "능력치", ("최대 체력 +25", "현재 체력도 +25")),
    RewardCard("heal", "긴급 수리", "회복", ("최대 체력의 60% 회복",)),
    RewardCard("regen", "자가 수리", "회복", ("초당 자동 회복량 +1.5", "피격 후 회복 대기 유지")),
    RewardCard("range", "고속 탄환", "강화", ("탄환 속도 +20%", "탄환 수명 +15%")),
    RewardCard("ammo", "탄약 보급", "보급", ("탄약 40발 보충", "최대 보유량까지 보충")),
    RewardCard("scout", "정찰선 전직", "전직", ("이동 가속도 +35%", "탄환 속도 +20%")),
    RewardCard("gunner", "포격선 전직", "전직", ("3방향 동시 발사", "각 탄환 피해량 -20%")),
    RewardCard("guardian", "수호선 전직", "전직", ("최대 체력 +60, 즉시 완전 회복", "초당 자동 회복량 +1.5")),
)

JOB_NAMES = {"rookie": "기본 우주선", "scout": "정찰선", "gunner": "포격선", "guardian": "수호선"}
