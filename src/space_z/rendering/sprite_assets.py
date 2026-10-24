"""PNG 원본과 투명도를 보존하며 화면용 크기·회전을 캐시한다."""
from __future__ import annotations
from numpy.typing import NDArray
from space_z.rendering.types import RGB

import math
from functools import lru_cache

import numpy as np
import pygame

from space_z.resource_paths import resource_path
from space_z.config.progression_definitions import BARREL_OVERRIDES

ENEMY_SUFFIX = (
    "@enemy"  # "ships/Lv10_트윈@enemy" → 같은 그림의 청록 선체를 붉은색으로 바꿔 쓴다
)
ELITE_SUFFIX = "@elite"  # 엘리트 적은 금색 선체
HEALTH_TINTS = {ENEMY_SUFFIX: (1.0, 0.32, 0.35), ELITE_SUFFIX: (1.0, 0.72, 0.18)}


def _health_mask(rgb_pixels: NDArray[np.int16], alpha: NDArray[np.uint8]) -> NDArray[np.bool_]:
    """이미지에서 불투명한 청록색 선체에 해당하는 픽셀을 찾는다.

    인자:
        rgb_pixels: (너비, 높이, 3) 모양의 NumPy RGB 배열. 축 순서는 x, y, 채널이다.
        alpha: 같은 이미지의 (너비, 높이) 모양 알파 배열. 값 범위는 0~255이다.

    처리:
        알파가 100보다 크고 초록·파랑 채널이 각각 빨강보다 30 넘게 큰 픽셀을 고른다.

    반환:
        np.ndarray: (너비, 높이) 모양의 불리언 마스크. 선체 픽셀은 True이다.
        입력 배열은 변경하지 않는다.
    """
    return (
        (alpha > 100)
        & (rgb_pixels[:, :, 1] > rgb_pixels[:, :, 0] + 30)
        & (rgb_pixels[:, :, 2] > rgb_pixels[:, :, 0] + 30)
    )


def _recolor_health(image: pygame.Surface, tint: tuple[float, float, float]) -> pygame.Surface:
    """선체의 밝기와 투명도를 유지하며 진영별 색상으로 바꾼 복사본을 만든다.

    인자:
        image: 색상을 바꿀 pygame.Surface. 청록색 선체와 회색 포신이 있는 이미지이다.
        tint: RGB 채널별 밝기 배율 세 개. HEALTH_TINTS의 0~1 범위 튜플을 사용한다.

    처리:
        1) 이미지를 복사하고 청록색 정도와 픽셀별 최대 채널 밝기를 구한다.
        2) 밝기에 tint를 적용한 색상을 만들고 가장자리의 청록색 정도에 따라 혼합한다.
        3) 회색 포신처럼 청록색이 아닌 부분과 기존 알파 값은 유지한다.

    반환:
        pygame.Surface: 원본과 같은 크기의 색상 변경 이미지. 입력 이미지는 변경하지 않는다.
    """

    # 원본을 복사하고 선체의 색상과 밝기를 읽는다.
    image = image.copy()
    rgb_pixels = pygame.surfarray.pixels3d(image)
    source_pixels = rgb_pixels.astype(np.float32)
    teal = (source_pixels[:, :, 2] - source_pixels[:, :, 0]) > 20
    value = source_pixels.max(axis=2)
    # 안티에일리어싱된 가장자리는 청록 정도만큼만 섞는다.
    blend_ratio = (
        np.clip((source_pixels[:, :, 2] - source_pixels[:, :, 0]) / 120.0, 0, 1)[
            ..., None
        ]
        * teal[..., None]
    )

    # 선체 밝기는 유지하면서 진영별 색상을 혼합한다.
    color = np.stack([value * channel_scale for channel_scale in tint], axis=2)
    rgb_pixels[...] = (source_pixels * (1 - blend_ratio) + color * blend_ratio).astype(
        np.uint8
    )
    del rgb_pixels
    return image


def _redraw_barrel(image: pygame.Surface, forward: float, inner: float) -> pygame.Surface:
    """기존 회색 포신을 제거하고 지정한 크기의 포신을 선체 아래에 다시 그린다.

    인자:
        image: 청록색 선체 영역과 픽셀 알파가 있는 pygame.Surface.
        forward: 선체 중심부터 새 포구까지의 거리. 선체 반지름에 대한 배율이다.
        inner: 새 포신의 안쪽 폭과 선체 지름의 비율. 테두리는 별도로 더한다.

    처리:
        1) 선체 마스크의 경계에서 중심 좌표와 반지름을 측정한다.
        2) 원본 복사본에서 회색 픽셀을 투명하게 만들어 기존 포신을 지운다.
        3) 같은 크기의 투명 표면에 오른쪽을 향하는 포신을 그리고 선체를 위에 합성한다.

    반환:
        pygame.Surface: 새 포신과 선체를 합친 이미지. 입력 이미지와 원본 파일은 변경하지 않는다.
    """

    # 선체 영역의 중심과 반지름을 측정한다.
    rgb_pixels = pygame.surfarray.array3d(image).astype(np.int16)
    alpha = pygame.surfarray.array_alpha(image)
    health_x_pixels, health_y_pixels = np.where(_health_mask(rgb_pixels, alpha))
    center_x, center_y = (
        (np.min(health_x_pixels) + np.max(health_x_pixels) + 1) / 2,
        (np.min(health_y_pixels) + np.max(health_y_pixels) + 1) / 2,
    )
    radius = (
        max(
            np.max(health_x_pixels) - np.min(health_x_pixels) + 1,
            np.max(health_y_pixels) - np.min(health_y_pixels) + 1,
        )
        / 2
    )

    # 선체 이미지에서 기존 회색 포신을 지운다.
    health = image.copy()
    gray = (np.abs(rgb_pixels[:, :, 0] - rgb_pixels[:, :, 1]) < 25) & (
        np.abs(rgb_pixels[:, :, 1] - rgb_pixels[:, :, 2]) < 25
    )
    health_alpha = pygame.surfarray.pixels_alpha(health)
    health_alpha[gray & (alpha > 0)] = 0
    del health_alpha

    # 측정한 선체 크기에 맞춰 새 포신을 그리고 선체와 합성한다.
    surface = pygame.Surface(image.get_size(), pygame.SRCALPHA)
    edge = max(2, round(radius * 0.08))
    half = inner * radius + edge
    tip = forward * radius
    outer = pygame.Rect(0, 0, round(tip), round(2 * half))
    outer.midleft = (round(center_x), round(center_y))
    pygame.draw.rect(surface, (85, 85, 85), outer, border_radius=edge)
    pygame.draw.rect(surface, (153, 153, 153), outer.inflate(-2 * edge, -2 * edge))
    surface.blit(health, (0, 0))
    return surface


class SpriteAssets:
    """원본·선체·탄환 이미지를 준비하고 인스턴스별 LRU 캐시로 재사용한다.

    이미지 메서드가 반환한 Surface는 캐시의 다른 호출과 공유될 수 있다.
    색상이나 투명도를 직접 바꿀 때는 반환값을 copy()한 뒤 사용한다.
    """

    def __init__(self) -> None:
        """각 이미지 처리 메서드에 크기가 제한된 LRU 캐시를 연결한다.

        인자:
            없음.

        처리:
            원본 로드·형상 측정·기준 이미지·크기 변환·회전 결과를 인스턴스별로 캐시한다.
            같은 인자의 결과는 재사용하고 캐시가 차면 가장 오래 사용하지 않은 항목을 지운다.
            이 시점에는 이미지 파일을 읽지 않으며 실제 요청 시 로드한다.

        반환:
            None: 현재 SpriteAssets 인스턴스의 메서드를 캐시를 사용하는 메서드로 교체한다.
        """
        # 인스턴스별 캐시와 cache_info()를 유지하는 바인딩이다. 메서드 재할당만 검사 예외로 둔다.
        self._source = lru_cache(maxsize=96)(self._source)  # type: ignore[method-assign]
        self._ship_geometry = lru_cache(maxsize=32)(self._ship_geometry)  # type: ignore[method-assign]
        self._ship_base = lru_cache(maxsize=32)(self._ship_base)  # type: ignore[method-assign]
        self._scaled = lru_cache(maxsize=192)(self._scaled)  # type: ignore[method-assign]
        self._rotated = lru_cache(maxsize=512)(self._rotated)  # type: ignore[method-assign]
        self._projectile_geometry = lru_cache(maxsize=8)(self._projectile_geometry)  # type: ignore[method-assign]
        self._projectile_base = lru_cache(maxsize=8)(self._projectile_base)  # type: ignore[method-assign]
        self._projectile_scaled = lru_cache(maxsize=64)(self._projectile_scaled)  # type: ignore[method-assign]
        self._projectile_rotated = lru_cache(maxsize=256)(self._projectile_rotated)  # type: ignore[method-assign]

    def _source(self, path: str) -> pygame.Surface:
        """리소스 키에 해당하는 PNG를 읽고 종류별 전처리를 적용한다.

        인자:
            path: assets/와 .png를 제외한 리소스 키. 예: "ships/Lv1_베이직".
                끝에 @enemy 또는 @elite가 있으면 해당 진영의 선체 색상을 적용한다.

        처리:
            1) 진영 접미사가 있으면 원본 키를 재귀적으로 조회해 선체 색상을 바꾼다.
            2) PNG를 로드하고 픽셀 알파를 사용하는 표면으로 변환한다.
               convert_alpha()를 사용하므로 pygame 화면 모드가 먼저 설정되어 있어야 한다.
            3) 장애물·메뉴 버튼의 투명 여백을 제거하고 지정된 우주선의 포신을 다시 그린다.

        반환:
            pygame.Surface: 전처리한 원본 이미지. 결과는 캐시되며 원본 파일은 변경하지 않는다.
        """
        for suffix, tint in HEALTH_TINTS.items():
            if path.endswith(suffix):
                return _recolor_health(self._source(path[: -len(suffix)]), tint)
        image = pygame.image.load(resource_path(f"assets/{path}.png")).convert_alpha()
        if path.startswith(("etc/guard_", "etc/home_")):
            # 장애물·버튼은 큰 투명 여백을 제외한 실제 그림을 표시 영역에 맞춘다.
            image = image.subsurface(image.get_bounding_rect()).copy()
        if path in BARREL_OVERRIDES:
            image = _redraw_barrel(image, *BARREL_OVERRIDES[path])
        return image

    def _ship_geometry(self, path: str) -> tuple[tuple[float, float], int]:
        """우주선 이미지에서 포신을 제외한 선체의 중심과 지름 기준값을 구한다.

        인자:
            path: assets/와 .png를 제외한 우주선 리소스 키. 진영 접미사도 허용한다.

        처리:
            1) 진영 접미사를 제거해 색상 변경 전의 원본 선체를 기준으로 측정한다.
            2) 불투명한 청록색 픽셀을 둘러싸는 경계 사각형을 구한다.
            3) 청록색 영역이 없으면 전체 불투명 영역의 경계를 대신 사용한다.
               경계의 중심과 긴 변의 길이(최소 1px)를 계산해 캐시한다.

        반환:
            tuple: ((center_x, center_y), health_diameter).
            중심은 원본 이미지 안의 픽셀 좌표이며 지름은 선체 크기 변환에 사용할 픽셀 길이이다.
        """
        for suffix in HEALTH_TINTS:  # 색을 바꾼 적 그림도 원본 선체 기준을 쓴다
            if path.endswith(suffix):
                return self._ship_geometry(path[: -len(suffix)])

        # 원본 선체의 픽셀 영역과 투명도를 읽는다.
        source = self._source(path)
        rgb_pixels = pygame.surfarray.array3d(source).astype(np.int16)
        alpha = pygame.surfarray.array_alpha(source)
        health = (
            (alpha > 100)
            & (rgb_pixels[:, :, 1] > rgb_pixels[:, :, 0] + 30)
            & (rgb_pixels[:, :, 2] > rgb_pixels[:, :, 0] + 30)
        )
        health_x_pixels, health_y_pixels = np.where(health)

        # 선체 영역의 중심과 충돌 지름에 대응할 크기를 구한다.
        if not len(health_x_pixels):
            rect = source.get_bounding_rect()
        else:
            rect = pygame.Rect(
                int(np.min(health_x_pixels)),
                int(np.min(health_y_pixels)),
                int(np.max(health_x_pixels) - np.min(health_x_pixels) + 1),
                int(np.max(health_y_pixels) - np.min(health_y_pixels) + 1),
            )
        return (rect.x + rect.width / 2, rect.y + rect.height / 2), max(
            1, rect.width, rect.height
        )

    def _ship_base(self, path: str) -> pygame.Surface:
        """포신까지 포함한 우주선 이미지를 선체 중심 기준의 정사각 캔버스에 배치한다.

        인자:
            path: assets/와 .png를 제외한 우주선 리소스 키. 진영 접미사도 허용한다.

        처리:
            1) 선체 중심과 포신을 포함한 전체 불투명 영역을 조회한다.
            2) 선체 중심에서 가장 먼 이미지 가장자리가 들어가는 정사각 캔버스를 만든다.
            3) 선체 중심이 캔버스 중앙에 오도록 원본을 복사해 카드와 월드의 정렬 기준을 맞춘다.

        반환:
            pygame.Surface: 선체 중심을 중앙에 둔 투명 정사각 이미지. 결과는 캐시한다.
            원본 이미지와 파일은 변경하지 않는다.
        """

        # 선체 중심과 포신을 포함한 실제 이미지 영역을 확인한다.
        source = self._source(path)
        (center_x, center_y), _ = self._ship_geometry(path)
        visible = source.get_bounding_rect()
        half = max(
            center_x - visible.left,
            visible.right - center_x,
            center_y - visible.top,
            visible.bottom - center_y,
        )

        # 선체 중심이 정중앙에 오도록 공통 정사각 캔버스에 배치한다.
        side = max(2, math.ceil(half) * 2)
        image = pygame.Surface((side, side), pygame.SRCALPHA)
        image.blit(source, (round(side / 2 - center_x), round(side / 2 - center_y)))
        return image

    def _scaled(self, path: str, width: int, height: int) -> pygame.Surface:
        """종류에 맞는 기준 이미지를 지정한 가로·세로 크기로 변환한다.

        인자:
            path: assets/와 .png를 제외한 리소스 키.
            width: 변환할 가로 길이(px). 호출자가 1 이상의 정수로 전달한다.
            height: 변환할 세로 길이(px). 호출자가 1 이상의 정수로 전달한다.

        처리:
            우주선은 선체 중심을 맞춘 이미지를, 나머지는 전처리한 원본을 선택한다.
            smoothscale로 요청한 크기에 맞추며 원본 종횡비를 별도로 보정하지 않는다.

        반환:
            pygame.Surface: (width, height) 크기의 이미지. 리소스 키와 크기별로 캐시한다.
        """
        source = (
            self._ship_base(path) if path.startswith("ships/") else self._source(path)
        )
        return pygame.transform.smoothscale(source, (width, height))

    def _rotated(self, path: str, side: int, angle: float) -> pygame.Surface:
        """정사각형으로 크기를 맞춘 이미지를 지정한 각도로 회전한다.

        인자:
            path: assets/와 .png를 제외한 리소스 키.
            side: 회전 전 정사각 이미지의 한 변 길이(px). 1 이상의 정수이다.
            angle: 회전각(도). 양수는 반시계방향이며 여기서는 각도를 반올림하지 않는다.

        처리:
            캐시된 크기 변환 이미지를 가져와 pygame.transform.rotate로 회전한다.

        반환:
            pygame.Surface: 회전한 이미지. 회전각에 따라 캔버스가 side보다 커질 수 있다.
            리소스 키·변환 크기·각도별로 캐시한다.
        """
        return pygame.transform.rotate(self._scaled(path, side, side), angle)

    def image(self, path: str, size: float | tuple[float, float], angle: float | None=None) -> pygame.Surface:
        """리소스 키와 표시 크기로 일반 이미지를 요청한다.

        인자:
            path: assets/와 .png를 제외한 리소스 키. 진영 접미사도 허용한다.
            size: 정사각형의 한 변 길이 또는 (가로, 세로) 튜플. 단위는 px이다.
            angle: 회전각(도). 양수는 반시계방향이며 None이면 회전하지 않는다.
                size가 튜플이면 이 인자는 사용하지 않는다.

        처리:
            1) 요청 크기를 정수로 반올림하고 각 변이 최소 1px이 되도록 제한한다.
            2) 튜플 크기는 가로·세로 변환만 수행한다.
            3) 단일 크기와 회전각이 주어지면 각도를 3도 간격으로 반올림하고
               0~360도 미만으로 맞춘 뒤 크기·회전 캐시를 조회한다.

        반환:
            pygame.Surface: 요청한 크기로 변환하고 필요하면 회전한 이미지.
            캐시를 통해 같은 Surface가 다시 반환될 수 있다.
        """
        if isinstance(size, tuple):
            return self._scaled(path, max(1, round(size[0])), max(1, round(size[1])))
        side = max(1, round(size))
        if angle is None:
            return self._scaled(path, side, side)
        return self._rotated(path, side, round(angle / 3) * 3 % 360)

    def ship_image(self, path: str, diameter: float, angle: float=0) -> pygame.Surface:
        """투명 여백과 포신 길이에 영향받지 않도록 실제 선체 크기를 맞춘다.

        인자:
            path: assets/와 .png를 제외한 우주선 리소스 키. 진영 접미사도 허용한다.
            diameter: 표시할 실제 선체의 지름(px). 포신과 투명 여백은 포함하지 않는다.
            angle: 회전각(도). 기본값은 0이며 양수는 반시계방향이다.

        처리:
            원본 선체 지름과 기준 캔버스 크기의 비율로 필요한 이미지 한 변 길이를 구한다.
            image()에 크기와 각도를 전달해 정수 크기·3도 간격 회전 및 캐시를 적용한다.

        반환:
            pygame.Surface: 선체 지름을 요청값에 맞춘 우주선 이미지.
            포신·여백·회전 때문에 전체 표면 크기는 diameter보다 클 수 있다.
        """
        _, health_diameter = self._ship_geometry(path)
        side = diameter * self._ship_base(path).get_width() / health_diameter
        return self.image(path, side, angle)

    def _projectile_geometry(self, path: str) -> pygame.Rect:
        """발광 여백을 제외한 탄환 몸체의 경계 사각형을 구한다.

        인자:
            path: assets/와 .png를 제외한 탄환 리소스 키. 원본 탄환은 위쪽을 향한다.

        처리:
            알파가 100 이상인 영역의 경계를 구해 흐릿한 발광 여백을 제외한다.
            해당 영역이 비어 있으면 기본 알파 기준으로 전체 불투명 영역을 다시 구한다.

        반환:
            pygame.Rect: 원본 이미지 안의 탄체 경계(px). width를 탄체 폭 기준으로 사용한다.
            결과는 리소스 키별로 캐시한다.
        """
        source = self._source(path)
        core = source.get_bounding_rect(min_alpha=100)
        if not core.width or not core.height:
            core = source.get_bounding_rect()
        return core

    def _projectile_base(self, path: str) -> pygame.Surface:
        """탄체와 가까운 발광만 남기고 실제 탄체 중심을 기준 이미지 중앙에 맞춘다.

        인자:
            path: assets/와 .png를 제외한 탄환 리소스 키.

        처리:
            1) 탄체 경계에 폭 기준의 발광 여유를 더하고 원본 이미지 범위로 제한한다.
            2) 탄체 중심에서 선택 영역의 가장자리까지 필요한 캔버스 크기를 구한다.
            3) 선택 영역만 새 투명 표면에 복사해 물리 위치와 표시 중심을 맞춘다.

        반환:
            pygame.Surface: 탄체 중심을 중앙에 둔 투명 이미지. 각 변은 최소 2px이다.
            결과는 캐시하며 원본 이미지와 파일은 변경하지 않는다.
        """

        # 불투명한 탄체와 가까운 발광 영역만 남길 범위를 정한다.
        source = self._source(path)
        core = self._projectile_geometry(path)
        halo = max(1, round(core.width * 0.7))
        rect = core.inflate(halo * 2, halo)
        rect.clamp_ip(source.get_rect())
        rect = rect.clip(source.get_rect())
        # 실제 탄체 중심을 표면 중앙에 둬 물리 좌표와 그림을 맞춘다.
        center = (core.x + core.width / 2, core.y + core.height / 2)

        # 탄체 중심을 기준으로 새 캔버스의 가로·세로 크기를 정한다.
        half_width = math.ceil(max(center[0] - rect.left, rect.right - center[0]))
        half_height = math.ceil(max(center[1] - rect.top, rect.bottom - center[1]))
        image = pygame.Surface(
            (max(2, half_width * 2), max(2, half_height * 2)), pygame.SRCALPHA
        )
        # area 잘라내기는 런타임 표면에서만 수행하며 원본 RGBA는 그대로 둔다.
        image.blit(
            source,
            (
                round(half_width + rect.left - center[0]),
                round(half_height + rect.top - center[1]),
            ),
            rect,
        )
        return image

    def _projectile_scaled(self, path: str, diameter: int) -> pygame.Surface:
        """투명 여백 대신 실제 탄체 폭을 기준으로 탄환 크기를 변환한다.

        인자:
            path: assets/와 .png를 제외한 탄환 리소스 키.
            diameter: 표시할 탄체 폭(px). 공개 메서드에서 1 이상의 정수로 보정해 전달한다.

        처리:
            요청한 폭과 원본 탄체 폭의 비율로 기준 이미지의 가로·세로를 함께 조정한다.
            두 변을 정수로 반올림하고 최소 1px로 제한해 원본 종횡비를 유지한다.

        반환:
            pygame.Surface: 탄체 폭을 요청값에 맞춘 이미지. 리소스 키와 지름별로 캐시한다.
            발광 여백이 포함되므로 표면 전체의 폭은 diameter와 다를 수 있다.
        """
        # 탄체의 실제 폭을 기준으로 요청한 충돌 지름에 맞춰 확대·축소한다.
        base = self._projectile_base(path)
        core = self._projectile_geometry(path)
        scale = diameter / max(1, core.width)
        return pygame.transform.smoothscale(
            base,
            (
                max(1, round(base.get_width() * scale)),
                max(1, round(base.get_height() * scale)),
            ),
        )

    def _projectile_rotated(self, path: str, diameter: int, angle: float) -> pygame.Surface:
        """탄체 폭을 맞춘 탄환 이미지를 지정한 각도로 회전한다.

        인자:
            path: assets/와 .png를 제외한 탄환 리소스 키.
            diameter: 회전 전 탄체 폭(px). 1 이상의 정수이다.
            angle: 회전각(도). 원본 방향에서 양수는 반시계방향이다.

        처리:
            크기 변환 캐시에서 탄환을 가져와 회전한다. 여기서는 각도를 반올림하지 않는다.

        반환:
            pygame.Surface: 회전한 탄환 이미지. 회전에 따라 전체 캔버스 크기가 달라진다.
            리소스 키·탄체 폭·각도별로 캐시한다.
        """
        return pygame.transform.rotate(self._projectile_scaled(path, diameter), angle)

    def projectile_image(self, path: str, diameter: float, angle: float | None=None) -> pygame.Surface:
        """실제 탄체 폭과 회전각을 지정해 표시할 탄환 이미지를 요청한다.

        인자:
            path: assets/와 .png를 제외한 탄환 리소스 키. 원본 탄환은 위쪽을 향한다.
            diameter: 표시할 탄체 폭(px). 발광과 투명 여백은 포함하지 않는다.
            angle: 원본 방향을 기준으로 한 회전각(도). 양수는 반시계방향이다.
                None이면 회전하지 않으며 월드 방향에서 이 각도로의 변환은 호출자가 수행한다.

        처리:
            1) 탄체 폭을 정수로 반올림하고 최소 1px로 제한한다.
            2) 각도가 없으면 크기 변환 캐시만 사용한다.
            3) 각도가 있으면 3도 간격으로 반올림하고 0~360도 미만으로 맞춰 회전 캐시를 조회한다.

        반환:
            pygame.Surface: 탄체 폭을 기준으로 크기를 맞추고 필요하면 회전한 이미지.
            발광 여백과 회전으로 전체 표면 크기가 달라질 수 있으며 캐시 결과를 공유한다.
        """
        diameter = max(1, round(diameter))
        if angle is None:
            return self._projectile_scaled(path, diameter)
        return self._projectile_rotated(path, diameter, round(angle / 3) * 3 % 360)
