"""개체별 상태 정의. 상태를 변경하는 게임 규칙은 각 담당 객체에 있다."""

from dataclasses import dataclass, field


@dataclass
class Tank:  # 플레이어·적 선체의 이동·전투·AI 상태
    id: int  # 이번 판에서 선체를 식별하는 고유 번호
    team: str  # 소속 진영 ("player" / "enemy")
    x: float  # 선체 중심의 월드 가로 좌표 (px)
    y: float  # 선체 중심의 월드 세로 좌표 (px, 아래쪽이 양수)
    hp: float  # 현재 체력
    max_hp: float  # 최대 체력
    radius: float  # 선체 충돌 반지름 (px)
    fire_cooldown_max: int  # 우주선 종류별 간격 배율 적용 전 기본 발사 대기 (프레임)
    velocity_x: float = 0.0  # 가로 이동 속도 (px/frame)
    velocity_y: float = 0.0  # 세로 이동 속도 (px/frame)
    angle: float = 0.0  # 포신 각도 (rad, 0=오른쪽, 시계방향이 양수)
    cooldown: int = 0  # 다음 발사 묶음까지 남은 대기 프레임
    alive: bool = True  # 선체 생존 여부
    respawn_timer: int = 0  # 죽은 적이 재등장하기까지 남은 프레임
    last_hit_frame: int = -(10**9)  # 마지막 피격 프레임 (회복 지연 계산용)
    damage_scale: float = 1.0  # 기본 탄환 피해에 곱할 개체별 공격력 배율
    accel_scale: float = 1.0  # 기본 이동 가속도에 곱할 개체별 배율
    bullet_speed_scale: float = 1.0  # 기본 탄속에 곱할 개체별 배율
    bullet_life_scale: float = 1.0  # 기본 탄환 수명에 곱할 개체별 배율
    regen_bonus: float = 0.0  # 플레이어의 프레임당 추가 체력 회복량
    # 현재 우주선의 발사 패턴 수 (실제 발사는 ShipClass.shots 사용)
    projectiles: int = 1
    job: str = "rookie"  # 현재 우주선 종류 키
    ammo: int = 0  # 플레이어 탄창의 남은 탄약 수
    max_ammo: int = 0  # 플레이어 탄창 용량
    reload_scale: float = 1.0  # 플레이어 기본 재장전 시간에 곱할 배율
    # 예약 점사 (발사 프레임, 패턴, 피해, 탄속, 수명) 목록
    pending_shots: list = field(default_factory=list)
    elite: bool = False  # 엘리트 적 여부 (능력치·처치 점수 강화, 처치 시 플레이어 회복)
    # 적 개체에 무작위 배분한 스탯 키별 강화 단계
    stat_levels: dict = field(default_factory=dict)
    # 적 AI 상태
    ai_timer: int = 0  # 목표·조준 오차·옆돌기 방향을 다시 정하기까지 남은 프레임
    # 목표 ("player", id) / ("shape", id) / ("point", (x, y)) / None
    ai_target: tuple = None
    ai_aim_offset: float = 0.0  # 목표 방향에 더할 조준 오차 (rad)
    ai_move: int = 0  # 목표가 없을 때 사용할 이동 번호 (0=정지, 1~8=8방향)
    # 이번 프레임에 시야 거리·시야선 조건으로 플레이어가 보이는지
    ai_can_see: bool = False
    # 감지하거나 동료에게 전달받은 마지막 플레이어 위치 (월드 x, y)
    ai_last_seen: tuple = None
    ai_last_seen_frame: int = -(10**9)  # 마지막 플레이어 위치를 확인·전달받은 프레임
    # A* 탐색 후 남은 이동 경로 (타일 열·행 좌표 목록)
    ai_path: list = field(default_factory=list)
    ai_path_timer: int = 0  # A* 경로를 다시 계산하기까지 남은 프레임
    ai_goal: tuple = None  # 현재 이동 목표의 월드 좌표 (디버그 표시용)
    ai_strafe: float = 1.0  # 목표 주위를 옆으로 도는 방향 (1 또는 -1)


@dataclass
class Shape:  # 파괴 가능한 천체의 이동·체력·점수 상태
    id: int  # 이번 판에서 천체를 식별하는 고유 번호
    kind: str  # 천체 종류 키 (square / triangle / pentagon)
    x: float  # 천체 중심의 월드 가로 좌표 (px)
    y: float  # 천체 중심의 월드 세로 좌표 (px)
    velocity_x: float  # 가로 표류 속도 (px/frame)
    velocity_y: float  # 세로 표류 속도 (px/frame)
    hp: float  # 현재 체력
    max_hp: float  # 최대 체력 (관찰·피해 보상 정규화 기준)
    radius: float  # 천체 충돌 반지름 (px)
    score: int  # 플레이어가 파괴했을 때 획득할 점수
    angle: float = 0.0  # 현재 회전 각도 (rad)
    spin: float = 0.0  # 프레임당 회전량 (rad/frame)


@dataclass
class Bullet:  # 탄환의 이동·피해·충돌·관통 상태
    x: float  # 탄환 중심의 현재 월드 가로 좌표 (px)
    y: float  # 탄환 중심의 현재 월드 세로 좌표 (px)
    velocity_x: float  # 가로 이동 속도 (px/frame)
    velocity_y: float  # 세로 이동 속도 (px/frame)
    life: int  # 소멸하기까지 남은 수명 (프레임)
    owner_id: int  # 탄환을 발사한 선체의 고유 번호
    team: str  # 공격 진영 ("player" / "enemy")
    damage: float  # 명중 시 적용할 피해량 (대상 선체의 받는 피해 배율 적용 전)
    radius: float  # 탄환 충돌 반지름 (px)
    blast_radius: float = 0.0  # 명중 시 폭발 반지름 (px, 0이면 직접 피해)
    # 이동 구간 충돌 판정의 시작 가로 좌표 (None이면 현재 위치 사용)
    prev_x: float = None
    prev_y: float = None  # 이동 구간 충돌 판정의 시작 세로 좌표
    kind: str = "plasma"  # 표시할 탄환 종류 (plasma / shell / mine / missile)
    arming_frames: int = 0  # 이전 지뢰의 무장 대기 프레임 (현재 미사용)
    homing: bool = False  # 이전 유도탄의 추적 여부 (현재 미사용)
    pierce: int = 0  # 명중 후 탄환을 유지할 수 있는 남은 관통 횟수
    # 이미 맞힌 대상 번호 집합 (관통 중 중복 피해 방지)
    hit_ids: set = field(default_factory=set)


@dataclass
class Beam:  # 빔 연출의 시작점·끝점·수명
    x: float  # 빔 시작점의 월드 가로 좌표 (px)
    y: float  # 빔 시작점의 월드 세로 좌표 (px)
    end_x: float  # 빔 끝점의 월드 가로 좌표 (px)
    end_y: float  # 빔 끝점의 월드 세로 좌표 (px)
    life: int = 6  # 연출이 사라지기까지 남은 프레임


@dataclass
class Explosion:  # 폭발 연출의 중심·크기·수명
    x: float  # 폭발 중심의 월드 가로 좌표 (px)
    y: float  # 폭발 중심의 월드 세로 좌표 (px)
    radius: float  # 폭발 연출의 기준 반지름 (px)
    life: int = 18  # 연출이 사라지기까지 남은 프레임
