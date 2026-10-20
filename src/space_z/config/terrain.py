"""맵 생성·타일·지형 기능 설정."""
from dataclasses import dataclass


@dataclass
class TerrainConfig:
    # 큰 소행성 벽과 넓은 통로. 중력장/파괴 가능한 벽은 선택 기능이다.
    enabled: bool = True             # False면 벽 없는 빈 경기장
    tile_size: int = 48              # 지형 타일 한 변 길이 (px)
    map_name: str = "drift"          # maps/<map_name>.txt (drift / ring / belt)
    map_pool: tuple = ()             # 비어있지 않으면 reset마다 seed로 이 중 하나 선택
    random_map: bool = True          # True면 reset마다 랜덤 블록 지형, False면 map_name 미로
    # 랜덤 지형 (diep.io 미로 모드 느낌): 큰 블록 격자 미로에서 벽 일부를 뚫는다
    block_tiles: int = 8                 # 블록 한 변 (8칸 = 384px, 통로/벽 폭 — 더 개방감 있게)
    extra_openings: float = 0.6          # 미로에서 막힌 연결 벽을 추가로 뚫는 비율 (클수록 덜 갑갑)
    pillar_removal: float = 0.5          # 벽 기둥을 없애 넓은 공간을 만드는 비율
    wall_merge: float = 0.0              # 벽 옆 바닥 블록을 메워 큰 벽 덩어리를 만드는 비율
    # 0보다 크면 가끔 ㄱ/ㄷ자처럼 꺾인 벽 덩어리가 생긴다. 각진 미로 느낌보다
    # 단순한 사각 장애물이 흩어진 느낌을 원해서 기본은 끈다.
    random_wall_density: float = 0.14    # 이전 설정 호환용: 미로 밀도는 통로/벽 두께로 결정
    wall_thickness: int = 4             # 방 기반 미로 생성기의 벽 두께 (타일)
    wall_min_length: int = 6            # 벽 최소 길이 (타일, 현재 생성기에서 미사용)
    wall_max_length: int = 10           # 벽 최대 길이 (타일, 현재 생성기에서 미사용)
    min_passage_tiles: int = 6          # 288px: 반지름 96px 선체와 작은 적이 통과
    navigation_radius: float = 96.0     # 두 배 커진 최종 가디언의 실제 반지름
    random_mud_density: float = 0.03     # 랜덤 중력장 생성 밀도 (mud_enabled일 때)
    random_breakable_density: float = 0.03  # 랜덤 파괴 가능 벽 생성 밀도 (breakable_enabled일 때)
    # 2단계 지형 (끄면 진흙은 빈칸, 부서지는 벽은 일반 벽으로 취급)
    mud_enabled: bool = False           # 중력장 지형 활성화 여부
    mud_accel_scale: float = 0.5         # 중력장 안에서의 이동 가속도 배율
    breakable_enabled: bool = False     # 파괴 가능한 벽 활성화 여부
    breakable_hp: float = 40.0          # 파괴 가능한 벽 타일당 체력
